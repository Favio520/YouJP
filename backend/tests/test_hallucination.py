"""Filtros contra las alucinaciones tipicas de Whisper en japones."""

from __future__ import annotations

from youjp.asr.hallucination import normalize, repetition_ratio, screen
from youjp.asr.types import QualitySignals

BUENA = QualitySignals(no_speech_prob=0.05, avg_logprob=-0.3, compression_ratio=1.4)

# "gracias por ver el video" -- la alucinacion mas frecuente sobre silencio.
GRACIAS = "ご視聴ありがとうございました"
FRASE_OK = "今日は経済への影響について話します。"


def test_texto_legitimo_pasa():
    assert screen(FRASE_OK, BUENA, blacklist=(GRACIAS,)) is None


def test_rechaza_texto_vacio():
    r = screen("。。。  ", BUENA)
    assert r is not None and r.reason == "empty"


def test_rechaza_por_no_speech():
    quality = QualitySignals(no_speech_prob=0.91, avg_logprob=-0.2)
    r = screen(FRASE_OK, quality, max_no_speech_prob=0.6)
    assert r is not None and r.reason == "no_speech"


def test_rechaza_por_confianza_baja():
    quality = QualitySignals(no_speech_prob=0.1, avg_logprob=-2.4)
    r = screen(FRASE_OK, quality, min_avg_logprob=-1.0)
    assert r is not None and r.reason == "low_confidence"


def test_rechaza_lista_negra_pese_a_buena_confianza():
    """Estas frases llegan con confianza alta: el modelo esta convencido de lo
    que dice. Solo la lista negra las para."""
    r = screen(GRACIAS, BUENA, blacklist=(GRACIAS,))
    assert r is not None and r.reason == "blacklist"


def test_lista_negra_ignora_puntuacion_y_espacios():
    ruido = GRACIAS[:4] + "、" + GRACIAS[4:] + "。"
    r = screen(ruido, BUENA, blacklist=(GRACIAS,))
    assert r is not None and r.reason == "blacklist"


def test_rechaza_bucle_de_repeticion():
    bucle = "ありがとう" * 12
    r = screen(bucle, BUENA)
    assert r is not None and r.reason == "repetition"


def test_repetition_ratio():
    assert repetition_ratio("あいうえ" * 10) > 0.5
    assert repetition_ratio(FRASE_OK) < 0.5
    assert repetition_ratio("あい") == 0.0  # demasiado corto para juzgar


def test_repetition_ratio_con_patron_largo():
    """El fallo de la primera version de la metrica.

    Contando el n-grama mas frecuente, un patron de doce caracteres repetido
    cuatro veces daba 0,33 y se colaba entero. Caso real: turbo repitiendo
    "私はサンドルオンを使って、" en la apertura de un reportaje.
    """
    largo = "私はサンドルオンを使って、" * 4
    corto = "ありがとう" * 12
    assert repetition_ratio(largo) > 0.5
    assert repetition_ratio(corto) > 0.5


def test_repetition_ratio_no_castiga_frases_cortas():
    """Repeticion legitima en habla informal. Un bucle real nunca es corto:
    llena la ventana entera."""
    assert repetition_ratio("はいはいはいはい") == 0.0
    assert repetition_ratio("そうそうそうですね") == 0.0


def test_caso_real_ruido_rosa():
    """Caso observado el 2026-09-14 con whisper tiny sobre 10 s de ruido rosa
    sintetico, sin una sola voz: el modelo emitio "このように、" 34 veces seguidas
    con avg_logprob = -0,25, es decir, convencidisimo de lo que decia.

    Es el motivo por el que la confianza sola no sirve como filtro. Aqui se
    comprueba que lo paran dos senales independientes, para que quitar una por
    error no deje pasar el caso.
    """
    texto = "このように、" * 34

    observado = QualitySignals(no_speech_prob=0.925, avg_logprob=-0.254, compression_ratio=8.0)
    assert screen(texto, observado).reason == "no_speech"

    # Si no_speech_prob no delatara el tramo, la repeticion sigue delatandolo.
    enganoso = QualitySignals(no_speech_prob=0.10, avg_logprob=-0.254)
    assert screen(texto, enganoso).reason == "repetition"

    # Y la confianza por si sola habria dejado pasar el texto entero.
    assert screen(texto, enganoso, max_repeat_ratio=1.1, max_no_speech_prob=1.1) is None


def test_normalize_quita_puntuacion():
    assert normalize("あ、い。 う！") == "あいう"
