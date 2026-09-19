"""Interfaz de traducción.

Existe desde el primer día por dos razones concretas, no por simetría:

* NLLB-200 es CC-BY-NC 4.0. Para uso personal da igual, pero si esto llegara a
  distribuirse habría que cambiarlo, y con una interfaz por medio ese cambio es
  de una línea.
* La decisión entre traductor dedicado y LLM se tomó sobre estimaciones
  (ADR 0003) y hay que confirmarla midiendo. Sin dos implementaciones
  intercambiables no hay comparación posible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from youjp.mt.languages import TargetLanguage


@dataclass(slots=True)
class Translation:
    text: str
    provider: str
    latency_ms: float
    cached: bool = False


@runtime_checkable
class TranslationProvider(Protocol):
    """Traduce una frase, opcionalmente con las anteriores como contexto.

    Solo se llama sobre frases **finales**. Traducir parciales produce español
    que cambia bruscamente mientras se lee, y desorienta más de lo que ayuda.
    """

    name: str

    def load(self) -> None:
        """Carga perezosa. Construir el proveedor no debe tocar la GPU."""
        ...

    def unload(self) -> None:
        """Libera recursos. Necesario para el cambio a modo estudio."""
        ...

    def translate(
        self, text: str, context: Sequence[str] = (), *, target: TargetLanguage | None = None
    ) -> Translation:
        ...


class NullProvider:
    """No traduce. Es el proveedor por defecto mientras no haya modelo
    descargado, para que el resto del pipeline funcione igual."""

    name = "none"

    def load(self) -> None:
        return None

    def unload(self) -> None:
        return None

    def translate(
        self, text: str, context: Sequence[str] = (), *, target: TargetLanguage | None = None
    ) -> Translation:
        return Translation(text="", provider=self.name, latency_ms=0.0)
