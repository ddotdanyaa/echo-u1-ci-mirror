"""U237 breakD, class «the shape of what the owner says»: an English remark (К28), a very long question, the same phrase twice in a row, a break-in over a cue that is being voiced, two voices at once.
Through the real ControlledMedia (helpers_s6_ack.Dictation). Red = a defect found; the assertions stay."""
import pytest

import helpers_s6_ack as H
from bw_common import SIDE_ANSWER, silence, speaks, waiting

ENGLISH = ['Okay so the next thing we will see is friction', 'yeah yeah right thank you very much', 'Wait, is it really that simple?',
           'окей сой зе некст синг ви вил си из фрикшн', 'сенк ю вери мач ай си', 'вот из зе фоурс']


@pytest.mark.parametrize('remark', ENGLISH)
def test_w11_an_english_remark_over_a_waiting_portion_does_not_reset_the_answer(tmp_path, remark):
    """К28: the Russian ear hears English as Cyrillic noise («что наводит финансия») and the answer was dropped for it."""
    d = waiting(tmp_path)
    index, plan = d.index, d.chunks
    out = d.say(remark)
    assert out.after == index and d.chunks == plan, f'{remark!r} moved or replaced the answer'
    assert not out.destroyed, f'{remark!r} cancelled the answer in play and started a new question: {out.types}'
    assert d.say(d.current).after == index + 1, f'after {remark!r} the owner\'s repeat no longer counts'


def test_w12_a_question_of_six_hundred_words_is_one_question_and_one_answer(tmp_path):
    d = waiting(tmp_path)
    long_question = 'Расскажи пожалуйста ' + ' '.join(['про трение и вес тела и массу и силу тяжести на Луне'] * 60) + ' что это такое?'
    out = d.say(long_question)
    assert out.types[:2] == ['cancel', 'route'], f'a long question was not taken as a question: {out.types}'
    assert out.types.count('route') == 1, f'a long question made {out.types.count("route")} routes'
    fresh = d.deliver(H.done('a-long', 'assistant', SIDE_ANSWER))
    assert len(speaks(fresh.actions)) == 1, f'the answer to a long question was said {len(speaks(fresh.actions))} times'


def test_w13_twenty_thousand_characters_without_a_stop_are_not_a_crash_and_leave_the_call_alive(tmp_path):
    d = waiting(tmp_path)
    index = d.index
    out = d.say('слово ' * 3500)                        # the recognizer never closed the phrase
    assert out.types.count('route') <= 1 and out.after in (index, index + 1)
    assert d.controller.state() is not None
    d.deliver(H.done('a-after', 'assistant', SIDE_ANSWER))
    alive = d.say('Что такое вес тела')
    assert alive.types[:2] == ['cancel', 'route'], f'the call is dead after a very long turn: {alive.types}'


def test_w14_the_portion_said_twice_in_one_breath_moves_one_not_two(tmp_path):
    d = waiting(tmp_path)
    index = d.index
    out = d.say(d.current + ' ' + d.current)
    assert out.after == index + 1, f'the portion said twice in one turn moved the cursor to {out.after} (from {index})'


def test_w15_the_old_portion_repeated_a_second_time_a_moment_later_is_no_progress(tmp_path):
    d = waiting(tmp_path)
    index, old = d.index, d.current
    assert d.say(old).after == index + 1
    out = d.say(old, gap=0.8)                           # the owner says it again, the portion is already behind
    assert out.after == index + 1, f'the already confirmed portion was counted twice (cursor {out.after})'
    assert not out.destroyed and out.model_calls == 0, out.types


def test_w16_next_said_three_times_in_one_turn_is_one_command(tmp_path):
    d = waiting(tmp_path, confirmed=0)
    index = d.index
    out = d.say('Дальше. Дальше. Дальше.')
    assert out.after == index + 1, f'«дальше» three times in one breath moved the cursor to {out.after}'


def test_w17_a_break_in_over_the_cue_that_is_being_voiced_then_silence_never_skips_ahead(tmp_path):
    d = waiting(tmp_path)
    index, plan = d.index, d.chunks
    cue = d.say(d.current, play=False)                  # the next portion is being voiced (not yet reported finished)
    assert cue.speaks, cue.actions
    index = d.index
    d.say('Подожди, а', gap=1.0)                        # the owner breaks in with half a phrase and says nothing more
    d.clock.advance(1.0)
    d.controller.playback_done(next(a for a in cue.actions if a['type'] == 'speak'), now=d.clock())     # the transport reports the end of the cue it cut, late
    later = silence(d, 120, step=2.0)
    assert d.index == index and d.chunks == plan, 'silence after a break-in moved the answer'
    assert set(later) <= {plan[index]}, f'after the break-in the app said a portion that was not waiting: {later}'


def test_w18_two_voices_at_once_the_foreign_turn_does_not_swallow_the_owners_repeat(tmp_path):
    d = waiting(tmp_path)
    index = d.index
    d.clock.advance(4.0)
    d.controller.speech_started()
    outs = [d.deliver(H.created('own', 'user', '')), d.deliver(H.created('other', 'user', '')),
            d.deliver(H.done('other', 'user', 'А ты вчера видел футбол')), d.deliver(H.done('own', 'user', d.current))]
    assert not any(o.destroyed for o in outs), f'a foreign voice over the owner\'s repeat cancelled the answer: {[o.types for o in outs]}'
    assert d.index == index + 1, f'the owner\'s repeat was lost under the second voice (cursor {d.index})'
