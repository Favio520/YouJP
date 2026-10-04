"""Traducción anticipada de un vídeo completo.

Para vídeos que no son directos no hace falta esperar al reproductor: se
obtienen todas las frases con su tiempo, se traducen y analizan una vez, y la
extensión las muestra sincronizadas con ``currentTime``. Las frases salen de:

1. el transcript japonés *manual* del propio YouTube, si el vídeo lo tiene
   (exacto, y no gasta GPU en Whisper), o
2. Whisper sobre el audio completo, descargado con yt-dlp, si no lo tiene.

Los subtítulos automáticos de YouTube no se usan: se solapan y se corrigen a
medida que avanzan, y Whisper los mejora.

El trabajo corre en un hilo y avanza frase a frase: quien consulta el estado
puede empezar a ver el principio sin esperar al final. El resultado se guarda en
``library_dir`` para no repetirlo, y también en el historial del lanzador.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from youjp.history import write_prepared_history

log = logging.getLogger(__name__)

MAX_DURATION_S = 4 * 3600
CONTEXT_SENTENCES = 3
MAX_CAPTION_BYTES = 8 * 1024 * 1024
LONG_SEGMENT_S = 12.0
LONG_SEGMENT_CHARS = 60
SENTENCE_END = re.compile(r"(?<=[。！？!?])")

Status = Literal["queued", "resolving", "downloading", "transcribing", "translating", "done", "error"]


class VideoUnavailable(Exception):
    """El vídeo no se puede preparar; el mensaje se muestra tal cual al usuario."""


@dataclass
class VideoInfo:
    title: str
    channel: str
    duration_s: float
    is_live: bool
    caption_url: str | None


@dataclass
class RawCue:
    start_ms: int
    end_ms: int
    text: str


# -- fuentes de frases ---------------------------------------------------------


def video_url(video_id: str) -> str:
    # La URL se construye aquí, nunca viene de la petición.
    return f"https://www.youtube.com/watch?v={video_id}"


def resolve_video(video_id: str) -> VideoInfo:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise VideoUnavailable("Falta yt-dlp. Ejecuta «Preparar / actualizar» desde el lanzador.") from exc
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url(video_id), download=False)
    except DownloadError as exc:
        raise VideoUnavailable("No se pudo acceder al vídeo (privado, con restricción de edad o no disponible).") from exc
    caption_url = None
    manual = info.get("subtitles") or {}
    for language in sorted(key for key in manual if key.lower().startswith("ja")):
        entry = next((item for item in manual[language] if item.get("ext") == "json3" and item.get("url")), None)
        if entry:
            caption_url = entry["url"]
            break
    return VideoInfo(
        title=str(info.get("title") or ""),
        channel=str(info.get("channel") or info.get("uploader") or ""),
        duration_s=float(info.get("duration") or 0),
        is_live=bool(info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}),
        caption_url=caption_url,
    )


def parse_json3(data: dict[str, Any]) -> list[RawCue]:
    """Convierte el formato json3 de YouTube en frases con tiempo."""
    cues: list[RawCue] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs or "tStartMs" not in event:
            continue
        text = "".join(str(seg.get("utf8", "")) for seg in segs).replace("\n", " ").strip()
        if not text:
            continue
        start = int(event["tStartMs"])
        end = start + int(event.get("dDurationMs", 0))
        cues.append(RawCue(start, max(end, start + 1), text))
    return cues


def fetch_captions(url: str) -> list[RawCue]:
    response = httpx.get(url, timeout=20, follow_redirects=True)
    response.raise_for_status()
    if len(response.content) > MAX_CAPTION_BYTES:
        raise ValueError("transcript demasiado grande")
    return parse_json3(response.json())


def download_audio(video_id: str, directory: Path, cancelled: threading.Event) -> Path:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    def hook(_status: dict) -> None:
        if cancelled.is_set():
            raise DownloadError("cancelado")

    options = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(directory / "%(id)s.%(ext)s"),
        "progress_hooks": [hook],
        "max_filesize": 1024 * 1024 * 1024,
    }
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url(video_id), download=True)
            return Path(ydl.prepare_filename(info))
    except DownloadError as exc:
        if cancelled.is_set():
            raise
        raise VideoUnavailable("No se pudo descargar el audio del vídeo.") from exc


def split_long(cue: RawCue) -> list[RawCue]:
    """Parte los segmentos largos de Whisper por frases, repartiendo el tiempo
    en proporción a los caracteres."""
    if cue.end_ms - cue.start_ms <= LONG_SEGMENT_S * 1000 and len(cue.text) <= LONG_SEGMENT_CHARS:
        return [cue]
    pieces = [piece.strip() for piece in SENTENCE_END.split(cue.text) if piece.strip()]
    if len(pieces) < 2:
        return [cue]
    total = sum(len(piece) for piece in pieces)
    span = cue.end_ms - cue.start_ms
    result, cursor = [], cue.start_ms
    for index, piece in enumerate(pieces):
        end = cue.end_ms if index == len(pieces) - 1 else cursor + round(span * len(piece) / total)
        result.append(RawCue(cursor, max(end, cursor + 1), piece))
        cursor = end
    return result


def whisper_cues(engine, path: Path, on_duration) -> Iterator[RawCue]:
    previous = ""
    for start, end, text, no_speech, logprob, compression in engine.transcribe_file(str(path), on_duration):
        text = text.strip()
        if not text or text == previous:
            continue
        if no_speech > 0.6 and logprob < -1.0 or compression > 2.4:
            continue
        previous = text
        yield from split_long(RawCue(round(start * 1000), round(end * 1000), text))


# -- trabajo ---------------------------------------------------------------------


class VideoJob:
    def __init__(self, video_id: str, target: str) -> None:
        self.video_id = video_id
        self.target = target
        self.status: Status = "queued"
        self.error = ""
        self.title = ""
        self.channel = ""
        self.duration_s = 0.0
        self.source = ""
        self.progress = 0.0
        self.cues: list[dict] = []
        self.cancelled = threading.Event()

    def snapshot(self, since: int = 0) -> dict:
        return {
            "video_id": self.video_id, "target": self.target, "status": self.status,
            "error": self.error, "title": self.title, "channel": self.channel,
            "duration_s": self.duration_s, "source": self.source,
            "progress": round(self.progress, 3), "total": len(self.cues),
            "cues": self.cues[since:],
        }

    def document(self) -> dict:
        return {
            "video_id": self.video_id, "target": self.target, "title": self.title,
            "channel": self.channel, "duration_s": self.duration_s, "source": self.source,
            "cues": self.cues,
        }


class VideoLibrary:
    """Reparte los trabajos y recuerda los terminados. Un único trabajo pesado a
    la vez: Whisper y el traductor comparten la GPU con las sesiones en directo."""

    def __init__(self, state) -> None:
        self._state = state
        self._jobs: dict[tuple[str, str], VideoJob] = {}
        self._lock = threading.Lock()
        self._busy = threading.Lock()

    def _cache_path(self, video_id: str, target: str) -> Path:
        return self._state.settings.library_dir / f"{video_id}.{target}.json"

    def cached(self, video_id: str, target: str) -> VideoJob | None:
        with self._lock:
            job = self._jobs.get((video_id, target))
        if job is not None:
            return job
        path = self._cache_path(video_id, target)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["video_id"] != video_id or data["target"] != target:
                return None
            job = VideoJob(video_id, target)
            job.title, job.channel = str(data.get("title", "")), str(data.get("channel", ""))
            job.duration_s, job.source = float(data.get("duration_s", 0)), str(data.get("source", ""))
            job.cues, job.status, job.progress = list(data["cues"]), "done", 1.0
        except (OSError, ValueError, KeyError, TypeError):
            return None
        with self._lock:
            return self._jobs.setdefault((video_id, target), job)

    def get(self, video_id: str, target: str) -> VideoJob | None:
        return self.cached(video_id, target)

    def prepare(self, video_id: str, target: str) -> VideoJob:
        existing = self.cached(video_id, target)
        if existing is not None and existing.status != "error":
            return existing
        job = VideoJob(video_id, target)
        with self._lock:
            self._jobs[(video_id, target)] = job
        threading.Thread(target=self._run, args=(job,), name=f"video-{video_id}", daemon=True).start()
        return job

    def cancel(self, video_id: str, target: str) -> None:
        with self._lock:
            job = self._jobs.get((video_id, target))
        if job is not None and job.status not in {"done", "error"}:
            job.cancelled.set()

    # -- hilo ----------------------------------------------------------------

    def _run(self, job: VideoJob) -> None:
        try:
            with self._busy:
                self._process(job)
            if job.cancelled.is_set():
                raise VideoUnavailable("Cancelado.")
            self._finish(job)
        except VideoUnavailable as exc:
            job.status, job.error = "error", str(exc)
        except Exception:  # noqa: BLE001 - el trabajo no debe tumbar el servidor
            if not job.cancelled.is_set():
                log.exception("fallo preparando %s", job.video_id)
            job.status, job.error = "error", "No se pudo preparar el vídeo. Revisa el registro."
        if job.cancelled.is_set():
            # Cancelar no es un fallo: al volver al vídeo se puede empezar de nuevo.
            with self._lock:
                if self._jobs.get((job.video_id, job.target)) is job:
                    del self._jobs[(job.video_id, job.target)]

    def _finish(self, job: VideoJob) -> None:
        job.status, job.progress = "done", 1.0
        try:
            path = self._cache_path(job.video_id, job.target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(job.document(), ensure_ascii=False), encoding="utf-8")
            write_prepared_history(self._state.settings.history_dir, job.document())
        except OSError:
            log.warning("no se pudo guardar el vídeo preparado", exc_info=True)

    def _process(self, job: VideoJob) -> None:
        state = self._state
        job.status = "resolving"
        info = resolve_video(job.video_id)
        job.title, job.channel, job.duration_s = info.title, info.channel, info.duration_s
        if info.is_live:
            raise VideoUnavailable("Es un directo: se traduce en tiempo real con el icono de YouJP.")
        if info.duration_s > MAX_DURATION_S:
            raise VideoUnavailable("El vídeo es demasiado largo para prepararlo de una vez.")

        cues: Iterator[RawCue] | None = None
        if info.caption_url:
            try:
                raw = fetch_captions(info.caption_url)
                if raw:
                    job.source = "captions"
                    cues = iter(raw)
            except (httpx.HTTPError, ValueError, KeyError):
                log.warning("transcript no disponible para %s; se usa Whisper", job.video_id, exc_info=True)

        with tempfile.TemporaryDirectory(prefix="youjp-video-") as tmp:
            if cues is None:
                job.status, job.source = "downloading", "whisper"
                path = download_audio(job.video_id, Path(tmp), job.cancelled)
                job.status = "transcribing"

                def known_duration(seconds: float) -> None:
                    job.duration_s = job.duration_s or seconds

                cues = whisper_cues(state.engine, path, known_duration)
            self._translate_all(job, cues)

    def _translate_all(self, job: VideoJob, cues: Iterator[RawCue]) -> None:
        state = self._state
        analyzer = state.new_analyzer()
        if analyzer.dictionary is not None:
            try:
                analyzer.dictionary.warmup()
            except Exception:  # noqa: BLE001 - sin diccionario solo se pierden las acepciones
                analyzer.dictionary = None
        translate = state.translator.name != "none"
        context: list[str] = []
        try:
            for cue in cues:
                if job.cancelled.is_set():
                    return
                job.status = "translating" if job.source == "captions" else "transcribing"
                translation = ""
                if translate:
                    try:
                        result = state.translator.translate(cue.text, tuple(context), target=job.target)
                        translation = result.text
                    except Exception:  # noqa: BLE001 - una frase sin traducir no invalida el vídeo
                        log.exception("falló la traducción de una frase de %s", job.video_id)
                context = (context + [cue.text])[-CONTEXT_SENTENCES:]
                try:
                    tokens = [t.model_dump(mode="json") for t in analyzer.analyze(cue.text)]
                except Exception:  # noqa: BLE001
                    log.exception("falló el análisis de una frase de %s", job.video_id)
                    tokens = []
                job.cues.append({
                    "i": len(job.cues), "start_ms": cue.start_ms, "end_ms": cue.end_ms,
                    "ja": cue.text, "tr": translation, "tokens": tokens,
                })
                if job.duration_s:
                    job.progress = min(0.99, cue.end_ms / 1000 / job.duration_s)
        finally:
            if analyzer.dictionary is not None:
                analyzer.dictionary.close()
        if not job.cues:
            raise VideoUnavailable("No se encontró habla en japonés en este vídeo.")
