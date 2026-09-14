"""Mensajes de texto del WebSocket."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from youjp.ws.protocol import (
    AsrFinal,
    AsrPartial,
    ControlFlush,
    Ping,
    SessionStart,
    SessionStop,
    parse_client_message,
)


def test_session_start_con_valores_por_defecto():
    msg = parse_client_message('{"type": "session.start"}')
    assert isinstance(msg, SessionStart)
    assert msg.source == "ja"
    assert msg.target == "es"
    assert msg.is_live is False


def test_session_start_completo():
    raw = json.dumps({
        "type": "session.start", "video_id": "I79zm6cIoNM", "is_live": True,
        "media_time_ms": 1_117_000, "profile": "n3",
    })
    msg = parse_client_message(raw)
    assert msg.video_id == "I79zm6cIoNM"
    assert msg.is_live is True
    assert msg.media_time_ms == 1_117_000


def test_despacha_por_el_campo_type():
    assert isinstance(parse_client_message('{"type": "session.stop"}'), SessionStop)
    assert isinstance(parse_client_message('{"type": "ping", "t": 5}'), Ping)
    flush = parse_client_message('{"type": "control.flush", "reason": "seek"}')
    assert isinstance(flush, ControlFlush)
    assert flush.reason == "seek"


def test_rechaza_tipo_desconocido():
    with pytest.raises(ValidationError):
        parse_client_message('{"type": "algo.inventado"}')


def test_rechaza_razon_de_flush_invalida():
    with pytest.raises(ValidationError):
        parse_client_message('{"type": "control.flush", "reason": "porque_si"}')


def test_rechaza_json_malformado():
    with pytest.raises(ValidationError):
        parse_client_message("{esto no es json")


def test_los_mensajes_de_salida_llevan_su_type():
    """El cliente despacha por este campo: si falta, no se entera de nada."""
    partial = AsrPartial(committed="今日は", tentative="経", media_start_ms=100)
    assert json.loads(partial.model_dump_json())["type"] == "asr.partial"

    final = AsrFinal(
        segment_id=1, text="今日は。", media_start_ms=100,
        media_end_ms=900, reason="punctuation", latency_ms=1432.5,
    )
    datos = json.loads(final.model_dump_json())
    assert datos["type"] == "asr.final"
    assert datos["segment_id"] == 1


def test_el_japones_sobrevive_a_la_serializacion():
    texto = "今日は経済への影響について話します。"
    final = AsrFinal(
        segment_id=1, text=texto, media_start_ms=0, media_end_ms=1,
        reason="punctuation", latency_ms=0.0,
    )
    assert json.loads(final.model_dump_json())["text"] == texto
