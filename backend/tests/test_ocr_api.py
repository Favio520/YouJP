"""La captura es opcional y solo acepta recortes de la extensión autorizada."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import youjp.main as server
from youjp.config import DEFAULT_ALLOWED_EXTENSION_IDS, Settings
from youjp.mt.base import Translation

ORIGIN = f"chrome-extension://{DEFAULT_ALLOWED_EXTENSION_IDS}"


class Translator:
    name = "test"

    def translate(self, text, context=(), *, target=None):
        assert target in {"es", "en"}
        return Translation(f"{target}:{text}", self.name, 1)


@pytest.fixture
def client(monkeypatch):
    state = SimpleNamespace(
        settings=Settings(_env_file=None, allowed_extension_ids=DEFAULT_ALLOWED_EXTENSION_IDS),
        translator=Translator(),
    )
    monkeypatch.setattr(server.app.state, "youjp", state, raising=False)
    monkeypatch.setattr(server, "recognize_japanese", lambda image: "猫です")
    test_client = TestClient(server.app, base_url="http://127.0.0.1:8770")
    try:
        yield test_client
    finally:
        test_client.close()


def png_header(width=200, height=100):
    return (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
            + width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")


def test_ocr_returns_japanese_and_spanish_without_starting_audio(client):
    response = client.post("/ocr/translate", content=png_header(),
                           headers={"origin": ORIGIN, "content-type": "image/png"})
    assert response.status_code == 200
    assert response.json() == {"japanese": "猫です", "spanish": "es:猫です",
                               "translation": "es:猫です", "target": "es",
                               "translation_error": None, "provider": "test"}
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_ocr_rejects_other_origins_and_bad_images(client):
    for origin in (None, "https://evil.example", "chrome-extension://" + "a" * 32):
        headers = {"content-type": "image/png"}
        if origin:
            headers["origin"] = origin
        response = client.post("/ocr/translate", content=png_header(), headers=headers)
        assert response.status_code == 403
    headers = {"origin": ORIGIN, "content-type": "image/png"}
    assert client.post("/ocr/translate", content=b"not png", headers=headers).status_code == 400
    assert client.post("/ocr/translate", content=png_header(4000, 4000),
                       headers=headers).status_code == 413


def test_ocr_preflight_uses_exact_extension_origin(client):
    assert client.options("/ocr/translate", headers={"origin": ORIGIN}).status_code == 204
    assert client.options("/ocr/translate", headers={"origin": "https://evil.example"}).status_code == 403


def test_missing_optional_ocr_reports_install_command(client, monkeypatch):
    def missing(_image):
        raise RuntimeError("Falta el OCR opcional. Ejecuta: uv sync --extra ocr")

    monkeypatch.setattr(server, "recognize_japanese", missing)
    response = client.post("/ocr/translate", content=png_header(),
                           headers={"origin": ORIGIN, "content-type": "image/png"})
    assert response.status_code == 503
    assert "uv sync --extra ocr" in response.json()["detail"]
    assert response.headers["access-control-allow-origin"] == ORIGIN


@pytest.mark.parametrize("content,media_type,status", [
    (b"invalid", "image/png", 400),
    (png_header(4000, 4000), "image/png", 413),
    (png_header(), "image/jpeg", 415),
])
def test_ocr_validation_errors_are_visible_to_the_extension(client, content, media_type, status):
    response = client.post("/ocr/translate", content=content,
                           headers={"origin": ORIGIN, "content-type": media_type})
    assert response.status_code == status
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["vary"] == "Origin"


def test_ocr_engine_errors_keep_cors_headers(client, monkeypatch):
    def fail(_):
        raise ValueError("invalid compressed image")

    monkeypatch.setattr(server, "recognize_japanese", fail)
    response = client.post("/ocr/translate", content=png_header(),
                           headers={"origin": ORIGIN, "content-type": "image/png"})
    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_ocr_accepts_case_insensitive_media_type(client):
    response = client.post("/ocr/translate", content=png_header(),
                           headers={"origin": ORIGIN, "content-type": "IMAGE/PNG; charset=binary"})
    assert response.status_code == 200


def test_ocr_respects_english_and_rejects_unsupported_language(client):
    headers = {"origin": ORIGIN, "content-type": "image/png"}
    result = client.post("/ocr/translate?target=en", content=png_header(), headers=headers)
    assert result.json()["translation"] == "en:猫です"
    assert result.json()["target"] == "en"
    assert result.json()["spanish"] == ""
    assert client.post("/ocr/translate?target=fr", content=png_header(), headers=headers).status_code == 422


def test_translation_failure_keeps_recognized_text_and_can_retry_without_ocr(client, monkeypatch):
    translator = server.app.state.youjp.translator
    original = translator.translate

    def fail(*args, **kwargs):
        raise TimeoutError("Ollama timed out")

    monkeypatch.setattr(translator, "translate", fail)
    response = client.post("/ocr/translate?target=en", content=png_header(),
                           headers={"origin": ORIGIN, "content-type": "image/png"})
    assert response.json()["japanese"] == "猫です"
    assert response.json()["translation_error"] == "translation_failed"
    assert response.json()["provider"] == "test"
    monkeypatch.setattr(translator, "translate", original)
    monkeypatch.setattr(server, "recognize_japanese", lambda _: pytest.fail("retry must not run OCR"))
    retry = client.post("/ocr/translate-text", json={"japanese": "猫です", "target": "en"},
                        headers={"origin": ORIGIN})
    assert retry.status_code == 200
    assert retry.json()["translation"] == "en:猫です"
    assert retry.json()["translation_error"] is None


def test_retry_checks_origin_language_and_text_size(client):
    assert client.post("/ocr/translate-text", json={"japanese": "猫"}).status_code == 403
    for data in [{"japanese": "猫", "target": "fr"}, {"japanese": ""}, {"japanese": "猫" * 8001}]:
        response = client.post("/ocr/translate-text", json=data, headers={"origin": ORIGIN})
        assert response.status_code == 422
        assert response.headers["access-control-allow-origin"] == ORIGIN
