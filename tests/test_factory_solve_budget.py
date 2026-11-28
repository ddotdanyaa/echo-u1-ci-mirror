"""fac-88: a solve ends by its own budgets (steps, silence, the cloud's own timeout); the clock alone never throws its steps away.
Live 25.11-28.11: 100 of 157 solves were dropped as 'older than 3600 s', while a finished solve takes 21-120 minutes."""
import threading
import time
from types import SimpleNamespace

from tools import factory_loop as L
from tools import factory_solver as SV

SILENT = 900.0


def _job(age=0.0, heard_ago=None, cloud_left=None):
    stop = threading.Event()
    job = L.Prefetch('solver', lambda: stop.wait(10), dict(row='E1', base='b', root='/nowhere'))
    now = time.monotonic()
    if heard_ago is not None:
        job.thread.heard = now - heard_ago
    if cloud_left is not None:
        job.thread.cloud_until = now + cloud_left
    job.thread.start()
    job.t0 -= age
    return job, stop


def _loop(job, events, stale=None):
    return SimpleNamespace(_hypers={'E1': job}, _hypo_skip={}, _hypo_dropped=[], base_sha='b', SOLVE_SILENT_S=SILENT,
                           HYPO_STALE_S=L.Loop.HYPO_STALE_S if stale is None else stale, err=lambda *a: None,
                           event=lambda kind, **k: events.append((kind, k.get('backlog_id'), k.get('status'), k.get('why'))))


def test_a_solve_older_than_an_hour_that_heard_an_answer_lately_is_kept():
    job, stop = _job(age=4000.0, heard_ago=100.0)
    events = []
    loop = _loop(job, events)
    L.Loop._hypo_collect(loop, 5.0)
    stop.set()
    assert list(loop._hypers) == ['E1'] and not job.cancel.is_set() and events == [] and loop._hypo_skip == {}


def test_a_silent_solve_is_dropped_and_the_event_says_what_was_lost():
    job, stop = _job(age=2000.0, heard_ago=SILENT + 50.0)
    job.thread.steps = 7
    events = []
    loop = _loop(job, events)
    L.Loop._hypo_collect(loop, 5.0)
    stop.set()
    assert loop._hypers == {} and job.cancel.is_set() and loop._hypo_dropped == [job] and loop._hypo_skip == {'E1': ('b', 5.0)}
    assert len(events) == 1 and events[0][:3] == ('solver', 'E1', 'stale')
    assert 'silent' in events[0][3] and '7 steps' in events[0][3] and 'age 2000 s' in events[0][3]


def test_a_solve_waiting_for_the_cloud_inside_its_timeout_is_working_not_silent():
    job, stop = _job(age=3000.0, heard_ago=SILENT * 2, cloud_left=600.0)
    events = []
    loop = _loop(job, events)
    L.Loop._hypo_collect(loop, 5.0)
    stop.set()
    assert list(loop._hypers) == ['E1'] and not job.cancel.is_set() and events == []


def test_a_cloud_call_past_its_own_timeout_does_not_keep_a_silent_solve():
    job, stop = _job(age=3000.0, heard_ago=SILENT * 2, cloud_left=-1.0)
    events = []
    loop = _loop(job, events)
    L.Loop._hypo_collect(loop, 5.0)
    stop.set()
    assert loop._hypers == {} and job.cancel.is_set()


def test_a_solve_that_never_heard_anything_is_dropped_after_the_silence():
    young, stop1 = _job(age=SILENT - 100.0)
    old, stop2 = _job(age=SILENT + 100.0)
    for job, dropped in ((young, False), (old, True)):
        events = []
        loop = _loop(job, events)
        L.Loop._hypo_collect(loop, 5.0)
        assert (loop._hypers == {}) is dropped and job.cancel.is_set() is dropped
        assert bool(events) is dropped
    stop1.set()
    stop2.set()


def test_the_backstop_is_computed_from_the_budgets_and_drops_whatever_the_solve_heard():
    assert L.Loop.HYPO_STALE_S == max(SV.STEPS, SV.STEPS_TFIRST) * L.Loop.SOLVE_SILENT_S
    job, stop = _job(age=L.Loop.HYPO_STALE_S + 10.0, heard_ago=1.0)
    events = []
    loop = _loop(job, events)
    L.Loop._hypo_collect(loop, 5.0)
    stop.set()
    assert loop._hypers == {} and job.cancel.is_set() and events[0][2] == 'stale' and 'backstop' in events[0][3]


def test_the_ask_and_the_cloud_set_one_mark_and_the_cloud_marks_its_flight(monkeypatch):
    from tools import factory_hypo as HY
    seen = {}

    def fake_cloud(root, ids, files, tid=''):
        t = threading.current_thread()
        seen['during'] = t.cloud_until - time.monotonic()
        seen['heard_before'] = t.heard
        return {'ok': 1}
    monkeypatch.setattr(HY, 'cloud_batch', fake_cloud)
    fake = SimpleNamespace(_arch_quotas={}, SOLVE_SILENT_S=8.0, SOLVER_RETRY_S=4.0, SOLVER_MAX_TOKENS=10, SOLVER_TEMPERATURE=0.1,
                           _sleep=lambda s: None, _review_hold=lambda: False, stop=SimpleNamespace(exists=lambda: False),
                           _light_ask=lambda *a, **k: ('ok', 'gemma', 'A', 0))
    out = {}

    def work():
        t = threading.current_thread()
        t.heard = 1.0           # an old mark
        ctx = L.Loop._solver_ctx(fake, '/nowhere', {'bid': 'E1'})
        ctx.ask('one')
        out['after_ask'] = (t.heard, t.steps)
        ctx.cloud('/nowhere', ['x'], {})
        out['after_cloud'] = (t.heard, t.cloud_until)
    job = L.Prefetch('solver', work, {})
    job.thread.start()
    job.thread.join(5)
    assert job.error is None
    assert out['after_ask'][0] > 1.0 and out['after_ask'][1] == 1
    assert seen['during'] > 600.0 and seen['heard_before'] == out['after_ask'][0]
    assert out['after_cloud'][0] >= out['after_ask'][0] and out['after_cloud'][1] is None


def test_a_running_solve_older_than_an_hour_keeps_its_snapshot(tmp_path):
    snaps = tmp_path / 'snaps'
    old, newest = snaps / 'aaaaaaaaaaaa', snaps / 'bbbbbbbbbbbb'
    old.mkdir(parents=True)
    newest.mkdir()
    job, stop = _job(age=5000.0, heard_ago=10.0)
    job.ctx['root'] = str(old)
    loop = SimpleNamespace(pool=SimpleNamespace(roots=lambda: []), _slicers={}, _hypers={'E1': job}, _hypo_dropped=[],
                           base_sha='bbbbbbbbbbbb' + '0' * 28, snap_dir=snaps, _rel_snap=None, err=lambda *a: None)
    L.Loop._prune_snapshots(loop)
    stop.set()
    assert old.is_dir() and newest.is_dir()
