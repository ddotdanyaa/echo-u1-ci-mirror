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
    return [task_row(1), task_row(2, depends_on=['T1']), task_row(3)]


def _jam_env(tmp_path, monkeypatch, plan=None, rows=None, ledger=None):
    env = _setup(tmp_path, monkeypatch, plan or _jam_plan(),
                 rows or {'T1': _failed(), 'T3': dict(not_before=10 ** 12)},
                 ledger if ledger is not None else {'T1': ['a', 'b', 'c']})
    return env


def test_next_action_waits_on_a_delayed_task_and_the_loop_gives_the_failed_task_back(tmp_path, monkeypatch):
    env = _jam_env(tmp_path, monkeypatch)
    loop = env.loop()
    tasks, state = loop.load()
    act = F.next_action(state, env.clock.now(), 0.0, False, tasks)
    assert (act['action'], act['reason']) == ('WAIT', 'not_before_or_lease')
    out = loop._step()
    assert out.action == 'REQUEUE', out
    assert _answers(env) == ['T1']
    ledger = _ledger(env)
    assert len(ledger['T1']) == 4 and len(ledger['jam:T1']) == 1


def test_without_a_jam_the_ceiling_stays(tmp_path, monkeypatch):
    # <id> is READY and runnable: no jam, so the task over max_times stays FAILED
    plan = _jam_plan() + [task_row(4)]
    env = _jam_env(tmp_path, monkeypatch, plan=plan)
    loop = env.loop()
    tasks, state = loop.load()
    assert loop._idle_requeue(tasks, state, env.clock.now()) is None
    assert _answers(env) == [] and 'jam:T1' not in _ledger(env)


def test_a_running_task_is_no_jam(tmp_path, monkeypatch):
    env = _jam_env(tmp_path, monkeypatch, rows={'T1': _failed(), 'T3': dict(status='RUNNING', lease='a' * 32, deadline=10 ** 12, attempts=1)})
    loop = env.loop()
    tasks, state = loop.load()
    assert loop._idle_requeue(tasks, state, env.clock.now()) is None
    assert _answers(env) == []


def test_private_and_only_opus_tasks_are_never_given_back_on_a_jam(tmp_path, monkeypatch):
    plan = [task_row(1, only_opus=True), task_row(2, id='B2', privacy_safe=False), task_row(3, depends_on=['T1'])]
    env = _setup(tmp_path, monkeypatch, plan, {'T1': _failed(), 'B2': _failed()},
                 {'T1': ['a', 'b', 'c'], 'B2': ['a', 'b', 'c']})
    loop = env.loop()
    tasks, state = loop.load()
    assert loop._idle_requeue(tasks, state, env.clock.now()) is None
    assert _answers(env) == []


def test_an_unclassified_failure_is_tried_once_more_on_a_jam_only(tmp_path, monkeypatch):
    env = _jam_env(tmp_path, monkeypatch, rows={'T1': _failed('something nobody classified'),
                                                 'T3': dict(not_before=10 ** 12)}, ledger={})
    loop = env.loop()
    tasks, state = loop.load()
    assert loop._idle_requeue(tasks, state, env.clock.now()) is not None
    assert _answers(env) == ['T1']
    # not a jam (<id> runnable): the unclassified skip stays
    state['tasks']['T3']['status'] = 'READY'
    assert R.pick(state, 'v', {}) == []


def test_one_jam_round_per_episode_until_something_got_done(tmp_path):
    state = {'tasks': {'A': _failed(), 'B': dict(status='READY'), 'C': dict(status='READY')}}
    ledger = {'A': ['a', 'b', 'c']}
    lifted = set()
    assert R.pick(state, 'v', ledger, jam=True, lifted=lifted) == [('A', 'no-edit-block')] and lifted == {'A'}
    assert R.pick(state, 'v', ledger, jam=False) == []
    ledger['jam:A'] = [R._progress(state)]               # the round was booked: no progress, no more budget
    assert R.pick(state, 'v', ledger, jam=True) == []
    state['tasks']['B']['status'] = 'DONE'               # progress: a new episode
    assert R.pick(state, 'v', ledger, jam=True) == [('A', 'no-edit-block')]
    ledger['jam:A'] = list(range(F.AUTO_UNBLOCK_MAX))    # the absolute cap
    state['tasks']['C']['status'] = 'DONE'
    assert R.pick(state, 'v', ledger, jam=True) == []


def test_a_failed_test_with_ready_code_tasks_goes_first(tmp_path):
    state = {'tasks': {'A': _failed(), 'T': _failed(), 'C': dict(status='READY')}}
    assert [t for t, _ in R.pick(state, 'v', {})] == ['A', 'T']
    assert [t for t, _ in R.pick(state, 'v', {}, blocking={'T'})] == ['T', 'A']
