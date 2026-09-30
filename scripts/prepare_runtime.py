"""Prepare effective runtime settings/resources for the Windows assistant."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def write_runtime(path: Path, config: dict) -> None:
    """Publish only complete JSON, retaining the previous config on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        pending = Path(handle.name)
        try:
            json.dump(config, handle, indent=2)
        except BaseException:
            handle.close()
            pending.unlink(missing_ok=True)
            raise
    try:
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-dictionary", action="store_true")
    parser.add_argument("--print-settings", action="store_true",
                        help="Print effective launcher settings without loading or downloading models")
    args = parser.parse_args()
    from youjp.config import get_settings
    from youjp.contract import APP_VERSION

    settings = get_settings()
    runtime_config = {"port": settings.port, "app_version": APP_VERSION,
                      "asr_device": settings.asr_device, "mt_provider": settings.mt_provider}
    if args.print_settings:
        print(json.dumps(runtime_config))
        return

    import fetch_models
    from youjp.asr.engine import WhisperEngine

    print(f"Configuracion efectiva: {settings.asr_model} / {settings.asr_device}; traduccion {settings.mt_provider}", flush=True)
    if not settings.vad_model.exists():
        # Reuse download helper, respecting a custom configured models folder.
        fetch_models.MODELS = settings.vad_model.parent
        downloaded = fetch_models.fetch_silero()
        if downloaded != settings.vad_model:
            settings.vad_model.write_bytes(downloaded.read_bytes())
    engine = WhisperEngine(settings)
    try:
        engine.load()
        engine.warmup()
    finally:
        engine.unload()

    if settings.mt_provider == "llm":
        print("Preparando Ollama y el modelo de traduccion...", flush=True)
        try:
            request = urllib.request.Request(
                settings.llm_url.rstrip("/") + "/api/pull",
                data=json.dumps({"model": settings.llm_model, "stream": True}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                last_status = ""
                for line in response:
                    result = json.loads(line)
                    if not isinstance(result, dict):
                        raise TypeError("Respuesta de Ollama invalida")
                    if result.get("error"):
                        raise RuntimeError(result["error"])
                    status = result.get("status", "")
                    if status != last_status:
                        print(status, flush=True)
                        last_status = status
                if last_status != "success":
                    raise ValueError("Ollama cerro la descarga antes de confirmarla")
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError("No se pudo preparar Ollama. Abre Ollama o elige NLLB/Solo japones en el asistente. Si tienes .env, revisa YOUJP_MT_PROVIDER.") from exc
    elif settings.mt_provider == "nllb":
        from youjp.mt import build_provider
        provider = build_provider(settings)
        try:
            provider.load()
            provider.warmup()
        finally:
            provider.unload()

    if not args.skip_dictionary and not settings.dict_db.exists():
        import fetch_dicts
        from youjp.dict.build_db import build
        fetch_dicts.RAW = settings.data_dir / "raw"
        # The downloader parses argv, so don't leak our --skip-dictionary.
        previous = sys.argv
        sys.argv = ["fetch_dicts.py"]
        try:
            if fetch_dicts.main() != 0:
                raise RuntimeError("No se pudieron descargar los diccionarios")
        finally:
            sys.argv = previous
        settings.dict_db.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=settings.dict_db.parent, prefix=f".{settings.dict_db.name}.",
            suffix=".building.sqlite3", delete=False,
        ) as handle:
            pending = Path(handle.name)
        try:
            conn = sqlite3.connect(pending)
            try:
                raw = fetch_dicts.RAW
                build(conn, raw / "jmdict-spa.json", raw / "jmdict-eng.json", raw / "kanjidic2.json")
            finally:
                conn.close()
            pending.replace(settings.dict_db)
        finally:
            pending.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(pending) + suffix).unlink(missing_ok=True)

    runtime = ROOT / ".youjp" / "runtime.json"
    write_runtime(runtime, runtime_config)


if __name__ == "__main__":
    main()
