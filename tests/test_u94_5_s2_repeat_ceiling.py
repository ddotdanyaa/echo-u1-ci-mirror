# factory-backlog-id: U94.5.s2
import pytest
from echo_sync.cm_timers import TimersMixin

class MockState:
    def __init__(self):
        self.position = 10

class TestTimersMixin(TimersMixin):
    def __init__(self):
        self._clock_val = 0
        self._repeat_at = None
        self._auto_repeats = 0
        self.unconfirmed_repeats = 0
        self._state = MockState()

    def clock(self):
        return self._clock_val

    def _position(self, state):
        return state.position

    def _cue_playing(self, clock):
        return False

    def state(self):
        return self._state

    @property
    def repeat_at(self):
        return self._repeat_at

    @repeat_at.setter
    def repeat_at(self, val):
        self._repeat_at = val

    @property
    def auto_repeats(self):
        return self._auto_repeats

    @auto_repeats.setter
    def auto_repeats(self, val):
        self._auto_repeats = val

    def _arm(self, at):
        self._repeat_at = at

def test_repeat_ceiling_enforcement():
    tm = TestTimersMixin()
    tm.auto_repeats = 1
    tm.unconfirmed_repeats = 0
    
    # First arming (allowed)
    tm._tempo_arm(100)
    assert tm.repeat_at == 100
    
    # Simulate repeat happening
    tm.unconfirmed_repeats = 1
    
    # Second arming attempt (should be blocked by ceiling)
    tm._tempo_arm(200)
    assert tm.repeat_at == 100  # Should NOT have changed to 200
