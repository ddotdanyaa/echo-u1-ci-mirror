"""W3 replays: the records of cloud_context/BACKLOG_ECHO.md (E34-E37, E42-E45, E10-E12, E17, E72, E73, E77, E26.2, E19.1, E89) as whole orders of events through the REAL
controller, ear, wire and fast-text channel (test_h3_tempo.Rig on the injected clock). SCRIPTED: the speech detector, the recognizer's worker, the cloud's events, the job's stream.
Each test is one record's order, not a rule of one phrase. A red one is ``xfail(strict=True)`` with the record's number, its first cause and the patch in reports/w3-replays.md.
What this proves is the logic: nothing here is a measurement of a call or a laptop.
"""
from helpers_fast_fake import two_asks
import re

import pytest

import helpers_s6_state as S
from echo_sync import controlled_host
from echo_sync import ear_shadow
from echo_sync import speech_text
from echo_sync import fast_text as FT
from echo_sync.classifier import analyze
from echo_sync.controlled_media import HOLD_BOUNDS, TEMPO_HOLD_SECONDS
from echo_sync.native_media_socket import ONSET_HOLD_MAX_S
from echo_sync.portioner import portions
from echo_sync.settings import TEMPO_REPEAT_SECONDS
from test_h1_fast_text import settled
from test_h3_tempo import GRID, TICK, Recognizer, call, in_flight       # noqa: F401 - call is the fixture
from test_h4_ear_first import slow
from test_h5_live import LIVE, asked, cloud, decisions, fails, piece, plan, said_to_the_room, spoken_failures
from test_h6 import BAPTISM, INERTIA, NOTICE, REMARK, RIGHT, TWO_NOTICE, errors, job_declines, plan_in_flight, remark
from test_h7 import CALL_1027, HEAD_89, NO_89, SAID_15, SAID_89, job_answers, said_with_a_delegation

WRONG_YEAR = 'Крещение Руси было в 1988 году.'
MATERIALS = 'Купили материалы за 10 000 рублей: дебет счёта материалов, кредит счёта денег.'
ACCOUNT = 'Как отразить покупку материалов'
AMORT = 'Что такое амортизация'
AMORT_ANSWER = 'Амортизация — постепенный перенос стоимости на расходы.'
CONDITIONS = ('Вклад сто тысяч рублей на два года под десять процентов годовых, нет, не под десять, а под двадцать, проценты простые, сколько начислят')
INTEREST = 'Проценты составят 40 000 рублей за 2 года.'


def user_turn(rig, uid, text, wait=0.5, partial=False):
    """The cloud's user turn: its start, ``wait`` seconds, its final. ``partial``: it first announces itself with the words so far (what marks the announcement)."""
    rig.w.feed(S.turn_created(uid, 'user', ''))
    if partial:
        rig.w.feed(S.turn_delta(uid, text.split()[0], 1))
    rig.pump(wait)
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK * 2)


LONG = b'\x00\x40' * 72000          # three seconds of voiced sound


def playing(rig, answer=TWO_NOTICE, uid='u0'):
    """The first cue of the answer is in flight (3 s of voice), heard from its first frame; the world's cue window is the wire's own."""
    rig.w.wire.synthesize = lambda text: _voice(LONG)
    rig.w.feed(S.turn_created(uid, 'user', 'Что'))
    rig.w.feed(S.turn_done(uid, 'user', 'Что такое инерция'))
    rig.job_says(0, answer)
    rig.fake.run(0).finish()
    settled(rig.fast)
    return in_flight(rig)


async def _voice(pcm):
    return pcm


def the_job_text(rig, n):
    """What the speaker said, of the job's input (with an answer in play the job also gets «Вопрос / Твой ответ» above it)."""
    return rig.fake.run(n).question.rsplit('Сейчас прозвучало: ', 1)[-1]


def heard(rig, key):
    return any(key in text for text in rig.said())


# =====================================================================================================================================
# E34: the cloud's text is no answer without a job
# =====================================================================================================================================

def test_e34_year_question_cloud_yes_then_job_fails_then_second_job_answers(call):
    """n1_04 step 10 in full: the question of a year, the cloud's «Да.» and its wrong year, the first job fails, the second answers: only the job's year is heard."""
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    cloud(rig, 'a1', 'Да.')
    cloud(rig, 'a2', WRONG_YEAR)
    rig.pump(2.0)
    assert 'Да.' not in rig.said() and WRONG_YEAR not in rig.said(), 'the cloud has no word without a job'
    assert rig.fake.run(0).question == BAPTISM, 'the job is asked'
    fails(rig, 0)
    rig.job_says(1, RIGHT)
    rig.job_ends(1)
    rig.pump(TICK * 3)
    heard = ' '.join(rig.said())
    assert '988' in heard and '1988' not in heard and 'Да.' not in rig.said() and not spoken_failures(rig)


def test_e34_the_cloud_yes_to_a_year_with_two_timer_repeats_is_not_said_at_all(call):
    """c14 had «Да.» and two repeats of it by the timer: nothing is a portion, so no timer."""
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    cloud(rig, 'a1', 'Да.')
    rig.pump(TEMPO_REPEAT_SECONDS * 3 + 4.0)
    assert rig.said().count('Да.') == 0 and not (rig.c.state() or {}).get('chunks')


# =====================================================================================================================================
# E35: the old plan does not come back by itself
# =====================================================================================================================================

def test_e35_plan_job_declines_a_remark_the_old_plan_stays_where_it_is(call):
    """n1_03 steps 9-18: a plan, a remark in the form of a question 32 s later, the job declines it: the old portion (older than 30 s) is not said again over it."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.c.max_auto_repeats = 0
    rig.pump(32.0)
    remark(rig, 'u1', 1)
    rig.pump(10.0)
    assert rig.said() == [NOTICE]
    assert rig.c.state()['history'][-1]['status'] == 'interrupted'


def test_e35_a_new_answer_is_not_followed_by_the_old_plan(call):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    user_turn(rig, 'u1', AMORT)
    rig.job_says(1, AMORT_ANSWER)
    rig.job_ends(1)
    rig.pump(3.0)
    assert heard(rig, 'перенос стоимости')
    seen = len(rig.said())
    rig.c.max_auto_repeats = 0
    rig.pump(40.0)
    assert MATERIALS.split(':')[0] + ':' not in rig.said()[seen:], 'the old plan does not come back over a newer answer'


def test_e35_after_a_refusal_an_explicit_continue_brings_the_old_plan_back(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.c.max_auto_repeats = 0
    rig.pump(32.0)
    remark(rig, 'u1', 1)
    rig.pump(2.0)
    assert rig.said() == [NOTICE]
    user_turn(rig, 'u2', 'Продолжай')
    rig.pump(3.0)
    assert len(rig.said()) >= 2, 'only the listener brings it back'


def test_e35_a_new_question_asked_over_the_old_plan_is_not_lost(call):
    """PRT-4: a question that comes while the old portion is being repeated still gets its job and its answer."""
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(TEMPO_REPEAT_SECONDS - 0.5)
    user_turn(rig, 'u1', AMORT)
    assert the_job_text(rig, 1) == AMORT
    rig.job_says(1, AMORT_ANSWER)
    rig.job_ends(1)
    rig.pump(3.0)
    assert heard(rig, 'перенос стоимости')


# =====================================================================================================================================
# E36: the job gets the best text of the utterance
# =====================================================================================================================================

@pytest.mark.xfail(strict=True, reason='w6-integ: on w3-integ the cloud final of the condition opens job 2 and job 3, both cancelled, so INTEREST of job 1 is never said; first cause not found in this run, see reports/w6-integ.md')
def test_e36_long_question_with_conditions_the_ear_in_pieces_the_cloud_whole(call):
    """s15/s16: the ear's text comes in pieces at the commas, the cloud's final is whole: the job's question is the whole condition, not a piece."""
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    for text in ('вклад сто тысяч рублей на два года', 'под десять процентов годовых', 'нет не под десять а под двадцать', 'проценты простые сколько начислят'):
        piece(rig, text, speech=2.0)
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', CONDITIONS))
    rig.pump(TICK * 3)
    asked_text = the_job_text(rig, 1)
    assert 'двадцать' in asked_text and 'начислят' in asked_text and 'сто тысяч' in asked_text, asked_text
    rig.job_says(1, INTEREST)
    rig.job_ends(1)
    assert heard(rig, '40 000')


def test_e36_the_open_tail_of_a_final_waits_for_its_rest_and_the_job_gets_it_whole(call):
    """s11: the cloud's final stops at «закон о», its rest comes 1.5 s later: one job, the whole question."""
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', 'А в каком году принят нынешний закон о'))
    rig.pump(0.6)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u2', 'user', 'бухгалтерском учёте'))
    rig.pump(TICK * 3)
    texts = [run.question for run in rig.fake.runs]
    assert texts and all('бухгалтерском' in text for text in texts), texts


def test_e36_a_glued_repeat_and_question_the_job_gets_the_question_only(call):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    first = rig.c.state()['chunks'][0].rstrip(':')
    user_turn(rig, 'u1', f'{first}. {AMORT}')
    assert the_job_text(rig, 1) == AMORT


# =====================================================================================================================================
# E37: the stop is proved on the server (R1, R4)
# =====================================================================================================================================

def test_e37_r1_a_short_command_over_the_cue_acts_before_the_clouds_final(call):
    """The ear hears «стоп» over a cue, the cloud announces the speech 1.5 s late: the cue is cut before the cloud's final, the plan stays stopped."""
    rig = call(**LIVE)
    slow(rig)
    plan_in_flight(rig)
    rig.says('стоп', speech=0.4)
    rig.pump(0.5)
    assert rig.c.state().get('paused') is True
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Стоп'))
    rig.pump(10.0)
    assert rig.c.state().get('paused') is True and len(rig.said()) == 1, 'nothing comes back by itself'


def test_e37_r4_a_stopped_plan_comes_alive_only_by_the_listener(call):
    """«стоп → ear-first → a final that disagrees» = a pause, not a repeat; then «продолжай» goes on."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    rig.says('стоп', speech=0.5)
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', 'Срок уведомления'))
    rig.pump(TEMPO_REPEAT_SECONDS * 2 + 4.0)
    assert rig.c.state().get('paused') is True and len(rig.said()) == 1
    user_turn(rig, 'u2', 'Продолжай')
    rig.pump(3.0)
    assert len(rig.said()) >= 2 or rig.c.state().get('paused') is not True, 'the listener asked to go on'


# =====================================================================================================================================
# E42: commands only on whole speech
# =====================================================================================================================================

@pytest.mark.parametrize('said', ['Подождите, а что такое амортизация', 'Стоп, а какая ставка по вкладу в 2020 году'])
def test_e42_a_hold_word_at_the_start_of_a_question_stops_nothing_and_the_question_is_answered(call, said):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    user_turn(rig, 'u1', said)
    assert rig.c.state().get('paused') is not True, 'a question is no stop'
    assert rig.fake.runs[1:], 'the job is asked'


def test_e42_a_false_stop_does_not_silence_the_prompter_for_good(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    user_turn(rig, 'u1', 'Подождите')
    rig.pump(1.0)
    user_turn(rig, 'u2', AMORT)
    rig.job_says(1, AMORT_ANSWER)
    rig.job_ends(1)
    rig.pump(3.0)
    assert heard(rig, 'перенос стоимости'), 'a new question after a stop is answered'


def test_e42_next_after_the_end_of_an_answer_is_silence_and_the_call_goes_on(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.c.max_auto_repeats = 0
    user_turn(rig, 'u1', 'Дальше')
    rig.pump(3.0)
    count = len(rig.said())
    user_turn(rig, 'u2', AMORT)
    rig.job_says(1, AMORT_ANSWER)
    rig.job_ends(1)
    rig.pump(3.0)
    assert heard(rig, 'перенос стоимости') and count == len(rig.said()) - 1


# =====================================================================================================================================
# E43: every hold has a bound
# =====================================================================================================================================

def test_e43_the_table_of_holds_has_no_bound_over_eight_seconds_and_hearing_agrees():
    assert HOLD_BOUNDS and all(bound <= 8.0 for bound, _ in HOLD_BOUNDS.values()), HOLD_BOUNDS
    assert ONSET_HOLD_MAX_S <= 8.0 and TEMPO_HOLD_SECONDS <= 8.0


def test_e43_no_final_from_the_cloud_the_ears_text_goes_to_the_job_within_the_bound(call):
    """A speech the cloud never finishes: the ear's text is the question after the bound; the listener is never left in silence."""
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says(AMORT.lower(), speech=1.5)
    rig.pump(ONSET_HOLD_MAX_S + 1.0)
    assert rig.fake.runs and AMORT.lower() in the_job_text(rig, 0).lower(), 'the job got the ear\'s text'
    rig.job_says(0, AMORT_ANSWER)
    rig.job_ends(0)
    assert heard(rig, 'перенос стоимости')


def test_e43_a_stuck_detector_lets_go_of_the_first_cue_after_the_bound(call):
    rig = call(**LIVE)
    asked(rig, INERTIA)
    rig.onset()                               # the detector sticks: no offset ever comes
    rig.job_says(0, 'Инерция — свойство тела сохранять скорость.')
    rig.job_ends(0)
    rig.pump(HOLD_BOUNDS['first_cue'][0] + 2.0)
    assert rig.said(), 'the first cue is said though the detector never ended'


def test_e43_the_first_job_fails_on_the_final_and_the_second_answers_within_the_total_bound(call):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    began = rig.w.clock.t
    fails(rig, 0)
    rig.job_says(1, RIGHT)
    rig.job_ends(1)
    rig.pump(TICK * 3)
    assert heard(rig, '988') and rig.w.clock.t - began <= 8.0


# =====================================================================================================================================
# E44: a dispute and a doubt reach the job
# =====================================================================================================================================

@pytest.mark.parametrize('text', ['Нет, год вы назвали неверный', 'Нет, это неправильно, был не тысяча девятьсот восемьдесят восьмой', 'Это неверно'])
def test_e44_a_dispute_goes_to_the_job_and_the_cursor_stands(call, text):
    rig = call(**LIVE)
    plan(rig, asked=BAPTISM, answer='Крещение Руси было в 988 году. Это князь Владимир.')
    cursor = rig.c.state().get('chunk_index')
    rig.pump(1.0)
    user_turn(rig, 'u1', text)
    assert rig.fake.runs[1:], 'the job heard the dispute'
    assert rig.c.state().get('chunk_index') == cursor


def test_e44_are_you_sure_after_a_right_answer_gets_a_short_confirmation(call):
    rig = call(**LIVE)
    plan(rig, asked=BAPTISM, answer='Крещение Руси было в 988 году.')
    rig.pump(1.0)
    user_turn(rig, 'u1', 'Крещение Руси в 988 году, ты уверена')
    assert rig.fake.runs[1:], 'the doubt reaches the job'
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(2.0)
    assert any('988' in text or 'Да' in text for text in rig.said()[1:]), rig.said()


# =====================================================================================================================================
# E45: «speech not judged yet» protection
# =====================================================================================================================================

def test_e45_r2_the_final_of_other_speech_does_not_lift_the_protection(call):
    """A plan, the ear hears speech over it, the cloud's final of ANOTHER earlier utterance arrives: the timer must not run into the open speech."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.pump(TEMPO_REPEAT_SECONDS - 1.0)
    uid = rig.onset()
    rig.w.feed(S.turn_done('u0x', 'user', 'Ну да'))
    rig.pump(TEMPO_REPEAT_SECONDS)
    assert rig.said() == [NOTICE], 'never into speech'
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'вот')
    assert rig.c is not None


def test_e45_r10_speech_begun_at_the_portion_before_holds_the_timer_for_any_cursor(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(TEMPO_REPEAT_SECONDS - 1.0)
    rig.onset()
    rig.pump(TEMPO_REPEAT_SECONDS)
    assert len(rig.said()) == 1


# =====================================================================================================================================
# E10 / E11: a repeat with a tail, a late old answer, a late repeat against a new question
# =====================================================================================================================================

def test_e10_a_late_old_answer_is_not_spoken_after_a_new_question(call):
    rig = call(**LIVE)
    asked(rig, INERTIA)
    user_turn(rig, 'u2', AMORT)
    assert rig.fake.run(0).cancelled.is_set(), 'the job of the old question is cut'
    cloud(rig, 'a1', 'Инерция — свойство тела сохранять скорость.')
    rig.pump(2.0)
    assert not heard(rig, 'свойство тела')
    rig.job_says(1, AMORT_ANSWER)
    rig.job_ends(1)
    assert heard(rig, 'перенос стоимости')


def test_e11_a_late_repeat_of_the_old_portion_with_a_new_question_after_it_keeps_the_question(call):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    first = rig.c.state()['chunks'][0].rstrip(':')
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', f'{first.lower()}. {AMORT}'))
    rig.pump(TICK * 3)
    assert the_job_text(rig, 1) == AMORT, 'the new question is not thrown away by the repeat before it'
    rig.job_says(1, AMORT_ANSWER)
    rig.job_ends(1)
    assert heard(rig, 'перенос стоимости')


# =====================================================================================================================================
# E43 (the whole path): the final late by the ear's p90, the first job silent, the second job silent: the listener's decision within 8 s of the end of speech
# =====================================================================================================================================

@pytest.mark.xfail(strict=True, reason='E43: the second job gets its own whole FIRST_TEXT_S after the first one timed out, then the cloud\'s ANSWER_WAIT_SECONDS: 13.9 s from the end of speech; see reports/w3-replays.md, E43')
def test_e43_late_final_and_two_silent_jobs_the_listener_is_told_within_eight_seconds_of_the_end_of_speech(call):
    rig = call(**LIVE)
    ended = rig.says('в каком году было крещение руси', speech=1.5)
    rig.pump(3.7)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', BAPTISM))
    for _ in range(int(14.0 / TICK)):
        rig.pump(TICK)
        if rig.said() or spoken_failures(rig):
            break
    told = rig.w.clock.t - ended
    assert rig.said() or spoken_failures(rig), 'the listener was told nothing in 14 s'
    assert told <= 8.0, f'{told:.1f} s from the end of the speech'


# =====================================================================================================================================
# E12: the exactness of ACK: numbers, negations, the cue heard back
# =====================================================================================================================================

PORTIONS = 'Налог по ставке 20 % не уплачивается. Срок уплаты через 10 дней после этого.'


def at_the_second_portion(rig):
    plan(rig, asked='Когда платить налог', answer=PORTIONS)
    return rig.c.state()['chunk_index'], rig.said()[0]


@pytest.mark.parametrize('wrong', ['налог по ставке 10 % не уплачивается', 'налог по ставке 20 % уплачивается'], ids=['number', 'negation'])
def test_e12_a_repeat_with_another_number_or_the_negation_gone_is_no_ack(call, wrong):
    rig = call(**LIVE)
    index, portion = at_the_second_portion(rig)
    rig.pump(0.5)
    user_turn(rig, 'u1', wrong)
    rig.pump(1.0)
    assert rig.c.state()['chunk_index'] == index, 'the protected difference confirms nothing'


def test_e12_the_right_repeat_moves_on_exactly_one_step(call):
    rig = call(**LIVE)
    index, portion = at_the_second_portion(rig)
    rig.pump(0.5)
    user_turn(rig, 'u1', portion.rstrip('.').lower())
    rig.pump(1.0)
    assert rig.c.state()['chunk_index'] == index + 1 and len(rig.said()) == 2


# =====================================================================================================================================
# E17: the first portion carries the answer; a portion is memorable
# =====================================================================================================================================

KALKA_ANSWER = 'Битва на реке Калке произошла в 1223 году. Это первое столкновение монголов с русскими князьями.'


@pytest.mark.parametrize('pieces', [['Битва на реке Калке произошла'], ['Битва на реке Калке произошла', ' в 12', '23 году. Это первое столкновение монголов с русскими князьями.']], ids=['head_only', 'in_pieces'])
def test_e17_the_first_portion_says_the_year_not_the_verb_alone(call, pieces):
    """Call of 10:27: «Битва на реке Калке произошла», the year 9 s later. The decisive content is in the first portion that is said."""
    rig = call(**CALL_1027)
    asked(rig, 'в каком году была битва при Калке')
    for text in pieces:
        rig.job_says(0, text)
    if len(pieces) == 1:
        rig.job_says(0, ' в 1223 году.')
    rig.job_ends(0)
    rig.pump(1.0)
    assert '1223' in rig.said()[0], rig.said()


def test_e17_no_portion_breaks_a_number_or_a_term_and_none_is_over_the_ceiling():
    from echo_sync.portioner import syllables
    from echo_sync.settings import resolve
    ceiling = resolve({})['max_syllables']
    text = ('Битва на реке Калке произошла в 1223 году. Ставка 20 % годовых начисляется на 100 000 рублей вклада, то есть проценты составят 40 000 рублей за два года. '
            'Амортизация — постепенный перенос стоимости основного средства на расходы.')
    for portion in portions(text):
        assert not re.search(r'\d$', portion) or not re.match(r'^\d{3}\b', portion), portion
        assert syllables(portion) <= max(ceiling, 16) or re.search(r'\d{3}', portion), portion
    joined = ' '.join(portions(text))
    assert '100 000' in joined and '40 000' in joined and not re.search(r'\b\d{1,3}\s*$', ' '.join(p for p in portions(text) if p.endswith(('100', '40')))), joined
    for portion in portions(text):
        assert not portion.endswith(('100', '40', '20')), f'a number cut at the group: {portion!r}'


# =====================================================================================================================================
# E72 / E73: the long remark with a question at the end, the words of a preface
# =====================================================================================================================================

def test_e73_194_a_now_in_the_preface_of_the_account_15_question_gets_an_answer(call, caplog):
    """194.3: «Вот сейчас третья минута идёт … что такое пятнадцатый счёт»: no_source_current_data and the false «Не нашёл» 0.2 s after the final."""
    import logging
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    said_with_a_delegation(rig, 'u1', SAID_15)
    rig.pump(TICK * 4)
    if rig.fast.count:
        job_answers(rig, 0, 'Счёт 15 — заготовление и приобретение материалов.')
        rig.pump(1.0)
    assert not decisions(caplog, 'no_source_current_data') and not decisions(caplog, 'personal_unanswerable')
    assert any('15' in text or 'заготовление' in text for text in rig.said()) and not spoken_failures(rig), rig.said()


@pytest.mark.parametrize('said, key', [(SAID_89, NO_89)], ids=['151_s89'])
def test_e72_a_remark_with_i_in_the_preface_gets_a_job_and_an_answer(call, caplog, said, key):
    """151.0 / 194.3 of the call: «я»/«сейчас» in the preface made the remark personal / changing; the job is asked on the question part and its answer is said."""
    import logging
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    said_with_a_delegation(rig, 'u1', said, HEAD_89)
    assert rig.fast.count >= 1, 'the job is asked'
    assert not decisions(caplog, 'personal_unanswerable') and not decisions(caplog, 'no_source_current_data')
    job_answers(rig, 0, key)
    rig.pump(1.0)
    assert key in rig.said() and not spoken_failures(rig)


@pytest.mark.parametrize('question', ['Какой курс доллара сейчас', 'Какая сегодня погода в Москве'])
def test_e73_data_that_really_changes_is_still_not_found_without_a_source(call, monkeypatch, question):
    rig = call(**CALL_1027)
    monkeypatch.setattr(rig.w, '_lookup', None, raising=False)
    asked(rig, question)
    rig.pump(0.5)
    assert rig.c.direct_content is False, 'not answered from memory'


# =====================================================================================================================================
# E77: the help at a stammer: one or two seconds and only the tail
# =====================================================================================================================================

INFLATION = 'Инфляция — это устойчивый рост общего уровня цен.'


def test_e77_the_stammer_at_the_second_word_brings_only_the_tail_within_1_2_s(call):
    """556.8 of the call: «инфляция это устойчивый» then silence; the whole portion came 15.4 s from the start. Now: the missing words, ≤1.2 s after the end."""
    rig = call(fast_text='on', max_auto_repeats=3)
    asked(rig, 'что такое инфляция')
    job_answers(rig, 0, INFLATION)
    first = rig.said()[0]
    rig.pump(1.0)
    ended = rig.says('цвета устойчивый', speech=2.2)
    cue = rig.next_cue(3.0)
    assert cue is not None and cue.t - ended <= 1.2 + GRID, 'within 1.2 s'
    assert cue.text != first and first.endswith(cue.text), f'only the missing tail: {cue.text!r}'


def test_e77_the_repeat_never_comes_before_the_start_of_the_listeners_speech(call):
    rig = call(fast_text='on', max_auto_repeats=3)
    asked(rig, 'что такое инфляция')
    job_answers(rig, 0, INFLATION)
    rig.pump(1.0)
    rig.onset()
    rig.pump(0.5)
    assert rig.next_cue(3.0) is None, 'never into the listener\'s speech'


# =====================================================================================================================================
# E26.2: the phone's Interrupt button (a command, not a sound) over a cue
# =====================================================================================================================================

def test_e26_2_interrupt_over_a_cue_cuts_the_sound(call):
    rig = call(**LIVE)
    cue = playing(rig)
    rig.w.client({'type': 'response.cancel'})
    assert cue.cleared, 'the sound is cut'


@pytest.mark.xfail(strict=True, reason='E26.2: native_media_socket.py:420 maps response.cancel to _speech_began only (a start of speech), so the timer brings the cut portion back 3 times; '
                   'the phone\'s barge-in is the same event (test_hearing_latch.py:124 requires the loop to resume): see reports/w3-replays.md, E26.2')
def test_e26_2_interrupt_over_a_cue_and_the_plan_does_not_return_by_itself(call):
    rig = call(**LIVE)
    playing(rig)
    rig.w.client({'type': 'response.cancel'})
    count = len(rig.cues())
    rig.pump(TEMPO_REPEAT_SECONDS * 3 + 6.0)
    assert len(rig.cues()) == count, 'the plan did not come back by itself'


def test_e26_2_clear_of_the_input_buffer_is_the_same_command(call):
    rig = call(**LIVE)
    cue = playing(rig)
    rig.w.client({'type': 'input_audio_buffer.clear'})
    assert cue.cleared


def test_e26_2_after_the_interrupt_a_new_question_is_answered(call):
    rig = call(**LIVE)
    playing(rig)
    rig.w.client({'type': 'response.cancel'})
    rig.pump(2.0)
    user_turn(rig, 'u1', AMORT)
    rig.job_says(1, AMORT_ANSWER)
    rig.job_ends(1)
    rig.pump(2.0)
    assert heard(rig, 'перенос стоимости')


# =====================================================================================================================================
# E19.1: the line drops in the middle of a plan: the controller is rebuilt over the same file
# =====================================================================================================================================

def rebuilt(rig):
    """The host's reconnect: the old call closed, a new controller, wire, ear and channel over the same file."""
    rig.fast.close()
    rig.w.reconnect()
    rig.c = rig.w.controller
    rig.c.begin_call()          # what controlled_host does on every call (line 331)
    rig.detector = type(rig.detector)([])
    rig.worker = Recognizer()
    rig.ear = ear_shadow.for_call(rig.settings, rig.c, detector_factory=lambda: rig.detector, worker=rig.worker, clock=rig.w.clock.now)
    rig.w.wire.ear = rig.ear
    rig.fake = type(rig.fake)()
    rig.fast = FT.for_call(rig.settings, rig.c, stream=two_asks(rig.fake, rig.w.clock.now), instructions=lambda: 'POLICY', wake=lambda: None, clock=rig.w.clock.now)
    rig.w.wire.fast = rig.fast


def test_e19_1_a_drop_in_the_middle_of_a_plan_does_not_say_it_twice_or_by_itself(call):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=PORTIONS)
    before = rig.c.state()
    said = list(rig.said())
    rig.pump(0.5)
    rebuilt(rig)
    after = rig.c.state()
    assert after['chunk_index'] == before['chunk_index'] and after['chunks'] == before['chunks'], 'the position is the file\'s'
    rig.pump(3.0)
    assert rig.said() == said, 'nothing said by itself at the new call'


def test_e19_1_the_stop_is_not_lost_across_the_drop(call):
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=PORTIONS)
    rig.pump(1.0)
    user_turn(rig, 'u1', 'Стоп')
    rig.pump(0.5)
    assert rig.c.state().get('paused') is True
    rebuilt(rig)
    rig.pump(TEMPO_REPEAT_SECONDS * 2 + 4.0)
    assert rig.c.state().get('paused') is True and len(rig.said()) == 1, 'a stopped plan stays stopped'


def test_e19_1_a_drop_in_the_middle_of_a_job_the_answer_of_the_old_job_is_never_said(call):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    rig.job_says(0, 'Крещение Руси')
    rebuilt(rig)
    rig.pump(5.0)
    assert not heard(rig, 'Крещение Руси'), 'the old call\'s job speaks to nobody'


def test_e19_1_after_the_drop_the_repeat_of_the_portion_still_moves_the_cursor_once(call):
    rig = call(**LIVE)
    index, portion = at_the_second_portion(rig)
    rig.pump(0.5)
    rebuilt(rig)
    user_turn(rig, 'u1', portion.rstrip('.').lower())
    rig.pump(1.0)
    assert rig.c.state()['chunk_index'] == index + 1, 'one NEXT, not two'
    assert len(rig.said()) == 2


# =====================================================================================================================================
# E89: numbers aloud: the path of the cue to the ear (controlled_host.render_cue_pcm → the synthesizer) and the ACK of the number
# =====================================================================================================================================

class Voice:
    """The worker the host gives ``render_cue_pcm``: it keeps what it was told to say and writes a silent WAV."""

    def __init__(self):
        self.said = []

    def synthesize(self, text, path):
        import wave
        self.said.append(text)
        with wave.open(path, 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(24000)
            out.writeframes(b'\x00\x40' * 2400)


NUMBERS = [('Это 10 000 рублей', 'десять тысяч'), ('Проценты составят 40 000 рублей', 'сорок тысяч'), ('Сумма 144 000 рублей', 'сто сорок четыре тысячи'),
           ('Население 1 500 000 человек', 'миллион пятьсот тысяч')]


@pytest.mark.parametrize('text, words', NUMBERS)
def test_e89_the_synthesizer_is_not_given_a_number_with_a_space_in_its_groups(tmp_path, text, words):
    """The engine reads «40 000» as «сорок ноль ноль ноль»: what the worker is told must not carry the group space (or must be the words)."""
    voice = Voice()
    controlled_host.render_cue_pcm(voice, text, tmp_path)
    told = voice.said[0]
    assert not re.search(r'\d \d{3}\b', told), f'the engine would say zeros: {told!r}'


@pytest.mark.parametrize('text', ['Это было в 1998 году', 'Ставка 20 %', 'Статья 17 кодекса'])
def test_e89_what_the_engine_reads_right_is_said_in_words_without_loss(tmp_path, text):
    voice = Voice()
    controlled_host.render_cue_pcm(voice, text, tmp_path)
    assert voice.said[0] == speech_text.speak(text) and not re.search(r'\d', voice.said[0]), 'a year, a percent, a number with no group: words, and the same words every time'


def test_e89_the_ack_takes_the_number_in_words_for_the_number_in_figures(call):
    rig = call(**LIVE)
    plan(rig, asked='Сколько составят проценты', answer='Проценты составят 40 000 рублей за два года. Это простые проценты.')
    index = rig.c.state()['chunk_index']
    assert '40 000' in rig.said()[0]
    rig.pump(0.5)
    user_turn(rig, 'u1', 'проценты составят сорок тысяч рублей')
    rig.pump(1.0)
    assert rig.c.state()['chunk_index'] == index + 1, 'the number in words confirms the portion in figures'


def test_e89_the_ack_does_not_take_another_number_in_words(call):
    rig = call(**LIVE)
    plan(rig, asked='Сколько составят проценты', answer='Проценты составят 40 000 рублей за два года. Это простые проценты.')
    index = rig.c.state()['chunk_index']
    rig.pump(0.5)
    user_turn(rig, 'u1', 'проценты составят сорок пять тысяч рублей')
    rig.pump(1.0)
    assert rig.c.state()['chunk_index'] == index, 'the protected difference of numbers is not weakened'


def test_e19_1_a_drop_with_a_live_spare_job_no_double_next_and_the_old_spare_says_nothing(call):
    """prepare_wide: a job on the final and a spare on the ear's text are alive; the line drops; the new call has neither, the old ones are cut and never speak."""
    from test_h7 import WIDE
    rig = call(**WIDE)
    rig.says('кто написал войну и мир', speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Кто написал Анну Каренину'))
    rig.pump(TICK)
    old = [run for run in rig.fake.runs]
    rebuilt(rig)
    for run in old:
        run.script.put(('delta', 'Толстой.'))
    rig.pump(5.0)
    assert rig.said() == [], 'the jobs of the dead call speak to nobody'
    user_turn(rig, 'u2', AMORT)
    rig.job_says(0, AMORT_ANSWER)
    rig.job_ends(0)
    rig.pump(2.0)
    assert heard(rig, 'перенос стоимости') and not heard(rig, 'Толстой')
