"""P12 modes/host: the real controlled_host.serve (HostRig) proves U34, U78, U120 and the websockets dependency (E59.1)."""
import json
import re
import time
from pathlib import Path

from echo_sync import build_info, controlled_host, degradation, ws_transport
from echo_sync.controlled_host import ControlledMedia
from helpers_spoken_diagnostics import run_host
from tools import deploy as dp

ROOT = Path(__file__).resolve().parents[1]


def profile(host, **values):
    folder = Path(host.home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


def spy_controller(monkeypatch):
    """The real ControlledMedia, recording what it held the moment it was built (before serve touches the object)."""
    built = []

    class Spy(ControlledMedia):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            built.append({'kwargs': k, 'flow': self.flow, 'self': self})
    monkeypatch.setattr(controlled_host, 'ControlledMedia', Spy)
    return built


# --- U34: the profile reaches the controller at creation, on the real host
def test_u34_profile_keys_read_in_init_are_in_effect_when_the_controller_is_created(tmp_path, monkeypatch):
    built = spy_controller(monkeypatch)

    async def body(host):
        profile(host, local_ear='act')
        await host.handshake()
        assert len(built) == 1
        one = built[0]
        assert one['kwargs']['settings']['local_ear'] == 'act'
        assert one['flow'] is not None, 'a key the controller reads only in __init__ was not there yet'
        assert one['self'].engine.settings is one['self'].settings, 'the engine decides with the very dict the controller was built with'
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_u34_host_has_no_second_copy_of_the_settings_after_creation():
    source = (ROOT / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
    assert 'controller.settings=' not in source and 'controller.engine.settings=' not in source


# --- U78: what the start of a call swallows is in the check «готово / недоступно и почему»
def test_u78_swallowed_start_failures_are_listed_before_the_call(tmp_path, monkeypatch):
    degradation.reset()

    def broken(*a, **k):
        raise RuntimeError('token=SECRET listener words')
    monkeypatch.setattr(build_info, 'fingerprint', broken)

    async def body(host):
        await host.handshake()
        text = host.logger.text()
        assert 'недоступно: host.fingerprint — RuntimeError' in text
        assert 'SECRET' not in text and 'listener words' not in text, 'the type only, never the message'
        assert any(row['component'] == 'host.fingerprint' for row in degradation.snapshot())
    run_host(tmp_path, monkeypatch, body, handshake=False)
    degradation.reset()


def test_u78_an_unreadable_profile_file_is_listed_not_only_defaulted(tmp_path, monkeypatch):
    degradation.reset()

    def broken(path):
        raise OSError('disk')
    monkeypatch.setattr(controlled_host, 'load_settings', broken)

    async def body(host):
        await host.handshake()
        assert 'недоступно: host.profile_settings — OSError' in host.logger.text()
    run_host(tmp_path, monkeypatch, body, handshake=False)
    degradation.reset()


# --- U120: a build that cannot name itself (no BUILD, no git) is not ready; deploy and rollback are repeatable and named by the BUILD sha
def test_u120_a_build_with_no_name_is_not_ready(tmp_path, monkeypatch):
    degradation.reset()
    monkeypatch.setattr(build_info, 'build_id', lambda root=None: 'unknown')

    async def body(host):
        await host.handshake()
        assert 'недоступно: host.build — unknown' in host.logger.text()
    run_host(tmp_path, monkeypatch, body, handshake=False)
    degradation.reset()


def test_u120_a_named_build_adds_no_line(tmp_path, monkeypatch):
    degradation.reset()
    monkeypatch.setattr(build_info, 'build_id', lambda root=None: 'abc123def456')

    async def body(host):
        await host.handshake()
        assert 'host.build' not in host.logger.text()
    run_host(tmp_path, monkeypatch, body, handshake=False)
    degradation.reset()


def test_u120_deploy_then_rollback_dry_run_in_a_temp_target_names_the_sha_and_the_time(tmp_path):
    """No live server: a temporary target. The release names itself with build_info, the rollback returns the previous one, both are timed."""
    src = tmp_path / 'src'
    (src / 'echo_sync').mkdir(parents=True)
    (src / 'echo_sync' / '__init__.py').write_text('x = 1\n', encoding='utf-8')
    target = tmp_path / 'srv'
    (target / 'profile' / 'materials').mkdir(parents=True)
    (target / 'profile' / 'materials' / 'qa.json').write_text('[]', encoding='utf-8')
    first = dp.deploy(src, target, sha='aaaaaaaaaaaa')
    (src / 'echo_sync' / '__init__.py').write_text('x = 2\n', encoding='utf-8')
    second = dp.deploy(src, target, sha='bbbbbbbbbbbb')
    assert build_info.build_id(target / 'releases' / second['release'] / 'echo_sync') == 'bbbbbbbbbbbb'
    began = time.perf_counter()
    back = dp.rollback(target)
    assert back['sha'] == 'aaaaaaaaaaaa' and back['release'] == first['release']
    assert build_info.build_id(target / 'releases' / back['release'] / 'echo_sync') == 'aaaaaaaaaaaa'
    assert back['duration_s'] >= 0 and time.perf_counter() - began < 30, 'the rollback time is named and bounded'
    assert not dp.verify(target, back['release'])


# --- E59.1 / harvest11 #5: the socket library is a dependency, and a host call with text_transport ws takes the socket
def test_websockets_is_pinned_in_the_plugin_dependencies():
    lines = (ROOT / 'echo_sync' / 'plugin.yaml').read_text(encoding='utf-8').splitlines()
    assert '  - websockets==15.0.1' in lines
    assert all(re.fullmatch(r'  - [\w.\-]+==[\w.\-]+', line) for line in lines[lines.index('python_dependencies:') + 1:] if line.strip())


def test_the_host_takes_the_websocket_transport_when_the_profile_asks_and_the_library_is_there(tmp_path, monkeypatch):
    import importlib.util
    assert importlib.util.find_spec('websockets.sync.client') is not None, 'the library plugin.yaml pins must be importable'
    made = []
    real = ws_transport.ws_stream

    def refused(url, headers):
        raise ConnectionRefusedError('no network in a test')

    def spy(credentials, **kwargs):
        stream = real(credentials, connect=refused, **kwargs)
        made.append(stream)
        return stream
    monkeypatch.setattr(ws_transport, 'ws_stream', spy)

    async def body(host):
        host.api._codex_credentials = lambda: {'access_token': 'x', 'account_id': 'y'}
        profile(host, fast_text='on', text_transport='ws')
        await host.handshake()
        assert made and isinstance(made[0], ws_transport.WsTransport), 'text_transport ws did not reach the socket transport'
        for stream in made:
            stream.close()
    run_host(tmp_path, monkeypatch, body, handshake=False)
