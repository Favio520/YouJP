"""Sonda ejecutable en subproceso: comprueba si un modelo admite word timestamps.

No se puede averiguar desde el proceso principal. Algunos modelos destilados
llevan los ``alignment_heads`` del modelo original copiados tal cual, apuntando a
capas del decodificador que en ellos no existen; CTranslate2 indexa fuera de
rango y el proceso muere con una violacion de acceso, que no es una excepcion de
Python y por tanto no se puede capturar.

Caso real: ``kotoba-tech/kotoba-whisper-v2.0-faster`` declara cabezas en las capas
7, 10, 12, 13, 16, 17, 19, 21, 24 y 25 -- las de large-v3 -- pero su decodificador
destilado solo tiene 2 capas. Con ``word_timestamps=True`` el proceso sale con
0xC0000005.

Por eso la comprobacion se hace aqui, en un proceso desechable::

    python -m youjp.asr.probe --model X --device cuda --compute-type int8_float16

Codigo de salida 0 = admite word timestamps. Cualquier otro = no.
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="int8_float16")
    parser.add_argument("--download-root", default=None)
    args = parser.parse_args()

    from youjp.cuda_setup import enable_cuda_dlls

    enable_cuda_dlls()

    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute_type,
        download_root=args.download_root,
    )
    # Ruido de baja amplitud: suficiente para que el decodificador emita algo y
    # se ejecute el alineamiento, que es lo que se quiere probar.
    pcm = (np.random.randn(16_000 * 2) * 0.01).astype(np.float32)
    segments, _ = model.transcribe(
        pcm,
        language="ja",
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        word_timestamps=True,
        vad_filter=False,
    )
    # transcribe() es perezoso: sin consumir el generador no se ejecuta nada.
    for segment in segments:
        _ = segment.words
    return 0


if __name__ == "__main__":
    sys.exit(main())
