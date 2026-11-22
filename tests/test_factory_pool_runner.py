"""Executor pool, layer B (coordinator 20.11): the runner no longer holds the checkpoint for a whole pass. A pass runs
the task it was given with its lease (``once(task_id=, lease=)``), keeps only read-only facts and changes the state in
short fenced commits on the FRESH state (agent_factory.Lease): the model calls and the gates run with the lock free,
the booking of a channel (view + choose + charge + reserve) is one commit, a stale lease writes nothing, and the gate's
slot budget counts waiting only. Fakes: the harness of test_factory_runtime (Rig)."""
import dataclasses
import json
import re
import tempfile
from pathlib import Path

import pytest

from tools import agent_factory as F
from tools import factory_channels as C
from tools import factory_gate as G
from test_factory_runtime import Rig, _kilo_engine, ev, finish, gr, verdict  # noqa: <id>  (autouse fixture)

REAL_SLOTS = True      # conftest leaves pytest_slot alone for this module (the gates here are fakes)
ROOT = Path(__file__).resolve().parents[1]
ONE = dict(id='T1', backlog_id='BL1', title='Fix sum', touch_files=['calc.py'], tests=['tests/test_calc.py'],
           privacy_safe=True)
TWO = dict(ONE, id='T2000', backlog_id='BL2')


def two_tasks(rig, second=TWO):
    rig.plan.write_text(json.dumps([ONE, second]), encoding='utf-8')


def lockdir(rig):
    return rig.state_path.with_suffix('.json.lockdir')


def disjoint_rig(tmp_path, monkeypatch, channel=None):
    """<id> on calc.py, <id> on calc2.py: both may run together. Fake model: writes the fixed file of its task."""
    rig = Rig(tmp_path, monkeypatch)
    two_tasks(rig, second=dict(TWO, touch_files=['calc2.py'], tests=['tests/test_calc2.py']))
    (rig.root / 'calc2.py').write_text('def add(a,b): return a-b\n')
    (rig.root / 'tests/test_calc2.py').write_text('from calc2 import add\ndef test_add(): assert add(2,3)==5\n')
    if channel is not None:
        rig.channels.write_text(json.dumps(dict(channels=[channel])), encoding='utf-8')
    rig.coder_calls = []

    def model(t, directory, name, timeout, **kwargs):
        if t.touch_files:
            rig.coder_calls.append(t.id)
            (directory / t.touch_files[0]).write_text('def add(a,b): return a+b\n')
            return 0, ev(finish()), b''
        return 0, verdict(True), b''

    def run(root, tests, timeout_s):
        name = 'calc2.py' if 'calc2' in tests[0] else 'calc.py'
        return gr('a+b' in (Path(root) / name).read_text(), diag='red')
    monkeypatch.setattr(rig.w, 'model_attempt', model)
    rig.run_tests_fn = run
    return rig


def test_runs_the_claimed_task_with_its_lease(tmp_path, monkeypatch):
    rig = disjoint_rig(tmp_path, monkeypatch)
    tid, token = F.claim(rig.state_path, rig.plan, 'T2000')
    assert tid == 'T2000'
    result = rig.once(task_id='T2000', lease=token)           # <id> comes first in the plan, the lease names <id>
    assert result['status'] == 'REVIEW' and result['task_id'] == 'T2000'
    rows = rig.state()['tasks']
    assert rows['T2000']['status'] == 'REVIEW' and rows['T2000'].get('lease') is None and 'began' not in rows['T2000']
    assert rows['T1']['status'] == 'READY' and rows['T1']['attempts'] == 0


def test_a_foreign_lease_ends_stale_and_writes_nothing(tmp_path, monkeypatch):
    rig = disjoint_rig(tmp_path, monkeypatch)
    tid, token = F.claim(rig.state_path, rig.plan, 'T2000')
    before = rig.state_path.read_bytes()
    result = rig.once(task_id='T2000', lease='f' * 32)         # the row is RUNNING under another token
    assert result['status'] == 'STALE_LEASE' and result['task_id'] == 'T2000'
    assert rig.state_path.read_bytes() == before and rig.coder_calls == []
    assert not lockdir(rig).exists()
    with F.txn(rig.state_path, rig.plan) as (tasks, state):    # the lease expired and was released: the old token is dead
        F.release_expired(state, state['tasks']['T2000']['deadline'] + 1)
    after = rig.state_path.read_bytes()
    result = rig.once(task_id='T2000', lease=token)
    assert result['status'] == 'STALE_LEASE' and rig.state_path.read_bytes() == after and rig.coder_calls == []


def test_without_a_lease_the_pass_claims_one_itself_and_task_id_picks_the_task(tmp_path, monkeypatch):
    rig = disjoint_rig(tmp_path, monkeypatch)
    result = rig.once(task_id='T2000')
    assert result['status'] == 'REVIEW' and result['task_id'] == 'T2000'
    assert rig.state()['tasks']['T1']['status'] == 'READY'


def test_a_stale_lease_inside_the_pass_stops_it_without_a_write(tmp_path, monkeypatch):
    """The lease is released while the model works: the pass answers STALE_LEASE and the runner does not die."""
    rig = Rig(tmp_path, monkeypatch)
    model = rig._model
    state_when_stolen = {}

    def steal(t, directory, name, timeout, **kwargs):
        with F.txn(rig.state_path, rig.plan, timeout_s=2) as (tasks, state):
            F.release_expired(state, state['tasks']['T1']['deadline'] + 1)
        state_when_stolen['bytes'] = rig.state_path.read_bytes()
        return model(t, directory, name, timeout, **kwargs)
    monkeypatch.setattr(rig.w, 'model_attempt', steal)
    result = rig.once()
    assert result['status'] == 'STALE_LEASE'
    assert not lockdir(rig).exists()
    row = rig.state()['tasks']['T1']
    assert row['status'] == 'READY' and row.get('lease') is None and row.get('pending_review') is None


def test_no_state_lock_during_calls_and_gates(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    lock = lockdir(rig)
    seen = []
    model, tests = rig._model, rig.run_tests_fn

    def m(*args, **kwargs):
        seen.append(('model', lock.exists()))
        return model(*args, **kwargs)

    def t(*args):
        seen.append(('gate', lock.exists()))
        return tests(*args)
    monkeypatch.setattr(rig.w, 'model_attempt', m)
    rig.run_tests_fn = t
    result = rig.once()
    assert result['status'] == 'REVIEW'
    assert {kind for kind, _ in seen} == {'model', 'gate'} and len(seen) >= 4     # red_before, coder, gate, reviewer
    assert not [kind for kind, held in seen if held], 'the state lock was held while a call or a gate ran'
    assert not lock.exists()


def test_keeps_rows_written_by_others(tmp_path, monkeypatch):
    rig = disjoint_rig(tmp_path, monkeypatch)
    other = dict(id='cx', group='gx', model='google/z', key_env='KEY', tpm=1000, rpd=10, verified=True)
    errors, done = [], []
    model = rig.w.model_attempt

    def meanwhile(t, directory, name, timeout, **kwargs):
        if not done:
            done.append(1)
            try:
                with F.txn(rig.state_path, rig.plan, timeout_s=2) as (tasks, state):
                    F.add_feedback(state, 'T2000', 'opus', 'a note of another writer')
                    F.charge_call(state, 'T2000')
                    C.reserve(state.setdefault('channel_quotas', {}), other, 100)
            except Exception as error:      # the old runner holds the lock: LockBusy
                errors.append(error)
        return model(t, directory, name, timeout, **kwargs)
    monkeypatch.setattr(rig.w, 'model_attempt', meanwhile)
    result = rig.once()
    assert not errors, errors
    state = rig.state()
    assert result['status'] == 'REVIEW' and state['tasks']['T1']['status'] == 'REVIEW'     # its own transition applied
    assert any('another writer' in str(i) for i in state['tasks']['T2000']['feedback'])
    assert 'gx' in state['channel_quotas'] and state['channel_quotas']['gx']['requests'] == 1
    assert state['model_calls'] == 4                  # coder + two critics of the pass, and the other writer's charge


def test_choose_reserve_atomic_across_workers(tmp_path, monkeypatch):
    """rpm 1: worker B books the only request between worker A's start and A's booking. A decides on the FRESH state
    and waits for the channel; a view taken at A's start would book a second request."""
    rig = disjoint_rig(tmp_path, monkeypatch, dict(id='c1', group='p', model='google/x', key_env='KEY', tpm=100000,
                                                   rpd=100, rpm=1, verified=True))
    for name in ('TEMP', 'TMP'):
        monkeypatch.setenv(name, tempfile.gettempdir())      # the pass redirects them; a nested pass restores them
    monkeypatch.setattr(tempfile, 'tempdir', tempfile.gettempdir())
    lease_a = F.claim(rig.state_path, rig.plan, 'T1')
    lease_b = F.claim(rig.state_path, rig.plan, 'T2000')
    assert lease_a and lease_b                               # disjoint files: both are runnable together
    inner, started = [], []
    run = rig.run_tests_fn

    def hook(root, tests, timeout_s):
        if not started:                                      # A's red_before: B runs its whole pass now
            started.append(1)
            inner.append(rig.once(task_id='T2000', lease=lease_b[1]))
        return run(root, tests, timeout_s)
    rig.run_tests_fn = hook
    result_a = rig.once(task_id='T1', lease=lease_a[1])
    result_b = inner[0]
    assert rig.coder_calls == ['T2000'], 'one booking only: %s' % rig.coder_calls
    assert result_a['status'] == 'WAITING_CHANNEL' and result_a['calls'] == []
    assert len(result_b['calls']) == 1 and result_b['calls'][0]['role'] in ('code', 'repair')
    state = rig.state()
    assert state['model_calls'] == 1 and len(state['channel_quotas']['p']['rpm_times']) == 1
    assert state['tasks']['T1']['status'] == 'READY' and 'began' not in state['tasks']['T1']


def gate_rig(tmp_path, monkeypatch, per_run_s, waits=None):
    rig = Rig(tmp_path, monkeypatch)
    clock = {'t': 1000.0}
    monkeypatch.setattr(rig.w, '_now', lambda: clock['t'])
    names = ['tests/test_n%d.py' % i for i in range(rig.w.MAX_NEIGHBORS)]
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: list(names))
    rig.calls = []

    def run(root, tests, timeout_s):
        wait_s = rig.gate_waits[-1]
        rig.calls.append((tuple(tests), wait_s))
        if len(rig.calls) == 1:                                  # red_before: a real red
            return rig._default_run_tests(root, tests, timeout_s)
        clock['t'] += per_run_s
        if waits is None:
            return gr(True) if tests[0] in names else rig._default_run_tests(root, tests, timeout_s)
        if wait_s <= 0:
            return dataclasses.replace(G.GateResult(-1, 0, 0, 0, 0, 0, False, 'pytest not started: no slot'),
                                       env_reason='pytest slot: no free pytest slot')
        waited = min(waits, wait_s)
        base = gr(True) if tests[0] in names else rig._default_run_tests(root, tests, timeout_s)
        return dataclasses.replace(base, slot_wait_s=waited)
    rig.run_tests_fn = run
    return rig


def test_slot_budget_counts_waiting_only(tmp_path, monkeypatch):
    rig = gate_rig(tmp_path, monkeypatch, per_run_s=60)          # 1 candidate run + 6 neighbours x 60 s = 420 s, no waiting
    result = rig.once()
    assert result['status'] == 'REVIEW'
    waits = rig.gate_waits[1:]
    assert len(waits) == 7 and set(waits) == {rig.w.SLOT_BUDGET_S}        # the run time never ate the budget
    assert result['stages']['slot_wait_s'] == 0.0


def test_slot_budget_spent_by_waiting_is_an_environment_shortage_not_a_strike(tmp_path, monkeypatch):
    rig = gate_rig(tmp_path, monkeypatch, per_run_s=10, waits=150)       # 150 + 150 s of waiting = the 300 s budget
    result = rig.once()
    waits = rig.gate_waits[1:]
    assert waits[:3] == [300, 150, 0.0]
    assert result['status'] == 'READY' and result['reason'] == 'transient' and 'env_shortage' in result['events']
    assert result['stages']['slot_wait_s'] == 300.0
    row = rig.state()['tasks']['T1']
    assert not rig.state().get('strikes') and row.get('pending_review') and row['attempts'] == 0


def test_gate_results_carry_the_slot_wait():
    assert G.GateResult(0, 1, 1, 0, 0, 0, True).slot_wait_s == 0.0
    merged = G._merge([(('a',), dataclasses.replace(gr(True), slot_wait_s=2.5)),
                       (('b',), dataclasses.replace(gr(True), slot_wait_s=4.0))])
    assert merged.slot_wait_s == 6.5


def test_pytest_slot_yields_how_long_it_waited(tmp_path, monkeypatch):
    monkeypatch.setattr(G, 'SLOT_DIRS', [str(tmp_path / 'slot1')])
    monkeypatch.setattr(G, '_free_ram', lambda: 8 * 2 ** 30)
    ticks = iter([100.0, 107.0])
    monkeypatch.setattr(G, '_clock', lambda: next(ticks, 107.0))
    monkeypatch.setattr(G, '_sleep', lambda s: None)
    with G.pytest_slot(wait_s=5) as why:
        assert why == '' and why.waited == 7.0


def test_the_runner_never_saves_the_state_by_itself():
    source = (ROOT / 'tools' / 'agent_factory_runner.py').read_text(encoding='utf-8')
    assert 'save_atomic(checkpoint' not in source and 'save_atomic(' not in re.sub(r'#.*', '', source.split('def once', 1)[1])
    assert 'LOCK_OWNER' not in source.split('def once', 1)[1]          # no whole-pass lock


def test_cli_passes_the_task_and_its_lease(tmp_path, monkeypatch):
    from tools import agent_factory_runner as w
    seen = {}

    def fake_once(**kwargs):
        seen.update(kwargs)
        return {'status': 'IDLE'}
    monkeypatch.setattr(w, 'once', fake_once)
    base = ['--root', str(tmp_path / 'src'), '--plan', str(tmp_path / 'p.json'),
            '--checkpoint', str(tmp_path / 's.json'), '--staging', str(tmp_path / 'stage'),
            '--small-model', 'google/x', '--large-model', 'google/x']
    assert w.main(base + ['--task', 'T2000', '--lease', 'abc123']) == 0
    assert seen['task_id'] == 'T2000' and seen['lease'] == 'abc123'
    seen.clear()
    assert w.main(base) == 0
    assert seen['task_id'] is None and seen['lease'] is None


# ---- review fixes (coordinator 20.11): the leaked lease, the busy lock, the unreturned booking, the lock drop ----

def _row(rig, tid='T2000'):
    return rig.state()['tasks'][tid]


def test_a_lease_handed_in_is_returned_when_once_raises_before_the_pass(tmp_path, monkeypatch):
    rig = disjoint_rig(tmp_path, monkeypatch)
    tid, token = F.claim(rig.state_path, rig.plan, 'T2000')
    monkeypatch.setattr(rig.w.shutil, 'which', lambda _: None)
    monkeypatch.delenv('FACTORY_KILO_ENTRY', raising=False)
    with pytest.raises(F.InvalidPlan):
        rig.once(task_id='T2000', lease=token)
    row = _row(rig)
    assert row['status'] == 'READY' and row['attempts'] == 0 and row.get('lease') is None and 'began' not in row


def test_a_lease_handed_in_is_returned_on_an_os_error_before_the_pass_and_on_a_dry_run(tmp_path, monkeypatch):
    rig = disjoint_rig(tmp_path, monkeypatch)
    tid, token = F.claim(rig.state_path, rig.plan, 'T2000')

    def boom(staging, *a, **k):
        raise OSError('locked')
    monkeypatch.setattr(rig.w, 'sweep_scratch', boom)
    result = rig.once(task_id='T2000', lease=token)
    assert result['status'] == 'READY' and result['reason'] == 'os_error'
    assert _row(rig)['status'] == 'READY' and _row(rig)['attempts'] == 0 and _row(rig).get('lease') is None
    tid, token = F.claim(rig.state_path, rig.plan, 'T2000')
    assert rig.once(task_id='T2000', lease=token, execute=False)['status'] == 'DRY_RUN'
    assert _row(rig)['status'] == 'READY' and _row(rig)['attempts'] == 0


def test_the_lease_comes_back_when_the_begin_commit_fails(tmp_path, monkeypatch):
    rig = disjoint_rig(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise OSError('disk')
    monkeypatch.setattr(rig.w, 'begin', boom)
    with pytest.raises(OSError):
        rig.once(task_id='T2000')                  # the pass claimed its own lease
    row = _row(rig)
    assert row['status'] == 'READY' and row['attempts'] == 0 and row.get('lease') is None


def test_a_busy_lock_inside_the_pass_is_no_machine_fault_of_the_task(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    real = F.Lease.commit

    def busy(self, fn):
        if fn.__name__ == 'account':
            raise F.LockBusy('plan is locked by another writer')
        return real(self, fn)
    monkeypatch.setattr(F.Lease, 'commit', busy)
    result = rig.once()                        # must not raise, must not call the busy lock a task fault
    assert result['status'] == 'READY' and result['reason'] == 'lock_busy' and result['infra'] is False
    row = rig.state()['tasks']['T1']
    assert row.get('defer_reason') != 'os_error' and not row.get('defer_streak')
    assert row['status'] == 'RUNNING'          # nothing was written: the lease runs out on its own


def test_a_call_that_dies_after_booking_gives_the_reservation_back(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)

    def dies(t, directory, name, timeout, **kwargs):
        raise OSError('the engine died')
    monkeypatch.setattr(rig.w, 'model_attempt', dies)
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'os_error'
    group = rig.state()['channel_quotas']['p']
    assert group['requests'] == 0 and not group['request_times'] and not group['rpm_times']


def test_the_lock_is_not_leaked_when_a_waiter_holds_the_owner_file_open(tmp_path, monkeypatch):
    """Windows: a waiter reading the owner file at the moment the holder removes it is a sharing violation."""
    lock = tmp_path / 'x.json.lockdir'
    lock.mkdir()
    (lock / F.LOCK_OWNER).write_text('1', encoding='ascii')
    real = Path.unlink
    fails = {'n': 3}

    def sharing(self, *args, **kwargs):
        if self.name == F.LOCK_OWNER and fails['n'] > 0:
            fails['n'] -= 1
            raise PermissionError(32, 'sharing violation')
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', sharing)
    F._drop_lock(lock)
    assert not lock.exists() and fails['n'] == 0
