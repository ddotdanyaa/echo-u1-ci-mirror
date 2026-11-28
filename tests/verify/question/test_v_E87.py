"""V2 E87: another ROLE of the numbers or another «не» takes somebody else's prepared job (the head start). The table of A2 («было 80, потратил 20» against the same with 20 and 80; «не нагревать, а охлаждать» against «нагревать, а не охлаждать»)
decides at the unit level (``test_a2_same_question``, ``test_h7``); what the backlog still asks is the order through the CHANGE of hands: prepare -> the revision -> adopt/release -> the sound, at ``prepare_wide`` off and on.

Real ControlledMedia, NativeMediaSocket and FastText (rig ``call``): the cloud's stable partial (the words A) gets a prepared job, the job says its answer, the cloud's final (the words B) comes. A pair from the A2 table (both directions):
the answer prepared for A is NEVER said for B and a job is asked on B; the paraphrases of the same table still adopt the prepared job (the control). ``prepare_wide`` off: no job is prepared on a partial at all, the final's job answers it.
Not run on the laptop. A red row is a defect card for the family Q (``cm_question``/``question_part``) and for R (``fast_text``).
"""
import pytest

import helpers_s6_state as S
from echo_sync.textutil import normalize
from question_kit import TICK, WIDE, call, job_answers, partial      # noqa: F401 - call is the fixture
from test_a2_same_question import ACCEPT, REFUSE

ANSWER_A = 'Ответ приготовлен на первые слова.'
ANSWER_B = 'Ответ на слова из финала.'
QUESTION_FORM = ('number-swap-defect', 'divide', 'minus', 'percent-of', 'dates', 'deposit', 'who-has-what', 'whose-number', 'unit-order', 'unit-money', 'who-killed-whom', 'pushkin-lermontov', 'planets', 'ticket-from-to')
ROWS = [row for row in REFUSE if row[0] in QUESTION_FORM]
KEEP = ('question-mark', 'leading-so', 'number-words', 'capital')
CONTROL = [row for row in ACCEPT if row[0] in KEEP]


def prepared_then_final(call, ear_text, final_text, wide=True):
    rig = call(**(WIDE if wide else {'fast_text': 'on', 'ear': 'off'}))
    partial(rig, 'u1', ear_text)
    rig.pump(0.5)
    prepared = rig.fast.count
    if prepared:
        job_answers(rig, 0, ANSWER_A)
        rig.pump(TICK)
    rig.w.feed(S.turn_done('u1', 'user', final_text))
    rig.pump(TICK * 3)
    return rig, prepared


def test_the_rows_of_the_table_are_all_there():
    assert len(ROWS) == len(QUESTION_FORM) and len(CONTROL) == len(KEEP), (len(ROWS), len(CONTROL))


@pytest.mark.parametrize('name, heard, final', ROWS, ids=[row[0] for row in ROWS])
@pytest.mark.parametrize('direction', ['as_written', 'turned'])
def test_the_job_prepared_for_one_reading_is_never_said_for_the_other(call, name, heard, final, direction):
    first, second = (heard, final) if direction == 'as_written' else (final, heard)
    rig, prepared = prepared_then_final(call, first, second)
    # 26.11-5: a sum whose numbers are all in the question is worked out on the spot by quick_math, the cloud is not waited for.
    # Worked by hand (100/4 = 25, 4/100 = 0.04, 5-3 = 2, 3-5 = -2), never by the product: (the answer of the words as written, the answer of the final's words as written).
    worked = {'divide': ('Двадцать пять.', 'Ноль целых четыре сотых.'), 'minus': ('Два.', 'Минус два.')}
    if name in worked:       # the answer said is the one of the final's own words, never the one of the other reading
        own = worked[name][1 if direction == 'as_written' else 0]
        other = worked[name][0 if direction == 'as_written' else 1]
        assert prepared == 0, 'a sum the code works out has no job to prepare'
        assert len(rig.fake.runs) == 0, 'no job waits for the cloud on a sum the code works out'
        assert rig.said() == [own] and other not in rig.said(), (f'{second!r}: {rig.said()}')
        return
    assert prepared == 1, 'precondition: the stable partial got a job (prepare_wide on)'
    assert ANSWER_A not in rig.said(), f'the answer of {first!r} was said for {second!r}'
    assert len(rig.fake.runs) == prepared + 1, 'a job was asked on the final\'s own words'
    job_answers(rig, len(rig.fake.runs) - 1, ANSWER_B)
    rig.pump(1.0)
    assert ANSWER_B in rig.said() and ANSWER_A not in rig.said(), rig.said()


@pytest.mark.parametrize('name, heard, final', CONTROL, ids=[row[0] for row in CONTROL])
def test_the_same_question_said_another_way_still_adopts_the_prepared_job(call, name, heard, final):
    rig, prepared = prepared_then_final(call, heard, final)
    worked = {'number-words': 'Четыреста восемьдесят.'}      # 48*10 = 480, worked by hand (26.11-5)
    if name in worked:       # the same sum said in words and in figures is worked out by the code once: one spoken answer, no prepared job, no job at all
        assert prepared == 0 and rig.fast.count == 0 and len(rig.fake.runs) == 0, (prepared, rig.fast.count, len(rig.fake.runs))
        assert rig.said() == [worked[name]], rig.said()
        return
    assert prepared == 1
    assert rig.said() == [ANSWER_A] and rig.fast.count == 1, (rig.said(), rig.fast.count)


@pytest.mark.parametrize('name, heard, final', ROWS[:6], ids=[row[0] for row in ROWS[:6]])
def test_with_prepare_wide_off_the_final_gets_its_own_job_and_only_its_answer_is_said(call, name, heard, final):
    rig, prepared = prepared_then_final(call, heard, final, wide=False)
    assert prepared == 0, 'no preparation on a partial'
    if name == 'minus':       # 26.11-5: the final's sum «3 минус 5» is worked out on the spot (3-5 = -2), no job to wait for
        assert len(rig.fake.runs) == 0 and rig.said() == ['Минус два.'], (len(rig.fake.runs), rig.said())
        return
    assert len(rig.fake.runs) == 1
    job_answers(rig, 0, ANSWER_B)
    rig.pump(1.0)
    assert rig.said() == [ANSWER_B]


@pytest.mark.parametrize('late', ['Сколько будет восемьдесят разделить на четыре, нет, на пять', 'Сколько будет восемьдесят разделить на четыре, нет, не на четыре, а на два'])
def test_a_late_correction_in_the_final_takes_the_prepared_job_back(call, late):
    """The late edit of the backlog: the partial was «80 разделить на 4», the final corrects it."""
    rig, prepared = prepared_then_final(call, 'Сколько будет восемьдесят разделить на четыре', late)
    assert prepared == 1
    assert ANSWER_A not in rig.said(), 'the prepared answer was said after the listener changed the numbers'
    assert len(rig.fake.runs) == prepared + 1

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
