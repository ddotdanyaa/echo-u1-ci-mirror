"""fac-base-cache (live 20.11 05:25-05:51): two tasks measured the same red base on every pass (about 70 s with a
hanging test file; a whole pass took 490 s). A red base measured on the same commit with the same tests and files
cannot change: it is kept on the task row and reused. A new commit, other file bytes, a unit_test task, a stale or a
damaged record measure again. What the base cut at the limit is handed to the candidate run (it starts file by file
and runs those tests alone: the joint run would only spend the limit again)."""
import dataclasses
import json
from types import SimpleNamespace

from test_factory_runtime import Rig, _kilo_engine, gr, next_pass, slot_failure  # noqa: <id>  (_kilo_engine: autouse)

SHA_A, SHA_B = 'a' * 40, 'b' * 40


def _released_then_resumed(rig, second_sha, between=None):
    """Pass 1: the base (red), then the candidate finds no pytest slot (released, kept). Pass 2 resumes it."""
    calls = []

    def run(root, tests, timeout_s):
        calls.append(root)
        return rig._default_run_tests(root, tests, timeout_s) if len(calls) != 2 else slot_failure()
    rig.run_tests_fn = run
    first = rig.once(base_sha=SHA_A)
    assert first['reason'] == 'transient' and 'base_reused' not in first['events']
    if between:
        between()
    next_pass(rig)
    return first, rig.once(base_sha=second_sha), calls


def test_the_red_base_of_the_same_commit_is_measured_once(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _, second, calls = _released_then_resumed(rig, SHA_A)
    assert 'base_reused' in second['events']
    assert len(calls) == 3                                   # base + candidate, then the candidate alone
    assert second['tests'] == dict(collected=1, passed=1, failed=0, skipped=0)


def test_a_new_commit_measures_the_base_again(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _, second, calls = _released_then_resumed(rig, SHA_B)
    assert 'base_reused' not in second['events'] and len(calls) == 4


def test_changed_file_bytes_measure_the_base_again(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _, second, calls = _released_then_resumed(
        rig, SHA_A, between=lambda: (rig.root / 'calc.py').write_text('def add(a,b): return a-b  # moved\n'))
    assert 'base_reused' not in second['events'] and len(calls) == 4


def test_a_unit_test_task_keeps_no_base(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test')
    rig.once(base_sha=SHA_A)
    assert 'base_red' not in rig.state()['tasks']['T1']


def test_without_a_base_commit_nothing_is_kept(tmp_path, monkeypatch):
    monkeypatch.delenv('FACTORY_BASE_SHA', raising=False)
    rig = Rig(tmp_path, monkeypatch)
    rig.once()
    assert 'base_red' not in rig.state()['tasks']['T1']


def test_the_kept_base_survives_the_state_file_and_refuses_stale_foreign_or_damaged_records(monkeypatch):
    from tools import agent_factory_runner as w
    monkeypatch.setattr(w, '_now', lambda: 1000.0)
    red = gr(False, missing=('tests/b.py',), timed_out=('tests/b.py',))
    good = json.loads(json.dumps({'key': 'k', 'at': 990.0, 'result': dataclasses.asdict(red)}))
    assert w._held_base({'base_red': good}, 'k') == red
    assert w._held_base({'base_red': good}, 'other') is None and w._held_base({'base_red': good}, None) is None
    assert w._held_base({'base_red': dict(good, at=1000.0 - w.BASE_CACHE_S)}, 'k') is None    # stale
    assert w._held_base({'base_red': dict(good, at=2000.0)}, 'k') is None                     # the clock stepped back
    for broken in (dict(good, result={'bogus': 1}), dict(good, result='x'), dict(good, at='x'), {'key': 'k'}, 'x'):
        assert w._held_base({'base_red': broken}, 'k') is None


def test_the_key_names_the_commit_the_kind_the_tests_and_the_file_bytes():
    from tools import agent_factory_runner as w
    task = SimpleNamespace(kind='code', tests=('tests/a.py', 'tests/b.py'))
    files = {'calc.py': b'x', w.POLICY_FILE: b'p'}
    key = w._base_key(SHA_A, task, files)
    same = SimpleNamespace(kind='code', tests=('tests/b.py', 'tests/a.py'))
    assert key == w._base_key(SHA_A, same, dict(files, **{w.POLICY_FILE: b'q'}))   # test order, worker policy: no
    assert key != w._base_key(SHA_B, task, files)
    assert key != w._base_key(SHA_A, task, dict(files, **{'calc.py': b'y'}))
    assert key != w._base_key(SHA_A, SimpleNamespace(kind='code', tests=('tests/a.py',)), files)
    assert key != w._base_key(SHA_A, SimpleNamespace(kind='spec', tests=task.tests), files)
    assert w._base_key(None, task, files) is None and w._base_key('', task, files) is None


def test_a_base_with_a_file_killed_at_the_limit_runs_the_candidate_file_by_file(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, tests=['tests/test_calc.py', 'tests/test_other.py'])
    (rig.root / 'tests/test_other.py').write_text('def test_other(): assert True\n')
    seen = []

    def run_tests(root, tests, timeout_s, workdir=None, wait_s=None, hung=(), trace=(), touched=None):
        seen.append(tuple(hung))
        if len(seen) == 1:      # the base: test_calc is red, test_other was killed at the limit
            return gr(False, junit_ok=False, missing=('tests/test_other.py',), timed_out=('tests/test_other.py',))
        return gr(True, collected=2)
    monkeypatch.setattr(rig.w.gate, 'run_tests', run_tests)
    rig.once(base_sha=SHA_A)
    assert seen[:2] == [(), ('tests/test_other.py',)]
    assert rig.state()['tasks']['T1']['base_red']['result']['timed_out'] == ['tests/test_other.py']
