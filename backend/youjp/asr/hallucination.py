"""Filtros contra las alucinaciones de Whisper en japones.

Es el riesgo mas probable de todo el proyecto. Sobre silencio, musica o ruido de
fondo, Whisper en japones no calla: produce frases completas, gramaticales y
plausibles, sacadas de los subtitulos de YouTube con los que se entreno. Las mas
habituales son la despedida de fin de video y la peticion de suscripcion.

Ninguno de estos filtros basta por separado; van los cuatro juntos, y el VAD de
:mod:`youjp.audio.vad` actua antes que todos ellos.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from youjp.asr.types import QualitySignals

log = logging.getLogger(__name__)

_STRIP = re.compile(r"[\s　、。！？，\.,!?]+")


@dataclass(frozen=True, slots=True)
class Rejection:
    reason: str
    detail: str


def normalize(text: str) -> str:
    """Quita espacios y puntuacion para comparar contra la lista negra."""
    return _STRIP.sub("", text)


MIN_CHARS_TO_JUDGE = 20
"""Por debajo de esto no se juzga la repeticion.

Frases cortas con repeticion legitima -- "はいはいはいはい", "そうそうそう" -- darian
valores altos, y un bucle real de Whisper nunca es corto: llena la ventana.
"""


def repetition_ratio(text: str, n: int = 4) -> float:
    """Cuanta de la variedad del texto se ha perdido por repeticion.

    Se mide como ``1 - n_gramas_distintos / n_gramas_totales``. Un texto normal
    casi no repite n-gramas y da ~0; un bucle del decodificador tiene periodo
    corto y da ~0,9.

    La medida obvia -- contar cuantas veces aparece el n-grama mas frecuente --
    parece equivalente pero no lo es: depende de la longitud del patron repetido.
    Con "ありがとう" repetido doce veces da 0,80, pero con un patron de doce
    caracteres repetido cuatro veces da solo 0,33 y el bucle se cuela. Caso real
    del 14-09-2026: "私はサンドルオンを使って、" repetido hasta agotar la
    ventana pasaba el filtro.
    """
    clean = normalize(text)
    if len(clean) < max(2 * n, MIN_CHARS_TO_JUDGE):
        return 0.0
    grams = [clean[i : i + n] for i in range(len(clean) - n + 1)]
    return 1.0 - len(set(grams)) / len(grams)


def screen(
    text: str,
    quality: QualitySignals,
    *,
    max_no_speech_prob: float = 0.6,
    min_avg_logprob: float = -1.0,
    max_repeat_ratio: float = 0.5,
    blacklist: tuple[str, ...] = (),
) -> Rejection | None:
    """Devuelve el motivo de rechazo, o ``None`` si el texto parece legitimo."""
    clean = normalize(text)
    if not clean:
        return Rejection("empty", "sin contenido tras normalizar")

    if quality.no_speech_prob > max_no_speech_prob:
        return Rejection("no_speech", f"no_speech_prob={quality.no_speech_prob:.2f}")

    if quality.avg_logprob < min_avg_logprob:
        return Rejection("low_confidence", f"avg_logprob={quality.avg_logprob:.2f}")

    for phrase in blacklist:
        needle = normalize(phrase)
        if needle and needle in clean:
            return Rejection("blacklist", phrase)

    ratio = repetition_ratio(clean)
    if ratio > max_repeat_ratio:
        return Rejection("repetition", f"ratio={ratio:.2f}")

    return None
