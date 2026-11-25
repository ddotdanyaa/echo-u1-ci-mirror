"""G32: the time to the first cue of the model, step by step (``tools/replay/first_clock.py``), and every wait with a reason. Numbers and «не» are not weakened.

Times are the stand's (the cloud's final 1.5 s after the speech, the model's first text 0.6 s after its job), not a laptop's nor a phone's.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echo_sync import two_witnesses as W                                         # noqa: E402
from tools.replay import first_clock as F                                       # noqa: E402
from tools.replay import stand as A                                             # noqa: E402


def stable(*texts):
    """The stable piece after the cloud's open turn grew through ``texts`` and then held the last one (a pause)."""
    p = W.Pieces()
    for text in texts:
        p.feed('t', text)
    return p.feed('t', texts[-1], still=True)


# --- 1. a number closed by «?» at the end of the cloud's open turn is the cloud's ---------------------------------------------------------

def test_a_number_closed_by_a_question_mark_is_stable():
    assert stable('Сколько', 'Сколько будет 4', 'Сколько будет 4 умножить на', 'Сколько будет 4 умножить на 8?').endswith('на 8')


def test_the_ear_and_the_closed_turn_agree_on_both_numbers():
    piece = stable('Сколько', 'Сколько будет 4', 'Сколько будет 4 умножить на', 'Сколько будет 4 умножить на 8?')
    assert W.verdict('сколько будет четыре умножить на восемь', piece) == W.SOUND


@pytest.mark.parametrize('texts', [
    ('Сколько', 'Сколько будет 4 умножить на 8'),            # no mark: «8» may still be «80»
    ('Сколько', 'Сколько будет 4 умножить на 2,'),           # a comma: «2,5»
    ('Сколько', 'Сколько будет 4 умножить на 2.'),           # a point: «2.5»
    ('Нужно', 'Нужно не'),                                  # «не» at the end
    ('Нужно', 'Нужно не?'),                                 # «не» is never closed by a mark here: the next word is what is denied
])
def test_an_open_number_or_a_negation_still_waits(texts):
    piece = stable(*texts)
    assert not W.norm_words(piece) or W.norm_words(piece)[-1] not in ('8', '2', 'не'), piece


def test_another_number_in_the_closed_turn_cuts():
    piece = stable('Сколько', 'Сколько будет 4 умножить на', 'Сколько будет 4 умножить на 9?')
    assert W.verdict('сколько будет четыре умножить на восемь', piece) == W.CUT


# --- 2. the stand: the clock of a clean question ----------------------------------------------------------------------------------------

SEEDS = range(40)


@pytest.fixture(scope='module')
def clock():
    return F.table(SEEDS)


def test_every_first_cue_is_right_and_no_invariant_breaks(clock):
    rows, _ = clock
    assert [r['seed'] for r in rows if not r['right']] == []
    assert [(r['seed'], r['violations']) for r in rows if r['violations']] == []


def test_arithmetic_heard_whole_by_both_does_not_wait_for_the_final(clock):
    """The ear's text and the cloud's open turn «… на 8?» both have the question, the job's answer is there 0.6 s after the ear: no reason to wait 1.5 s for the final."""
    rows, _ = clock
    late = [(r['seed'], r['cue'], r['final']) for r in rows if r['question'].startswith('Сколько будет') and r['cue'] >= r['final']]
    assert late == []


def test_the_steps_are_recorded(clock):
    rows, med = clock
    assert all(r['cue'] is not None for r in rows)
    assert med['ear'] < med['final'] and med['text'] <= med['cue']


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
