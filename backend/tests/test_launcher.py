import asyncio
from types import SimpleNamespace

import pytest

from youjp import launcher
from youjp.config import Settings


@pytest.mark.asyncio
async def test_owned_stop_signal_gracefully_exits_and_is_consumed(tmp_path, monkeypatch):
    signal = tmp_path / 'stop-owned-run'
    instances = []

    class FakeServer:
        def __init__(self, config):
            self.should_exit = False
            self.config = config
            instances.append(self)

        async def serve(self):
            signal.write_text('stop')
            while not self.should_exit:
                await asyncio.sleep(0.01)

    monkeypatch.setattr(launcher.uvicorn, 'Server', FakeServer)
    monkeypatch.setattr(launcher, 'get_settings', lambda: SimpleNamespace(port=9875, log_level='INFO'))
    await asyncio.wait_for(launcher.serve(signal), 2)
    assert instances[0].should_exit
    assert instances[0].config.host == '127.0.0.1'
    assert instances[0].config.port == 9875
    assert not signal.exists()


def test_user_config_overrides_assistant_defaults(tmp_path, monkeypatch):
    for name in ('YOUJP_ASR_DEVICE', 'YOUJP_MT_PROVIDER'):
        monkeypatch.delenv(name, raising=False)
    managed = tmp_path / 'launcher.env'
    user = tmp_path / '.env'
    managed.write_text('YOUJP_ASR_DEVICE=cpu\nYOUJP_MT_PROVIDER=none\n')
    user.write_text('YOUJP_MT_PROVIDER=llm\n')
    settings = Settings(_env_file=(managed, user))
    assert settings.asr_device == 'cpu'
    assert settings.mt_provider == 'llm'
