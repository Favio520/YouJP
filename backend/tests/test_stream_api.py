"""Exercise the real WebSocket route and MT worker, without loading ASR models."""

import asyncio
import struct
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import youjp.main as server
from youjp.config import Settings
from youjp.mt.base import Translation
from youjp.obs.metrics import MetricsCollector
from youjp.ws.protocol import APP_VERSION, PROTOCOL_VERSION, AsrFinal

EXTENSION_ORIGIN = "chrome-extension://" + "a" * 32


def extension_socket(client):
    return client.websocket_connect("/stream", headers={"origin": EXTENSION_ORIGIN})


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
        # Un trabajador anterior puede acabar tarde: su emisor debe estar cerrado.
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
    # Sin lifespan: los recursos pesados ya se han sustituido explícitamente.
    test_client = TestClient(server.app)
    try:
        yield test_client, state, tickers
    finally:
        test_client.close()


def audio(ws):
    ws.send_bytes(struct.pack("<BBBBIII", 0xA5, 1, 0, 0, 0, 0, 0) + b"\0" * 3200)


def test_live_target_switch_and_invalid_target_recovery(client):
    test_client, state, _ = client
    with extension_socket(test_client) as ws:
        ws.send_json({"type": "session.start", "target": "es", "protocol_version": PROTOCOL_VERSION})
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
    with extension_socket(test_client) as ws:
        for target in ["es", "en", "es"]:
            ws.send_json({"type": "session.start", "target": target, "protocol_version": PROTOCOL_VERSION})
            ready = ws.receive_json()
            assert ready["type"] == "session.ready"
            assert ready["target"] == target
            assert ready["protocol_version"] == PROTOCOL_VERSION
            assert ready["app_version"] == APP_VERSION
        ws.send_json({"type": "session.stop"})
    assert tickers["max"] == 1
    assert tickers["active"] == 0
    assert state.sessions == 0
    assert len(FakeAsr.stopped) == 3
    assert all("portal" not in thread for thread in FakeAsr.stopped)


@pytest.mark.parametrize("fields", [{}, {"protocol_version": 1}, {"protocol_version": 999}])
def test_incompatible_handshake_closes_without_allocating_workers(client, fields):
    test_client, state, tickers = client
    with extension_socket(test_client) as ws:
        ws.send_json({"type": "session.start", **fields})
        error = ws.receive_json()
        assert error["code"] == "protocol_mismatch"
        assert error["fatal"] is True
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1002
    assert state.sessions == 0
    assert tickers["max"] == 0
    assert not FakeAsr.stopped


@pytest.mark.parametrize("origin", [None, "null", "https://example.com", "http://127.0.0.1:8770",
                                     "chrome-extension://not-an-id", EXTENSION_ORIGIN + "/extra"])
def test_stream_rejects_untrusted_origins_before_allocating_workers(client, origin):
    test_client, state, tickers = client
    headers = {} if origin is None else {"origin": origin}
    with test_client.websocket_connect("/stream", headers=headers) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008
    assert state.sessions == 0
    assert tickers["max"] == 0
    assert not FakeAsr.stopped


def test_health_identifies_version_and_actual_capabilities(client, monkeypatch):
    test_client, state, _ = client
    state.engine = SimpleNamespace(is_loaded=True, word_timestamps=True)
    state.dictionary = None
    monkeypatch.setattr(server, "read_gpu", lambda: None)
    health = test_client.get('/health').json()
    assert health['service'] == 'youjp'
    assert health['app_version'] == APP_VERSION
    assert health['protocol_version'] == PROTOCOL_VERSION
    assert health['mt_provider'] == 'test'
    assert health['dictionary_loaded'] is False
