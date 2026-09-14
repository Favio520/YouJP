"""Reparto de tiempos por caracter cuando el modelo no da marcas por palabra.

Necesario porque kotoba-whisper-v2.0-faster lleva los ``alignment_heads`` de
large-v3 (capas 7 a 25) sobre un decodificador destilado de 2 capas: pedirle
``word_timestamps`` mata el proceso con 0xC0000005.
"""

from __future__ import annotations

import pytest

from youjp.asr.engine import interpolate_words
from youjp.asr.hypothesis import HypothesisBuffer

FRASE = "今日は経済への影響"  # 9 caracteres


def test_una_unidad_por_caracter():
    words = interpolate_words(FRASE, 10.0, 13.6)
    assert len(words) == len(FRASE)
    assert "".join(w.text for w in words) == FRASE


def test_los_tiempos_cubren_el_segmento_sin_huecos():
    words = interpolate_words(FRASE, 10.0, 13.6)
    assert words[0].start == pytest.approx(10.0)
    assert words[-1].end == pytest.approx(13.6)
    for a, b in zip(words[:-1], words[1:], strict=True):
        assert a.end == pytest.approx(b.start)
        assert a.end > a.start


def test_texto_vacio_o_en_blanco():
    assert interpolate_words("", 0.0, 1.0) == []
    assert interpolate_words("   \n ", 0.0, 1.0) == []


def test_conserva_la_granularidad_para_localagreement():
    """El objetivo de interpolar no es la precision temporal, es que el prefijo
    confirmado siga avanzando caracter a caracter. Con una sola unidad por
    segmento los parciales se actualizarian cada 5-10 s."""
    buf = HypothesisBuffer()
    buf.insert(interpolate_words(FRASE, 0.0, 3.6))
    buf.commit()
    # Segunda pasada: el modelo ha oido dos caracteres mas.
    buf.insert(interpolate_words(FRASE + "につ", 0.0, 4.4))
    newly = buf.commit()

    assert len(newly) == len(FRASE)
    assert buf.committed_text == FRASE
    assert buf.tentative_text == "につ"
