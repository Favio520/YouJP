"""OCR japonés opcional, cargado al pedir la primera captura."""

from __future__ import annotations

from pathlib import Path
from threading import Lock

_lock = Lock()
_engine = None


def recognize_japanese(png: bytes) -> str:
    """Reconoce texto en CPU sin cargar nada durante el arranque del servidor."""
    global _engine
    with _lock:
        if _engine is None:
            try:
                from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
            except ImportError as exc:
                raise RuntimeError(
                    "Falta el OCR opcional. Ejecuta: uv sync --extra ocr"
                ) from exc
            # Defaults track Chinese models across RapidOCR releases. Pin the
            # lightweight Japanese recognizer explicitly instead of relying on them.
            params = {
                "Global.model_root_dir": str(Path(__file__).resolve().parents[2] / "models" / "ocr"),
                "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                "Rec.lang_type": LangRec.JAPAN,
            }
            for section in ("Det", "Cls", "Rec"):
                params[f"{section}.ocr_version"] = OCRVersion.PPOCRV4
                params[f"{section}.model_type"] = ModelType.MOBILE
            _engine = RapidOCR(params=params)
        result = _engine(png)
    return "\n".join(line.strip() for line in (result.txts or ()) if line.strip())
