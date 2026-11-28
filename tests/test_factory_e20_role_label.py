# factory-backlog-id: E20
from echo_sync.materials import parse_topic

def test_roles_label():
    text = "Роли: выступающий, слушатель, коллега, аудитория, перебивающий человек"
    result = parse_topic(text)
    assert result.get('audience') == 'выступающий, слушатель, коллега, аудитория, перебивающий человек'
