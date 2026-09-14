"""Hace visibles las DLL de CUDA instaladas como ruedas de pip, en Windows.

CTranslate2 carga ``cublas64_*.dll`` y ``cudnn*.dll`` por nombre. Cuando esas
bibliotecas llegan via ``nvidia-cublas-cu12`` / ``nvidia-cudnn-cu12`` acaban en
``site-packages/nvidia/<lib>/bin``, que no esta en la ruta de busqueda de DLLs.
El sintoma tipico es un ``RuntimeError`` de "Library cublas64_12.dll is not found"
al crear el modelo, o un cuelgue silencioso.

Hay que llamar a :func:`enable_cuda_dlls` **antes** de importar ``faster_whisper``
o ``ctranslate2``. El modulo :mod:`youjp.asr.engine` ya lo hace por su cuenta.
"""

from __future__ import annotations

import logging
import os
import sys
import sysconfig
from pathlib import Path

log = logging.getLogger(__name__)

_added: list[Path] | None = None


def enable_cuda_dlls() -> list[Path]:
    """Anade las carpetas ``bin`` de las ruedas de NVIDIA al path de DLLs.

    Idempotente. Devuelve las carpetas anadidas (vacia fuera de Windows, donde
    el cargador dinamico ya las encuentra por RPATH).
    """
    global _added
    if _added is not None:
        return _added
    if sys.platform != "win32":
        _added = []
        return _added

    roots = {
        Path(sysconfig.get_paths()["purelib"]),
        Path(sysconfig.get_paths()["platlib"]),
    }
    added: list[Path] = []
    for root in roots:
        nvidia = root / "nvidia"
        if not nvidia.is_dir():
            continue
        for bindir in sorted(nvidia.glob("*/bin")):
            if not any(bindir.glob("*.dll")):
                continue
            try:
                os.add_dll_directory(str(bindir))
            except OSError:  # pragma: no cover - ruta rara o permisos
                log.warning("no se pudo anadir al path de DLLs: %s", bindir)
                continue
            added.append(bindir)

    if added:
        log.debug("DLLs de CUDA visibles desde: %s", ", ".join(str(p) for p in added))
    else:
        log.debug(
            "no se encontraron ruedas de CUDA en site-packages; "
            "si asr_device=cuda falla, instala el extra: uv sync --extra cuda"
        )
    _added = added
    return added
