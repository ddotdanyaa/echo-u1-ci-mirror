"""V4 E53: the next portion after a causal ACK within 0.5 s of its end (the «second ear» act). Backlog: a line of its own in the passport; the measure of 01.11 was 1259 ms, 96 % of it the wait for the
user's final of the cloud.

Real ControlledMedia, NativeMediaSocket, ShadowEar (rig ``call``): the ear confirms the whole repeat, the cloud's final of it never comes before the cue. Not run on the laptop: the number of the cloud is the
cloud's. A red test is a defect card for the family T (the terms) or P (flow_ahead).
"""
import helpers_s6_state as S
from portion_kit import CANDIDATE, GRID, HEAD, PORTION, TICK, call, rig_of      # noqa: F401 - call is the fixture


def test_the_ear_confirms_the_whole_repeat_and_the_next_portion_goes_within_half_a_second(call):
    rig = rig_of(call)
    rig.first_portion()
    rig.pump(0.5)
    rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created('u2', 'user', 'статья'))      # the cloud announces the turn; its final is never given in this scene
    rig.pump(0.6)
    uid = rig.ear.current
    ended = rig.offset()
    rig.pump(TICK)
    rig.worker.heard(uid, 'статья семнадцать налогового кодекса')
    cue = rig.next_cue(2)
    assert cue is not None and cue.text == PORTION, rig.said()
    assert cue.t - ended <= 0.5 + GRID, f'{cue.t - ended:.2f} s from the end of the repeat to the next portion'


def test_the_ear_alone_does_not_say_the_next_portion_over_another_utterance(call):
    rig = rig_of(call)
    rig.first_portion()
    rig.pump(0.5)
    rig.says('погода сегодня хорошая', speech=1.2)
    rig.pump(0.8)
    assert PORTION not in rig.said(), 'nothing is confirmed by words that are not the portion'
