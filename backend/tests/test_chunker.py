"""Reconstrucción de cadenas de conjugación a partir de morfemas de Sudachi.

Estos tests usan el Sudachi real: lo que se comprueba es que la regla de
agrupación case con lo que el analizador devuelve de verdad, y eso no se puede
simular con dobles sin acabar probando la simulación.
"""

from __future__ import annotations

import pytest

from youjp.nlp.chunker import AMBIGUOUS_LABEL, chunk
from youjp.nlp.tokenizer import get_tokenizer

sudachipy = pytest.importorskip("sudachipy", reason="falta sudachipy")


@pytest.fixture(scope="module")
def tokenizer():
    tok = get_tokenizer()
    tok.load()
    return tok


def analizar(tokenizer, texto: str):
    return chunk(tokenizer.tokenize(texto, mode="C"))


def test_verbo_sin_conjugar(tokenizer):
    trozos = analizar(tokenizer, "食べる")
    assert len(trozos) == 1
    assert trozos[0].lemma == "食べる"
    assert trozos[0].chain == []


def test_pasado_formal(tokenizer):
    """食べました -> 食べる, formal, pasado."""
    trozos = analizar(tokenizer, "食べました")
    assert len(trozos) == 1
    assert trozos[0].surface == "食べました"
    assert trozos[0].lemma == "食べる"
    assert trozos[0].chain == ["formal", "pasado"]


def test_causativo_pasivo_formal_pasado(tokenizer):
    """El ejemplo que motivó todo esto: 食べさせられました.

    Cinco morfemas sueltos que tienen que volver a ser una sola palabra con su
    historia completa.
    """
    trozos = analizar(
        tokenizer, "食べさせられました"
    )
    assert len(trozos) == 1
    trozo = trozos[0]
    assert trozo.lemma == "食べる"
    assert trozo.chain[0] == "causativo"
    assert AMBIGUOUS_LABEL in trozo.chain
    assert "formal" in trozo.chain
    assert trozo.chain[-1] == "pasado"


def test_relu_se_marca_como_ambiguo(tokenizer):
    """れる/られる es pasivo, potencial o respetuoso y ninguna regla morfológica
    lo distingue. Elegir uno por el estudiante sería enseñar mal."""
    trozos = analizar(tokenizer, "食べられる")
    assert AMBIGUOUS_LABEL in trozos[0].chain


def test_progresivo(tokenizer):
    trozos = analizar(tokenizer, "食べている")
    assert trozos[0].lemma == "食べる"
    assert "progresivo" in trozos[0].chain


def test_negativo_pasado(tokenizer):
    trozos = analizar(tokenizer, "行かなかった")
    assert trozos[0].lemma == "行く"
    assert "negativo" in trozos[0].chain
    assert "pasado" in trozos[0].chain


def test_las_particulas_de_caso_no_se_pegan(tokenizer):
    """は y を son marcas gramaticales independientes: el estudiante tiene que
    verlas por separado, no escondidas dentro del verbo."""
    trozos = analizar(tokenizer, "ご飯を食べる")
    superficies = [t.surface for t in trozos]
    assert "を" in superficies
    assert "ご飯" in superficies


def test_la_particula_conjuntiva_si_se_pega(tokenizer):
    """て en 食べて sí forma parte de la forma verbal."""
    trozos = analizar(tokenizer, "食べてください")
    assert trozos[0].surface.startswith("食べて")


def test_frase_completa(tokenizer):
    frase = (
        "今日は経済への影響に"
        "ついて話します。"
    )
    trozos = analizar(tokenizer, frase)
    # El texto reconstruido tiene que ser idéntico al original: si el chunker
    # pierde o duplica un carácter, los índices del overlay se desplazan y los
    # clics caen en la palabra equivocada.
    assert "".join(t.surface for t in trozos) == frase
    lemas = [t.lemma for t in trozos]
    assert "影響" in lemas
    assert "話す" in lemas


def test_los_indices_cubren_el_texto_sin_huecos(tokenizer):
    frase = "行かなければならないと思います"
    trozos = analizar(tokenizer, frase)
    assert trozos[0].begin == 0
    assert trozos[-1].end == len(frase)
    for a, b in zip(trozos[:-1], trozos[1:], strict=True):
        assert a.end == b.begin
        assert frase[a.begin : a.end] == a.surface
