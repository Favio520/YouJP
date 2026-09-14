"""Recogida de metricas de latencia.

Las medias mienten en sistemas interactivos: lo que se nota al usar esto no es
la latencia media sino la cola. Por eso todo se guarda crudo y se resume en
percentiles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


@dataclass(slots=True)
class Series:
    """Una serie de valores con resumen por percentiles."""

    name: str
    unit: str = "ms"
    values: list[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        self.values.append(float(value))

    def summary(self) -> dict[str, Any]:
        if not self.values:
            return {"name": self.name, "unit": self.unit, "count": 0}
        ordered = sorted(self.values)
        return {
            "name": self.name,
            "unit": self.unit,
            "count": len(ordered),
            "mean": round(sum(ordered) / len(ordered), 2),
            "p50": round(_percentile(ordered, 0.50), 2),
            "p95": round(_percentile(ordered, 0.95), 2),
            "max": round(ordered[-1], 2),
        }


class MetricsCollector:
    """Contenedor de series y contadores, serializable a JSON."""

    def __init__(self) -> None:
        self._series: dict[str, Series] = {}
        self._counters: dict[str, int] = {}

    def record(self, name: str, value: float, unit: str = "ms") -> None:
        series = self._series.get(name)
        if series is None:
            series = self._series[name] = Series(name, unit)
        series.add(value)

    def count(self, name: str, delta: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + delta

    def get(self, name: str) -> Series | None:
        return self._series.get(name)

    def counter(self, name: str) -> int:
        return self._counters.get(name, 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "series": {k: v.summary() for k, v in sorted(self._series.items())},
            "counters": dict(sorted(self._counters.items())),
        }
