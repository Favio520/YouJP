"""Codec binario de audio: ida y vuelta, y rechazo de basura.

Es la frontera entre TypeScript y Python. Un desajuste de un byte aqui no da un
error claro: da audio que suena a ruido blanco y una transcripcion sin sentido,
que es mucho mas caro de diagnosticar.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from youjp.audio.types import AudioFrame
from youjp.ws.codec import (
    FLAG_DISCONTINUITY,
    HEADER,
    HEADER_SIZE,
    MAGIC,
    VERSION,
    FrameDecodeError,
    decode_frame,
    encode_frame,
)


def make_frame(pcm: np.ndarray, **kwargs) -> AudioFrame:
    base = {"seq": 7, "media_time_ms": 1_117_420, "capture_ms": 3_400}
    base.update(kwargs)
    return AudioFrame(pcm=pcm, **base)


def test_cabecera_de_16_bytes():
    """El tamano esta fijado en el protocolo y en el worklet de la extension."""
    assert HEADER_SIZE == 16


def test_ida_y_vuelta_conserva_los_metadatos():
    original = make_frame(np.zeros(1600, dtype=np.float32))
    vuelta = decode_frame(encode_frame(original))

    assert vuelta.seq == original.seq
    assert vuelta.media_time_ms == original.media_time_ms
    assert vuelta.capture_ms == original.capture_ms
    assert len(vuelta.pcm) == 1600


def test_ida_y_vuelta_conserva_el_audio():
    """Int16 pierde precision, pero menos de la que anade el propio codec de
    origen. El error por muestra tiene que quedar por debajo de 1/32768."""
    rng = np.random.default_rng(0)
    pcm = (rng.random(1600, dtype=np.float32) * 2 - 1) * 0.8

    vuelta = decode_frame(encode_frame(make_frame(pcm)))
    assert np.abs(vuelta.pcm - pcm).max() < 1.0 / 32768


def test_los_extremos_no_se_desbordan():
    pcm = np.array([-1.0, 1.0, -1.5, 1.5, 0.0], dtype=np.float32)
    vuelta = decode_frame(encode_frame(make_frame(pcm)))
    assert vuelta.pcm.min() >= -1.0
    assert vuelta.pcm.max() <= 1.0
    assert vuelta.pcm[4] == pytest.approx(0.0)


def test_la_bandera_de_discontinuidad_viaja():
    frame = make_frame(np.zeros(160, dtype=np.float32), discontinuity=True)
    assert decode_frame(encode_frame(frame)).discontinuity is True
    assert decode_frame(encode_frame(make_frame(np.zeros(160, dtype=np.float32)))).discontinuity is False


def test_rechaza_trama_corta():
    with pytest.raises(FrameDecodeError, match="cabecera"):
        decode_frame(b"\xa5\x01")


def test_rechaza_magic_incorrecto():
    bad = HEADER.pack(0x00, VERSION, 0, 0, 1, 2, 3) + b"\x00\x00"
    with pytest.raises(FrameDecodeError, match="magic"):
        decode_frame(bad)


def test_rechaza_version_futura():
    """Si un dia cambia el formato, mejor un error claro que audio mal
    interpretado."""
    bad = HEADER.pack(MAGIC, VERSION + 1, 0, 0, 1, 2, 3) + b"\x00\x00"
    with pytest.raises(FrameDecodeError, match="version"):
        decode_frame(bad)


def test_rechaza_payload_impar():
    bad = HEADER.pack(MAGIC, VERSION, 0, 0, 1, 2, 3) + b"\x00\x00\x00"
    with pytest.raises(FrameDecodeError, match="multiplo"):
        decode_frame(bad)


def test_orden_de_bytes_little_endian():
    """Contra un DataView de JavaScript escrito sin el flag littleEndian, que es
    el error mas facil de cometer en el lado de la extension."""
    frame = make_frame(np.zeros(2, dtype=np.float32), seq=0x01020304)
    raw = encode_frame(frame)
    assert raw[4:8] == b"\x04\x03\x02\x01"


def test_trama_de_100ms_ocupa_3216_bytes():
    frame = make_frame(np.zeros(1600, dtype=np.float32))
    assert len(encode_frame(frame)) == 3216


def test_flags_declarados_coinciden_con_el_protocolo():
    frame = make_frame(np.zeros(2, dtype=np.float32), discontinuity=True)
    flags = struct.unpack_from("<B", encode_frame(frame), 2)[0]
    assert flags & FLAG_DISCONTINUITY
