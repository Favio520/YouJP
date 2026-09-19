"""Traducción japonés → español o inglés, con modelos compartidos por sesión."""

from __future__ import annotations

import logging

from youjp.config import Settings
from youjp.mt.base import NullProvider, Translation, TranslationProvider
from youjp.mt.ct2_nllb import Nllb200Provider
from youjp.mt.llm import LlmProvider

log = logging.getLogger(__name__)

__all__ = [
    "LlmProvider",
    "Nllb200Provider",
    "NullProvider",
    "Translation",
    "TranslationProvider",
    "build_provider",
]


def build_provider(settings: Settings) -> TranslationProvider:
    """Crea el proveedor configurado.

    No carga el modelo: eso ocurre en el primer uso o cuando alguien llame a
    ``load()`` explícitamente.
    """
    match settings.mt_provider:
        case "nllb":
            return Nllb200Provider(settings)
        case "llm":
            return LlmProvider(settings)
        case "none":
            return NullProvider()
        case other:  # pragma: no cover - lo impide la validación de Settings
            raise ValueError(f"proveedor de traducción desconocido: {other}")
