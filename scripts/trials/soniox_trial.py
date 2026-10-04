"""Isolated, bounded Soniox Japanese -> Spanish streaming trial.

Dry run (no network):
    backend/.venv/Scripts/python.exe scripts/trials/soniox_trial.py

After configuring SONIOX_API_KEY in the local process environment:
    backend/.venv/Scripts/python.exe scripts/trials/soniox_trial.py --execute-cloud

The default smoke sends the first 30 seconds of the existing news WAV.
The aggregate audio cap is 120 seconds. No production settings are changed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "wss://stt-rt.soniox.com/transcribe-websocket"
OUTPUT = ROOT / "bench/trials/20261003/soniox"
DOCS = {
    "models": "https://soniox.com/docs/stt/models",
    "websocket": "https://soniox.com/docs/api-reference/stt/websocket-api",
    "translation": "https://soniox.com/docs/translation/stt-translation/rt-translation",
    "pricing": "https://soniox.com/pricing",
    "languages": "https://soniox.com/docs/stt/concepts/supported-languages",
}


def inspect_clip(path: Path, seconds: float) -> dict:
    with wave.open(str(path), "rb") as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getcomptype()) != (
            16000, 1, 2, "NONE"
        ):
            raise ValueError(f"{path.name}: requires 16 kHz mono PCM 16-bit WAV")
        frames = min(audio.getnframes(), math.floor(seconds * audio.getframerate()))
        data = audio.readframes(frames)
        return {
            "path": str(path.resolve()),
            "sample": path.name,
            "available_audio_s": audio.getnframes() / audio.getframerate(),
            "trial_audio_s": frames / audio.getframerate(),
            "frames": frames,
            "pcm_sha256": hashlib.sha256(data).hexdigest(),
        }


def configuration() -> dict:
    return {
        "model": "stt-rt-v5",
        "audio_format": "pcm_s16le",
        "sample_rate": 16000,
        "num_channels": 1,
        "language_hints": ["ja"],
        "enable_language_identification": True,
        "enable_endpoint_detection": True,
        "translation": {"type": "one_way", "target_language": "es"},
    }


def load_key() -> str:
    key = os.environ.get("SONIOX_API_KEY", "").strip()
    if not key and (ROOT / ".env").is_file():
        # python-dotenv is already installed by the backend's pydantic-settings.
        # Read only this key from the workspace, without evaluating shell code.
        from dotenv import dotenv_values

        key = (dotenv_values(ROOT / ".env").get("SONIOX_API_KEY") or "").strip()
    return key


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_response(value: object, secret: str) -> object:
    # Do not persist a credential even if an upstream error echoes it.
    if isinstance(value, dict):
        return {k: safe_response(v, secret) for k, v in value.items() if k != "api_key"}
    if isinstance(value, list):
        return [safe_response(v, secret) for v in value]
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    return value


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 1)


async def send_audio(ws, clip: dict, started: float) -> dict:
    sent_frames = 0
    with wave.open(clip["path"], "rb") as audio:
        while sent_frames < clip["frames"]:
            # Send each 100 ms frame after that audio interval has elapsed.
            # This includes capture buffering in the token arrival measurements.
            count = min(1600, clip["frames"] - sent_frames)
            await asyncio.sleep(max(0.0, started + (sent_frames + count) / 16000 - time.perf_counter()))
            data = audio.readframes(count)
            if len(data) != count * 2:
                raise ValueError("Input audio changed after preparation")
            await ws.send(data)
            sent_frames += count
    await ws.send("")
    return {"sent_audio_s": sent_frames / 16000, "last_send_elapsed_ms": (time.perf_counter() - started) * 1000}


async def receive_results(ws, started: float, events: list[dict], secret: str) -> None:
    async for message in ws:
        response = json.loads(message)
        elapsed = (time.perf_counter() - started) * 1000
        events.append({"received_elapsed_ms": round(elapsed, 1), "response": safe_response(response, secret)})
        if response.get("error_code") is not None:
            raise RuntimeError("Soniox server returned an error; see sanitized events")
        if response.get("finished"):
            return
    raise RuntimeError("Connection closed before finished response")


def summarize_events(events: list[dict]) -> dict:
    final_tokens = []
    latencies = []
    first_source = first_translation = first_final_translation = None
    for event in events:
        received = event["received_elapsed_ms"]
        for token in event["response"].get("tokens", []):
            text = token.get("text", "")
            if not text or text in {"<end>", "<fin>"}:
                continue
            translated = token.get("translation_status") == "translation"
            if translated:
                if first_translation is None:
                    first_translation = received
                if token.get("is_final") and first_final_translation is None:
                    first_final_translation = received
            elif first_source is None:
                first_source = received
            if token.get("is_final"):
                final_tokens.append({**token, "received_elapsed_ms": received})
                if not translated and isinstance(token.get("end_ms"), (int, float)):
                    latencies.append(received - token["end_ms"])
    return {
        "first_source_token_elapsed_ms": first_source,
        "first_translation_token_elapsed_ms": first_translation,
        "first_final_translation_token_elapsed_ms": first_final_translation,
        "source_final_token_latency_ms": {
            "count": len(latencies),
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "p95": percentile(latencies, 0.95),
            "definition": "arrival elapsed minus source token end_ms; includes 100 ms capture pacing, network and model finalization",
        },
        "original_text": "".join(t.get("text", "") for t in final_tokens if t.get("translation_status") != "translation"),
        "translation_text": "".join(t.get("text", "") for t in final_tokens if t.get("translation_status") == "translation"),
        "final_tokens": final_tokens,
        "response_count": len(events),
        "limits": "Translated tokens have no audio timestamps and no 1:1 source mapping. Translation first-token elapsed is startup time, not sentence latency. No reference accuracy or application UI latency is measured.",
    }


async def run_clip(clip: dict, key: str, output: Path) -> dict:
    from websockets.asyncio.client import connect
    from websockets.exceptions import WebSocketException

    events: list[dict] = []
    result = {"clip": clip, "configuration": configuration(), "status": "failed"}
    started = time.perf_counter()
    tasks = []
    try:
        async with connect(ENDPOINT, open_timeout=15, close_timeout=5, max_size=2**22) as ws:
            await ws.send(json.dumps({**configuration(), "api_key": key}))
            result["connect_ms"] = round((time.perf_counter() - started) * 1000, 1)
            started = time.perf_counter()
            tasks = [asyncio.create_task(send_audio(ws, clip, started)), asyncio.create_task(receive_results(ws, started, events, key))]
            # The bounded audio is followed by at most 30 seconds for finalization.
            sent, _ = await asyncio.wait_for(asyncio.gather(*tasks), timeout=clip["trial_audio_s"] + 30)
            result.update(sent)
            result["status"] = "completed"
    except (WebSocketException, OSError, TimeoutError, ValueError, RuntimeError) as error:
        # Exception strings may contain secrets from authentication or transport libraries.
        result["error_type"] = type(error).__name__
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        result["wall_s"] = round(time.perf_counter() - started, 3)
        result["metrics"] = summarize_events(events)
        save_json(output.with_suffix(".events.json"), events)
        save_json(output.with_suffix(".json"), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, nargs="+", default=[ROOT / "bench/samples/10-noticias-apertura.wav"])
    parser.add_argument("--seconds-per-clip", type=float, default=30)
    parser.add_argument("--execute-cloud", action="store_true", help="Send bounded sample audio to paid Soniox API; otherwise plan only")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if not math.isfinite(args.seconds_per_clip) or not 0 < args.seconds_per_clip <= 120:
        parser.error("--seconds-per-clip must be > 0 and <= 120")
    try:
        clips = [inspect_clip(path, args.seconds_per_clip) for path in args.audio]
    except (OSError, ValueError, wave.Error) as error:
        parser.error(str(error))
    total_s = sum(c["trial_audio_s"] for c in clips)
    if total_s > 120:
        parser.error("aggregate requested audio exceeds the 120-second smoke limit")
    key = load_key()
    plan = {
        "status": "prepared_only",
        "cloud_request_made": False,
        "key_present": bool(key),
        "model": "stt-rt-v5",
        "endpoint": ENDPOINT,
        "clips": clips,
        "total_audio_s": total_s,
        "configuration": configuration(),
        "pricing_checked_utc_date": "2026-10-03",
        "estimated_cost_usd": round(total_s / 3600 * 0.18, 6),
        "estimate_basis": "Approximation: 30,000 audio tokens/h at $2/M plus 15,000 source and 15,000 translated text tokens/h at $4/M. Billing is token-based; actual token density/session duration can differ. No hard dollar cap is supported by this harness.",
        "docs": DOCS,
        "next_step": "Set SONIOX_API_KEY locally in the process environment or workspace .env; rerun with --execute-cloud when the cloud trial is authorized.",
    }
    if args.execute_cloud and not key:
        plan["status"] = "blocked_missing_api_key"
    save_json(args.output_dir / "plan.json", plan)
    print(json.dumps({k: plan[k] for k in ("status", "cloud_request_made", "key_present", "total_audio_s", "estimated_cost_usd")}, ensure_ascii=False))
    if not args.execute_cloud:
        return 0
    if not key:
        print("SONIOX_API_KEY is absent; no audio was sent. Configure it locally; do not paste it into chat.", file=sys.stderr)
        return 2

    async def run_all() -> list[dict]:
        results = []
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        for number, clip in enumerate(clips, 1):
            result = await run_clip(clip, key, args.output_dir / f"{stamp}-{number}-{Path(clip['sample']).stem}")
            results.append(result)
            print(json.dumps({"sample": clip["sample"], "status": result["status"]}))
            if result["status"] != "completed":
                break  # No automatic paid retries after authentication or network failures.
        save_json(args.output_dir / f"{stamp}-summary.json", results)
        return results

    results = asyncio.run(run_all())
    return 0 if len(results) == len(clips) and all(r["status"] == "completed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
