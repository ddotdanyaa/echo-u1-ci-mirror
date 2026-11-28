# factory-backlog-id: rel-base-w5-lead-off
import pytest
from echo_sync.utterance_judge import followup_lead
from echo_sync.classifier import QUIET, Decision

def test_followup_lead_identifies_valid_followup():
    # Mocking the context object 'c' as expected by followup_lead
    class MockContext:
        def __init__(self):
            self.tail = None
            self.utterance = None
            self.text = 'Как у тебя'
            self.decision = Decision(QUIET, 'mismatch_policy_silent', None, None)
            self.state = {'history': [{'text': 'Как дела?'}]}

    c = MockContext()
    
    # The current implementation requires 'а' or 'и' as a lead.
    # 'Как у тебя' does not start with these, so it returns None.
    # We expect it to return a QUESTION verdict.
    result = followup_lead(c)
    
    assert result is not None, "Expected a QUESTION verdict, but got None"
    assert result.kind == 'QUESTION'
