"""<id>/<id> wiring (owner: the factory sees the errors of its own conveyor and sets itself the tasks that
fix it). At most once an hour the loop gives the most frequent repeated failure class ONE self-build plan designed by
a free head model (tools/factory_selffix.py); one failure counts once (the runner's attempt row, not the loop's RUN
event that repeats it); a head that was not reached is asked again next hour; a busy queue is never doubled; a fault
never stops the loop. The model call and the queue are faked."""
import json

from tests.test_factory_loop import Env, L, task_row
from tools import factory_selffix as X


def rows(n, reason='review: The test is a stub and does not actually verify it', span='run'):
    return [{'ts': '2026-11-20T01:0%d:00+03:00' % i, 'span': span, 'task_id': 'T%d' % i, 'attempt': 1,
             'reason': reason, 'status': 'FAILED'} for i in range(n)]


def setup(tmp_path, monkeypatch, tel_rows, answer='{"skip": "not a factory defect"}', status='ok'):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    with (env.state_dir / 'telemetry.jsonl').open('a', encoding='utf-8') as fh:
        for r in tel_rows:
            fh.write(json.dumps(r) + '\n')
    self_dir = tmp_path / 'self'
    self_dir.mkdir()
    (self_dir / 'src_path.txt').write_text('%s\nabc123\n' % (tmp_path / 'src'), encoding='utf-8')
    monkeypatch.setattr(L.Loop, 'SELF_DIR', self_dir)
    calls, seen = [], {}

    def fake_run(rows_, ledger, *, ask, **kw):
        seen['rows'] = rows_
        answer_text = ask('prompt')
        calls.append(answer_text)
        ledger['weak-test'] = {'at': kw['now_iso'], 'status': 'skipped', 'why': 'x'}
        return {'cls': 'weak-test', 'status': 'skipped', 'why': 'not a factory defect'}
    monkeypatch.setattr(X, 'run', fake_run)
    monkeypatch.setattr(X, 'queue_running', lambda d: False)
    loop = env.loop()
    monkeypatch.setattr(loop, '_light_ask', lambda text, **kw: (status, 'google/x', answer if status == 'ok' else '', 9))
    return env, loop, calls, seen


def test_one_failure_counts_once_and_the_class_gets_one_plan_an_hour(tmp_path, monkeypatch):
    tel = rows(2) + rows(2, span='loop')
    env, loop, calls, seen = setup(tmp_path, monkeypatch, tel)
    loop._selffix()
    loop._selffix()                                          # the same hour: nothing more
    assert len(calls) == 1
    assert len(seen['rows']) == 2 and all(r['span'] == 'run' for r in seen['rows'])
    event = [e for e in env.events() if e.get('span') == 'selffix'][-1]
    assert event['status'] == 'skipped' and 'weak-test' in event['reason']
    assert loop.ls()['selffix']['weak-test']['status'] == 'skipped'


def test_a_head_that_was_not_reached_is_asked_again_next_hour(tmp_path, monkeypatch):
    env, loop, calls, seen = setup(tmp_path, monkeypatch, rows(2), status='no_channel')
    loop._selffix()
    assert 'weak-test' not in loop.ls().get('selffix', {})


def test_a_busy_queue_is_never_doubled_and_a_fault_never_stops_the_loop(tmp_path, monkeypatch):
    env, loop, calls, seen = setup(tmp_path, monkeypatch, rows(2))
    monkeypatch.setattr(X, 'queue_running', lambda d: True)
    loop._selffix()
    assert not calls and [e for e in env.events() if e.get('span') == 'selffix'][-1]['status'] == 'queue_busy'

    def boom(*a, **k):
        raise OSError('disk')
    monkeypatch.setattr(X, 'queue_running', boom)
    loop.clock = lambda: 10 ** 10
    loop._selffix()
    assert any(e.get('span') == 'infra' and 'selffix' in e.get('reason', '') for e in env.events())
