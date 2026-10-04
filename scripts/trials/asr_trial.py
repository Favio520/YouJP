"""Isolated real-WAV ASR trials. Never changes YouJP defaults or downloads models.

Run with backend/.venv/Scripts/python.exe. The Nemotron mode owns its local
server and stops it in finally; Whisper uses the existing production pipeline.
Fast mode measures elapsed/RTF only. Realtime mode paces audio and records final
arrival minus each recognizer's own end timestamp (not a human reference).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from youjp.obs.gpu import GpuMonitor
from youjp.obs.metrics import MetricsCollector, Series


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def wave_data(path: Path):
    import numpy as np
    import soundfile as sf

    data, rate = sf.read(path, dtype="float32", always_2d=True)
    if rate != 16000:
        raise ValueError(f"{path}: expected 16000Hz, got {rate}")
    mono = data.mean(axis=1)
    pcm16 = np.clip(mono * 32768, -32768, 32767).astype("<i2").tobytes()
    return pcm16, len(mono) / rate


def summary(values: list[float], name: str) -> dict | None:
    if not values:
        return None
    return Series(name, values=values).summary()


def verify_timestamps(finals: list[dict], duration: float) -> dict:
    """Check observed final payloads, not the requested timestamp option."""
    spoken_finals = [final for final in finals if final.get("text", "").strip()]
    reasons = []
    previous_start, previous_end = -1.0, -1.0
    checked_words = 0
    for final_index, final in enumerate(spoken_finals):
        words = final.get("words") or []
        if not words:
            reasons.append(f"final {final_index}: text present but words missing")
        for word_index, word in enumerate(words):
            label = f"final {final_index}, word {word_index}"
            if not str(word.get("word", word.get("text", ""))).strip():
                reasons.append(f"{label}: word text empty")
            try:
                start, end = float(word["start"]), float(word["end"])
            except (KeyError, TypeError, ValueError):
                reasons.append(f"{label}: start/end absent or nonnumeric")
                continue
            checked_words += 1
            if not math.isfinite(start) or not math.isfinite(end):
                reasons.append(f"{label}: nonfinite timestamp")
            elif start < 0 or end < start or end > duration + 0.5:
                reasons.append(f"{label}: out-of-bounds interval {start}-{end}")
            elif start < previous_start or end < previous_end:
                reasons.append(f"{label}: timestamps decrease across the stream")
            previous_start, previous_end = start, end
    verified = bool(spoken_finals) and bool(checked_words) and not reasons
    single_whole_phrase = sum(
        len(final.get("words") or []) == 1
        and str(
            final["words"][0].get("word", final["words"][0].get("text", ""))
        ).strip()
        == final["text"].strip()
        for final in spoken_finals
    )
    return {
        "timestamps_verified": verified if spoken_finals else None,
        "status": "verified"
        if verified
        else "invalid"
        if spoken_finals
        else "no_speech_text",
        "text_finals": len(spoken_finals),
        "checked_words": checked_words,
        "single_whole_phrase_word_finals": single_whole_phrase,
        "all_words_are_whole_phrase": bool(spoken_finals)
        and single_whole_phrase == len(spoken_finals),
        "end_bound_tolerance_s": 0.5,
        "issues": reasons,
        "note": "Validity of supplied intervals only; no human alignment reference.",
    }


def sample_report(
    path: Path, duration: float, wall: float, events: list, finals: list, realtime: bool
) -> dict:
    timestamps = verify_timestamps(finals, duration)
    latencies = (
        [f["latency_ms"] for f in finals if f.get("latency_ms") is not None]
        if timestamps["timestamps_verified"]
        else []
    )
    return {
        "sample": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "audio_s": duration,
        "wall_s": wall,
        "overall_rtf": wall / duration,
        "text": "".join(f["text"] for f in finals),
        "finals": finals,
        "timestamp_validation": timestamps,
        "partial_count": sum(e.get("kind") == "partial" for e in events),
        "first_partial_s": next(
            (e["arrival_s"] for e in events if e.get("kind") == "partial"), None
        ),
        "latency_ms": summary(latencies, "final_arrival_minus_recognizer_end_ms")
        if realtime
        else None,
        "events": events,
    }


def run_whisper(args, paths: list[Path], report: dict) -> None:
    from youjp.asr.engine import WhisperEngine
    from youjp.audio.source import FileSource
    from youjp.audio.vad import SileroVAD, VADGate
    from youjp.config import get_settings
    from youjp.pipeline.streaming import StreamingSession

    settings = get_settings().model_copy(deep=True)
    settings.asr_model = args.whisper_model
    settings.asr_device = args.device.split(":")[0]
    settings.asr_compute_type = args.compute_type
    # Capability already proven for turbo; avoid a probe/second process during trial.
    settings.asr_word_timestamps = "on"
    report["config"] = {
        "asr_model": settings.asr_model,
        "device": settings.asr_device,
        "compute_type": settings.asr_compute_type,
        "beam_size": settings.asr_beam_size,
        "word_timestamps": True,
        "vad_min_silence_ms": settings.vad_min_silence_ms,
        "min_chunk_s": settings.min_chunk_s,
        "buffer_trim_s": settings.buffer_trim_s,
    }
    engine = WhisperEngine(settings)
    load_start = time.perf_counter()
    try:
        engine.load()
        report["model_load_ms"] = (time.perf_counter() - load_start) * 1000
        report["warmup_ms"] = engine.warmup()
        for path in paths:
            source = FileSource(
                path,
                sample_rate=settings.sample_rate,
                frame_ms=settings.frame_ms,
                realtime=not args.fast,
            )
            vad = SileroVAD(settings.vad_model, sample_rate=settings.sample_rate)
            gate = VADGate(
                vad,
                threshold=settings.vad_threshold,
                release_threshold=settings.vad_release_threshold,
                min_silence_ms=settings.vad_min_silence_ms,
                speech_pad_ms=settings.vad_speech_pad_ms,
            )
            metrics = MetricsCollector()
            events, finals = [], []
            started = time.perf_counter()

            def on_partial(update, events=events, started=started):
                events.append(
                    {
                        "kind": "partial",
                        "arrival_s": time.perf_counter() - started,
                        "committed": update.committed,
                        "tentative": update.tentative,
                    }
                )

            def on_final(update, events=events, finals=finals, started=started):
                arrival = time.perf_counter() - started
                final = {
                    "text": update.sentence.text,
                    "start_s": update.sentence.start,
                    "end_s": update.sentence.end,
                    "arrival_s": arrival,
                    "latency_ms": arrival * 1000 - update.sentence.end * 1000
                    if not args.fast
                    else None,
                    "reason": update.sentence.reason,
                    "words": [asdict(w) for w in update.sentence.words],
                }
                finals.append(final)
                events.append({"kind": "final", **final})

            session = StreamingSession(
                settings,
                engine,
                gate,
                metrics=metrics,
                on_partial=on_partial,
                on_final=on_final,
            )
            for frame in source.frames():
                session.push(frame)
            session.finish()
            item = sample_report(
                path,
                source.duration_s,
                time.perf_counter() - started,
                events,
                finals,
                not args.fast,
            )
            item["stats"] = asdict(session.stats)
            item["metrics"] = metrics.as_dict()
            report["samples"].append(item)
            write_json(args.output, report)
            print(
                f"{path.name}: {item['wall_s']:.2f}s, {len(finals)} finals", flush=True
            )
    finally:
        engine.unload()


async def nemo_sample(args, path: Path) -> dict:
    import websockets

    pcm, duration = wave_data(path)
    events, finals = [], []
    sent_audio_s = 0.0
    commit_sent = False
    committed = False
    last_received = time.perf_counter()
    uri = f"ws://127.0.0.1:{args.port}/v1/audio/transcriptions/realtime"
    async with websockets.connect(uri, open_timeout=10, max_size=8 * 1024 * 1024) as ws:
        created = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if created.get("type") != "session.created":
            raise RuntimeError(f"Unexpected first event: {created}")
        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "sample_rate": 16000,
                        "language": "ja-JP",
                        "word_timestamps": True,
                        "endpointing_ms": args.endpointing_ms,
                        "automatic_punctuation": True,
                        "verbatim": True,
                    },
                }
            )
        )
        updated = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if updated.get("type") != "session.updated":
            raise RuntimeError(f"Session update failed: {updated}")
        started = time.perf_counter()

        async def receive():
            nonlocal committed, last_received
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), 0.5)
                except asyncio.TimeoutError:
                    quiet_s = time.perf_counter() - last_received
                    if committed and quiet_s >= 1:
                        return
                    if (
                        commit_sent
                        and time.perf_counter() - started > duration + 30
                        and not args.fast
                    ):
                        raise TimeoutError("No commit/final acknowledgement")
                    continue
                event = json.loads(raw)
                last_received = time.perf_counter()
                kind = event.get("type", "")
                arrival = last_received - started
                row = {"arrival_s": arrival, "sent_audio_s": sent_audio_s, "raw": event}
                if kind.endswith(".delta"):
                    row["kind"] = "partial"
                elif kind.endswith(".completed"):
                    row["kind"] = "final"
                    words = event.get("words") or []
                    end = max(
                        (float(w["end"]) for w in words if "end" in w), default=None
                    )
                    begin = min(
                        (float(w["start"]) for w in words if "start" in w), default=None
                    )
                    final = {
                        "text": event.get("transcript", event.get("text", "")),
                        "start_s": begin,
                        "end_s": end,
                        "arrival_s": arrival,
                        "latency_ms": (arrival - end) * 1000
                        if end is not None and not args.fast
                        else None,
                        "words": words,
                    }
                    finals.append(final)
                elif kind == "input_audio_buffer.committed":
                    committed = True
                elif kind == "error":
                    raise RuntimeError(f"Nemotron runtime error: {event}")
                events.append(row)

        reader = asyncio.create_task(receive())
        step = 16000 * 2 * args.frame_ms // 1000
        try:
            for offset in range(0, len(pcm), step):
                chunk = pcm[offset : offset + step]
                chunk_end_s = (offset + len(chunk)) / (16000 * 2)
                if not args.fast:
                    await asyncio.sleep(
                        max(0, started + chunk_end_s - time.perf_counter())
                    )
                sent_audio_s = chunk_end_s
                await ws.send(chunk)
                # Let the receiver drain events during unpaced sending, too.
                await asyncio.sleep(0)
            send_done = time.perf_counter()
            commit_sent = True
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            await asyncio.wait_for(reader, timeout=120)
        finally:
            if not reader.done():
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
        wall = time.perf_counter() - started
        collector_settle_s = time.perf_counter() - last_received
    result = sample_report(path, duration, wall, events, finals, not args.fast)
    result["audio_send_s"] = send_done - started
    result["collector_settle_s"] = collector_settle_s
    result["stream_rtf_excluding_collector_settle"] = (
        max(0, wall - collector_settle_s) / duration
    )
    return result


def run_nemo(args, paths: list[Path], report: dict) -> None:
    import httpx

    if not args.runtime or not args.model:
        raise ValueError("Nemotron requires --runtime and --model local paths")
    if not args.runtime.is_file() or not args.model.is_file():
        raise FileNotFoundError("Runtime/model file missing; use asr-setup.ps1 first")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError as exc:
            raise RuntimeError(f"Trial port {args.port} is already in use") from exc
    config = {
        "model": str(args.model),
        "device": args.device,
        "rnnt_right_context": args.right_context,
        "endpointing_ms": args.endpointing_ms,
        "frame_ms": args.frame_ms,
        "language": "ja-JP",
        "batching": False,
        "vad": "runtime token-silence endpointing; no external VAD",
        "word_timestamps": "final events",
    }
    report["config"] = config
    command = [
        str(args.runtime),
        "serve",
        "--asr-model",
        str(args.model),
        "--device",
        args.device,
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
        "--asr.streaming.rnnt_right_context",
        str(args.right_context),
        "--asr.batching.enabled=false",
        "--asr.endpointing.enable=true",
        "--asr.endpointing.stop_history_eou_ms",
        str(args.endpointing_ms),
        "--no-ui",
    ]
    report["command"] = command
    environment = os.environ.copy()
    environment["NEMO_SPEECH_MODEL_DIR"] = str(
        ROOT / "models" / "trials" / "nemotron-3.5-asr"
    )
    log_path = args.output.with_suffix(".server.log")
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
            cwd=args.runtime.parent,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        report["server_pid"] = process.pid
        try:
            with httpx.Client(timeout=1, trust_env=False) as client:
                deadline = time.perf_counter() + 90
                while time.perf_counter() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"Nemotron exited with {process.returncode}; see {log_path}"
                        )
                    try:
                        response = client.get(f"http://127.0.0.1:{args.port}/ready")
                        if response.is_success:
                            report["ready"] = response.json()
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                else:
                    raise TimeoutError("Nemotron server not ready in 90 seconds")
                report["model_load_and_server_ready_ms"] = (
                    time.perf_counter() - started
                ) * 1000
                report["version"] = client.get(
                    f"http://127.0.0.1:{args.port}/version"
                ).json()
            import numpy as np
            import soundfile as sf

            warm_path = args.output.parent / "inputs" / "_warmup_silence_2s.wav"
            warm_path.parent.mkdir(exist_ok=True)
            sf.write(
                warm_path, np.zeros(32000, dtype=np.float32), 16000, subtype="PCM_16"
            )
            warm_start = time.perf_counter()
            report["warmup"] = asyncio.run(nemo_sample(args, warm_path))
            report["warmup_ms"] = (time.perf_counter() - warm_start) * 1000
            for path in paths:
                result = asyncio.run(nemo_sample(args, path))
                report["samples"].append(result)
                write_json(args.output, report)
                print(
                    f"{path.name}: {result['wall_s']:.2f}s, {len(result['finals'])} finals",
                    flush=True,
                )
        finally:
            if process.poll() is None:
                report["server_cleanup"] = "terminated_by_harness"
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            else:
                report["server_cleanup"] = "already_exited"
            report["server_exit_code"] = process.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["whisper", "nemotron"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--samples", type=Path, default=ROOT / "bench" / "samples")
    parser.add_argument(
        "--sample", action="append", default=[], help="Repeat to select WAV names"
    )
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--whisper-model", default="large-v3-turbo")
    parser.add_argument("--compute-type", default="int8_float16")
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--frame-ms", type=int, default=100)
    parser.add_argument(
        "--right-context", type=int, choices=[0, 1, 3, 6, 13], default=3
    )
    parser.add_argument("--endpointing-ms", type=int, default=500)
    parser.add_argument(
        "--limit-seconds",
        type=float,
        help="Copy only the opening N seconds into trial inputs",
    )
    args = parser.parse_args()
    paths = (
        [args.samples / name for name in args.sample]
        if args.sample
        else sorted(args.samples.glob("*.wav"))
    )
    if not paths or any(not p.is_file() for p in paths):
        parser.error("No samples or a requested sample is missing")
    if args.frame_ms <= 0:
        parser.error("--frame-ms must be positive")
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    provenance = []
    if args.limit_seconds is not None:
        import soundfile as sf

        if args.limit_seconds <= 0:
            parser.error("--limit-seconds must be positive")
        input_dir = args.output.parent / "inputs"
        input_dir.mkdir(exist_ok=True)
        clipped_paths = []
        for source_path in paths:
            audio, rate = sf.read(source_path, dtype="float32", always_2d=True)
            clipped_path = input_dir / source_path.name
            sf.write(
                clipped_path,
                audio[: round(args.limit_seconds * rate)],
                rate,
                subtype="PCM_16",
            )
            provenance.append(
                {
                    "source": str(source_path),
                    "source_sha256": hashlib.sha256(
                        source_path.read_bytes()
                    ).hexdigest(),
                    "trial_input": str(clipped_path),
                    "limit_seconds": args.limit_seconds,
                }
            )
            clipped_paths.append(clipped_path)
        paths = clipped_paths
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "mode": "fast" if args.fast else "realtime",
        "machine": platform.platform(),
        "python": platform.python_version(),
        "samples": [],
        "status": "running",
        "input_provenance": provenance,
        "limitations": [
            "No human reference transcripts: CER is not measured.",
            "Final latency uses model end times; segmentation differs across providers.",
            "Isolated ASR only; MT/browser live capture are not exercised.",
        ],
    }
    exit_code = 0
    with GpuMonitor(hz=10) as gpu:
        try:
            if args.provider == "whisper":
                run_whisper(args, paths, report)
            else:
                run_nemo(args, paths, report)
            report["status"] = "completed"
        except Exception as exc:  # noqa: BLE001 - preserve failed trial evidence, then exit nonzero
            report["status"] = "failed"
            report["error"] = str(exc)
            report["traceback"] = traceback.format_exc()
            print(report["traceback"], file=sys.stderr)
            exit_code = 1
    report["gpu"] = {
        "name": gpu.device_name,
        "total_mb": gpu.total_mb,
        "baseline_used_mb": gpu.baseline_used_mb,
        "peak_used_mb": gpu.peak_used_mb,
        "increment_mb": gpu.attributable_mb,
        "sample_hz": 10,
        "samples": gpu.samples,
        "contended": gpu.baseline_used_mb > 1500,
        "note": "Total device VRAM sampled by NVML; delta also reflects other processes.",
    }
    write_json(args.output, report)
    print(args.output, flush=True)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
