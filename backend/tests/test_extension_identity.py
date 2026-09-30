"""El ID permitido debe coincidir con la clave pública del manifest."""

import base64
import hashlib
import re
from pathlib import Path

from youjp.config import DEFAULT_ALLOWED_EXTENSION_IDS


def test_default_extension_id_matches_manifest_public_key():
    config = Path(__file__).resolve().parents[2] / "extension" / "wxt.config.ts"
    source = config.read_text(encoding="utf-8")
    match = re.search(r"\bkey:[^'\n]*'([^']+)'", source)
    assert match is not None
    digest = hashlib.sha256(base64.b64decode(match.group(1), validate=True)).hexdigest()[:32]
    expected = "".join(chr(ord("a") + int(nibble, 16)) for nibble in digest)
    assert DEFAULT_ALLOWED_EXTENSION_IDS == expected
