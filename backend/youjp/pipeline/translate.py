"""Hilo de traducción.

Va en paralelo al ASR y no en serie con él. La razón es la del documento de
arquitectura: mientras se traduce la frase A, Whisper ya está transcribiendo la
B. Si la traducción bloqueara el hilo de ASR, cada frase sumaría su latencia a
la siguiente y el retraso crecería sin límite durante un directo.

Solo recibe frases **finales**. Traducir parciales produce español que cambia
bruscamente mientras se lee.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from youjp.mt.base import TranslationProvider
from youjp.obs.metrics import MetricsCollector
from youjp.ws.protocol import MtFinal

log = logging.getLogger(__name__)

_STOP = object()


@dataclass(slots=True)
class TranslationJob:
    segment_id: int
    text: str
    media_start_ms: int
    media_end_ms: int
    queued_at: float


class MtWorker:
    def __init__(
        self,
        provider: TranslationProvider,
        emit: Callable[[BaseModel], None],
        *,
        metrics: MetricsCollector | None = None,
        context_sentences: int = 3,
        max_queued: int = 16,
    ) -> None:
        self.provider = provider
        self.metrics = metrics or MetricsCollector()
        self._emit = emit
        self._queue: queue.Queue = queue.Queue(maxsize=max_queued)
        self._context: deque[str] = deque(maxlen=max(0, context_sentences))
        self._dropped = 0
        self._thread = threading.Thread(target=self._run, name="mt-worker", daemon=True)

    # -- ciclo de vida -----------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning("el hilo de traduccion no termino en %.1f s", timeout)

    # -- entrada -----------------------------------------------------------

    def submit(self, job: TranslationJob) -> None:
        """Encola una frase. Nunca bloquea al hilo de ASR.

        Si la cola se llena, el traductor no sigue el ritmo del habla. Se
        descarta la frase más antigua sin traducir: el japonés ya está en
        pantalla, así que el usuario pierde la traducción de una frase y no el
        subtítulo entero.
        """
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            try:
                descartada = self._queue.get_nowait()
                self._queue.put_nowait(job)
                log.warning("traduccion descartada para el segmento %d", descartada.segment_id)
            except (queue.Empty, queue.Full):  # pragma: no cover - carrera rara
                pass
            self._dropped += 1
            self.metrics.count("dropped_translations")

    # -- bucle -------------------------------------------------------------

    def _run(self) -> None:
        log.info("hilo de traduccion arrancado (%s)", self.provider.name)
        while True:
            job = self._queue.get()
            if job is _STOP:
                break
            try:
                self._process(job)
            except Exception:  # noqa: BLE001 - un fallo no debe matar el hilo
                log.exception("error traduciendo el segmento %d", job.segment_id)
        log.info("hilo de traduccion terminado (%d descartadas)", self._dropped)

    def _process(self, job: TranslationJob) -> None:
        waited_ms = (time.perf_counter() - job.queued_at) * 1000
        result = self.provider.translate(job.text, tuple(self._context))
        self._context.append(job.text)

        if not result.text:
            return

        self.metrics.record("translation_latency_ms", result.latency_ms)
        self.metrics.record("translation_queue_ms", waited_ms)
        self.metrics.count("translations")
        self._emit(
            MtFinal(
                segment_id=job.segment_id,
                text_es=result.text,
                provider=result.provider,
                media_start_ms=job.media_start_ms,
                media_end_ms=job.media_end_ms,
                latency_ms=round(result.latency_ms, 1),
            )
        )

    # -- diagnostico -------------------------------------------------------

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def queued(self) -> int:
        return self._queue.qsize()
