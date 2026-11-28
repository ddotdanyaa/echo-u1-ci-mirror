# factory-backlog-id: U94.s1
from echo_sync.cm_question import QuestionSlot


def test_bare_close_is_the_full_closing_and_named_close_stays_partial():
    slot = QuestionSlot()
    ticket = slot.open(question_id='q1', grounded=True, candidate={'id': 1}, held_source='src')
    assert slot.version == 1
    assert not slot.stale(ticket)
    slot.close()
    for name, value in QuestionSlot.CLOSED.items():
        assert slot.values[name] == value, name
    assert slot.values['question_id'] is None
    assert slot.version == 2
    assert slot.stale(ticket)

    other = QuestionSlot()
    other_ticket = other.open(question_id='q1', grounded=True, candidate={'id': 1})
    other.close('grounded')
    assert other.values['grounded'] is False
    assert other.values['candidate'] == {'id': 1}
    assert other.values['question_id'] == 'q1'
    assert other.version == 1
    assert not other.stale(other_ticket)
