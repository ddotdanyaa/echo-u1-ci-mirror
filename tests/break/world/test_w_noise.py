"""U237 breakD, class «noise, a changed microphone, the app's own voice heard back» (К7, К26, owner 06.11: «собственная озвучка не засчитывается за повтор», «тишина не продвигает курсор»).
The portion waits; the room makes sound that is not the owner's repeat. Through the real ControlledMedia (helpers_s6_ack.Dictation)."""
import pytest

import bps_common
import helpers_s6_ack as H
from bw_common import silence, speaks, waiting

JUNK = ['', ' ', '.', '…', 'э', 'м-м', 'а', 'хм', 'угу', '​', 'а а а а а а а а а а а а', 'ммм ааа ыыы']


@pytest.mark.parametrize('junk', JUNK)
def test_w06_junk_over_a_waiting_portion_neither_moves_nor_kills_it(tmp_path, junk):
    d = waiting(tmp_path)
    index, plan = d.index, d.chunks
    out = d.say(junk)
    assert out.after == index and d.chunks == plan, f'{junk!r} moved the cursor or changed the plan'
    assert not out.destroyed and out.model_calls == 0, f'{junk!r} was sent to the model or dropped the answer: {out.types}'
    assert d.say(d.current).after == index + 1, f'after {junk!r} the correct repeat no longer counts'


def test_w07_a_voice_detector_that_fires_thirty_times_with_no_words_leaves_the_portion_alone(tmp_path):
    d = waiting(tmp_path)
    index, plan = d.index, d.chunks
    for _ in range(30):                                 # the microphone hums: speech starts, no turn ever ends
        d.clock.advance(0.7)
        d.controller.speech_started()
        d.controller.tick(now=d.clock())
    assert d.index == index and d.chunks == plan
    assert d.say(d.current).after == index + 1, 'thirty empty starts of speech blocked the owner\'s repeat'


def test_w08_two_hundred_words_of_babble_are_noise_not_a_question(tmp_path):
    d = waiting(tmp_path)
    index = d.index
    out = d.say(' '.join(['ну вот и значит это самое'] * 40))
    assert out.after == index and not out.destroyed and out.model_calls == 0, f'long babble without a question: {out.types}'


def test_w09_a_turn_id_reused_after_the_microphone_restarted_is_a_new_turn(tmp_path):
    """The audio input is re-opened (an earphone is plugged in): the provider numbers its turns from the start again. The same id with ANOTHER text is not a retransmit."""
    d = waiting(tmp_path, confirmed=0)
    before, plan = d.index, d.chunks
    assert d.say(plan[before], tid='u-1').after == before + 1
    again = d.say(plan[before + 1], tid='u-1')          # the same id, the next portion's words
    assert again.after == before + 2, f'a new utterance with a reused turn id was swallowed as a duplicate (cursor {again.after})'


@pytest.mark.parametrize('form', ['in_flight_whole', 'tail_whole', 'in_flight_half'])
def test_w10_the_voice_of_the_app_heard_back_by_its_own_microphone_is_not_a_repeat(tmp_path, form):
    d = bps_common.dictation(tmp_path, play_first=form.startswith('in_flight'))      # tail: the cue has ended, its echo is still in the room
    index = d.index
    said = d.current.split()
    text = ' '.join(said[:len(said) // 2]) if form.endswith('half') else d.current
    d.clock.advance(0.4)
    d.deliver(H.created('echo-1', 'user', ''))          # no speech_started of the owner: the ear heard no near voice
    out = d.deliver(H.done('echo-1', 'user', text))
    assert d.index == index, f'{form}: the app\'s own cue heard back counted as the owner\'s repeat'
    assert not out.destroyed and out.model_calls == 0, out.actions

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
