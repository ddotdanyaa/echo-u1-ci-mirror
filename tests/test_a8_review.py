"""A8: an independent review of the merge of H6, T1 and Q1 (cloud_context/diffs/h5_to_integ.diff): what no branch alone could see. Every suspicion is a test on the real code (the rigs of H3/H4/H5/Q1:
the real NativeMediaSocket, ShadowEar and ControlledMedia on the injected clock, the cloud's events and the job's stream scripted). A test that needs a patch of controlled_media.py is xfail(strict=True) with its finding
number (A8-N), the patch is in cloud_context/reports/a8-review.md. No network, no sleep: nothing here is a measurement of a call.
"""
import pytest

import helpers_s6_state as S
from test_h3_tempo import TICK, call                  # noqa: F401 - call is the fixture
from test_h4_ear_first import final, speaks
from test_h5_live import LIVE


@pytest.fixture
def maths(call):
    def make(rule_two=True, **profile):
        rig = call(fast_text='on', **profile)
        if not rule_two:
            rig.c.prepared_job = None      # rule 2 (the ear opens on the job prepared on its text) has no key since f84a05a9: ``fast_text.for_call`` gives the controller the look at the job, nothing else makes it act
        return rig
    return make


# =====================================================================================================================================
# 1. quick_math: the last number the ear misheard, and a partial of the cloud that stops inside that number
# =====================================================================================================================================

@pytest.mark.parametrize('ear,head,rest,whole,spoken', [
    ('пять на пять', 'Пять на пять', 'десят', 'Пять на пятьдесят', 'Двести пятьдесят.'),
    ('семь на шесть', 'Семь на шесть', 'сот', 'Семь на шестьсот', 'Семь на шестьсот — четыре тысячи двести.'),      # U43(a), commit 832d0778: two witnesses that differ: the operands are named
    ('сто плюс два', 'Сто плюс два', 'дцать', 'Сто плюс двадцать', 'Сто плюс двадцать — сто двадцать.'),      # U43(a), commit 832d0778
], ids=lambda value: value.replace(' ', '_'))
def test_a_partial_cut_inside_the_last_number_is_no_second_witness(maths, ear, head, rest, whole, spoken):
    """The ear lost the end of the last word («пятьдесят» -> «пять»), the cloud's partial stops at a token inside the same word: both read the same figure, and it is wrong.
    U43 (a): where the two witnesses still differ on a number in the final, the figure names its operands («Семь на шестьсот — четыре тысячи двести.»): the figure is the final's, and a wrong one is heard."""
    rig = maths()
    ended = speaks(rig, ear, turn='u1', announced=1.0, speech=1.5)
    rig.pump(max(0.0, ended + 1.06 - rig.w.clock.t))
    rig.w.feed(S.turn_delta('u1', head, 1))
    rig.pump(TICK)
    rig.w.feed(S.turn_delta('u1', rest, 2))
    rig.pump(max(0.0, ended + 2.2 - rig.w.clock.t))
    final(rig, 'u1', whole)
    assert rig.said()[:1] == [spoken], f'the first figure in the earpiece is that of the final: {rig.said()}'


@pytest.mark.parametrize('text', ['сколько будет пять на пять', 'сколько будет сорок восемь умножить на десять'])
def test_a_sum_the_code_answers_asks_the_model_for_nothing(maths, text):
    """Q1 kept ``prefetch_candidate`` from the base and the code (``_reference``); H1's ``fast_prepare`` was not told: each sum the ear hears costs a request the call throws away (T2 ran into HTTP 429)."""
    rig = maths()
    speaks(rig, text, turn='u1', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_delta('u1', text, 1))
    rig.pump(1.0)
    final(rig, 'u1', text)
    assert len(rig.said()) == 1, 'precondition: the code answered'
    assert rig.fake.runs == [], 'no request of the model'


# =====================================================================================================================================
# 2. H6 x Q1: a final later than EAR_FINAL_SECONDS, the ear stands in for it (``_ear_final_due``), and the code works out a figure of the ear's words alone
# =====================================================================================================================================

def late_final(rig, ear, partial, *, at=4.6):
    """The ear's text, the cloud's partial (none when empty) about a second after the end of speech, its final ``at`` seconds after it: past EAR_FINAL_SECONDS (4.0; the cloud came up to 3.7 s behind the ear)."""
    ended = speaks(rig, ear, turn='u1', announced=1.0, speech=1.5)
    if partial:
        rig.pump(max(0.0, ended + 1.06 - rig.w.clock.t))
        rig.w.feed(S.turn_delta('u1', partial, 1))
    rig.pump(max(0.0, ended + at - rig.w.clock.t))
    return ended


@pytest.mark.parametrize('rule_two', [True, False])
def test_a_late_final_the_partial_contradicts_is_no_figure_of_the_ear(maths, rule_two):
    """Q1: «two witnesses of every number». The cloud's partial named another sum, so H4 held the figure; 4 s on, H6 made the ear's text the final of the cloud's open turn: the code said «Тридцать.», and the right final
    found its turn closed and was dropped."""
    rig = maths(rule_two=rule_two)
    late_final(rig, 'пять на шесть', 'Пять на пять')
    assert rig.said() == [], 'the cloud says another number: the ear alone cues no figure'
    final(rig, 'u1', 'Пять на пять')
    rig.pump(1.0)
    assert rig.said() == ['Двадцать пять.'], 'the final is judged'


def test_a_late_final_with_no_word_of_the_cloud_is_no_figure_of_the_ear(maths):
    """Q1 pinned «with no word of the cloud the ear alone cues no figure» for H4; H6's stand-in reaches the code with the ear's words alone."""
    rig = maths()
    late_final(rig, 'пять на шесть', '')
    assert 'Тридцать.' not in rig.said()


def test_a_late_final_the_partial_contradicts_reaches_the_job(call):
    """The same without the code: the job ran on the ear's «сорок», the ledger closed the cloud's open turn with the ear's words, and the final «четырнадцать» never reached anybody."""
    rig = call(**LIVE)
    late_final(rig, 'сколько стоит сорок метров кабеля', 'Сколько стоит четырнадцать метров кабеля')
    final(rig, 'u1', 'Сколько стоит четырнадцать метров кабеля?')
    rig.pump(TICK * 2)
    assert any('четырнадцать' in run.question for run in rig.fake.runs), [run.question for run in rig.fake.runs]


def test_a_late_final_the_partial_confirms_is_the_figure(maths):
    """The neighbour that must stay: both witnesses name it."""
    rig = maths()
    late_final(rig, 'пять на пять', 'Пять на пять')
    assert list(dict.fromkeys(rig.said())) == ['Двадцать пять.'], rig.said()      # w3-integ: since H7 the ear's tempo says the unconfirmed figure again 2.6 s on (reason=ear_tempo): one answer, as in the 240 orders above


# =====================================================================================================================================
# 3. H6 item 3 (``also``) x a new question: the ear's words of an older question reach the job as the second recording of this one
# =====================================================================================================================================

from test_h6 import input_of                          # noqa: E402

OLD = 'сколько начислят на сто тысяч под десять процентов за два года'


def test_the_words_of_an_older_question_are_no_second_recording_of_a_new_one(call):
    """The ear heard the first question; the second has no text of the ear (the recognizer dropped it, or its text comes after the final). ``_ear_words`` names the newest piece that shares a word or a number with
    the final, of any age: the job was told «Распознано: под двадцать процентов? / … под десять процентов …», two recordings of one utterance with another number."""
    rig = call(**LIVE)
    rig.says(OLD, speech=2.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', OLD.capitalize()))
    rig.pump(TICK * 2)
    rig.job_says(0, 'Двадцать тысяч рублей.')
    rig.job_ends(0)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u2', 'user', 'Двадцать'))
    rig.w.feed(S.turn_done('u2', 'user', 'Двадцать тысяч рублей'))
    rig.pump(15.0)
    rig.onset()
    rig.pump(1.2)
    rig.offset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.pump(1.5)
    rig.w.feed(S.turn_done('u3', 'user', 'А под двадцать процентов?'))
    rig.pump(TICK * 2)
    assert len(rig.fake.runs) == 2, 'precondition: the new question has its job'
    assert 'десять' not in input_of(rig, 1), input_of(rig, 1)


# =====================================================================================================================================
# 4. the base (or the code) and a prepared job on one question: one answer, whatever the order of the ear, the partial, the final and the job
# =====================================================================================================================================

import itertools                                      # noqa: E402

ONE_ANSWER_CASES = [('пять на пять', 'Пять на пять', 'Двадцать пять.'), ('сколько будет пять на пять', 'Сколько будет пять на пять?', 'Двадцать пять.'),
                    ('семнадцатая статья налогового кодекса', 'Семнадцатая статья Налогового кодекса', 'Статья 17 Налогового кодекса')]
ONE_ANSWER_GRID = list(itertools.product(range(len(ONE_ANSWER_CASES)), [0.5, 1.06, 2.0, None], [1.5, 2.2, 3.5, 4.6, 6.0], [True, False], [0.3, 1.0]))


@pytest.mark.parametrize('case,partial_at,final_at,rule_two,job_at', ONE_ANSWER_GRID)
def test_the_base_and_a_prepared_job_give_one_answer(maths, case, partial_at, final_at, rule_two, job_at):
    """No defect: every job the call made is let say another answer as soon as it may; only the base's or the code's is heard, and only one. ``partial_at``/``final_at``: seconds after the end of speech."""
    ear, cloud, answer = ONE_ANSWER_CASES[case]
    rig = maths(rule_two=rule_two)
    ended = speaks(rig, ear, turn='u1', announced=1.0, speech=1.5)
    for at, kind in sorted([(final_at, 'final')] + ([(partial_at, 'partial')] if partial_at is not None and partial_at < final_at else [])):
        rig.pump(max(0.0, ended + at - rig.w.clock.t))
        rig.w.feed(S.turn_delta('u1', cloud, 1) if kind == 'partial' else S.turn_done('u1', 'user', cloud))
    rig.pump(job_at)
    for n, run in enumerate(rig.fake.runs):
        if not run.cancelled.is_set():
            rig.job_says(n, 'Ответ задания. Он другой.')
            rig.job_ends(n)
    rig.pump(1.0)
    assert list(dict.fromkeys(rig.said())) == [answer], rig.said()


# =====================================================================================================================================
# 5. a new question, STOP: nothing of the old answer comes late (no defect: these pin the merged order)
# =====================================================================================================================================

import asyncio                                        # noqa: E402

from test_h5_live import asked, cloud                 # noqa: E402

INERTIA = 'Инерция — это свойство тела сохранять скорость.'
MORE = ' Её открыл Галилей. Ньютон записал это первым законом.'


def test_the_job_of_the_old_question_is_cancelled_by_the_new_one(call):
    rig = call(**LIVE)
    asked(rig, 'Что такое инерция')
    rig.pump(0.5)
    asked(rig, 'В каком году было крещение Руси', uid='u2')
    assert rig.fake.run(0).cancelled.is_set() and not rig.fake.run(1).cancelled.is_set()
    rig.job_says(1, 'Крещение Руси было в 988 году.')
    rig.job_ends(1)
    rig.pump(0.5)
    assert rig.said() and all('988' in said for said in rig.said())


def test_a_lookup_of_the_old_question_that_comes_after_the_new_one_starts_nothing(call):
    rig = call(**LIVE)
    gate = asyncio.Event()

    async def slow(question):
        rig.w.lookup_calls.append(question)
        await gate.wait()
        return list(S.SOURCE_ROWS)
    rig.w.wire.lookup = rig.w.wire.early.fetch = slow
    asked(rig, 'Какая сейчас ключевая ставка Банка России')
    rig.pump(0.5)
    asked(rig, 'Что такое инерция', uid='u2')
    rig.pump(0.3)
    gate.set()
    rig.pump(0.5)
    assert [run.question for run in rig.fake.runs] == ['Что такое инерция'], 'no job of the sources of the old question'
    rig.job_says(0, INERTIA)
    rig.job_ends(0)
    rig.pump(1.0)
    assert rig.said() and all('ставк' not in said for said in rig.said())


def test_a_stop_of_the_ear_keeps_the_rest_of_the_job_and_the_clouds_text_out(call):
    rig = call(**LIVE)
    asked(rig, 'Что такое инерция')
    rig.job_says(0, INERTIA)
    first = list(rig.said())
    rig.pump(0.5)
    rig.says('стоп', speech=0.5)
    rig.pump(0.5)
    assert rig.c.state().get('paused') is True
    rig.job_says(0, MORE)
    rig.job_ends(0)
    cloud(rig, 'a1', 'Инерция это когда тело сохраняет скорость.')
    rig.pump(2.0)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Стоп'))
    rig.pump(10.0)
    assert rig.said() == first


def test_a_stop_before_the_first_cue_lets_nothing_of_the_job_or_the_cloud_through(call):
    rig = call(**LIVE)
    asked(rig, 'Что такое инерция')
    rig.pump(0.3)
    rig.says('стоп', speech=0.5)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Стоп'))
    rig.pump(0.5)
    assert rig.fake.run(0).cancelled.is_set() and rig.c.question_id is None
    cloud(rig, 'a1', 'Инерция это когда тело сохраняет скорость.')
    rig.pump(10.0)
    assert rig.said() == []


def test_a_stop_that_waits_for_the_end_of_speech_lets_no_new_portion_through_meanwhile(call):
    """H6 item 5 holds a «стоп» while the ear hears speech go on: the job's later text must not reach the earpiece in that wait."""
    rig = call(**LIVE)
    asked(rig, 'Что такое инерция')
    rig.job_says(0, INERTIA)
    first = list(rig.said())
    rig.pump(0.5)
    uid = rig.onset()
    rig.pump(0.6)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Стоп'))
    rig.pump(TICK)
    assert rig.c.fast_mark is not None, 'precondition: the stop waits'
    rig.job_says(0, MORE)
    rig.job_ends(0)
    rig.pump(2.5)
    assert rig.said() == first
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'стоп не надо дальше я сам')
    rig.pump(10.0)
    assert rig.said() == first and rig.c.state().get('paused') is True


# =====================================================================================================================================
# 6. a prepared job (the ear's words) and a final with the other scope of «не»: the A2 defect of ``same_question``, end to end through the merge
# =====================================================================================================================================

def test_a_job_prepared_on_the_other_scope_of_not_is_not_adopted(call):
    """The order (5.1) had the unit probe only: «выдача неправильного звука целиком пока НЕ воспроизведена». Here it is: the ear heard «не нагревать, а охлаждать», the cloud's final says «нагревать, а не охлаждать»,
    the release adopts the job of the ear's words and its answer is the first cue."""
    rig = call(fast_text='on')
    speaks(rig, 'почему нужно не нагревать а охлаждать эту жидкость при таком давлении', turn='u1', announced=1.0, speech=2.5)
    rig.pump(0.3)
    assert [run.question for run in rig.fake.runs] == ['почему нужно не нагревать а охлаждать эту жидкость при таком давлении'], 'precondition: the ear prepared it'
    final(rig, 'u1', 'Почему нужно нагревать, а не охлаждать эту жидкость при таком давлении?', after=0.2)
    assert rig.fake.run(0).cancelled.is_set() and len(rig.fake.runs) == 2 and 'а не охлаждать' in rig.fake.run(1).question, 'the final asks its own job'


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
