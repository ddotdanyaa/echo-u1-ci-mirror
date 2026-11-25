"""WAVE 2 / Task B, item 4 (ACK-split): the cloud may hear ONE repeat as several consecutive turns.

Live evidence 02.11.2026 05:51 (deployed build 5dcbf8d): the 6-word portion «Свойство тела сопротивляться изменению
своего движения.» was repeated in full and the cloud delivered two turns, «свойство тела» | «сопротивляться изменению своего
движения»; each half was judged alone, neither was a confirmation, and the portion was never accepted.

Required: the controller matches the user's speech SINCE THE PORTION STARTED, the fragments joined in order, inside a bounded
window. Everything else about a confirmation is unchanged: a partial or a wrong repeat never advances, a duplicate advances at
most once, a fragment of an earlier portion or of a cancelled answer never counts. Time is injected (``FakeClock``): nothing
here sleeps.

WAVE 2 integration (task-b + task-c): the live sentence is no longer ONE portion - the first cue is a short unit of 2-4 words
(L2) and the later portions are 2-4 words in the production profile. The fixture is rebuilt around the longest portion that
profile makes, «при ста градусах Цельсия.» (4 words; the 2nd of the plan below), which is reached by repeating the first cue whole,
as the listener does; the properties and what fails them are the ones Task B wrote. A portion longer than ``ACK_JOIN_FRAGMENTS``
words does not exist in the production profile, so the test that needs one (the bound on the pieces), and a second run of the live
split at the size of the live case (7 words torn 3 + 4), use the 2-8-word profile (the owner's wording of the portion size).
"""
import asyncio

import pytest

import helpers_s6_ack as H
from echo_sync.controlled_media import ACK_JOIN_FRAGMENTS, ACK_JOIN_SECONDS
from engine_say import engine_reply

# Production plan (F1, wave F: the call cuts by meaning): «Вода закипает в обычной кастрюле на плите,» | «при ста градусах Цельсия.» |
# «При ста градусах вода кипит.» | «В горах она закипает раньше.» - the same portion under test, 2nd, and a portion after it that
# starts with its first words (it was «Вода кипит» | «при ста градусах Цельсия.» | «При ста градусах» | «вода кипит.»)
ANSWER = ('Вода закипает в обычной кастрюле на плите, при ста градусах Цельсия. При ста градусах вода кипит. '
          'В горах она закипает раньше.')
AT = 1                                       # the portion under test is the 2nd; the 1st cue is repeated whole before it
PORTION = 'при ста градусах Цельсия.'
HEAD, TAIL = 'при ста', 'градусах Цельсия'
# The portion after it repeats the first words of this one: a stale fragment would be enough to confirm it (F1: the whole next
# sentence; the stale «при ста» plus the new «градусах вода кипит» would spell it).
ECHO = 'При ста градусах вода кипит.'

# The 2-8-word profile (helpers_s6_seg.PROFILES['range_2_8']): the same sentence in portions of 7 and 8 words.
LONG_SETTINGS = dict(H.PROD_SETTINGS, portion_mode='syllables', min_words=2, max_words=8, target_syllables=12, max_syllables=20)
LONG_ANSWER = 'Вода кипит при ста градусах Цельсия на уровне моря. Выше в горах она кипит при меньшей температуре.'
LONG_PORTION = 'при ста градусах Цельсия на уровне моря.'
LONG_HEAD, LONG_TAIL = 'при ста градусах', 'Цельсия на уровне моря'


def dictation(tmp_path, answer=ANSWER, portion=PORTION, settings=None):
    """The dictation of ``answer`` with the cue(s) before the portion under test repeated whole: the portion is the one that waits."""
    d = H.Dictation(tmp_path / 'split', answer, settings=settings)
    for n in range(AT):
        assert d.say(d.current, gap=4.0).after == n + 1, 'precondition: the cue before the portion is confirmed'
    assert d.current == portion and d.index == AT, f'precondition: the portion under test, got {d.current!r} at {d.index}'
    return d


@pytest.mark.parametrize('answer,portion,settings,head,tail', [
    (ANSWER, PORTION, None, HEAD, TAIL),
    (LONG_ANSWER, LONG_PORTION, LONG_SETTINGS, LONG_HEAD, LONG_TAIL),
], ids=['production_profile', 'two_to_eight_word_profile'])
def test_the_live_split_repeat_is_one_confirmation(tmp_path, answer, portion, settings, head, tail):
    d = dictation(tmp_path, answer, portion, settings)
    first = d.say(head, gap=4.0)
    assert first.after == AT and first.speaks == [], 'the first half alone is only an attempt'
    second = d.say(tail, gap=0.8)
    assert second.after == AT + 1, f'the two halves are one full repeat; actions={second.types}'
    assert second.speaks == [d.chunks[AT + 1]], 'exactly the next portion is spoken, once'
    assert second.model_calls == 0 and not second.destroyed


@pytest.mark.parametrize('pieces', [
    ['при', 'ста градусах', 'Цельсия'],
    ['при ста', 'градусах', 'Цельсия'],
    ['при', 'ста', 'градусах', 'Цельсия'],
], ids=['3-pieces', '3-pieces-b', '4-pieces'])
def test_a_repeat_torn_into_several_pieces_is_joined(tmp_path, pieces):
    assert len(pieces) <= ACK_JOIN_FRAGMENTS, 'precondition: inside the limit'
    d = dictation(tmp_path)
    for piece in pieces[:-1]:
        assert d.say(piece, gap=1.0).after == AT, 'a piece alone is only an attempt'
    last = d.say(pieces[-1], gap=1.0)
    assert last.after == AT + 1 and last.speaks == [d.chunks[AT + 1]], (pieces, last.types)


def test_a_repeat_torn_into_more_pieces_than_the_limit_is_not_joined(tmp_path):
    words = LONG_PORTION.split()
    assert len(words) > ACK_JOIN_FRAGMENTS, 'precondition: one word per piece exceeds the limit'
    d = dictation(tmp_path, LONG_ANSWER, LONG_PORTION, LONG_SETTINGS)
    for word in words:
        out = d.say(word, gap=1.0)
    assert out.after == AT and d.index == AT, 'the joining is bounded: the first words fall out of the reach'


def test_a_filler_between_the_fragments_does_not_matter(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    assert d.say('ну', gap=0.5).after == AT
    assert d.say(TAIL, gap=0.5).after == AT + 1, 'a stray «ну» between the halves is not part of the speech'


def test_fragments_in_the_wrong_order_are_not_a_confirmation(tmp_path):
    d = dictation(tmp_path)
    d.say(TAIL, gap=4.0)
    out = d.say(HEAD, gap=0.8)
    assert out.after == AT and out.speaks == [], 'the tail before the head is not the portion'


def test_a_missing_word_between_the_fragments_is_not_a_confirmation(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    out = d.say('Цельсия', gap=0.8)                          # «градусах» was never said
    assert out.after == AT and out.speaks == []


@pytest.mark.parametrize('tail', [
    'не градусах Цельсия',                                   # an added «не»
    'градусах Цельсия не',
    'градусах Фаренгейта',                                   # another word (an inflected form of the same word is fine)
    'градусах Цельсия два',                                  # an added number
], ids=['added-not', 'trailing-not', 'other-word', 'added-number'])
def test_a_wrong_joined_repeat_is_not_a_confirmation(tmp_path, tail):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    out = d.say(tail, gap=0.8)
    assert out.after == AT and out.speaks == [], f'joined {HEAD!r} + {tail!r} must not confirm'


def test_fragments_further_apart_than_the_window_are_not_joined(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    out = d.say(TAIL, gap=ACK_JOIN_SECONDS + 1.0)
    assert out.after == AT, f'{ACK_JOIN_SECONDS + 1.0:.0f} s apart is two separate attempts, not one repeat'


def test_fragments_just_inside_the_window_are_joined(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    assert d.say(TAIL, gap=ACK_JOIN_SECONDS - 1.0).after == AT + 1


def test_a_fragment_of_the_confirmed_portion_is_not_joined_to_the_next_one(tmp_path):
    """«при ста» was said for the portion; after it is confirmed, the next one is «При ста градусах вода кипит.». The old words plus
    a new «градусах вода кипит» would spell it: the old words belong to the portion they were said for."""
    d = dictation(tmp_path)
    assert d.chunks[AT + 1] == ECHO, 'precondition: the next portion repeats the opening of this one'
    d.say(HEAD, gap=4.0)
    assert d.say(PORTION, gap=1.5).after == AT + 1
    stale = d.say('градусах вода кипит', gap=1.0)
    assert stale.after == AT + 1 and d.index == AT + 1 and stale.speaks == [], 'a stale fragment confirmed the next portion'


def test_the_fragments_are_what_the_user_said_since_the_portion_started(tmp_path):
    d = dictation(tmp_path)
    assert d.controller.heard_since_portion() == []
    d.say(HEAD, gap=4.0)
    assert d.controller.heard_since_portion() == [HEAD]
    d.say('ну', gap=0.5)
    assert d.controller.heard_since_portion() == [HEAD], 'a bare filler carries nothing'
    d.say(TAIL, gap=0.5)
    assert d.controller.heard_since_portion() == [], 'spent by the confirmation'


def test_fragments_belong_to_the_portion_they_were_said_for_whatever_moves_the_cursor(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    assert d.controller.heard_since_portion() == [HEAD]
    # something else confirms the portion behind the controller's back (another instance on the same session)
    engine_reply(d.controller.engine, session_id=H.SESSION, turn_id='elsewhere', text=PORTION, request={}, model='test')
    assert d.index == AT + 1
    assert d.controller.heard_since_portion() == [], 'the old half was said for the portion before, not for this one'


def test_a_repeat_request_starts_the_portion_afresh(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    asked = d.say('повтори', gap=1.0)
    assert asked.speaks == [PORTION], 'the portion is spoken again'
    assert d.controller.heard_since_portion() == [], 'it starts again: the old attempt does not count'
    assert d.say(TAIL, gap=4.0).after == AT, 'the tail alone, after the portion was spoken again, is only an attempt'


def test_a_new_question_discards_the_fragments(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    asked = d.say('Расскажи подробнее про фотосинтез', gap=1.0)
    assert asked.destroyed, 'a new question replaces the answer'
    assert d.controller.heard_since_portion() == []


def test_a_whole_repeat_after_an_attempt_advances_exactly_once(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    out = d.say(PORTION, gap=1.5, tid='whole')
    assert out.after == AT + 1 and out.speaks == [d.chunks[AT + 1]]
    again = d.deliver(H.done('whole', 'user', PORTION))          # the confirming turn once more
    assert again.speaks == [] and d.index == AT + 1


def test_a_retransmitted_second_half_advances_at_most_once(tmp_path):
    d = dictation(tmp_path)
    d.say(HEAD, gap=4.0)
    d.say(TAIL, gap=0.8, tid='tail-1')
    assert d.index == AT + 1
    out = d.deliver(H.done('tail-1', 'user', TAIL))               # the same turn id again
    assert out.speaks == [] and d.index == AT + 1, 'a duplicate final of the second half advances nothing'


def test_the_joined_repeat_works_through_the_wire(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'wire')
        try:
            await wire.begin(ANSWER)
            for n in range(AT):                                   # the cue before the portion is repeated whole
                await wire.user(wire.chunks[n], tid=f'cue-{n}')
                assert wire.index == n + 1, 'precondition: the cue before the portion is confirmed'
            assert wire.chunks[AT] == PORTION
            before = wire.audio_frames
            await wire.user(HEAD, tid='h1')
            assert wire.index == AT
            await wire.user(TAIL, tid='t1', reaction=0.8)
            assert wire.index == AT + 1, 'the two halves, delivered like the cloud delivers them, are one confirmation'
            assert wire.audio_frames > before and wire.synthesized[-1] == wire.chunks[AT + 1]
        finally:
            await wire.close()
    asyncio.run(run())
