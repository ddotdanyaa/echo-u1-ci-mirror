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


# --- E92
def helper_file(rig):
    folder = Path(rig.api.__file__).parent
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'watch_audio_helper.py').write_text('', encoding='utf-8')


class Pool:
    """A stand-in for the pool of spare helpers that only counts what the host asks of it."""
    made = []

    def __init__(self, factory):
        self.factory, self.asked = factory, 0
        Pool.made.append(self)

    def ensure_later(self):
        self.asked += 1

    def take(self):
        return None


def test_e92_the_first_call_of_the_process_asks_the_pool_for_a_started_helper_as_it_arrives(tmp_path, monkeypatch):
    Pool.made = []
    monkeypatch.setattr(controlled_host, 'SpareHelper', Pool)

    async def main():
        F.patch_clock(monkeypatch)
        rig = F.HostRig(tmp_path, monkeypatch)
        helper_file(rig)
        async with rig as host:
            await host.handshake()
            assert len(Pool.made) == 1 and Pool.made[0].asked == 1, 'one request, made when the call arrived (the end of the call asks the next one)'
    F.run(main)


def test_e92_with_no_helper_file_there_is_nothing_to_start_early(tmp_path, monkeypatch):
    Pool.made = []
    monkeypatch.setattr(controlled_host, 'SpareHelper', Pool)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
            assert len(Pool.made) == 1 and Pool.made[0].asked == 0
    F.run(main)


def bridge_class(made):
    class Bridge:
        def __init__(self, *args, **kwargs):
            self.started, self.closed, self.stage, self.process = 0, False, 0, SimpleNamespace(returncode=None)
            made.append(self)

        async def start(self):
            await asyncio.sleep(0.05)      # a helper takes time to start: that is the point
            self.started += 1
            return self

        async def send(self, kind, payload):
            pass

        async def receive(self, timeout):
            self.stage += 1
            if self.stage == 1:
                return ('O', b'v=0\n')
            if self.stage == 2:
                return ('R', b'')
            return ('e', b'{"type":"session.started"}')

        async def close(self):
            self.closed = True
            self.process.returncode = 0
    return Bridge


def cloud():
    async def scoped(profile, fn):
        return {'auth': 'subscription', 'transport': {'sdp': 'answer'}}
    return SimpleNamespace(_run_scoped=scoped, WATCH_AUDIO_CONNECT_TIMEOUT_S=0.5, WATCH_AUDIO_STUN=())


def test_e92_an_open_joins_the_helper_the_pool_is_starting_and_does_not_start_a_second_one():
    made = []
    Bridge = bridge_class(made)
    spare = helper_pool.SpareHelper(Bridge)

    async def run():
        spare.ensure_later()
        await asyncio.sleep(0)      # the start is under way
        bridge = await open_subscription(cloud(), 'p', 'unused', ('python', {}, (), ''), bridge_factory=Bridge, spare=spare)
        assert len(made) == 1 and bridge is made[0] and bridge.started == 1, 'one helper: the one that was being started'
        await spare.close()
    asyncio.run(run())


def test_e92_a_start_that_failed_is_no_spare_and_the_open_starts_its_own():
    made = []
    Bridge = bridge_class(made)

    class Failing(Bridge):
        async def start(self):
            await asyncio.sleep(0.01)
            if len(made) == 1:
                raise OSError('no helper')
            return await super().start()

    spare = helper_pool.SpareHelper(Failing)

    async def run():
        spare.ensure_later()
        await asyncio.sleep(0)
        bridge = await open_subscription(cloud(), 'p', 'unused', ('python', {}, (), ''), bridge_factory=Failing, spare=spare)
        assert len(made) == 2 and bridge is made[1]
        await spare.close()
    asyncio.run(run())


