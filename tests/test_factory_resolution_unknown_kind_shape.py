# factory-backlog-id: rel-c26b5822-4 
from echo_sync.utterance_judge import Resolutions


def test_unknown_kind_record_has_full_shape():
    res = Resolutions()
    rec, outcome = res.resolve('t1', resolution='ASSERT', rule='r1', reason='why', onset=1.5, revision=3, going='plan', authority='a')
    assert outcome == 'unknown_kind'
    assert rec.get('rule') == 'r1'
    assert rec.get('reason') == 'why'
    assert rec.get('onset') == 1.5
    assert rec.get('revision') == 3
    assert rec.get('going') == 'plan'
    assert rec.get('decision_id') is None
    assert rec.get('supersedes') is None
    assert rec.get('authority') == 'a'
    assert res.unknown_kinds == 1
    assert res.records == {}
