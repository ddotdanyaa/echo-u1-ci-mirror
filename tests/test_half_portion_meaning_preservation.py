# factory-backlog-id: U144.s1
import asyncio
from unittest.mock import MagicMock, patch

from echo_sync.cm_kind import KindMixin, QUIET, REPLAY


class MockState(dict):
    def __init__(self):
        super().__init__()
        self['paused'] = False


class MockCue:
    def __init__(self, kind):
        self.decision = MagicMock(kind=kind)
        self.state = MockState()
        self.text = "some text"
        self.disputed = False


class MockMixin(KindMixin):
    def __init__(self):
        self.tempo_live = True
        self.cue_window = [10, 20]
        self.tempo_began = 5  # Before cue window
        self.tempo_began_at = 15
        self.dictation = False
        self.go_on = None
        self.settings = MagicMock()

    def _position(self, state):
        return 15

    def _tempo_over(self, began):
        return False

    def _started(self, text, portion):
        return False

    def _tempo_verdict(self, text):
        return 'next'

    def _disputes(self, text, state):
        return False

    def _ruled(self, c, k, r, t, d):
        pass


def test_half_portion_meaning_preservation():
    """
    When speech began before the cue (before=True), a help/replay decision
    must not update self.go_on, preserving the existing speech context.
    """
    mixin = MockMixin()
    cue = MockCue(REPLAY)

    # Patch the external functions used by _rule_tempo_help where they are imported in cm_kind
    with patch('echo_sync.cm_kind.probe') as mock_probe, \
         patch('echo_sync.cm_kind.landmark_command') as mock_landmark, \
         patch('echo_sync.cm_kind.most_said') as mock_most_said, \
         patch('echo_sync.cm_kind.ends_like') as mock_ends_like, \
         patch('echo_sync.cm_kind.rule_verdict') as mock_rule_verdict:

        # Configure probe to return a mock with .value for 'strip_fillers' and 'waiting_portion'
        mock_strip = MagicMock()
        mock_strip.value = 'some text'
        mock_waiting = MagicMock()
        mock_waiting.value = 'waiting portion text'
        mock_probe.side_effect = lambda *args, **kwargs: mock_strip if args and args[0] == 'strip_fillers' else mock_waiting

        mock_landmark.return_value = False
        mock_most_said.return_value = True
        mock_ends_like.return_value = False
        mock_rule_verdict.return_value = 'next'

        mixin._rule_tempo_help(cue)

        # If 'before' is true, self.go_on should NOT be set.
        assert mixin.go_on is None, f"Expected go_on to remain None when before=True, got {mixin.go_on}"
