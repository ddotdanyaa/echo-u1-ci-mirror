# factory-backlog-id: W04
from echo_sync.utterance_judge import Resolutions

def is_revise_cause(cause):
    return cause in ["REVISE", "REVISE_KIND"]

def test_resolution_decisions_and_supersedes():
    res = Resolutions()
    # Using kinds that are likely in the registry or accepted by the logic
    kindA = "ASSERT"
    kindB = "QUERY"
    revise_cause = "REVISE"

    # First resolve('t1', resolution=kindA, rule='r1')
    rec1, outcome1 = res.resolve('t1', resolution=kindA, rule='r1')
    assert outcome1 == 'new'
    assert rec1['decision_id'] == 't1#1'
    assert rec1['supersedes'] is None
    assert rec1['authority'] == 'r1'

    # Second resolve with revise cause and rule='r2'
    rec2, outcome2 = res.resolve('t1', resolution=kindB, cause=revise_cause, rule='r2')
    assert outcome2 == 'revised'
    assert rec2['decision_id'] == 't1#2'
    assert rec2['supersedes'] == 't1#1'
    assert rec2['authority'] == 'r2'

    # Repeated identical revise call returns outcome 'same'
    rec3, outcome3 = res.resolve('t1', resolution=kindB, cause=revise_cause, rule='r2')
    assert outcome3 == 'same'
    assert rec3['decision_id'] == 't1#2'
    assert rec3['supersedes'] == 't1#1'

    # Different tid gets its own 'tX#1' with supersedes None
    rec_other, outcome_other = res.resolve('t2', resolution=kindA, rule='r1')
    assert outcome_other == 'new'
    assert rec_other['decision_id'] == 't2#1'
    assert rec_other['supersedes'] is None

    # authority= keyword passed explicitly overrides the rule
    rec_auth, outcome_auth = res.resolve('t3', resolution=kindA, rule='r1', authority='explicit_auth')
    assert outcome_auth == 'new'
    assert rec_auth['authority'] == 'explicit_auth'
