# factory-backlog-id: E868.s2
import pytest
from echo_sync.cm_answer import AnswerMixin

class MockAnswerMixin(AnswerMixin):
    def __init__(self, fast_call=False, public_lookup_allowed_val=True, state_dict=None):
        self.fast_call = fast_call
        self.public_lookup_allowed_val = public_lookup_allowed_val
        self._state_dict = state_dict or {"history": ()}

    def state(self):
        return self._state_dict

    def public_lookup_allowed(self, asked):
        return self.public_lookup_allowed_val

def test_remark_is_not_fast_routed():
    # Setup: fast_call is True.
    # Current logic: (self.fast_call or self.public_lookup_allowed(asked)) and not route_need(asked, history)
    # For "Спасибо", route_need is typically False, so it returns True.
    # It should return False because "Спасибо" is a remark.
    mixin = MockAnswerMixin(fast_call=True, public_lookup_allowed_val=True)
    asked = "Спасибо"
    
    # This fails on current code because it returns True
    assert mixin._fast_routed(asked) is False
