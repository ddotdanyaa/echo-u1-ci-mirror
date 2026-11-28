# factory-backlog-id: E882.s1
from echo_sync.user_intents import disagreement

def test_semantic_disagreement_recognition():
    # 'некорректно' is a semantic synonym for dissent terms like 'неверно'
    # The system should identify this as disagreement even if not in a static list
    result = disagreement(['это', 'некорректно'])
    assert result is True, "Should recognize 'некорректно' as semantic dissent"
