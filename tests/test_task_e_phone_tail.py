"""WAVE 2 / Task E, ruling 6 (fix round on d4c15e9): a tail that is exactly a phone phrase after a FILLER-ONLY previous chunk is not dropped.

The Task 2 review item (a): the stock phone (Conduit) handles a WHOLE utterance equal to «стоп», «хватит», «пока», «это всё»... itself, so a
portion must never be one; a tail that is nothing but such a phrase leads with the last words of the previous chunk instead (the listener hears a
word again, never a phrase they must not repeat). The review found the one case left: when the previous chunk consists only of filler words
(«Да!», «всё…») the overlap word is itself a filler, filler + phrase is still a phone phrase for every overlap size, and the tail was dropped
without a trace (``EchoEngine._portions_after(['Да!'], ' Хватит.', cfg)`` returned ``[]``; found by the review's fuzz).

Ruling: speak the previous chunk and the tail as ONE unit. The plan is lossless again; the unit is the only portion that can be a phone phrase
(there is nothing else to lead it with), and what the earlier tests pin stays: with no previous chunk at all a lone phone phrase is chatter.
"""
import pytest

from echo_sync.engine import EchoEngine, SILENT
from echo_sync.generator import StreamingAnswer
from echo_sync.settings import resolve
from echo_sync.textutil import normalize
import helpers_s6_seg as H
from engine_say import engine_reply

CFG = resolve(H.CONTROLLED_SETTINGS)
FILLER_CHUNKS = [['Да!'], ['Да.'], ['всё…'], ['всё)'], ['Ну, да.']]
PHRASES = [' Хватит.', ' Пока.', 'Стоп, стоп.', ' ну пока', ' До свидания.', ' Это всё.']


@pytest.mark.parametrize('chunks', FILLER_CHUNKS, ids=lambda c: c[0])
@pytest.mark.parametrize('tail', PHRASES, ids=lambda t: t.strip())
def test_a_phone_phrase_tail_after_a_filler_only_chunk_is_not_dropped(chunks, tail):
    added = EchoEngine._portions_after(chunks, tail, CFG)
    assert added, f'the tail {tail!r} after {chunks} was dropped without a trace'
    spoken = normalize(' '.join(added))
    for word in normalize(tail).split():
        assert word in spoken.split(), (tail, added)
    assert spoken.startswith(normalize(chunks[-1])), 'the unit leads with the previous chunk'


def test_the_unit_is_the_previous_chunk_and_the_tail_in_order():
    assert EchoEngine._portions_after(['Да!'], ' Хватит.', CFG) == ['Да! Хватит.']
    assert EchoEngine._portions_after(['Ну, да.'], ' Пока.', CFG) == ['Ну, да. Пока.']
    assert EchoEngine._portions_after(['всё…'], 'Это всё.', CFG) == ['всё… Это всё.']


def _engine(tmp_path, answer, first_chunk, final=False):
    produced = StreamingAnswer(answer, first_chunk=first_chunk, final=final)
    engine = EchoEngine(tmp_path / 'tail.sqlite3', lambda *args: produced, settings=H.CONTROLLED_SETTINGS)
    reply = engine_reply(engine, session_id='s', turn_id='q', text='Что сказал учитель?', request={}, model='m')
    return engine, reply


def test_a_streamed_filler_chunk_and_a_phone_phrase_tail_are_both_in_the_stored_plan(tmp_path):
    engine, reply = _engine(tmp_path, 'Да!', 'Да!')
    assert reply == 'Да!'
    revision = engine.state('s')['revision']
    assert engine.extend_answer(session_id='s', revision=revision, answer='Да! Хватит.', final=True) == SILENT
    state = engine.state('s')
    assert state['chunks'] == ['Да!', 'Да! Хватит.'], state['chunks']
    assert state['answer'] == 'Да! Хватит.'
    nxt = engine_reply(engine, session_id='s', turn_id='ack1', text='Да', request={}, model='m')
    assert nxt == 'Да! Хватит.', 'the tail is spoken after the previous chunk is repeated'


def test_the_rest_after_a_filler_only_first_chunk_is_not_dropped_either(tmp_path):
    """engine.reply: [first_chunk] + portions(rest) has the same loss and gets the same remedy."""
    engine, reply = _engine(tmp_path, 'Да! Хватит.', 'Да!', final=True)
    assert reply == 'Да!'
    assert engine.state('s')['chunks'] == ['Да!', 'Да! Хватит.']


def test_what_the_earlier_tests_pin_stays():
    assert EchoEngine._with_overlap([], 'Пока.', CFG) == [], 'no previous chunk: a lone phone phrase is chatter'
    assert EchoEngine._with_overlap(['Подождите'], 'Пока.', CFG) == ['Подождите Пока.']
    assert EchoEngine._portions_after(['Нужно остановиться'], ' Хватит.', CFG) == ['остановиться Хватит.'], 'a content chunk still leads by its last word'
    assert EchoEngine._portions_after(['Да!'], ' Это правда.', CFG), 'an ordinary tail is portioned as ever'
    assert EchoEngine._portions_after(['Да!'], '   ', CFG) == [], 'a tail without words adds nothing'
