"""Bounded shutdown and seek ordering under backpressure, without models."""

import queue
import sqlite3
import threading
import time
from types import SimpleNamespace

import youjp.ws.session as sessions
from youjp.config import Settings
from youjp.pipeline.analyze import NlpWorker
from youjp.pipeline.translate import MtWorker


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


def test_dropped_audio_reanchors_time_and_translation_context(monkeypatch):
    worker, events, _ = make_asr(monkeypatch, capacity=1)
    entered, release, processed = threading.Event(), threading.Event(), threading.Event()

    def push(item):
        events.append(item.seq)
        if item.seq == 0:
            entered.set()
            release.wait(3)
        else:
            processed.set()

    worker.session.push = push
    worker.start()
    try:
        worker.submit(frame(0))
        assert entered.wait(2)
        worker.submit(frame(1))
        assert not worker.submit(frame(2))
        release.set()
        assert processed.wait(2)
        assert events == [0, "reset", "context-reset", 2]
    finally:
        release.set()
        worker.stop()


def test_sequence_wrap_is_contiguous_audio(monkeypatch):
    worker, events, _ = make_asr(monkeypatch)
    processed = threading.Event()
    worker.session.push = lambda item: (
        events.append(item.seq), processed.set() if item.seq == 0 else None
    )
    worker.submit(frame(0xFFFFFFFF))
    worker.submit(frame(0))
    worker.start()
    try:
        assert processed.wait(2)
        assert events == [0xFFFFFFFF, 0]
    finally:
        worker.stop()


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


def test_workers_can_stop_before_start_after_partial_session_failure(monkeypatch):
    asr, _, _ = make_asr(monkeypatch)
    nlp = NlpWorker(Settings(_env_file=None), SimpleNamespace(dictionary=None), lambda _: None)
    mt = MtWorker(SimpleNamespace(name="test"), lambda _: None)
    for worker in (asr, nlp, mt):
        worker.stop()
        worker.stop()
        assert not worker._thread.is_alive()


def test_nlp_keeps_tokenizing_if_dictionary_warmup_fails():
    output = queue.Queue()
    closed = []

    def unavailable():
        raise sqlite3.OperationalError("dictionary unavailable")

    analyzer = SimpleNamespace(
        dictionary=SimpleNamespace(warmup=unavailable, close=lambda: closed.append(True)),
        analyze=lambda _: [],
    )
    worker = NlpWorker(Settings(_env_file=None), analyzer, output.put_nowait)
    worker.start()
    try:
        worker.submit(1, "日本語")
        assert output.get(timeout=2).segment_id == 1
        assert analyzer.dictionary is None
        assert closed == [True]
    finally:
        worker.stop()


def test_nlp_closes_its_thread_local_dictionary_connection():
    output = queue.Queue()
    closed = []
    analyzer = SimpleNamespace(
        dictionary=SimpleNamespace(
            warmup=lambda: 0,
            close=lambda: closed.append(threading.current_thread().name),
        ),
        analyze=lambda _: [],
    )
    worker = NlpWorker(Settings(_env_file=None), analyzer, output.put_nowait)
    worker.start()
    try:
        worker.submit(1, "日本語")
        output.get(timeout=2)
    finally:
        worker.stop()
    assert closed == ["nlp-worker"]
