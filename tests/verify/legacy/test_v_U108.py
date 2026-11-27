"""V5 / U108: the owner's remarks of the call 13.11 08:11, on 980c85a0. Closed by the commits 45c97e40 (2: the next portion is given within OWNER_SILENCE_S of the owner's silence) and 0052d0e2 (5: a complaint
with no question keeps the plan); this is the guard of the other wording of the same rows. Through the real ControlledMedia (test_h3_tempo.Rig, helpers_night_memory.Call). Nothing here is a measurement of a call."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest  # noqa: E402

import helpers_night_memory as M  # noqa: E402
from echo_sync.timer_policy import OWNER_SILENCE_S  # noqa: E402
from test_h3_tempo import GRID, TICK, call  # noqa: E402,F401 - call is the fixture
from test_one_u108_silence import matched_then_a_stuck_onset  # noqa: E402

ANSWER = 'Первая часть ответа про инерцию. Вторая часть ответа про силу. Третья часть ответа про массу.'
OTHER_WORDS = ['что за чушь', 'что за бред', 'что за ахинея', 'что ты несешь', 'что ты несёшь', 'сколько можно', 'как же ты надоел']      # the forms of utterance_judge.COMPLAINT_FORMS in the other spelling


@pytest.mark.parametrize('extra', [1.0, 2.0])
def test_u108_2_the_next_portion_is_given_inside_the_silence_number_even_a_second_later(call, extra):
    rig = call(max_auto_repeats=3)
    head, matched = matched_then_a_stuck_onset(rig)
    cue = rig.next_cue(OWNER_SILENCE_S + extra)
    assert cue is not None and cue.text != head.text, rig.said()
    assert rig.w.clock.t - matched <= OWNER_SILENCE_S + extra + GRID, (rig.w.clock.t, matched)


@pytest.mark.parametrize('remark', OTHER_WORDS)
def test_u108_5_a_complaint_is_no_question_and_the_plan_begun_stays(tmp_path, remark):
    call = M.Call(tmp_path / 'c', mind=lambda request: ANSWER, fast_text='on')
    try:
        call.say('Что такое инерция?')
        call.pump(1.0)
        before = call.c.state()
        call.say(remark)
        call.pump(2.0)
        after = call.c.state()
        assert after['revision'] == before['revision'] and after['chunk_index'] >= before['chunk_index'], (before, after)
    finally:
        call.close()
