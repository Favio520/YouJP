"""Configuracion de registro."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO", *, quiet_libs: bool = True) -> None:
    """Formato compacto con milisegundos: al depurar latencia, los segundos
    enteros no dicen nada."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d %(levelname)-5s %(name)-24s %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    if quiet_libs:
        for noisy in ("faster_whisper", "urllib3", "huggingface_hub", "filelock"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
