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


# --- E97
def trace_records(home, seen):
    folder = Path(home) / 'logs' / 'echo_calls'
    out = []
    for path in sorted(folder.glob('*.jsonl')):
        if path.name in seen:
            continue
        seen.add(path.name)
        out += [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    return out


def test_e97_the_passport_of_a_call_holds_a_hash_of_the_profile_and_no_word_of_it(tmp_path, monkeypatch):
    seen, got = set(), []

    async def main():
        F.patch_clock(monkeypatch)
        for subject, style in (('Физика', ''), ('Химия', ''), ('Химия', ''), ('Химия', 'простыми словами')):
            async with F.HostRig(tmp_path, monkeypatch) as host:
                profile(host, subject=subject, **({'style': style} if style else {}))
                await host.handshake()
            records = [r for r in trace_records(host.home, seen) if r.get('ev') == 'profile']
            assert len(records) == 1, records
            got.append(records[0])
    F.run(main)
    hashes = [r['profile'] for r in got]
    assert hashes[1] == hashes[2] and len({hashes[0], hashes[1], hashes[3]}) == 3, 'one profile, one hash; another subject or style, another hash'
    assert [r['subject_chars'] for r in got] == [6, 5, 5, 5] and [r['style_chars'] for r in got] == [0, 0, 0, 16]
    assert all(r['material'] == 'none' and r['material_chars'] == 0 for r in got)
    assert all(('Физика' not in json.dumps(r, ensure_ascii=False) and 'простыми' not in json.dumps(r, ensure_ascii=False)) for r in got)
