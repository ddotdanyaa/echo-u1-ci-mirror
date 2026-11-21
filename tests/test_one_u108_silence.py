"""one-input U108 (2): the word of the owner was heard and the portion matched: the next portion is given no later than ``OWNER_SILENCE_S`` of owner silence (no words), though the detector keeps saying «speech» (a cough, a breath, a stuck onset).
Through the real controller on the injected clock (the Rig of ``test_h3_tempo``). Nothing here is a measurement of the laptop or the phone."""
import pytest

from echo_sync.timer_policy import OWNER_SILENCE_S
from test_h3_tempo import GRID, TICK, call  # noqa: F401 - the fixture


def matched_then_a_stuck_onset(rig):
    """The owner says the portion back (the ear's text arrives late), and a second onset with no end and no words opens before it: the match is made while the detector says «speech»."""
    rig.first_portion()
    head = rig.next_cue(4)
    rig.pump(2.0)
    uid = rig.onset()
    rig.pump(0.5)
    rig.offset()
    rig.pump(0.1)
    rig.onset()
    rig.pump(TICK)
    matched = rig.w.clock.t
    words = head.text.rstrip('.,;:').split()
    rig.worker.heard(uid, ' '.join(words[1:] if len(words) > 2 else words))      # one word of it lost, as the owner says it back
    rig.pump(TICK)
    return head, matched


def test_the_constant_is_a_number_of_seconds_in_the_policy_not_a_settings_key():
    from echo_sync import settings
    assert 1.0 <= OWNER_SILENCE_S <= 8.0 and 'owner_silence' not in ' '.join(settings.DEFAULTS)


def test_the_next_portion_is_given_within_the_owner_silence_after_a_matched_word(call):
    rig = call(max_auto_repeats=3)
    head, matched = matched_then_a_stuck_onset(rig)
    cue = rig.next_cue(OWNER_SILENCE_S + 1.0)
    assert cue is not None and cue.text != head.text, rig.said()
    assert rig.w.clock.t - matched <= OWNER_SILENCE_S + 1.0 + GRID


def test_a_word_after_the_match_holds_the_portion_back(call):
    rig = call(max_auto_repeats=3)
    head, matched = matched_then_a_stuck_onset(rig)
    rig.worker.heard(rig.ear.current, 'так вот я хотел сказать')      # the owner goes on speaking: his words are no silence
    cue = rig.next_cue(OWNER_SILENCE_S - 0.5)
    assert cue is None or cue.text == head.text


# -- (5): a complaint with no question does not drop the answer plan already begun (a judge rule: ``remark_form``) ------------------------------------------------------------------------------
import helpers_night_memory as M      # noqa: E402

ANSWER = 'Первая часть ответа про инерцию. Вторая часть ответа про силу. Третья часть ответа про массу.'
COMPLAINTS = ['ну опять ты не то говоришь', 'ты опять говоришь не то', 'ты меня не слушаешь', 'ты несёшь чушь', 'это никуда не годится', 'опять не то', 'мне это не нравится',
              'как же ты надоел', 'ну сколько можно', 'ну что за ерунда', 'что ты несёшь']      # «зачем ты это повторяешь» asks something: not here


@pytest.fixture
def stand(tmp_path):
    calls = []

    def build():
        calls.append(M.Call(tmp_path / f'c{len(calls)}', mind=lambda request: ANSWER, fast_text='on'))
        return calls[-1]
    yield build
    for call in calls:
        call.close()


@pytest.mark.parametrize('remark', COMPLAINTS)
def test_a_complaint_with_no_question_keeps_the_plan(stand, remark):
    call = stand()
    call.say('Что такое инерция?')
    call.pump(1.0)
    state = call.c.state()
    call.say(remark)
    call.pump(2.0)
    after = call.c.state()
    assert after['revision'] == state['revision'] and after['chunk_index'] >= state['chunk_index'], (state, after)
