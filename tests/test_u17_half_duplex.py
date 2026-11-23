"""U17: a half-duplex phone (no microphone packets while a cue sounds) hears nothing of what the system says over its own cue, so the same portion is not said blindly more than HALF_DUPLEX_REPEATS times in a row.
Through the controller: the packets are fed by the test the way the transport feeds them (``mic_packet``), the cue events come from the real cues; the profile is the defaults (no ``input_state`` key)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync import call_trace      # noqa: E402
from test_h3_tempo import call      # noqa: E402,F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of      # noqa: E402


def run(rig, seconds, packets=True, step=0.1):
    """The line goes on ``seconds``: a packet of 100 ms every step, none while a cue sounds (half duplex), none at all with ``packets`` False."""
    c, end = rig.c, rig.w.clock.t + seconds
    while rig.w.clock.t < end:
        if packets and rig.w.open is None:
            c.mic_packet(4800, -40.0, now=rig.w.clock.t)
        rig.pump(step)


def test_half_duplex_says_the_same_portion_at_most_twice_in_a_row(call, monkeypatch):
    monkeypatch.setattr(call_trace, 'DUPLEX_MIN_CUE_S', 0.4)      # the rig's cues are 0.5 s of synthetic sound, a real one is 2-4 s: the verdict needs 2 s of cue time
    rig = rig_of(call, max_auto_repeats=4)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    run(rig, 90.0)
    assert rig.c.input_probe.duplex(rig.w.clock.t) == 'half', 'precondition: the meter saw a half-duplex line'
    said = rig.said()
    assert said[0] == P1 and said.count(P1) - 1 <= 2, said


def test_only_a_half_duplex_line_lowers_the_cap():
    from echo_sync.repeat_rule import repeat_cap
    args = dict(cycling=False, recording=False, unplaced=False, cycle_max_repeats=15, max_auto_repeats=4)
    assert [repeat_cap(**args, duplex=d) for d in ('full', 'unknown')] == [(4, 'plain')] * 2
    assert repeat_cap(**args, duplex='half') == (2, 'half')
    assert repeat_cap(**{**args, 'unplaced': True}, duplex='half') == (2, 'half')
    assert repeat_cap(**{**args, 'max_auto_repeats': 1}, duplex='half') == (1, 'plain'), 'never raised'
    assert repeat_cap(**{**args, 'cycling': True}, duplex='half') == (15, 'cycle'), 'K6: the owner\'s pen stands'


import pytest as _pytest_mic  # noqa: E402


@_pytest_mic.fixture(autouse=True)
def _own_microphone(monkeypatch):
    """This file feeds its own microphone packets (or none: a lost line): the live line of the world stays off (helpers_live_line)."""
    import helpers_s6_state
    monkeypatch.setattr(helpers_s6_state.World, 'mic_stream', False)
