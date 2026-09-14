"""Descarga los modelos que necesita la fase 0.

    uv run python ../scripts/fetch_models.py               # solo el VAD
    uv run python ../scripts/fetch_models.py --whisper large-v3-turbo

El VAD son 2 MB y se guarda en ``models/silero_vad.onnx``. Los modelos de
Whisper los gestiona huggingface-hub dentro de ``models/whisper`` y pesan entre
0,5 y 1,6 GB segun cual.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"

# Se prueban en orden: el proyecto ha movido el fichero de sitio entre versiones.
SILERO_URLS = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx",
    "https://raw.githubusercontent.com/snakers4/silero-vad/master/files/silero_vad.onnx",
)


def fetch_silero(force: bool = False) -> Path:
    target = MODELS / "silero_vad.onnx"
    if target.exists() and not force:
        print(f"[ok]   VAD ya presente: {target} ({target.stat().st_size / 1024:.0f} KB)")
        return target

    MODELS.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for url in SILERO_URLS:
        try:
            print(f"[..]   descargando {url}")
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
                data = response.read()
            if len(data) < 100_000:
                raise ValueError(f"respuesta demasiado corta ({len(data)} B)")
            target.write_bytes(data)
            print(f"[ok]   VAD guardado en {target} ({len(data) / 1024:.0f} KB)")
            return target
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            print(f"[warn] fallo: {exc}")
            last_error = exc

    raise SystemExit(
        "no se pudo descargar silero_vad.onnx desde ninguna URL conocida.\n"
        f"Ultimo error: {last_error}\n"
        "Descargalo a mano desde https://github.com/snakers4/silero-vad "
        f"y guardalo como {target}"
    )


def fetch_whisper(name: str, device: str, compute_type: str) -> None:
    """Fuerza la descarga creando el modelo una vez.

    Se hace aqui y no en el primer arranque real para que la descarga no se
    confunda con latencia del pipeline al medir.
    """
    sys.path.insert(0, str(ROOT / "backend"))
    from youjp.cuda_setup import enable_cuda_dlls

    enable_cuda_dlls()
    from faster_whisper import WhisperModel

    print(f"[..]   preparando Whisper {name} ({device}/{compute_type})")
    model = WhisperModel(
        name,
        device=device,
        compute_type=compute_type,
        download_root=str(MODELS / "whisper"),
    )
    del model
    print(f"[ok]   Whisper {name} listo en {MODELS / 'whisper'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="vuelve a descargar el VAD")
    parser.add_argument(
        "--whisper",
        metavar="NOMBRE",
        help="descarga tambien un modelo de Whisper (large-v3-turbo, small, ...)",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="int8_float16")
    args = parser.parse_args()

    fetch_silero(force=args.force)
    if args.whisper:
        fetch_whisper(args.whisper, args.device, args.compute_type)


if __name__ == "__main__":
    main()
