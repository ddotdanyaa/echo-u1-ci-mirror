# factory-backlog-id: W04
from echo_sync.utterance_judge import Resolutions, is_revise_cause
from echo_sync.reasons import KINDS, REVISE_CAUSES


def test_factory_resolution_decisions():
    res = Resolutions()
    kinds = sorted(KINDS)
    kind_a, kind_b = kinds[0], kinds[1]
    revise_cause = next(c for c in sorted(REVISE_CAUSES) if is_revise_cause(c))

    rec1, outcome1 = res.resolve('t1', resolution=kind_a, rule='r1')
    assert outcome1 == 'new'
    assert rec1.get('decision_id') == 't1#1'
    assert rec1.get('supersedes') is None
    assert rec1.get('authority') == 'r1'

    rec2, outcome2 = res.resolve('t1', resolution=kind_b, cause=revise_cause, rule='r2')
    assert outcome2 == 'revised'
    assert rec2.get('decision_id') == 't1#2'
    assert rec2.get('supersedes') == 't1#1'
    assert rec2.get('authority') == 'r2'

    rec3, outcome3 = res.resolve('t1', resolution=kind_b, cause=revise_cause, rule='r2')
    assert outcome3 == 'same'
    assert rec3.get('decision_id') == 't1#2'
    assert rec3.get('supersedes') == 't1#1'

    rec4, _ = res.resolve('t2', resolution=kind_a, rule='r1')
    assert rec4.get('decision_id') == 't2#1'
    assert rec4.get('supersedes') is None

    rec5, _ = res.resolve('t3', resolution=kind_a, rule='r1', authority='explicit')
    assert rec5.get('authority') == 'explicit'
