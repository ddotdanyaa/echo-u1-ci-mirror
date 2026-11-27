# factory-backlog-id: U117.s1
import pytest
from echo_sync.utterance_judge import _method

class DummyCMForMissingRuleTest:
    pass

class DummyCtx:
    def __init__(self, cm):
        self.cm = cm

def test_missing_rule_raises_descriptive_error():
    """Tests that _method raises a RuntimeError with descriptive context when the rule is missing."""
    row_fn = _method('nonexistent_rule')
    ctx = DummyCtx(DummyCMForMissingRuleTest())
    
    # The current implementation (defective) raises AttributeError: 'DummyCMForMissingRuleTest' object has no attribute '_rule_nonexistent_rule'
    # The requirement is to raise RuntimeError containing both names.
    with pytest.raises(RuntimeError) as exc_info:
        row_fn(ctx)
    
    err_msg = str(exc_info.value)
    assert 'nonexistent_rule' in err_msg
    assert 'DummyCMForMissingRuleTest' in err_msg
