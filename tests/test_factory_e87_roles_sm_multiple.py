# factory-backlog-id: E87-roles-sm
from echo_sync.search_identity import _ends

def test_ends_multiple_roles():
    # "из Москвы в Москву" -> 'москва' has both 'from' and 'to' roles.
    # The current implementation uses setdefault, so it only keeps the first one.
    roles = _ends("из Москвы в Москву")
    assert roles['москва'] == {'from', 'to'}
