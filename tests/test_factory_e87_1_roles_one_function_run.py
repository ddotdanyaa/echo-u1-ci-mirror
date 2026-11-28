# factory-backlog-id: E87-1-roles-one-function
from echo_sync.fast_text import roles_around

def test_roles_around_run_continuity():
    # Testing if roles are correctly identified when the "run" of words around numbers is slightly different
    # but the core roles (numbers and their units/context) are preserved.
    heard = "было 80 рублей, потратил 20"
    asked = "80 рублей и 20"
    # In 'heard', the roles for 80 are (80, 'рублей', {'было'}) and for 20 are (20, None, {'потратил'})
    # In 'asked', the roles for 80 are (80, 'рублей', set()) and for 20 are (20, None, {'и'})
    # The roles_around should return True if the roles of 'asked' are within 'heard' or vice versa.
    # However, the 'since' set (the words since the previous number) might not match exactly.
    assert roles_around(heard, asked)
