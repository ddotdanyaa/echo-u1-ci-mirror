# factory-backlog-id: E87-1-roles-one-function
from echo_sync.fast_text import roles_around

def test_roles_around_docstring():
    heard = "было 80 рублей, потратил 20, сколько денег осталось"
    asked = "было 20 рублей, потратил 80, сколько денег осталось"
    assert roles_around(heard, asked)
