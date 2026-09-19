"""Regresiones de calidad de traducción.

No mide "cómo de buena" es una traducción: mide que no vuelvan los errores
concretos que ya se han visto y corregido. Ajustar un prompt a ojo sobre
cuarenta frases da resultados no monótonos -- se arreglan unas cosas y se rompen
otras sin enterarse -- y estos casos son el ancla.

Todos salen de transcripciones reales del banco de la fase 0, revisadas a mano
el 14-09-2026.

Se salta si Ollama no responde: no es un test que deba bloquear la suite en una
máquina sin modelo.
"""

from __future__ import annotations

import pytest

from youjp.config import get_settings
from youjp.mt.llm import LlmProvider

settings = get_settings()


@pytest.fixture(scope="module")
def traductor() -> LlmProvider:
    provider = LlmProvider(settings)
    try:
        if not provider.available():
            pytest.skip(f"Ollama no tiene {settings.llm_model}")
        provider.warmup()
        yield provider
    finally:
        provider.unload()


def traducir(provider: LlmProvider, texto: str, contexto: tuple[str, ...] = ()) -> str:
    return provider.translate(texto, contexto, target="es").text.lower()


def test_tercera_persona_en_narracion(traductor: LlmProvider):
    """El japonés omite el sujeto; el modelo tendía a rellenarlo con primera
    persona incluso narrando sobre otro.

    Observado: 「漫画家を目指して10年以上になるという田中さん」 se traducía como
    "Soy un artista de mangas con más de 10 años" -- persona equivocada y, de
    paso, decía que ya lo era en vez de que aspiraba a serlo.
    """
    salida = traducir(
        traductor,
        "漫画家を目指して10年以上に"
        "なるという田中さん",
    )
    assert not salida.startswith("soy "), f"primera persona: {salida!r}"
    # Varias formas valen: aspirar, intentar, querer, buscar. Lo que no vale es
    # afirmar que ya lo es.
    aspiracion = ("aspir", "intentando ser", "quiere ser", "busca ser", "trata de ser")
    assert any(v in salida for v in aspiracion), (
        f"pierde el matiz de aspiración: {salida!r}"
    )


def test_la_persona_sale_del_contexto(traductor: LlmProvider):
    """「ここで毎朝2時間勉強しています」 no lleva sujeto. Las frases anteriores
    dejan claro que se habla DE alguien, no que hable él."""
    contexto = (
        "一方西梅田店は朝5時から営業",
        "証券会社でお客様対応をして"
        "いる35歳の西山さん",
    )
    salida = traducir(
        traductor,
        "ここで毎朝2時間勉強しています",
        contexto,
    )
    assert "estudia" in salida, f"no usa tercera persona: {salida!r}"
    assert "estudio" not in salida.split(), f"primera persona: {salida!r}"


def test_comparativa_con_el_interlocutor(traductor: LlmProvider):
    """「私の方が〜上」 compara al hablante CON EL OTRO.

    NLLB lo invertía por completo ("son mucho mejores que yo"). Una versión del
    prompt lo dejó en "mejores que los míos", que no significa nada.
    """
    salida = traducir(
        traductor,
        "魔力も技術もコントロールも"
        "私の方が遥かに上",
    )
    assert "los míos" not in salida and "las mías" not in salida, (
        f"comparación consigo mismo, sin sentido: {salida!r}"
    )
    assert any(w in salida for w in ("tuyo", "tuya", "ti", "tu ", "suyo", "usted")), (
        f"pierde con quién se compara: {salida!r}"
    )


def test_no_traduce_el_significado_de_los_apellidos(traductor: LlmProvider):
    """西山 es un apellido, no "montaña del oeste".

    Observado: una versión del prompt lo convirtió en "Westyama", que mezcla
    traducción y transliteración y no es ni una cosa ni la otra.
    """
    salida = traducir(
        traductor,
        "証券会社でお客様対応をして"
        "いる35歳の西山真さん",
    )
    assert "west" not in salida, f"traduce el kanji del apellido: {salida!r}"
    assert "oeste" not in salida, f"traduce el kanji del apellido: {salida!r}"


def test_acepcion_segun_contexto(traductor: LlmProvider):
    """技術 es "técnica" hablando de una habilidad y "tecnología" hablando de
    industria. En una escena de magia, "tecnología" está mal."""
    salida = traducir(
        traductor,
        "魔力も技術もコントロールも"
        "私の方が遥かに上",
    )
    assert "tecnolog" not in salida, f"acepcion equivocada de 技術: {salida!r}"


def test_no_inventa_el_final_de_un_fragmento(traductor: LlmProvider):
    """Las frases se cierran por silencio o por longitud, así que llegan
    fragmentos cortados. Completarlos inventa contenido que nadie dijo."""
    salida = traducir(traductor, "と言って")
    assert len(salida) < 60, f"inventa una frase entera a partir de dos palabras: {salida!r}"


def test_devuelve_una_sola_linea(traductor: LlmProvider):
    """Un subtítulo es una línea. Las notas y explicaciones acaban encima del
    vídeo."""
    salida = traductor.translate(
        "今日は経済への影響について"
        "話します。"
    ).text
    assert "\n" not in salida
    assert not salida.startswith('"') and not salida.startswith("「")


@pytest.mark.parametrize("source,expected", [
    ("今日は経済について話します。", ("economy", "economics")),
    ("私の名前は田中です。", ("tanaka",)),
    ("ありがとうございます。", ("thank",)),
])
def test_traduccion_ingles_real(traductor, source, expected):
    output = traductor.translate(source, target="en").text.lower()
    assert any(word in output for word in expected), output
    assert "\n" not in output
    assert not any("\u3040" <= char <= "\u30ff" for char in output)
