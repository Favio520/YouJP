"""Uso de GPU via NVML.

El dato que de verdad importa en esta maquina no es cuanta VRAM usa el modelo,
sino cuanta queda libre: Windows, Chrome y el resto del escritorio ya ocupan una
parte fija antes de que el backend arranque. Por eso se mide siempre una linea
base antes de cargar nada, y el pico se muestrea en un hilo aparte, porque el
maximo ocurre durante la inferencia y no al terminarla.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

try:  # pragma: no cover - depende de la maquina
    import pynvml

    _NVML_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # noqa: BLE001
    pynvml = None  # type: ignore[assignment]
    _NVML_IMPORT_ERROR = exc


@dataclass(frozen=True, slots=True)
class GpuSnapshot:
    name: str
    total_mb: float
    used_mb: float
    free_mb: float
    utilization_pct: float


def gpu_available() -> bool:
    return pynvml is not None


def _decode(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def read_gpu(index: int = 0) -> GpuSnapshot | None:
    """Lectura puntual. Devuelve ``None`` si no hay GPU NVIDIA accesible."""
    if pynvml is None:
        return None
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
        except Exception:  # noqa: BLE001 - no disponible en algunos drivers
            util = 0
        snap = GpuSnapshot(
            name=_decode(pynvml.nvmlDeviceGetName(handle)),
            total_mb=mem.total / 1024**2,
            used_mb=mem.used / 1024**2,
            free_mb=mem.free / 1024**2,
            utilization_pct=float(util),
        )
        pynvml.nvmlShutdown()
        return snap
    except Exception as exc:  # noqa: BLE001
        log.debug("NVML no disponible: %s", exc)
        return None


class GpuMonitor:
    """Muestrea la VRAM en un hilo y retiene el pico.

    Uso::

        with GpuMonitor(hz=4) as mon:
            ...trabajo...
        print(mon.peak_used_mb, mon.baseline_used_mb)
    """

    def __init__(self, *, hz: float = 4.0, index: int = 0) -> None:
        self.hz = hz
        self.index = index
        self.baseline_used_mb: float = 0.0
        self.peak_used_mb: float = 0.0
        self.samples: list[float] = []
        self.device_name: str = "desconocida"
        self.total_mb: float = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> GpuMonitor:
        snap = read_gpu(self.index)
        if snap is None:
            log.info("sin GPU NVIDIA accesible: no se mediran metricas de VRAM")
            return self
        self.device_name = snap.name
        self.total_mb = snap.total_mb
        self.baseline_used_mb = snap.used_mb
        self.peak_used_mb = snap.used_mb
        self._thread = threading.Thread(target=self._run, name="gpu-monitor", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        period = 1.0 / self.hz
        while not self._stop.wait(period):
            snap = read_gpu(self.index)
            if snap is None:
                continue
            self.samples.append(snap.used_mb)
            self.peak_used_mb = max(self.peak_used_mb, snap.used_mb)

    @property
    def attributable_mb(self) -> float:
        """Pico menos linea base: lo que se puede atribuir a nuestros modelos.

        Es una aproximacion, no una medida exacta: otra aplicacion puede haber
        pedido VRAM mientras tanto. Sirve para comparar configuraciones entre si.
        """
        return max(0.0, self.peak_used_mb - self.baseline_used_mb)
