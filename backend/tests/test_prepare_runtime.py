"""Installer resource preparation must respect settings and recover from failures."""

import importlib.util
import io
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


def test_print_settings_refreshes_port_without_loading_or_downloading(prepare, monkeypatch, capsys):
    module, root, calls, _ = prepare
    runtime = root / '.youjp/runtime.json'
    runtime.parent.mkdir()
    runtime.write_text('{"port":8770}', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['prepare_runtime.py', '--print-settings'])
    monkeypatch.setitem(sys.modules, 'fetch_models', None)
    module.main()
    assert json.loads(capsys.readouterr().out)['port'] == 9891
    assert calls == []
    assert json.loads(runtime.read_text()) == {'port': 8770}


def test_failed_model_preparation_unloads_and_does_not_publish_runtime(prepare, monkeypatch):
    module, root, calls, engine = prepare

    def fail(self):
        raise RuntimeError('GPU unavailable')

    monkeypatch.setattr(engine, 'warmup', fail)
    with pytest.raises(RuntimeError, match='GPU unavailable'):
        module.main()
    assert calls == ['load', 'unload']
    assert not (root / '.youjp/runtime.json').exists()


@pytest.mark.parametrize('response', [b'', b'{"status":"downloading"}\n', b'[]\n'])
def test_incomplete_ollama_pull_does_not_publish_runtime(prepare, monkeypatch, response):
    import youjp.config

    module, root, _, _ = prepare
    settings = youjp.config.get_settings()
    settings.mt_provider = 'llm'
    settings.llm_url = 'http://localhost:11434'
    settings.llm_model = 'fixture'
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(response))
    with pytest.raises(RuntimeError, match='No se pudo preparar Ollama'):
        module.main()
    assert not (root / '.youjp/runtime.json').exists()


def test_successful_ollama_pull_publishes_runtime(prepare, monkeypatch):
    import youjp.config

    module, root, _, _ = prepare
    settings = youjp.config.get_settings()
    settings.mt_provider = 'llm'
    settings.llm_url = 'http://localhost:11434'
    settings.llm_model = 'fixture'
    monkeypatch.setattr(module.urllib.request, 'urlopen',
                        lambda *a, **kw: io.BytesIO(b'{"status":"success"}\n'))
    module.main()
    assert json.loads((root / '.youjp/runtime.json').read_text())['mt_provider'] == 'llm'


def test_runtime_publication_failure_preserves_previous_json(prepare, monkeypatch):
    module, root, _, _ = prepare
    target = root / 'runtime.json'
    target.write_text('{"port":8770}', encoding='utf-8')

    def fail_replace(self, destination):
        assert json.loads(self.read_text()) == {'port': 9891}
        raise OSError('cannot replace')

    monkeypatch.setattr(Path, 'replace', fail_replace)
    with pytest.raises(OSError, match='cannot replace'):
        module.write_runtime(target, {'port': 9891})
    assert json.loads(target.read_text()) == {'port': 8770}
    assert not list(root.glob('.runtime.json.*.tmp'))


def test_failed_dictionary_build_cleans_partial_file_and_can_retry(prepare, monkeypatch):
    import sqlite3
    import youjp.config
    import youjp.dict.build_db

    module, root, _, _ = prepare
    settings = youjp.config.get_settings()
    settings.dict_db = root / 'dictionary.sqlite3'
    settings.data_dir = root / 'data'
    monkeypatch.setattr(sys, 'argv', ['prepare_runtime.py'])
    monkeypatch.setitem(sys.modules, 'fetch_dicts', SimpleNamespace(main=lambda: 0))

    def fail_build(conn, *paths):
        conn.execute('CREATE TABLE partial (value TEXT)')
        conn.commit()
        raise RuntimeError('interrupted build')

    monkeypatch.setattr(youjp.dict.build_db, 'build', fail_build)
    with pytest.raises(RuntimeError, match='interrupted build'):
        module.main()
    assert not settings.dict_db.exists()
    assert not list(root.glob('*.building.sqlite3*'))
    assert not (root / '.youjp/runtime.json').exists()

    def successful_build(conn, *paths):
        conn.execute('CREATE TABLE complete (value TEXT)')
        conn.commit()

    monkeypatch.setattr(youjp.dict.build_db, 'build', successful_build)
    module.main()
    with sqlite3.connect(settings.dict_db) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall() == [('complete',)]
    assert not list(root.glob('*.building.sqlite3*'))
