"""H2: the text channel is the brain (the judge and the source), GPT-Live is the ear. No network: the job's stream is scripted, everything else is production code.

The cases come from the owner's call of 4 Nov 20:34 (.superpowers/sdd/wave2/owner-call-2034-timeline.txt), in that call's order of events: a remark cued as «Ну наконец-то.»,
a question the classifier saw in «какой ещё раз вопрос», «тысяча девятьсот восемьдесят восьмой» and «ты уверена», meta tails as portions, the lookup of a final with no form.
Each has its neighbours, never a rule for one phrase. The text of a job here is what the experiment measured (03_TESTS/fast_text/text_brain_last.txt).
"""
import json
import logging

from cm_patch import patch_controller
import pytest

import helpers_s6_ack as H
import helpers_s6_state as S
from echo_sync import controlled_media as cm
from echo_sync import fast_text as FT
from echo_sync import reserve_text
from echo_sync.classifier import QUESTION
from echo_sync.content_policy import ANSWER_POLICY, CallContext, build_instructions
from echo_sync.native_media_socket import NO_SOURCE_RESULT
from echo_sync.settings import resolve
from echo_sync.textutil import drop_process_sentences, talks_about_itself
from test_h1_fast_text import (ANSWER, CURRENT, FIRST, FIRST_CUE, HAMMER, INERTIA, PHOTO, SECOND, STORED, VERIFY, FakeEar, FakeStream, Rig, acked, ask, break_once, cloud_says,
                               errors_of, make, rig, settled, speaks, types, until, user_says)      # noqa: F401 - rig is the fixture

BAPTISM = 'В каком году было крещение Руси'
BAPTISM_LEAD = 'Крещение Руси было в'      # f84a05a9: the start of the question is voiced first (a rule of fast_text on)
YEAR_WRONG = 'Тысяча девятьсот восемьдесят восьмой.'
REMARK = 'Да, конечно, 25 секунд подключаться — это мощно.'
PREFACED = ', прям подсказывала, быстрее реагировать нужно, значит медленно пока реагируешь. Хорошо. Пять умножить на пять'
ARTICLE_21 = 'А с двадцать первой статье Налогового кодекса'


def no_base(monkeypatch):
    """H4: behind the channel the base reads «А с двадцать первой статье …»: for what follows when it has no answer."""
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(), **_: None)


def plan(rig, text=ANSWER, topic=INERTIA, uid='u1', n=0):
    """A question, the job's answer, its first portion cued; nobody has repeated it."""
    rig.ask(topic, uid)
    rig.say(n, text)
    rig.fake.run(n).finish()
    rig.pump(0.3)
    assert rig.cues(), 'precondition: the first portion was cued'


def year(rig, answer=YEAR_WRONG, uid='u1', n=0):
    user_says(rig, uid, BAPTISM)
    rig.say(n, answer)
    rig.fake.run(n).finish()
    rig.pump(0.3)


def decline(rig, n=0, mark='—'):
    rig.say(n, mark)
    rig.fake.run(n).finish()
    rig.pump(0.3)


def history(rig):
    return rig.w.controller.state()['history']


# =====================================================================================================================================
# the prompt: BRAIN instead of the policy, the material as today, the answer in play in the input
# =====================================================================================================================================

def test_the_brain_is_the_prompt_of_a_job_and_the_policy_is_not_sent(rig):
    assert FT.BRAIN.startswith('Ты суфлёр') and 'выведи ровно один символ: —' in FT.BRAIN
    fast = FT.for_call(resolve({'fast_text': 'on'}), rig.w.controller, stream=FakeStream(), wake=lambda: None)
    body = fast._start('Что такое инерция').request
    fast.close()
    assert body['instructions'].startswith(FT.BRAIN) and ANSWER_POLICY not in body['instructions'] and 'Угу' not in body['instructions']


def test_the_brain_keeps_what_the_policy_must_not_lose():
    assert 'по-русски' in FT.BRAIN_POLICY and 'до 12 слов' in FT.BRAIN_POLICY and 'единиц' in FT.BRAIN_POLICY
    assert 'Без списков' in FT.BRAIN_POLICY


def test_the_material_stays_with_the_brain():
    text = build_instructions(CallContext(subject='Налоги', excerpt='Лекция про НДС.', material_sha256='a' * 64, material_chars=15), FT.BRAIN_POLICY)
    assert text.startswith(FT.BRAIN) and 'Лекция про НДС.' in text and 'Предмет занятия: Налоги' in text and ANSWER_POLICY not in text


def test_the_host_builds_the_brain_with_the_material_of_the_call():
    from pathlib import Path
    import echo_sync
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    assert 'build_instructions(context,fast_text.BRAIN_POLICY)' in source and 'or fast_text.BRAIN_POLICY' in source


def test_with_an_answer_in_play_the_input_says_the_question_the_answer_and_what_was_heard():
    body = FT.build_request('ты уверена', instructions='P', played=('Когда', '988 год.'))
    assert body['input'][-1]['content'][0]['text'] == 'Вопрос: Когда\nТвой ответ: 988 год.\nСейчас прозвучало: ты уверена'
    assert FT.build_request('ты уверена', instructions='P')['input'][-1]['content'][0]['text'] == 'ты уверена'


def test_earlier_exchanges_are_in_the_instructions_at_most_six_and_not_the_one_in_play():
    rows = [{'question': 'q%d' % i, 'answer': 'a%d' % i, 'status': 'complete'} for i in range(9)]
    text = FT.build_request('x', instructions='P', history=rows, played=('q8', 'a8'))['instructions']
    assert 'q7' in text and 'q2' in text and 'q1' not in text and 'q8' not in text


def test_an_answer_the_job_took_back_is_marked_for_the_next_job():
    text = FT.build_request('x', instructions='P', history=[{'question': 'q', 'answer': '1988 год.', 'status': 'revised'}])['instructions']
    assert '1988 год.' in text and FT.REVISED_MARK in text


def test_the_no_source_request_has_no_hedge_and_asks_for_no_number_it_is_not_sure_of():
    assert 'По памяти' not in FT.NO_SOURCE_BRAIN and 'не называй' in FT.NO_SOURCE_BRAIN and FT.NO_SOURCE_BRAIN != NO_SOURCE_RESULT


def test_the_wire_gives_a_job_the_answer_in_play_after_the_answer_was_retired(rig):
    plan(rig, YEAR_WRONG, S.TOPICS[0])
    user_says(rig, 'u2', 'Что такое фотосинтез?')
    c = rig.w.controller
    assert rig.fake.run(1).question == f'Вопрос: {c.fast_played[0]}\nТвой ответ: {c.fast_played[1]}\nСейчас прозвучало: {c.question_text}' and YEAR_WRONG in c.fast_played[1]


def test_an_answer_of_an_earlier_call_is_not_in_play(rig):
    plan(rig)
    c = rig.w.controller
    assert c.fast_in_play() is not None
    real = c.engine.clock
    c.engine.clock = lambda: real() + 1000      # the next call opens long after that answer
    c.begin_call()
    assert c.state()['history'] and c.fast_exchanges() == [] and c.fast_in_play() is None


def test_an_answer_stays_in_play_when_the_line_dropped_for_a_moment(rig):
    plan(rig)
    c = rig.w.controller
    c.begin_call()
    assert c.fast_in_play() is not None and c.fast_exchanges()


# =====================================================================================================================================
# rule 3: the job's text is the verdict
# =====================================================================================================================================

@pytest.mark.parametrize('final', [REMARK, 'Хорошо. Да, я готовился на самом деле', 'Блин, ну ты, конечно, долго. Вот я, допустим, тупил', 'Короче, пока что слабо, понял',
                                   'Да, какой еще раз вопрос', 'Ну что, давайте задавайте любой вопрос, собственно, готов', 'Ну и зачем такие ответы?'])
def test_the_remarks_of_the_call_say_nothing_whatever_the_cloud_replies(rig, final):
    """26.8-31.0 of the call: the final, the cloud's turn opens, its text arrives; the job's «—» came in between. No cue of «Ну наконец-то.», no question left open."""
    user_says(rig, 'u1', final)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Ну'))
    rig.pump(0.7)
    assert rig.cues() == [] and len(rig.fake.runs) == 1 and final.rstrip('?.').endswith(rig.fake.run(0).question.rstrip('?.')[-12:])
    decline(rig)
    rig.w.feed(S.turn_done('a1', 'assistant', 'Ну наконец-то. Ну что обсудим сегодня?'))
    rig.pump(20.0)
    c = rig.w.controller
    assert rig.cues() == [] and errors_of(rig) == [] and c.question_id is None and c.candidate is None and not c.published, (rig.cues(), errors_of(rig))


@pytest.mark.parametrize('mark', ['—', '–', '-', ' —\n'])      # a road that ends with NO word at all is a failed road, not the decline (``Roads``: ``ReserveError('empty')``; the BRAIN's own decline is the dash)
def test_every_form_of_the_decline_is_the_decline(rig, mark):
    user_says(rig, 'u1', REMARK)
    if mark:
        rig.say(0, mark)
    rig.fake.run(0).finish()
    rig.pump(2.0)
    assert rig.cues() == [] and rig.w.controller.candidate is None and rig.w.controller.question_id is None


@pytest.mark.parametrize('said, answer', [('—', ''), (' – ', ''), ('', ''), ('-', ''), ('— 25', '25'), ('—25', '25'), ('- 25', '25'), ('-5 градусов', '-5 градусов'), ('25 ', '25 ')])
def test_what_a_job_said_as_an_answer(said, answer):
    assert FT.brain_answer(said) == answer


def test_a_remark_while_a_portion_waits_leaves_the_portion_where_it_is(rig):
    plan(rig)
    c = rig.w.controller
    before = c.state()
    user_says(rig, 'u2', REMARK)
    decline(rig, 1)
    after = c.state()
    assert (after['revision'], after['chunk_index']) == (before['revision'], before['chunk_index']) and c.question_id == 'u1' and rig.cues() == [FIRST_CUE]


@pytest.mark.parametrize('final', ['Да, какой еще раз вопрос', 'Ну давайте, какой следующий вопрос?', 'Ну что, давайте задавайте любой вопрос, собственно, готов'])
def test_a_question_the_classifier_opened_and_the_job_declined_gives_the_plan_back(rig, final):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', final)
    assert c.question_id == 'u2' and c.state()['answer'] == '', 'precondition: the classifier opened it, the plan is retired'
    decline(rig, 1)
    assert c.question_id is None and c.state()['chunks'][0] == FIRST_CUE and rig.cues() == [FIRST_CUE, FIRST_CUE], (rig.cues(), c.state())
    rig.pump(10.0)
    assert errors_of(rig) == []


def test_the_answer_to_a_question_the_classifier_saw_is_not_judged_again_at_publication(rig):
    """The job's text is the verdict: the engine does not weigh the words again on the retired state and throw the answer away."""
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Серьёзно, а какая столица Австралии?')
    assert c.question_id == 'u2'
    rig.say(1, 'Канберра.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert rig.cues() == [FIRST_CUE, 'Канберра.'] and c.published


def test_a_question_declined_with_no_plan_is_dropped_at_once_and_nobody_is_told(rig):
    user_says(rig, 'u1', 'Какой у нас следующий вопрос?')
    c = rig.w.controller
    assert c.question_id == 'u1'
    decline(rig)
    assert c.question_id is None
    rig.pump(30.0)
    assert rig.cues() == [] and errors_of(rig) == []


def test_the_plan_comes_back_only_when_the_listener_is_quiet(rig):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Да, какой еще раз вопрос')
    c.speech_started()
    decline(rig, 1)
    assert rig.cues() == [FIRST_CUE] and c.question_id == 'u2', 'they are speaking: nothing is said over them, nothing moves'
    rig.pump(3.0)
    assert rig.cues() == [FIRST_CUE, FIRST_CUE], 'the hearing expired: the plan goes on'


def test_a_question_the_engine_would_not_take_is_published_all_the_same(rig, monkeypatch):
    """The job's text is the verdict: nothing weighs the words again on the retired state (the engine reads no text for its kind; the publication carries the verdict of the open question)."""
    rig.ask()
    rig.say(0, ANSWER)
    assert rig.cues() == [FIRST_CUE]


def test_a_declined_question_is_not_the_topic_of_the_next_follow_up(rig):
    plan(rig)
    c = rig.w.controller
    topic = c.lookup_topic
    user_says(rig, 'u2', 'Да, какой еще раз вопрос')
    decline(rig, 1)
    assert c.lookup_topic == topic


@pytest.mark.parametrize('said', ['Угу.', 'Понял тебя, буду реагировать быстрее.', 'Давай ещё вопрос, попробуем в таком темпе.', 'Сейчас уточню.'])
def test_a_job_that_says_only_talk_about_itself_admits_nothing(rig, said):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', REMARK)
    rig.say(1, said)
    rig.fake.run(1).finish()
    rig.pump(2.0)
    assert c.question_id == 'u1' and c.state()['chunks'][0] == FIRST_CUE and rig.cues() == [FIRST_CUE] and c.candidate is None


@pytest.mark.parametrize('said', ['Угу.', 'Сейчас уточню.', 'Понял, секунду.'])
def test_a_question_whose_job_gives_nothing_to_say_is_dropped_and_the_cloud_stays_out(rig, said):
    rig.ask()
    rig.w.feed(S.turn_created('a1', 'assistant', 'Инерция'))
    rig.say(0, said)
    rig.fake.run(0).finish()
    rig.pump(0.3)
    rig.w.feed(S.turn_done('a1', 'assistant', ANSWER))
    rig.pump(20.0)
    assert rig.cues() == [] and errors_of(rig) == [] and rig.w.controller.question_id is None


# =====================================================================================================================================
# rule 2: every final the arbiter leaves goes to the job; a job at a time
# =====================================================================================================================================

def test_the_job_is_the_candidates_admission(rig, caplog):
    """136.4 of the call: the end of a long remark asks. The plan was abandoned or waits: the answer is the job's, the cloud's tail is never a portion."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    user_says(rig, 'u1', PREFACED)
    c = rig.w.controller
    rig.w.feed(S.turn_created('a1', 'assistant', 'Двадцать'))
    assert c.question_id is None and c.candidate['id'] == 'u1'
    rig.say(0, '25')
    assert rig.cues() == [] and c.question_id is None, 'a lone number may still grow'
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert rig.cues() == ['25'] and c.question_id == 'u1' and c.fast_turn == 'fast-1'
    assert any('cloud_admitted evidence=text' in r.getMessage() for r in caplog.records)
    rig.w.feed(S.turn_done('a1', 'assistant', 'Двадцать пять. Понял тебя, буду реагировать быстрее, не тянуть. Давай ещё вопрос, попробуем в таком темпе.'))
    rig.pump(0.5)
    acked(rig, 1.0)
    assert rig.cues() == ['25'] and c.state()['completed'] and c.state()['answer'] == '25', (rig.cues(), c.state())


def test_an_admission_keeps_the_plan_that_it_took_over(rig):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Пять умножить на пять')
    rig.say(1, '25.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert rig.cues() == [FIRST_CUE, '25.'] and c.question_id == 'u2' and c.suspended and c.suspended['gives_back'] is True


@pytest.mark.parametrize('answer', ['Да.', 'Нет.'])
def test_a_yes_or_a_no_is_an_answer(rig, answer):
    plan(rig)
    user_says(rig, 'u2', 'Вода мокрая')
    rig.say(1, answer)
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert rig.cues() == [FIRST_CUE, answer] and rig.w.controller.question_id == 'u2', rig.cues()


def test_the_text_of_a_long_answer_admits_as_soon_as_a_sentence_is_whole(rig):
    plan(rig)
    user_says(rig, 'u2', 'Двойная запись в бухгалтерском учёте')
    c = rig.w.controller
    assert c.question_id == 'u1', 'precondition: a final with no form'
    rig.say(1, 'Двойная запись — это способ')
    assert c.question_id == 'u1' and rig.cues() == [FIRST_CUE]
    rig.say(1, ', при котором операция отражается на двух счетах. ')
    assert c.question_id == 'u2' and len(rig.cues()) == 2


@pytest.mark.parametrize('final', ['Опять ты, суфлёр, тормозишь', 'Ты опять тупишь.'])      # H6 item 7 took «Серьёзно?» out: a doubt gets a confirmation
def test_a_final_the_cloud_never_got_goes_to_the_job_too(rig, final):
    plan(rig)
    user_says(rig, 'u2', final)
    assert len(rig.fake.runs) == 2, 'the arbiter did not take it as a repeat, a command or a try'
    decline(rig, 1)
    assert rig.cues() == [FIRST_CUE]


def test_a_final_after_a_stop_goes_to_the_job(rig):
    plan(rig)
    user_says(rig, 'u2', 'стоп')
    assert rig.w.controller.state()['paused']
    user_says(rig, 'u3', 'Пять умножить на пять')
    assert len(rig.fake.runs) == 2
    decline(rig, 1)
    assert rig.w.controller.state()['paused'], 'declined: the paused plan is as it was'


def test_a_repeat_a_try_and_a_command_are_never_asked_of_the_job(rig):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'свойство тела')            # a try
    user_says(rig, 'u3', 'повтори')
    rig.pump(0.5)
    user_says(rig, 'u4', S.relaxed(FIRST_CUE))       # a repeat
    rig.pump(0.5)
    assert len(rig.fake.runs) == 1 and c.state()['chunk_index'] == 1


def test_a_final_said_while_the_job_of_the_question_runs_waits_for_it(rig):
    rig.ask()
    c = rig.w.controller
    rig.say(0, 'Инерция — это свойство тела')
    user_says(rig, 'u2', 'Пять умножить на пять')
    assert len(rig.fake.runs) == 1 and not rig.fake.run(0).cancelled.is_set(), 'one job at a time, and an answer is not cut for a final with no form'
    rig.say(0, ' сохранять своё состояние движения или покоя. ' + SECOND)
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert rig.cues() == [FIRST_CUE] and len(rig.fake.runs) == 2 and rig.fake.run(1).question.endswith('Сейчас прозвучало: Пять умножить на пять')
    decline(rig, 1)
    assert rig.cues() == [FIRST_CUE] and c.state()['answer'] == STORED


def test_a_backchannel_does_not_take_the_job_from_the_candidate(rig):
    user_says(rig, 'u1', 'Пять умножить на пять')
    user_says(rig, 'u2', 'угу')
    rig.say(0, '25.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert rig.cues() == ['25.'] and rig.w.controller.question_id == 'u1'


def test_a_new_final_with_content_replaces_the_candidate_and_its_job(rig):
    user_says(rig, 'u1', 'Хорошо, я готовился')
    user_says(rig, 'u2', 'Пять умножить на пять')
    assert until(lambda: rig.fake.run(0).cancelled.is_set()) and len(rig.fake.runs) == 2
    rig.fake.run(0).script.put(('delta', 'Что-то про подготовку.'))
    rig.say(1, '25.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert rig.cues() == ['25.'] and rig.w.controller.question_id == 'u2'


def test_the_verdict_waits_while_the_listener_speaks_and_their_words_are_judged(rig):
    user_says(rig, 'u1', 'Пять умножить на пять')
    c = rig.w.controller
    c.speech_started()
    rig.say(0, '25.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert c.question_id is None and rig.cues() == [] and c.candidate is not None
    rig.pump(3.0)
    assert rig.cues() == ['25.'], 'the hearing expired: nobody went on, the answer is the answer'


def test_speech_that_goes_on_drops_the_held_verdict(rig):
    user_says(rig, 'u1', 'Пять умножить на пять')
    c = rig.w.controller
    c.speech_started()
    rig.say(0, '25.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    user_says(rig, 'u2', 'Хорошо, а теперь посчитаем другое')
    rig.pump(3.0)
    assert rig.cues() == [] and len(rig.fake.runs) == 2


# =====================================================================================================================================
# rule 1: no race; the cloud is the fallback of a job that failed with nothing published
# =====================================================================================================================================

def test_an_answer_in_the_form_of_an_instruction_admits(rig):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Пять умножить на пять')
    assert c.question_id == 'u1', 'precondition: a final with no form'
    rig.say(1, 'Подайте декларацию в налоговую. Приложите документы.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert c.question_id == 'u2' and 'Приложите документы.' in c.state()['answer'], c.state()['answer']


def test_the_clouds_text_is_set_aside_while_a_job_runs(rig):
    rig.ask()
    cloud_says(rig, 'a1', ANSWER)
    rig.pump(3.0)
    c = rig.w.controller
    assert rig.cues() == [] and not c.published and c.source_segment_id is None, 'no race: the cloud was first and it does not matter'
    rig.say(0, 'Инерция — это свойство тела оставаться в покое или двигаться равномерно. Так говорит первый закон Ньютона.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert rig.cues()[0].startswith('свойство тела оставаться') and rig.cues()[0] != FIRST_CUE


def test_no_reply_of_the_cloud_admits_a_candidate_while_a_job_runs(rig):
    user_says(rig, 'u1', 'Пять умножить на пять')
    cloud_says(rig, 'a1', 'Двадцать пять, это простое умножение чисел.')
    rig.pump(3.0)
    c = rig.w.controller
    assert c.question_id is None and rig.cues() == [] and not c.candidate.get('ready') and not c.candidate.get('ended')


def test_a_reply_that_came_before_the_final_admits_nothing_either(rig):
    rig.w.feed(S.turn_created('u1', 'user', 'Пять'))
    cloud_says(rig, 'a1', 'Двадцать пять, это простое умножение чисел.')
    rig.w.feed(S.turn_done('u1', 'user', 'Пять умножить на пять'))
    rig.pump(2.0)
    assert rig.w.controller.question_id is None and rig.cues() == []
    decline(rig)
    assert rig.cues() == []


def test_the_clouds_backchannel_is_no_decline_while_the_job_is_the_judge(rig):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Сколько всего планет в Солнечной системе?')
    cloud_says(rig, 'a2', 'Угу.')
    rig.pump(3.0)
    assert c.question_id == 'u2' and rig.cues() == [FIRST_CUE], 'the plan does not come back on the word of the cloud'
    rig.say(1, 'В Солнечной системе восемь планет.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert any('восемь' in cue for cue in rig.cues())


def test_a_failed_job_hands_a_question_to_the_cloud_as_of_now(rig):
    rig.ask()
    cloud_says(rig, 'a1', ANSWER)
    rig.pump(0.2)
    rig.fake.run(0).fail()
    rig.pump(0.3)
    assert rig.cues() == [] and rig.fake.run(1), 'H5 item 7: one more job first'
    rig.fake.run(1).fail()
    rig.pump(0.3)
    assert rig.cues() == [FIRST_CUE] and errors_of(rig) == [] and rig.w.controller.fast_turn is None


def test_a_job_that_gave_no_text_in_time_hands_the_candidate_to_the_cloud(rig):
    user_says(rig, 'u1', 'Пять умножить на пять')
    cloud_says(rig, 'a1', 'Это простое умножение чисел.')
    rig.pump(reserve_text.GIVE_UP_S + 1.5)      # the roads give the hung job up at GIVE_UP_S (the cloud text of a candidate is not the question's answer yet: the honest phrase is said at 8 s first); no first-text bound, no second job
    assert rig.fake.run(0).cancelled.is_set() and rig.w.controller.question_id == 'u1' and rig.cues(), (rig.cues(), rig.w.controller.candidate)


def test_a_failed_job_of_a_candidate_with_a_cloud_that_said_nothing_of_substance_stays_silent(rig):
    plan(rig)
    user_says(rig, 'u2', REMARK)
    cloud_says(rig, 'a2', 'Угу.')
    rig.fake.run(1).fail()
    rig.pump(0.3)
    rig.fake.run(2).fail()
    rig.pump(2.0)
    assert rig.w.controller.question_id == 'u1' and rig.cues()[:1] == [FIRST_CUE] and errors_of(rig) == []


def test_after_a_hand_back_the_clouds_decline_counts_again(rig):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Да, какой еще раз вопрос')
    rig.fake.run(1).fail()
    rig.pump(0.2)
    rig.fake.run(2).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a2', 'Угу.')
    rig.pump(30.0)
    # c23: w10 R10.2 (282f933, rehearsal Р051): a question whose job FAILED is no talk: the cloud's backchannel no longer gives the old plan back (old_answer), the watchdog ends
    # the question with the honest phrase and the plan stays in the history (``_plan_after_decline``, ``_answer_timeout``). Was: the plan resumed at once.
    assert c.question_id is None and c.state()['chunks'] == [] and rig.w.cues[-1].text == 'Нет ответа. Повторите вопрос.' and rig.cues() == [FIRST_CUE], (rig.cues(), c.state())


def test_a_job_that_fails_after_a_portion_is_not_replaced_by_the_cloud(rig):
    rig.ask()
    rig.say(0, FIRST + ' ')
    rig.say(0, 'Чем больше ма')
    rig.fake.run(0).fail()
    rig.pump(0.3)
    cloud_says(rig, 'a1', 'Инерция — это другое определение. И другой текст облака.')
    rig.pump(1.0)
    state = rig.w.controller.state()
    assert state['answer'] == FIRST_CUE and not state['streaming'] and rig.cues() == [FIRST_CUE]


def test_the_delegation_of_a_candidate_waits_for_the_verdict(rig):
    """237.4 of the call: the cloud delegates what it took for a question. While the job judges nothing opens; a decline leaves it, an answer serves it."""
    user_says(rig, 'u1', 'Хорошо, я готовился')
    c = rig.w.controller
    rig.w.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    rig.pump(0.2)
    assert c.question_id is None and rig.w.lookup_calls == []
    decline(rig)
    assert c.question_id is None and rig.cues() == [] and c.candidate is None and rig.w.lookup_calls == []


def test_the_delegation_of_a_candidate_is_served_when_the_job_admits_it(rig):
    user_says(rig, 'u1', 'Пять умножить на пять')
    c = rig.w.controller
    rig.w.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    rig.say(0, '25.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert c.question_id == 'u1' and c.delegation_id == 'd1' and 'd1' in c.answered_delegations and rig.cues() == ['25.']


def test_after_a_failed_job_the_delegation_admits_as_it_did(rig):
    user_says(rig, 'u1', 'Пять умножить на пять')
    rig.w.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    rig.fake.run(0).fail()
    rig.pump(0.3)
    rig.fake.run(1).fail()
    rig.pump(0.3)
    assert rig.w.controller.question_id == 'u1'


def test_the_delegation_of_a_question_still_starts_the_lookup(rig):
    question = 'Проверь, пожалуйста, что такое гидравлический удар.'
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    rig.w.feed(S.turn_done('u1', 'user', question))
    rig.pump(0.3)
    assert rig.w.lookup_calls and rig.w.controller.delegation_id == 'd1'


def test_a_personal_question_the_lookup_refuses_is_answered_by_the_job(rig):
    user_says(rig, 'u1', 'Где мой паспорт?')
    c = rig.w.controller
    assert c.question_id == 'u1'
    rig.pump(0.3)
    assert len(rig.fake.runs) == 1 and c.search_refused
    rig.say(0, 'Лёгкий салат и рыбу на пару.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert rig.cues()


# =====================================================================================================================================
# the channel is out: the cloud decides as before H2
# =====================================================================================================================================

def test_with_the_breaker_open_a_candidate_goes_to_the_cloud_as_before(rig):
    rig.fast.off = True
    user_says(rig, 'u1', 'Пять умножить на пять')
    c = rig.w.controller
    assert rig.fake.runs == [] and c.fast_on is False
    cloud_says(rig, 'a1', 'Это простое умножение чисел.')
    rig.pump(2.0)
    assert c.question_id == 'u1' and rig.cues()


def test_with_the_breaker_open_a_question_goes_to_the_cloud_as_before(rig):
    rig.fast.off = True
    rig.ask()
    assert rig.fake.runs == []
    cloud_says(rig, 'a1', ANSWER)
    rig.pump(0.3)
    assert rig.cues() == [FIRST_CUE]


def test_a_call_with_no_channel_at_all_is_answered_by_the_cloud(rig):
    rig.w.wire.fast = None
    rig.ask()
    cloud_says(rig, 'a1', ANSWER)
    rig.pump(0.3)
    assert rig.cues() == [FIRST_CUE] and rig.w.controller.fast_on is False


def test_a_fault_of_the_pump_hands_the_candidate_to_the_cloud(rig):
    c = rig.w.controller
    user_says(rig, 'u1', 'Пять умножить на пять')
    cloud_says(rig, 'a1', 'Это простое умножение чисел.')
    rig.say(0, 'Двадцать')
    break_once(c)
    rig.say(0, ' пять')
    rig.pump(2.0)
    # c23: level 1 of 06.11 (laptop 2416fe0, tests/test_pump_fault.py): one fault of the pump costs its job, not the channel; FAST_FAULTS (3) of them do. Was: rig.fast.off and not c.fast_on.
    assert not rig.fast.off and c.fast_on is True and c.question_id == 'u1' and rig.cues()


# =====================================================================================================================================
# rule 4: a doubt, an objection, a follow-up have their answer in the input; a repair replaces the plan
# =====================================================================================================================================

def test_the_doubt_of_the_call(rig):
    """150.9-166.6 of the call: the answer is said, «ты уверена» comes with the repeat. The job has the whole answer in its input, its repair is the new plan, the old answer is
    marked in the history and can never come back."""
    year(rig)
    c = rig.w.controller
    asked = c.state()['question']
    assert rig.cues() == [YEAR_WRONG]
    user_says(rig, 'u2', 'А тысяча девятьсот восемьдесят восьмой, ты уверена')
    rig.w.feed(S.turn_created('a2', 'assistant', 'Нет'))
    assert rig.fake.run(1).question == f'Вопрос: {asked}\nТвой ответ: {YEAR_WRONG}\nСейчас прозвучало: ты уверена'
    rig.say(1, '988 году.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    rig.w.feed(S.turn_done('a2', 'assistant', 'Ммм. Нет, восемьсот восемьдесят восьмой. Ошибся, когда произнёс сначала.'))
    rig.pump(0.3)
    state = c.state()
    assert rig.cues() == [YEAR_WRONG, '988 году.'] and state['answer'] == '988 году.' and state['history'][0]['status'] == 'revised', (rig.cues(), state['history'])
    rig.w.feed(S.turn_done('u3', 'user', 'девятьсот восемьдесят восьмом году'))
    rig.pump(0.5)
    assert c.state()['completed']


@pytest.mark.parametrize('final', ['ты уверена', 'ты уверен?', 'точно?', 'нет, неверно', 'А может, всё-таки девятьсот девяностый?'])
def test_a_doubt_that_confirms_says_the_answer_once_and_marks_nothing(rig, final):
    year(rig, '988 год.')
    c = rig.w.controller
    user_says(rig, 'u2', final)
    rig.say(1, '988 год.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert rig.cues() == [BAPTISM_LEAD, '988 год.', '988 год.'], rig.cues()
    assert history(rig)[0]['status'] != 'revised' and c.state()['answer'] == '988 год.'


def test_a_confirmation_that_retells_a_long_answer_is_said_and_not_taken_for_a_decline(rig):
    plan(rig)
    c = rig.w.controller
    for n, cue in enumerate(list(rig.cues())):
        acked(rig, 0.5)
    acked(rig, 0.5)
    assert c.state()['completed']
    user_says(rig, 'u9', 'ты уверена')
    rig.say(1, ANSWER)
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert c.plan_told is None and rig.cues()[-1].startswith('Инерция') and history(rig)[0]['status'] != 'revised'


@pytest.mark.parametrize('final', ['ты уверена', 'ты уверен?'])
def test_a_repair_while_the_plan_waits_replaces_it_for_good(rig, final):
    plan(rig, 'Крещение Руси произошло в 1988 году. Князь Владимир крестил Киев.', uid='u1')
    c = rig.w.controller
    old = c.state()['chunks'][0]
    user_says(rig, 'u2', final)
    rig.say(1, 'Крещение Руси произошло в 988 году.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert c.suspended is None and history(rig)[0]['status'] == 'revised'
    user_says(rig, 'u3', S.relaxed(old))                # the old portion said once more: it does not bring the wrong plan back
    rig.pump(1.0)
    assert '988' in c.state()['answer'] and '1988' not in c.state()['answer']
    user_says(rig, 'u4', 'продолжай')
    rig.pump(0.5)
    assert '1988' not in c.state()['answer']


def test_an_objection_with_the_right_value_is_a_repair(rig):
    year(rig, 'Сидней.')
    user_says(rig, 'u2', 'Нет, это неверно, это Канберра')
    assert rig.w.controller.question_kind == 'correction'
    rig.say(1, 'Канберра.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert history(rig)[0]['status'] == 'revised'


def test_a_new_answer_with_the_policys_opening_is_a_repair_as_ever(rig):
    year(rig, 'Сидней.')
    user_says(rig, 'u2', 'ты уверен?')
    rig.say(1, 'Поправка: Канберра.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert history(rig)[0]['status'] == 'revised'


@pytest.mark.parametrize('final, answer', [('почему?', 'Потому что князь Владимир выбрал христианство ради союза с Византией.'),
                                           ('а пример?', 'Киевляне крестились в Днепре по приказу князя Владимира.'),
                                           ('Сколько будет пять умножить на пять?', '25.'),
                                           ('А когда была Куликовская битва?', 'Куликовская битва была в 1380 году.')])
def test_a_follow_up_or_a_new_question_is_no_repair(rig, final, answer):
    year(rig, '988 год.')
    user_says(rig, 'u2', final)
    assert 'Твой ответ: 988 год.' in rig.fake.run(1).question
    rig.say(1, answer)
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert history(rig)[0]['status'] != 'revised' and len(rig.cues()) == 2


@pytest.mark.parametrize('old, new, heard, asked, disputed, expected', [
    ('1988 год.', '988 год.', 'ты уверена', 'В каком году было крещение Руси', False, True),
    ('Сидней.', 'Канберра.', 'ты уверен?', 'Столица Австралии', False, True),
    ('365.', '366.', 'точно?', 'Сколько дней в високосном году', False, True),
    ('1942 год.', '1941 год.', 'А может, всё-таки сорок первый?', 'Когда началась война', False, True),
    ('988 год.', '988 год.', 'ты уверена', 'В каком году было крещение Руси', False, False),
    ('988 год.', 'В 988 году, через 126 лет после призвания варягов.', 'точно?', 'В каком году было крещение Руси', False, False),
    ('Толстой.', 'Толстой. «Войну и мир» написал Лев Толстой.', 'Разве не Достоевский?', 'Кто написал Войну и мир', False, False),
    ('Канберра.', 'Столица Австралии — Канберра.', 'Нет, это неверно, это Сидней', 'Столица Австралии', True, False),
    ('Сидней.', 'Канберра.', 'Нет, это неверно, это Канберра', 'Столица Австралии', True, True),
    ('1941 год.', '1941 год.', 'А может, всё-таки сорок второй?', 'Когда началась война', False, False),
    ('Статья 26 — право на представительство.', 'Статья 27 — законные представители.', 'а 27-я?', 'Что говорит статья 26', False, False),
    ('Канберра.', 'Её построили как компромисс.', 'почему?', 'Столица Австралии', False, False),
    ('Инерция — свойство тела.', 'Пассажиры наклоняются при торможении.', 'пример', 'Что такое инерция', False, False),
    ('Канберра.', 'Париж.', 'Столица Франции?', 'Столица Австралии', False, False),
    ('988 год.', '1380 год.', 'А когда была Куликовская битва?', 'В каком году было крещение Руси', False, False),
    ('Канберра.', 'Нет, налог не может быть отрицательным.', 'Может ли налог быть отрицательным?', 'Столица Австралии', False, False),
])
def test_what_is_a_repair(old, new, heard, asked, disputed, expected):
    assert FT.revises(old, new, heard=heard, question=asked, disputed=disputed) is expected


# =====================================================================================================================================
# rule 5: digits go through the existing path
# =====================================================================================================================================

@pytest.mark.parametrize('answer, said', [('988 году.', 'девятьсот восемьдесят восьмом году'), ('В 988 году.', 'в девятьсот восемьдесят восьмом году'),
                                          ('1500 рублей.', 'тысяча пятьсот рублей'), ('1500 рублей.', 'полторы тысячи рублей'), ('25', 'двадцать пять'), ('17 лет.', 'семнадцать лет')])
def test_a_number_as_digits_is_cued_repeated_in_words_and_confirmed(rig, answer, said):
    question = 'Сколько это будет в этой задаче?' if '988' not in answer else BAPTISM
    user_says(rig, 'u1', question)
    rig.say(0, answer)
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert rig.cues() == ([BAPTISM_LEAD, answer] if '988' in answer else [answer]), rig.cues()
    rig.w.feed(S.turn_done('u2', 'user', said))
    rig.pump(0.5)
    assert rig.w.controller.state()['completed'], rig.w.controller.state()


def test_a_wrong_number_in_words_does_not_confirm_a_number_in_digits(rig):
    user_says(rig, 'u1', BAPTISM)
    rig.say(0, '988 году.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u2', 'user', 'тысяча девятьсот восемьдесят восьмом году'))
    rig.pump(0.5)
    assert not rig.w.controller.state()['completed']


# =====================================================================================================================================
# rule 6: the lookup route
# =====================================================================================================================================

def test_a_candidate_that_needs_verification_waits_for_the_sources_one_more_job(rig, monkeypatch):
    no_base(monkeypatch)
    monkeypatch.setattr(S, 'SOURCE_ROWS', [{'url': 'https://example.org/21', 'text': 'Двадцать первая статья Налогового кодекса перечисляет права налогоплательщиков, а именно право на информацию.'}])
    user_says(rig, 'u1', ARTICLE_21)
    c = rig.w.controller
    assert c.question_id is None and c.candidate, 'precondition: a final with no form'
    rig.say(0, 'Статья 21 — это про обязанности банков.')
    rig.pump(0.3)
    assert c.question_id == 'u1' and rig.w.lookup_calls and rig.fake.run(0).cancelled.is_set() and rig.cues() == [], 'the job was the verdict: its text is no answer'
    second = rig.fake.run(1)
    assert 'Двадцать первая статья Налогового кодекса перечисляет' in second.request['input'][0]['content'][0]['text']
    rig.say(1, 'Статья 21 перечисляет права налогоплательщиков.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert rig.cues() and all('банков' not in cue for cue in rig.cues()) and c.engine.state(c.session_id)['retrieval_status'] == 'source_backed'


def test_with_no_source_the_second_job_has_the_no_source_text(rig, monkeypatch):
    no_base(monkeypatch)
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    user_says(rig, 'u1', ARTICLE_21)
    rig.say(0, 'Статья 21 — это про права налогоплательщиков.')
    rig.pump(0.3)
    second = rig.fake.run(1)
    assert second.request['input'][0]['content'][0]['text'] == FT.NO_SOURCE_BRAIN
    rig.say(1, 'Статья 21 — это про права налогоплательщиков.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    c = rig.w.controller
    assert rig.cues() and c.engine.state(c.session_id)['retrieval_status'] == 'unsourced'


def test_with_no_source_a_new_number_is_refused_and_the_listener_is_told(rig, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    user_says(rig, 'u1', VERIFY)
    rig.say(0, 'Удар был в 1898 году.')
    rig.fake.run(0).finish()
    rig.pump(10.0)
    assert rig.cues() == [] and 'controlled_sources_unavailable' in errors_of(rig), (rig.cues(), errors_of(rig))


def test_current_data_with_no_source_gets_no_memory_answer_from_a_candidate_either(rig, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    plan(rig)
    user_says(rig, 'u2', 'Ставка НДС сейчас')
    c = rig.w.controller
    assert c.question_id == 'u1', 'precondition: a final with no form'
    rig.say(1, 'Двадцать процентов.')
    rig.pump(1.0)
    assert rig.cues() == [FIRST_CUE] and 'controlled_sources_unavailable' in errors_of(rig) and len(rig.fake.runs) == 2 and c.question_id == 'u2', (rig.cues(), errors_of(rig))


def test_a_declined_lookup_question_says_nothing(rig):
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', VERIFY))
    rig.pump(0.3)
    decline(rig)
    assert rig.w.controller.question_id is None and rig.cues() == []
    rig.pump(30.0)
    assert errors_of(rig) == []


# =====================================================================================================================================
# rule 7: one detector, for both sources
# =====================================================================================================================================

@pytest.mark.parametrize('text, kept', [
    ('Двадцать пять. Понял тебя, буду реагировать быстрее, не тянуть. Давай ещё вопрос, попробуем в таком темпе.', 'Двадцать пять.'),
    ('По памяти, статья 21 — это про права налогоплательщиков. Точную формулировку по пунктам сейчас не воспроизведу, но если хочешь, можем разобрать логику и пример.',
     'По памяти, статья 21 — это про права налогоплательщиков.'),
])
@pytest.mark.parametrize('final', [True, False])
def test_the_meta_tails_of_the_call_are_no_portions(text, kept, final):
    assert talks_about_itself(text[len(kept):])
    assert drop_process_sentences(text, 'Пять умножить на пять', final=final, talk=True) == kept


@pytest.mark.parametrize('text, question', [
    ('Мне нравится эта работа. Я быстро учусь. Я работаю бухгалтером.', 'Почему вы хотите работать у нас?'),
    ('Я пять лет работал главным бухгалтером. Я знаю английский язык. Я могу работать удалённо.', 'Расскажите о себе'),
    ('Хочу расти. Ваша компания мне нравится.', 'Почему ты выбрал нашу компанию?'),
    ('Амортизация уменьшает прибыль. Мы применяем линейный способ.', 'Что такое амортизация?'),
])
def test_first_person_content_stays(text, question):
    assert drop_process_sentences(text, question, final=True, talk=True) == text


@pytest.mark.parametrize('sentence', ['Подайте декларацию в налоговую.', 'Приложите документы о расходах.', 'Вам нужно подать заявление.'])
def test_an_instruction_is_how_a_procedure_is_told(sentence):
    text = 'Сначала соберите справки о доходах. ' + sentence
    assert drop_process_sentences(text, 'Как оформить налоговый вычет', final=True, talk=True) == text


@pytest.mark.parametrize('sentence', ['Попробуем в таком темпе.', 'Могу разобрать логику на примере.', 'Если хотите, можем разобрать пример.', 'Давайте разберём пример.'])
def test_the_first_person_of_the_producer_goes_where_the_question_is_said_to_nobody(sentence):
    assert drop_process_sentences('Амортизация уменьшает прибыль. ' + sentence, 'Что такое амортизация', final=True, talk=True) == 'Амортизация уменьшает прибыль.'


@pytest.mark.parametrize('sentence', ['Давай ещё вопрос, попробуем в таком темпе.', 'Понял тебя, буду реагировать быстрее.', 'Если хочешь, можем разобрать пример.'])
def test_in_an_interview_a_sentence_said_to_the_listener_still_goes(sentence):
    text = 'Я работаю бухгалтером. ' + sentence
    assert drop_process_sentences(text, 'Кем вы работаете?', final=True, talk=True) == 'Я работаю бухгалтером.'


@pytest.mark.parametrize('tail', ['Понял тебя, буду реагировать', 'Давай ещё', 'Точную формулировку по пунктам сейчас не воспроизведу, но'])
def test_a_growing_sentence_is_withheld_while_it_is_turning_out_so(tail):
    head = 'Статья 21 — это про права налогоплательщиков. '
    assert drop_process_sentences(head + tail, 'Что в статье 21', talk=True) == head.rstrip()


def test_a_growing_sentence_of_content_goes_on(rig):
    assert drop_process_sentences('Двадцать пять. Чем больше масса, тем', 'Пять на пять', talk=True) == 'Двадцать пять. Чем больше масса, тем'


def test_with_the_channel_off_the_filter_is_what_it_was():
    text = 'Двадцать пять. Понял тебя, буду реагировать быстрее, не тянуть.'
    assert drop_process_sentences(text, 'Пять на пять', final=True) == text


def test_meta_tails_of_the_job_are_no_portions_on_the_wire(rig):
    user_says(rig, 'u1', 'Пять умножить на пять')
    rig.say(0, 'Двадцать пять. Понял тебя, буду реагировать быстрее, не тянуть. Давай ещё вопрос, попробуем в таком темпе.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert rig.cues() == ['Двадцать пять.'] and rig.w.controller.state()['answer'] == 'Двадцать пять.'


def test_meta_tails_of_the_cloud_are_no_portions_when_it_is_the_fallback(rig):
    rig.ask()
    rig.fake.run(0).fail()
    rig.pump(0.2)
    rig.fake.run(1).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a1', FIRST + ' Понял тебя, буду реагировать быстрее, не тянуть. Давай ещё вопрос, попробуем в таком темпе.')
    rig.pump(3.0)
    assert rig.w.controller.state()['answer'] == FIRST_CUE


# =====================================================================================================================================
# rule 8: a failure after publication
# =====================================================================================================================================

def test_a_failure_with_an_expanded_term_published_closes_on_it_without_a_rewrite(rig):
    rig.ask()
    rig.say(0, 'Инерция важна для расчёта ВВП страны, и о ней пишут в учебниках физики для школы. ')
    rig.pump(0.3)
    assert rig.cues()
    rig.say(0, 'Чем больше ма')
    rig.fake.run(0).fail()
    rig.pump(0.3)
    for _ in range(5):
        acked(rig, 0.6)
    state = rig.w.controller.state()
    assert state['completed'] and not state['streaming'] and not any('Поправка' in cue for cue in rig.cues()) and not any(cue.endswith(' ма') for cue in rig.cues()), (rig.cues(), state)


def test_a_failure_in_the_first_sentence_with_a_term_spelled_out_ends_the_stream_at_once(rig):
    c = rig.w.controller
    c.settings = {**c.settings, 'abbreviations': {'ВВП': 'валовой внутренний продукт'}}
    rig.ask()
    rig.say(0, 'Рост экономики считают по ВВП, и о нём пи')
    assert rig.cues() and c.published.endswith('продукт,'), 'a portion ended at the comma, and its words are not the words of the job'
    published = c.published
    rig.fake.run(0).fail()
    rig.pump(0.2)
    state = c.state()
    assert not state['streaming'] and state['answer'] == published and not any('Поправка' in cue for cue in rig.cues()), (rig.cues(), state)


def test_an_answer_with_an_open_end_is_whole_when_the_job_ended_ok(rig):
    rig.ask()
    rig.say(0, 'Инерция — это свойство тела сохранять скорость')
    rig.fake.run(0).finish()
    rig.pump(0.2)
    c = rig.w.controller
    assert rig.cues() and not c.state()['streaming'] and c.unsettled is None, 'a completed stream is the end: no grace window for a continuation that cannot come'


# =====================================================================================================================================
# rule 9: the adoption of a prepared job
# =====================================================================================================================================

@pytest.mark.parametrize('heard, final, same', [
    ('Какая столица Австралии', 'Какая столица Австралии и Канады?', False),       # half a question
    ('Какой газ легче воздуха', 'Какой газ тяжелее воздуха?', False),               # another key word
    ('Когда родился Пушкин', 'Когда родился Лермонтов?', False),
    ('Что такое амортизация основных средств', 'Что такое амортизация?', True),
    ('Что такое амортизация', 'что такое амортизация', True),
    ('Сколько будет сорок восемь умножить на десять', 'Сколько будет 48 умножить на 10', True),
    ('Сколько будет сорок восемь умножить на десять', 'Сколько будет 48 умножить на 11', False),
])
def test_every_content_word_of_the_final_is_in_the_ears_text(heard, final, same):
    assert FT.same_question(heard, final) is same


def test_a_number_said_as_an_ordinal_counts_in_the_match():
    assert FT.same_question('что говорит 27-я статья налогового кодекса', 'что говорит 28-я статья налогового кодекса') is False


def ear_says(rig, text):
    rig.hear(text)
    return rig.fake.run(len(rig.fake.runs) - 1)


def test_half_a_question_restarts_on_the_final(rig):
    first = ear_says(rig, 'Какая столица Австралии')
    rig.ask(text='Какая столица Австралии и Канады?')
    assert len(rig.fake.runs) == 2 and first.cancelled.is_set() and rig.fake.run(1).question == 'Какая столица Австралии и Канады?'


def test_a_prepared_job_uses_the_brain(rig):
    fast = FT.for_call(resolve({'fast_text': 'on'}), rig.w.controller, stream=rig.fake, wake=lambda: None)
    fast.prepare('Что такое инерция')
    assert rig.fake.run(0).request['instructions'].startswith(FT.BRAIN) and rig.fake.run(0).question == 'Что такое инерция'
    fast.close()


def test_a_prepared_job_has_the_answer_in_play_too(rig):
    plan(rig, YEAR_WRONG)
    run = ear_says(rig, 'Что такое фотосинтез')
    assert run.question.startswith('Вопрос: ') and 'Твой ответ: ' + YEAR_WRONG in run.question and run.question.endswith('Сейчас прозвучало: Что такое фотосинтез')


def test_a_prepared_job_is_adopted_with_the_plan_in_play(rig):
    plan(rig)
    run = ear_says(rig, 'Что такое фотосинтез')
    rig.say(1, PHOTO.answer)
    rig.ask(PHOTO, 'u2')
    run.finish()
    rig.pump(0.3)
    assert len(rig.fake.runs) == 2 and len(rig.cues()) == 2 and rig.w.controller.question_id == 'u2', rig.cues()


def test_a_prepared_job_of_another_answer_in_play_is_not_adopted():
    from test_h1_fast_text import Clock
    played = [('q', 'a')]
    fake, clock = FakeStream(), Clock()
    fast = FT.FastText(fake, instructions=lambda: 'P', history=lambda: [], in_play=lambda: played[0], clock=clock, wake=lambda: None)
    fast.prepare('Что такое инерция')
    played[0] = ('q', 'другой ответ')
    assert fast.release(qid='u1', turn='fast-1', epoch=1, question='Что такое инерция') == 'started' and len(fake.runs) == 2
    fast.close()


def test_a_prepared_decline_is_nothing_until_it_is_adopted_and_then_it_is_the_verdict(rig):
    run = ear_says(rig, 'Какой у нас следующий вопрос')
    rig.say(0, '—')
    run.finish()
    rig.pump(0.3)
    c = rig.w.controller
    assert c.question_id is None and rig.cues() == []
    rig.w.feed(S.turn_created('u1', 'user', 'Какой'))
    rig.w.feed(S.turn_done('u1', 'user', 'Какой у нас следующий вопрос?'))
    rig.pump(0.3)
    assert len(rig.fake.runs) == 1 and c.question_id is None and rig.cues() == []


def test_a_candidate_adopts_a_prepared_job(rig):
    run = ear_says(rig, 'Сколько будет пять умножить на пять')
    rig.say(0, '25.')
    run.finish()
    rig.pump(0.2)
    rig.w.feed(S.turn_created('u1', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u1', 'user', 'Хорошо. Сколько будет пять умножить на пять.'))
    rig.pump(0.3)
    assert len(rig.fake.runs) == 1 and rig.cues() == ['25.']


# =====================================================================================================================================
# rule 10, 11: what the review found, on the new path
# =====================================================================================================================================

def test_a_cancel_of_the_plan_does_not_cancel_the_job_of_a_candidate(rig):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Пять умножить на пять')
    run = rig.fake.run(1)

    async def cancel():
        await rig.w.wire.actions([{'type': 'cancel', 'epoch': c.epoch}])
    rig.w.run(cancel())
    assert not run.cancelled.is_set()


def test_the_decisions_of_a_verdict_are_logged_with_no_word_of_the_dialogue(rig, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    user_says(rig, 'u1', REMARK)
    decline(rig)
    lines = [r.getMessage() for r in caplog.records if 'fast_text' in r.getMessage()]
    assert any('reason=fast_text_declined' in line for line in lines), lines
    assert 'мощно' not in '\n'.join(lines)


def test_one_whole_stretch_of_the_call(rig):
    """The remark, the answer, the doubt: 27.9, 137.5, 150.9, 166.6 of the call, each with the cloud talking meanwhile."""
    c = rig.w.controller
    user_says(rig, 'u1', REMARK)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Ну'))
    decline(rig, 0)
    rig.w.feed(S.turn_done('a1', 'assistant', 'Ну наконец-то. Ну что обсудим сегодня?'))
    rig.pump(1.0)
    user_says(rig, 'u2', 'Да, какой еще раз вопрос')
    cloud_says(rig, 'a2', 'Да. Сначала простой вопрос.')
    decline(rig, 1)
    rig.pump(1.0)
    user_says(rig, 'u3', PREFACED)
    rig.w.feed(S.turn_created('a3', 'assistant', 'Двадцать'))
    rig.say(2, '25')
    rig.fake.run(2).finish()
    rig.pump(0.3)
    rig.w.feed(S.turn_done('a3', 'assistant', 'Двадцать пять. Понял тебя, буду реагировать быстрее, не тянуть. Давай ещё вопрос, попробуем в таком темпе.'))
    user_says(rig, 'u4', 'Двадцать пять. Хорошо, считаем быстро. Так, в каком году было крещение Руси')
    rig.pump(0.3)
    run = rig.fake.run(3)
    assert 'Твой ответ: 25' in run.question
    rig.say(3, '988 год.')
    run.finish()
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u5', 'user', 'девятьсот восемьдесят восьмой год'))
    rig.pump(0.5)
    assert rig.cues() == ['25', '988 год.'] and c.state()['completed'] and errors_of(rig) == [] and rig.w.violations == [], (rig.cues(), errors_of(rig))


def test_the_call_of_20_34_replayed(rig):
    """Every final of the call, in order, at its time, the cloud talking as it talked; the job says what the experiment measured («—» to a remark, the digits to a question)."""
    c = rig.w.controller
    start = rig.w.clock.now()
    trail = []

    def at(moment):
        rig.pump(max(0.1, start + moment - rig.w.clock.now()))

    def final(moment, uid, text, job=None, cloud=None):
        """The final at its moment, the cloud's turn right after it, the job's text 1.2 s later, as the channel gives it."""
        at(moment)
        before = len(rig.fake.runs)
        user_says(rig, uid, text)
        if cloud:
            rig.w.feed(S.turn_created('a' + uid, 'assistant', cloud.split()[0]))
        rig.pump(0.2)
        asked = len(rig.fake.runs) > before
        trail.append((text[:30], asked, c.question_id))
        if asked and job is not None:
            rig.pump(1.0)
            run = rig.fake.runs[-1]
            run.say(job)
            run.finish()
            rig.pump(0.2)
        if cloud:
            rig.w.feed(S.turn_done('a' + uid, 'assistant', cloud))
        rig.pump(0.1)
    final(26.8, 'u1', REMARK, '—', 'Ну наконец-то. Ну что обсудим сегодня?')
    final(41.3, 'u2', 'Хорошо. Да, я готовился на самом деле', '—', 'Мг.')
    final(52.2, 'u3', 'Да, я готовился. Готовился в целом, в целом. Ну что, давайте задавайте любой вопрос, собственно, готов', '—', 'Давай такой')
    final(55.2, 'u4', 'Да, какой еще раз вопрос', '—', 'Да. Сначала простой вопрос.')
    assert rig.cues() == [] and c.question_id is None, (rig.cues(), trail)
    final(59.0, 'u5', 'Семнадцатая статья Налогового кодекса', None, 'Мг. Ну давай такой сначала вопрос.')
    first = rig.cues()
    assert len(first) == 1 and first[0].startswith('Статья 17'), first
    final(62.9, 'u6', 'Ага', None, 'Ммм.')
    final(68.8, 'u7', S.relaxed(first[0]), None, 'Ммм.')
    assert len(rig.cues()) == 2 and rig.cues()[1].lstrip('— ').startswith('общие условия'), rig.cues()
    portion = rig.cues()[1]
    final(105.8, 'u8', 'кодекса о... общие... общие... общие условия установления налогов и сборов. Блин, ну ты, конечно, долго. Вот я, допустим, тупил', '—', 'Ммм. Ммм.')
    final(129.6, 'u9', 'целенаправленно, а ты мне подсказываешь секунд через шесть, через семь, ну это вообще очень плохо. Ты у тебя уже был, уже хороший, быстрый такой повтор.', '—', 'Мг.')
    final(136.4, 'u10', PREFACED, '25', 'Двадцать пять. Понял тебя, буду реагировать быстрее, не тянуть. Давай ещё вопрос, попробуем в таком темпе.')
    assert rig.cues()[-1] == '25', (rig.cues(), trail)
    final(150.4, 'u11', 'Двадцать пять. Хорошо, считаем быстро. Так, в каком году было крещение Руси', '988 году.', 'Тысяча девятьсот восемьдесят восьмой.')
    assert rig.cues()[-1] == '988 году.', (rig.cues(), trail)
    final(164.6, 'u12', 'девятьсот восемьдесят восьмом году, ты уверена', 'Крещение Руси произошло в 988 году.', 'Ммм. Нет, восемьсот восемьдесят восьмой. Ошибся, когда произнёс сначала.')
    assert rig.cues()[-1].endswith('в 988 году.') and not any('Ммм' in cue or 'восемьсот' in cue for cue in rig.cues()), (rig.cues(), trail)
    final(237.0, 'u13', 'Ну короче, у тебя ответы тупо вообще неправильные какие-то пошли, я понял, выдуманные. Короче, тоже слабоватенько пока.', '—', 'Принял, посмотрю, как это упаковать в нормальный план.')
    final(239.7, 'u14', 'Короче, пока что слабо, понял', '—', 'это упаковать в нормальный план.')
    said = list(rig.cues())
    assert errors_of(rig) == [] and rig.w.violations == [] and not any('Понял' in cue or 'Давай' in cue or 'наконец' in cue for cue in said), (said, trail, errors_of(rig))
    assert portion in said


# =====================================================================================================================================
# H2: skeptic. Each test here failed before its fix, on the production code, in the order of events it says
# =====================================================================================================================================

def spoken(rig, uid, text):
    """A turn the provider announces word by word: the stable partial may take it, and nothing here says it is over."""
    rig.w.feed(S.turn_created(uid, 'user', ''))
    for n, word in enumerate(text.split()):
        rig.w.feed(S.turn_delta(uid, word + ' ', n))


# -- the final of a long turn, the order of 69.1 -> 105.8 ---------------------------------------------------------------------------------

def test_the_final_of_a_long_turn_a_stable_partial_took_at_its_start_is_judged(rig):
    """The turn opened at 69.1 with the end of a portion, the stable partial took it; its final came 36 s later, past the window of a tail, and was thrown away with all it said."""
    c = rig.w.controller
    plan(rig)
    spoken(rig, 'u2', FIRST_CUE)
    rig.pump(30.0)
    assert c.state()['chunk_index'] == 1, 'precondition: the stable partial took the portion'
    rig.w.feed(S.turn_done('u2', 'user', FIRST_CUE + ' Блин, ну ты, конечно, долго. Сколько будет пять умножить на пять'))
    rig.pump(0.3)
    assert rig.fake.run(1).question.endswith('Сколько будет пять умножить на пять')
    rig.say(1, '25.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert rig.cues()[-1] == '25.'


def test_the_next_portion_said_in_a_long_turn_is_confirmed_and_its_tail_judged(rig):
    """105.8: «кодекса о... общие условия установления налогов и сборов. Блин, ну ты, конечно, долго»: the portion that waited by then is in that final."""
    c = rig.w.controller
    plan(rig)
    spoken(rig, 'u2', FIRST_CUE)
    rig.pump(30.0)
    rig.w.feed(S.turn_done('u2', 'user', FIRST_CUE + ' ' + SECOND + ' Блин, ну ты, конечно, долго'))
    rig.pump(0.3)
    assert c.state()['completed'] and rig.fake.run(1).question.endswith('Сейчас прозвучало: Блин, ну ты, конечно, долго')
    decline(rig, 1)
    assert errors_of(rig) == [] and c.state()['completed'] and c.question_id == 'u1'


def test_with_the_channel_off_the_final_of_a_long_turn_stays_what_it_was():
    world = S.World()
    try:
        world.feed(S.turn_created('u1', 'user', 'Что'))
        world.feed(S.turn_done('u1', 'user', INERTIA.question))
        world.feed(S.turn_created('a1', 'assistant', 'Инерция'))
        world.feed(S.turn_done('a1', 'assistant', ANSWER))
        world.advance(0.5)
        world.feed(S.turn_created('u2', 'user', ''))
        for n, word in enumerate(FIRST_CUE.split()):
            world.feed(S.turn_delta('u2', word + ' ', n))
        world.advance(30.0, step=0.1)
        index = world.controller.state()['chunk_index']
        world.feed(S.turn_done('u2', 'user', FIRST_CUE + ' ' + SECOND + ' Блин, ну ты, конечно, долго'))
        world.advance(0.3, step=0.1)
        assert world.controller.state()['chunk_index'] == index and not world.controller.state()['completed']
    finally:
        world.close()


# -- a number in digits, repeated the way a person says it ---------------------------------------------------------------------------------

@pytest.mark.parametrize('said', ['в девятьсот восемьдесят восьмом году', 'В 988 году', 'во девятьсот восемьдесят восьмом году'])
def test_a_repeat_with_the_preposition_the_answer_left_out_confirms(rig, said):
    """The measured answer to «В каком году …» is «988 году.»: nobody says that without its «в»."""
    year(rig, '988 году.')
    user_says(rig, 'u2', said)
    rig.pump(0.3)
    assert rig.w.controller.state()['completed'] and len(rig.fake.runs) == 1


def test_the_tail_after_a_repeat_with_its_preposition_is_judged(rig):
    year(rig, '988 году.')
    user_says(rig, 'u2', 'в девятьсот восемьдесят восьмом году, ты уверена')
    rig.pump(0.3)
    assert not rig.w.controller.state().get('completed') and rig.fake.run(1).question.endswith('ты уверена'), 'H6 item 4 moved this test: «<порция>, ты уверена» is no repeat'


@pytest.mark.parametrize('said', ['в девятьсот восемьдесят девятом году', 'в тысяча девятьсот восемьдесят восьмом году'])
def test_a_preposition_forgives_no_other_number(rig, said):
    year(rig, '988 году.')
    user_says(rig, 'u2', said)
    rig.pump(0.3)
    assert not rig.w.controller.state()['completed']


def test_a_portion_that_has_its_preposition_is_held_to_it(rig):
    year(rig, 'В 988 году.')
    user_says(rig, 'u2', 'на девятьсот восемьдесят восьмом году')
    rig.pump(0.3)
    assert not rig.w.controller.state()['completed']


@pytest.mark.parametrize('answer, said', [('С 1941 по 1945 год.', ['с тысяча девятьсот сорок первого по тысяча девятьсот сорок пятый год']),
                                          # R21-03: «с 1941 по 1945 год» is one range and no longer cut before «по» (the first cue «с 1941» stated another war);
                                          # the year before «по» is still confirmed in words, now inside the one portion that holds the range
                                          ('Шла с 1941 по 1945 год.', ['шла с тысяча девятьсот сорок первого по тысяча девятьсот сорок пятый год'])])
def test_a_range_of_years_in_digits_is_confirmed_in_words(rig, answer, said):
    """A year before «по» has no «года» after it: its digits read as a cardinal, the spoken year is an ordinal, and the same year did not confirm."""
    user_says(rig, 'u1', 'Когда шла Великая Отечественная война')
    rig.say(0, answer)
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert len(rig.w.controller.state()['chunks']) == len(said)
    for n, words in enumerate(said):
        user_says(rig, 'u%d' % (n + 2), words)
        rig.pump(0.3)
    assert rig.w.controller.state()['completed'] and len(rig.fake.runs) == 1


def test_another_year_of_a_range_does_not_confirm(rig):
    user_says(rig, 'u1', 'Когда шла Великая Отечественная война')
    rig.say(0, 'С 1941 по 1945 год.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    user_says(rig, 'u2', 'с тысяча девятьсот сорок первого по тысяча девятьсот сорок шестой год')
    rig.pump(0.3)
    assert not rig.w.controller.state()['completed']


@pytest.mark.parametrize('portion, said', [('988 году.', 'Восемьсот восемьдесят восьмой'), ('25', 'двадцать шесть'), ('Крещение Руси произошло в 988 году.', 'Восемьсот восемьдесят восьмой')])
def test_a_wrong_number_at_a_portion_in_digits_is_no_other_speech(rig, portion, said):
    """164.6 and 177.2 of the call, with the job's digits: the words of a wrong number share no stem with «988», the portion read as other speech, and after the cap of the repeats
    it was thrown away. In words (the cloud's text) the same repeat is a try that failed. The job still judges the final."""
    c = rig.w.controller
    year(rig, portion)
    rig.pump(20.0)
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u3', 'user', said))
    rig.pump(1.7)                               # H6 item 3: a number with no unit is an open tail: the job goes 1.5 s later
    assert c.state()['answer'] == portion and len(rig.fake.runs) == 2


def test_other_speech_at_a_portion_in_digits_still_gives_it_up(rig):
    c = rig.w.controller
    year(rig, '988 году.')
    rig.pump(20.0)
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u3', 'user', 'Хорошо, давайте поговорим о чём-нибудь другом'))
    rig.pump(0.3)
    assert c.state()['answer'] == ''


# -- talk about itself said first, the same words as at 143.7 in another order --------------------------------------------------------------

FIRST_TALK = ['Понял тебя, буду реагировать быстрее.', 'Понял, буду реагировать быстрее.', 'Давай ещё вопрос.', 'Хорошо, буду быстрее.']


@pytest.mark.parametrize('talk', FIRST_TALK)
def test_talk_about_itself_said_first_is_no_portion_of_a_job(rig, talk):
    user_says(rig, 'u1', 'Сколько будет пять умножить на пять?')
    rig.say(0, talk + ' Двадцать пять.')
    rig.fake.run(0).finish()
    rig.pump(0.5)
    assert rig.cues() == ['Двадцать пять.']


@pytest.mark.parametrize('talk', FIRST_TALK)
def test_talk_about_itself_said_first_is_no_portion_of_the_cloud_either(rig, talk):
    user_says(rig, 'u1', 'Сколько будет пять умножить на пять?')
    rig.fake.run(0).fail()
    rig.pump(0.2)
    rig.fake.run(1).fail()
    rig.pump(0.2)
    cloud_says(rig, 'a1', talk + ' Это произведение чисел.')
    rig.pump(1.5)
    assert rig.cues() == ['Это произведение чисел.']


def test_talk_said_first_never_reaches_a_cue_as_it_grows(rig):
    user_says(rig, 'u1', 'Сколько будет пять умножить на пять?')
    for piece in ['Понял', ' тебя', ',', ' буду', ' реагировать', ' быстрее', '.', ' Двадцать', ' пять', '.']:
        rig.fake.run(0).say(piece)
        rig.pump(0.1)
    rig.fake.run(0).finish()
    rig.pump(0.5)
    assert rig.cues() == ['Двадцать пять.']


def test_talk_said_first_is_not_what_a_candidate_is_admitted_with(rig):
    plan(rig)
    user_says(rig, 'u2', PREFACED)
    rig.say(1, 'Понял, буду быстрее. Пять на пять — это 25.')
    rig.fake.run(1).finish()
    rig.pump(0.5)
    assert rig.cues() == [FIRST_CUE, 'Пять на пять — это 25.']


@pytest.mark.parametrize('said', ['Жду следующий вопрос.', 'Понял тебя, буду быстрее.', 'Давай ещё вопрос. Понял тебя.'])
def test_a_question_whose_job_says_only_talk_is_declined_though_the_question_may_go_on(rig, said):
    """Nothing is left of the text: it does not wait for the hold of the question and then for the watchdog."""
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Какой у нас следующий вопрос?')
    rig.say(1, said)
    rig.fake.run(1).finish()
    rig.pump(0.5)
    assert c.question_id is None and rig.cues() == [FIRST_CUE, FIRST_CUE], (rig.cues(), c.question_id)


@pytest.mark.parametrize('text, cue', [('25. Понял тебя, буду реагировать быстрее.', '25.'), ('25. Давай ещё вопрос.', '25.'), ('Ответ 25. Хочешь ещё пример?', 'Ответ 25.'),
                                        ('Статья 21. Понял тебя.', 'Статья 21.')])
def test_a_sentence_that_ends_in_digits_is_a_sentence_for_the_talk_after_it(rig, text, cue):
    """The job writes numbers in digits, and a mark after a digit was no sentence end: the tail of 143.7 and the answer before it were one sentence, and went or stayed together."""
    user_says(rig, 'u1', 'Сколько будет пять умножить на пять?')
    rig.say(0, text)
    rig.fake.run(0).finish()
    rig.pump(0.5)
    assert rig.cues() == [cue]


def test_a_mark_inside_a_number_ends_no_sentence():
    text = 'Ставка 2.5 процента. Она действует с 2024 года.'
    assert drop_process_sentences(text, 'Какая ставка', final=True, talk=True) == text


@pytest.mark.parametrize('tail', ['Понял, буду реагировать быстрее.', 'Попробуем ещё раз.', 'Ну что обсудим сегодня?', 'Буду быстрее.'])
def test_a_remark_in_front_of_the_question_does_not_make_it_a_question_to_a_person(tail):
    """136.4 of the call: «… значит медленно пока реагируешь. Хорошо. Пять умножить на пять»: the 2nd person is in the remark, the question is the last sentence."""
    assert drop_process_sentences('Двадцать пять. ' + tail, PREFACED, final=True, talk=True) == 'Двадцать пять.'


@pytest.mark.parametrize('question', ['Хорошо, спасибо. Почему вы ушли с прошлой работы?', 'Расскажи о себе. Коротко.', 'Какой у вас опыт?'])
def test_a_question_to_a_person_after_a_remark_stays_one(question):
    text = 'Я хочу расти. Я быстро учусь.'
    assert drop_process_sentences(text, question, final=True, talk=True) == text


@pytest.mark.parametrize('text', ['А что именно вас интересует?', 'Что ещё разобрать?', 'Какой следующий вопрос?'])
def test_a_question_back_on_an_open_question_is_no_answer(rig, text):
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Какой у нас следующий вопрос?')
    rig.say(1, text)
    rig.fake.run(1).finish()
    rig.pump(0.5)
    assert c.question_id is None and rig.cues() == [FIRST_CUE, FIRST_CUE], (rig.cues(), c.question_id)


@pytest.mark.parametrize('tail', ['Что ещё разобрать?', 'Какой следующий вопрос?', 'Ещё вопросы?'])
def test_a_question_back_after_the_answer_is_no_portion(tail):
    assert drop_process_sentences('Амортизация уменьшает прибыль. ' + tail, 'Что такое амортизация', final=True, talk=True) == 'Амортизация уменьшает прибыль.'


def test_a_question_said_for_the_listener_to_a_person_stays():
    text = 'Я хочу расти. Какие задачи будут на испытательном сроке?'
    assert drop_process_sentences(text, 'Какие у вас вопросы к нам?', final=True, talk=True) == text


@pytest.mark.parametrize('text, question', [('Перенеси икс влево. Раздели обе части на два.', 'Как решить уравнение'), ('Позвони в пожарную службу. Выйди из здания.', 'Что делать при пожаре')])
def test_an_instruction_to_one_person_is_how_a_procedure_is_told(text, question):
    assert drop_process_sentences(text, question, final=True, talk=True) == text


@pytest.mark.parametrize('sentence', ['Давай разберём логику.', 'Спрашивай.', 'Задавай следующий вопрос.'])
def test_an_order_with_nothing_of_its_own_is_talk(sentence):
    assert drop_process_sentences('Амортизация уменьшает прибыль. ' + sentence, 'Что такое амортизация', final=True, talk=True) == 'Амортизация уменьшает прибыль.'


# -- the verdict -------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('said', ['—.', '«—»', '"—"', '— —', '…', '.', '-.', '**—**', '( — )'])
def test_a_text_with_no_word_in_it_is_the_decline(rig, said):
    assert FT.brain_answer(said) == ''
    plan(rig)
    c = rig.w.controller
    user_says(rig, 'u2', 'Какой у нас следующий вопрос?')
    rig.say(1, said)
    rig.fake.run(1).finish()
    rig.pump(0.5)
    assert c.question_id is None and rig.cues() == [FIRST_CUE, FIRST_CUE], (rig.cues(), c.question_id)


@pytest.mark.parametrize('old, new, expected', [
    ('Крещение Руси произошло в 988 году при князе Владимире. Он правил до 1015 года.', 'Да, в 988 году.', False),
    ('В 2024 году ставка 20 процентов, а с 2025 года 22 процента.', 'Да, 22 процента.', False),
    ('Это было в 988-м при Владимире.', 'Да, 988.', False),
    ('988 год, 1015 год.', '998 год, 1015 год.', True),
    ('1988 год.', '988 год.', True),
    ('988 год и 1015 год.', 'Точно сказать нельзя.', True),
])
def test_a_doubt_confirmed_with_fewer_numbers_is_no_repair(old, new, expected):
    assert FT.revises(old, new, heard='ты уверена', question='Когда было крещение Руси') is expected


def test_a_doubt_confirmed_with_fewer_numbers_keeps_the_answer_and_the_plan_on_the_wire(rig):
    c = rig.w.controller
    user_says(rig, 'u1', BAPTISM)
    rig.say(0, 'Крещение Руси произошло в 988 году при князе Владимире. Он правил до 1015 года.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    user_says(rig, 'u2', 'ты уверена')
    rig.say(1, 'Да, в 988 году.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert not any(entry.get('status') == 'revised' for entry in history(rig)) and c.suspended is not None


def test_a_job_the_sources_of_the_open_question_replaced_is_asked_again(rig):
    """A lookup is under way, a final with no form gets its job, the sources come: the one job of the channel goes to them, and the candidate waited for ever on a job that was gone."""
    c = rig.w.controller
    grounding, without_source = c.grounding, c.without_source
    c.grounding, c.without_source = (lambda epoch, rows: []), (lambda epoch, why: None if why == 'failed' else without_source(epoch, why))
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', VERIFY))
    rig.pump(0.2)
    c.grounding, c.without_source = grounding, without_source
    user_says(rig, 'u2', 'Пять умножить на пять')
    rig.pump(0.2)
    first = rig.fake.run(0)
    assert c.candidate['job'] and first.question.endswith('Пять умножить на пять')
    rig.w.run(rig.w.wire.actions(c.grounding(c.epoch, S.SOURCE_ROWS)))
    rig.w.settle()
    rig.pump(0.2)
    assert until(first.cancelled.is_set)
    rig.say(1, 'Гидравлический удар — резкий скачок давления в трубопроводе.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert len(rig.fake.runs) == 3 and rig.fake.run(2).question.endswith('Пять умножить на пять')
    rig.say(2, '25.')
    rig.fake.run(2).finish()
    rig.pump(0.3)
    assert rig.cues()[-1] == '25.' and c.candidate is None


@pytest.mark.parametrize('said', ['Разве?', 'Неужели?'])
def test_a_doubt_with_no_content_word_goes_to_the_job(rig, said):
    """«Разве?» is a doubt for `revises`, but the arbiter wanted a content word and nobody judged it."""
    year(rig, '988 году.')
    user_says(rig, 'u2', said)
    rig.pump(0.3)
    assert rig.fake.run(1).question.endswith('Сейчас прозвучало: ' + said)


def test_a_doubt_with_no_content_word_after_a_repeat_goes_to_the_job(rig):
    year(rig, '988 году.')
    user_says(rig, 'u2', 'девятьсот восемьдесят восьмом году, разве?')
    rig.pump(0.3)
    assert not rig.w.controller.state().get('completed') and rig.fake.run(1).question.endswith('разве?'), 'H6 item 4 moved this test'


@pytest.mark.parametrize('said', ['Угу', 'Ага', 'Да', 'Ну'])
def test_a_backchannel_is_still_asked_of_nobody(rig, said):
    year(rig, '988 году.')
    user_says(rig, 'u2', said)
    rig.pump(0.3)
    assert len(rig.fake.runs) == 1


def test_a_final_said_before_the_job_of_the_one_before_has_ruled_goes_to_the_job_with_it(rig):
    """«Пять умножить на пять» | «Ну давай быстрее уже»: the second replaced the first, its job was cancelled, and what the job then saw was the remark alone: the question was lost."""
    c = rig.w.controller
    user_says(rig, 'u1', 'Пять умножить на пять')
    rig.pump(0.3)
    first = rig.fake.run(0)
    user_says(rig, 'u2', 'Ну давай быстрее уже')
    rig.pump(0.3)
    assert until(first.cancelled.is_set) and rig.fake.run(1).question == 'Пять умножить на пять Ну давай быстрее уже'
    rig.say(1, '25.')
    rig.fake.run(1).finish()
    rig.pump(0.3)
    assert rig.cues() == ['25.'] and c.question_id == 'u2' and 'Пять умножить на пять' in c.question_text


def test_a_final_after_a_verdict_goes_to_the_job_alone(rig):
    user_says(rig, 'u1', 'Хорошо, я готовился')
    decline(rig, 0)
    user_says(rig, 'u2', 'Пять умножить на пять')
    rig.pump(0.3)
    assert rig.fake.run(1).question == 'Пять умножить на пять'


def test_a_repeat_after_an_unjudged_final_leaves_nothing_of_it_for_the_next_one(rig):
    plan(rig)
    user_says(rig, 'u2', 'Хорошо, я готовился')
    rig.pump(0.2)
    user_says(rig, 'u3', S.relaxed(FIRST_CUE))
    rig.pump(0.2)
    user_says(rig, 'u4', 'Пять умножить на пять')
    rig.pump(0.3)
    assert rig.fake.runs[-1].question.endswith('Сейчас прозвучало: Пять умножить на пять')


def test_a_question_taken_on_a_partial_is_not_judged_before_its_final(rig):
    """Rule 2 is about finals. The cloud's delegation may open a question on a partial («Что говорится в девятой статье» on the way to «… Налогового кодекса России»): a job on that
    half said «—», the question was dropped while it was still being said, and its final, a turn already seen, was nobody's."""
    c = rig.w.controller
    rig.w.feed(S.turn_created('u1', 'user', 'Что говорится в девятой статье'))
    rig.pump(0.2)
    rig.w.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    rig.pump(0.2)
    assert c.question_id == 'u1' and rig.fake.runs == [], 'no job on half a question'
    rig.w.feed(S.turn_done('u1', 'user', 'Что говорится в девятой статье'))
    rig.pump(0.2)
    assert len(rig.fake.runs) == 1
    rig.say(0, 'Девятая статья перечисляет участников налоговых отношений.')
    rig.fake.run(0).finish()
    rig.pump(0.5)
    assert rig.cues() and c.question_id == 'u1'


def result_of(rig, delegation):
    return [frame for kind, frame in rig.w.source.frames if kind == 'E' and delegation in frame.decode('utf-8', 'replace')]


def test_the_delegation_of_a_declined_candidate_gets_its_result(rig):
    """The model asked for a search on a remark and waits for that result. Declined, the final was left with it unanswered: the fallback of the next job that fails would be a model
    still waiting (DEF-T-B15)."""
    user_says(rig, 'u1', REMARK)
    rig.pump(0.2)
    rig.w.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    rig.pump(0.2)
    assert result_of(rig, 'd1') == []
    decline(rig)
    assert len(result_of(rig, 'd1')) == 1 and rig.cues() == [] and rig.w.controller.question_id is None


def test_a_delegation_that_comes_after_the_decline_gets_its_result(rig):
    user_says(rig, 'u1', REMARK)
    decline(rig)
    rig.w.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    rig.pump(0.2)
    assert len(result_of(rig, 'd1')) == 1 and rig.cues() == []


ROW_21 = 'Статья 21 Налогового кодекса перечисляет права налогоплательщиков.'


@pytest.mark.parametrize('text, kept', [(ROW_21, True), ('Статья 22 Налогового кодекса перечисляет гарантии прав налогоплательщиков.', False)])
def test_a_number_said_in_words_is_compared_with_a_source_by_value(rig, text, kept):
    """20:38:42 of the call: `sources_unrelated number=3`: «двадцать первой» and «21» share no stem, so every row went as another number and the answer came from memory."""
    c = rig.w.controller
    c.question_id, c.lookup_query = 'u1', ARTICLE_21
    assert bool(c._relevant([{'url': 'https://example.org/21', 'text': text}])) is kept


def test_with_the_channel_off_a_source_is_compared_as_it_was():
    world = S.World()
    try:
        c = world.controller
        c.question_id, c.lookup_query = 'u1', ARTICLE_21
        assert c._relevant([{'url': 'https://example.org/21', 'text': ROW_21}]) == []
    finally:
        world.close()


def test_the_article_of_the_call_is_answered_from_its_source(rig, monkeypatch):
    no_base(monkeypatch)
    monkeypatch.setattr(S, 'SOURCE_ROWS', [{'url': 'https://example.org/21', 'title': 'Статья 21', 'text': ROW_21}])
    user_says(rig, 'u1', ARTICLE_21)
    rig.pump(0.2)
    rig.say(0, 'Статья 21 перечисляет права налогоплательщиков.')
    rig.fake.run(0).finish()
    rig.pump(0.3)
    assert ROW_21 in rig.fake.run(1).request['input'][0]['content'][0]['text']


def test_a_final_begun_over_a_cue_goes_to_the_job_too(rig):
    """The examiner speaks while a cue plays: its speech start is in the span of the cue, so the final was «our own voice» evidence and no candidate, and nobody judged it."""
    c = rig.w.controller
    plan(rig)
    now = c.clock()
    c.cue_window, c.cue_heard, c.cue_input_ms = [now - 1.0, now + 5.0], True, None
    rig.w.feed(S.turn_created('u2', 'user', ''))
    from echo_sync.utterance_judge import AcceptCtx
    seen = AcceptCtx({'id': 'u2'}, 'provider_turn_done', False, '', False, False, False, 'u2', '', c.state())
    c._rule_own_voice(seen)
    assert seen.evidence is not None, 'precondition'
    rig.w.feed(S.turn_done('u2', 'user', 'Пять умножить на пять'))
    rig.pump(0.3)
    assert rig.fake.run(1).question.endswith('Сейчас прозвучало: Пять умножить на пять')


# -- the whole call, in the order of its own log ----------------------------------------------------------------------------------------------

CALL_2034 = [
    (22.8, 'ustart', '9oIOv', ''),
    (26.8, 'user', '9oIOv', 'Да, конечно, 25 секунд подключаться — это мощно.'),
    (26.8, 'astart', '38U48', ''),
    (31.0, 'cloud', '38U48', '  Ну наконец-то. Ну что обсудим сегодня?'),
    (37.6, 'ustart', 'PhBwo', ''),
    (41.3, 'user', 'PhBwo', 'Хорошо. Да, я готовился на самом деле'),
    (41.4, 'astart', 'a35od', ''),
    (41.5, 'cloud', 'a35od', '  Мг.'),
    (41.6, 'ustart', 'UqT1F', ''),
    (52.2, 'user', 'UqT1F', 'Да, я готовился. Готовился в целом, в целом. Ну что, давайте задавайте любой вопрос, собственно, готов'),
    (52.3, 'astart', 'Q8hJW', ''),
    (53.3, 'cloud', 'Q8hJW', '  Давай такой'),
    (53.3, 'ustart', '8XN04', ''),
    (55.2, 'user', '8XN04', 'Да, какой еще раз вопрос'),
    (55.2, 'astart', 'UoKOC', ''),
    (56.2, 'cloud', 'UoKOC', '  Да. Сначала простой вопрос.'),
    (56.2, 'ustart', '13Vkn', ''),
    (59.0, 'user', '13Vkn', 'Семнадцатая статья Налогового кодекса'),
    (59.1, 'astart', 'eAExX', ''),
    (62.1, 'cloud', 'eAExX', '  Мг. Ну давай такой сначала вопрос. Дава'),
    (62.1, 'ustart', 'YcYTa', ''),
    (62.9, 'user', 'YcYTa', 'Ага'),
    (63.0, 'astart', 'ZR9He', ''),
    (66.6, 'cloud', 'ZR9He', ' й представим, что твой знакомый'),
    (66.7, 'ustart', 'metQg', ''),
    (68.8, 'user', 'metQg', 'Статья 17 Налогового'),
    (68.9, 'astart', 'TToWz', ''),
    (69.1, 'cloud', 'TToWz', '  Ммм.'),
    (69.1, 'ustart', 'y8F4M', ''),
    (105.8, 'user', 'y8F4M', 'кодекса о... общие... общие... общие условия установления налогов и сборов. Блин, ну ты, конечно, долго. Вот я, допустим, тупил'),
    (105.8, 'astart', '0p7Xu', ''),
    (106.9, 'cloud', '0p7Xu', '  Ммм. Ммм.'),
    (106.9, 'ustart', 'o6RIY', ''),
    (129.6, 'user', 'o6RIY', 'целенаправленно, а ты мне подсказываешь секунд через шесть, через семь, ну это вообще очень плохо. Ты у тебя уже был, уже хороший, быстрый такой повтор. Ну видимо я до этого просто без ошибок повтор твой смотрел, а сейчас вот если легкую ошибку допускать, если я хоть что-то не расслышал, то ты все, ты вовремя не подсказываешь, а надо наоборот, чтобы ты прям вот говорила, говорила'),
    (129.8, 'astart', 'zzeos', ''),
    (129.9, 'cloud', 'zzeos', '  Мг.'),
    (129.9, 'ustart', 'VlOS0', ''),
    (136.4, 'user', 'VlOS0', ', прям подсказывала, быстрее реагировать нужно, значит медленно пока реагируешь. Хорошо. Пять умножить на пять'),
    (136.6, 'astart', 'E95QX', ''),
    (143.7, 'cloud', 'E95QX', '  Двадцать пять. Понял тебя, буду реагировать быстрее, не тянуть. Давай ещё вопрос, попробуем в таком темпе.'),
    (143.7, 'ustart', 'xvvTX', ''),
    (150.4, 'user', 'xvvTX', 'Двадцать пять. Хорошо, считаем быстро. Так, в каком году было крещение Руси'),
    (150.5, 'astart', 'T0wkF', ''),
    (152.6, 'cloud', 'T0wkF', '  Тысяча девятьсот восемьдесят восьмой.'),
    (153.7, 'astart', 'rLK0d', ''),
    (159.1, 'cloud', 'rLK0d', '  Извини, запнулся. Крещение Руси — это восемьсот восемьдесят восьмой, без «тысяча».'),
    (159.2, 'ustart', '3oyuR', ''),
    (164.6, 'user', '3oyuR', 'А тысяча девятьсот восемьдесят восьмой, ты уверена'),
    (164.7, 'astart', 'F5fSt', ''),
    (168.4, 'cloud', 'F5fSt', '  Ммм. Нет, восемьсот восемьдесят восьмой. Ошибся, когда произнёс сначала.'),
    (174.8, 'ustart', 'vDKup', ''),
    (177.2, 'user', 'vDKup', 'Восемьсот восемьдесят восьмой'),
    (177.3, 'astart', 'bT4dH', ''),
    (177.4, 'cloud', 'bT4dH', '  Да.'),
    (177.4, 'ustart', 'CnLrJ', ''),
    (237.0, 'user', 'CnLrJ', '. Ну короче, у тебя ответы тупо вообще неправильные какие-то пошли, я понял, выдуманные. Но зато, кстати, да, почти пять секунд. Но это ответ выдуманный ни о чём, типа блин, это... зачем такие ответы? Короче, тоже слабоватенько пока. Не-не-не, нужно прям дорабатывать сценарий прям, прогонять. Вот такие же проблемы придумывать, как я и до этого придумывал. Вот. Это же стандартные проблемы, таких проблем ну... по классам придумать, я не знаю, штук тридцать-сорок таких классовых проблем и в сценарии вот таких найти, искать. Или там взять уже готовый диалог, как люди общаются, как опрашивают людей. Вот в интернете и добавить просто эти классы проблем в этот диалог, и все, и смотреть как система отрабатывает по-разному вставлять эти пробелы. Тогда система отработает'),
    (237.4, 'astart', 'FCrkk', ''),
    (237.8, 'cloud', 'FCrkk', '  Принял, посмотрю, как'),
    (237.9, 'ustart', 'sD2NA', ''),
    (239.7, 'user', 'sD2NA', 'Короче, пока что слабо, понял'),
    (239.9, 'astart', 'TVEZO', ''),
    (241.2, 'cloud', 'TVEZO', '  это упаковать в нормальный план.'),
    (241.4, 'ustart', 'CpcpF', ''),
    (244.8, 'user', 'CpcpF', 'А с двадцать первой статье Налогового кодекса'),
    (244.9, 'astart', 'aj0UT', ''),
    (247.7, 'cloud', 'aj0UT', '  Секунду, уточню формулировку.'),
    (249.7, 'astart', 'fECI6', ''),
    (261.5, 'cloud', 'fECI6', '  По памяти, статья 21 — это про права налогоплательщиков. Точную формулировку по пунктам сейчас не воспроизведу, но если хочешь, можем разобрать логику и пример'),
    (264.3, 'ustart', 'Kd8hu', ''),
]


def job_of_the_call(question):
    """What the experiment measured: «—» to a remark, the digits to a question, a held answer to a doubt."""
    heard = question.rsplit('Сейчас прозвучало: ', 1)[-1].casefold()
    if 'уверена' in heard:
        return 'Крещение Руси произошло в 988 году.'
    if 'крещение руси' in heard:
        return '988 году.'
    if 'пять умножить' in heard:
        return '25'
    if 'двадцать первой' in heard:
        return 'Статья 21 Налогового кодекса перечисляет права налогоплательщиков.'
    return '—'


def test_the_call_of_20_34_in_the_order_of_its_log(rig):
    """Every turn start, every word of a final, every turn and final of the cloud at its moment, the job answering 1.2 s after it is asked. `test_the_call_of_20_34_replayed` has the finals
    alone; this one has what those finals are made of: the stable partial at 69.3 took a turn that ended 36 s later, and the cloud's turns overlap the listener's."""
    c = rig.w.controller
    w, fake = rig.w, rig.fake
    t0 = w.clock.now() - 20.0
    asked, served = {}, set()

    def step():
        now = w.clock.now() - t0
        for n, run in enumerate(list(fake.runs)):
            asked.setdefault(n, now)
            if n not in served and now - asked[n] >= 1.2:
                served.add(n)
                if not run.cancelled.is_set():
                    run.say(job_of_the_call(run.question))
                    run.finish()
        w.advance(0.1, step=0.1)

    def until_moment(moment):
        while w.clock.now() - t0 < moment:
            step()

    timeline, opened = [], {}
    for at, kind, key, text in CALL_2034:
        timeline.append((at, kind, key, text))
        if kind == 'ustart':
            opened[key] = at
        elif kind == 'user' and key in opened:
            words = text.split()
            for n, word in enumerate(words[:-1]):
                timeline.append((opened[key] + (at - opened[key]) * (n + 1) / len(words) - 0.01, 'word', key, (word + ' ', n)))
    for at, kind, key, text in sorted(timeline, key=lambda row: row[0]):
        until_moment(at)
        if kind in ('ustart', 'astart'):
            w.feed(S.turn_created(key, 'user' if kind == 'ustart' else 'assistant', ''))
        elif kind == 'word':
            w.feed(S.turn_delta(key, *text))
        else:
            w.feed(S.turn_done(key, 'user' if kind == 'user' else 'assistant', text))
    until_moment(270.0)
    cues = rig.cues()
    questions = [run.question.rsplit('Сейчас прозвучало: ', 1)[-1] for run in fake.runs]
    assert errors_of(rig) == [] and w.violations == [], (errors_of(rig), w.violations)
    assert not any(word in cue for cue in cues for word in ('наконец', 'Понял', 'Давай', 'Ммм', 'восемьсот', 'По памяти', 'хочешь')), cues
    assert cues[0].startswith('Статья 17') and any(cue.lstrip('— ').startswith('общие условия') for cue in cues) and '25' in cues and '988 году.' in cues, cues
    assert any(cue.startswith('Крещение Руси произошло в 988') for cue in cues) and any(cue.startswith('Статья 21') for cue in cues), cues
    # c23: the final of 105.8 (the portion said back and a remark) is no longer asked of a job: since the owner's call of 06.11 (``adds_nothing``, g28 ``_said_back``, laptop c20) a final
    # that adds nothing to the cues is passed as said back with no job. What the job was asked here for — that it is no question and nothing is cued — still holds.
    assert not any('Блин' in str(entry.get('question')) for entry in c.state()['history']) and not any('Блин' in cue for cue in cues), (questions, c.state()['history'])
    assert any(question.endswith('ты уверена') for question in questions) and c.fast_on and not rig.fast.off


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
