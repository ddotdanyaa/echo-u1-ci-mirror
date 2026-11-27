"""Class found 19.11 23:50 (<id>, <id>): a test task and its main task share the strike key of their backlog
row. Three failed passes of the test task quarantine the main task too, although it never ran (attempts 0). When the
test task is promoted later, the strikes are reset (already so) and a main task quarantined without an attempt of its
own goes back to READY; a task that failed on its own attempts, or a task of another row, stays FAILED."""
from tools import agent_factory as F


def _state():
    return {'strikes': {'bl:E1': 3}, 'tasks': {
        'T': dict(status='REVIEW', kind='unit_test', backlog_id='E1', attempts=2),
        'C': dict(status='FAILED', reason='quarantine', backlog_id='E1', attempts=0),
        'D': dict(status='FAILED', reason='quarantine', backlog_id='E1', attempts=2),
        'X': dict(status='FAILED', reason='quarantine', backlog_id='E2', attempts=0)}}


def test_the_main_task_quarantined_by_its_test_task_returns_when_the_test_is_promoted():
    state = _state()
    F.mark_promoted(state, 'T', 'abc1234')
    assert state['tasks']['T']['status'] == 'PROMOTED'
    assert 'bl:E1' not in state['strikes']
    assert state['tasks']['C']['status'] == 'READY' and state['tasks']['C'].get('reason') is None
    assert state['tasks']['D']['status'] == 'FAILED'
    assert state['tasks']['X']['status'] == 'FAILED'


def test_promoting_a_main_task_revives_nothing():
    state = _state()
    state['tasks']['T']['kind'] = 'code'
    F.mark_promoted(state, 'T', 'abc1234')
    assert state['tasks']['C']['status'] == 'FAILED'
