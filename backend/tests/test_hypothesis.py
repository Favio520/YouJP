"""LocalAgreement-2: nada se confirma hasta que dos pasadas coinciden."""

from __future__ import annotations

from youjp.asr.hypothesis import HypothesisBuffer
from youjp.asr.types import Word


def words(*pairs: tuple[str, float, float]) -> list[Word]:
    return [Word(start=s, end=e, text=t) for t, s, e in pairs]


def test_primera_pasada_no_confirma_nada():
    """Sin pasada anterior con la que comparar, no hay acuerdo posible."""
    buf = HypothesisBuffer()
    buf.insert(words(("今日", 0.0, 0.3), ("は", 0.3, 0.4)))
    assert buf.commit() == []
    assert buf.committed_text == ""
    assert buf.tentative_text == "今日は"


def test_confirma_el_prefijo_comun():
    buf = HypothesisBuffer()
    buf.insert(words(("今日", 0.0, 0.3), ("は", 0.3, 0.4), ("経", 0.4, 0.6)))
    buf.commit()
    # Segunda pasada: coincide en las dos primeras unidades y diverge despues.
    buf.insert(words(("今日", 0.0, 0.3), ("は", 0.3, 0.4), ("経済", 0.4, 0.8)))
    newly = buf.commit()

    assert [w.text for w in newly] == ["今日", "は"]
    assert buf.committed_text == "今日は"
    assert buf.tentative_text == "経済"
    assert buf.last_committed_time == 0.4


def test_lo_confirmado_no_se_revisa():
    """El prefijo firme no cambia aunque una pasada posterior lo contradiga:
    es justo la garantia que permite pintarlo sin miedo."""
    buf = HypothesisBuffer()
    buf.insert(words(("あ", 0.0, 0.2), ("い", 0.2, 0.4)))
    buf.commit()
    buf.insert(words(("あ", 0.0, 0.2), ("い", 0.2, 0.4)))
    buf.commit()
    assert buf.committed_text == "あい"

    buf.insert(words(("う", 0.0, 0.2), ("え", 0.2, 0.4)))
    buf.commit()
    assert buf.committed_text.startswith("あい")


def test_ignora_palabras_ya_superadas():
    buf = HypothesisBuffer()
    buf.insert(words(("あ", 0.0, 0.5), ("い", 0.5, 1.0)))
    buf.commit()
    buf.insert(words(("あ", 0.0, 0.5), ("い", 0.5, 1.0)))
    buf.commit()
    assert buf.last_committed_time == 1.0

    # Una pasada que reemite audio viejo no debe reintroducirlo.
    buf.insert(words(("あ", 0.0, 0.5), ("う", 1.0, 1.4)))
    assert buf.tentative == [] or all(w.end > 0.9 for w in buf._incoming)  # noqa: SLF001


def test_recorta_el_eco_del_prompt():
    """Whisper repite a menudo el initial_prompt al principio de su salida.

    Sin recorte, ese eco se confirmaria como texto nuevo y la frase saldria
    duplicada en pantalla.
    """
    buf = HypothesisBuffer()
    buf.insert(words(("今日", 0.0, 0.4), ("は", 0.4, 0.6)))
    buf.commit()
    buf.insert(words(("今日", 0.0, 0.4), ("は", 0.4, 0.6)))
    buf.commit()
    assert buf.committed_text == "今日は"

    # Nueva pasada que arranca repitiendo lo ya confirmado.
    buf.insert(
        words(("今日", 0.0, 0.4), ("は", 0.4, 0.6), ("天気", 0.6, 1.0))
    )
    assert buf.tentative_text in ("", "天気")
    buf.commit()
    assert buf.committed_text.count("今日") == 1


def test_normaliza_espacios_al_comparar():
    buf = HypothesisBuffer()
    buf.insert(words((" hello", 0.0, 0.3),))
    buf.commit()
    buf.insert(words(("hello ", 0.0, 0.3),))
    newly = buf.commit()
    assert len(newly) == 1


def test_reset_deja_el_buffer_limpio():
    buf = HypothesisBuffer()
    buf.insert(words(("あ", 0.0, 0.2),))
    buf.commit()
    buf.reset(at_time=12.5)
    assert buf.committed_text == ""
    assert buf.tentative_text == ""
    assert buf.last_committed_time == 12.5
