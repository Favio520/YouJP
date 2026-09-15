"""Conversión de kana a hiragana y a rōmaji.

Determinista y sin modelo: la lectura ya viene de Sudachi, aquí solo se cambia de
alfabeto. Se usa Hepburn, que es lo que aparece en los materiales de estudio de
japonés para hispanohablantes.
"""

from __future__ import annotations

from functools import lru_cache

_KATAKANA_START = 0x30A1
_KATAKANA_END = 0x30F6
_OFFSET = 0x30A1 - 0x3041


@lru_cache(maxsize=1)
def _kakasi():
    import pykakasi

    return pykakasi.kakasi()


def katakana_to_hiragana(text: str) -> str:
    """Conversión directa por desplazamiento de código.

    No hace falta una biblioteca: los dos silabarios están en el mismo orden en
    Unicode, separados por una distancia fija. Los caracteres que no son katakana
    (kanji, latino, signos) pasan sin tocar.
    """
    return "".join(
        chr(ord(c) - _OFFSET) if _KATAKANA_START <= ord(c) <= _KATAKANA_END else c for c in text
    )


def to_romaji(text: str) -> str:
    """Rōmaji Hepburn. Acepta kana, kanji o una mezcla."""
    if not text:
        return ""
    return "".join(part["hepburn"] for part in _kakasi().convert(text)).strip()


def reading_forms(reading_katakana: str) -> tuple[str, str]:
    """Devuelve ``(hiragana, rōmaji)`` a partir de la lectura de Sudachi.

    Sudachi da las lecturas en katakana, pero en un diccionario para estudiantes
    lo esperado es hiragana: el katakana en japonés marca extranjerismos y
    énfasis, así que mostrarlo ahí induce a error.
    """
    if not reading_katakana:
        return "", ""
    hiragana = katakana_to_hiragana(reading_katakana)
    return hiragana, to_romaji(hiragana)
