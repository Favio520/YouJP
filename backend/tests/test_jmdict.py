"""Consulta del diccionario.

Se salta si la base no está construida: son 130 MB de descarga y no tiene
sentido exigirlos para ejecutar el resto de la suite.
"""

from __future__ import annotations

import time

import pytest

from youjp.config import get_settings
from youjp.dict.jmdict import Dictionary

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.dict_db.is_file(),
    reason="falta data/youjp.sqlite3 (fetch_dicts.py + build_db)",
)


@pytest.fixture(scope="module")
def dic() -> Dictionary:
    return Dictionary(settings.dict_db, max_senses=settings.max_senses)


def test_palabra_comun_con_espanol(dic: Dictionary):
    entry = dic.lookup("影響", sudachi_pos="名詞")
    assert entry is not None
    assert entry.headword == "影響"
    assert "えいきょう" in entry.kana_forms
    assert entry.common is True
    assert entry.has_spanish
    assert any("influencia" in g.lower() for s in entry.senses for g in s.glosses_es)


def test_el_ingles_queda_de_respaldo(dic: Dictionary):
    """El español de JMdict cubre el 16 % de las entradas. Sin respaldo, una
    palabra fuera de esa lista no tendría tarjeta; con él, solo pierde la
    glosa."""
    entry = dic.lookup("証券会社", sudachi_pos="名詞")
    assert entry is not None
    assert any(s.glosses_en for s in entry.senses)


def test_palabra_inexistente(dic: Dictionary):
    assert dic.lookup("これは単語ではないよ") is None


def test_la_lectura_desempata_homografos(dic: Dictionary):
    """開く es 「ひらく」 y 「あく」 según el contexto. Sudachi sabe cuál es, y
    pasar la lectura evita ofrecer la entrada equivocada."""
    hiraku = dic.lookup("開く", reading="ヒラク")
    aku = dic.lookup("開く", reading="アク")
    assert hiraku is not None and aku is not None
    # Con lecturas distintas tiene que llegarse a entradas distintas.
    assert hiraku.id != aku.id


def test_se_acotan_las_acepciones(dic: Dictionary):
    """JMdict llega a veinte acepciones en palabras comunes. En una tarjeta
    sobre un vídeo, eso no se lee."""
    entry = dic.lookup("とる")
    assert entry is not None
    assert len(entry.senses) <= settings.max_senses


def test_las_acepciones_en_espanol_van_primero(dic: Dictionary):
    entry = dic.lookup("見る", sudachi_pos="動詞")
    assert entry is not None
    con_es = [i for i, s in enumerate(entry.senses) if s.has_spanish]
    sin_es = [i for i, s in enumerate(entry.senses) if not s.has_spanish]
    if con_es and sin_es:
        assert max(con_es) < min(sin_es)


def test_informacion_de_kanji(dic: Dictionary):
    kanji = dic.kanji("影")
    assert kanji is not None
    assert kanji.strokes == 15
    assert "エイ" in kanji.on_yomi
    assert "かげ" in kanji.kun_yomi


def test_kanji_inexistente(dic: Dictionary):
    assert dic.kanji("a") is None


def test_la_consulta_es_lo_bastante_rapida(dic: Dictionary):
    """La tarjeta tiene que aparecer en el mismo fotograma del clic.

    Regresión medida: la primera versión puntuaba las candidatas cargándolas
    enteras, tres consultas cada una, y tardaba 13,7 ms. Una frase de quince
    palabras necesita treinta consultas, así que eso eran 400 ms de retraso
    perfectamente visible.
    """
    palabras = ["影響", "話す", "経済", "今日", "勉強"]
    for palabra in palabras:  # calentar
        dic.lookup(palabra)

    t0 = time.perf_counter()
    for _ in range(20):
        for palabra in palabras:
            dic.lookup(palabra, sudachi_pos="名詞")
    ms = (time.perf_counter() - t0) * 1000 / 100

    assert ms < 2.0, f"{ms:.2f} ms por consulta"


def test_la_base_declara_lo_que_contiene(dic: Dictionary):
    stats = dic.stats()
    assert int(stats["entries"]) > 100_000
    assert int(stats["kanji"]) > 5_000
