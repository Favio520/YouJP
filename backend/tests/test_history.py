import json

from youjp.history import HistoryRecorder, MAX_SESSIONS
from youjp.ws.protocol import APP_VERSION, PROTOCOL_VERSION, AsrFinal, MtFinal, SessionStart


def start():
    return SessionStart(protocol_version=PROTOCOL_VERSION, app_version=APP_VERSION,
                        video_id="abc", url="https://www.youtube.com/watch?v=abc")


def final(i, text):
    return AsrFinal(segment_id=i, text=text, media_start_ms=i * 1000, media_end_ms=i * 1000 + 900,
                    reason="vad", latency_ms=1)


def test_session_without_sentences_leaves_no_file(tmp_path):
    HistoryRecorder(tmp_path, "s1", start())
    assert not list(tmp_path.glob("*.jsonl"))


def test_records_header_sentences_and_translations(tmp_path):
    recorder = HistoryRecorder(tmp_path, "s1", start())
    recorder.record(final(1, "こんにちは"))
    recorder.record(MtFinal(segment_id=1, text="Hola", provider="t", media_start_ms=1000,
                            media_end_ms=1900, latency_ms=1))
    (path,) = tmp_path.glob("*.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in rows] == ["session", "line", "tr"]
    assert rows[0]["video_id"] == "abc" and rows[1]["ja"] == "こんにちは" and rows[2]["text"] == "Hola"


def test_old_sessions_are_pruned(tmp_path):
    for i in range(MAX_SESSIONS + 3):
        (tmp_path / f"2000{i:04d}-old.jsonl").write_text("{}", encoding="utf-8")
    HistoryRecorder(tmp_path, "new", start()).record(final(1, "はい"))
    assert len(list(tmp_path.glob("*.jsonl"))) == MAX_SESSIONS
