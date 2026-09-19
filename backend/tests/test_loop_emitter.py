import asyncio

import pytest

from youjp.ws.protocol import Pong
from youjp.ws.session import LoopEmitter


@pytest.mark.asyncio
async def test_full_outbox_does_not_raise_in_event_loop():
    loop = asyncio.get_running_loop()
    out = asyncio.Queue(maxsize=1)
    emitter = LoopEmitter(loop, out)
    errors = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    try:
        emitter(Pong(t=1))
        emitter(Pong(t=2))
        await asyncio.sleep(0)
        assert errors == []
        assert out.get_nowait().t == 1
    finally:
        loop.set_exception_handler(previous)


@pytest.mark.asyncio
async def test_closed_emitter_drops_already_scheduled_messages():
    out = asyncio.Queue()
    emitter = LoopEmitter(asyncio.get_running_loop(), out)
    emitter(Pong())
    emitter.close()
    await asyncio.sleep(0)
    assert out.empty()
