"""w9-gate (N181-N184, N186): build id, xfail/skip inventory, test-wrapper exit code, heavy-slot lock, registry integrity. Real code, no mocks of the checked logic."""
import json
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_n186_loaded_package_names_its_own_build(tmp_path):
    import echo_sync
    assert re.fullmatch(r'[0-9a-f]{7,40}|unknown|BUILD:[\w.-]+', echo_sync.build_id())


def test_n186_build_file_wins_over_git(tmp_path):
    from echo_sync import _build_id_at
    (tmp_path / 'BUILD').write_text('abc1234def\n')
    assert _build_id_at(tmp_path) == 'abc1234def'
    assert _build_id_at(tmp_path / 'nowhere') == 'unknown'


def test_n181_inventory_counts_marks_with_reasons(tmp_path):
    from tools.gate.inventory import inventory
    (tmp_path / 'test_a.py').write_text(textwrap.dedent('''
        import pytest
        @pytest.mark.skip(reason="no sapi")
        def test_1(): pass
        @pytest.mark.skipif(True, reason="linux")
        def test_2(): pass
        @pytest.mark.xfail(strict=True, reason="T03: nothing")
        def test_3(): pass
        @pytest.mark.xfail
        def test_4(): pass
        def test_5():
            pytest.skip("late skip")
        @pytest.mark.skip
        class TestX:
            def test_a(self): pass
            def test_b(self): pass
        def test_ok(): pass
    '''))
    inv = inventory(tmp_path)
    assert (inv['skip'], inv['xfail']) == (5, 2)
    by = {r['test']: r for r in inv['rows']}
    assert by['test_3']['reason'] == 'T03: nothing' and by['test_3']['strict'] is True
    assert by['test_4']['reason'] == '' and inv['no_reason'] == 2   # test_4 and the class skip
    assert by['TestX']['count'] == 2 and by['test_5']['kind'] == 'skip'


def _gate(*args, cwd=ROOT):
    return subprocess.run([sys.executable, str(ROOT / 'tools/gate/run_gate.py'), *args], capture_output=True, text=True, cwd=cwd, timeout=120)


def test_n182_wrapper_returns_nonzero_on_red_and_zero_on_green(tmp_path):
    (tmp_path / 'test_g.py').write_text('def test_g(): pass\n')
    (tmp_path / 'test_r.py').write_text('def test_r(): assert 0\n')
    lock = ['--lock', str(tmp_path / 'slot.lock')]
    green = _gate(*lock, '--', str(tmp_path / 'test_g.py'))
    red = _gate(*lock, '--', str(tmp_path / 'test_r.py'))
    assert green.returncode == 0, green.stdout + green.stderr
    assert red.returncode != 0 and '"failed": 1' in red.stdout.replace('\n', ' '), red.stdout
    none = _gate(*lock, '--', str(tmp_path / 'test_missing.py'))
    assert none.returncode != 0                                   # nothing collected is not green


def test_n182_a_pipe_does_not_hide_the_code(tmp_path):
    (tmp_path / 'test_r.py').write_text('def test_r(): assert 0\n')
    r = subprocess.run(f'{sys.executable} {ROOT}/tools/gate/run_gate.py --lock {tmp_path}/l -- {tmp_path}/test_r.py | tail -1; exit "${{PIPESTATUS[0]}}"', shell=True, executable='/bin/bash', capture_output=True, text=True)
    assert r.returncode != 0


def test_n183_second_heavy_run_waits_or_refuses(tmp_path):
    from tools.gate.slot import HeavySlot, SlotBusy
    lock = tmp_path / 'slot.lock'
    with HeavySlot(lock, owner='first'):
        with pytest.raises(SlotBusy) as e:
            HeavySlot(lock, owner='second', wait=0.2).acquire()
        assert 'first' in str(e.value)
    with HeavySlot(lock, owner='third'):                           # released: free again
        pass


def test_n183_dead_owner_does_not_hold_the_slot(tmp_path):
    from tools.gate.slot import HeavySlot
    lock = tmp_path / 'slot.lock'
    lock.write_text(json.dumps({'pid': 2 ** 22 + 12345, 'owner': 'ghost', 'at': time.time()}))
    with HeavySlot(lock, owner='live', wait=0.1):
        pass


def test_n183_wrapper_refuses_when_slot_is_taken(tmp_path):
    from tools.gate.slot import HeavySlot
    (tmp_path / 'test_g.py').write_text('def test_g(): pass\n')
    lock = tmp_path / 'slot.lock'
    with HeavySlot(lock, owner='holder'):
        r = _gate('--lock', str(lock), '--wait', '0.2', '--', str(tmp_path / 'test_g.py'))
    assert r.returncode == 75 and 'holder' in r.stdout + r.stderr


def test_n184_registry_catches_broken_ids_links_and_stale_dates(tmp_path):
    from tools.gate.registry import check_registry
    (tmp_path / 'exists.md').write_text('x')
    reg = tmp_path / 'REG.md'
    reg.write_text(textwrap.dedent('''
        | E01 | first | needs E02 and E99 | [ok](exists.md) |
        | E02 | second | dup below |
        | E02 | second again | |
        | W01 | w | see [gone](missing.md) and `cloud_context/nope.py` |
        Дальше: E01. Снимок 04.11 10:00.
        **Добавлено 05.11 22:30.**
    '''))
    probs = check_registry(reg, root=tmp_path)
    kinds = {(p['kind'], p['what']) for p in probs}
    assert ('duplicate_id', 'E02') in kinds
    assert ('unknown_id', 'E99') in kinds
    assert ('broken_link', 'missing.md') in kinds
    assert ('missing_path', 'cloud_context/nope.py') in kinds
    assert not any(p['what'] in ('E01', 'exists.md') for p in probs)
    assert any(p['kind'] == 'stale_date' for p in probs)           # 04.11 snapshot behind 05.11 22:30


def test_n184_real_registry_runs_and_reports():
    from tools.gate.registry import check_registry
    probs = check_registry(ROOT / 'cloud_context/BACKLOG_ECHO.md', root=ROOT)
    assert isinstance(probs, list) and all({'kind', 'what', 'line'} <= p.keys() for p in probs)
