"""Genera los iconos de la extension.

    cd backend
    uv run python ../scripts/make_icons.py

Se generan aqui y se versionan los PNG resultantes, en vez de depender de una
herramienta de diseno: el icono es una pieza mas del repositorio y tiene que
poder reconstruirse igual dentro de un ano.

El diseno tiene que funcionar a 16 px en la barra de Chrome, que es donde de
verdad se ve. Por eso:

* Un solo glifo grande. Cualquier cosa mas fina desaparece a ese tamano.
* あ y no un kanji: el hiragana tiene trazos abiertos y sigue siendo legible en
  16 px, mientras que un kanji de doce trazos se convierte en una mancha.
* Barra inferior en el azul de los subtitulos, que sugiere la linea de subtitulo
  sin competir con el glifo.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "extension" / "public" / "icon"

SIZES = (16, 32, 48, 96, 128)

FONDO = (36, 66, 124, 255)  # indigo del proyecto
GLIFO = (255, 255, 255, 255)
BARRA = (168, 197, 240, 255)  # el azul del espanol en los subtitulos

FUENTES = (
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\NotoSansJP-VF.ttf",
    r"C:\Windows\Fonts\msgothic.ttc",
)


def cargar_fuente(px: int) -> ImageFont.FreeTypeFont:
    for ruta in FUENTES:
        if Path(ruta).is_file():
            try:
                return ImageFont.truetype(ruta, px)
            except OSError:
                continue
    raise SystemExit(
        "no encuentro ninguna fuente japonesa. Probadas:\n  " + "\n  ".join(FUENTES)
    )


def dibujar(size: int) -> Image.Image:
    # Se dibuja al cuadruple y se reduce: el antialiasing de Pillow al rotar y
    # redondear es pobre, y a 16 px se nota como bordes dentados.
    escala = 4
    lienzo = size * escala
    img = Image.new("RGBA", (lienzo, lienzo), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radio = int(lienzo * 0.22)
    draw.rounded_rectangle([0, 0, lienzo - 1, lienzo - 1], radius=radio, fill=FONDO)

    # Barra de subtitulo. Por debajo de 32 px se omite: a 16 px queda en medio
    # pixel y solo ensucia el glifo.
    if size >= 32:
        margen = int(lienzo * 0.22)
        alto = max(2, int(lienzo * 0.075))
        base = int(lienzo * 0.80)
        draw.rounded_rectangle(
            [margen, base, lienzo - margen, base + alto],
            radius=alto // 2,
            fill=BARRA,
        )
        centro_y = int(lienzo * 0.42)
    else:
        centro_y = int(lienzo * 0.50)

    glifo = "\u3042"  # あ
    fuente = cargar_fuente(int(lienzo * (0.62 if size >= 32 else 0.74)))
    izq, arr, der, aba = draw.textbbox((0, 0), glifo, font=fuente)
    draw.text(
        (lienzo // 2 - (der + izq) // 2, centro_y - (aba + arr) // 2),
        glifo,
        font=fuente,
        fill=GLIFO,
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        destino = OUT / f"{size}.png"
        dibujar(size).save(destino)
        print(f"  {destino.relative_to(ROOT)}  {destino.stat().st_size:,} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
