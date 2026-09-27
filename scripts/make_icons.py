"""Regenera el icono compartido de YouJP desde su fuente vectorial WPF.

    cd backend
    uv run python ../scripts/make_icons.py

La marca del dinosaurio vive en scripts/windows/assets/AppIcon.xaml. Este script
mantiene la orden histórica y delega en Build-Icons.ps1, sin depender de Pillow.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.name != "nt":
        raise SystemExit("El generador del icono de YouJP necesita Windows/WPF.")
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = windows / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = ROOT / "scripts" / "windows" / "Build-Icons.ps1"
    return subprocess.run(
        [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-File", str(script)],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
