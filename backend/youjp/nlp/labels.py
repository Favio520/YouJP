"""Nombres legibles para las categorías gramaticales.

Sudachi y JMdict usan dos vocabularios distintos y ninguno de los dos está
pensado para leerse: ``名詞,普通名詞,サ変可能`` y ``n,vs,vi`` describen lo mismo
de formas incompatibles. La tarjeta muestra la versión de Sudachi porque siempre
está presente, aunque la palabra no aparezca en el diccionario.
"""

from __future__ import annotations

SUDACHI_POS: dict[str, str] = {
    "名詞": "sustantivo",
    "動詞": "verbo",
    "形容詞": "adjetivo -i",
    "形状詞": "adjetivo -na",
    "副詞": "adverbio",
    "連体詞": "adnominal",
    "接続詞": "conjunción",
    "感動詞": "interjección",
    "代名詞": "pronombre",
    "助詞": "partícula",
    "助動詞": "auxiliar",
    "接頭辞": "prefijo",
    "接尾辞": "sufijo",
    "補助記号": "puntuación",
    "空白": "espacio",
}

# Matices del segundo nivel que cambian cómo se usa la palabra y que conviene
# mostrar: que un sustantivo admita する no se deduce de "sustantivo".
SUDACHI_POS1: dict[str, str] = {
    "サ変可能": "admite する",
    "形状詞可能": "también adjetivo -na",
    "副詞可能": "también adverbio",
    "固有名詞": "nombre propio",
    "数詞": "numeral",
    "非自立可能": "auxiliar",
    "格助詞": "partícula de caso",
    "係助詞": "partícula temática",
    "接続助詞": "partícula conjuntiva",
    "終助詞": "partícula final",
    "副助詞": "partícula adverbial",
}


def pos_label(pos: tuple[str, ...] | list[str]) -> str:
    """Etiqueta corta en español a partir de la tupla de Sudachi."""
    if not pos:
        return ""
    base = SUDACHI_POS.get(pos[0], pos[0])
    if len(pos) > 1 and (extra := SUDACHI_POS1.get(pos[1])):
        return f"{base} · {extra}"
    return base
