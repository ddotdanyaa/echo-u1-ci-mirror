# factory-backlog-id: E44.s2
import pytest
from echo_sync.cm_kind import KindMixin, ACK, QUIET, QUESTION

class Context:
    def __init__(self, text, state, decision_kind, tail=False, utterance=False):
        self.text = text
        self.state = state
        self.decision_kind = decision_kind
        self.tail = tail
        self.utterance = utterance
        self.disputed = False
        self.ruling = None

    @property
    def decision(self):
        class Decision:
            pass
        d = Decision()
        d.kind = self.decision_kind
        return d

class MockKind(KindMixin):
    def _disputes(self, text, state):
        return 'waiting_portion' in state

    def _ruled(self, c, kind, reason, val, tag):
        c.ruling = (kind, reason)

def test_dispute_routing_question():
    km = MockKind()
    c = Context(
        text='Are you sure about that?',
        state={'waiting_portion': 'some text'},
        decision_kind=QUESTION
    )
    
    km._rule_dispute(c)
    
    assert c.disputed is True
    assert c.ruling == (QUIET, 'dispute_of_the_portion')