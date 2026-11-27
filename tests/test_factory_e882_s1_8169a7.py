# factory-backlog-id: E882.s1
from echo_sync.user_intents import disagreement

def test_semantic_dissent():
    assert disagreement('неправильно') == (True, None)
    assert disagreement('нет') == (True, None)
    assert disagreement('не так') == (True, None)
