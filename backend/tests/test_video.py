import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import youjp.main as server
import youjp.video as video
from youjp.config import DEFAULT_ALLOWED_EXTENSION_IDS, Settings
from youjp.video import RawCue, VideoInfo, VideoLibrary, parse_json3, split_long

ID = "dQw4w9WgXcQ"
ORIGIN = f"chrome-extension://{DEFAULT_ALLOWED_EXTENSION_IDS}"


class Translator:
    name = "test"

    def translate(self, text, context=(), *, target=None):
        return SimpleNamespace(text=f"[{target}] {text}")


class Analyzer:
    dictionary = None

    def analyze(self, text):
        return []


def make_state(tmp_path):
    state = SimpleNamespace(
        settings=Settings(_env_file=None, history_dir=tmp_path / "history", library_dir=tmp_path / "library",
                          allowed_extension_ids=DEFAULT_ALLOWED_EXTENSION_IDS),
        translator=Translator(), engine=object(), new_analyzer=lambda: Analyzer(), sessions=0)
    state.videos = VideoLibrary(state)
    return state


def wait_done(library, target="es"):
    for _ in range(200):
        job = library.get(ID, target)
        if job is not None and job.status in {"done", "error"}:
            return job
        time.sleep(0.02)
    raise AssertionError("el trabajo no terminó")


def test_parse_json3_skips_empty_events_and_joins_segments():
    data = {"events": [
        {"tStartMs": 0, "dDurationMs": 1500, "segs": [{"utf8": "こんにちは"}, {"utf8": "、世界"}]},
        {"tStartMs": 1500, "dDurationMs": 100, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 2000},
        {"tStartMs": 3000, "dDurationMs": 500, "segs": [{"utf8": "はい"}]},
    ]}
    assert parse_json3(data) == [RawCue(0, 1500, "こんにちは、世界"), RawCue(3000, 3500, "はい")]


def test_split_long_distributes_time_by_sentence():
    cue = RawCue(0, 20_000, "これは最初の文です。これは二番目の文ですよ。")
    parts = split_long(cue)
    assert [p.text for p in parts] == ["これは最初の文です。", "これは二番目の文ですよ。"]
    assert parts[0].start_ms == 0 and parts[-1].end_ms == 20_000 and parts[0].end_ms == parts[1].start_ms
    assert split_long(RawCue(0, 2000, "短い")) == [RawCue(0, 2000, "短い")]


def test_manual_captions_are_used_without_whisper(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "resolve_video", lambda _id: VideoInfo("Título", "Canal", 60, False, "http://x"))
    monkeypatch.setattr(video, "fetch_captions", lambda _url: [RawCue(0, 1000, "一"), RawCue(1000, 2000, "二")])
    monkeypatch.setattr(video, "download_audio", lambda *a: pytest.fail("no debe descargar audio"))
    state = make_state(tmp_path)
    state.videos.prepare(ID, "es")
    job = wait_done(state.videos)
    assert job.status == "done" and job.source == "captions"
    assert [c["tr"] for c in job.cues] == ["[es] 一", "[es] 二"]
    assert (tmp_path / "library" / f"{ID}.es.json").exists()
    (history,) = (tmp_path / "history").glob("*-prepared-*.jsonl")
    assert "Canal" in history.read_text(encoding="utf-8")


def test_without_captions_it_falls_back_to_whisper(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "resolve_video", lambda _id: VideoInfo("T", "C", 0, False, None))
    monkeypatch.setattr(video, "download_audio", lambda *a: tmp_path / "audio.m4a")

    def fake_whisper(engine, path, on_duration):
        on_duration(10.0)
        yield RawCue(0, 2000, "音声")

    monkeypatch.setattr(video, "whisper_cues", fake_whisper)
    state = make_state(tmp_path)
    state.videos.prepare(ID, "en")
    job = wait_done(state.videos, "en")
    assert job.source == "whisper" and job.duration_s == 10.0 and job.cues[0]["tr"] == "[en] 音声"


def test_live_streams_are_rejected_and_can_be_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "resolve_video", lambda _id: VideoInfo("T", "C", 0, True, None))
    state = make_state(tmp_path)
    state.videos.prepare(ID, "es")
    job = wait_done(state.videos)
    assert job.status == "error" and "directo" in job.error
    assert state.videos.prepare(ID, "es") is not job


def test_finished_video_is_reloaded_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "resolve_video", lambda _id: VideoInfo("T", "C", 5, False, "u"))
    monkeypatch.setattr(video, "fetch_captions", lambda _url: [RawCue(0, 1000, "一")])
    state = make_state(tmp_path)
    state.videos.prepare(ID, "es")
    wait_done(state.videos)
    reloaded = VideoLibrary(state).get(ID, "es")
    assert reloaded.status == "done" and reloaded.cues[0]["ja"] == "一" and reloaded.title == "T"


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server.app.state, "youjp", make_state(tmp_path), raising=False)
    return TestClient(server.app, base_url="http://127.0.0.1:8770")


def post(c, path, body, origin=ORIGIN):
    return c.post(path, json=body, headers={"origin": origin, "host": "127.0.0.1:8770"})


def test_endpoints_validate_origin_and_video_id(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert post(c, "/video/poll", {"video_id": ID}, origin="https://example.com").status_code == 403
    assert post(c, "/video/poll", {"video_id": "../../etc/passwd"}).status_code == 422
    response = post(c, "/video/poll", {"video_id": ID})
    assert response.json() == {"status": "none"}
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_prepare_and_poll_return_cues_incrementally(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "resolve_video", lambda _id: VideoInfo("T", "C", 5, False, "u"))
    monkeypatch.setattr(video, "fetch_captions", lambda _url: [RawCue(0, 1000, "一"), RawCue(1000, 2000, "二")])
    c = client(tmp_path, monkeypatch)
    assert post(c, "/video/prepare", {"video_id": ID}).status_code == 200
    wait_done(server.app.state.youjp.videos)
    data = post(c, "/video/poll", {"video_id": ID, "since": 1}).json()
    assert data["status"] == "done" and data["total"] == 2 and [x["ja"] for x in data["cues"]] == ["二"]


def test_cancelled_job_is_forgotten(tmp_path, monkeypatch):
    def slow(_id):
        time.sleep(0.2)
        return VideoInfo("T", "C", 5, False, "u")

    monkeypatch.setattr(video, "resolve_video", slow)
    monkeypatch.setattr(video, "fetch_captions", lambda _url: [RawCue(0, 1000, "一")])
    state = make_state(tmp_path)
    job = state.videos.prepare(ID, "es")
    state.videos.cancel(ID, "es")
    for _ in range(100):
        if job.status in {"done", "error"}:
            break
        time.sleep(0.02)
    time.sleep(0.05)
    assert state.videos.get(ID, "es") is None
