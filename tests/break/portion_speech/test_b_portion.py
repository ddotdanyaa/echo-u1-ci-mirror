"""U237 break, family «порция»: how the owner kept breaking the portions (stumble and start again, «дальше» at the end, stop, a side question and back).
Through the real ControlledMedia (helpers_s6_ack.Dictation). Red = a defect found; the assertions stay."""
import pytest

import helpers_s6_ack as H
from bps_common import SIDE_ANSWER, STORY, dictation, finish, silence, speaks, words_of


def stumbled(words, form):
    k = 2
    if form == 'restart_from_start':
        return words[:k] + words                        # «инерция это инерция это свойство ...»
    if form == 'repeated_word':
        return words[:k] + [words[k - 1]] + words[k:]   # «инерция это это свойство ...»
    if form == 'hesitation_and_back':
        return words[:k] + ['э-э'] + words[k - 1:]      # «инерция это э-э это свойство ...»
    lead = words[0].lower()
    return [lead[:2] + '-' + lead] + words[1:]          # «ин-инерция это свойство ...»


@pytest.mark.parametrize('form', ['restart_from_start', 'repeated_word', 'hesitation_and_back', 'hyphen_stammer'])
def test_b01_a_stumble_and_a_restart_from_the_same_place_is_still_the_whole_portion(tmp_path, form):
    d = dictation(tmp_path)
    before, nxt = d.index, d.chunks[1]
    said = words_of(d.current)
    assert len(said) >= 3, 'precondition: a portion of at least three words'
    out = d.say(' '.join(stumbled(said, form)))
    assert out.after == before + 1, f'{form}: the whole portion with a stumble did not confirm it (cursor {out.after})'
    assert out.speaks == [nxt], (form, out.actions)
    assert out.model_calls == 0 and not out.destroyed, (form, out.actions)


def test_b02_fragments_of_the_portion_hold_the_cursor_and_the_whole_one_moves_it_exactly_one(tmp_path):
    d = dictation(tmp_path)
    before = d.index
    said = words_of(d.current)
    for k in range(1, len(said) - 1):                   # a fragment with two or more words still missing
        out = d.say(' '.join(said[:k]))
        assert out.after == before, f'a fragment of {k} of {len(said)} words moved the cursor'
        assert out.model_calls == 0 and not out.destroyed, out.actions
    whole = d.say(' '.join(said))
    assert whole.after == before + 1 and whole.speaks == [d.current], whole.actions


def test_b03_a_retransmitted_next_is_one_step_not_two(tmp_path):
    d = dictation(tmp_path)
    before = d.index
    first = d.say('Дальше.', tid='dup-next')
    assert first.after == before + 1, first.actions
    again = d.deliver(H.done('dup-next', 'user', 'Дальше.'))
    assert again.after == before + 1 and again.speaks == [], 'the same turn delivered twice must not step twice'


def test_b04_next_walks_the_plan_once_and_never_past_its_end(tmp_path):
    d = dictation(tmp_path)
    plan = d.chunks
    said = []
    for _ in range(len(plan) + 3):                      # three more «дальше» than there are portions
        ended = d.completed
        out = d.say('Дальше.')
        if ended:
            assert not set(out.speaks) & set(plan), f'«дальше» after the end said a portion again: {out.speaks}'
        said += out.speaks
        assert d.index <= len(plan), f'the cursor ran past the plan: {d.index} of {len(plan)}'
    assert said[:len(plan) - 1] == plan[1:], 'the portions did not come in order, each once'


def test_b05_next_after_stop_goes_one_portion_on_and_ends_the_pause(tmp_path):
    d = dictation(tmp_path)
    d.say(d.current)
    index, plan = d.index, d.chunks
    assert d.say('Стоп.').types == ['cancel'] and d.state.get('paused')
    out = d.say('Дальше.')
    assert out.after == index and out.speaks == [plan[index]], out.actions      # engine.going_on 4b: the cut portion, even «дальше» says it again (the cursor stays)
    assert not d.state.get('paused') and out.model_calls == 0


def test_b06_a_stop_with_no_voice_event_before_it_still_pauses(tmp_path):
    d = dictation(tmp_path)
    d.say(d.current)
    index, plan = d.index, d.chunks
    c = d.controller
    d.clock.advance(3.0)
    c.provider(H.created('lonely-stop', 'user', ''))    # the final comes with no speech_started(): the ear never reported a voice
    actions = c.provider(H.done('lonely-stop', 'user', 'Стоп.'))
    assert [a['type'] for a in actions] == ['cancel'], actions
    assert d.state.get('paused') and d.index == index and d.chunks == plan
    assert c.tick(now=d.clock() + 3600) == []


def test_b07_stop_with_nothing_to_stop_is_no_question_for_the_model(tmp_path):
    d = dictation(tmp_path)
    finish(d)
    for _ in range(3):
        out = d.say('Стоп.')
        assert out.model_calls == 0 and out.speaks == [], out.actions
        assert not {'route', 'lookup'} & set(out.types), f'«стоп» was sent to the model as a question: {out.types}'


def test_b08_the_end_of_a_cut_cue_reported_late_arms_no_repeat(tmp_path):
    d = dictation(tmp_path, play_first=False)           # the first cue is in flight
    cue = d.cues[0]
    assert d.say('Стоп.').types == ['cancel']
    d.clock.advance(1.0)
    d.controller.playback_done(cue, now=d.clock())      # the transport reports the end of the cue it cut
    assert not d.controller.authorized(cue)
    assert silence(d, 200, step=2.0) == [], 'a paused answer was spoken by itself after the late end of its cut cue'


def test_b09_a_question_over_an_unheard_first_portion_comes_back_to_that_portion(tmp_path):
    d = dictation(tmp_path, play_first=False)
    plan, old_cue = d.chunks, d.cues[0]
    asked = d.say('Что такое трение')
    assert asked.types[:2] == ['cancel', 'route'], asked.actions
    side = d.deliver(H.done('a-side', 'assistant', SIDE_ANSWER))
    d.play(side.actions)
    d.clock.advance(0.5)
    d.controller.playback_done(old_cue, now=d.clock())  # the first cue of the story reports its end late: nobody heard it
    finish(d)
    back = d.say('Вернёмся к прошлому вопросу.')
    assert back.speaks == [plan[0]], f'the unheard first portion must come back, got {back.speaks}'
    assert back.model_calls == 0


def test_b10_two_side_questions_and_back_to_the_first_story(tmp_path):
    d = dictation(tmp_path)
    plan = d.chunks
    d.say(plan[0])                                      # one portion confirmed, the second waits
    d.say('Что такое трение')
    d.play(d.deliver(H.done('a-b', 'assistant', SIDE_ANSWER)).actions)
    asked = d.say('Что такое вес тела')                 # asked before the answer to the first side question was heard to its end
    assert asked.types[:2] == ['cancel', 'route'], asked.actions
    d.play(d.deliver(H.done('a-c', 'assistant', 'Вес — это сила, с которой тело давит на опору. Он зависит от ускорения свободного падения.')).actions)
    finish(d)
    back = d.say('Вернёмся к первому вопросу.')
    assert back.speaks == [plan[1]], f'the story did not come back at its second portion: {back.speaks}'
    assert back.model_calls == 0 and d.controller.authorized(back.actions[-1])


def test_b11_a_changed_topic_silences_the_old_story_for_good(tmp_path):
    d = dictation(tmp_path)
    d.say(d.current)
    old_plan = set(d.chunks)
    old_cue = d.cues[-1]
    asked = d.say('Давай про другое. Что такое налог на имущество')
    assert asked.types[:2] == ['cancel', 'route'], asked.actions
    assert not d.controller.authorized(old_cue), 'the cue of the old story is still authorized after the topic changed'
    waited = silence(d, 120, step=2.0)                  # the new answer has not come yet: whatever is said, it is not the old story
    assert not set(waited) & old_plan, f'the old story was spoken while the new answer was awaited: {waited}'
    fresh = d.deliver(H.done('a-new', 'assistant', 'Налог на имущество платят собственники квартир и домов. Ставку устанавливают местные власти.'))
    assert len(speaks(fresh.actions)) == 1 and speaks(fresh.actions)[0] not in old_plan
    d.play(fresh.actions)
    later = silence(d, 300, step=2.0)
    assert not (set(later) & old_plan), f'the old story came back by itself: {later}'

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
