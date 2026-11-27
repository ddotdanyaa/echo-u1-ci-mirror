"""21.11 owner rule 3 (only safety invariants are hard, a tactical brake lifts itself on a jam). A jam is: nothing
runnable now and nothing RUNNING. Then the requeue ceiling (max_times) and the unclassified-failure skip give way, one
round per jam episode, recorded in the ledger as 'jam:<task>'; the loop does not sit in WAIT not_before_or_lease while
only delayed tasks are left; a FAILED test task that READY code tasks wait for is given back first. Never lifted: the
owner rules (only_opus / private), the quarantine."""
import json

from tests.test_factory_loop import Env, task_row
from tools import agent_factory as F
from tools import factory_requeue as R

NOEDIT = 'the model produced no change to the approved files (the answer had no SEARCH/REPLACE edit block)'


def _setup(tmp_path, monkeypatch, plan, rows, ledger=None):
    env = Env(tmp_path, monkeypatch, tasks=plan)
    env.state()                                   # creates state.json
    for tid, row in rows.items():
        env.set_row(tid, **row)
    if ledger is not None:
        (env.state_dir / 'requeue_ledger.json').write_text(json.dumps(ledger), encoding='utf-8')
    return env


def _failed(text=NOEDIT):
    return dict(status='FAILED', feedback=[{'source': 'gate', 'text': text}])


def _answers(env):
    box = env.state_dir / 'answers'
    return sorted(json.loads(p.read_text(encoding='utf-8'))['task_id'] for p in box.glob('*.json')) if box.is_dir() else []


def _ledger(env):
    return json.loads((env.state_dir / 'requeue_ledger.json').read_text(encoding='utf-8'))


def _jam_plan():
    # <id> failed test task over the ceiling; <id> (READY) waits for it; <id> READY but delayed: the loop sat in WAIT
    # <id> belongs to the failed row <id> (a ready task of another row behind a failed one is a row of its own now)
    return [task_row(1), task_row(2, depends_on=['T1'], backlog_id='B1'), task_row(3)]


def _jam_env(tmp_path, monkeypatch, plan=None, rows=None, ledger=None):
    env = _setup(tmp_path, monkeypatch, plan or _jam_plan(),
                 rows or {'T1': _failed(), 'T3': dict(not_before=10 ** 12)},
                 ledger if ledger is not None else {'T1': ['a', 'b', 'c']})
    return env


def test_a_delayed_task_does_not_prevent_slicing_a_failed_row(tmp_path, monkeypatch):
    env = _jam_env(tmp_path, monkeypatch)
    seen = []
    loop = env.loop(triage_fn=lambda **kw: {"tasks": [], "holds": [], "stale": [], "skipped": []},
                    extra={"slice_fn": lambda row, cause, *a, **kw: seen.append((row, cause))})
    loop.step()
    assert seen == [("B1", "first")]
    assert env.state()["tasks"]["T3"]["not_before"] == 10 ** 12


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.
