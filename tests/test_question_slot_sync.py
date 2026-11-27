# factory-backlog-id: U94.s1
import pytest
from echo_sync.cm_question import QuestionSlot

def test_question_slot_close_sync():
    slot = QuestionSlot()
    slot.values = {'a': 1, 'b': 2}
    slot.epoch = 1
    slot.close()
    assert slot.values == slot.CLOSED
    assert slot.epoch == 2