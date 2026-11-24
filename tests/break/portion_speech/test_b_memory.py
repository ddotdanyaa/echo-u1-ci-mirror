"""U237 break, family «память»: the phone has one session id, the owner comes back after minutes, a day, two days.
The windows are CONVERSATION_GAP_S (600 s: the same conversation) and CONVERSATION_CARRY_S (36 h: the explicit «продолжай», the recap, the dictation said by voice).
Through the real ControlledMedia."""
import pytest

from bps_common import dictation
from echo_sync.controlled_media import ControlledMedia
from echo_sync.timer_policy import CONVERSATION_CARRY_S, CONVERSATION_GAP_S

MEMORY = {'conversation_ledger': 'memory', 'topic_recap': 'on'}


def test_b22_after_the_gap_a_redial_presents_nothing_by_itself_but_continue_goes_on_from_the_same_portion(tmp_path):
    a = dictation(tmp_path)
    a.say(a.current)
    index, portion = a.index, a.current
    a.clock.advance(CONVERSATION_GAP_S + 100)
    b = a.reconnect()
    for text in ('что?', 'а?', 'не понял', 'ну'):
        assert b.say(text).speaks == [], f'{text!r} presented the stored portion of an old call'
    out = b.say('Продолжай.')
    assert out.speaks == [portion] and out.after == index, out.actions
    assert out.model_calls == 0


@pytest.mark.parametrize('hours,resumes', [(20, True), (37, False)])
def test_b23_an_explicit_continue_reaches_back_a_day_and_not_beyond_the_carry(tmp_path, hours, resumes):
    assert 20 * 3600 < CONVERSATION_CARRY_S < 37 * 3600, 'precondition: the carry window is 36 h'
    a = dictation(tmp_path)
    a.say(a.current)
    portion = a.current
    a.clock.advance(hours * 3600)
    b = a.reconnect()
    out = b.say('Продолжай.')
    if resumes:
        assert out.speaks == [portion], out.actions
    else:
        assert portion not in out.speaks, f'a portion of an answer {hours} h old was spoken as if it were fresh'
        assert out.types[:2] == ['cancel', 'route'], f'«продолжай» with nothing to resume goes to the model as a question: {out.types}'


def answered(c, tid, question, answer):
    c.provider({'type': 'turn.done', 'turn': {'id': tid, 'role': 'user', 'transcript': question}})
    c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'source'}])
    acts = c.provider({'type': 'turn.done', 'turn': {'id': 'a' + tid, 'role': 'assistant', 'transcript': getattr(c, 'answer_marker', '') + answer}})
    cue = next(x for x in acts if isinstance(x, dict) and x.get('text'))
    c._cue_event('began', cue, c.clock())
    c._cue_event('done', cue, c.clock() + 1.0)


@pytest.mark.parametrize('hours,carried', [(2, True), (20, True), (40, False)])
def test_b24_the_recap_of_earlier_calls_reaches_back_a_day_and_a_half_and_no_further(tmp_path, hours, carried):
    t = [1_794_000_000.0]

    def controller():
        c = ControlledMedia(tmp_path / 's.db', session_id='s', settings=MEMORY, clock=lambda: t[0] - 1_793_000_000.0)
        c.engine.clock = lambda: t[0]
        c.begin_call()
        return c
    first = controller()
    answered(first, 'u0', 'Почему меняются времена года?', 'Наклон земной оси меняет освещение.')
    t[0] += hours * 3600.0
    call = controller()
    carry = call.fast_carry()
    assert ('времена года' in carry) == carried, f'{hours} h later the recap of the earlier call is {carry!r}'


def test_b25_dictation_said_by_voice_goes_on_over_a_redial_and_ends_with_the_carry(tmp_path):
    a = dictation(tmp_path)
    a.say('Диктуй медленно.')
    assert a.controller.dictation, 'precondition: the owner said it, the mode is on'
    a.clock.advance(CONVERSATION_GAP_S + 100)
    assert a.reconnect().controller.dictation, 'a redial after ten minutes forgot that the owner is writing'
    a.clock.advance(CONVERSATION_CARRY_S + 100)
    assert not a.reconnect().controller.dictation, 'dictation said two days ago is still on'
