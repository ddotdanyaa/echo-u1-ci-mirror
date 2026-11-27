"""Executor pool, layer A (coordinator 20.11): the state of the factory changes in short fenced transactions, so that
several passes can work on one checkpoint. ``txn`` locks the checkpoint, reads the plan and the state fresh, saves on a
normal exit and writes nothing when the block raises; a lock whose holder is dead is cleared at once; a lease that is
not the caller's any more raises StaleLease (a subclass of InvalidPlan) in every transition; ``begin`` marks that a pass
started its work, ``unclaim`` is the exact inverse of a claim for a pass that died before that."""
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools import agent_factory as F

ROOT = Path(__file__).resolve().parents[1]
DIGEST = '0' * 64


def api(name):
    assert hasattr(F, name), 'tools.agent_factory has no %s' % name
    return getattr(F, name)


def row(tid='T1', **extra):
    base = {'id': tid, 'title': 'Synthetic repair', 'depends_on': [], 'touch_files': ['echo_sync/%s.py' % tid.lower()],
            'read_files': [], 'tests': ['tests/test_%s.py' % tid.lower()], 'privacy_safe': True, 'estimated_tokens': 200}
    base.update(extra)
    return base


@pytest.fixture
def files(tmp_path):
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps([row('T1'), row('T2000')]), encoding='utf-8')
    return plan, tmp_path / 'state.json'


def test_txn_gives_the_fresh_plan_and_state_and_saves_on_exit(files):
    plan, state_path = files
    with api('txn')(state_path, plan) as (tasks, state):
        assert set(tasks) == {'T1', 'T2000'}
        state['max_model_calls'] = 50
        F.charge_call(state, 'T1')
    saved = json.loads(state_path.read_text(encoding='utf-8'))
    assert saved['model_calls'] == 1 and saved['max_model_calls'] == 50
    assert not state_path.with_suffix('.json.lockdir').exists()


def test_a_txn_that_raises_writes_nothing(files):
    plan, state_path = files
    txn = api('txn')
    with txn(state_path, plan) as (tasks, state):
        F.charge_call(state, 'T1')
    before = state_path.read_bytes()
    with pytest.raises(RuntimeError):
        with txn(state_path, plan) as (tasks, state):
            F.charge_call(state, 'T1')
            raise RuntimeError('boom')
    assert state_path.read_bytes() == before
    assert not state_path.with_suffix('.json.lockdir').exists()


def test_a_task_added_to_the_plan_meanwhile_joins_the_state_inside_the_txn(files):
    plan, state_path = files
    txn = api('txn')
    with txn(state_path, plan):
        pass
    plan.write_text(json.dumps([row('T1'), row('T2000'), row('T3')]), encoding='utf-8')
    with txn(state_path, plan) as (tasks, state):
        assert 'T3' in tasks and state['tasks']['T3']['status'] == 'READY'


WORKER = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools import agent_factory as F
plan, state = Path(sys.argv[2]), Path(sys.argv[3])
for _ in range(int(sys.argv[4])):
    with F.txn(state, plan) as (tasks, st):
        F.charge_call(st, 'T1')
'''


def test_two_processes_lose_no_update(files):
    plan, state_path = files
    txn = api('txn')
    with txn(state_path, plan) as (tasks, state):
        state['max_model_calls'] = 1000
    env = dict(os.environ, PYTHONUTF8='1')
    procs = [subprocess.Popen([sys.executable, '-B', '-c', WORKER, str(ROOT), str(plan), str(state_path), '25'], env=env)
             for _ in range(2)]
    assert [p.wait(timeout=60) for p in procs] == [0, 0]
    assert json.loads(state_path.read_text(encoding='utf-8'))['model_calls'] == 50


def test_a_dead_holders_lock_is_cleared_at_once_and_a_live_one_is_waited_for(files):
    plan, state_path = files
    txn, busy = api('txn'), api('LockBusy')
    lock = state_path.with_suffix('.json.lockdir')
    lock.mkdir()
    (lock / F.LOCK_OWNER).write_text('999999', encoding='ascii')       # no such process
    started = time.monotonic()
    with txn(state_path, plan, timeout_s=10):
        pass
    assert time.monotonic() - started < 3 and not lock.exists()
    lock.mkdir()
    (lock / F.LOCK_OWNER).write_text(str(os.getpid()), encoding='ascii')   # a live holder, a fresh lock
    with pytest.raises(busy):
        with txn(state_path, plan, timeout_s=0.3):
            pass
    assert lock.exists()                                                 # never stolen from a live holder
    assert issubclass(busy, OSError)


def test_a_lease_that_is_not_the_callers_raises_stale_lease_everywhere():
    stale = api('StaleLease')
    assert issubclass(stale, F.InvalidPlan)
    tasks = F.read_plan([row('T1')])
    state = F.initial_state(tasks)
    token = F.acquire(tasks, state, 'T1', charge=False)
    api('fence')(state, 'T1', token)                                     # the holder passes
    wrong = 'f' * 32
    with pytest.raises(stale):
        api('fence')(state, 'T1', wrong)
    with pytest.raises(stale):
        F.settle(state, 'T1', wrong, tests_ok=True, evidence=DIGEST)
    with pytest.raises(stale):
        F.defer(state, 'T1', wrong, 'transient', 60)
    with pytest.raises(stale):
        F.quarantine(state, 'T1', wrong, reason='no_diff')
    assert state['tasks']['T1']['status'] == 'RUNNING' and state['tasks']['T1']['lease'] == token
    F.release_expired(state, time.time() + F.LEASE_LIFETIME_S + 1)       # the lease expired and was released
    with pytest.raises(stale):
        F.settle(state, 'T1', token, tests_ok=True, evidence=DIGEST)
    assert state['tasks']['T1']['status'] == 'READY'


def test_unclaim_is_the_inverse_of_a_claim_and_began_marks_the_start_of_the_work():
    stale = api('StaleLease')
    begin, unclaim = api('begin'), api('unclaim')
    tasks = F.read_plan([row('T1')])
    state = F.initial_state(tasks)
    before = copy.deepcopy(state['tasks']['T1'])
    token = F.acquire(tasks, state, 'T1', charge=False)
    with pytest.raises(stale):
        unclaim(state, 'T1', 'f' * 32)
    unclaim(state, 'T1', token)
    assert state['tasks']['T1'] == before                                # exactly as before the claim
    token = F.acquire(tasks, state, 'T1', charge=False)
    begin(state, 'T1', token, 1234)
    assert state['tasks']['T1']['began'] == {'pid': 1234, 'booked': 0}
    F.validate_state(tasks, state)                                       # a RUNNING row may carry it
    with pytest.raises(F.InvalidPlan):
        unclaim(state, 'T1', token)                                      # after the start the lease stays until it ends
    F.settle(state, 'T1', token, tests_ok=False, evidence=DIGEST)
    assert 'began' not in state['tasks']['T1']
    state['tasks']['T1']['began'] = {'pid': 1, 'booked': 0}
    with pytest.raises(F.InvalidPlan):
        F.validate_state(tasks, state)                                   # only a RUNNING row carries it


def test_every_end_of_a_run_drops_began():
    begin = api('begin')
    for end in ('defer', 'quarantine', 'expire', 'park'):
        tasks = F.read_plan([row('T1')])
        state = F.initial_state(tasks)
        token = F.acquire(tasks, state, 'T1', charge=False)
        begin(state, 'T1', token, 7)
        if end == 'defer':
            F.defer(state, 'T1', token, 'transient', 60)
        elif end == 'quarantine':
            F.quarantine(state, 'T1', token, reason='no_diff')
        elif end == 'expire':
            F.release_expired(state, time.time() + F.LEASE_LIFETIME_S + 1)
        else:
            F.park(state, 'T1', 'runner_no_result', 'the runner gave no result')
        assert 'began' not in state['tasks']['T1'], end
        F.validate_state(tasks, state)


def test_claim_takes_a_ready_task_in_a_txn_and_two_claims_take_two_tasks(files):
    plan, state_path = files
    claim = api('claim')
    first, token = claim(state_path, plan)
    second, other = claim(state_path, plan)
    assert {first, second} == {'T1', 'T2000'} and token != other
    saved = json.loads(state_path.read_text(encoding='utf-8'))
    assert saved['tasks'][first]['status'] == 'RUNNING' and saved['tasks'][first]['lease'] == token
    assert saved['model_calls'] == 0                                     # the call is charged when it is made
    assert claim(state_path, plan) is None                               # nothing left to claim


# ---- layer C needs: what may run together, the approved candidate, the pool's view of next_action ---------------------

def _tasks(*rows):
    return F.read_plan(list(rows))


def test_ready_never_pairs_a_shared_file_or_test_and_a_review_holds_its_files():
    a = row('A', touch_files=['echo_sync/a.py'], tests=['tests/test_shared.py'])
    b = row('B', touch_files=['echo_sync/b.py'], tests=['tests/test_shared.py'])       # shares a test with A
    c = row('C', touch_files=['echo_sync/c.py'], tests=['tests/test_c.py'], read_files=['echo_sync/a.py'])  # reads A's file
    d = row('D', touch_files=['echo_sync/d.py'], tests=['tests/test_d.py'])
    tasks = _tasks(a, b, c, d)
    state = F.initial_state(tasks)
    # W-optim 1 (replaces the file/test/read booking): only a REVIEW function, a new test file and a row hold a start
    assert F.ready(tasks, state) == ['A', 'B', 'C', 'D']
    token = F.acquire(tasks, state, 'A', now=1, charge=False)
    assert F.ready(tasks, state) == ['B', 'C', 'D']
    F.settle(state, 'A', token, tests_ok=True, evidence=DIGEST)           # REVIEW: holds functions of a contract only
    assert F.ready(tasks, state) == ['B', 'C', 'D']
    F.mark_promoted(state, 'A', 'a' * 40)
    assert F.ready(tasks, state) == ['B', 'C', 'D']


def test_settle_keeps_the_candidate_and_requeue_can_bring_it_back_as_a_pending_review():
    tasks = _tasks(row('A'))
    state = F.initial_state(tasks)
    token = F.acquire(tasks, state, 'A', now=1, charge=False)
    state['tasks']['A']['pending_review'] = {'workdir': 'w', 'baseline_digest': 'd', 'coder_model': 'm'}
    F.settle(state, 'A', token, tests_ok=True, evidence=DIGEST)
    state['tasks']['A'].pop('pending_review')                                 # the runner drops it after the settle
    assert state['tasks']['A']['candidate'] == {'workdir': 'w', 'baseline_digest': 'd', 'coder_model': 'm'}
    kept = copy.deepcopy(state)
    F.requeue(state, 'A', 'moved')                                          # an ordinary requeue forgets it
    assert 'candidate' not in state['tasks']['A'] and 'pending_review' not in state['tasks']['A']
    F.requeue(kept, 'A', 'moved', keep_candidate=True)
    assert kept['tasks']['A']['status'] == 'READY' and kept['tasks']['A']['pending_review']['workdir'] == 'w'
    assert 'candidate' not in kept['tasks']['A']
    state2 = F.initial_state(tasks)
    token = F.acquire(tasks, state2, 'A', now=1, charge=False)
    state2['tasks']['A']['pending_review'] = {'workdir': 'w', 'baseline_digest': 'd', 'coder_model': 'm'}
    F.settle(state2, 'A', token, tests_ok=True, evidence=DIGEST)
    F.mark_promoted(state2, 'A', 'b' * 40)
    assert 'candidate' not in state2['tasks']['A']


def test_next_action_skips_the_tasks_of_live_workers_and_lists_all_compatible_ones():
    tasks = _tasks(row('A'), row('B'), row('C'))
    state = F.initial_state(tasks)
    act = F.next_action(state, 10, 0, False, tasks)
    assert act['action'] == 'RUN' and act['task_ids'] == ['A', 'B', 'C']
    act = F.next_action(state, 10, 0, False, tasks, skip=('A',))
    assert act['task_ids'] == ['B', 'C']
    token = F.acquire(tasks, state, 'A', now=1, charge=False)
    F.settle(state, 'A', token, tests_ok=True, evidence=DIGEST)
    assert F.next_action(state, 10, 0, False, tasks, skip=('A',))['action'] == 'RUN'      # A's REVIEW waits for its reap
    assert F.next_action(state, 10, 0, False, tasks)['action'] == 'PROMOTE'


def test_a_live_workers_lease_is_not_released_by_the_clock():
    tasks = _tasks(row('A'), row('B'))
    state = F.initial_state(tasks)
    F.acquire(tasks, state, 'A', now=1, lifetime=5, charge=False)
    F.acquire(tasks, state, 'B', now=1, lifetime=5, charge=False)
    assert F.release_expired(state, 100, keep=('A',)) == ['B']
    assert state['tasks']['A']['status'] == 'RUNNING' and state['tasks']['B']['status'] == 'READY'


def test_triage_may_run_while_a_worker_lives_only_when_there_is_room():
    tasks = _tasks(row('A'))
    state = F.initial_state(tasks)
    F.acquire(tasks, state, 'A', now=1, charge=False)
    assert F.next_action(state, 10, 0, True, tasks)['action'] == 'WAIT'                    # as today
    assert F.next_action(state, 10, 0, True, tasks, free=1)['action'] == 'TRIAGE'
