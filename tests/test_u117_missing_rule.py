# factory-backlog-id: U117.s1
from echo_sync.utterance_judge import _method


class DummyCMForMissingRuleTest:
    pass


class DummyCtx:
    def __init__(self, cm):
        self.cm = cm


def test_missing_rule_raises_descriptive_error():
    row_fn = _method('nonexistent_rule')
    ctx = DummyCtx(DummyCMForMissingRuleTest())
    caught = None
    try:
        row_fn(ctx)
    except Exception as e:
        caught = e
    expected = (
        "controller DummyCMForMissingRuleTest has no rule 'nonexistent_rule' "
        "(expected method _rule_nonexistent_rule)"
    )
    assert (type(caught), str(caught)) == (RuntimeError, expected)
