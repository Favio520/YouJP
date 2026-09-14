"""Banco de pruebas de la fase 0.

Ejecuta el pipeline completo (VAD + Whisper + LocalAgreement + segmentador)
sobre ficheros WAV y escribe un JSON comparable entre ejecuciones. Es lo que
sustituye las estimaciones del documento de arquitectura por medidas reales.

Dos modos, que miden cosas distintas:

* ``--realtime`` (por defecto): entrega el audio al ritmo del reloj, como un
  directo. Mide **latencia**: cuanto tarda una frase en aparecer.
* ``--fast``: entrega el audio tan rapido como se consuma. Mide **RTF**: si el
  modelo es capaz de seguir el ritmo en esta maquina. Un RTF de 0,3 significa
  que procesa 1 s de audio en 0,3 s, es decir, que le sobra margen.

Uso::

    cd backend
    uv run python ../scripts/bench_latency.py --model large-v3-turbo
    uv run python ../scripts/bench_latency.py --model small --fast
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from youjp.asr.engine import WhisperEngine  # noqa: E402
from youjp.audio.source import FileSource  # noqa: E402
from youjp.audio.vad import SileroVAD, VADGate  # noqa: E402
from youjp.config import get_settings  # noqa: E402
from youjp.obs.gpu import GpuMonitor, read_gpu  # noqa: E402
from youjp.obs.logging import setup_logging  # noqa: E402
from youjp.obs.metrics import MetricsCollector  # noqa: E402
from youjp.pipeline.streaming import FinalUpdate, StreamingSession  # noqa: E402

console = Console()

BUSY_GPU_MB = 1500
"""Linea base por encima de la cual se avisa de que la GPU esta ocupada.

El escritorio de esta maquina consume entre 825 y 1 060 MiB en reposo. Por
encima de 1 500 hay otra aplicacion compitiendo y las medidas dejan de ser
comparables entre ejecuciones.
"""


def run_sample(
    path: Path, settings, engine: WhisperEngine, *, realtime: bool, show: bool
) -> dict:
    source = FileSource(path, sample_rate=settings.sample_rate, frame_ms=settings.frame_ms, realtime=realtime)
    vad = SileroVAD(settings.vad_model, sample_rate=settings.sample_rate)
    gate = VADGate(
        vad,
        threshold=settings.vad_threshold,
        release_threshold=settings.vad_release_threshold,
        min_silence_ms=settings.vad_min_silence_ms,
        speech_pad_ms=settings.vad_speech_pad_ms,
    )
    metrics = MetricsCollector()
    sentences: list[dict] = []

    def on_final(update: FinalUpdate) -> None:
        sentences.append(
            {
                "id": update.sentence.segment_id,
                "text": update.sentence.text,
                "start_s": round(update.sentence.start, 2),
                "end_s": round(update.sentence.end, 2),
                "reason": update.sentence.reason,
                "latency_ms": round(update.latency_ms, 1),
            }
        )
        if show:
            marca = f"[dim]{update.sentence.start:6.1f}s[/dim]"
            lat = f"[dim]{update.latency_ms:6.0f} ms[/dim]" if realtime else ""
            console.print(f"{marca} {update.sentence.text}  {lat}")

    session = StreamingSession(settings, engine, gate, metrics=metrics, on_final=on_final)

    wall0 = time.perf_counter()
    for frame in source.frames():
        session.push(frame)
    session.finish()
    wall = time.perf_counter() - wall0

    whisper = metrics.get("whisper_processing_ms")
    latency = metrics.get("speech_latency_ms")
    return {
        "sample": path.name,
        "audio_s": round(source.duration_s, 2),
        "wall_s": round(wall, 2),
        "overall_rtf": round(wall / source.duration_s, 3) if source.duration_s else None,
        "passes": session.stats.passes,
        "skipped_silent": session.stats.skipped_silent,
        "rejected": session.stats.rejected,
        "sentences": sentences,
        "whisper_ms": whisper.summary() if whisper else None,
        "latency_ms": latency.summary() if latency and realtime else None,
        "metrics": metrics.as_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", default=str(ROOT / "bench" / "samples"))
    parser.add_argument("--model", help="sobreescribe YOUJP_ASR_MODEL")
    parser.add_argument("--device", help="cuda o cpu")
    parser.add_argument("--compute-type", help="int8_float16, float16, int8...")
    parser.add_argument("--min-chunk", type=float, help="segundos entre pasadas")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="sin pacing: mide RTF en vez de latencia",
    )
    parser.add_argument("--quiet", action="store_true", help="no imprimir las frases")
    parser.add_argument("--tag", default="", help="etiqueta para el fichero de salida")
    args = parser.parse_args()

    settings = get_settings()
    if args.model:
        settings.asr_model = args.model
    if args.device:
        settings.asr_device = args.device
    if args.compute_type:
        settings.asr_compute_type = args.compute_type
    if args.min_chunk:
        settings.min_chunk_s = args.min_chunk

    setup_logging(settings.log_level)

    sample_dir = Path(args.samples)
    wavs = sorted(p for p in sample_dir.glob("*.wav"))
    if not wavs:
        console.print(f"[red]No hay .wav en {sample_dir}[/red]")
        console.print(
            "Prepara alguna muestra con:\n"
            "  .\\scripts\\prepare_sample.ps1 -Input <fichero> -Name <nombre> -Duration 60"
        )
        raise SystemExit(1)

    baseline = read_gpu()
    contended = False
    if baseline:
        console.print(
            f"[dim]GPU: {baseline.name} · {baseline.used_mb:.0f}/{baseline.total_mb:.0f} MiB "
            f"ocupados antes de cargar nada[/dim]"
        )
        # Una linea base alta significa que otra aplicacion tiene la GPU. No
        # invalida la ejecucion, pero si las cifras: la VRAM atribuible sale
        # inflada y la inferencia sale lenta por contencion, no por el modelo.
        # Ocurrio el 14-09-2026 con un juego y Steam abiertos: el pico paso de
        # 2 674 a 5 392 MiB y la latencia p50 casi se duplico.
        if baseline.used_mb > BUSY_GPU_MB:
            contended = True
            console.print(
                f"[bold yellow]Aviso:[/bold yellow] hay {baseline.used_mb:.0f} MiB de VRAM "
                f"ocupados por otras aplicaciones. Las cifras de esta ejecucion no son "
                f"comparables con una GPU en reposo. Cierra juegos, navegadores con "
                f"aceleracion y Docker antes de medir en serio."
            )

    engine = WhisperEngine(settings)
    realtime = not args.fast

    with GpuMonitor(hz=settings.gpu_sample_hz) as gpu:
        load0 = time.perf_counter()
        engine.load()
        load_ms = (time.perf_counter() - load0) * 1000
        warmup_ms = engine.warmup()

        results = []
        for wav in wavs:
            console.rule(f"[bold]{wav.name}")
            results.append(
                run_sample(wav, settings, engine, realtime=realtime, show=not args.quiet)
            )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "realtime" if realtime else "fast",
        "config": {
            "asr_model": settings.asr_model,
            "asr_device": settings.asr_device,
            "asr_compute_type": settings.asr_compute_type,
            "asr_beam_size": settings.asr_beam_size,
            "min_chunk_s": settings.min_chunk_s,
            "buffer_trim_s": settings.buffer_trim_s,
            "vad_min_silence_ms": settings.vad_min_silence_ms,
        },
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "gpu": gpu.device_name,
            "gpu_total_mb": round(gpu.total_mb, 1),
        },
        "gpu": {
            "contended": contended,
            "baseline_used_mb": round(gpu.baseline_used_mb, 1),
            "peak_used_mb": round(gpu.peak_used_mb, 1),
            "attributable_mb": round(gpu.attributable_mb, 1),
        },
        "model_load_ms": round(load_ms, 1),
        "warmup_ms": round(warmup_ms, 1),
        "samples": results,
    }

    out_dir = ROOT / "bench" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = f"-{args.tag}" if args.tag else ""
    safe_model = settings.asr_model.replace("/", "_")
    out_path = out_dir / f"{stamp}-{safe_model}-{report['mode']}{tag}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_summary(report)
    console.print(f"\n[dim]informe: {out_path}[/dim]")


def _print_summary(report: dict) -> None:
    console.rule("[bold]resumen")
    table = Table(box=None, pad_edge=False)
    table.add_column("muestra")
    table.add_column("audio", justify="right")
    table.add_column("RTF global", justify="right")
    table.add_column("whisper p50", justify="right")
    table.add_column("whisper p95", justify="right")
    table.add_column("latencia p50", justify="right")
    table.add_column("latencia p95", justify="right")
    table.add_column("frases", justify="right")
    table.add_column("descartes", justify="right")

    for s in report["samples"]:
        w = s["whisper_ms"] or {}
        lat = s["latency_ms"] or {}
        rejected = sum(s["rejected"].values()) if s["rejected"] else 0
        table.add_row(
            s["sample"],
            f"{s['audio_s']:.0f} s",
            f"{s['overall_rtf']:.2f}" if s["overall_rtf"] else "-",
            f"{w.get('p50', 0):.0f} ms" if w else "-",
            f"{w.get('p95', 0):.0f} ms" if w else "-",
            f"{lat.get('p50', 0):.0f} ms" if lat else "-",
            f"{lat.get('p95', 0):.0f} ms" if lat else "-",
            str(len(s["sentences"])),
            str(rejected),
        )
    console.print(table)

    g = report["gpu"]
    if g.get("contended"):
        console.print(
            "\n[bold yellow]Cifras contaminadas:[/bold yellow] otra aplicacion tenia la GPU. "
            "La VRAM atribuible sale inflada y la latencia, alta por contencion."
        )
    console.print(
        f"\nVRAM  base [bold]{g['baseline_used_mb']:.0f}[/bold] MiB  ·  "
        f"pico [bold]{g['peak_used_mb']:.0f}[/bold] MiB  ·  "
        f"atribuible al modelo [bold]{g['attributable_mb']:.0f}[/bold] MiB  "
        f"(de {report['machine']['gpu_total_mb']:.0f} MiB)"
    )
    console.print(
        f"carga del modelo {report['model_load_ms']:.0f} ms  ·  "
        f"calentamiento {report['warmup_ms']:.0f} ms"
    )


if __name__ == "__main__":
    main()
