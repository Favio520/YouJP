"""Servidor local: HTTP de diagnostico y WebSocket de transcripcion.

    cd backend
    uv run uvicorn youjp.main:app --host 127.0.0.1 --port 8770

Sin ``--reload``: recargaria el modelo en cada cambio de fichero, y son cinco
segundos y 1,3 GB de VRAM cada vez.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from youjp.asr.engine import WhisperEngine
from youjp.audio.vad import SileroVAD
from youjp.config import Settings, get_settings
from youjp.mt import build_provider
from youjp.obs.gpu import read_gpu
from youjp.obs.logging import setup_logging
from youjp.pipeline.streaming import FinalUpdate
from youjp.pipeline.translate import MtWorker, TranslationJob
from youjp.ws.codec import FrameDecodeError, decode_frame
from youjp.ws.protocol import (
    ControlFlush,
    ErrorMessage,
    MetricsTick,
    Ping,
    Pong,
    SessionReady,
    SessionStart,
    SessionStop,
    parse_client_message,
)
from youjp.ws.session import AsrWorker, LoopEmitter

log = logging.getLogger(__name__)

METRICS_INTERVAL_S = 2.0
OUTBOX_SIZE = 512


class AppState:
    """Recursos compartidos entre conexiones.

    El modelo se carga una sola vez: son 1,3 GB de VRAM y 5 s de arranque, y no
    tiene sentido pagarlos por sesion.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = WhisperEngine(settings)
        self.translator = build_provider(settings)
        self.vad_path = settings.vad_model
        self.sessions = 0

    def new_vad(self) -> SileroVAD:
        # Una instancia por sesion: el modelo es diminuto (2 MB) pero su estado
        # recurrente no se puede compartir entre flujos de audio distintos.
        return SileroVAD(self.vad_path, sample_rate=self.settings.sample_rate)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    state = AppState(settings)
    app.state.youjp = state

    log.info("precargando el modelo de ASR...")
    await asyncio.to_thread(state.engine.load)
    await asyncio.to_thread(state.engine.warmup)

    if settings.mt_provider != "none":
        try:
            log.info("precargando el traductor (%s)...", settings.mt_provider)
            # Avisar antes de cargar: si hay modelos ajenos ocupando la GPU,
            # conviene saberlo antes de intentar meter uno más.
            residents = getattr(state.translator, "report_residents", None)
            if residents is not None:
                await asyncio.to_thread(residents)
            await asyncio.to_thread(state.translator.load)
            # Calentar aquí y no en la primera frase del vídeo: en frío, subir
            # el modelo a la GPU cuesta unos 30 s.
            warm = getattr(state.translator, "warmup", None)
            if warm is not None:
                await asyncio.to_thread(warm)
        except Exception:  # noqa: BLE001
            # Sin traductor el sistema sigue siendo útil: los subtítulos
            # japoneses son la mitad del producto. Mejor arrancar cojo que no
            # arrancar.
            log.exception("no se pudo cargar el traductor; se sigue sin traducción")
            state.translator = build_provider(settings.model_copy(update={"mt_provider": "none"}))

    _warn_if_vram_tight()
    log.info("servidor listo en http://%s:%d", settings.host, settings.port)
    try:
        yield
    finally:
        state.engine.unload()
        state.translator.unload()


MIN_FREE_VRAM_MB = 500
"""Margen por debajo del cual se avisa.

Con Whisper y Qwen3-4B cargados quedan unos 640 MiB en una tarjeta de 6 GB, y
Chrome reproduciendo vídeo se come parte de eso. Por debajo de este margen, lo
siguiente que pase será que el controlador desborde a RAM del sistema y todo se
vuelva cinco veces más lento sin dar un solo error.
"""


def _warn_if_vram_tight() -> None:
    gpu = read_gpu()
    if gpu is None:
        return
    log.info(
        "VRAM: %.0f/%.0f MiB usados, %.0f libres", gpu.used_mb, gpu.total_mb, gpu.free_mb
    )
    if gpu.free_mb < MIN_FREE_VRAM_MB:
        log.warning(
            "solo quedan %.0f MiB de VRAM libres. Cierra juegos y aplicaciones con "
            "aceleracion por GPU, o pasa el traductor a CPU con YOUJP_LLM_NUM_GPU=0 "
            "(mas lento) o a NLLB con YOUJP_MT_PROVIDER=nllb (mas ligero, peor).",
            gpu.free_mb,
        )


app = FastAPI(title="youjp", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    state: AppState = app.state.youjp
    gpu = read_gpu()
    return {
        "status": "ok",
        "asr_model": state.settings.asr_model,
        "device": state.settings.asr_device,
        "compute_type": state.settings.asr_compute_type,
        "asr_loaded": state.engine.is_loaded,
        "word_timestamps": state.engine.word_timestamps,
        "sessions": state.sessions,
        "gpu": None
        if gpu is None
        else {
            "name": gpu.name,
            "used_mb": round(gpu.used_mb),
            "free_mb": round(gpu.free_mb),
            "total_mb": round(gpu.total_mb),
        },
    }


@app.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    state: AppState = app.state.youjp
    settings = state.settings
    await ws.accept()

    session_id = uuid.uuid4().hex[:8]
    loop = asyncio.get_running_loop()
    outbox: asyncio.Queue[BaseModel] = asyncio.Queue(maxsize=OUTBOX_SIZE)
    emitter = LoopEmitter(loop, outbox)

    worker: AsrWorker | None = None
    mt: MtWorker | None = None
    sender = asyncio.create_task(_sender(ws, outbox), name=f"sender-{session_id}")
    ticker: asyncio.Task | None = None

    log.info("[%s] conexion abierta desde %s", session_id, ws.client)
    state.sessions += 1

    try:
        while True:
            packet = await ws.receive()
            kind = packet.get("type")

            if kind == "websocket.disconnect":
                break

            if (data := packet.get("bytes")) is not None:
                if worker is None:
                    # Audio antes de session.start: la extension aun no ha
                    # anunciado la sesion. Se ignora en vez de fallar.
                    continue
                try:
                    worker.submit(decode_frame(data))
                except FrameDecodeError as exc:
                    log.warning("[%s] trama descartada: %s", session_id, exc)
                    emitter(ErrorMessage(code="bad_frame", message=str(exc)))
                continue

            raw = packet.get("text")
            if raw is None:
                continue

            try:
                message = parse_client_message(raw)
            except ValidationError as exc:
                log.warning("[%s] mensaje invalido: %s", session_id, exc)
                emitter(ErrorMessage(code="bad_message", message=exc.json()))
                continue

            if isinstance(message, SessionStart):
                if worker is not None:
                    worker.stop()
                if mt is not None:
                    mt.stop()

                mt = MtWorker(
                    state.translator,
                    emitter,
                    context_sentences=settings.mt_context_sentences,
                )
                mt.start()

                worker = AsrWorker(
                    settings,
                    state.engine,
                    state.new_vad(),
                    emitter,
                    start_media_ms=message.media_time_ms,
                    on_sentence=_forward_to_mt(mt),
                )
                worker.start()
                ticker = asyncio.create_task(
                    _metrics_ticker(worker, mt, emitter), name=f"metrics-{session_id}"
                )
                log.info(
                    "[%s] sesion iniciada · video=%s directo=%s t=%d ms",
                    session_id,
                    message.video_id or "?",
                    message.is_live,
                    message.media_time_ms,
                )
                emitter(
                    SessionReady(
                        session_id=session_id,
                        asr_model=settings.asr_model,
                        device=settings.asr_device,
                        compute_type=settings.asr_compute_type,
                        sample_rate=settings.sample_rate,
                        frame_ms=settings.frame_ms,
                    )
                )

            elif isinstance(message, ControlFlush):
                if worker is not None:
                    worker.request_flush(message.media_time_ms)
                    log.info(
                        "[%s] flush por %s en t=%d ms",
                        session_id,
                        message.reason,
                        message.media_time_ms,
                    )

            elif isinstance(message, SessionStop):
                break

            elif isinstance(message, Ping):
                emitter(Pong(t=message.t))

    except WebSocketDisconnect:
        log.info("[%s] el cliente cerro la conexion", session_id)
    except Exception:  # noqa: BLE001
        log.exception("[%s] error en la sesion", session_id)
    finally:
        state.sessions -= 1
        for task in (ticker, sender):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if worker is not None:
            await asyncio.to_thread(worker.stop)
        if mt is not None:
            await asyncio.to_thread(mt.stop)
        log.info("[%s] sesion cerrada", session_id)


def _forward_to_mt(mt: MtWorker):
    """Puente ASR -> traducción. Encola y vuelve: se ejecuta en el hilo de ASR
    y no puede pararse a trabajar."""

    def forward(update: FinalUpdate) -> None:
        mt.submit(
            TranslationJob(
                segment_id=update.sentence.segment_id,
                text=update.sentence.text,
                media_start_ms=update.media_start_ms,
                media_end_ms=update.media_end_ms,
                queued_at=time.perf_counter(),
            )
        )

    return forward


async def _sender(ws: WebSocket, outbox: asyncio.Queue[BaseModel]) -> None:
    """Unico punto de envio. Centralizarlo evita escrituras concurrentes sobre
    el mismo socket, que en Starlette no estan permitidas."""
    while True:
        message = await outbox.get()
        try:
            await ws.send_text(message.model_dump_json())
        except (WebSocketDisconnect, RuntimeError):
            return


async def _metrics_ticker(worker: AsrWorker, mt: MtWorker, emit: LoopEmitter) -> None:
    proc = psutil.Process()
    while True:
        await asyncio.sleep(METRICS_INTERVAL_S)
        m = worker.metrics
        e2e = m.get("speech_latency_ms")
        whisper = m.get("whisper_processing_ms")
        mt_latency = mt.metrics.get("translation_latency_ms")
        e2e_summary = e2e.summary() if e2e else {}
        whisper_summary = whisper.summary() if whisper else {}
        mt_summary = mt_latency.summary() if mt_latency else {}
        gpu = read_gpu()
        emit(
            MetricsTick(
                end_to_end_ms_p50=e2e_summary.get("p50", 0.0),
                end_to_end_ms_p95=e2e_summary.get("p95", 0.0),
                whisper_processing_ms_p50=whisper_summary.get("p50", 0.0),
                audio_buffer_ms=worker.buffer_ms(),
                dropped_audio_chunks=worker.dropped,
                partial_transcripts=m.counter("partial_transcripts"),
                final_transcripts=m.counter("final_transcripts"),
                passes=worker.session.stats.passes,
                skipped_silent=worker.session.stats.skipped_silent,
                rejected=dict(worker.session.stats.rejected),
                translation_latency_ms_p50=mt_summary.get("p50", 0.0),
                translations=mt.metrics.counter("translations"),
                dropped_translations=mt.dropped,
                mt_provider=mt.provider.name,
                gpu_used_mb=round(gpu.used_mb) if gpu else 0.0,
                gpu_total_mb=round(gpu.total_mb) if gpu else 0.0,
                cpu_pct=proc.cpu_percent(),
                ram_mb=round(proc.memory_info().rss / 1024**2),
            )
        )
