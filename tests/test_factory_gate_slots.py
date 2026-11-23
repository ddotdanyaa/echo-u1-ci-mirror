"""Laptop rule for the factory's own pytest: 2 slots machine-wide, free RAM > 2 GB (round 6 add-on)."""
import os
import time

import pytest

from tools import factory_gate as G

GB = 2 ** 30
REAL_SLOTS = True      # conftest leaves pytest_slot alone for this module


@pytest.fixture
def slots(tmp_path, monkeypatch):
    a, b = str(tmp_path / 's1'), str(tmp_path / 's2')
    monkeypatch.setattr(G, 'SLOT_DIRS', [a, b])
    monkeypatch.setattr(G, '_free_ram', lambda: 8 * GB)
    return a, b


def test_slot_is_taken_and_released(slots):
    with G.pytest_slot() as why:
        assert why == '' and os.path.isdir(slots[0]) and not os.path.exists(slots[1])
    assert not os.path.exists(slots[0])


def test_slot_released_when_the_body_raises(slots):
    with pytest.raises(RuntimeError):
        with G.pytest_slot():
            raise RuntimeError('x')
    assert not os.path.exists(slots[0])


def test_second_slot_is_used_when_first_is_busy(slots):
    os.mkdir(slots[0])
    with G.pytest_slot() as why:
        assert why == '' and os.path.isdir(slots[1])
    assert not os.path.exists(slots[1]) and os.path.isdir(slots[0])


def test_both_busy_gives_reason_at_the_deadline_without_real_waiting(slots, monkeypatch):
    for d in slots:
        os.mkdir(d)
    now = [0.0]
    monkeypatch.setattr(G, '_clock', lambda: now[0])
    monkeypatch.setattr(G, '_sleep', lambda s: now.__setitem__(0, now[0] + s))
    with G.pytest_slot(wait_s=30) as why:
        assert 'slot' in why
    assert now[0] >= 30 and all(os.path.isdir(d) for d in slots)   # busy dirs untouched


def test_low_ram_waits_then_gives_reason(slots, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(G, '_clock', lambda: now[0])
    monkeypatch.setattr(G, '_sleep', lambda s: now.__setitem__(0, now[0] + s))
    monkeypatch.setattr(G, '_free_ram', lambda: 1 * GB)
    with G.pytest_slot(wait_s=20) as why:
        assert 'RAM' in why
    assert now[0] >= 20 and not os.path.exists(slots[0])


def test_ram_recovers_while_waiting(slots, monkeypatch):
    now = [0.0]
    ram = iter([1 * GB, 1 * GB, 4 * GB])
    monkeypatch.setattr(G, '_clock', lambda: now[0])
    monkeypatch.setattr(G, '_sleep', lambda s: now.__setitem__(0, now[0] + s))
    monkeypatch.setattr(G, '_free_ram', lambda: next(ram))
    with G.pytest_slot(wait_s=60) as why:
        assert why == ''


def test_stale_dir_is_removed_and_reused(slots):
    os.mkdir(slots[0])
    old = time.time() - 500
    os.utime(slots[0], (old, old))
    with G.pytest_slot() as why:
        assert why == '' and os.path.isdir(slots[0])
    assert not os.path.exists(slots[0])


def test_fresh_dir_is_not_removed(slots):
    os.mkdir(slots[0])
    os.mkdir(slots[1])
    now = [0.0]
    import tools.factory_gate as g
    g._clock = lambda: now[0]
    g._sleep = lambda s: now.__setitem__(0, now[0] + s)
    try:
        with G.pytest_slot(wait_s=5) as why:
            assert why
    finally:
        g._clock, g._sleep = time.monotonic, time.sleep
    assert os.path.isdir(slots[0]) and os.path.isdir(slots[1])


def test_run_tests_without_a_slot_is_environment_not_a_pass(slots, tmp_path, monkeypatch):
    for d in slots:
        os.mkdir(d)
    monkeypatch.setattr(G, 'SLOT_QUEUE_S', 0)
    (tmp_path / 't.py').write_text('def test_a():\n    assert True\n', encoding='utf-8')
    r = G.run_tests(tmp_path, ['t.py'], 5)
    assert not r.junit_ok and r.env_reason and 'slot' in r.env_reason


def test_profile_without_a_slot_is_unknown(slots, tmp_path, monkeypatch):
    for d in slots:
        os.mkdir(d)
    monkeypatch.setattr(G, 'SLOT_QUEUE_S', 0)
    (tmp_path / 't.py').write_text('def test_a():\n    assert True\n', encoding='utf-8')
    assert G.profile_tests(tmp_path, ['t.py'], 5).verdict == 'unknown'


def test_slot_names_and_dirs_have_the_two_shared_names():
    # the comparison with verify_run.py's LOCKS (and the process-TEMP independence) is in test_factory_round7.py
    assert G.SLOT_NAMES == ('night_pytest.lock', 'night_pytest.lock2')
    assert [os.path.basename(d) for d in G.SLOT_DIRS] == list(G.SLOT_NAMES)


def test_empty_slot_dirs_is_refused_not_silently_ungated(monkeypatch):
    monkeypatch.setattr(G, 'SLOT_DIRS', [])
    with pytest.raises(RuntimeError):
        with G.pytest_slot():
            pass


def test_holder_refreshes_the_slot_mtime_while_pytest_runs(slots, monkeypatch):
    monkeypatch.setattr(G, 'SLOT_TOUCH_S', 0.05)
    with G.pytest_slot() as why:
        assert why == ''
        old = time.time() - 500
        os.utime(slots[0], (old, old))                 # looks stale ...
        deadline = time.time() + 5
        while time.time() < deadline and time.time() - os.stat(slots[0]).st_mtime > 100:
            time.sleep(0.05)
        assert time.time() - os.stat(slots[0]).st_mtime < 100   # ... until the heartbeat refreshes it
    assert not os.path.exists(slots[0])


def test_gate_reads_no_environment_name_for_slot_control():
    import ast
    import importlib.util
    spec = importlib.util.find_spec('tools.factory_gate')
    tree = ast.parse(open(spec.origin, encoding='utf-8').read())
    slot_fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                and n.name in ('pytest_slot', '_take_slot', '_free_ram')}
    assert set(slot_fns) == {'pytest_slot', '_take_slot', '_free_ram'}
    for fn in slot_fns.values():
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute) and node.attr in ('environ', 'getenv'):
                raise AssertionError('slot control reads the environment in ' + fn.name)
    text = open(spec.origin, encoding='utf-8').read()
    assert 'FACTORY_PYTEST_SLOT_DIRS' not in text and "environ.get('PYTEST_CURRENT_TEST')" not in text


def _res(**kw):
    base = dict(rc=0, collected=1, passed=1, failed=0, errors=0, skipped=0, junit_ok=True)
    base.update(kw)
    return G.GateResult(**base)


def test_accept_env_result_has_an_env_prefix_and_a_real_failure_does_not():
    base = _res(rc=1, passed=0, failed=1)
    env = _res(rc=-1, collected=0, passed=0, junit_ok=False, env_reason='pytest slot: no free pytest slot')
    ok, reason = G.accept(base, env, True)
    assert not ok and reason.startswith('env:') and 'slot' in reason
    ok, reason = G.accept(env, _res(), True)          # the base side too
    assert not ok and reason.startswith('env:')
    ok, reason = G.accept(base, _res(rc=1, passed=0, failed=1), True)
    assert not ok and not reason.startswith('env:')
    ok, reason = G.accept(base, _res(rc=1, passed=0, errors=1, junit_ok=False), True)
    assert not ok and not reason.startswith('env:')


def test_accept_unit_test_env_prefix():
    env = _res(rc=-1, collected=0, passed=0, junit_ok=False, env_reason='pytest slot: free RAM 1.0 GB <= 2 GB')
    ok, reason = G.accept_unit_test(env)
    assert not ok and reason.startswith('env:')
    ok, reason = G.accept_unit_test(_res(rc=1, passed=0, failed=1))
    assert ok
    ok, reason = G.accept_unit_test(_res())
    assert not ok and not reason.startswith('env:')
    ok, reason = G.accept_unit_test(_res(rc=2, collected=0, passed=0, errors=1, junit_ok=False, diag='SyntaxError'))
    assert not ok and not reason.startswith('env:')


def test_wait_s_is_passed_through_and_default_is_the_queue_time():
    assert G.SLOT_QUEUE_S == 900                      # the one queue time of a slot and of a cloud place (replaces SLOT_WAIT_S = 120)
    import inspect
    assert 'wait_s' in inspect.signature(G.run_tests).parameters
    assert 'wait_s' in inspect.signature(G.profile_tests).parameters


def test_run_tests_wait_s_bounds_the_wait(slots, tmp_path, monkeypatch):
    for d in slots:
        os.mkdir(d)
    now = [0.0]
    monkeypatch.setattr(G, '_clock', lambda: now[0])
    monkeypatch.setattr(G, '_sleep', lambda s: now.__setitem__(0, now[0] + s))
    (tmp_path / 't.py').write_text('def test_a():' + chr(10) + '    assert True' + chr(10), encoding='utf-8')
    r = G.run_tests(tmp_path, ['t.py'], 5, wait_s=9)
    assert r.env_reason and 9 <= now[0] < 13
    p = G.profile_tests(tmp_path, ['t.py'], 5, wait_s=9)
    assert p.verdict == 'unknown' and p.diag.startswith(G.NOT_STARTED)
