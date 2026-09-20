"""Owned backend process for the Windows panel, with graceful file-based stop.

No shutdown HTTP endpoint is exposed. The panel signals only its own unique run.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn

from youjp.config import get_settings


async def serve(stop_file: Path) -> None:
    settings = get_settings()
    server = uvicorn.Server(uvicorn.Config(
        "youjp.main:app", host="127.0.0.1", port=settings.port,
        log_level=settings.log_level.lower(), timeout_graceful_shutdown=10,
    ))

    async def watch() -> None:
        while not stop_file.exists():
            await asyncio.sleep(0.25)
        server.should_exit = True

    watcher = asyncio.create_task(watch())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
        stop_file.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-file", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.stop_file))


if __name__ == "__main__":
    main()
