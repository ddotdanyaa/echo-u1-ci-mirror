# factory-backlog-id: U18
from echo_sync.repeat_rule import dictation_command


def test_not_going_to_write_does_not_turn_dictation_on():
    # This should return 'off' as the user explicitly negates the intention to record.
    # Currently it returns 'on' because 'буду' and 'записывать' are in _ON.
    assert dictation_command('я не буду записывать') == 'off'
