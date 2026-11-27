# factory-backlog-id: E20
from echo_sync.materials import parse_topic

def test_roles_parsing():
    text = """
    Предмет: История России
    Роли: выступающий, слушатель, коллега, аудитория, перебивающий человек
    Стиль: Официальный
    """
    result = parse_topic(text)
    # The requirement E20 introduces 'Роли' as a specific field.
    # Currently, parse_topic likely doesn't have 'roles' in _FIELD_NAMES.
    assert result.get('roles') == "выступающий, слушатель, коллега, аудитория, перебивающий человек"
