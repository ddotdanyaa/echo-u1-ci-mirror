"""WAVE 2 / Task E, ruling 5 (fix round on d4c15e9): more stalling openers are not cues.

The review (probe_stalls.py): Task C's filter is a word list and the live phrase «Понял, сейчас быстро проверю и скажу.» is covered,
but «Один момент.», «Подождите секунду.», «Сейчас, одну секунду.», «Сейчас расскажу.», «Хорошо, отвечаю.», «Дайте-ка подумать.»,
«Хмм, дайте проверить.» (and a lone «Хмм.») were still spoken as the first cue: the listener is asked to repeat a promise. The ruling
extends the SAME lists of textutil (``_ACK``, ``_PAUSE``, the whole-sentence stalls of ``_PROCESS_PREFIX``); no parallel list. Only a
WHOLE sentence is a stall: the same words inside a longer sentence are content.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                           # noqa: E402
from echo_sync.textutil import strip_process_prefix                  # noqa: E402

BODY = 'Проезд стоит 100 рублей за одну поездку.'
QUESTION = 'Сколько стоит проезд на метро в Москве?'

STALLS = [
    'Один момент.', 'Подождите секунду.', 'Подождите.', 'Подожди секундочку.', 'Сейчас, одну секунду.', 'Сейчас расскажу.',
    'Конечно, сейчас расскажу.', 'Отвечаю.', 'Хорошо, отвечаю.', 'Дайте-ка подумать.', 'Дайте-ка проверить.', 'Дайте проверить.',
    'Хмм, дайте проверить.', 'Хмм.', 'Хм.', 'Да, один момент.', 'Дайте‑ка подумать.',
]


@pytest.mark.parametrize('stall', STALLS)
def test_a_stalling_sentence_is_stripped_before_the_answer(stall):
    assert strip_process_prefix(stall + ' ' + BODY) == BODY


@pytest.mark.parametrize('stall', STALLS)
def test_a_lone_stalling_sentence_is_nothing(stall):
    assert strip_process_prefix(stall) == ''


@pytest.mark.parametrize('how', ['words', 'chars5', 'chars1'])
@pytest.mark.parametrize('stall', STALLS)
def test_a_stall_is_never_the_first_cue_whatever_the_slicing(stall, how):
    run = H.stream(QUESTION, stall + ' ' + BODY, how, walk=False)
    assert run.cues, 'the real answer after the stall must still be cued'
    assert run.cues[0].startswith('Проезд'), run.cues
    spoken = ' '.join(run.chunks).casefold()
    for word in ('момент', 'подожд', 'расскажу', 'отвечаю', 'дайте', 'хм', 'сейчас'):
        assert word not in spoken, (word, run.chunks)
    assert H.nospace(''.join(run.chunks)) == H.nospace(BODY)


@pytest.mark.parametrize('text', [
    'Один момент времени отделяет прошлое от будущего.',
    'Подождите, пока вода закипит.',
    'Подождите пока вода закипит, потом добавьте соль.',
    'Сейчас расскажу вам подробно, что такое масса.',
    'Сейчас, как известно, вода кипит при ста градусах.',
    'Отвечаю на ваш вопрос: вода кипит при ста градусах.',
    'Дайте-ка подумать над этим вопросом внимательно.',
    'Хмм-хмм, это звук.',
    'Момент силы равен произведению силы на плечо.',
    'Отвечают на вопросы по очереди.',
    'Подождите секунду, пока завершится реакция.',
])
def test_real_content_that_looks_like_a_stall_is_left_alone(text):
    assert strip_process_prefix(text) == text


def test_the_live_opener_and_the_task_c_stalls_are_still_stripped():
    assert strip_process_prefix('Понял, сейчас быстро проверю и скажу. ' + BODY) == BODY
    assert strip_process_prefix('Секунду, сейчас найду информацию. ' + BODY) == BODY
