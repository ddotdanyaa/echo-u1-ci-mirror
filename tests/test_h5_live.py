"""H5: what the first live run of candidate 14 showed (U1/03_TESTS/corpus_v1/scenarios_n1/runs/20261105-070800, FIRST_DIVERGENCE.md). No network, no sleep: the real NativeMediaSocket, ShadowEar and controller on the injected
clock; only the speech detector, the recognizer's worker, the cloud's events and the job's stream are scripted, each case in the live order of its events. Neighbours are here too, never a rule for one phrase. What this
proves is the logic: nothing here is a measurement of a call.
"""
import logging

import pytest

import helpers_s6_state as S
from echo_sync import fast_text as FT
from echo_sync.classifier import ACK, analyze, open_tail
from echo_sync.timer_policy import ABANDON_SECONDS
from echo_sync.controlled_media import (ANSWER_WAIT_SECONDS, REFUSE_BEFORE_DROP_SECONDS, EAR_BIND_SECONDS, MONOLOGUE_QUIET_SECONDS, EAR_FIRST_BIND_SECONDS, EAR_RELEASE_SILENCE_SECONDS, EAR_TAIL_SILENCE_SECONDS, TEMPO_FILLER_SECONDS,
                                        TEMPO_HOLD_SECONDS)
from echo_sync.fast_text import FIRST_TEXT_S
from echo_sync.first_useful import first_cue
from echo_sync.ru_alignment import _canonical, match_current
from echo_sync.settings import CALL_SETTINGS, resolve
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS
from test_h1_fast_text import settled
from test_h3_tempo import GRID, TICK, call, in_flight       # noqa: F401 - call is the fixture
from test_h4_ear_first import slow

LIVE = {'fast_text': 'on', 'ear_release': 'on', 'max_auto_repeats': 3}     # 702f35b as it runs: local_ear are the rig's
ACCOUNT = 'Как отразить покупку материалов'
MATERIALS = 'Купили материалы за 10 000 рублей: дебет счёта материалов, кредит счёта денег.'
BOUGHT = 'Купили материалы за 10 000 рублей:'
TASK = 'Дальше задачка. Вклад, ну, сто тысяч рублей на два года под десять процентов годовых, нет, не под десять, а под двадцать, проценты простые, сколько, э-э, начислят'
INTEREST = 'Проценты составят 40 000 рублей за 2 года.'


def decisions(caplog, word):
    return [record.getMessage() for record in caplog.records if word in record.getMessage()]


def plan(rig, uid='u0', asked=ACCOUNT, answer=MATERIALS, n=0):
    """The answer in play: its first portion said to its end, nobody has repeated it."""
    rig.asks(uid, asked, n, answer)
    return rig.ended()


def piece(rig, text, speech=1.5, lag=0.1, gap=0.3):
    """One piece of an utterance the detector cut at a comma: its speech, its end, the text, ``gap`` seconds later the next piece may begin. Returns its end."""
    ended = rig.says(text, speech=speech, lag=lag)
    rig.pump(max(0.0, gap - lag - TICK))
    return ended


# =====================================================================================================================================
# 1. the tempo cut a question (n1_01 step 8): any speech with content stops the timer until its final is judged
# =====================================================================================================================================

def test_n1_01_step_8_the_first_piece_of_a_long_question_is_not_answered_with_the_old_portion(call):
    """95.08 speech, 96.92 «Дальше задачка.» at a comma pause, 96.95 replay/ear_tempo, 15 s of question under it."""
    rig = call(**LIVE)
    plan(rig)
    rig.pump(TEMPO_REPEAT_SECONDS - 1.0)                              # the timer runs out inside the speech
    rig.w.feed(S.turn_created('u1', 'user', ''))
    piece(rig, 'дальше задачка', speech=1.5)
    assert rig.said() == [BOUGHT], 'no replay at the comma'
    for text in ('вклад ну сто тысяч рублей на два года', 'под десять процентов годовых', 'нет не под десять а под двадцать', 'проценты простые сколько э-э начислят'):
        piece(rig, text, speech=2.5)
        assert rig.said() == [BOUGHT], 'not in the pauses of the question either'
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', TASK))
    rig.pump(TICK * 2)
    assert rig.said() == [BOUGHT]
    rig.job_says(1, INTEREST)
    assert rig.c.question_id == 'u1' and 'начислят' in rig.c.question_text, 'its final was judged, whole'
    assert rig.said().count(BOUGHT) == 1


@pytest.mark.parametrize('said', ['дальше задачка', 'новый вопрос', 'теперь станок', 'ладно поехали', 'вот смотрите', 'следующая тема'])
def test_a_short_piece_with_content_stops_the_timer_until_its_final(call, said):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(TEMPO_REPEAT_SECONDS - 1.0)
    rig.says(said, speech=1.5)
    assert rig.c.repeat_at is None and rig.c.tempo_hold is not None
    assert rig.next_cue(4.0) is None, 'the old portion waits for what that speech was'


def test_a_decline_runs_the_timer_from_the_moment_of_the_verdict(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(TEMPO_REPEAT_SECONDS - 1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('ну ладно посмотрим', speech=1.5)
    rig.pump(2.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Ну ладно, посмотрим'))
    rig.pump(1.0)
    assert rig.said() == [BOUGHT]
    verdict = rig.w.clock.t
    rig.job_says(1, '—')
    rig.job_ends(1)
    cue = rig.next_cue(5.0)
    assert cue is not None and cue.text == BOUGHT and cue.t - verdict == pytest.approx(TEMPO_REPEAT_SECONDS, abs=3 * GRID)


def test_a_hesitation_over_the_time_waits_a_second_and_a_half_after_its_end(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(TEMPO_REPEAT_SECONDS - 0.5)
    ended = rig.says('э-э', speech=1.5)
    assert rig.said() == [BOUGHT], 'nothing at its text'
    cue = rig.next_cue(2.0)
    assert cue is not None and cue.t - ended == pytest.approx(TEMPO_FILLER_SECONDS, abs=GRID)


@pytest.mark.parametrize('said', ['э-э', 'как там', 'оксим', ''], ids=['filler', 'how', 'noise', 'empty'])
def test_no_replay_while_the_ear_has_speech_open(call, said):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(3.0)
    rig.says(said, speech=1.5)
    rig.pump(0.3)
    uid = rig.onset()                          # it went on after the pause: the wait ran out meanwhile
    assert rig.next_cue(3.0) is None, 'never into speech'
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'э-э')
    assert rig.next_cue(TEMPO_FILLER_SECONDS - 3 * GRID) is None


def test_a_start_of_the_portion_keeps_its_own_time(call):
    """H3 rule 3: the help for a listener who stopped is not a replay over a question: a start is said to the portion."""
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    ended = rig.says('купили материалы', speech=1.0)
    cue = rig.next_cue(2.0)
    assert cue is not None and cue.text.startswith('за 10 000') and cue.t - ended <= 1.2 + GRID


# =====================================================================================================================================
# 2. a first cue over new speech (n1_01 step 16: −6.2 s): it never starts while the ear hears speech, and that speech is judged first
# =====================================================================================================================================

QUESTION = 'Что такое инерция'
INERTIA = 'Инерция — свойство тела сохранять скорость.'
SECOND = 'Что такое амортизация'
WRITE_OFF = 'Амортизация — постепенный перенос стоимости на расходы.'


def answer_over_speech(rig, *, said=INERTIA):
    """The job's answer to the question before arrives while a new utterance is being said: its first cue is ready, the ear hears speech."""
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', QUESTION))
    uid = rig.onset()
    rig.pump(0.5)
    rig.job_says(0, said)
    rig.job_ends(0)
    assert rig.c.published, 'precondition: the answer is ready'
    return uid


def test_n1_01_step_16_the_first_cue_waits_through_the_whole_utterance(call):
    """198.5-212.0 a new question, 203.87 the answer to the one before is ready, 204.98 it was cued: the hold of the ear alone ran out after 1 s."""
    rig = call(**LIVE)
    uid = answer_over_speech(rig)
    rig.pump(6.0)
    assert rig.said() == [], 'never while the ear hears speech'
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'теперь станок стоимость сто двадцать тысяч')
    rig.pump(1.0)
    assert rig.said() == [], 'that speech is judged first'


def test_speech_judged_nothing_lets_the_first_cue_go(call):
    rig = call(**LIVE)
    uid = answer_over_speech(rig)
    rig.pump(2.0)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'ну ладно посмотрим')
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u2', 'user', 'Ну ладно, посмотрим'))
    rig.pump(0.3)
    assert rig.said() == [], 'the job judges it'
    rig.job_says(1, '—')
    rig.job_ends(1)
    assert rig.said() == [rig.c.state()['chunks'][0]], 'nothing asked: the answer goes'


def test_speech_that_is_a_new_question_takes_the_first_cue_with_it(call):
    rig = call(**LIVE)
    uid = answer_over_speech(rig)
    rig.pump(2.0)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'что такое амортизация')
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u2', 'user', SECOND))
    rig.pump(0.3)
    rig.job_says(1, WRITE_OFF)
    rig.job_ends(1)
    assert len(rig.said()) == 1 and 'перенос' in rig.said()[0], 'the answer to the question before is not cued'


@pytest.mark.parametrize('said', ['э-э', 'оксим', ''], ids=['filler', 'noise', 'empty'])
def test_speech_with_no_content_holds_it_to_its_end_only(call, said):
    rig = call(**LIVE)
    uid = answer_over_speech(rig)
    rig.pump(1.5)
    rig.offset()
    rig.pump(0.1)
    assert rig.said() == [], 'its text has not come'
    rig.worker.heard(uid, said)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS)
    assert len(rig.said()) == 1


def test_a_text_that_never_comes_does_not_silence_the_call(call):
    rig = call(**LIVE)
    answer_over_speech(rig)
    rig.pump(0.5)
    rig.offset()
    assert rig.next_cue(1.2) is None
    assert rig.next_cue(0.6) is not None, 'the bound of the text'


def test_a_final_that_never_comes_does_not_silence_the_call(call):
    rig = call(**LIVE)
    uid = answer_over_speech(rig)
    rig.pump(0.5)
    ended = rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'ну ладно посмотрим')
    cue = rig.next_cue(9.0)
    assert cue is not None and ANSWER_WAIT_SECONDS - REFUSE_BEFORE_DROP_SECONDS - GRID <= cue.t - ended <= TEMPO_HOLD_SECONDS + GRID, 'round 3: the hold (EAR_FINAL_SECONDS) and the one walk of the roads of the job on the ear text are inside ONE bound of 8 s from the end of speech (hold8)'


def test_the_clouds_start_of_that_speech_does_not_lose_the_first_cue(call):
    """The cloud announces the new turn seconds late, while the ear still hears it: nothing is playing, there is nothing to cut."""
    rig = call(**LIVE)
    uid = answer_over_speech(rig)
    rig.pump(1.5)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'э-э')
    rig.pump(EAR_RELEASE_SILENCE_SECONDS)
    assert len(rig.said()) == 1, 'it plays once'
    rig.pump(1.0)
    assert len(rig.said()) == 1


def test_a_first_cue_of_the_base_has_no_second_of_the_ear_either(call):
    """The cloud has said nothing of this speech yet: only the ear hears it, and that gave any cue 1 s."""
    rig = call(**LIVE)
    uid = rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Семнадцатая статья Налогового кодекса'))
    rig.pump(2.0)
    assert rig.said() == []
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, '')
    rig.pump(TICK * 2)
    assert len(rig.said()) == 1


def test_a_reference_the_ear_opens_on_an_open_turn_goes_at_once(call):
    """What the ear has just acted on is judged: the same tick's text holds no first cue."""
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    uid = rig.onset()
    rig.pump(1.4)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, 'семнадцатая статья налогового кодекса')
    rig.pump(TICK * 3)
    assert len(rig.said()) == 1


def test_a_first_cue_of_the_base_waits_the_same(call):
    rig = call(**LIVE)
    uid = rig.onset()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Семнадцатая статья Налогового кодекса'))
    rig.pump(2.0)
    assert rig.said() == []
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, '')
    rig.pump(TICK * 2)
    assert len(rig.said()) == 1


def test_a_monologue_does_not_hold_it_for_ever(call):
    """R2.5: no hold without a bound. H6 item 6 moved this test: one stretch of speech with no offset and no text is a stuck detector, and it holds a first cue 8 s (HOLD_BOUNDS)."""
    rig = call(**LIVE)
    answer_over_speech(rig)
    rig.pump(7.0)
    assert rig.said() == []
    rig.pump(2.0)
    assert len(rig.said()) == 1


# =====================================================================================================================================
# 3. commands in live speech: the job's text exactly a mark is that command, by the existing paths, with a plan in play; with none, silence
# =====================================================================================================================================

STOP_HEARD = 'Стоп, подождите секунду, у меня телефон, ну, звонит'
BACK_HEARD = 'Так, я вернулась. Продолжайте, э-э, на чём мы остановились'
NOTICE = 'Минимум за 2 недели.'


def job_mark(rig, n, mark, pieces=False):
    """The job says the mark and is over. ``pieces``: as a stream may, a letter at a time: nothing of it may reach the listener meanwhile."""
    for piece in (mark if pieces else [mark]):
        rig.job_says(n, piece)
    rig.job_ends(n)


def said_to_the_room(rig, uid, text):
    rig.w.feed(S.turn_created(uid, 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK * 2)


def test_the_brain_is_the_measured_one_with_the_first_words_rule():
    assert FT.BRAIN.startswith('Ты суфлёр') and 'Если вопроса нет, выведи ровно один символ: —. Это знак «вопроса нет», а не «не знаю»' in FT.BRAIN
    assert ('Если человек обращается к подсказке с просьбой, выведи только метку, без других слов: [стоп], когда просит остановиться или подождать; [продолжай], когда просит продолжить с того '
            'места, вернуться к прежнему ответу или спрашивает, где остановились; [повтори], когда не расслышал или просит сказать ещё раз; [дальше], когда просит перейти к следующей части ответа.') in FT.BRAIN
    assert 'На вопрос, требующий да или нет, начинай ответ со слова да или нет.' in FT.BRAIN
    assert 'Первые слова ответа' in FT.BRAIN and FT.BRAIN_POLICY.startswith(FT.BRAIN)


@pytest.mark.parametrize('said, word', [('[стоп]', 'стоп'), ('[продолжай]', 'продолжай'), ('[повтори]', 'повтори'), ('[дальше]', 'дальше'), (' [стоп]\n', 'стоп')])
def test_a_text_that_is_exactly_a_mark_is_the_command(said, word):
    assert FT.brain_command(said) == word and FT.brain_answer(said) == ''


@pytest.mark.parametrize('said', ['стоп', '[Стоп] ждём', '[стоп].', 'Стоп — это сигнал.', '[пока]', '', '—', '[стоп] [дальше]'])
def test_anything_else_is_no_command(said):
    assert FT.brain_command(said) is None


@pytest.mark.parametrize('said', ['[', '[ст', '[стоп', '[стоп] подождите', '[пока]'])
def test_a_text_that_opens_with_a_bracket_is_never_an_answer(said):
    assert FT.brain_answer(said) == ''


def test_n1_02_step_15_the_stop_holds_and_seventy_seconds_of_silence_bring_nothing(call):
    """139.2 «Стоп, подождите секунду…», 146.5 its final, 147.8 the job said «—», 151.3 the plan was replayed through the stop."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', STOP_HEARD)
    job_mark(rig, 1, '[стоп]', pieces=True)
    assert rig.c.state()['paused'] is True and rig.said() == [NOTICE]
    rig.pump(70.0)
    assert rig.said() == [NOTICE], 'no automatic replay until the listener resumes'


def test_n1_02_step_17_the_resume_after_the_stop_says_the_portion_once(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    said_to_the_room(rig, 'u1', STOP_HEARD)
    job_mark(rig, 1, '[стоп]')
    rig.pump(70.0)
    said_to_the_room(rig, 'u2', BACK_HEARD)
    job_mark(rig, 2, '[продолжай]')
    rig.pump(TICK * 2)
    assert rig.said() == [NOTICE, NOTICE] and not rig.c.state().get('paused')
    assert rig.c.question_id == 'u0', 'no question was opened: the paused answer stays where it was'


@pytest.mark.parametrize('mark', ['[продолжай]', '[повтори]'])
def test_a_plan_abandoned_by_that_very_final_comes_back(call, caplog, mark):
    """231.29 ``portion_abandoned`` retired the plan just before: «продолжайте» then had nothing, and 46 s of silence followed."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Телефон звонит у соседа за стеной')
    job_mark(rig, 1, '—')
    rig.c.repeat_at = None
    rig.pump(ABANDON_SECONDS + 1.0)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        said_to_the_room(rig, 'u2', BACK_HEARD)
    assert decisions(caplog, 'portion_abandoned'), 'precondition: it was abandoned'
    job_mark(rig, 2, mark)
    rig.pump(TICK * 2)
    assert rig.said()[-1] == NOTICE and len(rig.said()) >= 2 and rig.c.state()['chunks'] == [NOTICE]


@pytest.mark.parametrize('mark', ['[стоп]', '[продолжай]', '[повтори]', '[дальше]'])
def test_with_no_plan_a_mark_is_silence(call, mark):
    rig = call(**LIVE)
    said_to_the_room(rig, 'u1', 'Подождите минутку, сейчас посмотрю')
    job_mark(rig, 0, mark)
    rig.pump(2.0)
    assert rig.said() == [] and rig.c.question_id is None and not rig.w.errors


def test_a_mark_with_words_after_it_is_never_said(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    said_to_the_room(rig, 'u1', STOP_HEARD)
    job_mark(rig, 1, '[стоп] Подождите, пожалуйста.')
    assert not any('[' in text or 'Подождите' in text for text in rig.said())


def test_the_mark_of_a_repeat_says_the_portion_again_at_once(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Как ты сказала?')
    job_mark(rig, 1, '[повтори]')
    assert rig.said() == [NOTICE, NOTICE]
    assert rig.c.state()['chunk_index'] == 0


def test_the_mark_of_next_goes_one_portion_forward(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=MATERIALS)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Это я понял, что там по ответу дальше')
    job_mark(rig, 1, '[дальше]')
    rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 1 and len(rig.said()) == 2 and rig.said()[1] != BOUGHT


def test_a_repeat_after_the_end_of_an_answer_says_its_last_portion(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.w.feed(S.turn_done('u1', 'user', NOTICE))
    rig.pump(TICK * 3)
    assert rig.c.state()['completed'] is True
    said_to_the_room(rig, 'u2', 'Как ты сказала?')
    job_mark(rig, 1, '[повтори]')
    assert rig.said() == [NOTICE, NOTICE]


def test_a_question_the_classifier_opened_gives_the_plan_back_to_the_command(call):
    """«Вернёмся к двойной записи. На чём мы остановились?»: a question in form, the plan it took over is what the command is about."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Какой следующий вопрос нам задать сейчас?')
    assert rig.c.question_id == 'u1', 'precondition: the classifier opened it'
    job_mark(rig, 1, '[продолжай]')
    rig.pump(TICK * 2)
    assert rig.said() == [NOTICE, NOTICE] and rig.c.question_id is None


def test_a_stop_to_a_question_the_classifier_opened_pauses_the_plan_it_took_over(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Какой следующий вопрос нам задать сейчас?')
    job_mark(rig, 1, '[стоп]')
    rig.pump(10.0)
    assert rig.said() == [NOTICE] and rig.c.state()['paused'] is True and rig.c.state()['chunks'] == [NOTICE]


def test_a_mark_before_the_final_opens_nothing_from_the_ear(call):
    """Rule 2 of H4 reads the job prepared on the ear: a mark is no answer to open on."""
    rig = call(**LIVE)
    uid = rig.onset()
    rig.pump(2.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'где мы там остановились в прошлый раз')
    rig.pump(TICK)
    rig.job_says(0, '[продолжай]')
    rig.job_ends(0)
    rig.pump(2.0)
    assert rig.said() == [] and rig.c.question_id is None


# =====================================================================================================================================
# 4. a self-correction in a repeat (class 17) and a number split by a filler (class 18)
# =====================================================================================================================================

UNITS = '400 штук в месяц.'
BREAK_EVEN = '400 штук в месяц. Это точка безубыточности.'
SUM = 'При сложных процентах итоговая сумма составит 144 000 рублей.'
SHORT_SUM = '144 000 рублей.'


def waiting(portion, *more):
    chunks = [portion, *more]
    return {'revision': 3, 'answer': ' '.join(chunks), 'chunks': chunks, 'chunk_index': 0, 'completed': False, 'question': 'Сколько штук', 'history': []}


@pytest.mark.parametrize('said', [
    '401 штук в месяц, нет, 400 штук в месяц.',
    'Четыреста один штук в месяц? Нет, четыреста штук в месяц',
    'четыреста один штук в месяц нет четыреста штук в месяц',
    '500 штук в месяц, вернее, 400 штук в месяц',
    '500 штук в месяц, то есть 400 штук в месяц',
    'четыреста пять штук в месяц, точнее, четыреста штук в месяц',
    '401 штук, ой, 400 штук в месяц',
    '401 штук, нет, 402 штуки, нет, 400 штук в месяц',
    'пятьсот, нет, четыреста штук в месяц',
])
def test_a_repeat_is_judged_on_what_follows_the_marker(said):
    assert analyze(said, waiting(UNITS), [], CALL_SETTINGS).kind == ACK


@pytest.mark.parametrize('said', [
    '401 штук в месяц',
    '401 штук в месяц, нет',
    'четыреста один штук в месяц',
    '400 штук в месяц, нет, 401 штук в месяц',
    '401 штук в месяц, нет, 402 штуки в месяц',
    '401 штук, нет, 400 штук',
    'нет, 401 штук в месяц',
    'какая выручка, нет, 400 штук в месяц',
    '400 штук в месяц, то есть сколько это в год',
])
def test_a_wrong_number_stays_wrong(said):
    assert analyze(said, waiting(UNITS), [], CALL_SETTINGS).kind != ACK


def test_a_portion_that_holds_a_marker_is_held_to_all_of_it():
    portion = 'Нет, 400 штук в месяц.'
    assert analyze(portion, waiting(portion), [], CALL_SETTINGS).kind == ACK
    assert analyze('401 штук, нет, 400 штук в месяц', waiting('Точнее, 400 штук в месяц, то есть 4800 штук в год.'), [], CALL_SETTINGS).kind != ACK


def test_n1_04_step_4_the_number_taken_back_vetoes_nothing_and_the_repeat_is_one_ack(call):
    """43.5-48.3 «401 штук в месяц, нет, 400 штук в месяц.», 50.4 its final with a «?» in it: it was a new question, the plan retired."""
    rig = call(**LIVE)
    plan(rig, asked='Сколько штук в месяц', answer=BREAK_EVEN)
    assert rig.said() == [UNITS]
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('четыреста один штук в месяц', speech=2.9)
    rig.pump(0.2)
    rig.says('нет четыреста штук в месяц', speech=1.9)
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Четыреста один штук в месяц? Нет, четыреста штук в месяц'))
    rig.pump(TICK * 3)
    assert rig.said() == [UNITS, 'Это точка безубыточности.'], 'one next portion'
    assert len(rig.fake.runs) == 1, 'no job: no new question'
    assert rig.c.state()['question'] == 'Сколько штук в месяц'


def test_the_number_he_took_back_does_not_veto_the_clouds_confirmation(call, caplog):
    """The ear heard both numbers in one piece, the cloud only the last."""
    rig = call(**LIVE)
    plan(rig, asked='Сколько штук в месяц', answer=BREAK_EVEN)
    rig.pump(1.0)
    rig.says('четыреста один штук в месяц нет четыреста штук в месяц', speech=3.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        rig.w.feed(S.turn_done('u1', 'user', 'Четыреста штук в месяц'))
        rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 1 and not decisions(caplog, 'local_ear_number_veto')


def test_a_truly_wrong_number_is_still_vetoed(call, caplog):
    rig = call(**LIVE)
    plan(rig, asked='Сколько штук в месяц', answer=BREAK_EVEN)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('четыреста один штук в месяц', speech=2.0)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        rig.w.feed(S.turn_done('u1', 'user', 'Четыреста штук в месяц'))
        rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 0 and decisions(caplog, 'local_ear_number_veto')


def test_the_cloud_may_cut_at_the_marker(call):
    rig = call(**LIVE)
    plan(rig, asked='Сколько штук в месяц', answer=BREAK_EVEN)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Четыреста один штук в месяц'))
    rig.pump(0.3)
    assert rig.c.state()['chunk_index'] == 0, 'not for the first half'
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Нет, четыреста штук в месяц'))
    rig.pump(TICK * 3)
    assert rig.c.state()['chunk_index'] == 1 and rig.said() == [UNITS, 'Это точка безубыточности.']


@pytest.mark.parametrize('said', [
    'сто сорок четыре тысячи рублей',
    'сто сорок э-э четыре тысячи рублей',
    'сто сорок… э-э… четыре тысячи рублей',
    'сто сорок, ну, четыре тысячи рублей',
    'сто сорок эээ четыре тысячи рублей',
    'сто э-э сорок э-э четыре тысячи рублей',
    'сто сорок четыре э-э тысячи рублей',
    'сто сорок четыре ноль ноль ноль рублей',
])
def test_a_number_split_by_a_filler_is_one_number(said):
    assert match_current(said, SHORT_SUM, frozenset(resolve(CALL_SETTINGS)['fillers'])) == 'ack'


@pytest.mark.parametrize('said', [
    'сто сорок э-э пять тысяч рублей',
    'сто э-э сорок тысяч рублей',
    'сто сорок четыре э-э',
    'сто сорок четыре ноль ноль рублей',
    'сто сорок четыре ноль рублей',
    'сто сорок четыре ноль ноль ноль ноль рублей',
])
def test_a_filler_makes_no_other_number_right(said):
    assert match_current(said, SHORT_SUM, frozenset(resolve(CALL_SETTINGS)['fillers'])) != 'ack'


def test_two_numbers_are_not_summed_through_a_filler():
    assert match_current('пять э-э шесть рублей', '11 рублей.') != 'ack' and match_current('пять э-э шесть рублей', '56 рублей.') != 'ack'


def test_a_filler_after_a_number_with_no_number_behind_it_stays_out_of_the_number():
    assert [atom.atom for atom in _canonical('сто рублей э-э в месяц', (), True)][:2] == ['#100', 'рубль']
    assert match_current('двадцать мм три', '23.') != 'ack'


def test_n1_01_step_17_the_two_halves_are_one_repeat_and_one_next_portion(call):
    """220.8-228.6: «… составит сто сорок четыре» | «ноль ноль ноль рублей», 227.6 and 230.4 of the cloud: the first half is not accepted, one next portion after the second."""
    rig = call(**LIVE)
    plan(rig, asked='Сколько будет при сложных процентах', answer=SUM + ' Это на 44 000 рублей больше.')
    first = rig.said()[0]
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u1', 'user', 'При сложных процентах итоговая сумма составит сто сорок четыре'))
    rig.pump(0.2)
    assert rig.c.state()['chunk_index'] == 0, 'not for the first half'
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u2', 'user', 'Ноль ноль ноль рублей'))
    rig.pump(TICK * 3)
    assert first == SUM and rig.c.state()['chunk_index'] == 1 and len(rig.said()) == 2


def test_a_number_said_in_one_final_with_a_filler_confirms_and_the_ear_vetoes_nothing(call, caplog):
    rig = call(**LIVE)
    plan(rig, asked='Сколько будет при сложных процентах', answer=SUM + ' Это на 44 000 рублей больше.')
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('при сложных процентах итоговая сумма составит сто сорок э-э четыре тысячи рублей', speech=4.0)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        rig.w.feed(S.turn_done('u1', 'user', 'При сложных процентах итоговая сумма составит сто сорок… э-э… четыре тысячи рублей'))
        rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 1 and not decisions(caplog, 'number_veto')


# =====================================================================================================================================
# 5. the first portion carries the answer (n1_02 step 1: «Максимальный испытательный срок», then the number)
# =====================================================================================================================================

TERM_ASKED = 'Давайте сразу по делу. Эээ, испытательный срок для главного бухгалтера какой максимум'
TERM_ANSWER = 'Максимальный испытательный срок для главного бухгалтера — 6 месяцев.'


def first(answer, asked=TERM_ASKED, **how):
    return first_cue(answer, asked, CALL_SETTINGS, **{'final': True, 'last': True, **how})


def test_a_first_portion_that_only_repeats_the_question_takes_in_the_first_new_word():
    assert first(TERM_ANSWER) == TERM_ANSWER


@pytest.mark.parametrize('answer, holds', [
    ('Испытательный срок для главного бухгалтера составляет 6 месяцев.', '6'),
    ('Максимальный срок для главного бухгалтера — полгода.', 'полгода'),
    ('Испытательный срок главного бухгалтера максимум 6 месяцев, это статья 70 Трудового кодекса.', '6'),
])
def test_its_neighbours(answer, holds):
    assert holds in first(answer)


def test_a_new_word_past_the_window_of_a_first_portion_is_taken_in_all_the_same():
    asked = 'какой максимальный испытательный срок для главного бухгалтера организации и его заместителя в трудовом договоре'
    answer = 'Максимальный испытательный срок для главного бухгалтера организации и его заместителя в трудовом договоре — 6 месяцев.'
    assert '6' in first(answer, asked) and answer.startswith(first(answer, asked))


def test_a_first_portion_with_the_answer_in_it_stays_short():
    answer = 'Шесть месяцев для главного бухгалтера и его заместителя, а для остальных работников три месяца.'
    assert first(answer).startswith('Шесть месяцев') and len(first(answer)) < len(answer)


def test_the_question_read_back_is_still_no_answer():
    assert first('Испытательный срок для главного бухгалтера.', 'Какой испытательный срок для главного бухгалтера') is None


def test_a_choice_is_answered_in_the_words_of_the_question():
    assert first('Кофе.', 'Чай или кофе') == 'Кофе.'
    assert first('Кофе. Он бодрит лучше.', 'Чай или кофе') == 'Кофе.'


def test_a_stream_of_the_job_waits_for_the_new_word_a_moment_away():
    text = 'Максимальный испытательный срок для главного бухгалтера — 6'
    assert first(text + ' ', final=False, last=False, patient=True) is None
    asked = 'какой максимальный испытательный срок для главного бухгалтера организации и его заместителя в трудовом договоре'
    assert first('Максимальный испытательный срок для главного бухгалтера организации и его заместителя в трудовом договоре — ', asked, final=False, last=False, patient=True) is None, 'past the window too'
    assert first(TERM_ANSWER, final=False, last=False, patient=True) == TERM_ANSWER


def test_n1_02_step_1_the_job_in_pieces_is_cued_with_its_number(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', TERM_ASKED))
    for delta in ('Максимальный испытательный срок', ' для главного бухгалтера —', ' 6 месяцев.'):
        rig.job_says(0, delta)
    rig.job_ends(0)
    assert rig.said() == [TERM_ANSWER]


# =====================================================================================================================================
# 6. ear release (n1_01 step 15): the ear's silence and an open tail say when an utterance is over; a final that shows it went on restarts the job on the whole
# =====================================================================================================================================

HEAD_15 = ', подождите, статью потом А вот если, ну, сто тысяч на два года под двадцать'
REST_15 = 'процентов, но уже со сложными, с процентами на проценты, сколько получится'
SIMPLE = 'Проценты составят 40 000 рублей за 2 года.'
COMPOUND = 'При сложных процентах итоговая сумма составит 144 000 рублей.'
EAR_BAPTISM = 'так в каком году было крещение руси'
FINAL_BAPTISM = 'Так, в каком году было крещение Руси'


@pytest.mark.parametrize('said', [
    'это произошло потому что', 'платёж рассчитан за', 'за год или', 'я имею в виду', 'температура двадцать', 'первое второе и', 'сто тысяч на два года под двадцать', 'а вот', 'а вот если',
    'если', 'а если работник сам решит уволиться', 'хотя он сам решит', 'сто двадцать тысяч и', 'Двадцать', 'в размере сорока', 'чтобы списать недостачу', 'ну и если бы он ушёл',
])
def test_an_open_tail(said):
    assert open_tail(said)


@pytest.mark.parametrize('said', [
    'пять на пять', 'сколько будет пять на пять', 'сорок восемь умножить на десять', 'семь плюс восемь', 'статья двадцать один', 'статья 21', 'пункт 3', 'счёт 71', 'двадцать первая статья',
    'сто тысяч на два года под двадцать процентов', 'почему', 'а почему это', 'что это', 'в каком году было крещение руси', 'что было в 1945', 'двести рублей',
    'а вот если работник сам решит уволиться за сколько ему нужно предупредить работодателя', 'если работник уволится то что будет', '', 'это одно и то же',
])
def test_no_open_tail(said):
    assert not open_tail(said)


def test_n1_01_step_15_a_head_of_the_question_is_not_answered(call):
    """190.44 the cloud's final stopped at «… под двадцать», the ear was between two pieces of the same breath; 192.0 the job's answer was admitted, 194.1 cued: simple interest."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    piece(rig, 'нет нет подождите статью потом', speech=1.7)
    piece(rig, 'а вот если ну сто тысяч', speech=3.4, gap=0.1)
    uid = rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', HEAD_15))
    rig.pump(1.6)                              # H6 item 3: a final on an open tail waits 1.5 s for its rest before the job goes
    rig.job_says(1, SIMPLE)
    rig.job_ends(1)
    rig.pump(0.1)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'на два года под двадцать')
    rig.pump(TICK)
    assert rig.said() == [NOTICE] and rig.c.question_id != 'u1', 'the ear was quiet 0.1 s: no admission, the plan stands'
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.onset()
    rig.pump(3.0)
    assert rig.said() == [NOTICE] and rig.c.state()['chunks'] == [NOTICE]
    rig.offset()
    rig.pump(0.5)
    rig.w.feed(S.turn_done('u2', 'user', REST_15))
    rig.pump(TICK * 2)
    assert 'под двадцать' in rig.fake.run(2).question and 'сложными' in rig.fake.run(2).question, 'the job restarts on the whole'
    rig.job_says(2, COMPOUND)
    rig.job_ends(2)
    rig.pump(1.0)
    assert rig.c.question_id == 'u2' and 'под двадцать' in rig.c.question_text and not any('Проценты составят' in text for text in rig.said())


def test_the_answer_goes_once_the_ear_has_been_quiet_for_the_silence(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    ended = rig.says('а что такое амортизация простыми словами', speech=2.0)
    rig.w.feed(S.turn_done('u1', 'user', 'А что такое амортизация простыми словами'))
    rig.pump(TICK)
    rig.job_says(1, WRITE_OFF)
    rig.job_ends(1)
    assert rig.w.clock.t - ended < EAR_RELEASE_SILENCE_SECONDS and len(rig.said()) == 1, 'precondition: the final was fast'
    cue = rig.next_cue(1.5)
    assert cue is not None and cue.t - ended == pytest.approx(EAR_RELEASE_SILENCE_SECONDS, abs=GRID + TICK)


def test_a_question_that_stops_on_an_open_tail_waits_longer_but_not_for_ever(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    ended = rig.says('какая ставка налога на прибыль в размере двадцать', speech=2.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Какая ставка налога на прибыль, в размере двадцать'))
    rig.pump(1.6)                              # H6 item 3: 1.5 s after the final the job goes
    rig.job_says(0, 'Ставка налога на прибыль — 25 процентов.')
    rig.job_ends(0)
    assert rig.next_cue(ended + EAR_TAIL_SILENCE_SECONDS - 3 * GRID - rig.w.clock.t) is None, 'an open tail'
    cue = rig.next_cue(3.0)
    assert cue is not None and cue.t - ended == pytest.approx(EAR_TAIL_SILENCE_SECONDS, abs=GRID + TICK), 'a bounded hold, no veto'


def test_rule_two_of_h4_opens_at_the_new_silence(call):
    rig = call(**LIVE)
    uid = rig.onset()
    rig.pump(2.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    ended = rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, EAR_BAPTISM)
    rig.pump(TICK)
    rig.job_says(0, 'Крещение Руси произошло в 988 году.')
    rig.pump(0.3)
    assert rig.c.question_id is None and rig.said() == [], 'at 0.6 s: not yet'
    while rig.w.clock.t - ended < EAR_RELEASE_SILENCE_SECONDS + GRID:
        rig.pump(TICK)
    assert rig.c.question_id == 'u1' and len(rig.said()) == 1


def test_rule_two_of_h4_does_not_open_on_an_open_tail(call):
    rig = call(**LIVE)
    uid = rig.onset()
    rig.pump(2.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'сколько будет сто тысяч под двадцать')
    rig.pump(TICK)
    rig.job_says(0, '120 000 рублей.') if rig.fake.runs else None
    rig.pump(1.5)
    assert rig.c.question_id is None and rig.said() == []


def test_a_final_that_shows_the_utterance_went_on_cuts_the_cue_and_restarts_the_job_on_the_whole(call):
    """The ear opened after 0.9 s of silence, the listener went on: the final holds more than it heard."""
    rig = call(**LIVE)
    slow(rig)
    uid = rig.onset()
    rig.pump(2.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, EAR_BAPTISM)
    rig.pump(TICK)
    rig.job_says(0, 'Крещение Руси произошло в 988 году.')
    rig.pump(EAR_RELEASE_SILENCE_SECONDS)
    assert rig.c.question_id == 'u1', 'precondition: the ear opened it'
    rig.w.feed(S.turn_done('u1', 'user', FINAL_BAPTISM + ' в Киеве, и кто его провёл'))
    rig.pump(TICK * 2)
    run = rig.fake.run(1)
    assert 'кто его провёл' in run.question and 'крещение Руси' in run.question


def test_a_question_the_classifier_opened_joins_what_the_breath_went_on_with(call):
    """A final that is a question by itself, the first cue parked, the ear never quiet in between: the second final is the rest of it, however long."""
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    uid = rig.onset()
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Какой налог платит предприниматель на упрощённой системе'))
    rig.pump(TICK)
    rig.job_says(0, 'Налог на упрощённой системе — 6 процентов с доходов.')
    rig.job_ends(0)
    rig.pump(2.0)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'и ещё если у него есть наёмные работники и страховые взносы')
    rig.pump(0.3)
    assert rig.said() == []
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'И ещё если у него есть наёмные работники и страховые взносы'))
    rig.pump(1.7)                              # H6 item 3: the clause of «если» is an open tail
    question = rig.fake.run(1).question
    assert 'упрощённой' in question and 'работники' in question


def test_a_new_utterance_after_a_real_silence_is_a_final_of_its_own(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('какой налог платит предприниматель', speech=2.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Какой налог платит предприниматель'))
    rig.pump(TICK)
    rig.job_says(0, 'Предприниматель платит налог на доходы.')
    rig.job_ends(0)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS + 0.5)
    assert len(rig.said()) == 1
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.says('а какая столица австралии вообще интересно мне', speech=2.0)
    rig.w.feed(S.turn_done('u2', 'user', 'А какая столица Австралии, вообще интересно мне'))
    rig.pump(TICK * 2)
    assert 'налог' not in rig.fake.run(1).question.split('Сейчас прозвучало:')[-1]


# =====================================================================================================================================
# 8. the wait for the cloud's turn of a reference opened from the ear: on the phone it was announced 3.1-3.7 s after the onset
# =====================================================================================================================================

ASKED_17 = 'Семнадцатая статья Налогового кодекса'
EAR_17 = 'семнадцатая статья налогового кодекса'


def test_a_short_reference_waits_for_a_turn_announced_as_late_as_on_the_phone(call):
    rig = call(**LIVE)
    uid = rig.onset()
    rig.pump(1.4)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, EAR_17)
    rig.pump(2.0)
    assert rig.said() == [], 'no turn yet'
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(TICK)
    assert len(rig.said()) == 1, 'at the announcement, 3.7 s after the onset'
    rig.w.feed(S.turn_done('u1', 'user', ASKED_17))
    rig.pump(0.5)
    assert len(rig.said()) == 1


def test_the_wait_of_a_reference_has_its_own_bound(call, caplog):
    assert EAR_FIRST_BIND_SECONDS == 4.0 and EAR_BIND_SECONDS == 1.5, 'an ACK keeps its value'
    rig = call(**LIVE)
    uid = rig.onset()
    rig.pump(1.4)
    rig.offset()
    rig.pump(0.15)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        rig.worker.heard(uid, EAR_17)
        rig.pump(EAR_FIRST_BIND_SECONDS + 3 * TICK)
    assert decisions(caplog, 'ear first=dropped'), 'H6 item 6: at the same bound the ear stands in for the final'
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(TICK)
    assert rig.said(), 'H6 item 6: speech nobody judged: its text stood in, and the base answered it'


# =====================================================================================================================================
# 7. a failed job: one more job, then the cloud, whose new number is refused and the failure said
# =====================================================================================================================================

BAPTISM = 'В каком году было крещение Руси'
WRONG_YEAR = 'Тысяча девятьсот восемьдесят восьмой год.'
RIGHT = 'Крещение Руси произошло в 988 году.'
NO_NUMBER = 'Инерция — это свойство тела сохранять скорость.'


def fails(rig, n):
    rig.fake.run(n).fail()
    rig.pump(TICK * 2)


def cloud(rig, tid, text):
    rig.w.feed(S.turn_created(tid, 'assistant', text.split()[0]))
    rig.w.feed(S.turn_done(tid, 'assistant', text))
    rig.pump(TICK * 2)


def asked(rig, text=BAPTISM, uid='u1'):
    rig.w.feed(S.turn_created(uid, 'user', text.split()[0]))
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK)


def spoken_failures(rig):
    return [cue for cue in rig.w.cues if cue.diagnostic]


def test_a_failed_job_gets_one_more_before_the_cloud(call):
    rig = call(**LIVE)
    asked(rig)
    cloud(rig, 'a1', WRONG_YEAR)
    fails(rig, 0)
    assert rig.said() == [] and rig.fake.run(1).question == BAPTISM, 'one more job on the same words'
    rig.job_says(1, RIGHT)
    rig.job_ends(1)
    rig.pump(TICK * 3)
    assert any('988' in text for text in rig.said()) and not spoken_failures(rig)


def test_a_candidate_gets_one_more_too(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Ну допустим крещение Руси, а год'))
    rig.pump(TICK)
    fails(rig, 1)
    assert 'крещение' in rig.fake.run(2).question
    rig.job_says(2, RIGHT)
    rig.job_ends(2)
    rig.pump(TICK * 3)
    assert any('988' in text for text in rig.said())


def test_two_failures_and_a_cloud_with_a_new_number_say_the_failure(call):
    """The fuzz of H4: a failed job brought the cloud's wrong year back in 6 of 24 runs."""
    rig = call(**LIVE)
    asked(rig)
    cloud(rig, 'a1', WRONG_YEAR)
    fails(rig, 0)
    fails(rig, 1)
    rig.pump(TICK * 3)
    assert rig.said() == [], 'the wrong year is not cued'
    assert len(spoken_failures(rig)) == 1 and rig.c.question_id is None
    cloud(rig, 'a2', 'В девятьсот восемьдесят восьмом году.')
    assert rig.said() == [], 'and nothing of it comes later'


def test_a_cloud_that_comes_after_the_failures_is_refused_the_same(call):
    rig = call(**LIVE)
    asked(rig)
    fails(rig, 0)
    fails(rig, 1)
    assert rig.said() == [] and not spoken_failures(rig), 'nothing yet: the cloud may still say something'
    cloud(rig, 'a1', WRONG_YEAR)
    assert rig.said() == [] and len(spoken_failures(rig)) == 1


def test_a_fallback_with_no_new_number_is_the_answer(call):
    rig = call(**LIVE)
    asked(rig, 'Что такое инерция')
    cloud(rig, 'a1', NO_NUMBER)
    fails(rig, 0)
    fails(rig, 1)
    rig.pump(TICK * 3)
    assert rig.said() and not spoken_failures(rig)


def test_a_number_of_the_question_may_be_said(call):
    rig = call(**LIVE)
    asked(rig, 'Почему в сказке 3 богатыря')
    cloud(rig, 'a1', 'Потому что 3 богатыря защищают родную землю.')
    fails(rig, 0)
    fails(rig, 1)
    rig.pump(TICK * 3)
    assert rig.said() and not spoken_failures(rig)


def test_a_new_number_after_the_first_cue_ends_the_answer_there(call):
    rig = call(**LIVE)
    asked(rig, 'Что такое инерция')
    fails(rig, 0)
    fails(rig, 1)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Инерция'))
    rig.w.feed(S.turn_delta('a1', ' — это свойство тела сохранять скорость.', 1))
    rig.pump(TICK * 2)
    assert rig.said(), 'precondition: the first cue is out'
    rig.w.feed(S.turn_delta('a1', ' Закон открыт в 1687 году.', 2))
    rig.w.feed(S.turn_done('a1', 'assistant', 'Инерция — это свойство тела сохранять скорость. Закон открыт в 1687 году.'))
    rig.pump(1.0)
    assert not any('1687' in text for text in rig.c.state()['chunks'])
    assert not spoken_failures(rig) and rig.c.question_id == 'u1', 'what was said stands, the answer ends there'


def test_a_channel_that_is_gone_is_not_asked_again(call):
    rig = call(**LIVE)
    asked(rig, 'Что такое инерция')
    cloud(rig, 'a1', NO_NUMBER)
    rig.fast.shutdown()
    rig.w.run(rig.w.wire._fast_hand_back())
    rig.pump(TICK * 3)
    assert len(rig.fake.runs) == 1 and rig.said()


def test_with_the_channel_gone_the_clouds_new_number_is_refused_as_well(call):
    rig = call(**LIVE)
    rig.fast.shutdown()
    rig.w.run(rig.w.wire._fast_hand_back())
    asked(rig)
    cloud(rig, 'a1', WRONG_YEAR)
    assert rig.said() == [] and len(spoken_failures(rig)) == 1


def test_a_source_backs_its_numbers(call):
    """A question on the lookup route: its sources, its answer."""
    rig = call(**LIVE)
    rig.fast.shutdown()
    rig.w.run(rig.w.wire._fast_hand_back())
    asked(rig)
    rig.c.direct_content = True
    rig.c.sources = [{'title': 'x'}]
    assert rig.c._fallback_refused('a1', 'number', WRONG_YEAR) is None, 'a source backs what the cloud says'
    rig.c.sources = []
    assert rig.c._fallback_refused('a1', 'number', WRONG_YEAR) is not None, 'from memory a number the question does not have is refused'


# =====================================================================================================================================
# neighbours found rereading the rules
# =====================================================================================================================================

def test_a_plan_given_back_by_a_decline_is_a_replay_too(call):
    """A question in form, declined a moment after its speech ended: the plan comes back, not within 1.5 s of the ear's last offset."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    ended = rig.says('какой следующий вопрос нам задать сейчас', speech=2.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Какой следующий вопрос нам задать сейчас?'))
    rig.pump(TICK)
    assert rig.c.question_id == 'u1', 'precondition: the classifier opened it'
    rig.job_says(1, '—')
    rig.job_ends(1)
    assert len(rig.said()) == 1
    cue = rig.next_cue(2.0)
    assert cue is not None and cue.text == NOTICE and cue.t - ended == pytest.approx(TEMPO_FILLER_SECONDS, abs=GRID + TICK)


def test_a_stopped_plan_stays_stopped_through_a_question_nobody_asked(call):
    """«Стоп», then a remark in the form of a question that the job declines: the decline gives the plan back, and it comes back as it was: no replay until the listener resumes."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    said_to_the_room(rig, 'u1', STOP_HEARD)
    job_mark(rig, 1, '[стоп]')
    assert rig.c.state()['paused'] is True
    said_to_the_room(rig, 'u2', 'Какой следующий вопрос нам задать сейчас?')
    rig.job_says(2, '—')
    rig.job_ends(2)
    rig.pump(10.0)
    assert rig.said() == [NOTICE] and rig.c.state()['paused'] is True and rig.c.state()['chunks'] == [NOTICE]
    said_to_the_room(rig, 'u3', BACK_HEARD)
    job_mark(rig, 3, '[продолжай]')
    rig.pump(TICK * 2)
    assert rig.said() == [NOTICE, NOTICE]


def test_a_final_that_waited_for_the_job_of_a_command_is_asked_after_it(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Какой следующий вопрос нам задать сейчас?')
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Ну и погода сегодня за окном'))
    rig.pump(TICK * 2)
    job_mark(rig, 1, '[дальше]')
    rig.pump(TICK * 2)
    assert 'погода' in rig.fake.run(2).question


def test_three_zeros_after_digits_are_their_thousands_too():
    assert match_current('144 ноль ноль ноль рублей', SHORT_SUM, frozenset(resolve(CALL_SETTINGS)['fillers'])) == 'ack'


# =====================================================================================================================================
# H5: skeptic: the run's order of events with one thing changed, and the neighbours of each case
# =====================================================================================================================================

def results_of(rig, delegation):
    return [frame for kind, frame in rig.w.source.frames if kind == 'E' and delegation in frame.decode('utf-8', 'replace')]


def delegates(rig, uid='u1', did='d1'):
    rig.w.feed({'type': 'delegation.created', 'item': {'id': did, 'user_bidi_turn_id': uid, 'target': 'client'}})
    rig.pump(0.2)


# -- a long question with several pauses ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize('said', ['купили станок', 'купили новый станок', 'купили станок вчера'])
def test_a_first_word_of_the_portion_and_a_word_of_its_own_is_no_start(call, said):
    """Step 8 again, with a question that opens with the first word of the portion: «станок» was a hesitation to ``_start_in``, so the tail came 1.2 s after a comma."""
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says(said, speech=1.0)
    assert rig.c.tempo_hold is not None, 'it waits for what that speech was'
    assert rig.next_cue(4.0) is None


def test_a_start_of_two_words_and_a_wrong_word_is_still_a_start(call):
    """H3 rule 3 stands: that is a listener at the portion."""
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    ended = rig.says('купили материалы станок', speech=1.0)
    cue = rig.next_cue(2.0)
    assert cue is not None and cue.text.startswith('за 10 000') and cue.t - ended <= 1.2 + GRID


def two_pieces(rig, first, second):
    """Two pieces of one breath have been heard, the cloud's final of the first comes only now (3 s behind the ear on the phone)."""
    piece(rig, first, speech=1.5)
    piece(rig, second, speech=2.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', first.capitalize()))
    rig.pump(TICK * 2)


def test_a_final_of_the_first_piece_does_not_judge_the_second_for_a_first_cue(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u0', 'user', ''))
    rig.w.feed(S.turn_done('u0', 'user', QUESTION))
    uid = rig.onset()
    rig.pump(0.5)
    rig.job_says(0, INERTIA)
    rig.job_ends(0)
    rig.pump(0.7)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'ну ладно посмотрим')
    rig.pump(0.2)
    rig.says('стоимость сто двадцать тысяч рублей', speech=2.0, lag=0.1)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Ну ладно, посмотрим'))
    rig.pump(TICK * 2)
    job = len(rig.fake.runs) - 1
    rig.job_says(job, '—')
    rig.job_ends(job)
    assert rig.next_cue(1.5) is None, 'the second piece has not been judged'
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.w.feed(S.turn_done('u3', 'user', 'Стоимость сто двадцать тысяч рублей'))
    rig.pump(TICK * 2)
    job = len(rig.fake.runs) - 1
    rig.job_says(job, '—')
    rig.job_ends(job)
    assert len(rig.said()) == 1, 'now it has'


def test_the_number_of_the_first_piece_is_no_word_on_the_number_of_the_second(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u0', 'user', ''))
    rig.w.feed(S.turn_done('u0', 'user', QUESTION))
    uid = rig.onset()
    rig.pump(0.5)
    rig.job_says(0, INERTIA)
    rig.job_ends(0)
    rig.pump(0.7)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'ну допустим сто тысяч')
    rig.pump(0.2)
    rig.says('срок службы пять лет', speech=2.0, lag=0.1)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Ну, допустим, сто тысяч'))
    rig.pump(TICK * 2)
    job = len(rig.fake.runs) - 1
    rig.job_says(job, '—')
    rig.job_ends(job)
    assert rig.next_cue(1.5) is None


def test_a_final_in_digits_names_the_piece_the_ear_wrote_in_words(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u0', 'user', ''))
    rig.w.feed(S.turn_done('u0', 'user', QUESTION))
    uid = rig.onset()
    rig.pump(0.5)
    rig.job_says(0, INERTIA)
    rig.job_ends(0)
    rig.pump(0.7)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'двести пятьдесят')
    rig.pump(0.2)
    rig.says('срок службы станка', speech=2.0, lag=0.1)
    assert [text for _, text in rig.c.tempo_unjudged] == ['двести пятьдесят', 'срок службы станка'], 'precondition'
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', '250'))
    rig.pump(TICK * 2)
    assert [text for _, text in rig.c.tempo_unjudged] == ['срок службы станка']


def test_a_final_that_names_no_piece_of_the_ear_judges_them_all(call):
    """Short questions are what the ear gets wrong: one misheard word must not hold the answer for the bound of a lost final."""
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    ended = rig.says('кампания вэпэ', speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Какой ВВП у Франции'))
    rig.pump(TICK)
    rig.job_says(0, 'ВВП Франции — около 3 триллионов долларов.')
    rig.job_ends(0)
    cue = rig.next_cue(1.5)
    assert rig.said() and rig.cues()[0].t - ended <= EAR_RELEASE_SILENCE_SECONDS + GRID + TICK


def test_a_decline_leaves_the_timer_of_a_portion_the_later_speech_was_not_said_to(call):
    """Speech begun on the portion before sets no hold: the timer of the next portion runs, whatever the decline skipped."""
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    uid = rig.onset()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Купили материалы за 10 000 рублей'))
    rig.pump(0.3)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'теперь станок стоит очень дорого')
    rig.pump(TICK)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Ну и погода сегодня за окном'))
    rig.pump(TICK * 2)
    rig.job_says(1, '—')
    rig.job_ends(1)
    assert rig.next_cue(TEMPO_HOLD_SECONDS + 1.0) is not None


def test_a_decline_of_the_first_piece_leaves_the_hold_of_the_second(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    two_pieces(rig, 'ну ладно посмотрим', 'теперь станок стоит сто двадцать тысяч')
    rig.job_says(1, '—')
    rig.job_ends(1)
    assert rig.next_cue(5.5) is None, 'its final has not come'


def test_a_decline_of_the_last_piece_runs_the_timer_from_the_verdict(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    two_pieces(rig, 'ну ладно посмотрим', 'теперь станок стоит сто двадцать тысяч')
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Теперь станок стоит сто двадцать тысяч'))
    rig.pump(TICK * 2)
    verdict = rig.w.clock.t
    rig.job_says(2, '—')
    rig.job_ends(2)
    cue = rig.next_cue(5.0)
    assert cue is not None and cue.text == BOUGHT and cue.t - verdict == pytest.approx(TEMPO_REPEAT_SECONDS, abs=3 * GRID)


def test_a_hold_with_no_final_for_the_second_piece_still_ends(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    two_pieces(rig, 'ну ладно посмотрим', 'теперь станок стоит сто двадцать тысяч')
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(TEMPO_HOLD_SECONDS - 0.5)      # the second piece ended 0.8 s before this
    assert rig.c.candidate is None and not rig.c.tempo_unjudged, 'the job on the ear text is over within the 8 s of the speech: nothing of it is left to wait for'
    assert rig.next_cue(MONOLOGUE_QUIET_SECONDS + 1.0) is not None, 'R2.5: no hold without a bound: two pieces of other speech are a monologue (u18), whose quiet is its own row (MONOLOGUE_QUIET_SECONDS counted from the end of the speech); the hung job on the ear text ends inside the 8 s (TEMPO_HOLD_SECONDS) and holds nothing longer'


@pytest.mark.parametrize('job', ['hangs', 'declines', 'answers'])
def test_a_question_as_the_second_piece_with_no_final_is_decided_within_8_s_of_its_end(call, caplog, job):
    """Round 3, the owner's rule: the listener gets a decision (the cue, or the failure phrase) within ANSWER_WAIT_SECONDS of the END of a question, every time. The same two pieces as the monologue test above, but the
    second one asks and the cloud never writes it down: its job hangs (the phrase of the roads), declines (a question nobody answers is given up aloud), or answers (the cue goes when the hold of speech nobody judged is over).
    Counted from the end of the second piece's speech, not from the cloud's final of the first that came seconds after it. Plain talk keeps its own, longer, quiet (the test above)."""
    caplog.set_level(logging.INFO)
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    first, second = 'ну ладно посмотрим', 'а сколько стоит этот станок в год'
    piece(rig, first, speech=1.5)
    ended = piece(rig, second, speech=2.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', first.capitalize()))
    rig.pump(TICK * 2)
    last = len(rig.fake.runs) - 1
    if job == 'declines':
        rig.job_says(last, '—')
        rig.job_ends(last)
    elif job == 'answers':
        rig.job_says(last, 'Станок стоит сто двадцать тысяч рублей в год.')
        rig.job_ends(last)
    mark = len(rig.cues())
    rig.pump(ended + ANSWER_WAIT_SECONDS + 1e-6 - rig.w.clock.t)
    if job == 'answers':
        assert [c.text for c in rig.cues()[mark:]] and rig.cues()[mark].t - ended <= ANSWER_WAIT_SECONDS + 1e-6, 'the answer is a decision of the 8 s'
    else:
        assert decisions(caplog, 'ear_question_unanswered'), 'a question nobody answered is given up aloud (the failure phrase) inside the 8 s of its end, not at 8.3 or 8.4'


def test_a_plan_given_back_waits_for_speech_nobody_has_judged(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    two_pieces(rig, 'какой следующий вопрос нам задать сейчас', 'станок стоит сто двадцать тысяч рублей')
    assert rig.c.question_id == 'u1', 'precondition: the classifier opened it'
    rig.job_says(1, '—')
    rig.job_ends(1)
    assert rig.next_cue(4.0) is None, 'the second piece has not been judged'


def test_a_plan_given_back_waits_for_the_job_on_that_speech(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    two_pieces(rig, 'какой следующий вопрос нам задать сейчас', 'станок стоит сто двадцать тысяч рублей')
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Станок стоит сто двадцать тысяч рублей'))
    rig.pump(TICK * 2)
    rig.job_says(1, '—')
    rig.job_ends(1)
    assert rig.next_cue(3.0) is None, 'the job of the final that waited judges it'
    rig.job_says(2, 'Амортизация составит 24 000 рублей в год.')
    rig.job_ends(2)
    rig.pump(1.0)
    assert not any(text == NOTICE for text in rig.said()[1:]) and any('24 000' in text for text in rig.said())


HEAD_16 = 'Теперь станок'
MIDDLE_16 = 'Стоимость сто двадцать тысяч рублей, срок службы пять лет'
REST_16 = 'Амортизация линейным способом за год, только цифру'
DEPRECIATION = 'Амортизация составит 24 000 рублей в год.'


def one_breath(rig, *finals, ruled='—', pause=2.0):
    """One breath of the ear, the cloud cut it into ``finals``, the job rules on each before the next (n1_01 step 16: 203.7 | 206.5 | 210.1 | 214.2). Returns the question of the last job."""
    uid = rig.onset()
    jobs = len(rig.fake.runs)
    for at, text in enumerate(finals):
        rig.w.feed(S.turn_created(f'p{at}', 'user', ''))
        rig.pump(pause)
        rig.w.feed(S.turn_done(f'p{at}', 'user', text))
        rig.pump(TICK * 2)
        if at < len(finals) - 1:
            rig.job_says(jobs + at, ruled)
            rig.job_ends(jobs + at)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, ' '.join(finals).lower())
    return rig.fake.run(jobs + len(finals) - 1).question


def test_n1_01_step_16_a_breath_cut_into_finals_reaches_the_job_whole_with_no_plan(call):
    rig = call(**LIVE)
    asked = one_breath(rig, HEAD_16, MIDDLE_16, REST_16)
    assert 'станок' in asked and 'сто двадцать' in asked and 'линейным' in asked


def test_n1_01_step_16_a_breath_cut_into_finals_reaches_the_job_whole_with_a_plan(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    asked = one_breath(rig, HEAD_16, MIDDLE_16, REST_16).split('Сейчас прозвучало:')[-1]
    assert 'станок' in asked and 'сто двадцать' in asked and 'линейным' in asked
    assert rig.said() == [BOUGHT]
    rig.job_says(3, DEPRECIATION)
    rig.job_ends(3)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS + 0.2)
    assert rig.said()[-1] == DEPRECIATION


def test_a_question_in_form_after_a_head_the_job_declined_keeps_the_head(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    asked = one_breath(rig, HEAD_16, 'Какая амортизация линейным способом за год').split('Сейчас прозвучало:')[-1]
    assert 'станок' in asked and 'линейным' in asked


def test_a_question_the_ear_opens_in_that_breath_keeps_its_prepared_job(call):
    """The ear's words are what its job was prepared on, and what the cloud is compared with: no head goes in front of them."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    uid = rig.onset()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Ну ладно, допустим, сегодня посмотрим'))
    rig.pump(TICK * 2)
    assert rig.c.question_id != 'u1', 'precondition: a final with no form'
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(2.0)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, EAR_BAPTISM)
    rig.pump(TICK)
    jobs = len(rig.fake.runs)
    rig.job_says(jobs - 1, RIGHT)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS)
    assert rig.c.question_id == 'u2' and 'посмотрим' not in rig.c.question_text and len(rig.fake.runs) == jobs


def test_a_long_remark_the_job_declined_is_no_head(call):
    """129.6-136.4 of the call: 60 words about the prompter, «Пять умножить на пять» in the same breath: with the remark in front the question took the route of a lookup, 1.4 s more."""
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    remark = ' '.join(['ну вот очень долго ты мне подсказываешь и это плохо'] * 3)
    asked = one_breath(rig, remark, 'Пять умножить на пять').split('Сейчас прозвучало:')[-1]
    assert 'долго' not in asked


def test_a_breath_goes_on_through_a_pause_shorter_than_the_silence(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says(HEAD_16.lower(), speech=1.0, lag=0.05)
    rig.w.feed(S.turn_done('u1', 'user', HEAD_16))             # in the pause
    uid = rig.onset()
    rig.pump(TICK)
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(1.5)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'амортизация за год только цифру')
    rig.w.feed(S.turn_done('u2', 'user', 'Амортизация за год, только цифру'))
    rig.pump(TICK * 2)
    assert 'станок' in rig.fake.runs[-1].question.split('Сейчас прозвучало:')[-1]


def test_a_final_the_ear_heard_nothing_of_is_no_rest_of_a_breath_that_ended(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('что такое инерция простыми словами', speech=2.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Что такое инерция простыми словами'))
    rig.pump(TICK)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(TICK)
    rig.w.feed(S.turn_done('u2', 'user', 'И ещё наёмные работники, страховые взносы, налог на имущество, земельный налог и всякое такое прочее'))
    rig.pump(TICK * 2)
    assert 'работники' not in rig.c.question_text


def test_a_question_in_a_new_breath_takes_no_candidate_with_it(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    rig.says('ну допустим сегодня посмотрим', speech=1.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Ну, допустим, сегодня посмотрим'))
    rig.pump(EAR_RELEASE_SILENCE_SECONDS + TICK)
    rig.says('какая столица австралии вообще', speech=1.5)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Какая столица Австралии вообще'))
    rig.pump(TICK * 2)
    assert 'посмотрим' not in rig.fake.runs[-1].question.split('Сейчас прозвучало:')[-1]


def test_a_real_silence_ends_the_breath(call):
    rig = call(**LIVE)
    plan(rig)
    rig.pump(1.0)
    rig.says('ну ладно посмотрим что там', speech=1.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Ну ладно, посмотрим, что там'))
    rig.pump(TICK * 2)
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS + 0.3)
    rig.says('поставьте новый станок завтра утром', speech=1.5)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Поставьте новый станок завтра утром'))
    rig.pump(TICK * 2)
    assert 'посмотрим' not in rig.fake.run(2).question.split('Сейчас прозвучало:')[-1]


FORTY = 'Нет, 40 000 рублей: 20 процентов от 100 000.'
BANK = 'Допустим, с начислением на вкладе в банке'
RULED = 'При сложных начислениях сумма составит 144 000 рублей.'


def ruled_while_the_ear_hears(rig, *, breath):
    """The job has ruled on a final with no form, its answer waits for the silence: ``breath``: the same speech goes on past that final, else it began after it."""
    plan(rig, asked=QUESTION, answer=FORTY)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    if breath:
        uid = rig.onset()
        rig.pump(1.0)
    rig.w.feed(S.turn_done('u1', 'user', BANK))
    rig.pump(TICK * 2)
    if not breath:
        uid = rig.onset()
        rig.pump(0.3)
    rig.job_says(1, RULED)
    rig.job_ends(1)
    assert (rig.c.candidate or {}).get('verdict'), 'precondition: the job has ruled, the ear hears speech'
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'рублей, ну'))
    rig.pump(TICK * 2)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'рублей ну')


def test_a_try_in_a_new_breath_does_not_lose_the_candidate_the_job_ruled_on(call):
    """n1_01 203.7-210.1: «рублей, ну» shares a word with the portion, a try; the answer that waited for silence went with it, and the question of step 15 was never answered."""
    rig = call(**LIVE)
    ruled_while_the_ear_hears(rig, breath=False)
    rig.pump(EAR_RELEASE_SILENCE_SECONDS + 0.5)
    assert rig.c.question_id == 'u1' and any('начислениях' in text for text in rig.said())


def test_a_word_of_the_portion_in_the_same_breath_is_no_try(call):
    rig = call(**LIVE)
    ruled_while_the_ear_hears(rig, breath=True)
    asked = rig.fake.runs[-1].question.split('Сейчас прозвучало:')[-1]
    assert 'вкладе' in asked and 'рублей' in asked, 'the job has the whole'


# -- ear release: a final that shows the utterance went on ------------------------------------------------------------------------------

def head_cued(rig, final, answer):
    """A question stopped on an open tail, its answer has gone out after the bound of the tail."""
    rig.w.feed(S.turn_created('u1', 'user', ''))
    ended = rig.says(final.lower().replace(',', ''), speech=2.5)
    rig.pump(0.2)
    rig.w.feed(S.turn_done('u1', 'user', final))
    rig.pump(TICK)
    rig.job_says(0, answer)
    rig.job_ends(0)
    while rig.w.clock.t - ended < EAR_TAIL_SILENCE_SECONDS + 2 * TICK:
        rig.pump(TICK)
    assert rig.c.question_id == 'u1' and len(rig.said()) == 1, 'precondition'


def test_the_rest_of_a_head_with_no_form_restarts_the_job_on_the_whole(call):
    """Item 6 in its other shape: what the job admitted has no form of a question, and neither has it joined: nothing opened, the answer to the head stood."""
    rig = call(**LIVE)
    head_cued(rig, 'Ну, сто тысяч на два года под двадцать', SIMPLE)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.says('процентов но уже со сложными сколько получится', speech=2.5)
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u2', 'user', 'процентов, но уже со сложными, сколько получится'))
    rig.pump(TICK * 3)
    question = rig.fake.run(1).question
    assert 'под двадцать' in question and 'сложными' in question and rig.c.question_id == 'u2'
    rig.job_says(1, COMPOUND)
    rig.job_ends(1)
    rig.pump(1.0)
    assert any('144' in text for text in rig.said())


def test_a_head_the_classifier_opened_and_the_job_declined_joins_its_rest(call):
    rig = call(**LIVE)
    uid = rig.onset()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(2.0)
    rig.w.feed(S.turn_done('u1', 'user', HEAD_16))
    rig.pump(TICK)
    assert rig.c.question_id == 'u1', 'precondition: a topic phrase'
    rig.job_says(0, '—')
    rig.job_ends(0)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u2', 'user', MIDDLE_16))
    rig.pump(TICK * 2)
    assert 'станок' in rig.fake.run(1).question and 'сто двадцать' in rig.fake.run(1).question
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'теперь станок')


def test_a_wrong_repeat_of_the_cue_of_an_open_tail_is_no_rest_of_the_question(call):
    rig = call(**LIVE)
    head_cued(rig, 'Сколько будет сто тысяч на два года под двадцать', SIMPLE)
    portion = rig.said()[0]
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.says('проценты составят сорок одну тысячу рублей', speech=2.0)
    rig.w.feed(S.turn_done('u2', 'user', 'Проценты составят сорок одну тысячу рублей'))
    rig.pump(TICK * 3)
    assert rig.c.question_id == 'u1' and len(rig.fake.runs) == 1 and rig.c.state()['chunks'][0] == portion


# -- a stop in the middle of a cue, a resume after a long silence, a command the model marks on a question ----------------------------------

async def long_voice(text, end=None):
    return b'\x00\x40' * 96000


def test_a_stop_over_a_cue_in_flight_stays_a_stop(call):
    """The replay is playing, the listener cuts it with a stop in words the grammars do not know; the job says so a second later."""
    rig = call(**LIVE)
    rig.w.wire.synthesize = long_voice
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(3.0)
    cue = in_flight(rig)
    assert cue.text == NOTICE
    rig.w.feed(S.turn_created('u1', 'user', ''))       # the cloud's start of speech cuts it
    rig.w.feed(S.turn_done('u1', 'user', STOP_HEARD))
    rig.pump(TICK * 2)
    job_mark(rig, 1, '[стоп]')
    count = len(rig.said())
    rig.pump(25.0)
    assert len(rig.said()) == count and rig.c.state()['paused'] is True
    said_to_the_room(rig, 'u2', BACK_HEARD)
    job_mark(rig, 2, '[продолжай]')
    rig.pump(TICK * 2)
    assert rig.said() == [NOTICE] * (count + 1)


def test_next_on_a_stopped_plan_a_question_took_over_says_that_portion_again(call):
    """Ruling 4b of CL2: a paused portion was cut, so even «дальше» says it again. A question in form took the plan over, the mark gave it back unpaused and one portion was skipped."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=MATERIALS)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', STOP_HEARD)
    job_mark(rig, 1, '[стоп]')
    said_to_the_room(rig, 'u2', 'Какой следующий вопрос нам задать сейчас?')
    assert rig.c.question_id == 'u2', 'precondition'
    job_mark(rig, 2, '[дальше]')
    rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 0 and rig.said() == [BOUGHT, BOUGHT]


@pytest.mark.parametrize('mark, answer', [('[дальше]', 'Дальше идёт налог на прибыль. Его платят организации.'), ('[продолжай]', 'Продолжайте платить взносы. Это важно.')], ids=['next', 'resume'])
def test_a_mark_on_a_portion_that_opens_with_its_word(call, mark, answer):
    """«дальше» said to «Дальше идёт налог…» is a try at that portion: the command went nowhere and nothing was said. A mark is no try."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=answer)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Ладно, с этим ясно, поехали')
    job_mark(rig, 1, mark)
    rig.pump(TICK * 2)
    assert len(rig.said()) == 2


@pytest.mark.parametrize('after', [False, True], ids=['before', 'after'])
@pytest.mark.parametrize('mark', ['[стоп]', '—'], ids=['mark', 'decline'])
def test_the_model_that_asked_for_a_search_on_a_question_nobody_asked_is_told(call, mark, after):
    """A question in form, the model's delegation, and the job says it is no question: DEF-T-B15, the model waits for a result that never comes."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Какой следующий вопрос нам задать сейчас?')
    if not after:
        delegates(rig)
    job_mark(rig, 1, mark)
    rig.pump(TEMPO_FILLER_SECONDS + 0.5)
    if after:
        delegates(rig)
    assert results_of(rig, 'd1')


# -- a bracket token inside an answer --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('said', ['— [стоп]', '—[стоп]', '- [стоп]', '—\n[продолжай]', '— [ст'])
def test_a_dash_in_front_of_a_mark_makes_no_answer_of_it(said):
    assert FT.brain_answer(said) == ''


@pytest.mark.parametrize('said, word', [('— [стоп]', 'стоп'), ('[Стоп]', 'стоп'), ('[ПРОДОЛЖАЙ]', 'продолжай'), ('[Повтори]\n', 'повтори')])
def test_a_mark_with_a_dash_or_a_capital_is_the_command(said, word):
    """No answer can be made of it, and as a decline it replays the plan through the stop."""
    assert FT.brain_command(said) == word


@pytest.mark.parametrize('text', ['Двадцать пять. [стоп]', 'Двадцать пять. [стоп] Хорошо.', 'Двадцать пять [дальше].', 'Двадцать пять.\n[продолжай]', 'Двадцать пять. [Стоп]'])
def test_a_mark_inside_an_answer_never_reaches_the_earpiece(call, text):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Пять умножить на пять'))
    rig.job_says(0, text)
    rig.job_ends(0)
    rig.pump(1.0)
    assert rig.said()[0].startswith('Двадцать пять') and not any('[' in chunk or ']' in chunk for chunk in rig.c.state()['chunks'])
    assert '[' not in rig.c.state()['answer']


def test_the_start_of_a_mark_at_the_frontier_is_not_said(call):
    """The listener has repeated all there is, a piece of the job ends on the start of a mark."""
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Пять умножить на пять'))
    rig.job_says(0, 'Двадцать пять, это произведение чисел.')
    first = list(rig.said())
    rig.w.feed(S.turn_done('u2', 'user', first[0]))
    rig.pump(TICK * 2)
    rig.job_says(0, ' Запомните это [сто')
    rig.job_ends(0)
    rig.pump(1.0)
    assert not any('[' in text or 'сто' in text.split() for text in rig.said())


def test_a_mark_that_comes_in_pieces_after_the_first_cue_never_reaches_the_earpiece(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Пять умножить на пять'))
    for delta in ('Двадцать пять.', ' [', 'сто', 'п]'):
        rig.job_says(0, delta)
    rig.job_ends(0)
    rig.pump(1.0)
    rig.w.feed(S.turn_done('u2', 'user', 'Двадцать пять'))
    rig.pump(1.0)
    assert not any('[' in text or 'стоп' in text for text in rig.said())


def test_brackets_that_are_no_mark_stay_the_models(call):
    rig = call(**LIVE)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Что такое инерция'))
    rig.job_says(0, 'Инерция [по Ньютону] — свойство тела.')
    rig.job_ends(0)
    assert 'Ньютону' in rig.c.state()['answer']


# -- a self-correction, a real wrong number ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize('said', ['401 штук то есть в месяц', '401 штук в месяц нет в месяц', 'четыреста один штук в месяц ой в месяц'])
def test_a_marker_with_no_number_after_it_washes_no_number(call, caplog, said):
    """What stands holds no number, so the number he said stands: the veto of a truly wrong number is not weakened by a word in the sentence."""
    rig = call(**LIVE)
    plan(rig, asked='Сколько штук в месяц', answer=BREAK_EVEN)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says(said, speech=2.0)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        rig.w.feed(S.turn_done('u1', 'user', 'Четыреста штук в месяц'))
        rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 0 and decisions(caplog, 'local_ear_number_veto')


def test_the_ear_took_the_correction_and_the_clouds_first_half_overrules_nothing(call):
    """The ear heard both halves and confirmed; the cloud cut at the marker and its first final says the number he took back: the next portion was cut and said twice."""
    rig = call(**LIVE)
    plan(rig, asked='Сколько штук в месяц', answer=BREAK_EVEN)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('четыреста один штук в месяц', speech=2.0)
    rig.pump(0.2)
    rig.says('нет четыреста штук в месяц', speech=2.0)
    assert rig.said() == [UNITS, 'Это точка безубыточности.'], 'precondition: the ear took it'
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u1', 'user', 'Четыреста один штук в месяц'))
    rig.pump(0.5)
    assert rig.c.state()['chunk_index'] == 1
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Нет, четыреста штук в месяц'))
    rig.pump(TICK * 3)
    assert rig.said() == [UNITS, 'Это точка безубыточности.'] and rig.c.state()['chunk_index'] == 1


def test_the_ear_took_the_correction_and_a_third_number_still_overrules(call, caplog):
    rig = call(**LIVE)
    plan(rig, asked='Сколько штук в месяц', answer=BREAK_EVEN)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('четыреста один штук в месяц', speech=2.0)
    rig.pump(0.2)
    rig.says('нет четыреста штук в месяц', speech=2.0)
    assert rig.c.state()['chunk_index'] == 1, 'precondition'
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        rig.w.feed(S.turn_done('u1', 'user', 'Четыреста два штук в месяц'))
        rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 0 and decisions(caplog, 'local_ear_overruled')


def test_the_ear_took_a_confirmation_and_a_truly_other_number_still_overrules(call, caplog):
    rig = call(**LIVE)
    plan(rig, asked='Сколько штук в месяц', answer=BREAK_EVEN)
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('четыреста штук в месяц', speech=2.0)
    assert rig.c.state()['chunk_index'] == 1, 'precondition'
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        rig.w.feed(S.turn_done('u1', 'user', 'Четыреста один штук в месяц'))
        rig.pump(TICK * 2)
    assert rig.c.state()['chunk_index'] == 0 and decisions(caplog, 'local_ear_overruled')


def test_n1_01_step_17_with_the_ear_in_the_order_of_the_run(call):
    """221.0-226.3 and 227.0-228.6 the ear, 227.6 the cloud's first half in the middle of the second piece (it was read as a wrong repeat, 232.5 the timer said the end again), 230.4 its second half."""
    rig = call(**LIVE)
    plan(rig, asked='Сколько будет при сложных процентах', answer=SUM + ' Это на 44 000 рублей больше.')
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.says('при сложных процентах итоговая сумма составит сто сорок четыре', speech=5.0, lag=0.1)
    rig.pump(0.4)
    uid = rig.onset()
    rig.pump(0.6)
    rig.w.feed(S.turn_done('u1', 'user', 'При сложных процентах итоговая сумма составит сто сорок четыре'))
    rig.pump(0.95)
    rig.offset()
    rig.pump(0.5)
    rig.worker.heard(uid, 'ноль ноль ноль рублей')
    rig.pump(1.2)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Ноль ноль ноль рублей'))
    rig.pump(TICK * 3)
    assert rig.c.state()['chunk_index'] == 1 and len(rig.said()) == 2, 'one next portion, no replay of the end'


# -- the run's own order: steps 15-16 of n1_01 ----------------------------------------------------------------------------------------------

STEP_15 = (('нет нет', 1.0), ('подождите', 0.9), ('статью потом', 1.0), ('а вот если', 0.9), ('ну', 0.3), ('сто тысяч на два года под двадцать процентов', 3.8), ('но уже со сложными', 1.6),
           ('с процентами на проценты', 2.0), ('тогда сколько выйдет', 1.7))
FINALS_15 = ((3.0, 'Нет, нет'), (10.3, ', подождите, статью потом А вот если, ну, сто тысяч на два года под двадцать'), (17.5, ' процентов, но уже со сложными, с процентами на проценты, тогда сколько выйдет'))


def test_n1_01_step_15_in_the_order_of_the_run(call):
    """180.4-195.2 a question, 183.2 | 190.5 | 197.6 its finals, the job's answer to the head 192.0: nothing over the speech (194.1 of the run), and the job has the whole at the end."""
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer='Купили станок за 40 000 рублей. Это основное средство.')
    first = rig.said()[0]
    rig.pump(1.0)
    zero, at = rig.w.clock.t, 0

    def finals():
        nonlocal at
        while at < len(FINALS_15) and rig.w.clock.t - zero >= FINALS_15[at][0]:
            rig.w.feed(S.turn_created(f'f{at}', 'user', ''))
            rig.w.feed(S.turn_done(f'f{at}', 'user', FINALS_15[at][1]))
            rig.pump(TICK)
            if at == 1:
                rig.job_says(len(rig.fake.runs) - 1, SIMPLE)
                rig.job_ends(len(rig.fake.runs) - 1)
            at += 1
    for said, speech in STEP_15:
        uid = rig.onset()
        rig.pump(speech)
        finals()
        rig.offset()
        rig.pump(0.1)
        rig.worker.heard(uid, said)
        rig.pump(0.25)
        finals()
    assert rig.said() == [first], 'nothing over the speech'
    rig.pump(max(0.0, FINALS_15[-1][0] - (rig.w.clock.t - zero)) + TICK)
    finals()
    last = rig.fake.runs[-1]
    assert 'под двадцать' in last.question and 'сложными' in last.question, 'the job on the whole'
    last.say(COMPOUND)
    last.finish()
    settled(rig.fast)
    jobs = len(rig.fake.runs)
    rig.pump(1.2)
    if len(rig.fake.runs) > jobs:            # rule 6 of H2: a sum goes the way of the lookup, one more job
        rig.job_says(jobs, COMPOUND)
        rig.job_ends(jobs)
        rig.pump(1.2)
    assert rig.said()[-1] == COMPOUND
