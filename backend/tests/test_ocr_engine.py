"""The optional OCR engine must select Japanese models and load only once."""
import sys
from types import SimpleNamespace

import youjp.ocr as ocr


def test_japanese_models_are_explicit_and_reused(monkeypatch):
    loaded = []

    class Engine:
        def __init__(self, *, params):
            loaded.append(params)

        def __call__(self, png):
            assert png == b"png"
            return SimpleNamespace(txts=[" 猫です ", "", "こんにちは"])

    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(
        RapidOCR=Engine, LangRec=SimpleNamespace(JAPAN="japan"),
        ModelType=SimpleNamespace(MOBILE="mobile"), OCRVersion=SimpleNamespace(PPOCRV4="v4")))
    monkeypatch.setattr(ocr, "_engine", None)
    assert ocr.recognize_japanese(b"png") == "猫です\nこんにちは"
    assert ocr.recognize_japanese(b"png") == "猫です\nこんにちは"
    assert len(loaded) == 1
    assert loaded[0]["Rec.lang_type"] == "japan"
    assert loaded[0]["Rec.ocr_version"] == "v4"
    assert loaded[0]["Rec.model_type"] == "mobile"
