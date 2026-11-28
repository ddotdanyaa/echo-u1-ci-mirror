# factory-backlog-id: E882.s1
from echo_sync.user_intents import disagreement

def test_semantic_dissent():
    # The guard `if one_word and rest is None and start == 0 and subject is None: continue`
    # causes these simple dissent markers to return None instead of (True, None).
    assert disagreement('неправильно') == (True, None)
    assert disagreement('нет') == (True, None)
    assert disagreement('не так') == (True, None)
    assert disagreement('ну так') == (True, None)
