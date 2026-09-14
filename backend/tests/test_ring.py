"""Buffer de PCM: indexado por tiempo absoluto, desaloja lo mas antiguo."""

from __future__ import annotations

import numpy as np
import pytest

from youjp.audio.ring import PCMRing

SR = 16_000


def tone(seconds: float, value: float = 1.0) -> np.ndarray:
    return np.full(int(seconds * SR), value, dtype=np.float32)


def test_lectura_por_tiempo_absoluto():
    ring = PCMRing(capacity_s=10, sample_rate=SR)
    ring.write(tone(1.0, 0.1))
    ring.write(tone(1.0, 0.2))

    assert ring.end_time == pytest.approx(2.0)
    pcm, start = ring.read_from(1.0)
    assert start == pytest.approx(1.0)
    assert len(pcm) == SR
    assert pcm[0] == pytest.approx(0.2)


def test_lectura_anterior_al_inicio_se_recorta():
    """Pedir audio ya desalojado no es un error: se sirve lo que queda y se
    informa del instante real de la primera muestra."""
    ring = PCMRing(capacity_s=1.0, sample_rate=SR)
    ring.write(tone(2.0))
    pcm, start = ring.read_from(0.0)
    assert start == pytest.approx(1.0)
    assert len(pcm) == SR


def test_desalojo_al_llenarse():
    ring = PCMRing(capacity_s=1.0, sample_rate=SR)
    ring.write(tone(0.5, 0.1))
    ring.write(tone(0.5, 0.2))
    ring.write(tone(0.5, 0.3))

    assert ring.duration == pytest.approx(1.0)
    assert ring.dropped_samples == int(0.5 * SR)
    pcm, _ = ring.read_from(ring.start_time)
    assert pcm[0] == pytest.approx(0.2)


def test_trim_before_libera_la_ventana():
    ring = PCMRing(capacity_s=30, sample_rate=SR)
    ring.write(tone(5.0))
    ring.trim_before(3.0)
    assert ring.start_time == pytest.approx(3.0)
    assert ring.duration == pytest.approx(2.0)


def test_trim_no_retrocede():
    ring = PCMRing(capacity_s=30, sample_rate=SR)
    ring.write(tone(2.0))
    ring.trim_before(1.0)
    ring.trim_before(0.5)
    assert ring.start_time == pytest.approx(1.0)


def test_lectura_futura_devuelve_vacio():
    ring = PCMRing(capacity_s=10, sample_rate=SR)
    ring.write(tone(1.0))
    pcm, _ = ring.read_from(5.0)
    assert len(pcm) == 0


def test_clear_reancla_el_reloj():
    ring = PCMRing(capacity_s=10, sample_rate=SR)
    ring.write(tone(2.0))
    ring.clear(at_time=100.0)
    assert ring.duration == 0
    assert ring.end_time == pytest.approx(100.0)
    ring.write(tone(0.5))
    assert ring.end_time == pytest.approx(100.5)


def test_convierte_a_float32():
    ring = PCMRing(capacity_s=10, sample_rate=SR)
    ring.write(np.zeros(100, dtype=np.float64))
    pcm, _ = ring.read_from(0.0)
    assert pcm.dtype == np.float32
