"""Mensajes de texto del WebSocket.

Los esquemas viven aqui y de aqui salen los tipos de TypeScript de la extension
(``scripts/gen_ts_types.py``), para que el protocolo no pueda desincronizarse
entre los dos lados sin que alguien se entere.

Las tramas de audio no pasan por aqui: van en binario, ver :mod:`youjp.ws.codec`.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# cliente -> servidor
# --------------------------------------------------------------------------


class SessionStart(BaseModel):
    type: Literal["session.start"] = "session.start"
    video_id: str = ""
    url: str = ""
    is_live: bool = False
    media_time_ms: int = 0
    source: str = "ja"
    target: str = "es"
    profile: str = "n4"


class SessionStop(BaseModel):
    type: Literal["session.stop"] = "session.stop"


class ControlFlush(BaseModel):
    """Seek, pausa o cambio de velocidad: se descarta el buffer y se reancla."""

    type: Literal["control.flush"] = "control.flush"
    reason: Literal["seek", "pause", "rate", "manual"] = "manual"
    media_time_ms: int = 0


class Ping(BaseModel):
    type: Literal["ping"] = "ping"
    t: int = 0


ClientMessage = Annotated[
    Union[SessionStart, SessionStop, ControlFlush, Ping],
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------
# servidor -> cliente
# --------------------------------------------------------------------------


class SessionReady(BaseModel):
    type: Literal["session.ready"] = "session.ready"
    session_id: str
    asr_model: str
    device: str
    compute_type: str
    sample_rate: int
    frame_ms: int
    protocol_version: int = 1


class AsrPartial(BaseModel):
    """Texto en curso.

    ``committed`` ya no cambiara nunca: es lo que LocalAgreement ha confirmado y
    se puede pintar en firme. ``tentative`` se reemplaza entera en cada
    actualizacion, asi que se pinta en gris y no se le montan interacciones
    encima.
    """

    type: Literal["asr.partial"] = "asr.partial"
    committed: str
    tentative: str
    media_start_ms: int


class AsrFinal(BaseModel):
    type: Literal["asr.final"] = "asr.final"
    segment_id: int
    text: str
    media_start_ms: int
    media_end_ms: int
    reason: str
    latency_ms: float


class MtFinal(BaseModel):
    """Traducción de una frase ya cerrada.

    Llega por separado y después del ``asr.final`` correspondiente, y se enlaza
    con él por ``segment_id``. Así el japonés aparece en cuanto está listo, sin
    esperar al traductor: son dos trabajos en paralelo, no una cadena.
    """

    type: Literal["mt.final"] = "mt.final"
    segment_id: int
    text_es: str
    provider: str
    media_start_ms: int
    media_end_ms: int
    latency_ms: float


class MetricsTick(BaseModel):
    type: Literal["metrics.tick"] = "metrics.tick"
    end_to_end_ms_p50: float = 0.0
    end_to_end_ms_p95: float = 0.0
    whisper_processing_ms_p50: float = 0.0
    audio_buffer_ms: float = 0.0
    dropped_audio_chunks: int = 0
    partial_transcripts: int = 0
    final_transcripts: int = 0
    passes: int = 0
    skipped_silent: int = 0
    rejected: dict[str, int] = Field(default_factory=dict)
    translation_latency_ms_p50: float = 0.0
    translations: int = 0
    dropped_translations: int = 0
    mt_provider: str = "none"
    gpu_used_mb: float = 0.0
    gpu_total_mb: float = 0.0
    cpu_pct: float = 0.0
    ram_mb: float = 0.0


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    fatal: bool = False


class Pong(BaseModel):
    type: Literal["pong"] = "pong"
    t: int = 0


ServerMessage = Union[
    SessionReady, AsrPartial, AsrFinal, MtFinal, MetricsTick, ErrorMessage, Pong
]


class ClientEnvelope(BaseModel):
    """Envoltorio solo para validar: pydantic necesita un modelo raiz para
    despachar por el campo ``type``."""

    message: ClientMessage


def parse_client_message(raw: str) -> ClientMessage:
    """Valida un mensaje de texto entrante.

    Lanza ``pydantic.ValidationError`` si no encaja con ningun tipo conocido.
    """
    return ClientEnvelope.model_validate_json(f'{{"message": {raw}}}').message
