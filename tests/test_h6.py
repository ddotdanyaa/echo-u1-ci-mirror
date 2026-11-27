"""H6: the risks of the one-pass analyses (05_WORK/ANALYSIS_20261105): the text of the cloud, the old plan, the job's text, a dispute, commands in speech, every hold, a doubt, the prepared speech. No network, no sleep: the real
NativeMediaSocket, ShadowEar and controller on the injected clock; the speech detector, the recognizer's worker, the cloud's events and the job's stream are scripted, each case in the live order of its events. What this proves is
the logic: nothing here is a measurement of a call.
"""
import logging
import re
from pathlib import Path

import pytest

import helpers_s6_state as S
from echo_sync import controlled_media
from echo_sync import fast_text as FT
from echo_sync.classifier import waiting_portion
from echo_sync.controlled_media import HOLD_BOUNDS, TEMPO_HOLD_SECONDS
from echo_sync.native_media_socket import ONSET_HOLD_MAX_S
from echo_sync.portioner import portions
from echo_sync.settings import CALL_SETTINGS, TEMPO_REPEAT_SECONDS, resolve
from test_h1_fast_text import settled
from test_h3_tempo import GRID, TICK, call, in_flight       # noqa: F401 - call is the fixture
from test_h4_ear_first import slow
from test_h5_live import LIVE, answer_over_speech, asked, cloud, decisions, fails, job_mark, piece, plan, said_to_the_room, spoken_failures

REVENUE = 'Выручка — это все деньги от продаж, а прибыль — оставшаяся сумма после расходов.'
LAW = 'А в каком году принят нынешний закон о бухгалтерском учёте'
LAW_CUT = 'А в каком году принят нынешний закон о'
THE_LAW = 'Закон принят в 2011 году.'
BAPTISM = 'В каком году было крещение Руси'
RIGHT = 'Крещение Руси было в 988 году.'
INERTIA = 'Что такое инерция'
MATERIALS_ANSWER = 'Купили материалы за 10 000 рублей: дебет счёта материалов, кредит счёта денег.'


def plan_in_flight(rig, answer='Срок уведомления две недели. Это статья восемьдесят.'):
    """The first cue of an answer stays in flight, heard from its first frame."""
    rig.w.feed(S.turn_created('u0', 'user', 'Что'))
    rig.w.feed(S.turn_done('u0', 'user', 'Что такое инерция'))
    rig.job_says(0, answer)
    rig.fake.run(0).finish()
    settled(rig.fast)
    rig.pump(TICK)
    rig.c.cue_heard = True
    rig.c.cue_window = [rig.w.clock.t, rig.w.clock.t + 10.0]
    rig.c.cue_outstanding = True


def errors(rig):
    return [frame[2]['error']['code'] for frame in rig.w.frames if frame[2].get('type') == 'error']


# =====================================================================================================================================
# 1. no cloud text without a job (risk 1, N3)
# =====================================================================================================================================

def test_n1_04_step_10_the_clouds_yes_does_not_reach_the_plan(call):
    """120.75 the repeat and a question cut at «закон о», 120.89 the cloud's «Да.», 122.42 the rest, 124.07 «Да.» published, then twice by the timer. «нынешний» made it data that changes, and that got no job."""
    rig = call(**LIVE)
    plan(rig, answer=REVENUE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', f"{rig.c.state()['chunks'][0].rstrip(',')} {LAW_CUT}"))
    rig.pump(TICK)
    cloud(rig, 'a1', 'Да.')
    rig.pump(1.5)
    rig.w.feed(S.turn_done('u2', 'user', 'бухгалтерском учёте'))
    rig.pump(5.0)
    assert 'Да.' not in rig.said(), 'a text of the cloud with no job'


@pytest.mark.parametrize('question', ['В каком году принят нынешний закон о бухгалтерском учёте', 'Какая текущая редакция закона о бухучёте', 'Что изменилось в законе о бухучёте в этом году'])
def test_data_that_changes_goes_to_the_lookup_and_its_job_answers(call, question):
    rig = call(**LIVE)
    asked(rig, question)
    cloud(rig, 'a1', 'Да, конечно.')
    rig.pump(0.5)
    assert rig.c.direct_content is False, 'data that changes is not answered from memory'
    assert len(rig.fake.runs) == 1 and rig.said() == [], 'the job got the sources'
    rig.job_says(0, THE_LAW)
    rig.job_ends(0)
    assert rig.said() == [THE_LAW]


def test_data_that_changes_with_no_source_is_not_found(call, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    rig = call(**LIVE)
    asked(rig, 'В каком году принят нынешний закон о бухгалтерском учёте')
    cloud(rig, 'a1', 'В 2011 году.')
    rig.pump(1.0)
    assert rig.said() == [] and 'controlled_sources_unavailable' in errors(rig), 'an honest «Не нашёл»'


def test_a_candidate_about_data_that_changes_waits_for_the_sources(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Нынешний закон о бухучёте, год принятия'))
    rig.pump(TICK)
    assert rig.c.candidate is not None, 'precondition: a final with no form'
    cloud(rig, 'a1', 'Да.')
    rig.job_says(1, THE_LAW)
    rig.job_ends(1)
    rig.pump(0.5)
    assert len(rig.fake.runs) == 3 and rig.c.question_id == 'u1' and not rig.c.direct_content, 'one more job, with the sources'
    rig.job_says(2, THE_LAW)
    rig.job_ends(2)
    assert rig.said()[-1] == THE_LAW and 'Да.' not in rig.said()


def test_a_personal_question_about_data_that_changes_is_no_memory_answer(call):
    rig = call(**LIVE)
    asked(rig, 'Какой мой нынешний стаж по закону')
    cloud(rig, 'a1', 'Да.')
    rig.pump(1.0)
    assert 'Да.' not in rig.said()


def test_a_cloud_turn_with_no_job_asked_is_nobodys(call):
    """The invariant, whatever the route: with the channel on, nothing of the cloud reaches the plan until a job for that very final has failed."""
    rig = call(**LIVE)
    asked(rig, INERTIA)
    rig.c.fast_asked = None       # a route nobody has thought of: no job was asked
    cloud(rig, 'a1', 'Инерция — свойство тела сохранять скорость.')
    rig.pump(1.0)
    assert rig.said() == [] and not rig.c.published


@pytest.mark.parametrize('text', ['Да.', 'Нет.', 'Конечно.', 'Да, конечно.', 'Верно.'])
@pytest.mark.parametrize('question', [BAPTISM, 'Кто написал Войну и мир', 'Сколько планет в Солнечной системе', 'Что такое инерция'])
def test_a_fallback_that_is_no_whole_answer_is_refused(call, text, question):
    rig = call(**LIVE)
    asked(rig, question)
    fails(rig, 0)
    fails(rig, 1)
    cloud(rig, 'a1', text)
    rig.pump(1.5)
    assert rig.said() == [] and len(spoken_failures(rig)) == 1, 'an honest failure beats a wrong word'


@pytest.mark.parametrize('question, text', [('Вода мокрая?', 'Да.'), ('Москва столица России?', 'Да, столица.'), ('Это одно и то же?', 'Нет.'), ('Можно ли вернуть товар', 'Да, можно.')])
def test_a_yes_to_a_question_of_yes_or_no_is_a_whole_answer(call, question, text):
    rig = call(**LIVE)
    asked(rig, question)
    fails(rig, 0)
    fails(rig, 1)
    cloud(rig, 'a1', text)
    rig.pump(1.5)
    assert rig.said() and not spoken_failures(rig)


@pytest.mark.parametrize('text', ['Понял, сейчас уточню и отвечу подробнее.', 'Я постараюсь отвечать быстрее.', 'Хочешь, разберём это на примере?', 'Давай ещё вопрос, попробуем в таком темпе.'])
def test_a_fallback_that_talks_about_itself_is_refused(call, text):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    fails(rig, 0)
    fails(rig, 1)
    cloud(rig, 'a1', text)
    rig.pump(1.5)
    assert rig.said() == [] and len(spoken_failures(rig)) == 1


def test_a_fallback_of_a_whole_answer_with_the_words_of_the_question_stands(call):
    rig = call(**LIVE)
    asked(rig, 'Кто написал Войну и мир')
    fails(rig, 0)
    fails(rig, 1)
    cloud(rig, 'a1', 'Войну и мир написал Лев Толстой.')
    rig.pump(1.5)
    assert rig.said() and not spoken_failures(rig)


def test_a_yes_that_goes_on_is_judged_on_all_of_it(call):
    """The first delta of an answer: «Да» may still become one."""
    rig = call(**LIVE)
    asked(rig, 'Кто написал Войну и мир')
    fails(rig, 0)
    fails(rig, 1)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Да.'))
    rig.pump(TICK * 2)
    assert rig.said() == [] and not spoken_failures(rig)
    rig.w.feed(S.turn_delta('a1', ' Её написал Лев Толстой.', 1))
    rig.w.feed(S.turn_done('a1', 'assistant', 'Да. Её написал Лев Толстой.'))
    rig.pump(1.5)
    assert rig.said() and not spoken_failures(rig)


def test_a_refused_fallback_on_the_no_source_route_says_not_found(call, monkeypatch):
    """R13: on `unsourced` the listener hears «Не нашёл», as the watchdog there says it."""
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    rig = call(**LIVE)
    asked(rig, 'Проверь, пожалуйста, что такое гидравлический удар.')
    rig.pump(0.5)
    fails(rig, 0)
    fails(rig, 1)
    cloud(rig, 'a1', 'Да.')
    rig.pump(1.5)
    assert rig.said() == [] and 'controlled_sources_unavailable' in errors(rig)


# =====================================================================================================================================
# 2. the old plan does not come back by itself (risk 2, N4, R3, R4): one rule
# =====================================================================================================================================

NOTICE = 'Срок уведомления две недели.'
REMARK = 'Какой следующий вопрос нам задать сейчас?'


def job_declines(rig, n):
    rig.job_says(n, '—')
    rig.job_ends(n)
    rig.pump(TICK * 2)


def remark(rig, uid, n, text=REMARK):
    """A remark in the form of a question: the classifier opens it, the job declines it."""
    said_to_the_room(rig, uid, text)
    assert rig.c.question_id == uid, 'precondition: the classifier opened it'
    job_declines(rig, n)


def test_n1_03_step_18_a_plan_older_than_30_s_stays_in_the_history(call):
    """205.77 «Так, а какой у нас дальше, ну, вопрос по списку», 212.26 declined, 212.28 plan_goes_on_after_no_answer: a portion 73.8 s old, over everything since."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.c.max_auto_repeats = 0
    rig.pump(31.0)
    remark(rig, 'u1', 1)
    rig.pump(5.0)
    assert rig.said() == [NOTICE], 'it waits in the history'
    entry = rig.c.state()['history'][-1]
    assert entry['status'] == 'interrupted' and entry['spoken'] == 0


def test_a_plan_cued_less_than_30_s_ago_with_the_listener_at_it_goes_on(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.pump(1.0)
    remark(rig, 'u1', 1)
    rig.pump(2.0)
    assert rig.said()[:2] == [NOTICE, NOTICE]


def test_the_bound_is_30_s_from_the_last_cue(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.c.max_auto_repeats = 0
    rig.pump(28.0)
    remark(rig, 'u1', 1)
    rig.pump(2.0)
    assert rig.said() == [NOTICE, NOTICE], 'not yet 30 s'


def test_a_plan_only_the_timer_kept_alive_is_nobodys(call):
    """Cued 4 s ago by the timer: nobody has said a word to it since it was first cued."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    assert rig.next_cue(5.0) is not None, 'precondition: the timer said it again'
    rig.pump(1.0)
    remark(rig, 'u1', 1)
    rig.pump(5.0)
    assert rig.said() == [NOTICE, NOTICE]


def test_a_try_at_the_portion_is_the_listener_at_it_even_after_the_timer(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    assert rig.next_cue(5.0) is not None
    rig.w.feed(S.turn_done('u1', 'user', 'Срок уведомления'))
    rig.pump(TICK * 2)
    remark(rig, 'u2', 1)
    rig.pump(2.0)
    assert rig.said()[-1] == NOTICE and len(rig.said()) >= 3


def test_no_older_plan_comes_back_over_a_newer_answer(call):
    """G3 stood for a plan somebody took up: H3's fix 13 let it outrank the answer in play. No more: «no newer answer was given since»."""
    rig = call(**LIVE)
    rig.asks('u1', INERTIA, 0, 'Первая часть ответа. Вторая часть ответа.')
    first = rig.said()[-1]
    rig.w.feed(S.turn_done('u2', 'user', first))
    rig.pump(TICK * 2)
    second = rig.said()[-1]
    rig.w.feed(S.turn_created('u3', 'user', 'А'))
    rig.w.feed(S.turn_done('u3', 'user', 'А какая столица Германии?'))
    rig.pump(TICK)
    rig.job_says(1, 'Берлин.')
    rig.job_ends(1)
    remark(rig, 'u4', 2)
    rig.pump(2.0)
    assert second not in rig.said()[2:], rig.said()
    assert rig.said()[-1] == 'Берлин.'


def test_no_plan_comes_back_over_an_answer_that_is_over(call):
    """The newer answer has been said to its end: nothing waits, and the plan under it stays where it is."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.w.feed(S.turn_created('u1', 'user', 'А'))
    rig.w.feed(S.turn_done('u1', 'user', 'А какая столица Германии?'))
    rig.pump(TICK)
    rig.job_says(1, 'Берлин.')
    rig.job_ends(1)
    rig.w.feed(S.turn_done('u2', 'user', 'Берлин.'))
    rig.pump(TICK * 2)
    assert rig.c.state()['completed'] is True
    count = len(rig.said())
    remark(rig, 'u3', 2)
    rig.pump(3.0)
    assert len(rig.said()) == count, rig.said()


def test_an_explicit_resume_brings_the_old_plan_back(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.c.max_auto_repeats = 0
    rig.pump(31.0)
    remark(rig, 'u1', 1)
    rig.pump(1.0)
    assert rig.said() == [NOTICE]
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Продолжай'))
    rig.pump(TICK * 3)
    assert rig.said() == [NOTICE, NOTICE]


def test_the_words_of_the_portion_bring_the_old_plan_back(call):
    """G3 rule 5 stands: the listener's own words at it are no plan coming back by itself."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Первая часть ответа. Вторая часть ответа.')
    rig.c.max_auto_repeats = 0
    rig.pump(31.0)
    remark(rig, 'u1', 1)
    rig.w.feed(S.turn_done('u2', 'user', 'Первая часть ответа'))
    rig.pump(TICK * 3)
    assert rig.said()[-1] == 'Вторая часть ответа.'


def test_a_candidate_declined_runs_no_timer_for_a_plan_past_the_rule(call):
    """The same rule when no question opened: the portion still waits, nothing replays it to a remark."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.c.max_auto_repeats = 3
    rig.c.repeat_at = None
    rig.pump(31.0)
    count = len(rig.said())
    rig.w.feed(S.turn_created('u1', 'user', ''))
    ended = rig.says('ну ладно посмотрим что там', speech=1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Ну ладно, посмотрим, что там'))
    rig.pump(0.5)
    job_declines(rig, 1)
    assert rig.next_cue(8.0) is None and len(rig.said()) == count


def test_the_watchdog_gives_nothing_old_back_either(call):
    """The cloud took a question and nothing came, long after the plan was cued."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.c.max_auto_repeats = 0
    rig.pump(31.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', REMARK))
    rig.pump(TICK * 2)
    fails(rig, 1)
    fails(rig, 2)
    rig.pump(10.0)
    assert rig.said() == [NOTICE]


# -- stopped plans stay stopped (R4) ------------------------------------------------------------------------------------------------

STOP_HEARD = 'Стоп, подождите секунду'


def stopped(rig, uid='u1'):
    plan(rig, asked=INERTIA, answer=NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created(uid, 'user', ''))
    rig.w.feed(S.turn_done(uid, 'user', 'Стоп'))
    rig.pump(TICK * 2)
    assert rig.c.state().get('paused') is True


def test_r4_a_stopped_plan_stays_stopped_when_a_final_overrules_the_ear(call):
    """«Стоп», a question opened from the ear over the stopped plan, the final says something else: the plan was back unpaused, and its timer ran."""
    rig = call(**LIVE)
    stopped(rig)
    rig.pump(1.0)
    rig.c.suspended = None
    rig.w.feed(S.turn_created('u2', 'user', ''))
    uid = rig.onset()
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, 'статья семнадцатая налогового кодекса')
    rig.pump(0.5)
    assert rig.c.question_id == 'u2' and rig.c.user_boundaries.get('u2') == 'ear_first', 'precondition: the ear opened it'
    rig.w.feed(S.turn_done('u2', 'user', 'Ну и погода сегодня за окном'))
    rig.pump(10.0)
    assert rig.c.state().get('paused') is True and NOTICE not in rig.said()[1:]


def test_r4_a_try_does_not_take_a_stopped_plan_back(call):
    rig = call(**LIVE)
    stopped(rig)
    rig.w.feed(S.turn_created('u2', 'user', 'А'))
    rig.w.feed(S.turn_done('u2', 'user', 'А какая столица Германии?'))
    rig.pump(TICK)
    rig.job_says(1, 'Берлин. Это столица.')
    rig.job_ends(1)
    rig.pump(TICK * 2)
    count = len(rig.said())
    rig.w.feed(S.turn_done('u3', 'user', 'Срок уведомления две недели'))
    rig.pump(5.0)
    assert NOTICE not in rig.said()[count:]


def test_a_stopped_plan_stays_stopped_past_the_rule_too(call):
    """Past the 30 s it waits in the history; «продолжай» brings it back, and says the portion once."""
    rig = call(**LIVE)
    stopped(rig)
    rig.pump(31.0)
    remark(rig, 'u2', 1)
    rig.pump(10.0)
    assert rig.said() == [NOTICE]
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.w.feed(S.turn_done('u3', 'user', 'Продолжай'))
    rig.pump(TICK * 3)
    assert rig.said() == [NOTICE, NOTICE]


# =====================================================================================================================================
# 3. the job gets the best text (risk 3, N5)
# =====================================================================================================================================

def input_of(rig, n):
    return rig.fake.run(n).question.split('Сейчас прозвучало: ')[-1]


def test_the_input_carries_both_recordings():
    request = FT.build_request('Сколько стоит', instructions='I', also='сколько стоит станок')
    assert request['input'][-1]['content'][0]['text'] == 'Распознано: Сколько стоит / сколько стоит станок'
    played = FT.build_request('Сколько стоит', instructions='I', played=('Вопрос?', 'Ответ.'), also='сколько стоит станок')
    assert played['input'][-1]['content'][0]['text'] == 'Вопрос: Вопрос?\nТвой ответ: Ответ.\nСейчас прозвучало: Распознано: Сколько стоит / сколько стоит станок'
    assert FT.build_request('Сколько стоит', instructions='I')['input'][-1]['content'][0]['text'] == 'Сколько стоит'


def test_brain_is_told_what_two_recordings_are():
    assert 'Распознано: А / Б' in FT.BRAIN and 'одной реплики' in FT.BRAIN and 'пропасть' in FT.BRAIN


def test_the_ears_words_reach_the_job_when_the_cloud_lost_some(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('какая столица австралии и новой зеландии', speech=2.0)
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Какая столица Австралии'))
    rig.pump(TICK * 2)
    assert 'зеландии' in input_of(rig, 0), 'the job prepared on the ear is adopted, or both are in the input'


def test_two_recordings_that_disagree_both_reach_the_job(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('какая столица австрии', speech=2.0)
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Какая столица Австралии'))
    rig.pump(TICK * 2)
    assert rig.fake.runs[-1].question == 'Распознано: Какая столица Австралии / какая столица австрии'


def test_the_same_words_are_said_once(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('какая столица австралии', speech=2.0)
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Какая столица Австралии?'))
    rig.pump(TICK * 2)
    assert input_of(rig, 0) in ('Какая столица Австралии?', 'какая столица австралии')


def test_with_no_ear_the_job_has_the_final(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Какая столица Австралии?'))
    rig.pump(TICK * 2)
    assert input_of(rig, 0) == 'Какая столица Австралии?'


def test_a_later_utterance_of_the_ear_is_not_the_words_of_this_final(call):
    rig = call(**LIVE)
    rig.says('какая столица австралии', speech=1.5)
    rig.pump(2.0)
    rig.says('ну и погода сегодня', speech=1.5)
    rig.pump(0.2)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Какая столица'))
    rig.pump(TICK * 2)
    assert 'погода' not in input_of(rig, 0)


def test_n1_01_step_16_the_holes_of_the_cloud_are_filled_by_the_ear(call):
    """203.7 «Теперь станок», 206.47 «Двадцать», 210.05 «рублей, ну», 214.15 «, амортизация …»: the ear had all the words, the chain had holes."""
    rig = call(**LIVE)

    def the_job_declines():
        rig.fake.runs[-1].say('—')
        settled(rig.fast)
        rig.fake.runs[-1].finish()
        settled(rig.fast)
        rig.pump(TICK * 2)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    piece(rig, 'теперь станок', speech=1.2)
    rig.w.feed(S.turn_done('u1', 'user', 'Теперь станок'))
    rig.pump(TICK * 2)
    piece(rig, 'стоимость сто двадцать тысяч рублей', speech=2.5)
    the_job_declines()
    piece(rig, 'срок службы пять лет', speech=1.5)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'рублей, ну'))
    rig.pump(TICK * 2)
    piece(rig, 'ну амортизация линейным способом за год', speech=2.5)
    the_job_declines()
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.w.feed(S.turn_done('u3', 'user', ', амортизация линейным способом за год, только цифру'))
    rig.pump(TICK * 2)
    text = rig.fake.runs[-1].question
    assert 'стоимость сто двадцать тысяч' in text and 'срок службы пять лет' in text, text


@pytest.mark.parametrize('tail', ['закон о', 'если', 'и', 'потому что', 'а вот', 'под двадцать'])
def test_a_final_on_an_open_tail_waits_for_its_rest(call, tail):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', f'Скажите какой размер у этого {tail}'))
    rig.pump(1.2)
    assert rig.fake.runs == [], 'the job waits'
    rig.pump(0.5)
    assert len(rig.fake.runs) == 1, 'up to 1.5 s'


def test_the_rest_of_a_final_on_an_open_tail_goes_to_the_job_whole(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'В каком году открыт закон о'))
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'всемирном тяготении'))
    rig.pump(TICK * 2)
    assert 'тяготении' in input_of(rig, 0) and len(rig.fake.runs) == 1


def test_a_final_with_no_open_tail_does_not_wait(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Какая столица Австралии?'))
    rig.pump(TICK * 2)
    assert len(rig.fake.runs) == 1


def test_a_candidate_on_an_open_tail_waits_too(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Ну допустим крещение Руси и'))
    rig.pump(1.0)
    assert len(rig.fake.runs) == 1 and rig.c.candidate is not None
    rig.pump(0.7)
    assert len(rig.fake.runs) == 2


def test_the_quiet_of_the_ear_ends_the_wait(call):
    """On the phone the final comes ~3 s behind the ear: nothing goes on, and that is known."""
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('скажите какой размер у этого под двадцать', speech=1.5)
    rig.pump(2.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Скажите какой размер у этого под двадцать'))
    rig.pump(TICK * 2)
    assert len(rig.fake.runs) == 1


def test_a_final_that_glues_a_repeat_to_a_question_is_split_on_the_portion(call):
    """n1_04 step 10: the job got the repeat and the question as one text."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Первая часть ответа. Вторая часть ответа.')
    portion = rig.c.state()['chunks'][0]
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', f'{portion} А какая столица Германии?'))
    rig.pump(TICK * 2)
    assert input_of(rig, 1) == 'какая столица Германии?'


def test_a_repeat_glued_after_a_question_is_cut_off_too(call):
    """n1_01 step 11: the final held a question and the listener's repeats after it."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=MATERIALS_ANSWER)
    portion = rig.c.state()['chunks'][0]
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', f'Какая столица Германии и сколько там жителей живёт? {portion}'))
    rig.pump(TICK * 2)
    assert input_of(rig, 1) == 'Какая столица Германии и сколько там жителей живёт?'


def test_a_candidate_with_a_repeat_glued_after_it_too(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=MATERIALS_ANSWER)
    portion = rig.c.state()['chunks'][0]
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', f'Ну допустим крещение Руси, князь Владимир, какой-нибудь там год. {portion}'))
    rig.pump(TICK * 2)
    assert portion.split()[0] not in input_of(rig, 1)


# =====================================================================================================================================
# 4. a dispute reaches the job (risk 6, N6): the neighbours in both directions
# =====================================================================================================================================

YEAR = 'Первую часть Налогового кодекса приняли в 1998 году.'
SAID = 'Первую часть Налогового кодекса приняли в 1998 году'
WRONG = 'Первую часть Налогового кодекса приняли в 1997 году'
WHALE = 'Нет, кит не рыба, а млекопитающее. Он дышит лёгкими.'
TWO = 'Первая часть ответа. Вторая часть ответа.'


def said_to(rig, text, uid='u1'):
    rig.pump(1.0)
    rig.w.feed(S.turn_created(uid, 'user', ''))
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK * 2)


@pytest.mark.parametrize('text', [
    'Нет, год вы назвали неверный, там вроде совсем другой',
    f'{SAID}, ты уверена',
    f'{SAID}, вы точно уверены',
    f'Нет, {SAID.lower()}, это неверно',
    f'{SAID}, это неправильно',
    'Нет, там вроде другой год',
    'Не в 1998 году',
    f'{WRONG}, нет, это неверно',
    f'{SAID}, разве не так',
], ids=['year_wrong', 'are_you_sure', 'sure_plural', 'no_portion_wrong', 'portion_wrong', 'other_year', 'not_the_year', 'marker_no_portion', 'isnt_it'])
def test_a_dispute_goes_to_the_job_and_the_cursor_stands(call, text):
    rig = call(**LIVE)
    plan(rig, asked='В каком году приняли первую часть Налогового кодекса', answer=YEAR)
    before = rig.c.state()
    said_to(rig, text)
    rig.pump(1.6)                       # «так» is an open tail
    assert len(rig.fake.runs) == 2, 'the job judges it'
    assert text.split()[-1].strip(',.') in rig.fake.run(1).question
    now = rig.c.state()
    assert now['chunk_index'] == before['chunk_index'] and not now.get('completed'), 'no try at the portion, no confirmation'
    rig.pump(0.5)
    assert rig.said() == [YEAR], 'no replay of the portion'


@pytest.mark.parametrize('answer, text', [
    (YEAR, SAID),
    (YEAR, f'{WRONG}, нет, {SAID.lower()}'),
    (YEAR, f'{SAID}, да?'),
    (YEAR, f'{SAID}, правильно?'),
    (YEAR, f'{SAID}, верно?'),
    (WHALE, 'Нет, кит не рыба, а млекопитающее'),
], ids=['portion', 'self_corrected', 'tag_yes', 'tag_right', 'tag_true', 'its_own_no'])
def test_a_repeat_stays_a_repeat(call, answer, text):
    rig = call(**LIVE)
    plan(rig, asked='В каком году приняли первую часть Налогового кодекса', answer=answer)
    before = rig.c.state()
    said_to(rig, text)
    now = rig.c.state()
    assert len(rig.fake.runs) == 1, 'no job for a repeat'
    assert now.get('completed') or now['chunk_index'] == before['chunk_index'] + 1


@pytest.mark.parametrize('answer, text', [
    (YEAR, WRONG),
    (YEAR, 'Первую часть Налогового кодекса'),
    (WHALE, 'Нет, кит рыба, а млекопитающее'),
    (YEAR, f'Нет, {WRONG.lower()}'),
], ids=['wrong_number', 'a_start', 'lost_its_not', 'no_and_a_try'])
def test_a_try_stays_a_try(call, answer, text):
    rig = call(**LIVE)
    plan(rig, asked='В каком году приняли первую часть Налогового кодекса', answer=answer)
    before = rig.c.state()
    said_to(rig, text)
    assert len(rig.fake.runs) == 1, 'no job for a try'
    assert rig.c.state()['chunk_index'] == before['chunk_index'] and rig.c.question_id == 'u0'


def test_n1_03_step_7_the_old_portion_is_not_said_again_to_a_dispute(call, caplog):
    """92.52 «Нет, год вы назвали, эээ, неверный, там вроде совсем другой»: attempt_shared_stem, wrong_repeat, ear_tempo: the same words again, word for word."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    rig = call(**LIVE)
    plan(rig, asked='В каком году приняли первую часть Налогового кодекса', answer=YEAR)
    said_to(rig, 'Нет, год вы назвали, эээ, неверный, там вроде совсем другой')
    assert not decisions(caplog, 'reason=wrong_repeat')
    rig.job_says(1, 'Первую часть приняли в 1998 году, вторую в 2000 году.')
    rig.job_ends(1)
    assert rig.c.question_id == 'u1' and 'вторую' in rig.c.published


def test_the_ear_does_not_confirm_a_dispute(call, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    rig = call(**LIVE)
    plan(rig, asked='В каком году приняли первую часть Налогового кодекса', answer=TWO)
    portion = rig.c.state()['chunks'][0]
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says(f'{portion.rstrip(".")}, ты уверена', speech=2.0)
    rig.pump(1.0)
    assert not decisions(caplog, 'local_ear') and rig.c.state()['chunk_index'] == 0


def test_a_doubt_after_a_portion_the_partial_confirmed_takes_the_step_back(call):
    """The stable partial took the repeat before the words of doubt came: the final says what it was."""
    rig = call(**LIVE)
    plan(rig, asked='В каком году приняли первую часть Налогового кодекса', answer=TWO)
    portion = rig.c.state()['chunks'][0]
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_delta('u1', portion, 1))
    rig.pump(0.5)
    assert rig.c.state()['chunk_index'] == 1, 'precondition: the partial confirmed it'
    rig.w.feed(S.turn_done('u1', 'user', f'{portion.rstrip(".")}, ты уверена'))
    rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 0 and len(rig.fake.runs) == 2


def test_a_dispute_of_the_last_portion_goes_to_the_job_too(call):
    """Nothing waits any more, and «<the last portion>, ты уверена» is no late try."""
    rig = call(**LIVE)
    plan(rig, asked='В каком году приняли первую часть Налогового кодекса', answer=YEAR)
    said_to(rig, SAID)
    assert rig.c.state().get('completed')
    said_to(rig, f'{SAID}, ты уверена', uid='u2')
    assert len(rig.fake.runs) == 2


def test_with_the_channel_off_a_dispute_is_what_it_was(call):
    rig = call()
    rig.w.feed(S.turn_created('u1', 'user', 'Что'))
    rig.w.feed(S.turn_done('u1', 'user', 'Что такое инерция?'))
    assert rig.c._disputes('Нет, инерция неверно', {'chunks': ['Инерция — свойство.'], 'chunk_index': 0}) is False


# =====================================================================================================================================
# 5. commands only on whole speech (risk 4, R1)
# =====================================================================================================================================

HOLD_ON = 'Обождите-ка, дайте подумать'             # no word of the grammars: the job's mark says what it is
HOW = 'А как считается амортизация'
TWO_NOTICE = 'Срок уведомления две недели. Это статья восемьдесят.'


def speech_goes_on(rig):
    """The cloud's final of the first piece came, the ear hears the speech go on."""
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', HOLD_ON))
    rig.pump(TICK)
    return rig.onset()


@pytest.mark.parametrize('mark', ['[стоп]', '[дальше]'])
def test_a_mark_waits_while_the_speech_goes_on_and_a_question_takes_it_away(call, mark):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    uid = speech_goes_on(rig)
    job_mark(rig, 1, mark)
    assert not rig.c.state().get('paused') and rig.c.state()['chunk_index'] == 0, 'not while the ear hears speech'
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'а как считается амортизация')
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', HOW))
    rig.pump(TICK * 2)
    rig.job_says(2, 'Амортизация считается линейным способом.')
    rig.job_ends(2)
    rig.pump(2.0)
    assert 'линейным' in ' '.join(rig.said()) and not rig.c.state().get('paused')


@pytest.mark.parametrize('mark, done', [('[стоп]', lambda state: state.get('paused') is True), ('[дальше]', lambda state: state['chunk_index'] == 1)])
def test_a_mark_is_carried_out_once_the_ears_silence_has_lasted(call, mark, done):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    uid = speech_goes_on(rig)
    job_mark(rig, 1, mark)
    rig.pump(0.3)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'э-э')
    assert not done(rig.c.state())
    rig.pump(1.0)
    assert done(rig.c.state())


def test_a_mark_in_silence_is_carried_out_at_once(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', HOLD_ON))
    rig.pump(TICK)
    job_mark(rig, 1, '[стоп]')
    assert rig.c.state().get('paused') is True


def test_a_hold_word_at_the_start_of_a_question_stops_nothing(call, caplog):
    """D14 line 180: «подождите» read as a stop: the cloud gave it a final of its own while the question went on."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    uid = rig.onset()
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Подождите'))
    rig.pump(1.0)
    assert not rig.c.state().get('paused'), 'the ear hears the speech go on'
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'подождите а как считается амортизация')
    rig.pump(0.3)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'а как считается амортизация'))
    rig.pump(TICK * 2)
    rig.job_says(1, 'Амортизация считается линейным способом.')
    rig.job_ends(1)
    rig.pump(2.0)
    assert 'линейным' in ' '.join(rig.said()) and not rig.c.state().get('paused')


def test_a_hold_word_alone_stops(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('подождите', speech=0.6)
    rig.w.feed(S.turn_done('u1', 'user', 'Подождите'))
    rig.pump(1.5)
    assert rig.c.state().get('paused') is True


def test_a_false_stop_does_not_silence_the_prompter_for_good(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', HOLD_ON))
    rig.pump(TICK)
    job_mark(rig, 1, '[стоп]')
    assert rig.c.state().get('paused') is True
    rig.pump(5.0)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', HOW))
    rig.pump(TICK * 2)
    rig.job_says(2, 'Амортизация считается линейным способом.')
    rig.job_ends(2)
    rig.pump(1.0)
    assert 'линейным' in ' '.join(rig.said())


def test_a_false_stop_and_a_job_that_fails_end_in_a_failure_said(call):
    """Раздел 3 of the analysis: «ложный стоп + новый вопрос + отказ job»."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', HOLD_ON))
    rig.pump(TICK)
    job_mark(rig, 1, '[стоп]')
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', HOW))
    rig.pump(TICK * 2)
    fails(rig, 2)
    fails(rig, 3)
    rig.pump(9.0)
    assert len(spoken_failures(rig)) == 1, 'the listener is told'
    rig.pump(10.0)
    assert rig.said() == [rig.c.state()['history'][0]['chunks'][0]] or len(rig.said()) == 1, 'and the stopped plan stays stopped'


def test_r1_speech_begun_over_a_cue_cuts_it_when_the_cloud_announces_it(call):
    """R1: the ear heard «стоп» begin and end over the cue, the cloud's start of speech came after that: «old news», the cue played on to the final."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', TWO_NOTICE.split('.')[0]))
    rig.pump(TICK)
    assert len(rig.said()) == 2
    rig.c.cue_outstanding = True
    rig.c.cue_window = [rig.w.clock.t, rig.w.clock.t + 10.0]
    rig.says('ну-ка', speech=0.4, lag=0.1)
    assert rig.c.tempo_old_news() is False
    rig.c.cue_outstanding = False
    assert rig.c.tempo_old_news() is True, 'the cue is over: it cuts nothing'


def test_r1_speech_ended_before_the_cue_stays_old_news(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.says('ну-ка', speech=0.4, lag=0.1)
    rig.c.cue_outstanding = True
    rig.c.cue_window = [rig.w.clock.t, rig.w.clock.t + 10.0]
    assert rig.c.tempo_old_news() is True


def test_a_whole_stop_heard_by_the_ear_acts_before_the_clouds_turn(call):
    """n1_02 step 15: 140.29 the ear heard «стоп», the cloud announced the turn 3.1-3.7 s after the onset: past EAR_BIND_SECONDS, and the stop rested on the job."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO_NOTICE)
    rig.pump(1.0)
    ended = rig.says('стоп', speech=0.5)
    rig.pump(0.5)
    assert rig.c.state().get('paused') is True and rig.w.clock.t - ended <= 1.0, 'no turn of the cloud is needed'
    rig.pump(2.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Стоп'))
    rig.pump(1.0)
    assert rig.c.state().get('paused') is True and rig.fake.runs[1:] == [], 'its turn does nothing more'
    rig.pump(10.0)
    assert len(rig.said()) == 1


def test_a_stop_over_a_cue_acts_on_the_ear_too(call):
    rig = call(**LIVE)
    slow(rig)
    plan_in_flight(rig)
    rig.says('стоп', speech=0.4)
    rig.pump(0.5)
    assert rig.c.state().get('paused') is True


def test_a_cue_heard_back_with_a_stop_word_in_it_stops_nothing(call):
    rig = call(**LIVE)
    slow(rig)
    plan_in_flight(rig, answer='Стоп, это знак. Стоп-лист ведёт менеджер.')
    rig.says('стоп', speech=0.4)
    rig.pump(0.5)
    assert not rig.c.state().get('paused')


def test_a_stop_of_the_ear_with_the_channel_off_waits_for_the_cloud_as_it_did(call):
    rig = call()
    rig.first_portion()
    rig.pump(1.0)
    rig.says('стоп', speech=0.5)
    rig.pump(1.0)
    assert not rig.c.state().get('paused')


# =====================================================================================================================================
# 6. every hold has a bound (risk 5): one table, a decision within 8 s
# =====================================================================================================================================

def newest_says(rig, text):
    """The newest job says ``text`` and is over: the ear's own question has a job of its own, prepared, before the one that counts."""
    run = rig.fake.runs[-1]
    run.say(text)
    settled(rig.fast)
    rig.pump(TICK)
    run.finish()
    settled(rig.fast)
    rig.pump(TICK * 2)


def test_every_hold_is_in_one_table_and_none_is_over_eight_seconds():
    assert set(HOLD_BOUNDS) >= {'ear_text', 'cloud_final', 'job_first_text', 'speech_unjudged', 'ear_detector', 'first_cue', 'command', 'tail_before_job', 'tail_before_cue', 'cue_in_speech'}
    for name, (seconds, what) in HOLD_BOUNDS.items():
        assert 0 < seconds <= 8.0, name
        assert len(what) > 10, name
    assert HOLD_BOUNDS['cloud_final'][0] + HOLD_BOUNDS['job_first_text'][0] == HOLD_BOUNDS['speech_unjudged'][0] == TEMPO_HOLD_SECONDS == 8.0, 'a verdict within 8 s of the end of speech'
    assert HOLD_BOUNDS['job_first_text'][0] == FT.FIRST_TEXT_S and HOLD_BOUNDS['cue_in_speech'][0] == ONSET_HOLD_MAX_S


def test_n1_02_step_12_speech_nobody_judges_goes_to_the_job_on_the_ears_text(call):
    """Step 12 of n1_02 and step 9 of n1_01: speech with content, and no final of the cloud at all."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    ended = rig.says('а какая столица австралии', speech=2.0)
    first = rig.said()
    newest_says(rig, 'Канберра.')                      # the job prepared on the ear: nothing of it counts until a final adopts it
    rig.pump(3.0)
    assert rig.said() == first and rig.c.question_id == 'u0', 'its final may still come'
    rig.pump(0.9)
    assert rig.c.tempo_unjudged == [] and 'австралии' in rig.fake.runs[-1].question and rig.w.clock.t - ended < 5.2, 'the job runs on the ear text'
    rig.pump(0.5)
    assert rig.said()[-1] == 'Канберра.', 'its verdict stands'
    jobs = len(rig.fake.runs)
    rig.w.feed(S.turn_created('u9', 'user', ''))
    rig.w.feed(S.turn_done('u9', 'user', 'А какая столица Австралии?'))
    rig.pump(1.0)
    assert len(rig.fake.runs) == jobs and rig.said().count('Канберра.') == 1, 'a late final opens nothing twice'


def test_the_verdict_on_the_ears_text_may_be_a_decline(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.says('ну ладно посмотрим на погоду', speech=2.0)
    rig.pump(4.2)
    newest_says(rig, '—')
    assert rig.c.tempo_unjudged == [] and rig.next_cue(4.5) is not None, 'decided: the timer runs again'


def test_a_final_that_comes_in_time_needs_no_ear_final(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('а какая столица австралии', speech=2.0)
    rig.pump(3.0)
    rig.w.feed(S.turn_done('u1', 'user', 'А какая столица Австралии?'))
    rig.pump(1.5)
    assert rig.c.ear_finals == 0 and rig.c.tempo_unjudged == []


def test_an_open_turn_of_the_cloud_takes_the_ears_text_as_its_final(call):
    """The cloud announced the turn and never closed it: its final, if it comes, finds it judged."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('столица австралии', speech=2.0)
    rig.pump(4.2)
    newest_says(rig, 'Канберра.')
    assert rig.said()[-1] == 'Канберра.'
    jobs = len(rig.fake.runs)
    rig.w.feed(S.turn_done('u1', 'user', 'Столица Австралии'))
    rig.pump(1.0)
    assert len(rig.fake.runs) == jobs and rig.said().count('Канберра.') == 1


def test_a_job_on_the_ears_text_has_no_second_chance_past_the_bound(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.says('ну ладно посмотрим на погоду', speech=2.0)
    rig.pump(4.2)
    rig.fast.roads.backup = None      # one road: with a road after it a failed job is no end of the question (the next road is asked at once, by the roads, not by a retry of the controller)
    jobs = len(rig.fake.runs)
    rig.fake.runs[-1].fail()
    rig.pump(1.0)
    assert len(rig.fake.runs) == jobs, 'a second job would take the decision past 8 s'


def test_a_stuck_detector_lets_go_after_eight_seconds(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.onset()
    rig.pump(7.5)
    assert rig.c.hearing is True
    rig.pump(0.7)
    assert rig.c.hearing is False, 'hearing from the ear has its bound'
    assert rig.next_cue(5.0) is not None, 'the timer runs again'


def test_a_long_stretch_the_cloud_writes_down_is_speech(call):
    """The call of 4 Nov has stretches of the ear longer than 8 s: the cloud's words say that somebody speaks."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.onset()
    for n in range(12):
        rig.pump(1.0)
        rig.w.feed(S.turn_delta('u1', 'слово ', n))
    assert rig.c.hearing is True and rig.said()[1:] == []


def test_a_late_offset_after_the_bound_does_no_harm(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    uid = rig.onset()
    rig.pump(8.5)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'э-э')
    assert rig.c.hearing is False


def test_a_first_cue_lets_go_of_a_stuck_detector(call):
    rig = call(**LIVE)
    uid = answer_over_speech(rig)
    assert rig.next_cue(7.0) is None, 'a first cue waits for speech: item 2 of H5 wins over ONSET_HOLD_MAX_S'
    assert rig.next_cue(2.0) is not None, 'a stuck detector does not hold it past 8 s'


def test_a_first_cue_lets_go_of_a_noisy_room(call):
    """Noise: stretches with no content and short gaps: no silence of 0.9 s ever comes."""
    rig = call(**LIVE)
    answer_over_speech(rig)
    rig.pump(0.3)
    rig.offset()
    rig.pump(0.1)
    began = rig.w.clock.t
    while not rig.said() and rig.w.clock.t - began < 12.0:
        rig.says('кхм', speech=0.3, lag=0.05)
        rig.pump(0.2)
    assert rig.said() and rig.w.clock.t - began <= 8.5


def test_a_real_long_question_keeps_the_first_cue_past_eight_seconds(call):
    """H5 item 2 stands: speech with content holds the first cue, and the cap of a question bounds that."""
    rig = call(**LIVE)
    uid = answer_over_speech(rig)
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'теперь станок')
    rig.pump(0.2)
    for text in ('стоимость сто двадцать тысяч рублей', 'срок службы пять лет', 'амортизация линейным способом', 'за год только цифру', 'и ещё остаточная стоимость'):
        piece(rig, text, speech=2.0)
        assert rig.said() == [], 'not into a question'


def test_a_next_portion_keeps_onset_hold_max(call):
    """ONSET_HOLD_MAX_S stands for a cue that is no first cue: a next portion after a confirmation may begin 1 s into speech."""
    assert ONSET_HOLD_MAX_S == 1.0


# =====================================================================================================================================
# 7. a doubt on a right answer
# =====================================================================================================================================

YEAR_988 = 'Крещение Руси было в 988 году. Его провёл князь Владимир.'


def answered(rig):
    rig.asks('u0', BAPTISM, 0, YEAR_988)
    rig.pump(1.0)


def test_brain_is_told_that_a_doubt_always_gets_an_answer():
    assert 'Сейчас прозвучало' in FT.BRAIN and 'сомнение или спор' in FT.BRAIN and 'всегда' in FT.BRAIN


@pytest.mark.parametrize('said', ['ты уверена', 'Ты уверена?', 'Точно?', 'Разве?', 'Вы уверены', 'Правда?'])
def test_a_job_that_declines_a_doubt_gets_a_short_confirmation(call, said):
    """1 of 8 measured: «—» to «ты уверена»: nothing was said at all."""
    rig = call(**LIVE)
    answered(rig)
    count = len(rig.said())
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', said))
    rig.pump(TICK * 2)
    assert len(rig.fake.runs) == 2, 'the job is asked'
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(0.3)
    assert len(rig.said()) == count + 1 and '988' in rig.said()[-1], 'a short confirmation, never «—»'
    assert 'Владимир' not in rig.said()[-1]


def test_a_doubt_the_classifier_opened_is_confirmed_too(call):
    rig = call(**LIVE)
    answered(rig)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'А ты точно уверена, что это правда?'))
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u1', 'precondition: a question in form'
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(0.3)
    assert '988' in rig.said()[-1]


def test_a_doubt_with_a_subject_of_its_own_may_be_declined(call):
    rig = call(**LIVE)
    answered(rig)
    count = len(rig.said())
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Может, сегодня погода испортится'))
    rig.pump(TICK * 2)
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(0.3)
    assert len(rig.said()) == count


def test_a_doubt_with_no_answer_in_play_stays_a_decline(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Ты уверена?'))
    rig.pump(TICK * 2)
    rig.job_says(0, '—')
    rig.job_ends(0)
    rig.pump(0.3)
    assert rig.said() == []


def test_a_confirmation_changes_nothing_in_the_history(call):
    rig = call(**LIVE)
    answered(rig)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Ты уверена?'))
    rig.pump(TICK * 2)
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(0.3)
    assert all(entry.get('status') != 'revised' for entry in rig.c.state()['history'])


# =====================================================================================================================================
# 10. the prepared speech (ПОТ-1)
# =====================================================================================================================================

SPEECH = ('Добрый день, уважаемые коллеги. Сегодня я расскажу о точке безубыточности. Она показывает объём продаж, при котором прибыль равна нулю. '
          'Постоянные расходы делим на маржинальный доход с единицы. В нашем примере это четыреста штук в месяц.')
PRICE = 'А что такое маржинальный доход'
MARGIN = 'Цена минус переменные расходы.'


def speech(rig):
    rig.c.prepare_speech(SPEECH)
    return rig


def said_final(rig, uid, text):
    rig.w.feed(S.turn_created(uid, 'user', ''))
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK * 2)


def repeats_current(rig, uid):
    portion = waiting_portion(rig.c.state())
    said_final(rig, uid, portion)
    return portion


def test_the_setting_is_off_by_default():
    assert resolve({})['prepared_speech'] == 'off' and resolve({'prepared_speech': 'on'})['prepared_speech'] == 'on' and resolve({'prepared_speech': 'да'})['prepared_speech'] == 'off'


def test_the_host_gives_the_call_its_speech():
    source = (Path(controlled_media.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    assert "profile_settings['prepared_speech']" in source and 'prepare_speech(context.excerpt)' in source


def test_with_no_mode_a_material_and_no_question_say_nothing(call):
    """What the code does today: the material is in the job's instructions, «начинаем» is no question, the job says «—», silence."""
    rig = call(**LIVE)
    said_final(rig, 'u1', 'Начинаем')
    if rig.fake.runs:
        rig.job_says(0, '—')
        rig.job_ends(0)
    rig.pump(2.0)
    assert rig.said() == [] and not rig.c.state()


@pytest.mark.parametrize('word', ['Начинаем', 'Поехали', 'Ну что, начинаем', 'Давайте начнём'])
def test_a_command_opens_the_speech_as_the_plan(call, word):
    rig = speech(call(**LIVE))
    said_final(rig, 'u1', word)
    state = rig.c.state()
    assert rig.fake.runs == [] and rig.said() == [state['chunks'][0]] and len(state['chunks']) > 2
    assert ' '.join(' '.join(state['chunks']).split()) == SPEECH, 'the plan is the material, cut by the portioner'


def test_the_first_words_of_the_text_open_it_and_are_not_said_again(call):
    rig = speech(call(**LIVE))
    said_final(rig, 'u1', 'Добрый день, уважаемые')
    state = rig.c.state()
    assert state['chunks'] and rig.fake.runs == []
    assert rig.said() and not rig.said()[0].startswith('Добрый день, уважаемые'), 'what is missing of the portion'


def test_the_whole_first_portion_said_goes_on_to_the_next(call):
    rig = speech(call(**LIVE))
    first = portions(SPEECH, CALL_SETTINGS)[0]
    said_final(rig, 'u1', first)
    assert rig.c.state()['chunk_index'] == 1 and rig.said() == [rig.c.state()['chunks'][1]]


def test_the_speech_goes_portion_by_portion_with_ack_as_usual(call):
    rig = speech(call(**LIVE))
    said_final(rig, 'u1', 'Начинаем')
    count = len(rig.c.state()['chunks'])
    for at in range(count):
        assert rig.c.state()['chunk_index'] == at
        rig.pump(1.0)
        repeats_current(rig, f'r{at}')
    assert rig.c.state()['completed'] is True and len(set(rig.said())) == count


def test_a_question_in_the_middle_is_answered_and_the_speech_resumes(call):
    rig = speech(call(**LIVE))
    said_final(rig, 'u1', 'Начинаем')
    rig.pump(1.0)
    repeats_current(rig, 'r1')
    rig.pump(1.0)
    waiting = waiting_portion(rig.c.state())
    said_final(rig, 'u2', PRICE)
    rig.job_says(0, MARGIN)
    rig.job_ends(0)
    assert rig.said()[-1] == MARGIN
    rig.pump(1.0)
    repeats_current(rig, 'r2')
    rig.pump(TICK * 2)
    assert rig.said()[-1] == waiting and rig.c.question_id is None, 'the speech resumes where it stopped'
    rig.pump(1.0)
    repeats_current(rig, 'r3')
    assert rig.c.state()['chunk_index'] == 1 or rig.said()[-1] != waiting


def test_a_remark_in_the_middle_changes_nothing(call):
    rig = speech(call(**LIVE))
    said_final(rig, 'u1', 'Начинаем')
    rig.pump(1.0)
    waiting = waiting_portion(rig.c.state())
    said_final(rig, 'u2', 'Ну и погода сегодня за окном')
    rig.job_says(0, '—')
    rig.job_ends(0)
    assert waiting_portion(rig.c.state()) == waiting


def test_the_speech_opens_once(call):
    rig = speech(call(**LIVE))
    said_final(rig, 'u1', 'Начинаем')
    rig.pump(1.0)
    first = waiting_portion(rig.c.state())
    repeats_current(rig, 'r1')
    rig.pump(1.0)
    said_final(rig, 'u2', 'Поехали')
    assert waiting_portion(rig.c.state()) != first


def test_a_question_before_the_speech_is_a_question(call):
    rig = speech(call(**LIVE))
    said_final(rig, 'u1', PRICE)
    assert len(rig.fake.runs) == 1
    rig.job_says(0, MARGIN)
    rig.job_ends(0)
    assert rig.said() == [MARGIN]


def test_a_stop_stops_the_speech_as_any_plan(call):
    rig = speech(call(**LIVE))
    said_final(rig, 'u1', 'Начинаем')
    rig.pump(1.0)
    said_final(rig, 'u2', 'Стоп')
    assert rig.c.state().get('paused') is True
    rig.pump(10.0)
    said_final(rig, 'u3', 'Продолжай')
    rig.pump(TICK * 2)
    assert len(rig.said()) == 2 and rig.said()[0] == rig.said()[1]


def test_no_material_no_mode(call):
    rig = call(**LIVE)
    rig.c.prepare_speech('')
    said_final(rig, 'u1', 'Начинаем')
    assert rig.c.speech is None and not rig.c.state()


# =====================================================================================================================================
# 9. numbers on the phone: the production path has not the defect of the probe
# =====================================================================================================================================

@pytest.mark.parametrize('text', ['При сложных процентах итоговая сумма составит 144 000 рублей. Доход по процентам — 44 000 рублей.', 'Сумма 144 000 рублей, ещё 2 000 000 рублей, итого 3 500 рублей и 21 000.'])
def test_no_portion_is_cut_between_the_groups_of_a_number(text):
    """N2: the probe cut «144 | 000 рублей»; the portioner of the product keeps a number whole."""
    cut = portions(text, CALL_SETTINGS)
    assert not any(re.search(r'(?:^|\s)\d{3}(?:\s|\.|$)', portion) and not re.search(r'\d\s\d{3}', portion) for portion in cut), cut
    assert ''.join(' '.join(cut).split()) == ''.join(text.split())


# =====================================================================================================================================
# H5's open case, addendum: [дальше] on a question the classifier opened after the end of an answer
# =====================================================================================================================================

def test_a_next_after_the_end_of_an_answer_is_silence_and_the_call_goes_on(call):
    """It stays open, with its reason in the report: the word would be a new phrase of the owner's list (diagnostics.PHRASES), and a cue is repeated aloud. The word «дальше» says nothing there either."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Срок уведомления две недели.')
    said_to(rig, 'Срок уведомления две недели')
    assert rig.c.state().get('completed') is True
    count = len(rig.said())
    said_to(rig, 'А что там дальше по этому ответу?', uid='u2')
    job_mark(rig, 1, '[дальше]')
    rig.pump(5.0)
    assert len(rig.said()) == count and not spoken_failures(rig)
    said_to(rig, 'Какая столица Австралии?', uid='u3')
    rig.job_says(2, 'Канберра.')
    rig.job_ends(2)
    assert rig.said()[-1] == 'Канберра.'


# =====================================================================================================================================
# R1-R10 of 03_ARCHITECTURE_CONSEQUENCES.md: what the items above did not settle, each confirmed by a test first
# =====================================================================================================================================

def test_r9_a_candidate_the_job_has_not_ruled_on_goes_to_the_job_with_the_question_after_it(call):
    """Order 1: «Столица Австралии», over 0.9 s of silence, «А Новой Зеландии?»: the cancel took the job, the first question was gone and the second had no context."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Столица Австралии'))
    rig.pump(1.5)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'А Новой Зеландии?'))
    rig.pump(TICK * 2)
    text = rig.fake.runs[-1].question
    assert 'Австралии' in text and 'Зеландии' in text, text


def test_r9_a_repeat_during_the_job_of_a_candidate_keeps_the_candidate(call):
    """Order 2: the confirmation of the portion took the candidate with it, and the job's verdict was nobody's."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO)
    portion = rig.c.state()['chunks'][0]
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Столица Австралии'))
    rig.pump(TICK * 2)
    assert rig.c.candidate is not None
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', portion))
    rig.pump(TICK * 2)
    assert rig.c.candidate is not None and rig.c.state()['chunk_index'] == 1, 'the repeat is confirmed and the job goes on'
    rig.job_says(1, 'Канберра.')
    rig.job_ends(1)
    rig.pump(0.5)
    assert rig.said()[-1] == 'Канберра.'


def test_r10_speech_begun_at_the_portion_before_holds_the_timer_too(call):
    """R10: speech begun at one portion, the cursor moved by the final of the repeat before it: no hold was set, and the next portion was said again over speech nobody had judged."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=TWO)
    portion = rig.c.state()['chunks'][0]
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    uid = rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', portion))          # the cloud's final of the repeat before: the cursor moves under the speech
    rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 1
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'а вот какая сейчас погода за окном')
    count = len(rig.said())
    assert rig.next_cue(TEMPO_REPEAT_SECONDS) is None and len(rig.said()) == count, 'speech with content stops the timer, wherever the cursor stood when it began'
