"""fac-feedback-window (live 20.11): the loop's repeat marker ("не повторяй: ...") was the newest gate remark, so
add_feedback evicted the failure it repeats; the requeue then read markers only, found no class and never returned
the task. The window keeps the newest real failure; it evicts older failures, then older markers, then the oldest
Opus note."""
from tools import agent_factory as F

FAIL = '[attempt 3] rc=1 (0 required) failure tests.verify.test_v::t: AssertionError'


def _row(*items):
    return {'tasks': {'T': {'status': 'FAILED', 'kind': 'code',
                            'feedback': [{'source': s, 'text': t} for s, t in items]}}}


def test_a_repeat_marker_never_pushes_out_the_failure_it_repeats():
    state = _row(('opus', 'note one'), ('opus', 'note two'), ('gate', FAIL))
    F.add_feedback(state, 'T', 'gate', F.REPEAT_MARK + ' gate:#aQX18d34f08f')
    texts = [x['text'] for x in state['tasks']['T']['feedback']]
    assert texts == ['note two', FAIL, F.REPEAT_MARK + ' gate:#aQX18d34f08f']

def test_older_markers_go_before_notes_and_a_new_failure_replaces_the_old_one():
    state = _row(('opus', 'note'), ('gate', FAIL), ('gate', F.REPEAT_MARK + ' a'))
    F.add_feedback(state, 'T', 'gate', F.REPEAT_MARK + ' b')
    assert [x['text'] for x in state['tasks']['T']['feedback']] == ['note', FAIL, F.REPEAT_MARK + ' b']
    F.add_feedback(state, 'T', 'review', 'review: the change misses the case')
    assert [x['text'] for x in state['tasks']['T']['feedback']] == ['note', F.REPEAT_MARK + ' b',
                                                                     'review: the change misses the case']


def test_without_markers_the_window_is_as_before():
    state = _row(('gate', 'first'), ('gate', 'second'), ('opus', 'note'))
    F.add_feedback(state, 'T', 'gate', 'third')
    assert [x['text'] for x in state['tasks']['T']['feedback']] == ['second', 'note', 'third']
