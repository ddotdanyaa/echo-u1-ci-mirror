"""<id> (owner: the loop never stands in HOLD while there are tasks). A FAILED or BLOCKED task whose last
failure has a class of the failure register (tools/factory_classes.py) goes back to the queue once per new factory
code version, through the same answer box Opus uses (one JSON file per answer in <state_dir>/answers). At most
max_times per task; infrastructure classes, unknown failures, scope or green-base refusals and skipped (owner-only,
private) tasks stay. A ledger <state_dir>/requeue_ledger.json keeps the code versions each task was requeued on."""
import json

from tools import factory_classes as C
from tools import factory_requeue as R


def _state(**rows):
    return {'tasks': {tid: dict(status=st, feedback=[{'source': 'attempt 3', 'text': text}])
                      for tid, (st, text) in rows.items()}}


STATE = _state(
    A=('FAILED', 'the model produced no change to the approved files (the answer had no SEARCH/REPLACE edit block)'),
    B=('BLOCKED', 'does not compile: invalid syntax (tests/test_x.py, line 64)'),
    C=('FAILED', 'scope_violation: tools/other.py is outside the task'),
    D=('FAILED', 'HTTP 503 transient overload'),
    E=('DONE', 'had no SEARCH/REPLACE edit block'),
    F=('FAILED', 'something nobody classified'),
    G=('FAILED', 'review: the test only checks that something changed'),
)


def test_a_review_rejection_has_its_own_class_and_a_weak_test_stays_weak():
    assert C.classify('review: the test only checks that something changed') == 'review-reject'
    assert C.classify('review: The test is a stub and does not actually verify it') == 'weak-test'


def test_classified_failures_are_picked_once_per_code_version():
    assert R.pick(STATE, 'v1', {}) == [('A', 'no-edit-block'), ('B', 'test-crash'), ('G', 'review-reject')]
    assert R.pick(STATE, 'v1', {'A': ['v1']}) == [('B', 'test-crash'), ('G', 'review-reject')]
    assert R.pick(STATE, 'v4', {'A': ['v1', 'v2', 'v3']}, max_times=3) == [('B', 'test-crash'),
                                                                          ('G', 'review-reject')]
    assert R.pick(STATE, 'v1', {}, skip={'B', 'G'}) == [('A', 'no-edit-block')]


def test_the_note_names_the_version_and_the_remedy_of_the_class_without_quotes():
    note = R.note('search-miss', 'abc123def456')
    assert 'abc123def456' in note and 'ERROR_PATTERNS repairs' in note and 'could not copy the code' in note
    assert not any(ch in note for ch in '()"«»')


def test_run_writes_answers_and_the_ledger_and_does_not_repeat_on_the_same_version(tmp_path):
    (tmp_path / 'state.json').write_text(json.dumps(STATE), encoding='utf-8')
    assert R.run(tmp_path, 'v9') == ['A', 'B', 'G']
    answers = sorted((tmp_path / 'answers').glob('*.json'))
    payloads = [json.loads(p.read_text(encoding='utf-8')) for p in answers]
    assert sorted(p['task_id'] for p in payloads) == ['A', 'B', 'G']
    assert all(set(p) == {'task_id', 'note'} and 'v9' in p['note'] for p in payloads)
    ledger = json.loads((tmp_path / 'requeue_ledger.json').read_text(encoding='utf-8'))
    assert {k: v for k, v in ledger.items() if not k.startswith('at:')} == {'A': ['v9'], 'B': ['v9'], 'G': ['v9']}
    assert {k for k in ledger if k.startswith('at:')} == {'at:A', 'at:B', 'at:G'}   # <id>: the term starts here
    assert R.run(tmp_path, 'v9') == []
    assert len(list((tmp_path / 'answers').glob('*.json'))) == 3
    # <id>: on the same version only once the term is over, booked as 'term:<time>'; max_times stays shared
    at = ledger['at:A'][0]
    assert R.run(tmp_path, 'v9', now=at + 10, term_s=3600) == []
    assert R.run(tmp_path, 'v9', now=at + 3601, term_s=3600) == ['A', 'B', 'G']
    ledger = json.loads((tmp_path / 'requeue_ledger.json').read_text(encoding='utf-8'))
    assert ledger['A'][0] == 'v9' and ledger['A'][1].startswith('term:') and len(ledger['A']) == 2
    assert R.run(tmp_path, 'v9', now=at + 3700, term_s=3600) == []          # the new term started at the retry


def test_a_note_refused_by_the_public_check_is_not_written(tmp_path):
    (tmp_path / 'state.json').write_text(json.dumps(STATE), encoding='utf-8')

    def refuse(note):
        raise ValueError('refused')

    assert R.run(tmp_path, 'v9', check=refuse) == []
    assert not list((tmp_path / 'answers').glob('*.json')) if (tmp_path / 'answers').exists() else True
    assert not (tmp_path / 'requeue_ledger.json').exists() or json.loads(
        (tmp_path / 'requeue_ledger.json').read_text(encoding='utf-8')) == {}


def test_the_failure_is_read_past_the_notes_of_opus_after_it():
    """Live 20.11 00:11: after a requeue the newest feedback items are Opus notes; the failure class is read from
    the newest non-Opus items (the gate's 'do not repeat' signature alone names no class, the item before it does)."""
    state = {'tasks': {
        'K': dict(status='FAILED', feedback=[
            {'source': 'attempt 3', 'text': 'The test is a stub and does not actually verify the behaviour'},
            {'source': 'opus', 'text': 'Retry with the light engine'},
            {'source': 'opus', 'text': 'Retry: a second critic now checks the test'}]),
        'U': dict(status='FAILED', feedback=[
            {'source': 'gate', 'text': '[attempt 3] rc=1 (0 required) failure tests.verify.test_v::t: AssertionError'},
            {'source': 'gate', 'text': 'не повторяй: gate:#bf8d34f08f'}])}}
    assert R.pick(state, 'v1', {}) == [('K', 'weak-test'), ('U', 'gate-red')]


def test_a_task_quarantined_by_its_sibling_takes_the_sibling_failure_class():
    """Live 20.11 00:27: 15 of 20 FAILED ECHO tasks were quarantined by the strikes of their test task (same backlog
    row) and had no failure of their own; the requeue read 'quarantine' and skipped them all."""
    state = {'tasks': {
        'M': dict(status='FAILED', reason='quarantine', backlog_id='E1', feedback=[{'source': 'opus', 'text': 'x'}]),
        'M_test': dict(status='FAILED', reason='quarantine', backlog_id='E1', feedback=[
            {'source': 'attempt 3', 'text': 'junit not ok: timeout after 30s (process tree killed)'}]),
        'L': dict(status='FAILED', reason='quarantine', backlog_id='E2', feedback=[])}}
    assert R.pick(state, 'v1', {}) == [('M', 'test-hang'), ('M_test', 'test-hang')]


def test_a_class_taken_from_the_sibling_names_the_sibling_in_the_note(tmp_path):
    """Live 20.11 00:53: the coder of <id> was told 'your last attempt failed as weak-test' - it was the test task
    of the same row that had failed so; the note of a borrowed class names the sibling instead."""
    state = {'tasks': {
        'W': dict(status='FAILED', reason='quarantine', backlog_id='W03000', feedback=[]),
        'W_test': dict(status='FAILED', reason='quarantine', backlog_id='W03000', feedback=[
            {'source': 'review', 'text': 'review: The test is a stub and does not actually verify it'}])}}
    (tmp_path / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    assert R.run(tmp_path, 'v9') == ['W', 'W_test']
    notes = {json.loads(p.read_text(encoding='utf-8'))['task_id']: json.loads(p.read_text(encoding='utf-8'))['note']
             for p in (tmp_path / 'answers').glob('*.json')}
    assert 'held back because W_test of the same backlog row failed as weak-test' in notes['W']
    assert 'Your last attempt' not in notes['W']
    assert notes['W_test'].startswith('Retry on factory version v9. Your last attempt failed as weak-test')


def _audit_state():
    st = {'tasks': {
        'X': dict(status='FAILED', kind='code', backlog_id='Q1',
                  feedback=[{'source': 'gate', 'text': '[attempt 3] gate: rc=1 (0 required) AssertionError'}]),
        'X_test': dict(status='PROMOTED', kind='unit_test', backlog_id='Q1', feedback=[]),
    }}
    return st


def test_a_code_task_that_keeps_failing_its_gate_sends_its_promoted_test_back(tmp_path):
    """20.11 02:55: three of five promoted factory tests whose fixes kept failing could never be made green by a
    correct fix. After AUDIT_AFTER returns of the code task the test goes back to its test task, once."""
    (tmp_path / 'state.json').write_text(json.dumps(_audit_state()), encoding='utf-8')
    (tmp_path / 'requeue_ledger.json').write_text(json.dumps({'X': ['v1']}), encoding='utf-8')
    assert R.run(tmp_path, 'v2') == ['X']                      # one return so far: the code task again
    assert R.run(tmp_path, 'v3') == ['X_test']                 # two returns: the test is suspected
    answers = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((tmp_path / 'answers').glob('*.json'))]
    audit = [a for a in answers if a['task_id'] == 'X_test']
    assert len(audit) == 1 and audit[0]['reject'] is True and 'v3' in audit[0]['note']
    assert 'replace the function the behaviour happens in' in audit[0]['note']
    assert not any(ch in audit[0]['note'] for ch in '()"«»')
    ledger = json.loads((tmp_path / 'requeue_ledger.json').read_text(encoding='utf-8'))
    assert ledger['audit:X_test'] == ['v3'] and ledger['X'] == ['v1', 'v2', 'v3']
    assert R.run(tmp_path, 'v4') == []                         # max_times reached, the audit is never repeated


def test_the_audit_of_a_promoted_test_is_reached_after_max_returns(tmp_path):
    """Live 20.11: the audit could fire only at exactly AUDIT_AFTER returns; tasks already past it (3 or 4 returns)
    were dropped by max_times before the audit was checked."""
    (tmp_path / 'state.json').write_text(json.dumps(_audit_state()), encoding='utf-8')
    (tmp_path / 'requeue_ledger.json').write_text(json.dumps({'X': ['v1', 'v2', 'v3']}), encoding='utf-8')
    assert R.run(tmp_path, 'v4') == ['X_test']
    assert R.run(tmp_path, 'v5') == []                         # once per test; max_times for the code task


def test_a_cut_test_is_gate_cut_for_a_code_task_and_a_hang_for_a_test_task():
    text = 'gate: junit not ok: tests/test_a.py: timeout after 30s (process tree killed)'
    state = {'tasks': {
        'C': dict(status='FAILED', kind='code', feedback=[{'source': 'gate', 'text': text}]),
        'T': dict(status='FAILED', kind='unit_test', feedback=[{'source': 'gate', 'text': text}])}}
    assert R.pick(state, 'v1', {}) == [('C', 'gate-cut'), ('T', 'test-hang')]


def test_a_window_left_with_repeat_markers_only_still_names_the_class():
    """Live 20.11: the loop's repeat marker had evicted the failure it repeats; three FAILED code tasks held only
    markers and were never returned. A marker is written only for a repeated gate, weakening or review rejection."""
    state = {'tasks': {
        'G': dict(status='FAILED', kind='code', feedback=[
            {'source': 'opus', 'text': 'x'}, {'source': 'gate', 'text': 'не повторяй: gate:#bf8d34f08f'}]),
        'V': dict(status='FAILED', kind='code', feedback=[{'source': 'gate', 'text': 'не повторяй: review:#0123456789'}]),
        'N': dict(status='FAILED', kind='code', feedback=[{'source': 'opus', 'text': 'only a note'}])}}
    assert R.pick(state, 'v1', {}) == [('G', 'gate-red'), ('V', 'review-reject')]


def test_a_test_written_by_hand_or_not_promoted_is_never_suspected(tmp_path):
    st = _audit_state()
    st['tasks']['X_test']['status'] = 'DONE'
    (tmp_path / 'state.json').write_text(json.dumps(st), encoding='utf-8')
    (tmp_path / 'requeue_ledger.json').write_text(json.dumps({'X': ['v1', 'v2']}), encoding='utf-8')
    assert R.run(tmp_path, 'v3') == ['X']
