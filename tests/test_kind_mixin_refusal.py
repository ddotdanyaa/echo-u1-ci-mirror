# factory-backlog-id: E868.s1
import pytest
from unittest.mock import MagicMock
from echo_sync.cm_kind import KindMixin, REFUSAL


class MockCandidate:
    def __init__(self):
        self.data = {'id': 1, 'said': ''}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __setitem__(self, key, value):
        self.data[key] = value

    def __getitem__(self, key):
        return self.data[key]

    def pop(self, key, default=None):
        return self.data.pop(key, default)

    def update(self, d=(), **kwargs):
        self.data.update(d, **kwargs)


class KindMixinMock(KindMixin):
    def __init__(self):
        self.candidate = MockCandidate()
        self.state = MagicMock(return_value={})
        self._candidate_back = MagicMock(return_value=[])

    def _fast_verdict(self, turn):
        return False, []


def test_refusal_without_source_route_is_not_verdict():
    km = KindMixinMock()
    turn = (1, 'text')
    text = REFUSAL

    km._candidate_asks = MagicMock(return_value=False)

    result = km._fast_judged(turn, 'text', text)

    assert result[0] is False, "A refusal without a source route should not be judged as a verdict"
