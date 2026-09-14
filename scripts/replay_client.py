"""Cliente de repeticion: ejercita el servidor entero sin navegador.

Hace exactamente lo que hara la extension -- abrir el WebSocket, anunciar la
sesion y enviar PCM de 16 kHz en tramas de 100 ms al ritmo del reloj -- pero
leyendo de un WAV. Permite depurar el protocolo, el codec, el backpressure y la
latencia extremo a extremo antes de que exista una sola linea de TypeScript, y
despues sirve para saber de que lado esta un fallo.

    cd backend
    uv run python ../scripts/replay_client.py ../bench/samples/11-noticias-entrevista.wav
    uv run python ../scripts/replay_client.py <wav> --seek-at 20   # prueba el flush
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import websockets  # noqa: E402
from rich.console import Console  # noqa: E402

HEADER = struct.Struct("<BBBBIII")
MAGIC, VERSION = 0xA5, 1
FLAG_LIVE, FLAG_DISCONTINUITY = 1, 2

console = Console()


def build_frame(seq: int, media_ms: int, capture_ms: int, pcm: np.ndarray, flags: int) -> bytes:
    header = HEADER.pack(MAGIC, VERSION, flags, 0, seq, media_ms, capture_ms)
    data = np.round(np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2")
    return header + data.tobytes()


async def receive_loop(ws, started: float, stats: dict) -> None:
    async for raw in ws:
        msg = json.loads(raw)
        kind = msg["type"]

        if kind == "session.ready":
            console.print(
                f"[dim]sesion {msg['session_id']} · {msg['asr_model']} en "
                f"{msg['device']}/{msg['compute_type']}[/dim]"
            )
        elif kind == "asr.partial":
            stats["partials"] += 1
            texto = msg["committed"] + msg["tentative"]
            console.print(f"[dim]  ~ {texto[-60:]}[/dim]", highlight=False)
        elif kind == "asr.final":
            stats["finals"] += 1
            stats["latencies"].append(msg["latency_ms"])
            t = msg["media_start_ms"] / 1000
            console.print(
                f"[bold]{t:6.1f}s[/bold] {msg['text']}  "
                f"[dim]{msg['latency_ms']:.0f} ms[/dim]",
                highlight=False,
            )
        elif kind == "metrics.tick":
            stats["last_metrics"] = msg
        elif kind == "error":
            console.print(f"[red]error {msg['code']}: {msg['message'][:200]}[/red]")


async def run(path: Path, url: str, seek_at: float | None, live: bool) -> int:
    pcm, rate = sf.read(str(path), dtype="float32", always_2d=True)
    if rate != 16_000:
        console.print(f"[red]{path.name} esta a {rate} Hz, se esperan 16 000[/red]")
        return 1
    audio = pcm.mean(axis=1).astype(np.float32)

    frame_ms = 100
    step = 16_000 * frame_ms // 1000
    stats = {"partials": 0, "finals": 0, "latencies": [], "last_metrics": None}

    console.rule(f"[bold]{path.name}[/bold]  {len(audio) / 16_000:.1f} s")
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "session.start",
            "video_id": path.stem,
            "is_live": live,
            "media_time_ms": 0,
            "source": "ja",
            "target": "es",
        }))
        receiver = asyncio.create_task(receive_loop(ws, time.perf_counter(), stats))

        t0 = time.perf_counter()
        seq = 0
        seeked = False
        media_offset = 0
        flags = FLAG_LIVE if live else 0
        for offset in range(0, len(audio), step):
            chunk = audio[offset : offset + step]
            if len(chunk) < step:
                chunk = np.pad(chunk, (0, step - len(chunk)))

            elapsed_ms = seq * frame_ms
            frame_flags = flags
            if seek_at is not None and not seeked and elapsed_ms >= seek_at * 1000:
                # Simula un salto de un minuto hacia delante en el reproductor.
                # La extension real hace dos cosas, y aqui se replican las dos:
                # manda control.flush y, a partir de ahi, sella las tramas con
                # la nueva posicion del video. Solo con el mensaje no basta --
                # las tramas son la fuente de verdad del tiempo de medio.
                nueva_pos = elapsed_ms + 60_000
                media_offset = nueva_pos - elapsed_ms
                await ws.send(json.dumps({
                    "type": "control.flush", "reason": "seek",
                    "media_time_ms": nueva_pos,
                }))
                console.print(
                    f"[yellow]-- seek simulado: {elapsed_ms / 1000:.0f}s -> "
                    f"{nueva_pos / 1000:.0f}s --[/yellow]"
                )
                frame_flags |= FLAG_DISCONTINUITY
                seeked = True

            target = t0 + (elapsed_ms + frame_ms) / 1000
            if (delay := target - time.perf_counter()) > 0:
                await asyncio.sleep(delay)

            await ws.send(build_frame(
                seq, elapsed_ms + media_offset,
                int((time.perf_counter() - t0) * 1000), chunk, frame_flags
            ))
            seq += 1

        # Margen para que salga la cola del pipeline antes de cerrar.
        await asyncio.sleep(3.0)
        await ws.send(json.dumps({"type": "session.stop"}))
        receiver.cancel()

    console.rule("[bold]resumen")
    lat = sorted(stats["latencies"])
    if lat:
        console.print(
            f"frases {len(lat)} · parciales {stats['partials']} · "
            f"latencia p50 {lat[len(lat) // 2]:.0f} ms · max {lat[-1]:.0f} ms"
        )
    else:
        console.print(f"sin frases · parciales {stats['partials']}")
    if m := stats["last_metrics"]:
        console.print(
            f"[dim]buffer {m['audio_buffer_ms']:.0f} ms · descartadas "
            f"{m['dropped_audio_chunks']} · pasadas {m['passes']} · "
            f"saltadas {m['skipped_silent']} · VRAM {m['gpu_used_mb']:.0f} MiB[/dim]"
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--url", default="ws://127.0.0.1:8770/stream")
    parser.add_argument("--seek-at", type=float, help="simula un seek en el segundo N")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.wav, args.url, args.seek_at, args.live)))


if __name__ == "__main__":
    main()
