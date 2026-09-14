"""Codec de las tramas binarias de audio.

Formato (little endian, 16 B de cabecera + PCM)::

    offset  tamano  campo
      0      1 B    magic          0xA5
      1      1 B    version        1
      2      1 B    flags          bit0 = directo, bit1 = discontinuidad
      3      1 B    reservado      0
      4      4 B    seq            uint32, tramas desde session.start
      8      4 B    media_time_ms  uint32, player.currentTime al capturar
     12      4 B    capture_ms     uint32, reloj monotono del capturador
     16      N B    pcm            Int16 LE, mono, 16 kHz

A 100 ms por trama son 3 216 B, unos 32 KB/s. Int16 y no float32 porque
reduce a la mitad el trafico sin perder nada util: el audio de origen ya
viene de un codec con perdida.

El doble sello de tiempo es deliberado y esta explicado en
:class:`youjp.audio.types.AudioFrame`.
"""

from __future__ import annotations

import struct

import numpy as np

from youjp.audio.types import AudioFrame

MAGIC = 0xA5
VERSION = 1
HEADER = struct.Struct("<BBBBIII")
HEADER_SIZE = HEADER.size  # 16

FLAG_LIVE = 1 << 0
FLAG_DISCONTINUITY = 1 << 1

_INT16_SCALE = 32767.0
"""Escala de conversion float32 <-> Int16, la misma en los dos sentidos.

Con 32767 al codificar y 32768 al decodificar -- que es lo que sale si se copia
la primera receta que aparece por ahi -- queda un sesgo de escala del 0,003 %.
Es inaudible, pero convierte un test de ida y vuelta en algo que "casi" pasa, y
esconde de paso cualquier error de verdad que se meta despues por aqui.

El worklet de la extension tiene que usar exactamente esta constante::

    const s = Math.max(-1, Math.min(1, sample));
    int16[i] = Math.round(s * 32767);
"""


class FrameDecodeError(ValueError):
    """Trama binaria malformada. Se responde con un error, no se cierra la
    conexion: una trama corrupta no tiene por que tumbar la sesion."""


def decode_frame(data: bytes) -> AudioFrame:
    if len(data) < HEADER_SIZE:
        raise FrameDecodeError(f"trama de {len(data)} B, menor que la cabecera")

    magic, version, flags, _reserved, seq, media_time_ms, capture_ms = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise FrameDecodeError(f"magic 0x{magic:02X}, se esperaba 0x{MAGIC:02X}")
    if version != VERSION:
        raise FrameDecodeError(f"version {version} no soportada (esta es la {VERSION})")

    payload = data[HEADER_SIZE:]
    if len(payload) % 2:
        raise FrameDecodeError(f"payload de {len(payload)} B, no es multiplo de 2")

    pcm = np.frombuffer(payload, dtype="<i2").astype(np.float32) / _INT16_SCALE
    return AudioFrame(
        seq=seq,
        media_time_ms=media_time_ms,
        capture_ms=capture_ms,
        pcm=pcm,
        discontinuity=bool(flags & FLAG_DISCONTINUITY),
    )


def encode_frame(frame: AudioFrame, *, live: bool = False) -> bytes:
    """Contraparte del decodificador.

    La usan los tests y el cliente de repeticion (``scripts/replay_client.py``),
    que es lo que permite ejercitar el servidor entero sin navegador.
    """
    flags = (FLAG_LIVE if live else 0) | (FLAG_DISCONTINUITY if frame.discontinuity else 0)
    header = HEADER.pack(
        MAGIC,
        VERSION,
        flags,
        0,
        frame.seq & 0xFFFFFFFF,
        frame.media_time_ms & 0xFFFFFFFF,
        frame.capture_ms & 0xFFFFFFFF,
    )
    clipped = np.clip(frame.pcm, -1.0, 1.0)
    pcm = np.round(clipped * _INT16_SCALE).astype("<i2")
    return header + pcm.tobytes()
