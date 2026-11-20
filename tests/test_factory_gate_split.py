"""fac-gate-split (live 20.11 05:00): three tasks stayed gate_unknown on every pass. Their 3-5 test files ran in ONE
pytest call killed at the 30 s limit, because one file hung (it waits on a speech process); the other files were red
in 4 s each. When a run of several files is killed at the limit, each file runs on its own (same limit, its own
slot); a file killed again is "timed out", the others keep their verdict. The base is red when a file that ran is
red; a candidate is accepted only when every file ran and passed."""
from tools import factory_gate as fg

A, B, C = 'tests/test_a.py', 'tests/test_b.py', 'tests/test_c.py'
TIMEOUT = fg.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout after 30s (process tree killed)')


def _red(*ids):
    return fg.GateResult(1, len(ids) + 1, 1, len(ids), 0, 0, True, 'failure ...', failed_ids=tuple(ids))


def _green(n=2):
    return fg.GateResult(0, n, n, 0, 0, 0, True, '')


def _fake(monkeypatch, by_file):
    calls = []

    def once(root, tests, timeout_s, workdir=None, wait_s=None):
        files = sorted({t.split('::', 1)[0] for t in tests})
        calls.append(files)
        return TIMEOUT if len(files) > 1 else by_file[files[0]]
    monkeypatch.setattr(fg, '_run_once', once)
    return calls


def test_a_hanging_file_no_longer_hides_the_red_of_the_others(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, {A: _red('a::t1', 'a::t2'), B: TIMEOUT, C: _red('c::t9')})
    result = fg.run_tests(tmp_path, [A, B, C], 30)
    assert calls == [[A, B, C], [A], [B], [C]]                  # one try together, then each file once
    assert result.failed == 3 and result.failed_ids == ('a::t1', 'a::t2', 'c::t9')
    assert result.timed_out == (B,) and B in result.missing and not result.junit_ok
    assert 'timeout' in result.diag and B in result.diag
    monkeypatch.setattr(fg, 'run_tests', lambda *a, **k: result)
    assert fg.red_before(tmp_path, [A, B, C], 30)[0] == 'red'


def test_one_file_killed_at_the_limit_stays_unknown(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, {A: TIMEOUT})
    monkeypatch.setattr(fg, '_run_once', lambda *a, **k: calls.append(1) or TIMEOUT)
    assert fg.red_before(tmp_path, [A], 30)[0] == 'unknown' and calls == [1]


def test_every_file_timed_out_is_unknown(monkeypatch, tmp_path):
    _fake(monkeypatch, {A: TIMEOUT, B: TIMEOUT})
    result = fg.run_tests(tmp_path, [A, B], 30)
    monkeypatch.setattr(fg, 'run_tests', lambda *a, **k: result)
    assert fg.red_before(tmp_path, [A, B], 30)[0] == 'unknown'


def test_a_slot_refusal_of_one_file_makes_the_run_environmental(monkeypatch, tmp_path):
    no_slot = fg.GateResult(-1, 0, 0, 0, 0, 0, False, 'pytest not started: no RAM', env_reason='pytest slot: no RAM')
    _fake(monkeypatch, {A: _red('a::t1'), B: no_slot})
    result = fg.run_tests(tmp_path, [A, B], 30)
    assert result.env_reason.startswith('pytest slot')
    monkeypatch.setattr(fg, 'run_tests', lambda *a, **k: result)
    assert fg.red_before(tmp_path, [A, B], 30)[0] == 'unknown'


def test_a_full_green_candidate_is_accepted_against_a_partly_timed_out_red_base(monkeypatch, tmp_path):
    _fake(monkeypatch, {A: _red('a::t1'), B: TIMEOUT})
    base = fg.run_tests(tmp_path, [A, B], 30)
    assert fg.accept(base, fg.GateResult(0, 5, 5, 0, 0, 0, True, ''), True) == (True, 'ok')
    _fake(monkeypatch, {A: _green(), B: TIMEOUT})
    partial = fg.run_tests(tmp_path, [A, B], 30)
    ok, reason = fg.accept(base, partial, True)
    assert not ok and reason.startswith('junit not ok')


def test_tests_of_one_file_are_never_split(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fg, '_run_once', lambda root, tests, *a, **k: calls.append(list(tests)) or TIMEOUT)
    fg.run_tests(tmp_path, [A + '::t1', A + '::t2'], 30)
    assert calls == [[A + '::t1', A + '::t2']]
