"""Fuentes de audio.

El backend no sabe de donde viene el PCM. Esta interfaz es la razon por la que
mas adelante se podran anadir Twitch, captura de loopback WASAPI (la unica via
posible para contenido con DRM) o ficheros locales sin tocar el pipeline.

En la fase 0 solo existe :class:`FileSource`, que reproduce un WAV como si fuera
audio en vivo. Es la pieza que permite medir latencia de forma reproducible y
depurar sin un directo delante.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import soundfile as sf

from youjp.audio.types import AudioFrame

log = logging.getLogger(__name__)


@runtime_checkable
class AudioSource(Protocol):
    """Produce tramas de PCM mono float32 a la frecuencia de la sesion."""

    sample_rate: int

    def frames(self) -> Iterator[AudioFrame]:
        """Itera tramas hasta que la fuente se agota o se cierra."""
        ...

    def close(self) -> None: ...


class FileSource:
    """Reproduce un fichero de audio como si llegara desde la extension.

    Parameters
    ----------
    path:
        Cualquier formato que lea libsndfile (WAV, FLAC, OGG). Para MP3/M4A,
        conviertelo antes con ``scripts/prepare_sample.ps1``.
    realtime:
        Si es cierto, entrega las tramas al ritmo del reloj de pared, igual que
        lo haria un directo. Si es falso, las entrega tan rapido como se
        consuman: es lo que se quiere al medir el RTF del modelo, porque asi el
        limite lo pone la inferencia y no el reloj.
    start_media_ms:
        Posicion inicial simulada dentro del video.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        sample_rate: int = 16_000,
        frame_ms: int = 100,
        realtime: bool = True,
        start_media_ms: int = 0,
    ) -> None:
        self.path = Path(path)
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.realtime = realtime
        self.start_media_ms = start_media_ms
        self._closed = False

        data, file_rate = sf.read(str(self.path), dtype="float32", always_2d=True)
        if file_rate != sample_rate:
            raise ValueError(
                f"{self.path.name} esta a {file_rate} Hz y se esperan {sample_rate} Hz. "
                f"Conviertelo con: scripts/prepare_sample.ps1 -Source '{self.path}'"
            )
        channels = data.shape[1]
        if channels > 1:
            log.info("%s: mezclado a mono desde %d canales", self.path.name, channels)
            data = data.mean(axis=1, keepdims=True)
        self._pcm = np.ascontiguousarray(data[:, 0], dtype=np.float32)

    @property
    def duration_s(self) -> float:
        return len(self._pcm) / self.sample_rate

    def frames(self) -> Iterator[AudioFrame]:
        step = self.sample_rate * self.frame_ms // 1000
        t0 = time.perf_counter()
        seq = 0
        for offset in range(0, len(self._pcm), step):
            if self._closed:
                return
            chunk = self._pcm[offset : offset + step]
            if len(chunk) < step:
                # Ultima trama incompleta: se rellena para que el VAD reciba
                # siempre ventanas del mismo tamano.
                chunk = np.pad(chunk, (0, step - len(chunk)))
            elapsed_ms = seq * self.frame_ms
            if self.realtime:
                target = t0 + (elapsed_ms + self.frame_ms) / 1000.0
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            yield AudioFrame(
                seq=seq,
                media_time_ms=self.start_media_ms + elapsed_ms,
                capture_ms=int((time.perf_counter() - t0) * 1000),
                pcm=chunk,
            )
            seq += 1

    def close(self) -> None:
        self._closed = True
