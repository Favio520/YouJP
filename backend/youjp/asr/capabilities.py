"""Deteccion cacheada de lo que sabe hacer cada modelo de ASR.

Ahora mismo solo hay una capacidad que averiguar, pero es critica: si un modelo
admite ``word_timestamps``. Ver :mod:`youjp.asr.probe` para el porque de que haya
que comprobarlo lanzando un proceso aparte.

El resultado se guarda en ``models/.asr_capabilities.json``, asi que el coste se
paga una vez por combinacion de modelo, dispositivo y tipo de computo.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 300


def _cache_path(models_dir: Path) -> Path:
    return models_dir / ".asr_capabilities.json"


def _load_cache(models_dir: Path) -> dict[str, bool]:
    path = _cache_path(models_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("cache de capacidades ilegible (%s); se rehara", exc)
        return {}


def _save_cache(models_dir: Path, cache: dict[str, bool]) -> None:
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
        _cache_path(models_dir).write_text(
            json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError as exc:  # pragma: no cover - disco lleno o permisos
        log.warning("no se pudo guardar la cache de capacidades: %s", exc)


def supports_word_timestamps(
    model: str,
    device: str,
    compute_type: str,
    models_dir: Path,
    *,
    force: bool = False,
) -> bool:
    """Devuelve si el modelo puede generar marcas por palabra sin morir.

    Lanza la sonda **antes** de que el proceso principal cargue el modelo, para
    que las dos copias no coincidan nunca en la VRAM.
    """
    key = f"{model}|{device}|{compute_type}"
    cache = _load_cache(models_dir)
    if not force and key in cache:
        return cache[key]

    log.info("comprobando si %s admite word timestamps (una sola vez)...", model)
    cmd = [
        sys.executable,
        "-m",
        "youjp.asr.probe",
        "--model",
        model,
        "--device",
        device,
        "--compute-type",
        compute_type,
        "--download-root",
        str(models_dir / "whisper"),
    ]
    try:
        result = subprocess.run(  # noqa: S603 - comando construido aqui, sin shell
            cmd,
            capture_output=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
            cwd=Path(__file__).resolve().parents[2],
        )
        ok = result.returncode == 0
        if not ok:
            log.warning(
                "%s no admite word timestamps (la sonda salio con %s). "
                "Se usaran tiempos interpolados por caracter.",
                model,
                result.returncode,
            )
    except subprocess.TimeoutExpired:
        log.warning("la sonda de %s no termino en %d s; se asume que no", model, PROBE_TIMEOUT_S)
        ok = False

    cache[key] = ok
    _save_cache(models_dir, cache)
    return ok
