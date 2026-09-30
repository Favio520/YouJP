"""El arranque parcial y los errores de cierre no deben dejar recursos vivos."""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

import youjp.main as server
from youjp.config import Settings


def make_state(monkeypatch):
    events = []
    settings = Settings(_env_file=None, mt_provider="none")
    state = SimpleNamespace(
        settings=settings,
        engine=SimpleNamespace(
            load=lambda: events.append("asr.load"),
            warmup=lambda: events.append("asr.warmup"),
            unload=lambda: events.append("asr.unload"),
        ),
        tokenizer=SimpleNamespace(load=lambda: events.append("tokenizer.load")),
        translator=SimpleNamespace(unload=lambda: events.append("mt.unload")),
        dictionary=None,
    )
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    monkeypatch.setattr(server, "setup_logging", lambda _: None)
    monkeypatch.setattr(server, "AppState", lambda _: state)
    monkeypatch.setattr(server, "_warn_if_vram_tight", lambda: None)
    return state, events


def test_startup_failure_releases_loaded_models(monkeypatch):
    state, events = make_state(monkeypatch)

    def fail():
        raise RuntimeError("warmup failed")

    state.engine.warmup = fail

    async def run():
        async with server.lifespan(FastAPI()):
            pytest.fail("startup should have failed")

    with pytest.raises(RuntimeError, match="warmup failed"):
        asyncio.run(run())
    assert events == ["asr.load", "mt.unload", "asr.unload"]


def test_corrupt_optional_dictionary_does_not_prevent_startup(monkeypatch):
    state, events = make_state(monkeypatch)

    def fail():
        raise sqlite3.DatabaseError("database disk image is malformed")

    dictionary = SimpleNamespace(stats=fail, close=lambda: events.append("dictionary.close"))
    monkeypatch.setattr(server, "Dictionary", lambda *a, **kw: dictionary)

    async def run():
        async with server.lifespan(FastAPI()):
            assert state.dictionary is None

    asyncio.run(run())
    assert events[-3:] == ["dictionary.close", "mt.unload", "asr.unload"]


def test_cleanup_continues_when_ticker_and_worker_fail():
    stopped = []

    def fail_stop():
        stopped.append("asr")
        raise RuntimeError("worker failure")

    async def fail_tick():
        raise RuntimeError("metrics failure")

    async def run():
        ticker = asyncio.create_task(fail_tick())
        await asyncio.sleep(0)
        await server._stop_session(
            ticker,
            SimpleNamespace(stop=fail_stop),
            SimpleNamespace(stop=lambda: stopped.append("mt")),
            SimpleNamespace(stop=lambda: stopped.append("nlp")),
        )

    asyncio.run(run())
    assert stopped == ["asr", "mt", "nlp"]
