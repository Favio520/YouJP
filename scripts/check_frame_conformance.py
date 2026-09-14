"""Comprueba que el codec de la extension y el del backend coinciden.

Compila `extension/src/protocol.ts` con esbuild, genera una trama desde Node con
el mismo codigo que usa la extension, y la decodifica aqui con el codigo del
backend. Si los dos lados discrepan en el orden de bytes, en el tamano de la
cabecera o en la escala Int16, salta aqui y no tres horas despues mirando una
transcripcion sin sentido.

    cd backend
    uv run python ../scripts/check_frame_conformance.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402

from youjp.ws.codec import HEADER_SIZE, decode_frame  # noqa: E402

EXTENSION = ROOT / "extension"
PROTOCOL_TS = EXTENSION / "src" / "protocol.ts"
BUNDLE = ROOT / "scripts" / ".frame-codec.mjs"
GENERATOR = ROOT / "scripts" / "check_frame_conformance.mjs"

NPX = "npx.cmd" if sys.platform == "win32" else "npx"
NODE = "node.exe" if sys.platform == "win32" else "node"


def build_bundle() -> None:
    """esbuild viene con Vite, que ya esta en las dependencias de la extension."""
    subprocess.run(  # noqa: S603
        [NPX, "esbuild", str(PROTOCOL_TS), "--format=esm", f"--outfile={BUNDLE}"],
        cwd=EXTENSION,
        check=True,
        capture_output=True,
    )


def main() -> int:
    if not PROTOCOL_TS.is_file():
        print(f"no encuentro {PROTOCOL_TS}")
        return 1

    print("compilando el codec de la extension...")
    build_bundle()

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "frame.bin"
        result = subprocess.run(  # noqa: S603
            [NODE, str(GENERATOR), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        expected = json.loads(result.stdout.strip().splitlines()[-1])
        raw = target.read_bytes()

    frame = decode_frame(raw)
    fallos: list[str] = []

    def check(nombre: str, obtenido: object, esperado: object) -> None:
        marca = "ok " if obtenido == esperado else "MAL"
        if obtenido != esperado:
            fallos.append(f"{nombre}: TypeScript dice {esperado!r}, Python lee {obtenido!r}")
        print(f"  [{marca}] {nombre:<16} {obtenido!r}")

    print(f"\ntrama de {len(raw)} B ({HEADER_SIZE} de cabecera + {len(raw) - HEADER_SIZE} de PCM)")
    check("bytes", len(raw), expected["bytes"])
    check("header_size", HEADER_SIZE, expected["header_size"])
    check("seq", frame.seq, expected["seq"])
    check("media_time_ms", frame.media_time_ms, expected["mediaTimeMs"])
    check("capture_ms", frame.capture_ms, expected["captureMs"])
    check("discontinuity", frame.discontinuity, bool(expected["flags"] & 0b10))
    check("muestras", len(frame.pcm), expected["samples"])

    # La rampa tiene que reconstruirse igual por los dos lados.
    primero = int(round(float(frame.pcm[0]) * 32767))
    ultimo = int(round(float(frame.pcm[-1]) * 32767))
    check("primera muestra", primero, expected["first_sample"])
    check("ultima muestra", ultimo, expected["last_sample"])
    check("monotona", bool(np.all(np.diff(frame.pcm) >= 0)), True)

    BUNDLE.unlink(missing_ok=True)

    if fallos:
        print("\nDISCREPANCIAS:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("\nlos dos codecs coinciden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
