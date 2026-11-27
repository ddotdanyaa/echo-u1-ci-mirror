# factory-backlog-id: U144.s2
from echo_sync.repeat_rule import silence, Silence

class MockPace:
    def __init__(self, wait_val):
        self.wait_val = wait_val
        self.seen = False

    def wait(self, portion, current_wait):
        return max(current_wait, self.wait_val)

def test_dictation_silence_and_half_portion_unification():
    # Setup: half-portion active (pace.wait is high), but not yet 'seen' or 'recording'
    # The defect is that in silence(), if cycling=True, pace.wait is only called 
    # if (pace.seen or recording).
    pace = MockPace(wait_val=10.0)
    
    # We expect the silence wait to be at least the pace.wait value (10.0)
    # even if recording=False and pace.seen=False, to unify the rules.
    res = silence(
        repeats=0, 
        cycling=True, 
        tools=True, 
        pace=pace, 
        portion="test_portion", 
        recording=False
    )
    
    # res is a Silence object: Silence((count, cap, why, wait, cycling))
    # Access the wait time directly from the Silence tuple
    actual_wait = res[3]
    
    # On current code, this will be cycle_wait(0) (likely 3.0 or 5.0), not 10.0,
    # because pace.seen is False and recording is False.
    assert actual_wait == 10.0, f"Expected wait to be unified with pace.wait (10.0), but got {actual_wait}"
