"""fix-c20 (the coordinator): the first portion is at most 9 words and ends on a finished thought. G15 (``first_useful._finish_thought``) lengthens a cue to
its sentence end; a sentence end that would make the portion longer than 9 words is not taken: the cue stays as the window cut it. The R21 table on both channels.
A question for a number (C7-A) or with a condition (R21-05) keeps the owner's wider window (``portioner.first_window(number=True)``, 12 words): the number with its
unit, the verdict with its qualifier; g15 never takes a portion past it."""
import re

import pytest

from helpers_r21_first import first_portion
from helpers_r21_table import ROWS

# a number written in groups («300 000») is one word: it is said as one number
_WORD = re.compile(r"\d[\d  ]*\d|[^\W_]+(?:[-’'][^\W_]+)*")
FIRST_MAX = 9


def count(text):
    return len(_WORD.findall(text))


@pytest.mark.parametrize('fast', [False, True], ids=['cloud', 'fast'])
def test_no_first_portion_of_the_table_is_longer_than_nine_words(fast):
    from echo_sync.first_useful import asks_for_number, asks_with_condition
    from echo_sync.portioner import first_window
    from echo_sync.settings import CALL_SETTINGS
    wide, _ = first_window(CALL_SETTINGS, number=True)
    long = []
    for row in ROWS:
        if row.silent:
            continue
        cue = first_portion(row.question, row.answer, fast=fast).cue
        if cue and count(cue) > (wide if asks_for_number(row.question) or asks_with_condition(row.question) else FIRST_MAX):
            long.append((row.id, count(cue), cue))
    assert long == [], (len(long), long[:10])


def test_g15_still_finishes_a_thought_that_fits():
    from echo_sync.first_useful import _finish_thought
    text = 'ПКО КО-1 — приходный кассовый ордер, по нему принимают наличные.'
    assert _finish_thought(text, 'ПКО КО-1 — приходный кассовый ордер,', final=True, last=True) == text


def test_a_thought_that_would_run_past_nine_words_is_not_finished():
    from echo_sync.first_useful import _finish_thought
    text = 'Первая мировая война началась 28 июля 1914 года, после убийства эрцгерцога Франца Фердинанда.'
    cue = 'Первая мировая война началась 28 июля 1914 года,'
    assert _finish_thought(text, cue, final=True, last=True) == cue
    assert _finish_thought(text[:len(cue) + 10], cue, final=False, last=False) == cue      # nothing is waited for that could not be taken
