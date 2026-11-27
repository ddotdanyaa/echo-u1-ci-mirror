"""U62 (family question, package Q): a TICKET is (question id, version of the slot); what an answer, a search or a sound was made for carries it, and the gate of the irreversible (``ControlledMedia._act``) reads it:
a decision whose basis holds the ticket of a question that is no longer the one standing is 'stale', whatever the reply token says (the token also moves for reasons that are not another question).
Real ControlledMedia: the second question is opened by the controller itself. Not run on the laptop."""
from echo_sync.controlled_media import ControlledMedia


def _final(c, uid, text):
    return c.provider({'type': 'turn.done', 'turn': {'id': uid, 'role': 'user', 'transcript': text}})


def test_a_basis_made_for_the_old_question_is_stale_once_another_is_open(tmp_path):
    c = ControlledMedia(tmp_path / 's.db', session_id='s', source_delivery='delegation')
    _final(c, 'u1', 'Почему меняются времена года?')
    assert c.question_id == 'u1'
    basis = c.act_basis()
    assert len(basis) == 4 and basis[3] == c.slot.ticket, 'the basis carries the ticket of the standing question'
    assert c._act_verdict('drop_question', basis) == 'do'
    _final(c, 'u2', 'Сколько будет сорок на два?')
    assert c.question_id == 'u2' and c.ticket_stale(basis[3]), 'another question stands: the old ticket is stale'
    only_the_ticket = (None, None, None, basis[3])
    assert c._act_verdict('drop_question', only_the_ticket) == 'stale', 'the gate reads the ticket, not only the token'
    assert c._act_verdict('drop_question', (None, None, None, c.slot.ticket)) == 'do'


def test_a_basis_without_a_ticket_is_judged_as_before(tmp_path):
    c = ControlledMedia(tmp_path / 's.db', session_id='s', source_delivery='delegation')
    _final(c, 'u1', 'Почему меняются времена года?')
    assert c._act_verdict('drop_question', (c.epoch, None, 'u1')) == 'do'
    assert c._act_verdict('drop_question', None) == 'do'
