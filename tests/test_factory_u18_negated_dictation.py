# factory-backlog-id: U18
from echo_sync.repeat_rule import dictation_command

def test_negated_dictation_phrases():
    assert dictation_command('Я не буду записывать') == 'off'
    assert dictation_command('не диктуй медленно') == 'off'
    assert dictation_command('я буду записывать') == 'on'
