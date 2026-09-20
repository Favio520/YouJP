"""Generated wire models plus validation/compatibility at the connection boundary."""

from __future__ import annotations

import json
from pydantic import TypeAdapter

from youjp.contract import (  # noqa: F401 -- public protocol API
    APP_VERSION, PROTOCOL_VERSION, AsrFinal, AsrPartial, ClientMessage,
    ControlFlush, DictPayload, ErrorMessage, MetricsTick, MtFinal, NlpTokens,
    Ping, Pong, SensePayload, ServerMessage, SessionConfigure, SessionReady,
    SessionStart, SessionStop, Token,
)

_CLIENT = TypeAdapter(ClientMessage)


class ProtocolMismatch(ValueError):
    """A legacy or incompatible client must upgrade before sending audio."""


def parse_client_message(raw: str) -> ClientMessage:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return _CLIENT.validate_json(raw)
    if isinstance(data, dict) and data.get("type") == "session.start":
        version = data.get("protocol_version")
        if type(version) is not int or version != PROTOCOL_VERSION:
            raise ProtocolMismatch(
                f"Protocolo incompatible ({version!r}); YouJP {APP_VERSION} requiere "
                f"protocolo {PROTOCOL_VERSION}. Actualiza el backend y recarga la extensión."
            )
    return _CLIENT.validate_json(raw)
