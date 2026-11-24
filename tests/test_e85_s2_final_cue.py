# factory-backlog-id: E85.s2
from unittest.mock import MagicMock
from echo_sync.cm_answer import AnswerMixin


class DummyAnswer(AnswerMixin):
    def __init__(self):
        self.settled_segment = None
        self.unsettled = None
        self.source_calls = []

    def state(self):
        return {}

    def _source(self, turn, settled=False, final=False):
        self.source_calls.append((turn, settled, final))
        return "sourced"


def test_end_declared_passes_final_true():
    da = DummyAnswer()
    turn = {"id": 123}
    da._end_declared(turn, reason="test")
    assert len(da.source_calls) == 1
    _, settled, final = da.source_calls[0]
    assert settled is True
    assert final is True
