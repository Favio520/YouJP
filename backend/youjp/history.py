"""Historial de páginas traducidas.

Cada sesión de captura se guarda como un fichero JSONL en ``.youjp/history``
para que el lanzador de Windows pueda listarlas sin hablar con el backend:

    {"kind": "session", "id": ..., "started_at": ..., "video_id": ..., "url": ..., "target": ...}
    {"kind": "line", "id": 3, "start_ms": 12000, "ja": "..."}
    {"kind": "tr", "id": 3, "text": "..."}
    {"kind": "meta", "title": "...", "channel": "..."}

``meta`` llega después y es opcional: se consulta a YouTube sin bloquear la sesión.

El fichero se crea con la primera frase final: una sesión que no llegó a
transcribir nada no aporta nada al historial.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

from youjp.contract import AsrFinal, MtFinal, SessionStart

log = logging.getLogger(__name__)

MAX_SESSIONS = 100
OEMBED = "https://www.youtube.com/oembed"


def fetch_video_meta(video_id: str) -> dict[str, str]:
    """Título y canal públicos de un vídeo, sin yt-dlp. Vacío si no hay red."""
    try:
        response = httpx.get(
            OEMBED, params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        return {"title": str(data.get("title", "")), "channel": str(data.get("author_name", ""))}
    except (httpx.HTTPError, ValueError):
        return {}


class HistoryRecorder:
    def __init__(self, directory: Path, session_id: str, start: SessionStart) -> None:
        self._directory = directory
        self._session_id = session_id
        self._header = {
            "kind": "session",
            "id": session_id,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "video_id": start.video_id,
            "url": start.url,
            "target": start.target,
        }
        self._path: Path | None = None
        self._failed = False
        self._meta_requested = False

    def _fetch_meta(self) -> None:
        meta = fetch_video_meta(self._header["video_id"])
        if meta.get("title") and not self._failed:
            try:
                self._append({"kind": "meta", **meta})
            except OSError:
                log.warning("no se pudo guardar el título del vídeo", exc_info=True)

    def record(self, message: BaseModel) -> None:
        if self._failed:
            return
        if isinstance(message, AsrFinal) and message.text.strip():
            self._write({"kind": "line", "id": message.segment_id,
                         "start_ms": message.media_start_ms, "ja": message.text})
        elif isinstance(message, MtFinal) and self._path is not None:
            text = message.text or message.text_es
            if text:
                self._write({"kind": "tr", "id": message.segment_id, "text": text})

    def _write(self, entry: dict) -> None:
        try:
            if self._path is None:
                self._directory.mkdir(parents=True, exist_ok=True)
                self._path = self._directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{self._session_id}.jsonl"
                self._append(self._header)
                self._prune()
            self._append(entry)
            if not self._meta_requested and self._header["video_id"]:
                self._meta_requested = True
                threading.Thread(target=self._fetch_meta, name="history-meta", daemon=True).start()
        except OSError:
            # El historial es un extra: nunca debe tumbar la transcripción.
            self._failed = True
            log.warning("no se pudo guardar el historial", exc_info=True)

    def _append(self, entry: dict) -> None:
        assert self._path is not None
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _prune(self) -> None:
        files = sorted(self._directory.glob("*.jsonl"))
        for old in files[:-MAX_SESSIONS]:
            old.unlink(missing_ok=True)


def write_prepared_history(directory: Path, document: dict) -> None:
    """Guarda un vídeo traducido de una vez con el mismo formato que las sesiones."""
    directory.mkdir(parents=True, exist_ok=True)
    video_id = document["video_id"]
    # Preparar de nuevo el mismo vídeo sustituye a la entrada anterior.
    for old in directory.glob(f"*-prepared-{video_id}.jsonl"):
        old.unlink(missing_ok=True)
    path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-prepared-{video_id}.jsonl"
    rows: list[dict] = [
        {"kind": "session", "id": f"prepared-{video_id}", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
         "video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
         "target": document["target"], "source": document.get("source", "")},
        {"kind": "meta", "title": document.get("title", ""), "channel": document.get("channel", "")},
    ]
    for cue in document["cues"]:
        rows.append({"kind": "line", "id": cue["i"], "start_ms": cue["start_ms"], "ja": cue["ja"]})
        if cue["tr"]:
            rows.append({"kind": "tr", "id": cue["i"], "text": cue["tr"]})
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    files = sorted(directory.glob("*.jsonl"))
    for old in files[:-MAX_SESSIONS]:
        old.unlink(missing_ok=True)
