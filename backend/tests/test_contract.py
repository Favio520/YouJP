"""Single-source versions and generated files must never drift."""

import importlib.util
from pathlib import Path

from youjp import __version__
from youjp.contract import APP_VERSION, AUDIO_VERSION
from youjp.ws.codec import VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_generated_contract_is_current():
    spec = importlib.util.spec_from_file_location("generate_contract", ROOT / "scripts/generate_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for path, expected in module.outputs().items():
        assert path.read_text(encoding="utf-8") == expected, f"Regenerate {path} with scripts/generate_contract.py"


def test_release_version_and_audio_codec_agree():
    assert __version__ == APP_VERSION == (ROOT / "VERSION").read_text().strip()
    assert VERSION == AUDIO_VERSION
