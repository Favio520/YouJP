"""Supported subtitle languages, shared by providers and the wire protocol."""

from typing import Literal

TargetLanguage = Literal["es", "en"]
NLLB_TARGETS: dict[TargetLanguage, str] = {"es": "spa_Latn", "en": "eng_Latn"}


def resolve_target(target: TargetLanguage | None, configured: str) -> TargetLanguage:
    if target is not None:
        if target not in NLLB_TARGETS:
            raise ValueError(f"Unsupported translation target: {target}")
        return target
    for language, code in NLLB_TARGETS.items():
        if configured == code:
            return language
    raise ValueError(f"Unsupported translation target: {configured}")
