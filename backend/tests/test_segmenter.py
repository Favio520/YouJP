"""Cierre de frases por puntuacion, longitud y silencio."""

from __future__ import annotations

from youjp.asr.segmenter import SentenceSegmenter
from youjp.asr.types import Word


def w(text: str, start: float = 0.0, end: float = 0.1) -> Word:
    return Word(start=start, end=end, text=text)


def test_cierra_con_punto_japones():
    seg = SentenceSegmenter()
    closed = seg.feed([w("今日", 0, 0.3), w("は", 0.3, 0.4), w("。", 0.4, 0.5)])
    assert len(closed) == 1
    assert closed[0].text == "今日は。"
    assert closed[0].reason == "punctuation"
    assert closed[0].start == 0.0
    assert closed[0].end == 0.5
    assert not seg.has_pending


def test_ids_consecutivos():
    seg = SentenceSegmenter(first_id=7)
    a = seg.feed([w("あ"), w("。")])
    b = seg.feed([w("い"), w("！")])
    assert [s.segment_id for s in a + b] == [7, 8]


def test_cierre_por_longitud_maxima():
    """Whisper puntua el japones de forma irregular: sin este tope habria frases
    de treinta segundos sin un solo signo."""
    seg = SentenceSegmenter(max_chars=5)
    closed = seg.feed([w(c) for c in "あいうえおか"])
    assert len(closed) == 1
    assert closed[0].reason == "max_length"
    assert len(closed[0].text) == 5
    assert seg.pending_text == "か"


def test_flush_por_silencio():
    seg = SentenceSegmenter()
    seg.feed([w("あ", 1.0, 1.2), w("い", 1.2, 1.5)])
    assert seg.has_pending
    sentence = seg.flush("silence")
    assert sentence is not None
    assert sentence.reason == "silence"
    assert sentence.text == "あい"
    assert seg.flush() is None


def test_pending_start_y_reset():
    seg = SentenceSegmenter()
    assert seg.pending_start is None
    seg.feed([w("あ", 4.0, 4.2)])
    assert seg.pending_start == 4.0
    seg.reset()
    assert not seg.has_pending
    assert seg.pending_start is None


def test_signos_de_interrogacion_y_exclamacion():
    seg = SentenceSegmenter()
    assert len(seg.feed([w("あ"), w("？")])) == 1
    assert len(seg.feed([w("い"), w("！")])) == 1
