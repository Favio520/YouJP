"""Descarga los diccionarios japoneses y los deja en data/raw.

Se usa jmdict-simplified en vez del XML original de JMdict: publica los mismos
datos en JSON regularizado, con releases semanales, y ahorra escribir un parser
de entidades XML y de estructuras irregulares.

    cd backend
    uv run python ../scripts/fetch_dicts.py

Se bajan dos ficheros de glosas, no uno:

* ``jmdict-spa`` (1,4 MB) -- las acepciones en espanol. La comparacion con los
  11 MB del ingles ya adelanta que la cobertura es parcial.
* ``jmdict-eng`` (11 MB) -- respaldo para las entradas sin espanol, marcadas como
  tales en la interfaz.

Mas ``kanjidic2``, que trae grado escolar, frecuencia y lecturas por kanji.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RELEASES = "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest"

# Los patrones exigen un dígito de versión justo detrás del nombre. Sin eso,
# "jmdict-eng-" también casa con "jmdict-eng-common-", que es el subconjunto de
# palabras frecuentes: 22 640 entradas en lugar de las ~200 000 del diccionario
# completo. El fichero se descarga igual de bien y nada falla, solo que faltan
# nueve de cada diez palabras.
WANTED = {
    re.compile(r"^jmdict-spa-\d"): "jmdict-spa.json",
    re.compile(r"^jmdict-eng-\d"): "jmdict-eng.json",
    re.compile(r"^kanjidic2-en-\d"): "kanjidic2.json",
}


def latest_assets() -> tuple[str, dict[str, str]]:
    with urllib.request.urlopen(RELEASES, timeout=60) as response:  # noqa: S310
        release = json.load(response)

    found: dict[str, str] = {}
    for asset in release["assets"]:
        name = asset["name"]
        if not name.endswith(".json.tgz"):
            continue
        for pattern, target in WANTED.items():
            if pattern.match(name):
                found[target] = asset["browser_download_url"]
    return release["tag_name"], found


def download_and_extract(url: str, target: Path) -> None:
    tmp = target.with_suffix(".tgz")
    print(f"[..]   {target.name}")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310
    try:
        with tarfile.open(tmp) as archive:
            member = next(m for m in archive.getmembers() if m.name.endswith(".json"))
            # El nombre dentro del tar lleva la version; se renombra al nombre
            # estable para que el resto del codigo no dependa de ella.
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"{member.name} no es un fichero regular")
            with target.open("wb") as out:
                while chunk := extracted.read(1 << 20):
                    out.write(chunk)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"[ok]   {target.name}  {target.stat().st_size / 1024**2:.1f} MB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="vuelve a descargar")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    tag, assets = latest_assets()
    print(f"jmdict-simplified {tag}")

    if missing := set(WANTED.values()) - set(assets):
        print(f"[warn] no estan en el release: {', '.join(sorted(missing))}")

    for target_name, url in sorted(assets.items()):
        target = RAW / target_name
        if target.exists() and not args.force:
            print(f"[ok]   {target_name} ya presente ({target.stat().st_size / 1024**2:.1f} MB)")
            continue
        download_and_extract(url, target)

    (RAW / "VERSION").write_text(tag, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
