"""Exercise the real WebSocket route and MT worker, without loading ASR models."""

import asyncio
import struct
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import youjp.main as server
from youjp.config import Settings
from youjp.mt.base import Translation
from youjp.obs.metrics import MetricsCollector
from youjp.ws.protocol import AsrFinal


class Translator:
    name = "test"

    def translate(self, text, context=(), *, target=None):
        return Translation(f"{target}:{text}", self.name, 1)


class FakeAsr:
    stopped = []

    def __init__(self, settings, engine, vad, emit, *, on_sentence, on_reset, **kwargs):
        self.emit = emit
        self.on_sentence = on_sentence
        self.on_reset = on_reset
        self.index = 0
        self.metrics = MetricsCollector()

    def start(self):
        pass

    def stop(self):
        self.stopped.append(threading.current_thread().name)
        # An old worker can still finish after replacement. Its emitter must be closed.
        self.emit(AsrFinal(segment_id=99, text="stale", media_start_ms=0,
                           media_end_ms=1, reason="stop", latency_ms=0))

    def submit(self, frame):
        self.index += 1
        sentence = SimpleNamespace(segment_id=self.index, text="猫")
        self.emit(AsrFinal(segment_id=self.index, text=sentence.text, media_start_ms=0,
                           media_end_ms=100, reason="punctuation", latency_ms=0))
        self.on_sentence(SimpleNamespace(sentence=sentence, media_start_ms=0, media_end_ms=100))

    def request_flush(self, media_time_ms):
        self.on_reset()


class FakeNlp:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def submit(self, *args):
        pass

    def stop(self):
        pass


@pytest.fixture
def client(monkeypatch):
    state = SimpleNamespace(settings=Settings(_env_file=None), translator=Translator(),
                            engine=None, new_vad=lambda: None, new_analyzer=lambda: None, sessions=0)
    monkeypatch.setattr(server.app.state, "youjp", state, raising=False)
    monkeypatch.setattr(server, "AsrWorker", FakeAsr)
    monkeypatch.setattr(server, "NlpWorker", FakeNlp)
    FakeAsr.stopped = []
    tickers = {"active": 0, "max": 0}

    async def ticker(*args):
        tickers["active"] += 1
        tickers["max"] = max(tickers["max"], tickers["active"])
        try:
            await asyncio.Event().wait()
        finally:
            tickers["active"] -= 1

    monkeypatch.setattr(server, "_metrics_ticker", ticker)
    # No context-manager lifespan: heavy resources above are replaced explicitly.
    test_client = TestClient(server.app)
    try:
        yield test_client, state, tickers
    finally:
        test_client.close()


def audio(ws):
    ws.send_bytes(struct.pack("<BBBBIII", 0xA5, 1, 0, 0, 0, 0, 0) + b"\0" * 3200)


def test_live_target_switch_and_invalid_target_recovery(client):
    test_client, state, _ = client
    with test_client.websocket_connect("/stream") as ws:
        ws.send_json({"type": "session.start", "target": "es"})
        assert ws.receive_json()["target"] == "es"
        audio(ws)
        assert ws.receive_json()["type"] == "asr.final"
        assert ws.receive_json()["text_es"] == "es:猫"
        ws.send_json({"type": "session.configure", "target": "en"})
        audio(ws)
        assert ws.receive_json()["type"] == "asr.final"
        result = ws.receive_json()
        assert result["target"] == "en"
        assert result["text"] == "en:猫"
        assert result["text_es"] == ""
        ws.send_json({"type": "session.configure", "target": "fr"})
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "ping", "t": 42})
        assert ws.receive_json() == {"type": "pong", "t": 42}
        ws.send_json({"type": "session.stop"})
    assert state.sessions == 0


def test_repeated_start_cancels_ticker_and_stops_off_loop(client):
    test_client, state, tickers = client
    with test_client.websocket_connect("/stream") as ws:
        for target in ["es", "en", "es"]:
            ws.send_json({"type": "session.start", "target": target})
            ready = ws.receive_json()
            assert ready["type"] == "session.ready"
            assert ready["target"] == target
        ws.send_json({"type": "session.stop"})
    assert tickers["max"] == 1
    assert tickers["active"] == 0
    assert state.sessions == 0
    assert len(FakeAsr.stopped) == 3
    assert all("portal" not in thread for thread in FakeAsr.stopped)
