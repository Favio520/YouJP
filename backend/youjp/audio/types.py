"""Tipos comunes del subsistema de audio."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """Una trama de PCM tal y como llega desde la fuente de audio.

    El doble sello de tiempo es deliberado:

    * ``capture_ms`` es un reloj monotono del capturador. Sirve para medir la
      latencia real del pipeline.
    * ``media_time_ms`` es la posicion dentro del video. Sirve para anclar el
      subtitulo, para retroceder y para guardar la frase con su marca temporal.

    Los dos avanzan por caminos distintos y su diferencia es justamente la
    metrica de deriva que hay que vigilar en sesiones largas.
    """

    seq: int
    """Numero de trama desde el inicio de la sesion. Detecta huecos."""

    media_time_ms: int
    capture_ms: int

    pcm: np.ndarray
    """float32 en [-1, 1], mono, a la frecuencia de muestreo de la sesion."""

    discontinuity: bool = False
    """Cierto en la primera trama tras un seek o un cambio de velocidad."""

    def duration_ms(self, sample_rate: int) -> float:
        return 1000.0 * len(self.pcm) / sample_rate
