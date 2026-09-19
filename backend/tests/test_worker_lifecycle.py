"""Bounded shutdown and seek ordering under backpressure, without models."""

import threading
import time
from types import SimpleNamespace

import youjp.ws.session as sessions
from youjp.config import Settings
from youjp.pipeline.analyze import NlpWorker


def make_asr(monkeypatch, capacity=2):
    events = []
    processed = threading.Event()
    session = SimpleNamespace(
        reset=lambda: events.append("reset"),
        push=lambda frame: (events.append(frame.seq), processed.set()),
        finish=lambda: None,
        stats=SimpleNamespace(passes=0, skipped_silent=0),
    )
    monkeypatch.setattr(sessions, "VADGate", lambda *a, **kw: None)
    monkeypatch.setattr(sessions, "StreamingSession", lambda *a, **kw: session)
    worker = sessions.AsrWorker(
        Settings(_env_file=None), None, None, lambda _: None,
        max_queued_frames=capacity, on_reset=lambda: events.append("context-reset"),
    )
    return worker, events, processed


def frame(seq):
    return SimpleNamespace(seq=seq, discontinuity=False)


def test_saturated_audio_cannot_move_flush_behind_new_frames(monkeypatch):
    worker, events, processed = make_asr(monkeypatch)
    worker.submit(frame(0))
    worker.request_flush(1000)
    worker.submit(frame(1))
    assert not worker.submit(frame(2))
    worker.start()
    try:
        assert processed.wait(2)
        assert events == ["reset", "context-reset", 1]
        assert worker._pending_flush is None
    finally:
        worker.stop()


def test_asr_stop_is_bounded_with_full_queue(monkeypatch):
    worker, _, _ = make_asr(monkeypatch, capacity=1)
    entered, release = threading.Event(), threading.Event()
    worker.session.push = lambda _: (entered.set(), release.wait(3))
    worker.start()
    try:
        worker.submit(frame(0))
        assert entered.wait(2)
        worker.submit(frame(1))
        start = time.monotonic()
        worker.stop(timeout=0.02)
        assert time.monotonic() - start < 0.5
        assert not worker.submit(frame(2))
    finally:
        release.set()
        worker._thread.join(2)
    assert not worker._thread.is_alive()


def test_nlp_stop_is_bounded_with_full_queue():
    entered, release = threading.Event(), threading.Event()

    def analyze(_):
        entered.set()
        release.wait(3)
        return []

    worker = NlpWorker(
        Settings(_env_file=None), SimpleNamespace(dictionary=None, analyze=analyze),
        lambda _: None, max_queued=1,
    )
    worker.start()
    try:
        worker.submit(1, "one")
        assert entered.wait(2)
        worker.submit(2, "two")
        start = time.monotonic()
        worker.stop(timeout=0.02)
        assert time.monotonic() - start < 0.5
    finally:
        release.set()
        worker._thread.join(2)
    assert not worker._thread.is_alive()
