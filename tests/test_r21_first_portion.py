"""R21 (work order 5.1): the first thing the listener hears is a short, right gist - the year for «когда», the number with its unit, a negation, a condition,
never a bare «Да.» for a conditional question, never the question read back, never scaffolding - and what follows never takes it back or holds it up.

The table (tests/helpers_r21_table.py, 300+ rows) is written by hand from the texts: for each question and answer the first portion a person would cut, the
fragments it must hold (``want``) and the first portions that are not allowed (``bad``). The functions are the production ones, in the order ControlledMedia
calls them (tests/helpers_r21_first.py): the answer arrives a word at a time, is cleaned (``strip_process_prefix``, ``drop_process_sentences``, ``definition_body``,
``compact_opening``), ``first_cue`` chooses, ``EchoEngine._portions_after`` cuts the rest. The same rows run for the cloud and for the text channel (digits, ``patient``).

A row that the code still gets wrong is ``xfail(strict=True)`` under its finding (``FINDINGS``): the day a fix makes it pass, strict xfail fails and the row leaves
the list in the same commit. Nothing here measures time: «lag» is counted in words of the answer that had arrived beyond the cue, never in seconds.
"""
from __future__ import annotations

import re

import pytest

from echo_sync.first_useful import asks_for_number, asks_with_condition
from echo_sync.portioner import first_window
from echo_sync.settings import CALL_SETTINGS
from helpers_r21_first import after, first_portion, normal, words
from helpers_r21_table import ROWS, violations

# finding -> the rows (both channels, unless PASSING says one passes) that the code still gets wrong. The text of each finding and its cause: cloud_context/reports/r21-core.md
# c20-first-cue (07.11): G15 (first_useful._finish_thought, e465c7e) lengthens a first portion to the end of its thought, and with the
# word cap it now has (``_portion_cap_holds``) it makes cond-094, neg-143, ref-276 and why-212 right. Their entries leave the list in
# the same commit, as the rule above says. They were already XPASS(strict) on master at d764fa0, where G15 had no cap: the file has been
# red since e465c7e (8 strict XPASS) and no one took them out.
FINDINGS = {
    'R21-08 the first window (8 words) and the cost of a 2-word tail decide: the verdict and the question read back, the correction in the next portion':
        ('cond-108', 'neg-137'),
    'R21-10 a reference header that the window cannot hold with its content (digits weigh like the words they are said as)': ('ref-273',),
    'R21-11 a why/how cue that the cost model cuts before the number, the object or the second half': ('why-207', 'why-211', 'why-216'),
    'R21-12 the text channel drops a whole answer that opens with «Скажу честно:»': ('lead-255',),
}
KNOWN = {row: finding for finding, rows in FINDINGS.items() for row in rows}
PASSING = {('lead-255', 'cloud'), ('ref-273', 'fast')}        # the one channel in which such a row is already right


def _param(row, known):
    out = []
    for mode in ('cloud', 'fast'):
        marks = []
        if known and row.id in KNOWN and (row.id, mode) not in PASSING:
            marks.append(pytest.mark.xfail(strict=True, reason=KNOWN[row.id]))
        out.append(pytest.param(row, mode == 'fast', id=f'{row.id}-{mode}', marks=marks))
    return out


SPOKEN = [case for row in ROWS if not row.silent for case in _param(row, False)]
GIST = [case for row in ROWS if not row.silent for case in _param(row, True)]


def test_the_table_is_what_the_work_order_asks_for():
    classes = {row.cls for row in ROWS}
    assert len(ROWS) >= 300
    assert len({(row.question, row.answer) for row in ROWS}) == len(ROWS)
    assert {'date', 'qty', 'cond', 'neg', 'qual', 'name', 'why', 'calc', 'choice', 'lead', 'stall', 'ref', 'en', 'multi', 'tail'} <= classes
    assert sum(1 for row in ROWS if row.silent) >= 6
    assert all(row.bad or row.silent or row.cls in ('name', 'choice', 'calc', 'qual', 'neg', 'why', 'cond', 'date', 'lead', 'ref', 'multi', 'tail', 'en', 'qty') for row in ROWS)


@pytest.mark.parametrize('row', [row for row in ROWS if not row.silent], ids=lambda row: row.id)
def test_the_table_agrees_with_itself(row):
    """The ideal portion passes the oracle that judges the code; every fragment asked for stands in the answer; every forbidden portion is a real cut of it."""
    whole = first_portion(row.question, row.answer).whole
    assert violations(row, row.ideal, whole) == []
    for item in row.want:
        assert normal(item) in normal(row.answer), item
    raw, clean = [normal(w) for w in words(row.answer)], [normal(w) for w in words(whole)]
    for item in row.bad:
        if item.startswith('~'):
            continue
        cut = [normal(w) for w in words(item)]
        assert raw[:len(cut)] == cut or clean[:len(cut)] == cut, f'«{item}» is no start of the answer'
        assert normal(item) != normal(row.ideal), f'«{item}» is the ideal portion'


@pytest.mark.parametrize('row', [row for row in ROWS if row.silent], ids=lambda row: row.id)
def test_scaffolding_alone_is_not_a_portion_to_speak(row):
    for fast in (False, True):
        assert first_portion(row.question, row.answer, fast=fast).cue is None


@pytest.mark.parametrize('row,fast', GIST)
def test_the_first_portion_is_the_right_gist(row, fast):
    found = first_portion(row.question, row.answer, fast=fast)
    assert violations(row, found.cue, found.whole) == [], f'{found.cue!r} after {found.arrived} of {found.total} words'


@pytest.mark.parametrize('row,fast', SPOKEN)
def test_the_rest_of_the_answer_is_what_was_not_said(row, fast):
    """Continuation: the portions after the first, joined to it, are the answer as it was cleaned - no word lost, none invented, numbers and negations in place."""
    found = first_portion(row.question, row.answer, fast=fast)
    if found.cue is None:
        pytest.skip('no first portion')
    portions = [found.cue] + after(found.cue, found.whole)
    assert [normal(w) for w in words(' '.join(portions))] == [normal(w) for w in words(found.whole)]
    assert ' '.join(' '.join(portions).split()) == ' '.join(found.whole.split())
    for item in re.findall(r'\d[\d ,.:-]*\d|\d|\b(?:не|нет|нельзя|ни|no|not)\b', found.whole, re.I):
        assert ' '.join(portions).count(item) == found.whole.count(item), item


@pytest.mark.parametrize('row', [row for row in ROWS if not row.silent], ids=lambda row: row.id)
def test_the_first_portion_does_not_wait_for_the_continuation(row):
    """The cloud's stream: the window of the first portion (8 words, 12 for a question for a number) is all it ever waits for: the word after the window is whole
    once the one after it has begun (+2), never the rest of the answer. (The text channel, ``patient``, waits for the end of a job a moment away when its head only
    repeats the question: H5 item 5, by design.)"""
    found = first_portion(row.question, row.answer)
    if found.cue is None:
        pytest.skip('no first portion')
    window, _ = first_window(CALL_SETTINGS, number=asks_for_number(row.question) or asks_with_condition(row.question))   # R21-05: a verdict takes its qualifier along
    assert len(words(found.cue)) + found.lag <= window + 2, f'{found.cue!r} waited for {found.lag} words beyond it'
