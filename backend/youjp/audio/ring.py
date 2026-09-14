"""Buffer circular de PCM con tiempos absolutos de sesion.

El ASR no pide "los ultimos N segundos": pide "desde el instante T hasta ahora",
porque la politica LocalAgreement reejecuta sobre una ventana que crece hasta el
siguiente recorte. Por eso el buffer indexa por tiempo absoluto desde el inicio
de la sesion y no por posicion relativa.

Implementado como cola de trozos en vez de array circular: a 16 kHz, 30 s son
1,9 MB y concatenar cada 0,8 s es irrelevante frente a la inferencia. La version
simple es mas facil de razonar y de testear, que es lo que importa aqui.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

import numpy as np

log = logging.getLogger(__name__)


class PCMRing:
    """Retiene los ultimos ``capacity_s`` segundos de audio.

    Seguro para escribir desde el hilo receptor y leer desde el hilo de ASR.
    Cuando se llena, descarta lo mas antiguo: perder audio viejo es preferible
    a acumular retraso.
    """

    def __init__(self, capacity_s: float = 30.0, sample_rate: int = 16_000) -> None:
        self.sample_rate = sample_rate
        self.capacity_samples = int(capacity_s * sample_rate)
        self._chunks: deque[np.ndarray] = deque()
        self._held = 0  # muestras actualmente en el buffer
        self._start = 0  # indice absoluto de la primera muestra retenida
        self._end = 0  # indice absoluto tras la ultima muestra escrita
        self._dropped = 0
        self._lock = threading.Lock()

    # -- escritura ---------------------------------------------------------

    def write(self, pcm: np.ndarray) -> None:
        """Anade PCM float32 al final, desalojando lo mas antiguo si hace falta."""
        if pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)
        with self._lock:
            self._chunks.append(pcm)
            self._held += len(pcm)
            self._end += len(pcm)
            self._evict_locked()

    def _evict_locked(self) -> None:
        while self._held > self.capacity_samples and self._chunks:
            excess = self._held - self.capacity_samples
            head = self._chunks[0]
            if len(head) <= excess:
                self._chunks.popleft()
                self._held -= len(head)
                self._start += len(head)
                self._dropped += len(head)
            else:
                self._chunks[0] = head[excess:]
                self._held -= excess
                self._start += excess
                self._dropped += excess

    # -- lectura -----------------------------------------------------------

    def read_from(self, t0: float) -> tuple[np.ndarray, float]:
        """Devuelve el audio desde ``t0`` (segundos absolutos) hasta el final.

        Si ``t0`` es anterior a lo que queda retenido, se sirve desde el inicio
        real del buffer. Devuelve ``(pcm, t_inicio_real)`` para que quien llame
        sepa a que instante corresponde la primera muestra.
        """
        with self._lock:
            if not self._chunks:
                return np.empty(0, dtype=np.float32), self._end / self.sample_rate
            want = int(t0 * self.sample_rate)
            first = max(want, self._start)
            if first >= self._end:
                return np.empty(0, dtype=np.float32), first / self.sample_rate
            data = np.concatenate(self._chunks)
            return data[first - self._start :].copy(), first / self.sample_rate

    def trim_before(self, t: float) -> None:
        """Descarta el audio anterior a ``t``. Lo llama el ASR tras confirmar
        una frase: sin esto la ventana crece hasta los 30 s."""
        with self._lock:
            cut = int(t * self.sample_rate)
            while self._chunks and self._start < cut:
                head = self._chunks[0]
                take = min(len(head), cut - self._start)
                if take == len(head):
                    self._chunks.popleft()
                else:
                    self._chunks[0] = head[take:]
                self._held -= take
                self._start += take

    # -- estado ------------------------------------------------------------

    @property
    def start_sample(self) -> int:
        """Indice absoluto de la muestra mas antigua retenida.

        Para comparar instantes usa siempre los indices de muestra, no los
        segundos: en coma flotante ``0.6 - 0.4`` no da ``0.2``, y eso convierte
        un intervalo fijo entre pasadas en uno que oscila entre dos valores.
        """
        return self._start

    @property
    def end_sample(self) -> int:
        """Indice absoluto tras la ultima muestra escrita."""
        return self._end

    @property
    def start_time(self) -> float:
        """Instante absoluto de la muestra mas antigua retenida."""
        return self._start / self.sample_rate

    @property
    def end_time(self) -> float:
        """Instante absoluto tras la ultima muestra escrita."""
        return self._end / self.sample_rate

    @property
    def duration(self) -> float:
        return self._held / self.sample_rate

    @property
    def dropped_samples(self) -> int:
        """Muestras desalojadas por desbordamiento. En regimen normal debe ser 0."""
        return self._dropped

    def clear(self, at_time: float | None = None) -> None:
        """Vacia el buffer. Se usa tras un seek.

        ``at_time`` reancla el reloj absoluto; si es ``None`` se conserva el
        actual, que es lo que se quiere en una pausa.
        """
        with self._lock:
            self._chunks.clear()
            self._held = 0
            if at_time is not None:
                self._start = self._end = int(at_time * self.sample_rate)
            else:
                self._start = self._end
