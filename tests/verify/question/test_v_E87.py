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
# The forms a JOB serves (a knowledge question): a stable partial of them gets a prepared job. The arithmetic forms and the word problem are the code's (``local_reference`` / ``word_problem``): no job is prepared for them, so they have their own test below.
QUESTION_FORM = ('dates', 'unit-order', 'unit-money', 'who-killed-whom', 'pushkin-lermontov', 'planets', 'ticket-from-to')
ROWS = [row for row in REFUSE if row[0] in QUESTION_FORM]
CODE_FORM = ('divide', 'minus')
CODE_ROWS = [row for row in REFUSE if row[0] in CODE_FORM]
KEEP = ('question-mark', 'leading-so', 'year-ordinal', 'capital')
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
    assert len(ROWS) == len(QUESTION_FORM) and len(CODE_ROWS) == len(CODE_FORM) and len(CONTROL) == len(KEEP), (len(ROWS), len(CODE_ROWS), len(CONTROL))


@pytest.mark.parametrize('name, heard, final', ROWS, ids=[row[0] for row in ROWS])
@pytest.mark.parametrize('direction', ['as_written', 'turned'])
def test_the_job_prepared_for_one_reading_is_never_said_for_the_other(call, name, heard, final, direction):
    first, second = (heard, final) if direction == 'as_written' else (final, heard)
    rig, prepared = prepared_then_final(call, first, second)
    assert prepared == 1, 'precondition: the stable partial got a job (prepare_wide on)'
    assert ANSWER_A not in rig.said(), f'the answer of {first!r} was said for {second!r}'
    assert len(rig.fake.runs) == prepared + 1, 'a job was asked on the final\'s own words'
    job_answers(rig, len(rig.fake.runs) - 1, ANSWER_B)
    rig.pump(1.0)
    assert ANSWER_B in rig.said() and ANSWER_A not in rig.said(), rig.said()


@pytest.mark.parametrize('name, heard, final', CONTROL, ids=[row[0] for row in CONTROL])
def test_the_same_question_said_another_way_still_adopts_the_prepared_job(call, name, heard, final):
    rig, prepared = prepared_then_final(call, heard, final)
    assert prepared == 1
    assert rig.said() == [ANSWER_A] and rig.fast.count == 1, (rig.said(), rig.fast.count)


WIDE_OFF = [row for row in ROWS if row[0] != 'ticket-from-to']      # a price is data that changes: the lookup route says its own line before the job's answer, with the switch off


@pytest.mark.parametrize('name, heard, final', WIDE_OFF, ids=[row[0] for row in WIDE_OFF])
def test_with_prepare_wide_off_the_final_gets_its_own_job_and_only_its_answer_is_said(call, name, heard, final):
    rig, prepared = prepared_then_final(call, heard, final, wide=False)
    assert prepared == 0, 'no preparation on a partial'
    assert len(rig.fake.runs) == 1
    job_answers(rig, 0, ANSWER_B)
    rig.pump(1.0)
    assert rig.said() == [ANSWER_B]


@pytest.mark.parametrize('late', ['Сколько дней с 3 мая по 17 июня, нет, по 18 июня', 'Сколько дней с 3 мая по 17 июня, нет, не по 17 июня, а по 20 июня'])
def test_a_late_correction_in_the_final_takes_the_prepared_job_back(call, late):
    """The late edit of the backlog: the partial was «с 3 мая по 17 июня», the final corrects it."""
    rig, prepared = prepared_then_final(call, 'Сколько дней с 3 мая по 17 июня', late)
    assert prepared == 1
    assert ANSWER_A not in rig.said(), 'the prepared answer was said after the listener changed the numbers'
    assert len(rig.fake.runs) == prepared + 1


@pytest.mark.parametrize('name, heard, final', CODE_ROWS, ids=[row[0] for row in CODE_ROWS])
def test_the_code_answers_the_numbers_of_the_final_and_no_job_is_prepared_for_them(call, name, heard, final):
    """The arithmetic forms of the table never reach a prepared job: the code reads the numbers of the final in their own order, so the two readings say two different answers and no job's answer is there to be taken."""
    said = []
    for ear_text, final_text in ((heard, final), (final, heard)):
        rig, prepared = prepared_then_final(call, ear_text, final_text)
        assert prepared == 0 and not rig.fake.runs, 'no job is prepared for an arithmetic form'
        assert len(rig.said()) == 1 and ANSWER_A not in rig.said(), rig.said()
        said.append(rig.said()[0])
    assert said[0] != said[1], f'{name}: the two readings got one answer: {said}'
