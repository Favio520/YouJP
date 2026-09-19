"""Provider routing without a GPU, plus worker language-switch races."""

import json
import queue
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from youjp.config import Settings
from youjp.mt.base import Translation
from youjp.mt.ct2_nllb import Nllb200Provider
from youjp.mt.llm import LlmProvider, SYSTEM_PROMPTS
from youjp.pipeline.translate import MtWorker, TranslationJob
from youjp.ws.protocol import SessionConfigure, parse_client_message


@pytest.mark.parametrize("target", ["es", "en"])
@pytest.mark.parametrize("kind", ["session.start", "session.configure"])
def test_protocol_accepts_supported_targets(target, kind):
    message = parse_client_message(json.dumps({"type": kind, "target": target}))
    assert message.target == target
    if kind == "session.configure":
        assert isinstance(message, SessionConfigure)


@pytest.mark.parametrize("target", ["fr", "eng_Latn", "", None])
@pytest.mark.parametrize("kind", ["session.start", "session.configure"])
def test_protocol_rejects_unsupported_targets(target, kind):
    with pytest.raises(ValidationError):
        parse_client_message(json.dumps({"type": kind, "target": target}))


def test_protocol_rejects_non_japanese_source():
    with pytest.raises(ValidationError):
        parse_client_message('{"type":"session.start","source":"en"}')


@pytest.mark.parametrize("target", ["es", "en"])
def test_llm_uses_target_prompt_and_preserves_shared_settings(target):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '<think>hidden</think>"Hello\nworld"'}})

    provider = LlmProvider(Settings(_env_file=None))
    provider._client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    try:
        result = provider.translate("こんにちは", ["西山さん"], target=target)
        assert result.text == "Hello world"
        assert requests[0]["messages"][0]["content"] == SYSTEM_PROMPTS[target]
        assert "西山さん" in requests[0]["messages"][1]["content"]
        assert requests[0]["think"] is False
        assert provider.settings.mt_target_lang == "spa_Latn"
    finally:
        provider.unload()


def test_llm_default_can_be_english():
    provider = LlmProvider(Settings(_env_file=None, mt_target_lang="eng_Latn"))
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "Good morning."}})

    provider._client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    try:
        assert provider.translate("おはようございます。").text == "Good morning."
        assert seen[0]["messages"][0]["content"] == SYSTEM_PROMPTS["en"]
    finally:
        provider.unload()


@pytest.mark.parametrize("target,code", [("es", "spa_Latn"), ("en", "eng_Latn")])
def test_nllb_sets_per_call_prefix(target, code):
    provider = Nllb200Provider(Settings(_env_file=None))
    seen = []

    def translate_batch(source, **options):
        seen.append(options)
        return [SimpleNamespace(hypotheses=[[code, "translated"]])]

    provider._translator = SimpleNamespace(translate_batch=translate_batch)
    provider._tokenizer = SimpleNamespace(
        encode=lambda text: [1], convert_ids_to_tokens=lambda ids: ["source"],
        convert_tokens_to_ids=lambda tokens: tokens, decode=lambda tokens: " ".join(tokens),
    )
    assert provider.translate("日本語", target=target).text == "translated"
    assert seen[0]["target_prefix"] == [[code]]
    assert provider.settings.mt_target_lang == "spa_Latn"


class FakeProvider:
    name = "fake"

    def __init__(self, block_first=False):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_first = block_first

    def translate(self, text, context=(), *, target=None):
        self.calls.append((text, context, target))
        if self.block_first and len(self.calls) == 1:
            self.entered.set()
            assert self.release.wait(3), "test did not release translation"
        return Translation(f"{target}:{text}", self.name, 1.0)


def job(index):
    return TranslationJob(index, f"phrase-{index}", index * 100, index * 100 + 99, time.perf_counter())


@pytest.mark.parametrize("target", ["es", "en"])
def test_worker_emits_language_and_legacy_spanish_only(target):
    output = queue.Queue()
    provider = FakeProvider()
    worker = MtWorker(provider, output.put_nowait, target=target)
    worker.start()
    try:
        worker.submit(job(1))
        result = output.get(timeout=2)
        assert result.target == target
        assert result.text == f"{target}:phrase-1"
        assert result.text_es == (result.text if target == "es" else "")
        worker.submit(job(2))
        output.get(timeout=2)
        assert provider.calls[1][1] == ("phrase-1",)
    finally:
        worker.stop()


def test_switch_discards_inflight_and_queued_old_language():
    output = queue.Queue()
    provider = FakeProvider(block_first=True)
    worker = MtWorker(provider, output.put_nowait)
    worker.start()
    try:
        worker.submit(job(1))
        assert provider.entered.wait(2)
        worker.submit(job(2))
        worker.set_target("en")
        worker.submit(job(3))
        provider.release.set()
        result = output.get(timeout=2)
        assert result.segment_id == 3
        assert result.target == "en"
        assert output.empty()
        assert [call[0] for call in provider.calls] == ["phrase-1", "phrase-3"]
    finally:
        provider.release.set()
        worker.stop()


def test_reset_discards_old_translation_context():
    output = queue.Queue()
    provider = FakeProvider()
    worker = MtWorker(provider, output.put_nowait)
    worker.start()
    try:
        worker.submit(job(1))
        output.get(timeout=2)
        worker.reset()
        worker.submit(job(2))
        output.get(timeout=2)
        assert provider.calls[1][1] == ()
    finally:
        worker.stop()


def test_stop_with_full_queue_is_bounded_and_suppresses_late_results():
    output = queue.Queue()
    provider = FakeProvider(block_first=True)
    worker = MtWorker(provider, output.put_nowait, max_queued=1)
    worker.start()
    try:
        worker.submit(job(1))
        assert provider.entered.wait(2)
        worker.submit(job(2))
        stopped = threading.Event()
        stopper = threading.Thread(target=lambda: (worker.stop(timeout=0.01), stopped.set()), daemon=True)
        stopper.start()
        assert stopped.wait(1), "stop blocked on a full queue"
        worker.submit(job(3))
    finally:
        provider.release.set()
        worker._thread.join(2)
    assert not worker._thread.is_alive()
    assert output.empty()


def test_sessions_keep_independent_targets_with_shared_provider():
    output = queue.Queue()
    provider = FakeProvider()
    spanish = MtWorker(provider, output.put_nowait, target="es")
    english = MtWorker(provider, output.put_nowait, target="en")
    spanish.start()
    english.start()
    try:
        spanish.submit(job(1))
        english.submit(job(2))
        assert {output.get(timeout=2).target, output.get(timeout=2).target} == {"en", "es"}
    finally:
        spanish.stop()
        english.stop()
