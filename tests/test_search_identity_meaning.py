# factory-backlog-id: E872.s1
from echo_sync.search_identity import same_meaning

def test_same_meaning_distinguishes_cases():
    # Subject vs Object
    assert same_meaning('Кто убил Каина', 'Кого убил Каин') is False
    # Pronoun case
    assert same_meaning('Это мне', 'Это я') is False
    # Same meaning should still work
    assert same_meaning('Кто убил Каина', 'Кто убил Каина') is True