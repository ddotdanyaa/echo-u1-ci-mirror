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


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


def _audit_state():
    st = {'tasks': {
        'X': dict(status='FAILED', kind='code', backlog_id='Q1',
                  feedback=[{'source': 'gate', 'text': '[attempt 3] gate: rc=1 (0 required) AssertionError'}]),
        'X_test': dict(status='PROMOTED', kind='unit_test', backlog_id='Q1', feedback=[]),
    }}
    return st


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.
