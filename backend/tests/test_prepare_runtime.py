"""Installer resource preparation must respect settings and recover from failures."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def prepare(tmp_path, monkeypatch):
    import youjp.config
    import youjp.asr.engine

    spec = importlib.util.spec_from_file_location('prepare_runtime', ROOT / 'scripts/prepare_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    vad = tmp_path / 'custom-vad.onnx'
    vad.write_bytes(b'existing fixture')
    settings = SimpleNamespace(asr_model='small', asr_device='cpu', mt_provider='none',
                               vad_model=vad, port=9891)
    monkeypatch.setattr(youjp.config, 'get_settings', lambda: settings)
    monkeypatch.setattr(sys, 'argv', ['prepare_runtime.py', '--skip-dictionary'])
    monkeypatch.setitem(sys.modules, 'fetch_models', SimpleNamespace())
    calls = []

    class Engine:
        def __init__(self, config):
            assert config is settings

        def load(self):
            calls.append('load')

        def warmup(self):
            calls.append('warmup')

        def unload(self):
            calls.append('unload')

    monkeypatch.setattr(youjp.asr.engine, 'WhisperEngine', Engine)
    return module, tmp_path, calls, Engine


def test_prepare_records_effective_port_only_after_success(prepare):
    module, root, calls, _ = prepare
    module.main()
    assert calls == ['load', 'warmup', 'unload']
    config = json.loads((root / '.youjp/runtime.json').read_text())
    assert config['port'] == 9891
    assert config['mt_provider'] == 'none'
    assert (root / 'custom-vad.onnx').read_bytes() == b'existing fixture'


def test_failed_model_preparation_unloads_and_does_not_publish_runtime(prepare, monkeypatch):
    module, root, calls, engine = prepare

    def fail(self):
        raise RuntimeError('GPU unavailable')

    monkeypatch.setattr(engine, 'warmup', fail)
    with pytest.raises(RuntimeError, match='GPU unavailable'):
        module.main()
    assert calls == ['load', 'unload']
    assert not (root / '.youjp/runtime.json').exists()
