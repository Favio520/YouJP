"""Regenera los iconos de YouJP desde su fuente vectorial.

    cd backend
    uv run python ../scripts/make_icons.py

El logo (el dinosaurio con auriculares y sakura) vive en
scripts/windows/assets/app-icon-sumi-e.png. Build-Icons.ps1 lo escala con WPF y
escribe app-logo.png, youjp-logo.ico y los iconos de la extensión, sin depender
de Pillow. Este script mantiene la orden histórica y delega en él.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.name != "nt":
        raise SystemExit("El generador del icono de YouJP necesita Windows.")
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = windows / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = ROOT / "scripts" / "windows" / "Build-Icons.ps1"
    return subprocess.run(
        [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
