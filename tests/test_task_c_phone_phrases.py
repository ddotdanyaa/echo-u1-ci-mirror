"""WAVE 2 / Task C-seg, DEF-SEG-20 and the Task 2 review item "phone-phrase tail dropped".

The stock iPhone client (Conduit) handles a WHOLE utterance equal to «стоп», «хватит», «замолчи», «тише», «пока»,
«до свидания», «закончить разговор», «это всё» itself and never sends it on. A portion the listener is asked to repeat
aloud must therefore never be (or consist essentially of) one of them: repeating it would end the voice session.
Such a portion is merged into a neighbouring content portion; an answer that is nothing else is not spoken.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                                    # noqa: E402
from echo_sync.engine import EchoEngine, SILENT                              # noqa: E402
from echo_sync.first_useful import first_cue                                 # noqa: E402
from echo_sync.generator import StreamingAnswer                              # noqa: E402
from echo_sync.portioner import portions                                     # noqa: E402
from echo_sync.settings import resolve                                       # noqa: E402
from echo_sync.textutil import CONDUIT_LOCAL_PHRASES, is_phone_phrase, normalize, phone_phrase  # noqa: E402
from engine_say import engine_reply

CONTROLLED = H.CONTROLLED_SETTINGS


@pytest.mark.parametrize('text', ['Стоп', 'стоп.', 'СТОП!', 'Хватит.', 'Замолчи!', 'Тише…', 'Пока.', 'До свидания.',
                                  'Закончить разговор.', 'Это всё.', 'это все', 'Это всё!'])
def test_the_eight_phrases_are_phone_phrases(text):
    assert is_phone_phrase(text) and phone_phrase(text) in CONDUIT_LOCAL_PHRASES


@pytest.mark.parametrize('text', ['Ну, пока.', 'Всё, стоп.', 'Стоп, стоп.', 'Пока, пока!', 'Тише, тише, тише.',
                                  'Стоп, пожалуйста.', 'Ладно, хватит.', 'Итак, до свидания.', 'До свидания, до свидания.',
                                  'Да, пока.', 'Хорошо, это всё.'])
def test_a_phone_phrase_with_fillers_around_it_or_said_twice_is_still_a_phone_phrase(text):
    assert is_phone_phrase(text), text


@pytest.mark.parametrize('text', ['Пока не поздно', 'Хватит ли денег?', 'Это всё, что нужно знать.', 'Стоп-сигнал',
                                  'Тише едешь — дальше будешь.', 'До свидания, Иван Петрович.', 'Нет.', 'Хорошо.', 'Ладно, итак.',
                                  '', '   ', 'пока дождь'])
def test_ordinary_text_is_not_a_phone_phrase(text):
    assert not is_phone_phrase(text), text


PHONE_ANSWERS = [
    ('Как попрощаться вежливо?', 'До свидания. Всего доброго вам и удачи.'),
    ('Как завершить звонок вежливо?', 'Закончить разговор. Затем положите трубку.'),
    ('Что сказать на прощание?', 'Ну, пока. Увидимся завтра на уроке математики.'),
    ('Как остановить машину?', 'Стоп, стоп. Нажмите на тормоз до упора.'),
    ('Что ответить на шум?', 'Скажите: тише, тише. Потом попросите повторить вопрос.'),
]


@pytest.mark.parametrize('profile', ['controlled', 'adaptive', 'words2', 'words3', 'range_2_8'])
@pytest.mark.parametrize('question,answer', PHONE_ANSWERS)
def test_no_portion_of_the_plan_is_a_phone_phrase_not_even_essentially(profile, question, answer):
    parts = portions(answer, H.PROFILES[profile])
    assert parts
    for part in parts:
        assert not is_phone_phrase(part), (profile, answer, part)


@pytest.mark.parametrize('question,answer', PHONE_ANSWERS)
def test_a_streamed_answer_never_cues_or_stores_a_phone_phrase(question, answer):
    run = H.stream(question, answer, 'words', walk=True)
    assert run.cues, 'an answer with content after the phrase must still be cued'
    for part in run.cues + run.chunks + (run.walk or []):
        assert not is_phone_phrase(part), (answer, part)
    # nothing is dropped: every character of the answer is in the stored plan, in order
    assert H.lossless_problem(answer, run.chunks) is None, run.chunks


@pytest.mark.parametrize('answer', ['До свидания.', 'Закончить разговор.', 'Стоп!', 'Ну, пока.'])
def test_an_answer_that_is_only_a_phone_phrase_is_not_spoken(answer):
    run = H.stream('Как попрощаться?', answer, 'words', walk=False)
    assert run.cues == [] and not any(is_phone_phrase(c) for c in run.chunks)


@pytest.mark.parametrize('final', [True, False])
def test_the_first_cue_is_never_a_phone_phrase_even_when_a_sentence_mark_ends_it(final):
    q = 'Как попрощаться вежливо?'
    for answer in ('До свидания. Всего доброго вам и удачи.', 'Закончить разговор. Затем положите трубку мягко.'):
        cue = first_cue(answer, q, CONTROLLED, final=final, last=final)
        assert cue is None or not is_phone_phrase(cue), (answer, cue)
        if final:
            assert cue and answer.startswith(cue) and len(cue) > len(answer.split('.')[0]) + 1


# --- Task 2 review: a tail that is nothing but a phone phrase is not dropped ------------------------------------------

def _engine(tmp_path, answer, first_chunk, final=False):
    produced = StreamingAnswer(answer, first_chunk=first_chunk, final=final)
    engine = EchoEngine(tmp_path / 'tail.sqlite3', lambda *args: produced, settings=CONTROLLED)
    reply = engine_reply(engine, session_id='s', turn_id='q', text='Что делать при шуме?', request={}, model='m')
    return engine, reply


@pytest.mark.parametrize('phrase', ['Хватит.', 'Стоп!', 'Это всё.', 'До свидания.', 'Тише, тише.'])
def test_a_tail_that_is_a_phone_phrase_is_portioned_with_the_last_words_of_the_previous_chunk(tmp_path, phrase):
    engine, reply = _engine(tmp_path, 'Нужно остановиться', 'Нужно остановиться')
    assert reply == 'Нужно остановиться'
    revision = engine.state('s')['revision']
    assert engine.extend_answer(session_id='s', revision=revision, answer='Нужно остановиться ' + phrase, final=True) == SILENT
    chunks = engine.state('s')['chunks']
    assert chunks[0] == 'Нужно остановиться' and len(chunks) == 2, chunks
    assert not any(is_phone_phrase(c) for c in chunks)
    # the words of the tail are in the plan (nothing silently dropped) and are led by the overlap
    assert normalize(phrase) in normalize(chunks[-1]) and normalize(chunks[-1]).startswith('остановиться')
    assert engine.state('s')['answer'] == 'Нужно остановиться ' + phrase


def test_the_tail_overlap_is_spoken_after_the_previous_chunk_is_repeated(tmp_path):
    engine, _ = _engine(tmp_path, 'Нужно остановиться', 'Нужно остановиться')
    revision = engine.state('s')['revision']
    engine.extend_answer(session_id='s', revision=revision, answer='Нужно остановиться. Хватит.', final=True)
    nxt = engine_reply(engine, session_id='s', turn_id='ack1', text='Нужно остановиться', request={}, model='m')
    assert nxt == 'остановиться. Хватит.'
    assert engine_reply(engine, session_id='s', turn_id='ack2', text=nxt, request={}, model='m') == SILENT
    assert engine.state('s')['completed']


def test_a_tail_without_words_adds_nothing_and_is_not_an_overlap_case(tmp_path):
    engine, _ = _engine(tmp_path, 'Нужно остановиться', 'Нужно остановиться')
    revision = engine.state('s')['revision']
    engine.extend_answer(session_id='s', revision=revision, answer='Нужно остановиться.', final=True)
    assert engine.state('s')['chunks'] == ['Нужно остановиться']


def test_the_rest_after_the_first_chunk_that_is_a_phone_phrase_is_not_dropped(tmp_path):
    """engine.reply: [first_chunk] + portions(rest) has the same loss and gets the same remedy."""
    engine, reply = _engine(tmp_path, 'Нужно остановиться. Хватит.', 'Нужно остановиться.', final=True)
    assert reply == 'Нужно остановиться.'
    chunks = engine.state('s')['chunks']
    assert chunks[0] == 'Нужно остановиться.' and len(chunks) == 2, chunks
    assert not any(is_phone_phrase(c) for c in chunks) and 'хватит' in normalize(chunks[-1])


def test_a_phone_phrase_tail_after_a_single_word_chunk_still_gets_an_overlap(tmp_path):
    engine, _ = _engine(tmp_path, 'Подождите', 'Подождите')
    revision = engine.state('s')['revision']
    engine.extend_answer(session_id='s', revision=revision, answer='Подождите, пока', final=True)
    chunks = engine.state('s')['chunks']
    assert chunks[0] == 'Подождите' and len(chunks) == 2 and 'пока' in normalize(chunks[-1])
    assert not any(is_phone_phrase(c) for c in chunks)


def test_a_phone_phrase_tail_with_no_previous_chunk_is_chatter_and_is_dropped():
    """Nothing to lead with (a state always has a first chunk; the helper is still total): «Пока.» alone is chatter."""
    assert EchoEngine._with_overlap([], 'Пока.', resolve(CONTROLLED)) == []
    assert EchoEngine._with_overlap(['Подождите'], 'Пока.', resolve(CONTROLLED)) == ['Подождите Пока.']
