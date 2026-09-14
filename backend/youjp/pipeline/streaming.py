"""El bucle de streaming: VAD + Whisper + LocalAgreement + segmentador.

Esta clase es el corazon del sistema y no sabe nada de WebSockets ni de YouTube.
Se le empujan tramas de audio y emite dos tipos de evento:

* :class:`PartialUpdate` -- texto en curso. La parte ``committed`` ya no
  cambiara nunca; ``tentative`` se reemplaza entera en cada actualizacion.
* :class:`FinalUpdate` -- frase cerrada, lista para traducir y analizar.

En la fase 0 se ejecuta de forma sincrona desde el banco de pruebas. En la fase 1
el mismo objeto vivira en el hilo de ASR, alimentado por la cola del receptor de
WebSocket: la logica no cambia, solo quien llama a :meth:`push`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from youjp.asr.engine import WhisperEngine
from youjp.asr.hallucination import normalize, repetition_ratio, screen
from youjp.asr.hypothesis import HypothesisBuffer
from youjp.asr.segmenter import SentenceSegmenter
from youjp.asr.types import Sentence
from youjp.audio.ring import PCMRing
from youjp.audio.types import AudioFrame
from youjp.audio.vad import VADGate
from youjp.config import Settings
from youjp.obs.metrics import MetricsCollector

log = logging.getLogger(__name__)


@dataclass(slots=True)
class PartialUpdate:
    committed: str
    tentative: str
    media_start_ms: int
    wall_ms: float


@dataclass(slots=True)
class FinalUpdate:
    sentence: Sentence
    media_start_ms: int
    media_end_ms: int
    latency_ms: float
    """Desde que termino el audio de la frase hasta que se emite. Solo tiene
    sentido cuando la fuente va a ritmo real."""


@dataclass(slots=True)
class SessionStats:
    passes: int = 0
    skipped_silent: int = 0
    rejected: dict[str, int] = field(default_factory=dict)


class StreamingSession:
    def __init__(
        self,
        settings: Settings,
        engine: WhisperEngine,
        gate: VADGate,
        *,
        metrics: MetricsCollector | None = None,
        on_partial: Callable[[PartialUpdate], None] | None = None,
        on_final: Callable[[FinalUpdate], None] | None = None,
        start_media_ms: int = 0,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.gate = gate
        self.metrics = metrics or MetricsCollector()
        self.on_partial = on_partial
        self.on_final = on_final
        self.stats = SessionStats()

        self.ring = PCMRing(settings.ring_seconds, settings.sample_rate)
        self.hypothesis = HypothesisBuffer()
        self.segmenter = SentenceSegmenter(
            end_chars=settings.sentence_end_chars, max_chars=settings.max_sentence_chars
        )

        self._window_start = 0.0  # inicio absoluto de la ventana que ve Whisper
        # El ritmo de pasadas se cuenta en muestras, no en segundos: con floats,
        # un intervalo de 0,8 s se convierte en uno que alterna entre 0,8 y 0,9.
        self._min_chunk_samples = int(settings.min_chunk_s * settings.sample_rate)
        self._min_window_samples = int(0.3 * settings.sample_rate)
        self._last_pass_sample = 0
        self._last_emitted = ("", "")
        self._last_final_text = ""
        # Instante absoluto de la ultima voz detectada. -1 significa "todavia
        # ninguna". Es lo que decide si una pasada puede ejecutarse; ver
        # _window_has_speech.
        self._last_speech_at = -1.0
        self._anchor_session_s = 0.0
        self._anchor_media_ms = start_media_ms
        # La primera trama fija el ancla de verdad; start_media_ms solo sirve
        # mientras no haya llegado ninguna.
        self._needs_anchor = True
        self._t0 = time.perf_counter()

    # -- relojes -----------------------------------------------------------

    def wall_ms(self) -> float:
        """Milisegundos de reloj de pared desde el inicio de la sesion."""
        return (time.perf_counter() - self._t0) * 1000

    def media_ms(self, session_s: float) -> int:
        """Traduce tiempo de sesion a posicion dentro del video."""
        return int(self._anchor_media_ms + (session_s - self._anchor_session_s) * 1000)

    # -- entrada -----------------------------------------------------------

    def push(self, frame: AudioFrame) -> None:
        """Consume una trama de audio y ejecuta una pasada si toca."""
        if frame.discontinuity:
            self.reset()

        if self._needs_anchor:
            # El ancla se toma de la trama, nunca del mensaje de control. Ver
            # reset() para el porque.
            self._anchor_session_s = self.ring.end_time
            self._anchor_media_ms = frame.media_time_ms
            self._needs_anchor = False
            log.debug(
                "anclado: media_time=%d ms en t=%.2f s",
                frame.media_time_ms,
                self._anchor_session_s,
            )

        self.ring.write(frame.pcm)
        events = self.gate.push(frame.pcm)

        if self.gate.is_speech:
            self._last_speech_at = self.ring.end_time

        for event in events:
            if event.kind == "speech_end":
                self._last_speech_at = max(self._last_speech_at, event.time)
                # Silencio sostenido: una ultima pasada para no perder la cola de
                # la frase, y cierre inmediato en vez de esperar puntuacion.
                self._run_pass(force=True)
                self._close_on_silence()

        if self.ring.end_sample - self._last_pass_sample >= self._min_chunk_samples:
            self._run_pass()

    def finish(self) -> None:
        """Cierra la sesion: ultima pasada y emision de lo que quede pendiente."""
        self._run_pass(force=True)
        self._close_on_silence(reason="end_of_stream")

    def reset(self) -> None:
        """Descarta todo el estado tras un seek, una pausa o un cambio de velocidad.

        **No** recibe el nuevo tiempo de medio a proposito. Hay dos formas de
        enterarse de un salto -- el mensaje ``control.flush`` del content script y
        la bandera de discontinuidad en la primera trama posterior -- y llegan por
        caminos distintos, con latencias distintas y con tiempos que no coinciden.
        Medido el 14-09-2026: el flush reanclo en 80 000 ms y 92 ms despues la
        trama marcada lo piso con 20 000 ms, dejando los subtitulos desplazados un
        minuto sin que nada fallara visiblemente.

        La regla es que **las tramas son la unica fuente de verdad del tiempo de
        medio**. Un reset solo marca que hace falta reanclar; el ancla la pone la
        siguiente trama que llegue, con el valor que traiga. Asi el orden de
        llegada deja de importar y un flush sin bandera, o una bandera sin flush,
        funcionan igual de bien.
        """
        log.info("flush del pipeline; se reanclara con la siguiente trama")
        now = self.ring.end_time
        self.ring.clear(at_time=now)
        self.gate.reset(at_time=now)
        self.hypothesis.reset(at_time=now)
        self.segmenter.reset()
        self._window_start = now
        self._last_pass_sample = self.ring.end_sample
        self._needs_anchor = True
        self._last_emitted = ("", "")
        self._last_final_text = ""
        self._last_speech_at = -1.0

    # -- nucleo ------------------------------------------------------------

    def _window_has_speech(self) -> bool:
        """Si la ventana actual contiene voz detectada por el VAD.

        Medido el 14-09-2026 sobre 30 s de silencio digital absoluto:

        * large-v3-turbo emite "ご視聴ありがとうございました" con
          ``no_speech_prob = 0.000`` y ``avg_logprob = -0.143``, es decir, con
          mas confianza que sobre habla real;
        * kotoba-whisper emite "ごめん", que no repite, no comprime raro y
          es una palabra perfectamente normal.

        Ninguna senal estadistica los distingue del habla, y ninguna lista negra
        razonable contiene "ごめん". El VAD no es una optimizacion para ahorrar
        GPU: es la unica defensa que funciona, y por eso ni siquiera una pasada
        forzada puede saltarselo.
        """
        return self._last_speech_at >= self._window_start

    def _run_pass(self, *, force: bool = False) -> None:
        s = self.settings
        self._last_pass_sample = self.ring.end_sample

        # `force` adelanta la cadencia, pero nunca autoriza a transcribir
        # silencio: eso es exactamente lo que fabrica alucinaciones.
        if not self._window_has_speech() and not self.segmenter.has_pending:
            self.stats.skipped_silent += 1
            return

        pcm, window_start = self.ring.read_from(self._window_start)
        if len(pcm) < self._min_window_samples:
            return

        result = self.engine.transcribe(
            pcm,
            offset=window_start,
            prompt=self.hypothesis.prompt(s.prompt_chars, max_repeat_ratio=s.max_repeat_ratio),
        )
        self.stats.passes += 1
        self.metrics.record("whisper_processing_ms", result.inference_ms)
        self.metrics.record("whisper_rtf", result.rtf, unit="ratio")
        self.metrics.record("asr_window_s", result.audio_s, unit="s")

        raw_text = "".join(w.text for w in result.words)
        rejection = screen(
            raw_text,
            result.quality,
            max_no_speech_prob=s.max_no_speech_prob,
            min_avg_logprob=s.min_avg_logprob,
            max_repeat_ratio=s.max_repeat_ratio,
            blacklist=s.hallucination_blacklist,
        )
        if rejection is not None:
            self.stats.rejected[rejection.reason] = (
                self.stats.rejected.get(rejection.reason, 0) + 1
            )
            self.metrics.count(f"rejected_{rejection.reason}")
            log.debug("descartado (%s: %s): %r", rejection.reason, rejection.detail, raw_text)
            # Recortar tambien aqui. Un tramo largo de musica o ruido rechaza
            # todas las pasadas; sin recorte la ventana se queda pegada a los
            # 30 s y, cuando vuelve la voz, cada pasada cuesta segundos en vez
            # de milisegundos. Medido: 2 185 ms sobre 45 s de ruido rosa.
            self._maybe_trim()
            return

        self.hypothesis.insert(result.words)
        newly = self.hypothesis.commit()
        if newly:
            self.metrics.count("committed_words", len(newly))

        self._emit_partial()

        for sentence in self.segmenter.feed(newly):
            self._emit_final(sentence)

        self._maybe_trim()

    def _close_on_silence(self, reason: str = "silence") -> None:
        sentence = self.segmenter.flush(reason)
        if sentence is not None:
            self._emit_final(sentence)

    def _maybe_trim(self) -> None:
        """Recorta la ventana por el ultimo punto confirmado.

        Sin esto la ventana crece hasta los 30 s y el tiempo de inferencia sube
        con ella hasta romper el presupuesto de latencia.
        """
        s = self.settings
        if self.ring.end_time - self._window_start < s.buffer_trim_s:
            return
        cut = self.hypothesis.last_committed_time
        if cut <= self._window_start:
            # Nada confirmado en toda la ventana: probablemente ruido. Se recorta
            # igualmente para no quedarse atascado con una ventana enorme.
            cut = self.ring.end_time - s.min_chunk_s
        self._window_start = cut
        self.ring.trim_before(cut)
        self.hypothesis.drop_committed_before(cut - 30.0)
        self.metrics.count("buffer_trims")
        log.debug("ventana recortada en t=%.2f s", cut)

    # -- emision -----------------------------------------------------------

    def _emit_partial(self) -> None:
        committed = self.segmenter.pending_text
        tentative = self.hypothesis.tentative_text
        if (committed, tentative) == self._last_emitted:
            return
        self._last_emitted = (committed, tentative)
        if not committed and not tentative:
            return
        self.metrics.count("partial_transcripts")
        if self.on_partial is not None:
            start = self.segmenter.pending_start
            if start is None:
                start = self.ring.end_time
            self.on_partial(
                PartialUpdate(
                    committed=committed,
                    tentative=tentative,
                    media_start_ms=self.media_ms(start),
                    wall_ms=self.wall_ms(),
                )
            )

    def _emit_final(self, sentence: Sentence) -> None:
        # Ultima red antes de pantalla. Los filtros de `screen` miran la pasada
        # entera, donde un bucle queda diluido entre texto legitimo; aqui se mira
        # la frase concreta, que es lo que veria el estudiante.
        if repetition_ratio(sentence.text) > self.settings.max_repeat_ratio:
            self.stats.rejected["repetition_final"] = (
                self.stats.rejected.get("repetition_final", 0) + 1
            )
            self.metrics.count("rejected_repetition_final")
            log.debug("frase repetitiva descartada: %r", sentence.text)
            return

        normalized = normalize(sentence.text)
        if normalized and normalized == self._last_final_text:
            self.stats.rejected["duplicate_final"] = (
                self.stats.rejected.get("duplicate_final", 0) + 1
            )
            self.metrics.count("rejected_duplicate_final")
            log.debug("frase duplicada descartada: %r", sentence.text)
            return
        self._last_final_text = normalized

        latency = self.wall_ms() - sentence.end * 1000
        self.metrics.count("final_transcripts")
        self.metrics.record("speech_latency_ms", latency)
        self._last_emitted = ("", "")
        if self.on_final is not None:
            self.on_final(
                FinalUpdate(
                    sentence=sentence,
                    media_start_ms=self.media_ms(sentence.start),
                    media_end_ms=self.media_ms(sentence.end),
                    latency_ms=latency,
                )
            )
