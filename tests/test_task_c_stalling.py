"""WAVE 2 / Task C-seg, item 5: a stalling phrase is not a cue.

Live evidence 2026-11-02 00:05 (corpus run 20261102-000520, lookup_law_article): the model announced «Понял, сейчас
быстро проверю и скажу.» and ECHO made «Понял, сейчас быстро» the first cue, so the listener was asked to repeat a
promise. Fix round 2 already strips whole stalling sentences (textutil.strip_process_prefix); this module checks that
the same mechanism now covers that opener, and that real answers are left alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                           # noqa: E402
from echo_sync.textutil import strip_process_prefix                  # noqa: E402

LIVE = 'Понял, сейчас быстро проверю и скажу. Статья 421 ГК РФ устанавливает принцип свободы договора: граждане'
LIVE_BODY = 'Статья 421 ГК РФ устанавливает принцип свободы договора: граждане'


def test_the_live_stalling_opener_is_stripped():
    assert strip_process_prefix(LIVE) == LIVE_BODY


@pytest.mark.parametrize('text,body', [
    ('Понял, сейчас быстро проверю и скажу. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Понятно, сейчас проверю. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Хорошо, сейчас быстро уточню. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Секунду, сейчас найду информацию. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Одну секунду, проверю. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Посмотрю и скажу. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Сейчас гляну и отвечу. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Минуточку. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Понял. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Ясно, секундочку. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Принято, проверяю. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
    ('Понял, понял, сейчас проверю. Вода кипит при ста градусах.', 'Вода кипит при ста градусах.'),
])
def test_more_ways_to_stall_are_stripped(text, body):
    assert strip_process_prefix(text) == body


@pytest.mark.parametrize('text', [
    'Понятно, что вода кипит при ста градусах.',
    'Быстро проверили скорость света в XVII веке.',
    'Сейчас вода кипит при ста градусах.',
    'Секунду называют единицей времени.',
    'Минута состоит из шестидесяти секунд.',
    'Понял — это прошедшее время глагола.',
    'Ясно видно, что небо голубое.',
    'Принятое решение вступает в силу сразу.',
    'Хорошо проводит тепло металл.',
])
def test_real_content_that_looks_like_a_stall_is_left_alone(text):
    assert strip_process_prefix(text) == text


@pytest.mark.parametrize('how', ['words', 'chars5', 'chars1'])
def test_a_stall_is_never_the_first_cue_whatever_the_slicing(how):
    answer = 'Понял, сейчас быстро проверю и скажу. Металл намного лучше проводит тепло и забирает его у руки.'
    run = H.stream('Почему металлическая ложка кажется холоднее деревянной?', answer, how, walk=False)
    assert run.cues, 'the real answer after the stall must still be cued'
    spoken = ' '.join(run.chunks).casefold()
    for word in ('понял', 'сейчас', 'быстро', 'проверю', 'скажу'):
        assert word not in spoken, (word, run.chunks)
    assert 'металл' in run.cues[0].casefold()
    assert H.nospace(''.join(run.chunks)) == H.nospace('Металл намного лучше проводит тепло и забирает его у руки.')
