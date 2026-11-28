"""V4 E65: the small things of the delay. B3: the ear's text wakes the loop at once (no wait for the tick); B4: the first cue is released at the exact time of its gate, not on the tick after it. B5, B11, B12 are
deferred in the backlog «measure after E05.1»: nothing of them is asserted here.

Real ControlledMedia, NativeMediaSocket, ShadowEar and FastText (rig ``call``, the ear's wake and the release time as the host sets them). Not run on the laptop; none of this is a measurement of a call. A red test is a defect
card for the family T (the terms) or R (the road).
"""
import pytest

from portion_kit import EAR_RELEASE_SILENCE_SECONDS, TICK, asked, call      # noqa: F401 - call is the fixture

WIDE = {'fast_text': 'on', 'prepare_wide': 'on'}      # needs the ear, so with the ear's tempo


def test_b3_the_ears_text_is_taken_before_the_next_tick(call):
    rig = call(**WIDE)
    rig.ear.wake = lambda: rig.w.loop.call_soon(rig.w.wire.ear_wake)
    uid = rig.onset()
    rig.pump(1.5)
    rig.offset()
    rig.w.clock.advance(0.03)
    rig.worker.heard(uid, 'амортизация основных средств')
    rig.w.settle()
    assert rig.fast.count == 1, 'the job went with no tick between the text and the start'


def test_b3_a_wake_and_a_tick_take_one_text_once(call):
    rig = call(**WIDE)
    rig.ear.wake = lambda: rig.w.loop.call_soon(rig.w.wire.ear_wake)
    uid = rig.onset()
    rig.pump(1.5)
    rig.offset()
    rig.worker.heard(uid, 'амортизация основных средств')
    rig.pump(TICK * 3)
    assert rig.fast.count == 1


def test_b4_the_first_cue_is_released_at_the_time_of_its_gate_not_on_the_tick_after(call):
    rig = call(fast_text='on', prepare_wide='on')
    rig.c.prepared_job = None      # rule 2 off: the key ear_release is deleted (f84a05a9); the controller has no look at the job prepared on the ear's text
    # A command, so no lead (question_lead: a command has none). Since f84a05a9 (lead_cue is a rule of fast_text, no key) «что такое инерция» gets its lead «Инерция —» at once, the job's text after it is no
    # first cue and the gate of the first cue (B4) is not what holds it; here the job's text is the first cue.
    asked(rig, 'объясни что такое инерция')
    uid = rig.onset()
    rig.pump(1.0)
    ended = rig.offset()
    rig.worker.heard(uid, 'э-э')
    rig.pump(TICK)
    times = []
    wire = rig.w.wire
    wire._release_at = times.append
    rig.job_says(0, 'Инерция — свойство тела сохранять скорость.')
    rig.job_ends(0)
    assert times and times[-1] == pytest.approx(ended + EAR_RELEASE_SILENCE_SECONDS), 'the exact time of the gate is asked for'
    assert rig.said() == []
    rig.w.clock.t = ended + EAR_RELEASE_SILENCE_SECONDS + 1e-6
    rig.w.run(wire._release_pending())
    rig.w.settle()
    assert rig.said() == ['Инерция — свойство тела сохранять скорость.'], 'said with no tick in between'
