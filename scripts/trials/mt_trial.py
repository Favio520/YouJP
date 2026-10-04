"""Isolated Japanese subtitle MT trial; never changes YouJP defaults.

Prepare cases without inference:
  backend\\.venv\\Scripts\\python.exe scripts\\trials\\mt_trial.py

After the candidate is installed and the GPU phase is authorized:
  backend\\.venv\\Scripts\\python.exe scripts\\trials\\mt_trial.py --run

The candidate uses Tencent's published user-only translation prompt and decode
parameters. The baseline reuses YouJP's actual prompt builder and cleaning.
Timing is MT only, on a serial, initially idle Ollama server, without Whisper.
No lexical cue is a quality score: raw outputs and review questions are saved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "bench" / "trials" / "20261003" / "mt"
DEFAULT_BASELINE = "qwen3:4b-instruct-2507-q4_K_M"
DEFAULT_CANDIDATE = "youjp-trial-hymt2:1.8b-q4_k_m-20261003"
SOURCES = {
    "candidate_card": "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF",
    "candidate_file": "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/blob/main/Hy-MT2-1.8B-Q4_K_M.gguf",
    "candidate_download": "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/main/Hy-MT2-1.8B-Q4_K_M.gguf",
    "candidate_sha256": "dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699",
    "ollama_import": "https://docs.ollama.com/import",
    "ollama_chat": "https://docs.ollama.com/api/chat",
    "official_chat_template": "https://huggingface.co/tencent/Hy-MT2-1.8B/blob/main/chat_template.jinja",
}


def case(
    identifier: str,
    source: str,
    review: str,
    *,
    provenance: str = "manually authored edge case; not a recording",
    target: str = "es",
    context: tuple[str, ...] = (),
    context_only_cues: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": identifier,
        "source": source,
        "target": target,
        "context": list(context),
        "provenance": provenance,
        "review_question": review,
        "context_only_cues": list(context_only_cues),
    }


def cases() -> list[dict[str, Any]]:
    regression = "backend/tests/test_translation_quality.py; real transcript regression, reviewed 2026-09-14"
    return [
        case(
            "reg_aspiration", "漫画家を目指して10年以上になるという田中さん",
            "Keep third-person Tanaka and over ten years of trying/aspiring to become a manga artist; do not claim that he already is one.",
            provenance=regression,
        ),
        case(
            "reg_subject_context", "ここで毎朝2時間勉強しています",
            "Use third-person studies; translate only the last line, without adding Nishiyama's age, job or the shop opening time.",
            context=("一方西梅田店は朝5時から営業", "証券会社でお客様対応をしている35歳の西山さん"),
            context_only_cues=("35", "treinta y cinco", "cinco de la mañana", "valores", "nishiyama", "nishi-umeda"),
            provenance=regression,
        ),
        case(
            "reg_comparison_skill", "魔力も技術もコントロールも私の方が遥かに上",
            "The speaker is far above the other person in magical power, skill/technique and control. Do not invert comparison, use 'los míos', or translate skill as industrial technology.",
            provenance=regression,
        ),
        case(
            "reg_proper_name", "証券会社でお客様対応をしている35歳の西山真さん",
            "Preserve age 35, customer-facing securities job and Nishiyama by sound. Given-name reading 真 is not established in this isolated line; do not score one reading as certain.",
            provenance=regression,
        ),
        case(
            "reg_fragment", "と言って",
            "Translate the short quoted-speech fragment without inventing a completed event.",
            provenance=regression,
        ),
        case(
            "reg_one_line", "今日は経済への影響について話します。",
            "A natural subtitle about discussing effects on the economy today; no commentary or extra lines.",
            provenance=regression,
        ),
        case(
            "edge_negation", "行かないわけではないけど、今日はやめておく。",
            "The speaker does not flatly refuse to go; today they choose to leave it. Preserve the double-negation nuance without reversing the decision.",
        ),
        case(
            "edge_numbers", "料金は税込みで一万二千五百円、割引はありません。",
            "Preserve 12,500 yen, taxes included, and no discount.",
        ),
        case(
            "edge_politeness", "恐れ入りますが、少々お待ちいただけますか。",
            "A polite request to wait a moment, maintaining polite register without a long cultural explanation.",
        ),
        case(
            "edge_colloquial", "マジで？めっちゃすごいじゃん。",
            "Natural informal surprise and praise; preserve questions and colloquial register.",
        ),
        case(
            "edge_unfinished_condition", "もし明日までに返事がなかったら",
            "Preserve the unfinished condition 'if there is no reply by tomorrow'; do not invent what happens next.",
        ),
        case(
            "edge_idiom", "猫の手も借りたいくらい忙しい。",
            "Express being extremely busy / needing any help, without presenting literal cat labor as the intended meaning.",
        ),
        case(
            "edge_terms_places", "本町から西梅田まで地下鉄で行きます。",
            "Travel by subway from Honmachi to Nishi-Umeda, preserving both place names by sound.",
        ),
        case(
            "ctx_subject_three", "毎朝ここで二時間勉強しています。",
            "Third-person studies for two hours every morning; preceding Tanaka/library/exam information must only resolve context, without being translated again.",
            context=("これは田中さんです。", "田中さんは試験に向けて準備しています。", "勉強場所は図書館です。"),
            context_only_cues=("tanaka", "biblioteca", "examen"),
        ),
        case(
            "ctx_person_three", "昨日、退院しました。",
            "Context identifies Misaki as the discharged person; preserve yesterday and discharge rather than admission, without repeating the family/intake history.",
            context=("山田さんには娘がいます。", "娘の名前は美咲です。", "美咲は先週、病院に入院しました。"),
            context_only_cues=("yamada", "hija", "semana pasada", "ingresó", "ingresada"),
        ),
        case(
            "ctx_no_repetition_three", "会議は午後三時からです。",
            "Only the meeting starting at 3 p.m.; prior Tokyo/Nishiyama/sushi/train sentences must not reappear.",
            context=("昨日は東京へ行きました。", "西山さんと寿司を食べました。", "新幹線で帰ってきました。"),
            context_only_cues=("tokio", "tokyo", "nishiyama", "sushi", "shinkansen", "tren"),
        ),
        case("en_economy", "今日は経済について話します。", "Discuss the economy today in English.", target="en", provenance=regression),
        case("en_name", "私の名前は田中です。", "The speaker's name is Tanaka, in English.", target="en", provenance=regression),
        case("en_thanks", "ありがとうございます。", "A polite thank-you in English.", target="en", provenance=regression),
    ]


def json_request(url: str, path: str, body: dict | None = None, *, timeout: float = 120) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def gpu_snapshot() -> dict:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return {"csv": result.stdout.strip(), "fields": ["name", "total_mib", "used_mib", "utilization_percent"]}
    except (OSError, subprocess.SubprocessError) as error:
        return {"unavailable": type(error).__name__}


def production_helpers():
    sys.path.insert(0, str(ROOT / "backend"))
    from youjp.config import Settings
    from youjp.mt.llm import SYSTEM_PROMPTS, LlmProvider, _clean

    # No Settings() / get_settings(): do not read or expose launcher.env / .env.
    defaults = {name: Settings.model_fields[name].default for name in (
        "mt_max_tokens", "llm_num_gpu", "llm_num_ctx", "llm_keep_alive",
    )}
    builder = object.__new__(LlmProvider)
    return defaults, builder._build_prompt, SYSTEM_PROMPTS, _clean


def candidate_prompt(sample: dict) -> str:
    language = {"es": "Spanish", "en": "English"}[sample["target"]]
    if sample["context"]:
        # Official background-information example, with an explicit output-only
        # rule needed by subtitles. This adaptation is saved in full per case.
        background = "\n".join(sample["context"])
        return (
            f"[Background Information]\n{background}\n"
            f"Please translate the following text into {language}, taking the provided "
            "background information into consideration. Only output the translation "
            "of [Source Text], without any additional explanation. Do not translate "
            "the background information.\n"
            f"[Source Text]\n{sample['source']}"
        )
    return (
        f"Translate the following text into {language}. Note that you should only "
        "output the translated result without any additional explanation:\n"
        f"{sample['source']}"
    )


def make_payload(
    sample: dict, label: str, model: str, defaults: dict,
    build_baseline, system_prompts: dict, *, seed: int, num_gpu: int | None,
) -> dict:
    options = {
        "num_predict": defaults["mt_max_tokens"],
        "num_gpu": defaults["llm_num_gpu"] if num_gpu is None else num_gpu,
        "num_ctx": defaults["llm_num_ctx"],
        "seed": seed,
    }
    payload = {"model": model, "stream": True, "keep_alive": "5m", "options": options}
    if label == "baseline":
        options["temperature"] = 0.2
        payload["think"] = False
        payload["messages"] = [
            {"role": "system", "content": system_prompts[sample["target"]]},
            {"role": "user", "content": build_baseline(sample["source"], sample["context"], sample["target"])},
        ]
    else:
        options.update(temperature=0.7, top_p=0.6, top_k=20, repeat_penalty=1.05)
        payload["messages"] = [{"role": "user", "content": candidate_prompt(sample)}]
    return payload


def streamed_request(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    first_content = None
    contents, thoughts, chunks = [], [], 0
    final: dict = {}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for line in response:
                if time.perf_counter() - start > timeout:
                    raise TimeoutError("Elapsed request deadline exceeded while receiving stream")
                if not line.strip():
                    continue
                obj = json.loads(line)
                if obj.get("error"):
                    raise RuntimeError(str(obj["error"]))
                chunks += 1
                message = obj.get("message", {})
                content = message.get("content", "")
                if content and first_content is None:
                    first_content = (time.perf_counter() - start) * 1000
                contents.append(content)
                thoughts.append(message.get("thinking", ""))
                if obj.get("done"):
                    final = obj
        raw = "".join(contents)
        wall_ms = (time.perf_counter() - start) * 1000
        fields = ("done", "done_reason", "total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration")
        counters = {field: final.get(field) for field in fields}
        token_s = None
        if counters.get("eval_duration"):
            token_s = counters.get("eval_count", 0) * 1e9 / counters["eval_duration"]
        return {
            "raw_output": raw,
            "thinking_output": "".join(thoughts),
            "wall_ms": round(wall_ms, 3),
            "first_content_ms": round(first_content, 3) if first_content is not None else None,
            "stream_chunks": chunks,
            "ollama": counters,
            "eval_tokens_per_s": round(token_s, 3) if token_s is not None else None,
            "error": None,
        }
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
        # Preserve partial output; do not turn a request failure into a success.
        return {
            "raw_output": "".join(contents), "thinking_output": "".join(thoughts),
            "wall_ms": round((time.perf_counter() - start) * 1000, 3),
            "first_content_ms": round(first_content, 3) if first_content is not None else None,
            "stream_chunks": chunks, "ollama": final,
            "eval_tokens_per_s": None, "error": f"{type(error).__name__}: {error}",
        }


def output_cues(sample: dict, result: dict, cleaned: str) -> dict:
    raw = result["raw_output"]
    lower = cleaned.casefold()
    words = re.findall(r"\w+", lower)
    trigrams = [tuple(words[index:index + 3]) for index in range(max(len(words) - 2, 0))]
    repeats = sorted({" ".join(gram) for gram in trigrams if trigrams.count(gram) > 1})
    return {
        "request_failed": result["error"] is not None or result["ollama"].get("done") is not True,
        "empty_after_cleaning": not cleaned,
        "generation_hit_limit": result["ollama"].get("done_reason") == "length",
        "raw_has_multiple_lines": "\n" in raw.strip(),
        "raw_has_thinking": bool(result["thinking_output"]) or "<think>" in raw,
        "raw_wrapping_quotes": bool(raw.strip()) and raw.strip()[0] in '\"「“',
        "output_contains_japanese_kana": bool(re.search(r"[\u3040-\u30ff]", cleaned)),
        "context_only_cues_found": [cue for cue in sample["context_only_cues"] if cue.casefold() in lower],
        "repeated_trigrams": repeats,
        "interpretation": "Observable format/repetition/failure cues only. Not a semantic pass/fail score.",
    }


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summary(report: dict) -> dict:
    aggregates = {}
    for label in ("baseline", "candidate"):
        runs = [run for run in report["runs"] if run["label"] == label]
        good = [run for run in runs if not run["cues"]["request_failed"]]
        latency = [run["wall_ms"] for run in good]
        first = [run["first_content_ms"] for run in good if run["first_content_ms"] is not None]
        aggregates[label] = {
            "requests": len(runs), "request_failures": len(runs) - len(good),
            "warm_wall_p50_ms": percentile(latency, 0.5),
            "warm_wall_p95_ms": percentile(latency, 0.95),
            "warm_wall_max_ms": max(latency) if latency else None,
            "warm_first_content_p50_ms": percentile(first, 0.5),
            "warm_first_content_p95_ms": percentile(first, 0.95),
            "warm_first_content_max_ms": max(first) if first else None,
            "warm_wall_es_p50_ms": percentile([run["wall_ms"] for run in good if run["sample"]["target"] == "es"], 0.5),
            "warm_wall_es_p95_ms": percentile([run["wall_ms"] for run in good if run["sample"]["target"] == "es"], 0.95),
            "empty_outputs": sum(run["cues"]["empty_after_cleaning"] for run in good),
            "generation_limit_hits": sum(run["cues"]["generation_hit_limit"] for run in good),
            "requests_containing_context_review_cues": sum(bool(run["cues"]["context_only_cues_found"]) for run in good),
            "semantic_quality_score": None,
        }
    return aggregates


def write_markdown(report: dict, out: Path) -> None:
    whisper = report["conditions"].get("whisper_resident")
    whisper_description = (
        "Whisper está residente en GPU, sin ejecutar ASR, para observar el presupuesto de VRAM compartido."
        if whisper else "Whisper no está cargado por esta prueba."
    )
    lines = [
        "# Prueba aislada de traducción YouJP — 3 de octubre de 2026", "",
        ("La prueba mide traducción de texto japonés a subtítulos en español y un subconjunto en inglés. "
         "No mide ASR, audio a subtítulo, captura de navegador ni contención durante inferencia concurrente. "
         "No modifica el proveedor ni el modelo predeterminado."), "",
        whisper_description, "",
        ("Las traducciones y las preguntas de revisión permiten una revisión semántica; las coincidencias "
         "de palabras y el éxito de la API no prueban calidad. Los casos escritos a mano están identificados. "
         "Varias frases de regresión ya están enseñadas explícitamente en el prompt de Qwen; no son una prueba ciega."), "",
        "## Condiciones", "",
        f"- Ollama: `{report['environment'].get('ollama_version', {})}`.",
        f"- Semilla base: {report['seed']}; {report['repetitions']} repeticiones por caso.",
        f"- Modelo baseline: `{next((run['model'] for run in report['runs'] if run['label'] == 'baseline'), DEFAULT_BASELINE)}`.",
        f"- Modelo candidato: `{next((run['model'] for run in report['runs'] if run['label'] == 'candidate'), DEFAULT_CANDIDATE)}`.",
        "- Baseline: prompt y limpieza actuales de `backend/youjp/mt/llm.py`, temperatura 0.2.",
        ("- Candidato: prompt de traducción de Tencent sin system prompt; para contexto usa el ejemplo "
         "de información de fondo con la instrucción explícita de traducir solo la última línea."),
        ("- La importación directa de Hugging Face en Ollama 0.35.0 devolvió una plantilla sin `.Prompt` "
         "ni `.Response` y con texto residual `onse }}`. Se creó un alias aislado con los mismos pesos "
         "y la plantilla exacta del caso de un único mensaje de usuario de Tencent. "
         "La importación original y la plantilla oficial se preservan en los artefactos de esta prueba."),
        ("- Candidato: temperatura 0.7, top_p 0.6, top_k 20, repeat_penalty 1.05. "
         "Se mantiene el límite de 256 tokens / contexto 2048 del caso en vivo, frente a 4096 tokens sugeridos por Tencent."),
        ("- Comparación de dos configuraciones apropiadas a cada modelo, con prompts y parámetros diferentes; "
         "no permite atribuir todas las diferencias únicamente a los pesos."),
        ("- Primera petición con el modelo descargado de VRAM; caché de archivos del SO sin limpiar. "
         "Las mediciones calientes siguen a esa petición y reutilizan el mismo modelo."),
        "- Streaming de la API para medir primer contenido; YouJP actualmente consume la traducción completa.",
        ("- Timeout de socket/inactividad de 120 s y comprobación de plazo al recibir cada bloque; "
         "un read bloqueado puede consumir su timeout aunque el plazo global ya haya vencido. "
         "No es una garantía de cancelación global exacta."),
        "- p95 interpolado sobre una muestra pequeña; es descriptivo, sin intervalo de confianza.", "",
        "## Tiempos", "",
        "| Configuración | Peticiones calientes | Errores API | Primera carga y traducción (ms) | Español p50 (ms) | Español p95 (ms) | Todos p50 (ms) | Todos p95 (ms) | Máximo (ms) | Primer contenido p50 (ms) | Primer contenido máximo (ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ("baseline", "candidate"):
        aggregate = report["summary"][label]
        cold = report["cold_requests"].get(label, {}).get("wall_ms")
        lines.append(
            f"| {label} | {aggregate['requests']} | {aggregate['request_failures']} | {cold} | "
            f"{aggregate['warm_wall_es_p50_ms']} | {aggregate['warm_wall_es_p95_ms']} | "
            f"{aggregate['warm_wall_p50_ms']} | {aggregate['warm_wall_p95_ms']} | "
            f"{aggregate['warm_wall_max_ms']} | {aggregate['warm_first_content_p50_ms']} | "
            f"{aggregate['warm_first_content_max_ms']} |"
        )
    lines.extend([
        "", "## VRAM observada", "",
        ("Muestreo NVML a 4 Hz de VRAM total usada, incluido escritorio y Whisper cuando está residente. "
         "Un pico corto puede quedar entre muestras; `/api/ps` registra además el tamaño residente de cada traductor."), "",
        "| Configuración | Base antes de cargar MT (MiB) | Pico observado (MiB) | MT residente según Ollama (MiB) |",
        "|---|---:|---:|---:|",
    ])
    for label in ("baseline", "candidate"):
        gpu = report["models"].get(label + "_gpu_monitor", {})
        resident = report["models"].get(label + "_resident_after", {}).get("models", [])
        mt_size = resident[0].get("size_vram", 0) / 1024**2 if resident else 0
        lines.append(f"| {label} | {gpu.get('baseline_used_mib', 0):.1f} | {gpu.get('peak_used_mib', 0):.1f} | {mt_size:.1f} |")
    if report["runs"]:
        worst = max(report["runs"], key=lambda run: run["wall_ms"])
        counters = worst["ollama"]
        prompt_ms = (counters.get("prompt_eval_duration") or 0) / 1e6
        lines.extend([
            "", (f"Caso de mayor tiempo: `{worst['label']}` `{worst['sample']['id']}` r{worst['repetition']}, "
            f"{worst['wall_ms']:.1f} ms, primer contenido {worst['first_content_ms']} ms, "
            f"prefill/prompt_eval {prompt_ms:.1f} ms, {counters.get('eval_count')} tokens generados, "
            f"terminación `{counters.get('done_reason')}`."), "",
        ])
    lines.extend(["", "## Traducciones completas para revisión", ""])
    for sample in report["cases"]:
        lines.extend([
            f"### {sample['id']} ({sample['target']})", "",
            f"Procedencia: {sample['provenance']}", "",
            f"Japonés: {sample['source']}", "",
        ])
        if sample["context"]:
            lines.extend(["Contexto previo:", "", *[f"> {line}" for line in sample["context"]], ""])
        lines.extend([f"Revisión: {sample['review_question']}", ""])
        for run in report["runs"]:
            if run["sample"]["id"] == sample["id"]:
                lines.append(f"- {run['label']} r{run['repetition']} ({run['wall_ms']:.0f} ms): {run['cleaned_output'] or '[VACÍO]'}")
                if run["error"]:
                    lines.append(f"  Error: {run['error']}")
                cues = {key: value for key, value in run["cues"].items() if value and key != "interpretation"}
                if cues:
                    lines.append(f"  Señales observables: `{json.dumps(cues, ensure_ascii=False)}`")
        lines.append("")
    lines.extend([
        "## Fuentes primarias verificadas", "",
        f"- [Ficha oficial y prompts de Hy-MT2]({SOURCES['candidate_card']})",
        f"- [Archivo Q4_K_M oficial y SHA256]({SOURCES['candidate_file']})",
        f"- [Importación GGUF de Ollama]({SOURCES['ollama_import']})", "",
        f"- [Plantilla oficial del tokenizer]({SOURCES['official_chat_template']})", "",
        ("Los detalles de plantilla, parámetros, contadores de evaluación, tiempos, versión, VRAM y "
         "errores están en `mt-results.json`; `mt-runs.jsonl` preserva cada petición inmediatamente."), "",
    ])
    (out / "mt-results.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Execute serial model inference; requires separate GPU-phase authorization.")
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--num-gpu", type=int, help="Override GPU layers for an explicitly labeled CPU/control trial.")
    parser.add_argument("--with-whisper-resident", action="store_true", help="Load installed current Whisper without ASR inference; requires GPU-phase authorization.")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    sample_list = cases()
    args.out.mkdir(parents=True, exist_ok=True)
    journal = args.out / "mt-runs.jsonl"
    if args.run and (journal.exists() or (args.out / "mt-results.json").exists()):
        parser.error("Output already contains an inference run; choose a new --out to preserve evidence.")
    write_json(args.out / "cases.json", sample_list)
    if not args.run:
        print(f"Prepared {len(sample_list)} labeled cases; no network, download, model load or inference. {args.out / 'cases.json'}")
        return

    defaults, builder, system_prompts, clean = production_helpers()
    from youjp.obs.gpu import GpuMonitor

    installed = json_request(args.url, "/api/tags")
    names = {model.get("name") for model in installed.get("models", [])}
    missing = {args.baseline, args.candidate} - names
    if missing:
        parser.error(f"Models not installed: {', '.join(sorted(missing))}. This script never downloads them.")
    initial_ps = json_request(args.url, "/api/ps")
    other_residents = [model["name"] for model in initial_ps.get("models", []) if model["name"] not in (args.baseline, args.candidate)]
    if other_residents:
        parser.error(f"Other Ollama models resident; coordinate idle GPU before trial: {', '.join(other_residents)}")

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trial_client_date": "2026-10-03", "seed": args.seed,
        "repetitions": args.repetitions, "sources": SOURCES,
        "production_prompt_sha256": hashlib.sha256((ROOT / "backend" / "youjp" / "mt" / "llm.py").read_bytes()).hexdigest(),
        "repository_defaults_without_env": defaults,
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "ollama_version": json_request(args.url, "/api/version"),
            "installed_selected_models": [model for model in installed.get("models", []) if model.get("name") in (args.baseline, args.candidate)],
            "initial_residents": initial_ps, "initial_gpu": gpu_snapshot(),
        },
        "conditions": {
            "asr_running_by_this_script": False,
            "production_settings_changed": False,
            "disk_cache_cleared": False,
            "serial_model_order": ["baseline", "candidate"],
            "different_model_prompts_and_decoding": True,
            "whisper_resident": args.with_whisper_resident,
            "gpu_layers": defaults["llm_num_gpu"] if args.num_gpu is None else args.num_gpu,
            "lexical_cues_are_not_quality_scores": True,
            "context_review_cues_may_be_legitimate_explicit_subjects": True,
            "timeout_s": args.timeout,
            "timeout_semantics": "Socket inactivity timeout plus elapsed check per received line; not an exact global cancellation deadline.",
        },
        "cases": sample_list, "models": {}, "cold_requests": {}, "runs": [],
    }
    whisper_engine = None
    monitor = None
    try:
        if args.with_whisper_resident:
            from youjp.asr.engine import WhisperEngine
            from youjp.config import get_settings

            # Only this process is forced offline, and only selected ASR fields
            # are recorded. Never print environment files or other settings.
            os.environ["HF_HUB_OFFLINE"] = "1"
            settings = get_settings().model_copy(update={"asr_word_timestamps": "on"})
            whisper_engine = WhisperEngine(settings)
            report["whisper"] = {
                "model": settings.asr_model, "device": settings.asr_device,
                "compute_type": settings.asr_compute_type,
                "word_timestamps_probe_skipped": True,
                "before_gpu": gpu_snapshot(), "asr_inference": False,
                "hf_hub_offline": True,
            }
            started = time.perf_counter()
            print(f"Loading resident-only Whisper {settings.asr_model}, offline", flush=True)
            whisper_engine.load()
            report["whisper"].update(load_ms=(time.perf_counter() - started) * 1000, after_gpu=gpu_snapshot())
        for label, model in (("baseline", args.baseline), ("candidate", args.candidate)):
            report["models"][label] = json_request(args.url, "/api/show", {"model": model})
            for resident in json_request(args.url, "/api/ps").get("models", []):
                if resident["name"] in (args.baseline, args.candidate):
                    json_request(args.url, "/api/generate", {"model": resident["name"], "keep_alive": 0})
                else:
                    raise RuntimeError(f"Unexpected other model became resident: {resident['name']}")
            warmup_case = case("cold_warmup", "今日はいい天気です。", "Cold load timing only; not part of quality set.")
            cold_payload = make_payload(warmup_case, label, model, defaults, builder, system_prompts, seed=args.seed, num_gpu=args.num_gpu)
            print(f"Loading and warming {label}: {model}", flush=True)
            monitor = GpuMonitor(hz=4)
            monitor.__enter__()
            cold = streamed_request(args.url, cold_payload, args.timeout)
            cold["gpu_after"] = gpu_snapshot()
            cold["residents_after"] = json_request(args.url, "/api/ps")
            report["cold_requests"][label] = cold
            if cold["error"] or not cold["ollama"].get("done"):
                raise RuntimeError(f"{label} cold request failed: {cold['error'] or cold['ollama']}")
            for repetition in range(1, args.repetitions + 1):
                for sample in sample_list:
                    payload = make_payload(sample, label, model, defaults, builder, system_prompts, seed=args.seed + repetition - 1, num_gpu=args.num_gpu)
                    result = streamed_request(args.url, payload, args.timeout)
                    cleaned = clean(result["raw_output"])
                    run = {
                        "label": label, "model": model, "repetition": repetition,
                        "sample": sample, "request": payload, **result,
                        "cleaned_output": cleaned, "cues": output_cues(sample, result, cleaned),
                    }
                    report["runs"].append(run)
                    with journal.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(run, ensure_ascii=False) + "\n")
                    print(f"{label} r{repetition} {sample['id']}: {run['wall_ms']:.0f} ms; error={bool(run['error'])}", flush=True)
            report["models"][label + "_resident_after"] = json_request(args.url, "/api/ps")
            monitor.__exit__(None, None, None)
            report["models"][label + "_gpu_monitor"] = {
                "total_mib": monitor.total_mb,
                "baseline_used_mib": monitor.baseline_used_mb,
                "peak_used_mib": monitor.peak_used_mb,
                "sample_count": len(monitor.samples),
                "sampled_used_mib": monitor.samples,
            }
            json_request(args.url, "/api/generate", {"model": model, "keep_alive": 0})
    except Exception as error:
        report["execution_error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["cleanup_errors"] = []
        if monitor is not None:
            try:
                monitor.__exit__(None, None, None)
            except Exception as error:  # noqa: BLE001 - preserve independent cleanup and evidence
                report["cleanup_errors"].append(f"GPU monitor: {type(error).__name__}: {error}")
        # Each cleanup is independent: a failed network call cannot skip
        # Whisper unloading, preservation of earlier results or report writes.
        for model in (args.baseline, args.candidate):
            try:
                json_request(args.url, "/api/generate", {"model": model, "keep_alive": 0}, timeout=5)
            except Exception as error:  # noqa: BLE001 - continue cleanup after any unload failure
                report["cleanup_errors"].append(f"Unload {model}: {type(error).__name__}: {error}")
        if whisper_engine is not None:
            try:
                whisper_engine.unload()
            except Exception as error:  # noqa: BLE001 - preserve results even if CUDA cleanup fails
                report["cleanup_errors"].append(f"Unload Whisper: {type(error).__name__}: {error}")
        report["summary"] = summary(report)
        report["environment"]["final_gpu"] = gpu_snapshot()
        try:
            report["environment"]["final_residents"] = json_request(args.url, "/api/ps", timeout=5)
        except Exception as error:  # noqa: BLE001 - endpoint may vanish after partial results
            report["environment"]["final_residents"] = {"unavailable": f"{type(error).__name__}: {error}"}
        write_json(args.out / "mt-results.json", report)
        write_markdown(report, args.out)
        print(f"Report: {args.out / 'mt-results.md'}", flush=True)


if __name__ == "__main__":
    main()
