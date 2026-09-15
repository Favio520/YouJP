"""Puente entre el WebSocket y el pipeline de ASR.

El receptor de WebSocket vive en el event loop y no puede bloquearse nunca: si se
para a esperar a Whisper, deja de leer del socket, el buffer del sistema se llena
y se pierde audio del que ya no queda rastro. Por eso el ASR corre en su propio
hilo -- CTranslate2 libera el GIL durante la inferencia -- y los dos lados se
comunican por colas:

    receptor WS (async)  --cola acotada-->  hilo de ASR
    hilo de ASR  --call_soon_threadsafe-->  emisor WS (async)

Las ordenes de flush y de parada viajan por la misma cola que el audio, y no por
un canal aparte, para que no se adelanten a las tramas que ya estaban en camino:
un seek tiene que descartar exactamente el audio anterior, ni mas ni menos.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from youjp.asr.engine import WhisperEngine
from youjp.audio.types import AudioFrame
from youjp.audio.vad import SileroVAD, VADGate
from youjp.config import Settings
from youjp.obs.metrics import MetricsCollector
from youjp.pipeline.streaming import FinalUpdate, PartialUpdate, StreamingSession
from youjp.ws.protocol import AsrFinal, AsrPartial

log = logging.getLogger(__name__)

_STOP = object()


class AsrWorker:
    """Hilo que consume tramas y emite eventos de transcripcion."""

    def __init__(
        self,
        settings: Settings,
        engine: WhisperEngine,
        vad: SileroVAD,
        emit: Callable[[BaseModel], None],
        *,
        start_media_ms: int = 0,
        max_queued_frames: int = 64,
        on_sentence: Callable[[FinalUpdate], None] | None = None,
    ) -> None:
        self.settings = settings
        self.metrics = MetricsCollector()
        self._emit = emit
        # Gancho para el traductor. Se llama desde el hilo de ASR, así que lo
        # que haya al otro lado tiene que encolar y volver, no trabajar.
        self._on_sentence = on_sentence
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max_queued_frames)
        self._dropped = 0

        gate = VADGate(
            vad,
            threshold=settings.vad_threshold,
            release_threshold=settings.vad_release_threshold,
            min_silence_ms=settings.vad_min_silence_ms,
            speech_pad_ms=settings.vad_speech_pad_ms,
        )
        self.session = StreamingSession(
            settings,
            engine,
            gate,
            metrics=self.metrics,
            on_partial=self._on_partial,
            on_final=self._on_final,
            start_media_ms=start_media_ms,
        )
        self._thread = threading.Thread(target=self._run, name="asr-worker", daemon=True)

    # -- ciclo de vida -----------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning("el hilo de ASR no termino en %.1f s", timeout)

    # -- entrada (desde el event loop) -------------------------------------

    def submit(self, frame: AudioFrame) -> bool:
        """Encola una trama. Devuelve False si se ha tenido que descartar.

        Nunca bloquea. Si la cola esta llena es que el ASR no sigue el ritmo, y
        entonces lo correcto es tirar lo mas antiguo: acumular retraso es peor
        que perder 100 ms de audio viejo, porque el retraso no se recupera nunca.
        """
        try:
            self._queue.put_nowait(frame)
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(frame)
            except (queue.Empty, queue.Full):  # pragma: no cover - carrera rara
                pass
            self._dropped += 1
            self.metrics.count("dropped_audio_chunks")
            if self._dropped % 10 == 1:
                log.warning("cola de ASR llena, %d tramas descartadas", self._dropped)
            return False

    def request_flush(self, media_time_ms: int = 0) -> None:
        """Encola un flush. Viaja por la cola del audio, no por un canal aparte,
        para que descarte exactamente las tramas anteriores y ni una mas.

        ``media_time_ms`` es solo informativo: el reanclaje lo hace la siguiente
        trama. Ver :meth:`StreamingSession.reset`.
        """
        self._queue.put(("flush", media_time_ms))

    # -- bucle del hilo ----------------------------------------------------

    def _run(self) -> None:
        log.info("hilo de ASR arrancado")
        while True:
            item = self._queue.get()
            if item is _STOP:
                break
            try:
                if isinstance(item, tuple) and item[0] == "flush":
                    self.session.reset()
                else:
                    self.session.push(item)
            except Exception:  # noqa: BLE001 - un fallo aqui no debe matar el hilo
                log.exception("error procesando audio; la sesion continua")
        try:
            self.session.finish()
        except Exception:  # noqa: BLE001
            log.exception("error al cerrar la sesion")
        log.info(
            "hilo de ASR terminado: %d pasadas, %d saltadas, %d tramas descartadas",
            self.session.stats.passes,
            self.session.stats.skipped_silent,
            self._dropped,
        )

    # -- salida (hacia el event loop) --------------------------------------

    def _on_partial(self, update: PartialUpdate) -> None:
        self._emit(
            AsrPartial(
                committed=update.committed,
                tentative=update.tentative,
                media_start_ms=update.media_start_ms,
            )
        )

    def _on_final(self, update: FinalUpdate) -> None:
        # El japonés sale primero y sin esperar a nadie. La traducción llegará
        # después por su cuenta, enlazada por segment_id.
        self._emit(
            AsrFinal(
                segment_id=update.sentence.segment_id,
                text=update.sentence.text,
                media_start_ms=update.media_start_ms,
                media_end_ms=update.media_end_ms,
                reason=update.sentence.reason,
                latency_ms=round(update.latency_ms, 1),
            )
        )
        if self._on_sentence is not None:
            self._on_sentence(update)

    # -- diagnostico -------------------------------------------------------

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def queued(self) -> int:
        return self._queue.qsize()

    def buffer_ms(self) -> float:
        """Audio pendiente en la cola, en milisegundos."""
        return self.queued * self.settings.frame_ms


class LoopEmitter:
    """Convierte llamadas desde un hilo en envios por el WebSocket.

    ``call_soon_threadsafe`` y no ``run_coroutine_threadsafe``: lo primero solo
    encola en el loop y vuelve, lo segundo crea un future y espera a que el loop
    lo agende. En el camino caliente esa diferencia importa.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, out: asyncio.Queue[BaseModel]) -> None:
        self._loop = loop
        self._out = out

    def __call__(self, message: BaseModel) -> None:
        try:
            self._loop.call_soon_threadsafe(self._out.put_nowait, message)
        except RuntimeError:
            # El loop se ha cerrado: la sesion esta terminando y ya no hay a
            # quien enviar. No es un error.
            log.debug("emisor: el loop ya no acepta mas")


def now_ms() -> int:
    return int(time.time() * 1000)
