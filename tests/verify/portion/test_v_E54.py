"""V4 E54: the prompt at a stumble about 2-3 s (the owner: «6-7 с очень плохо»); the tempo of the ear back in the profile. Backlog: on the profile in force the wait of the repeat was 6.0 s; the target 2-3 s,
0 repeats before his speech began.

Real ControlledMedia over a job's answer (rig ``call`` with the working profile) and over the reference plan. Not run on the laptop. A red test is a defect card for the family T (the terms).
"""
from portion_kit import GRID, LIVE_RULES, PORTION, call, plan      # noqa: F401 - call is the fixture


def test_the_silence_after_a_portion_of_a_job_brings_it_back_within_three_seconds(call):
    rig = call(**LIVE_RULES)
    end = plan(rig)
    count = len(rig.said())
    cue = rig.next_cue(3.5)
    assert cue is not None and len(rig.said()) == count + 1, rig.said()
    assert 2.0 - GRID <= cue.t - end <= 3.0, f'the prompt came {cue.t - end:.2f} s after the end of the portion'


def test_the_silence_after_the_reference_portion_brings_it_back_within_three_seconds(call):
    rig = call()
    rig.second_portion()
    end = rig.ended()
    cue = rig.next_cue(3.5)
    assert cue is not None and cue.text == PORTION and 2.0 - GRID <= cue.t - end <= 3.0


def test_no_prompt_comes_before_his_speech_began_in_the_wait(call):
    rig = call(**LIVE_RULES)
    plan(rig)
    count = len(rig.said())
    rig.pump(1.5)
    rig.onset()
    rig.pump(3.0)
    assert len(rig.said()) == count, rig.said()
