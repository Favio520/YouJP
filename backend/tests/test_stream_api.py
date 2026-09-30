"""Exercise the real WebSocket route and MT worker, without loading ASR models."""

import asyncio
import struct
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

import youjp.main as server
from youjp.config import DEFAULT_ALLOWED_EXTENSION_IDS, Settings
from youjp.mt.base import Translation
from youjp.obs.metrics import MetricsCollector
from youjp.ws.protocol import APP_VERSION, PROTOCOL_VERSION, AsrFinal

EXTENSION_ORIGIN = f"chrome-extension://{DEFAULT_ALLOWED_EXTENSION_IDS}"


def extension_socket(client):
    return client.websocket_connect("/stream", headers={"origin": EXTENSION_ORIGIN,
                                                         "host": "127.0.0.1:8770"})


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
    state = SimpleNamespace(settings=Settings(_env_file=None,
                                             allowed_extension_ids=DEFAULT_ALLOWED_EXTENSION_IDS), translator=Translator(),
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
    test_client = TestClient(server.app, base_url="http://127.0.0.1:8770")
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


def test_session_stop_closes_the_socket(client):
    test_client, state, _ = client
    with extension_socket(test_client) as ws:
        ws.send_json({"type": "session.stop"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1000
    assert state.sessions == 0


def test_failed_session_start_closes_the_socket(client):
    test_client, state, _ = client

    def unavailable_vad():
        raise FileNotFoundError("missing VAD model")

    state.new_vad = unavailable_vad
    with extension_socket(test_client) as ws:
        ws.send_json({"type": "session.start", "protocol_version": PROTOCOL_VERSION})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1011
    assert state.sessions == 0


def test_failed_sender_does_not_leave_receive_and_session_alive(client):
    _, state, _ = client

    class BrokenSocket:
        headers = {"origin": EXTENSION_ORIGIN}
        client = "test"
        closed = False

        async def accept(self):
            pass

        async def receive(self):
            if not hasattr(self, "received"):
                self.received = True
                return {"type": "websocket.receive", "text": '{"type":"ping","t":1}'}
            await asyncio.Event().wait()

        async def send_text(self, _):
            raise OSError("connection broken")

        async def close(self, **kwargs):
            self.closed = True

    socket = BrokenSocket()

    async def run():
        await asyncio.wait_for(server.stream(socket), timeout=2)

    asyncio.run(run())
    assert socket.closed
    assert state.sessions == 0


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
                                     "chrome-extension://not-an-id", EXTENSION_ORIGIN + "/extra",
                                     "chrome-extension://" + "b" * 32])
def test_stream_rejects_untrusted_origins_before_allocating_workers(client, origin):
    test_client, state, tickers = client
    headers = {"host": "127.0.0.1:8770"}
    if origin is not None:
        headers["origin"] = origin
    with test_client.websocket_connect("/stream", headers=headers) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008
    assert state.sessions == 0
    assert tickers["max"] == 0
    assert not FakeAsr.stopped


def test_stream_allows_configured_ids_and_explicit_development_fallback(client):
    test_client, state, _ = client
    other_origin = "chrome-extension://" + "b" * 32
    state.settings = state.settings.model_copy(update={"allowed_extension_ids": "b" * 32})
    with test_client.websocket_connect("/stream", headers={"origin": other_origin,
                                                           "host": "127.0.0.1:8770"}) as ws:
        ws.send_json({"type": "ping", "t": 7})
        assert ws.receive_json() == {"type": "pong", "t": 7}
        ws.send_json({"type": "session.stop"})
    with extension_socket(test_client) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
        assert closed.value.code == 1008

    state.settings = state.settings.model_copy(update={"allowed_extension_ids": ""})
    with test_client.websocket_connect("/stream", headers={"origin": other_origin,
                                                           "host": "127.0.0.1:8770"}) as ws:
        ws.send_json({"type": "ping", "t": 8})
        assert ws.receive_json() == {"type": "pong", "t": 8}
        ws.send_json({"type": "session.stop"})
    assert state.sessions == 0


def test_rejected_origin_is_logged_without_raw_newlines(client, caplog):
    test_client, _, _ = client
    with caplog.at_level("WARNING", logger="youjp.main"):
        with test_client.websocket_connect("/stream", headers={"origin": "https://evil.example",
                                                               "host": "127.0.0.1:8770"}) as ws:
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
    [record] = [r for r in caplog.records if "rechazada" in r.getMessage()]
    assert "'https://evil.example'" in record.getMessage()
    assert "YOUJP_ALLOWED_EXTENSION_IDS" in record.getMessage()


def test_extension_ids_are_normalized_at_startup():
    settings = Settings(_env_file=None, allowed_extension_ids=f" {DEFAULT_ALLOWED_EXTENSION_IDS} , {'b' * 32} ,")
    assert settings.allowed_extension_ids == f"{DEFAULT_ALLOWED_EXTENSION_IDS},{'b' * 32}"
    assert settings.extension_ids == {DEFAULT_ALLOWED_EXTENSION_IDS, "b" * 32}
    assert server._trusted_origin("chrome-extension://" + "b" * 32, settings.extension_ids)
    assert Settings(_env_file=None, allowed_extension_ids="  ").extension_ids == frozenset()


@pytest.mark.parametrize("value", [" , ", "abc", "q" * 32, DEFAULT_ALLOWED_EXTENSION_IDS.upper(),
                                   f"{DEFAULT_ALLOWED_EXTENSION_IDS},chrome-extension://{'b' * 32}"])
def test_malformed_extension_ids_fail_at_startup(value):
    with pytest.raises(ValidationError, match="YOUJP_ALLOWED_EXTENSION_IDS"):
        Settings(_env_file=None, allowed_extension_ids=value)


@pytest.mark.parametrize(("host", "expected"), [
    ("127.0.0.1", ["127.0.0.1", "localhost"]),
    ("0.0.0.0", ["127.0.0.1", "localhost"]),
    ("192.168.1.20", ["127.0.0.1", "localhost", "192.168.1.20"]),
])
def test_trusted_hosts_follow_listen_address(host, expected):
    assert Settings(_env_file=None, host=host).trusted_hosts == expected


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
    assert test_client.get('/health', headers={"host": "localhost:8770"}).status_code == 200
    assert test_client.get('/health', headers={"host": "attacker.example:8770"}).status_code == 400
