"""El bucle completo, con un motor y un VAD de mentira.

No hace falta GPU ni modelos: lo que se comprueba aqui es el pegamento, que es
justo donde estan los fallos dificiles de ver (ventanas que no se recortan,
parciales emitidos dos veces, frases que se pierden al cerrar la sesion).
"""

from __future__ import annotations

import numpy as np
import pytest

from youjp.asr.types import QualitySignals, TranscribeResult, Word
from youjp.audio.types import AudioFrame
from youjp.audio.vad import SpeechEvent
from youjp.config import Settings
from youjp.pipeline.streaming import FinalUpdate, PartialUpdate, StreamingSession

SR = 16_000


class FakeEngine:
    """Devuelve hipotesis predefinidas, una por pasada."""

    def __init__(self, script: list[list[tuple[str, float, float]]]) -> None:
        self.script = script
        self.calls = 0
        self.prompts: list[str] = []

    def transcribe(self, pcm, *, offset: float = 0.0, prompt: str = "") -> TranscribeResult:
        self.prompts.append(prompt)
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        words = [Word(start=s, end=e, text=t) for t, s, e in self.script[index]]
        return TranscribeResult(
            words=words,
            quality=QualitySignals(no_speech_prob=0.02, avg_logprob=-0.3),
            inference_ms=12.0,
            audio_s=len(pcm) / SR,
        )


class FakeGate:
    """VAD controlable: habla siempre salvo que se le pidan silencios."""

    def __init__(self, silence_after: set[int] | None = None) -> None:
        self.is_speech = True
        self.silence_after = silence_after or set()
        self.pushes = 0
        self.resets = 0

    def push(self, pcm) -> list[SpeechEvent]:
        self.pushes += 1
        if self.pushes in self.silence_after:
            self.is_speech = False
            return [SpeechEvent("speech_end", self.pushes * 0.1)]
        return []

    def reset(self, at_time: float | None = None) -> None:
        self.resets += 1
        self.is_speech = True


def settings_for_test(**overrides) -> Settings:
    base = {
        "min_chunk_s": 0.2,
        "buffer_trim_s": 2.0,
        "vad_model": "no-usado.onnx",
        "max_sentence_chars": 60,
    }
    base.update(overrides)
    return Settings(**base)


def frames(count: int, frame_ms: int = 100) -> list[AudioFrame]:
    samples = SR * frame_ms // 1000
    return [
        AudioFrame(
            seq=i,
            media_time_ms=i * frame_ms,
            capture_ms=i * frame_ms,
            pcm=np.full(samples, 0.1, dtype=np.float32),
        )
        for i in range(count)
    ]


def test_confirma_y_cierra_una_frase():
    s = settings_for_test()
    # Dos pasadas identicas: LocalAgreement confirma todo el prefijo comun.
    hypothesis = [("今日", 0.0, 0.3), ("は", 0.3, 0.5), ("。", 0.5, 0.6)]
    engine = FakeEngine([hypothesis, hypothesis, hypothesis])
    gate = FakeGate()
    finals: list[FinalUpdate] = []

    session = StreamingSession(s, engine, gate, on_final=finals.append)
    for frame in frames(8):
        session.push(frame)
    session.finish()

    assert len(finals) == 1
    assert finals[0].sentence.text == "今日は。"
    assert finals[0].sentence.reason == "punctuation"


def test_la_primera_pasada_no_emite_nada_en_firme():
    s = settings_for_test(min_chunk_s=10.0)  # una sola pasada en toda la sesion
    engine = FakeEngine([[("あ", 0.0, 0.3)]])
    finals: list[FinalUpdate] = []
    session = StreamingSession(s, engine, FakeGate(), on_final=finals.append)

    for frame in frames(3):
        session.push(frame)

    assert engine.calls == 0 or not finals


def test_silencio_cierra_la_frase_sin_puntuacion():
    s = settings_for_test()
    hypothesis = [("あ", 0.0, 0.3), ("い", 0.3, 0.5)]
    engine = FakeEngine([hypothesis] * 6)
    gate = FakeGate(silence_after={5})
    finals: list[FinalUpdate] = []

    session = StreamingSession(s, engine, gate, on_final=finals.append)
    for frame in frames(8):
        session.push(frame)

    assert finals, "el silencio deberia haber cerrado la frase"
    assert finals[0].sentence.reason == "silence"


def test_los_parciales_no_se_repiten():
    """Reemitir el mismo parcial hace parpadear el overlay sin aportar nada."""
    s = settings_for_test()
    hypothesis = [("あ", 0.0, 0.3), ("い", 0.3, 0.5)]
    engine = FakeEngine([hypothesis] * 10)
    partials: list[PartialUpdate] = []

    session = StreamingSession(s, engine, FakeGate(), on_partial=partials.append)
    for frame in frames(12):
        session.push(frame)

    textos = [(p.committed, p.tentative) for p in partials]
    assert len(textos) == len(set(textos))


def test_no_se_ejecuta_whisper_sobre_silencio():
    """El VAD es el portero: sin voz ni texto a medias, no se toca la GPU."""
    s = settings_for_test()
    engine = FakeEngine([[]])
    gate = FakeGate()
    gate.is_speech = False

    session = StreamingSession(s, engine, gate)
    for frame in frames(10):
        session.push(frame)

    assert engine.calls == 0
    assert session.stats.skipped_silent > 0


def test_ni_una_pasada_forzada_transcribe_silencio():
    """El agujero que destapo el banco el 14-09-2026.

    finish() y el cierre por silencio ejecutaban una pasada forzada que se
    saltaba el VAD. Sobre una sesion sin una sola palabra, eso mete silencio
    puro en Whisper -- que es justo donde turbo emite
    "ご視聴ありがとうございました" con no_speech_prob = 0,000, y kotoba
    emite "ごめん", que ningun filtro estadistico ni lista negra puede atrapar.
    """
    s = settings_for_test()
    engine = FakeEngine([[("ごめん", 0.0, 0.5)]] * 10)
    gate = FakeGate()
    gate.is_speech = False

    session = StreamingSession(s, engine, gate)
    for frame in frames(12):
        session.push(frame)
    session.finish()

    assert engine.calls == 0, "se transcribio silencio"
    assert session.stats.skipped_silent > 0


def test_la_ventana_se_recorta():
    """Sin recorte la ventana crece hasta 30 s y la inferencia se dispara."""
    s = settings_for_test(buffer_trim_s=0.5)
    hypothesis = [("あ", 0.0, 0.3), ("い", 0.3, 0.5)]
    engine = FakeEngine([hypothesis] * 20)

    session = StreamingSession(s, engine, FakeGate())
    for frame in frames(20):
        session.push(frame)

    assert session.metrics.counter("buffer_trims") > 0
    assert session.ring.duration < s.ring_seconds


def test_cadencia_de_pasadas_regular():
    """El intervalo entre pasadas tiene que ser exacto.

    Comparando en segundos, ``0.6 - 0.4`` no da ``0.2`` y la cadencia alterna
    entre dos y tres tramas. En vivo eso son ~100 ms de jitter aleatorio en la
    latencia, dificiles de atribuir despues. Se compara en muestras enteras.
    """
    s = settings_for_test()  # min_chunk 0,2 s = 2 tramas de 100 ms
    engine = FakeEngine([[("あ", 0.0, 0.3)]] * 30)

    session = StreamingSession(s, engine, FakeGate())
    for frame in frames(20):
        session.push(frame)

    # Trama 1 dispara una pasada que se descarta por ventana corta (<0,3 s);
    # a partir de ahi, una pasada real cada dos tramas: 3, 5, 7 ... 19.
    assert engine.calls == 9


def test_el_prompt_lleva_el_texto_confirmado():
    s = settings_for_test()
    hypothesis = [("今日", 0.0, 0.3), ("は", 0.3, 0.5)]
    engine = FakeEngine([hypothesis] * 6)

    session = StreamingSession(s, engine, FakeGate())
    for frame in frames(8):
        session.push(frame)

    assert any("今日" in p for p in engine.prompts)


def test_seek_reancla_el_tiempo_de_medio():
    s = settings_for_test()
    engine = FakeEngine([[("あ", 0.0, 0.3)]] * 6)
    session = StreamingSession(s, engine, FakeGate(), start_media_ms=0)

    for frame in frames(4):
        session.push(frame)

    salto = AudioFrame(
        seq=99,
        media_time_ms=600_000,
        capture_ms=400,
        pcm=np.zeros(1600, dtype=np.float32),
        discontinuity=True,
    )
    session.push(salto)

    assert session.media_ms(session.ring.end_time) == pytest.approx(600_000, abs=200)
    assert not session.segmenter.has_pending


def test_el_flush_y_la_bandera_no_se_pisan():
    """El bug del 14-09-2026, encontrado con el cliente de repeticion.

    Hay dos formas de enterarse de un seek: el mensaje ``control.flush`` del
    content script y la bandera de discontinuidad en la primera trama posterior.
    Llegaban por caminos distintos y cada una reanclaba con su propio tiempo: el
    flush ponia 80 000 ms y 92 ms despues la trama lo pisaba con 20 000 ms,
    dejando los subtitulos desplazados un minuto sin que nada fallara a la vista.

    Ahora las tramas son la unica fuente de verdad, asi que el orden de llegada
    no importa. Aqui se comprueban los dos ordenes posibles.
    """
    nueva_pos = 600_000

    def salto(seq: int) -> AudioFrame:
        return AudioFrame(
            seq=seq, media_time_ms=nueva_pos, capture_ms=0,
            pcm=np.zeros(1600, dtype=np.float32), discontinuity=True,
        )

    # Orden A: primero el mensaje de control, luego la trama marcada.
    s = settings_for_test()
    a = StreamingSession(s, FakeEngine([[]]), FakeGate())
    for f in frames(4):
        a.push(f)
    a.reset()
    a.push(salto(99))
    assert a.media_ms(a.ring.end_time) == pytest.approx(nueva_pos, abs=200)

    # Orden B: primero la trama marcada, luego el mensaje de control con retraso.
    b = StreamingSession(s, FakeEngine([[]]), FakeGate())
    for f in frames(4):
        b.push(f)
    b.push(salto(99))
    b.reset()
    b.push(AudioFrame(
        seq=100, media_time_ms=nueva_pos + 100, capture_ms=0,
        pcm=np.zeros(1600, dtype=np.float32),
    ))
    assert b.media_ms(b.ring.end_time) == pytest.approx(nueva_pos + 100, abs=200)


def test_descarta_texto_de_la_lista_negra():
    gracias = "ご視聴ありがとうございました"
    s = settings_for_test(hallucination_blacklist=(gracias,))
    engine = FakeEngine([[(gracias, 0.0, 1.5)]] * 6)
    finals: list[FinalUpdate] = []

    session = StreamingSession(s, engine, FakeGate(), on_final=finals.append)
    for frame in frames(10):
        session.push(frame)
    session.finish()

    assert finals == []
    assert session.stats.rejected.get("blacklist", 0) > 0


def test_descarta_frases_repetitivas():
    """Tercera linea contra los bucles de repeticion.

    `screen` mira la pasada entera, donde un bucle queda diluido entre texto
    legitimo y puede colarse; aqui se mira la frase concreta, que es lo que
    veria el estudiante. Caso real del 14-09-2026: turbo repitiendo
    "私はサンドルオンを使って、" hasta agotar la ventana.
    """
    s = settings_for_test(max_sentence_chars=40)
    bucle = "私はサンドルオンを使って、"
    hypothesis = [(bucle * 4, 0.0, 4.0)]
    engine = FakeEngine([hypothesis] * 8)
    finals: list[FinalUpdate] = []

    session = StreamingSession(s, engine, FakeGate(), on_final=finals.append)
    for frame in frames(10):
        session.push(frame)
    session.finish()

    assert finals == []
    assert any("repetition" in motivo for motivo in session.stats.rejected), (
        f"ninguna capa freno el bucle: {session.stats.rejected}"
    )


def test_la_capa_de_frase_frena_lo_que_la_de_pasada_diluye():
    """`screen` mira la pasada entera: un bucle rodeado de texto legitimo baja
    del umbral y se cuela. La comprobacion por frase mira lo que realmente
    veria el estudiante."""
    from youjp.asr.types import Sentence, Word

    s = settings_for_test()
    session = StreamingSession(s, FakeEngine([[]]), FakeGate(), on_final=lambda u: emitidas.append(u))
    emitidas: list[FinalUpdate] = []

    bucle = "私はサンドルオンを使って、" * 5
    session._emit_final(  # noqa: SLF001
        Sentence(1, bucle, 0.0, 5.0, [Word(0.0, 5.0, bucle)], "max_length")
    )
    assert emitidas == []
    assert session.stats.rejected.get("repetition_final", 0) == 1

    buena = "今日は経済への影響について話します。"
    session._emit_final(  # noqa: SLF001
        Sentence(2, buena, 5.0, 8.0, [Word(5.0, 8.0, buena)], "punctuation")
    )
    assert len(emitidas) == 1


def test_descarta_frases_duplicadas_consecutivas():
    s = settings_for_test(max_sentence_chars=3)
    frase = [("あ", 0.0, 0.3), ("い", 0.3, 0.5), ("う", 0.5, 0.7)]
    engine = FakeEngine([frase] * 12)
    finals: list[FinalUpdate] = []

    session = StreamingSession(s, engine, FakeGate(), on_final=finals.append)
    for frame in frames(14):
        session.push(frame)
    session.finish()

    textos = [f.sentence.text for f in finals]
    assert len(textos) == len(set(textos)), f"frases duplicadas emitidas: {textos}"


def test_el_prompt_no_realimenta_un_bucle():
    """Devolverle al modelo el bucle que acaba de producir lo perpetua."""
    from youjp.asr.hypothesis import HypothesisBuffer
    from youjp.asr.types import Word

    buf = HypothesisBuffer()
    bucle = "ありがとう"
    palabras = [Word(i * 0.1, (i + 1) * 0.1, bucle) for i in range(12)]
    buf.insert(palabras)
    buf.commit()
    buf.insert(palabras)
    buf.commit()

    assert buf.committed_text != ""
    assert buf.prompt(180, max_repeat_ratio=0.5) == ""


def test_la_ventana_se_recorta_aunque_todo_se_rechace():
    """Un tramo largo de musica o ruido rechaza todas las pasadas.

    Si el recorte solo ocurriera en el camino feliz, la ventana se quedaria
    pegada a los 30 s y la primera pasada tras volver la voz costaria segundos.
    Medido en el banco: 2 185 ms sobre 45 s de ruido rosa frente a 94 ms sobre
    silencio.
    """
    gracias = "ご視聴ありがとうございました"
    s = settings_for_test(buffer_trim_s=0.5, hallucination_blacklist=(gracias,))
    engine = FakeEngine([[(gracias, 0.0, 1.5)]] * 30)

    session = StreamingSession(s, engine, FakeGate())
    for frame in frames(20):
        session.push(frame)

    assert session.stats.rejected.get("blacklist", 0) > 0
    assert session.metrics.counter("buffer_trims") > 0
