"""V4 E77: help at a stumble within 1-2 s and only the tail; the whole portion went back after 15.4 s (call 10:27). Backlog: replay with the tempo: only what is missing, up to 1.2 s; the wait of the repeat 2.0 s
instead of 3.5, and the repeat does not come before his speech began.

Real ControlledMedia, NativeMediaSocket, ShadowEar (rig ``call``, whose defaults are the ear in act and the tempo of the ear). Not run on the laptop. A red test is a defect card for the family T (the terms).
"""
import pytest

from portion_kit import GRID, HEAD, LIVE_RULES, PORTION, REST, TEMPO_REPEAT_SECONDS, TEMPO_START_SECONDS, TICK, call, plan      # noqa: F401 - call is the fixture


def test_a_start_that_stopped_gets_only_the_tail_within_the_start_wait(call):
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    ended = rig.says('общие', speech=1.2)
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == REST, f'only what is missing: {rig.said()}'
    assert cue.t - ended <= 1.2 + GRID and TEMPO_START_SECONDS <= 1.2


def test_the_silence_brings_the_whole_portion_after_the_wait_of_the_tempo_not_after_fifteen_seconds(call):
    rig = call()
    rig.second_portion()
    end = rig.ended()
    cue = rig.next_cue(4)
    assert cue is not None and cue.text == PORTION and cue.t - end == pytest.approx(TEMPO_REPEAT_SECONDS, abs=GRID)
    assert TEMPO_REPEAT_SECONDS == 2.0


def test_the_repeat_never_comes_into_speech_that_began_within_the_wait(call):
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    rig.onset()
    rig.pump(4.0)               # speaking the whole time: no offset, the cue of the wait must not come into it
    assert rig.said() == [HEAD, PORTION], rig.said()


def test_the_same_holds_on_the_profile_of_the_working_call(call):
    rig = call(**LIVE_RULES)
    rig.second_portion()
    end = rig.ended()
    cue = rig.next_cue(4)
    assert cue is not None and cue.t - end <= 3.0, 'no wait of 6 s: the profile of the call keeps the wait of the tempo'
