"""W14 item 1/2: the night call on the laptop. ``brain_short.py`` said ``from echo_sync import fast_text``; the deployed package is ``echo_controlled``,
so ``ModuleNotFoundError``, ``for_call`` raised, the host logged «fast text unavailable» and the whole call ran without the text channel: every answer was
silent. Item 1: every module of ``echo_sync`` imports under another package name with ``echo_sync`` itself unimportable, and ``for_call`` goes through with
every flag of the waves on; no module imports its own package absolutely. Item 2: an optional part (``brain_short``, ``ws``) that fails leaves the channel
up without it, and the log names the module."""
import ast
import importlib
import importlib.util
import logging
import shutil
import sys
from pathlib import Path

import pytest

import echo_sync
from echo_sync import codex_road as CR
from echo_sync import settings as S

ROOT = Path(echo_sync.__file__).parent
STUB = '"""Echo adapters only; never registers the legacy controller."""\n'
ON = {key: ('act' if key == 'local_ear' else 'on') for key, value in S.DEFAULTS.items() if value == 'off'}
ON['text_transport'] = 'ws'


class Controller:
    settings, ear_ended, source_segment_id, prepared_job, prepare_wide = {}, None, None, None, False
    refuse_deadline = decision_due = staticmethod(lambda *a: None)      # no question open, no bound

    def fast_exchanges(self):
        return []

    def fast_in_play(self):
        return None

    def fast_carry(self):
        return ''      # the memory of earlier calls (``for_call`` hands it to the channel)


def creds():
    return ('not-a-secret', 'acct-1')


@pytest.fixture
def deployed(tmp_path, monkeypatch):
    """The deploy's copy (every module but ``__init__``/``plugin`` into ``echo_controlled``, a stub ``__init__``), with ``echo_sync`` blocked."""
    target = tmp_path / 'echo_controlled'
    target.mkdir()
    for item in ROOT.glob('*.py'):
        if item.name not in {'__init__.py', 'plugin.py'}:
            shutil.copy2(item, target / item.name)
    (target / '__init__.py').write_text(STUB, encoding='utf-8')
    name = 'echo_controlled_w14'
    saved = {key: sys.modules.pop(key) for key in [k for k in sys.modules if k == 'echo_sync' or k.startswith('echo_sync.')]}
    monkeypatch.setitem(sys.modules, 'echo_sync', None)       # ``import echo_sync`` -> ModuleNotFoundError, as on the laptop
    spec = importlib.util.spec_from_file_location(name, target / '__init__.py', submodule_search_locations=[str(target)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    try:
        yield name
    finally:
        for key in [k for k in sys.modules if k == name or k.startswith(name + '.')]:
            sys.modules.pop(key)
        sys.modules.update(saved)


def test_every_module_imports_under_the_deployed_name(deployed):
    failed = {}
    for item in sorted(ROOT.glob('*.py')):
        if item.stem in {'__init__', 'plugin'}:
            continue
        try:
            importlib.import_module(f'{deployed}.{item.stem}')
        except ModuleNotFoundError as error:
            if error.name and (error.name == 'echo_sync' or error.name.startswith('echo_sync.')):
                failed[item.stem] = str(error)
        except Exception:       # noqa: BLE001, S112 - a missing optional third-party dependency is not this test's business
            continue
    assert not failed, failed


def test_for_call_with_every_flag_on_under_the_deployed_name(deployed):
    FT = importlib.import_module(f'{deployed}.fast_text')
    controller = Controller()
    channel = FT.for_call(ON, controller, credentials=creds, instructions=lambda *a: FT.BRAIN_POLICY)
    assert channel is not None and type(getattr(channel.stream, 'primary', channel.stream)).__module__ == f'{deployed}.ws_transport'
    assert FT.BRAIN_POLICY not in channel.instructions() and 'Ты суфлёр' in channel.instructions()      # brain_short really on
    assert controller.prepare_wide is True and controller.prepared_job == channel.prepared


def test_no_module_imports_its_own_package_absolutely():
    bad = []
    for item in sorted(ROOT.glob('*.py')):
        for node in ast.walk(ast.parse(item.read_text(encoding='utf-8'))):
            names = [node.module or ''] if isinstance(node, ast.ImportFrom) and not node.level else [a.name for a in node.names] if isinstance(node, ast.Import) else []
            bad += [f'{item.name}:{node.lineno}' for n in names if n == 'echo_sync' or n.startswith('echo_sync.')]
    assert not bad, bad


@pytest.mark.parametrize('part', ['brain_short', 'ws_transport'])
def test_a_broken_optional_part_leaves_the_channel_up_and_names_itself(part, monkeypatch, caplog):
    from echo_sync import fast_text as FT
    monkeypatch.setitem(sys.modules, f'echo_sync.{part}', None)        # its import raises, as the night's did
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        channel = FT.for_call(ON, Controller(), credentials=creds, instructions=lambda *a: FT.BRAIN_POLICY)
    assert channel is not None, 'the call was left without the text channel'
    if part == 'brain_short':
        assert channel.instructions() == FT.BRAIN_POLICY and type(getattr(channel.stream, 'primary', channel.stream)).__name__ == 'WsTransport'
    else:
        assert type(getattr(channel.stream, 'primary', channel.stream)) is CR.CodexTransport and 'Ты суфлёр' in channel.instructions()
    assert any(part in record.getMessage() for record in caplog.records), [r.getMessage() for r in caplog.records]
