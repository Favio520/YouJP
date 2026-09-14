"""Motor de reconocimiento sobre faster-whisper / CTranslate2.

Envuelve el modelo para que el resto del pipeline trabaje con tiempos absolutos
de sesion y no con los tiempos relativos a la ventana que devuelve Whisper.

Tambien concentra aqui los ajustes que importan en streaming y que no son los
que se usarian en transcripcion por lotes:

* ``beam_size=1`` -- un beam de 5 multiplica por 2-3 el tiempo de decodificacion
  para una ganancia que no se aprecia en un subtitulo.
* ``condition_on_previous_text=False`` -- realimentar el texto anterior dispara
  bucles de alucinacion. El contexto se pasa acotado por ``initial_prompt``.
* ``temperature=0.0`` -- desactiva la escalera de reintentos, que en el camino
  caliente solo anade latencia impredecible.
* ``vad_filter=False`` -- el VAD ya ha decidido antes; hacerlo dos veces es
  gastar CPU y descuadrar los tiempos.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from youjp.asr.capabilities import supports_word_timestamps
from youjp.asr.types import QualitySignals, TranscribeResult, Word
from youjp.config import Settings
from youjp.cuda_setup import enable_cuda_dlls

log = logging.getLogger(__name__)


def interpolate_words(text: str, start: float, end: float) -> list[Word]:
    """Reparte el texto de un segmento en caracteres con tiempos proporcionales.

    Se usa cuando el modelo no puede dar marcas por palabra. LocalAgreement
    compara *texto*, no tiempos: lo que necesita es granularidad fina para que el
    prefijo confirmado avance de forma suave. Los tiempos solo sirven para
    ordenar y para anclar el subtitulo al video, asi que interpolarlos
    linealmente cuesta unas decimas de sincronia pero conserva el streaming.

    La alternativa -- una sola unidad por segmento -- haria que los parciales se
    actualizaran cada 5-10 s, que es tanto como no tener parciales.
    """
    text = text.strip()
    if not text:
        return []
    step = (end - start) / len(text)
    return [
        Word(start=start + i * step, end=start + (i + 1) * step, text=ch)
        for i, ch in enumerate(text)
    ]


class WhisperEngine:
    """Carga perezosa del modelo: el objeto se puede construir sin tocar la GPU."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._load_ms: float | None = None
        self.word_timestamps: bool = True
        """Se resuelve al cargar. Ver :mod:`youjp.asr.capabilities`."""

    # -- ciclo de vida -----------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        enable_cuda_dlls()
        from faster_whisper import WhisperModel  # import tardio: carga DLLs

        s = self.settings
        # La sonda carga el modelo en un proceso aparte, asi que tiene que
        # ejecutarse antes que nosotros: nunca dos copias a la vez en la VRAM.
        if s.asr_word_timestamps == "auto":
            self.word_timestamps = supports_word_timestamps(
                s.asr_model, s.asr_device, s.asr_compute_type, s.models_dir
            )
        else:
            self.word_timestamps = s.asr_word_timestamps == "on"

        t0 = time.perf_counter()
        log.info(
            "cargando ASR %s en %s (%s, word_timestamps=%s)...",
            s.asr_model,
            s.asr_device,
            s.asr_compute_type,
            self.word_timestamps,
        )
        try:
            self._model = WhisperModel(
                s.asr_model,
                device=s.asr_device,
                compute_type=s.asr_compute_type,
                download_root=str(s.models_dir / "whisper"),
                num_workers=1,
            )
        except Exception as exc:  # noqa: BLE001 - se reenvia con contexto util
            raise RuntimeError(
                f"no se pudo cargar el modelo ASR {s.asr_model!r} en "
                f"{s.asr_device}/{s.asr_compute_type}. Causas habituales: falta el "
                f"extra de CUDA (uv sync --extra cuda), no hay VRAM libre, o el "
                f"nombre del modelo no existe en esta version de faster-whisper. "
                f"Error original: {exc}"
            ) from exc
        self._load_ms = (time.perf_counter() - t0) * 1000
        log.info("ASR listo en %.0f ms", self._load_ms)

    def unload(self) -> None:
        """Libera la VRAM. Es lo que permite el cambio a modo estudio, donde el
        LLM ocupa la GPU y el ASR no hace falta."""
        if self._model is None:
            return
        del self._model
        self._model = None
        import gc

        gc.collect()
        log.info("ASR descargado")

    def warmup(self, seconds: float = 2.0) -> float:
        """Primera inferencia sobre silencio, para pagar la inicializacion de
        cuBLAS antes de medir nada. Devuelve los ms que ha costado."""
        self.load()
        pcm = np.zeros(int(seconds * self.settings.sample_rate), dtype=np.float32)
        t0 = time.perf_counter()
        self.transcribe(pcm, offset=0.0)
        ms = (time.perf_counter() - t0) * 1000
        log.info("calentamiento: %.0f ms", ms)
        return ms

    # -- inferencia --------------------------------------------------------

    def transcribe(
        self, pcm: np.ndarray, *, offset: float = 0.0, prompt: str = ""
    ) -> TranscribeResult:
        """Transcribe una ventana de audio.

        Parameters
        ----------
        pcm:
            float32 mono a ``settings.sample_rate``.
        offset:
            Instante absoluto de ``pcm[0]``. Todas las marcas temporales salen ya
            desplazadas, de modo que quien llame nunca maneja tiempos relativos.
        prompt:
            Texto confirmado reciente, como ``initial_prompt``.
        """
        self.load()
        s = self.settings
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)

        window_s = len(pcm) / s.sample_rate
        # Cota dura de generacion: un bucle de repeticion llegaria si no a los
        # 448 tokens que admite Whisper por ventana, y la pasada pasa de 400 ms
        # a 8 s. El suelo evita estrangular ventanas muy cortas.
        max_new_tokens = max(48, int(window_s * s.asr_max_tokens_per_second))

        t0 = time.perf_counter()
        segments, _info = self._model.transcribe(
            pcm,
            language=s.asr_language,
            task="transcribe",
            beam_size=s.asr_beam_size,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=prompt or None,
            word_timestamps=self.word_timestamps,
            vad_filter=False,
            no_repeat_ngram_size=s.asr_no_repeat_ngram_size,
            repetition_penalty=s.asr_repetition_penalty,
            max_new_tokens=max_new_tokens,
        )

        words: list[Word] = []
        logprobs: list[float] = []
        no_speech: list[float] = []
        compressions: list[float] = []

        # transcribe() devuelve un generador: el trabajo real ocurre al consumirlo.
        for seg in segments:
            logprobs.append(seg.avg_logprob)
            no_speech.append(seg.no_speech_prob)
            compressions.append(seg.compression_ratio)
            if not seg.words:
                # O el modelo no admite marcas por palabra, o el segmento es tan
                # corto que no ha producido ninguna. En ambos casos se reparte el
                # texto por caracteres para no perder granularidad.
                words.extend(
                    interpolate_words(seg.text, offset + seg.start, offset + seg.end)
                )
                continue
            for w in seg.words:
                words.append(
                    Word(
                        start=offset + w.start,
                        end=offset + w.end,
                        text=w.word,
                        probability=w.probability,
                    )
                )

        inference_ms = (time.perf_counter() - t0) * 1000
        quality = QualitySignals(
            no_speech_prob=max(no_speech) if no_speech else 0.0,
            avg_logprob=min(logprobs) if logprobs else 0.0,
            compression_ratio=max(compressions) if compressions else 1.0,
        )
        return TranscribeResult(
            words=words,
            quality=quality,
            inference_ms=inference_ms,
            audio_s=len(pcm) / s.sample_rate,
        )
