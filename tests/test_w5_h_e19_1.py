"""w5 H (modes and host): E19.1, E92, E97 through the real ``controlled_host`` (the HostRig of helpers_s6_fault: the real ``serve``, a fake phone, a fake helper pipe).

E19.1  a redial while the disk does not answer keeps the settings of the conversation (before: the defaults, in the middle of a talk).
E92    the first call of a process asks the pool for a started helper as it arrives (before: at the END of the call), and an open joins a start that is already under way instead of starting a second helper.
E97    the passport of a call (its trace) holds a hash of the profile (subject, audience, style, version of the material) and never a word of it.
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import helpers_s6_fault as F
from echo_sync import controlled_host, degradation, helper_pool
from echo_sync.controlled_host import ControlledMedia, open_subscription


@pytest.fixture(autouse=True)
def _clean_host_state(monkeypatch):
    monkeypatch.setattr(controlled_host, '_LAST_SETTINGS', {})
    monkeypatch.setattr(controlled_host, '_SPARES', {})
    degradation.reset()
    yield
    degradation.reset()


def profile(host, **values):
    folder = Path(host.home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def spy_controller(monkeypatch):
    """The real ControlledMedia, recording the keywords it was built with."""
    built = []

    class Spy(ControlledMedia):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            built.append(k)
    monkeypatch.setattr(controlled_host, 'ControlledMedia', Spy)
    return built


# --- E19.1
def test_e19_1_a_redial_with_a_disk_that_does_not_answer_keeps_the_settings_of_the_conversation(tmp_path, monkeypatch):
    built = spy_controller(monkeypatch)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            profile(host, repeat_seconds=9, max_auto_repeats=2)
            await host.handshake()

        def broken(path):
            raise OSError('disk')
        monkeypatch.setattr(controlled_host, 'load_settings', broken)
        async with F.HostRig(tmp_path, monkeypatch) as host:      # the same phone dials again: the same profile, the file cannot be read this second
            await host.handshake()
            assert 'недоступно: host.profile_settings — OSError' in host.logger.text()      # it is still said (U78)
    F.run(main)
    assert [(k['repeat_seconds'], k['max_auto_repeats']) for k in built] == [(9, 2), (9, 2)], 'the second call runs on the owner\'s settings, not on the defaults'


def test_e19_1_a_profile_never_read_in_this_process_is_still_the_defaults(tmp_path, monkeypatch):
    built = spy_controller(monkeypatch)

    def broken(path):
        raise OSError('disk')
    monkeypatch.setattr(controlled_host, 'load_settings', broken)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
    F.run(main)
    assert [(k['repeat_seconds'], k['max_auto_repeats']) for k in built] == [(6, 1)]


