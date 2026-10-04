"""Historial de páginas traducidas.

Cada sesión de captura se guarda como un fichero JSONL en ``.youjp/history``
para que el lanzador de Windows pueda listarlas sin hablar con el backend:

    {"kind": "session", "id": ..., "started_at": ..., "video_id": ..., "url": ..., "target": ...}
    {"kind": "line", "id": 3, "start_ms": 12000, "ja": "..."}
    {"kind": "tr", "id": 3, "text": "..."}

El fichero se crea con la primera frase final: una sesión que no llegó a
transcribir nada no aporta nada al historial.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from pydantic import BaseModel

from youjp.contract import AsrFinal, MtFinal, SessionStart

log = logging.getLogger(__name__)

MAX_SESSIONS = 100


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
