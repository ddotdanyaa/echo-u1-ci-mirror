"""<id> wiring (owner: the loop never stands while there are tasks). At its START the loop gives the
FAILED/BLOCKED tasks one more try on its own code version through tools.factory_requeue (the answers go through the
Opus answer box), skipping owner-only and private tasks, with the public check of notes; the result is one REQUEUE
event; a fault of the requeue never stops the loop."""
from tests.test_factory_loop import Env, L, task_row
from tools import factory_requeue


def test_the_loop_requeues_on_its_version_and_logs_it(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1), task_row(2, only_opus=True)])
    seen = {}

    def fake(state_dir, code, *, skip=(), check=None, max_times=3):
        seen.update(state_dir=state_dir, code=code, skip=set(skip), check=check)
        return ['T1']
    monkeypatch.setattr(factory_requeue, 'run', fake)
    env.loop()._requeue_on_new_version()
    assert str(seen['state_dir']) == str(env.state_dir)
    assert seen['code'] == L._ROOT.name
    assert seen['skip'] == {'T%d' % 2}
    assert seen['check'] == L.Loop._check_note
    events = [e for e in env.events() if e.get('action') == 'REQUEUE']
    assert len(events) == 1 and 'T1' in events[0]['reason']


def test_nothing_requeued_writes_no_event(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    monkeypatch.setattr(factory_requeue, 'run', lambda *a, **k: [])
    env.loop()._requeue_on_new_version()
    assert not [e for e in env.events() if e.get('action') == 'REQUEUE']


def test_a_requeue_fault_never_stops_the_loop(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1)])

    def boom(*a, **k):
        raise OSError('disk')
    monkeypatch.setattr(factory_requeue, 'run', boom)
    env.loop()._requeue_on_new_version()
