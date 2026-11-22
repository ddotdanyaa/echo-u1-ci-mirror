"""<id> (owner: «реестр классов ошибок ... класс, повторившийся 2 раза, сам становится задачей самопочинки»).
Every failed attempt of the loop gets a class; the classes are counted over the telemetry; a class that repeated at
least twice, is not an infrastructure class and has no open self-fix yet becomes a self-fix question for the head
(Opus or any other), with its tasks, examples and the remedy known today."""
from tools import factory_classes as K


def test_failures_get_their_class():
    assert K.classify('gate:no_changes', 'edit blocks 2, changed files 0; 1: SEARCH not found exactly once') == 'search-miss'
    assert K.classify('gate:no_changes', 'the answer had no SEARCH/REPLACE edit block') == 'no-edit-block'
    assert K.classify('gate:no_changes', 'the model answered CANNOT: the row is a design question') == 'cannot'
    assert K.classify('review: The test is a stub and does not actually verify the behaviour', '') == 'weak-test'
    assert K.classify('gate: тест не ловит дефект: на старом коде зелёный', '') == 'weak-test'
    assert K.classify('gate: the test crashes before its assertion on the current code', '') == 'test-crash'
    assert K.classify('gate: rc=1 (0 required)', 'failure tests.test_x::test_y: AssertionError') == 'gate-red'
    assert K.classify('rate_day', '') == 'quota' and K.classify('transient', '{"code": 503}') == 'overload'
    assert K.classify('something new', '') == 'unknown'


def _row(ts, task, reason, detail='', status='FAILED'):
    return {'ts': ts, 'span': 'loop', 'action': 'RUN', 'task_id': task, 'status': status, 'reason': reason,
            'reason_detail': detail}


ROWS = [_row('2026-11-19T22:00:00+03:00', 'bl_A', 'gate:no_changes', '1: SEARCH not found exactly once'),
        _row('2026-11-19T22:10:00+03:00', 'bl_B', 'gate:no_changes', '1: SEARCH not found exactly once', 'READY'),
        _row('2026-11-19T22:20:00+03:00', 'bl_C', 'rate_day', '', 'READY'),
        _row('2026-11-19T22:30:00+03:00', 'bl_C', 'rate_day', '', 'READY'),
        _row('2026-11-19T22:40:00+03:00', 'bl_D', 'review: The test is a stub'),
        _row('2026-11-19T20:00:00+03:00', 'bl_E', 'review: The test is a stub'),          # before `since`
        {'ts': '2026-11-19T22:50:00+03:00', 'span': 'loop', 'action': 'HOLD', 'reason': 'only_opus_or_blocked'},
        _row('2026-11-19T22:55:00+03:00', 'bl_F', None, '', 'REVIEW')]                # a success has no class


def test_counting_keeps_the_tasks_and_a_few_examples_since_a_time():
    counts = K.count(ROWS, since='2026-11-19T21:00:00+03:00')
    assert counts['search-miss']['n'] == 2 and counts['search-miss']['tasks'] == ['bl_A', 'bl_B']
    assert counts['search-miss']['examples'][0].startswith('gate:no_changes')
    assert counts['quota']['n'] == 2 and counts['weak-test']['n'] == 1
    assert 'unknown' not in counts and sum(c['n'] for c in counts.values()) == 5


def test_a_repeated_class_without_an_open_fix_is_due_infrastructure_never():
    counts = K.count(ROWS, since='2026-11-19T21:00:00+03:00')
    assert K.due(counts, open_classes=set()) == ['search-miss']             # quota repeated too: infrastructure
    assert K.due(counts, open_classes={'search-miss'}) == []
    assert K.due(counts, open_classes=set(), threshold=1) == ['search-miss', 'weak-test']


def test_the_self_fix_question_names_the_class_tasks_examples_and_known_remedy():
    counts = K.count(ROWS, since='2026-11-19T21:00:00+03:00')
    text = K.question('search-miss', counts['search-miss'])
    assert text.startswith('Self-fix search-miss:') and 'bl_A' in text and 'bl_B' in text and '2 times' in text
    assert 'SEARCH not found' in text and 'known remedy:' in text


def test_a_hanging_test_has_its_own_class_and_it_is_not_infrastructure():
    """Live 19.11 (<id>_test, <id>): 'junit not ok: timeout after 30s (process tree killed)' - the written test
    waits on a device, a network or a sleep; it was read as weak-test or not classified at all."""
    text = '[attempt 3] junit not ok: timeout after 30s (process tree killed) timeout after 30s (process tree killed)'
    assert K.classify(text) == 'test-hang'
    assert 'test-hang' not in K.INFRASTRUCTURE_CLASSES
    assert K.classify('The test is a stub and does not actually verify') == 'weak-test'


def test_a_test_of_a_code_task_cut_at_the_limit_is_its_own_class():
    """Live 20.11 06:08-06:28: four code tasks failed on '<file>: timeout after 30s'; their tests are the
    repository's (slow or hanging here), the coder wrote none, so the test-hang advice was wrong for them."""
    assert K.classify('gate: junit not ok: tests/test_silence_kinds.py: timeout after 30s (process tree killed)') \
        == 'gate-cut'
    assert K.classify('junit not ok: tests/test_a.py::t2 (+3 more): timeout after 30s: the split budget was spent') \
        == 'gate-cut'
    assert K.classify('[attempt 3] junit not ok: timeout after 30s (process tree killed)') == 'test-hang'
    assert 'gate-cut' not in K.INFRASTRUCTURE_CLASSES
