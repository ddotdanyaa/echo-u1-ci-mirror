"""c8b: the owner's real call of 3 Nov 2026, 20:10 (trace echo_calls/20261103-201019-72c65a267b59.jsonl), in a car, talking with a friend.

1. A portion nobody repeats blocked the whole call. The greeting «Да, привет, привет. Ну что, как дела? Что-то слышишь меня» was taken for a
   question and the cloud's chit-chat «Да, слышу хорошо.» was cued; the owner never repeated it, so for two minutes the state stayed «portion
   waiting» (rev 30 idx 0) and every real question was judged against it and dropped as unrelated_speech. The class: a waiting portion is
   ABANDONED when the listener has clearly moved on - ABANDON_SECONDS of speaking other things since it was cued (or since the listener last
   tried it), or the auto-repeat cap spent and other speech begun after that last auto-repeat while the listener never tried it - and the
   utterance that shows it is judged as when nothing waits. Never on a try, a command, a pause with no speech, or a bystander while the
   listener keeps trying. «повтори» / «продолжай» bring the abandoned answer back inside the resume window.
2. A greeting followed by small talk questions («как дела?», «как ты?», «слышишь меня?», «ты тут?», «что нового?») cues nothing; a real
   question after the small talk in the same utterance still wins.
3. «Сверяю формулировку пятнадцатой статьи НК РФ.» was cued twice (first cue + auto-repeat): an announcement whose objects are only meta
   nouns, the question's own words and a reference to its document (an abbreviation of the question's words, its jurisdiction).

REAL: ControlledMedia, EchoEngine + SQLite, the ledger, the classifier (the Wire harness of the W1F tests: the cloud is the scripted turns).
"""
import logging

import pytest

from echo_sync.classifier import GREETING, QUESTION, QUIET, REPLAY, analyze
from echo_sync.settings import CALL_SETTINGS
from echo_sync.textutil import drop_process_sentences, strip_process_prefix
from helpers_w1f import Wire

WAITING = {'revision': 30, 'chunks': ['Да, слышу хорошо.'], 'chunk_index': 0, 'completed': False, 'question': 'x', 'history': []}

# -- 2. small talk ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize('said', [
    'Да, привет, привет. Ну что, как дела? Что-то слышишь меня',          # the cloud's final of the 20:10 call
    'да привет привет ну что как дела что ты слышишь меня',               # the ear's text of the same utterance
    'Привет, как ты?', 'Привет! Слышишь меня?', 'Привет, ты тут?', 'Привет, что нового?', 'Здравствуйте, как у вас дела?',
    'Привет, ну что, как дела?', 'Алло, привет, как у тебя дела? Ты меня слышишь?'])
@pytest.mark.parametrize('state', [None, WAITING], ids=['nothing_waits', 'portion_waits'])
def test_a_greeting_followed_by_small_talk_cues_nothing(said, state):
    assert analyze(said, state, [], CALL_SETTINGS).kind == GREETING


def test_a_real_question_after_the_small_talk_still_wins():
    decision = analyze('Привет, как дела? Сколько будет пятью пять?', None, [], CALL_SETTINGS)
    assert decision.kind == QUESTION and 'пятью пять' in decision.question


@pytest.mark.parametrize('said', ['Что нового в налоговом кодексе?', 'Что такое инерция?', 'Как дела у компании Газпром?'])
def test_a_question_about_something_is_no_small_talk(said):
    assert analyze(said, None, [], CALL_SETTINGS).kind == QUESTION


@pytest.mark.parametrize('said', ['Что?', 'Что-что?'])
def test_a_bare_what_while_a_portion_waits_is_still_no_greeting(said):
    assert analyze(said, WAITING, [], CALL_SETTINGS).kind != GREETING


# -- 3. announcements ------------------------------------------------------------------------------------------------------------------
ARTICLE_Q = 'Так, что такое пятнадцатая статья Налогового кодекса'
ARTICLE_A = 'Пятнадцатая статья Налогового кодекса — это «Местные налоги» в части первой.'


@pytest.mark.parametrize('lead', ['Сверяю формулировку пятнадцатой статьи НК РФ.',             # the 20:10 call, cued twice
                                  'Уточняю формулировку статьи НК.',
                                  'Изучаю формулировку статьи.',                              # a present verb no lemma list has
                                  'Изучаю формулировку статьи НК РФ.'])
def test_an_announcement_with_the_questions_own_words_is_stripped_at_the_start(lead):
    assert strip_process_prefix(lead + ' ' + ARTICLE_A, ARTICLE_Q) == ARTICLE_A


def test_an_announcement_is_dropped_mid_answer():
    text = ARTICLE_A + ' Сверяю формулировку пятнадцатой статьи НК РФ. Она определяет местные налоги.'
    assert drop_process_sentences(text, ARTICLE_Q, final=True) == ARTICLE_A + ' Она определяет местные налоги.'


def test_the_announcement_alone_is_no_answer():
    assert strip_process_prefix('Сверяю формулировку пятнадцатой статьи НК РФ.', ARTICLE_Q) == ''
    assert strip_process_prefix('Понял, смотрю про семьдесят первый счёт.',
                                'Так, план счетов, семьдесят первый счет, это что? Про что счет?') == ''


@pytest.mark.parametrize('question,answer', [
    ('Вы сверите отчёт?', 'Сверю отчёт до пятницы.'),                                          # the question's verb: an answer
    ('Вы подготовите отчёт к понедельнику?', 'Да, подготовлю отчёт к понедельнику.'),
    ('Кем вы работаете?', 'Работаю бухгалтером.'),
    ('Где вы живёте?', 'Живу в Москве.'),
    ('Что вы сделаете первым делом?', 'Посмотрю документы.'),                                  # F3 pin
    ('Что выбрать: ИП или ООО?', 'Выберу ООО.'),
    ('Какой вариант лучше, первый или второй?', 'Рекомендую второй вариант.'),
    ('Расскажите о себе.', 'Люблю кошек.'),
    ('Вы за это решение?', 'Поддерживаю это.'),
    ('Это правда?', 'Сомневаюсь.'),
])
def test_an_answer_in_the_first_person_stays(question, answer):
    assert strip_process_prefix(answer, question) == answer


# -- 1. the waiting portion nobody repeats -----------------------------------------------------------------------------------------------
INERTIA_Q = 'Что такое инерция?'
INERTIA_A = ' Инерция — это свойство тела сохранять скорость.'
ACCOUNT_Q = (' А я сейчас всем говорю. Я не уверен, что сейчас вечером станет шесть. Так, план счетов , семьдесят первый счет, это что? '
             'Про что счет? Сейчас скажу')
ACCOUNT_A = ' Семьдесят первый счёт — это расчёты с подотчётными лицами.'


# The car talk of the same call that asks nothing (finals at 155.0 and 161.5 of the trace), said where the arithmetic questions were.
CHATTER = (' Там он чуть-чуть десять минут проехать, и мы приедем там, где мы забирали',
           ' Так они сыпут после всех отзывов истории про пистол еты, сигнализации')


def call_2010(tmp_path, first=(INERTIA_Q, INERTIA_A), account_answer=ACCOUNT_A, chatter=False, **overrides):
    """The user finals of the 20:10 call with their timing (seconds of the trace); the cloud's replies as it said them, except the first
    exchange (``first``) and the answer to the account question (the real cloud only announced it). ``chatter``: the two arithmetic
    questions are replaced by the call's own car talk (other speech that asks nothing), at the same instants."""
    w = Wire(tmp_path, **overrides)
    w.user('u1', first[0], 7.5, 11.1)
    w.assistant('a1', first[1], 11.12, 12.0)
    w.user('u2', CHATTER[0] if chatter else ' Все, славно, отлично. Че там, дважды два сколько будет', 17.1, 22.9)
    w.assistant('a2', ' Понял.' if chatter else ' Четыре.', 23.0, 24.9)
    w.user('u3', CHATTER[1] if chatter else ' 5 и 5 сколько будет', 35.8, 37.9)
    w.assistant('a3', ' Ясно.' if chatter else ' Десять — пять плюс пять.', 37.95, 40.8)
    w.user('u4', ' Прямо, прямо, прямо. Окей, на право, да? Классные водители. И женщину будут... А сейчас налево или на право',
           48.0, 54.9)
    w.assistant('a4', ' Секунду, посмотрю точно, что имеется в виду.', 55.0, 57.7)
    w.user('u5', ACCOUNT_Q, 57.8, 72.8)
    w.assistant('a5', ' Понял, смотрю про семьдесят первый счёт.' + (account_answer or ''), 72.85, 77.1)
    return w


def test_the_calls_questions_are_answered_and_the_stale_portion_never_comes_back(tmp_path):
    """The real finals (c8: «дважды два сколько будет», «5 и 5 сколько будет» are questions while a portion waits): each one retires the
    waiting portion and is answered; the portion nobody repeated is never spoken again, and its answer is kept, unsaid, in the history."""
    w = call_2010(tmp_path).until(76.0)          # the harness serves no lookup: the watchdog gives the account question up at 80.8 s
    assert w.played[0][1].startswith('свойство тела'), w.played
    assert any(text.startswith('Четыре') for at, text in w.played if 22.9 <= at < 35.8), w.played
    assert any(text.startswith('Десять') for at, text in w.played if 37.9 <= at < 48.0), w.played
    assert not any(text.startswith('свойство тела') for at, text in w.played if at >= 22.9), w.played
    first = next(e for e in w.state()['history'] if e.get('question') == INERTIA_Q)
    assert first['status'] == 'interrupted' and first['spoken'] == 0, first
    # the account question is a question (deployed: dropped as unrelated_speech against «Да, слышу хорошо.»): it opens the lookup (the
    # harness serves none, so its answer is not dictated here), and the announcement of the cloud is never cued
    assert w.c.question_id == 'u5', w.c.question_id
    assert not any('смотрю' in text for _, text in w.played), w.played


def test_continue_brings_the_earlier_answers_back_once_the_new_one_is_said(tmp_path):
    """The questions retired the earlier answers unsaid: once the newest is said, «продолжай» brings them back, the latest first (CL2)."""
    w = call_2010(tmp_path)
    w.confirm(41.0)                              # the listener repeats «Десять — пять плюс пять.»: that answer is complete
    w.user('u9', ' Продолжай', 42.0, 43.0)
    w.until(43.4)
    assert [text for at, text in w.played if at >= 43.0] == ['Четыре.'], w.played
    w.confirm(43.5)
    w.user('u10', ' Продолжай', 44.5, 45.5)
    w.until(47.5)
    assert any(text.startswith('свойство тела') for at, text in w.played if at >= 45.5), w.played


def test_a_portion_nobody_repeats_is_abandoned_and_the_next_question_is_answered(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = call_2010(tmp_path, chatter=True).until(76.0)
    assert w.played[0][1].startswith('свойство тела'), w.played
    lines = [r.getMessage() for r in caplog.records]
    abandoned = [line for line in lines if 'reason=portion_abandoned' in line]
    assert len(abandoned) == 1 and 'tried=False' in abandoned[0], lines
    assert w.c.question_id == 'u5', w.c.question_id
    assert not any('смотрю' in text for _, text in w.played), w.played
    assert not any(text.startswith('свойство тела') for at, text in w.played if at >= 22.9), w.played


def test_the_portion_is_released_at_the_first_utterance_twenty_seconds_after_its_cue(tmp_path):
    w = call_2010(tmp_path, chatter=True)
    w.until(30.0)
    assert w.state().get('chunks') and not w.state().get('completed'), w.state()       # 11.8 s after the cue: still waits
    w.until(38.5)
    assert w.state().get('completed') and not w.state().get('chunks'), w.state()       # 26.8 s after it: released
    assert not w.state().get('pending_turn'), w.state()                                 # by the abandonment, not by a question
    entry = w.state()['history'][-1]
    assert entry['question'] == INERTIA_Q and entry['status'] == 'interrupted' and entry['spoken'] == 0, entry


def test_the_real_call_cues_no_greeting_and_its_questions_are_questions(tmp_path):
    """The 20:10 call as it was: the greeting cues nothing, so nothing waits; the arithmetic questions are answered and the account question
    is a question."""
    w = call_2010(tmp_path, first=(' Да, привет, привет. Ну что, как дела? Что-то слышишь меня', ' Да, слышу хорошо. Как ты сам?'),
                  account_answer='')
    w.until(76.0)
    assert not any(at < 22.9 for at, _ in w.played), w.played           # deployed: «Да, слышу хорошо.» at 11.2 s
    assert not any('слышу' in text.lower() for _, text in w.played), w.played
    assert any(text.startswith('Четыре') for _, text in w.played), w.played
    assert any(text.startswith('Десять') for _, text in w.played), w.played
    assert w.c.question_id == 'u5', w.c.question_id


@pytest.mark.parametrize('said', [' Повтори', ' Продолжай'])
def test_repeat_or_continue_brings_the_abandoned_answer_back(tmp_path, said):
    w = call_2010(tmp_path, chatter=True)
    w.until(40.0)
    assert w.state().get('completed') and not w.state().get('pending_turn'), w.state()
    w.user('u9', said, 42.0, 43.0)
    w.until(46.0)
    assert any(text.startswith('свойство тела') for at, text in w.played if at >= 43.0), w.played


# -- 1. what never releases it (S6 invariants) ---------------------------------------------------------------------------------------
def lake(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', INERTIA_Q, 0.0, 2.0)
    w.assistant('a1', INERTIA_A, 2.01, 3.0)
    return w


def waits(w):
    state = w.state()
    return bool(state.get('chunks')) and not state.get('completed') and state.get('chunk_index') == 0


def test_a_pause_with_no_speech_never_releases_it(tmp_path):
    w = lake(tmp_path).until(60.0)
    assert waits(w), w.state()


def test_a_bystander_while_the_listener_keeps_trying_never_releases_it(tmp_path):
    w = lake(tmp_path)
    t = 5.0
    for k in range(6):                     # every 8 s: a bystander, then a try at the portion
        w.user(f'b{k}', ' Мы вчера ходили в кино, там было шумно', t, t + 1.5)
        w.user(f't{k}', ' Инерция это свойство', t + 3.0, t + 4.0)
        t += 8.0
    w.user('bz', ' Мы вчера ходили в кино, там было шумно', t, t + 1.5)
    w.until(t + 3.0)
    assert waits(w), w.state()


def test_repeat_requests_keep_it(tmp_path):
    w = lake(tmp_path)
    w.user('r1', ' Повтори', 12.0, 12.5)
    w.user('b1', ' Мы вчера ходили в кино, там было шумно', 25.0, 26.5)
    w.until(28.0)
    assert waits(w), w.state()


def test_wrong_repeats_long_after_the_cue_keep_it(tmp_path):
    w = lake(tmp_path)
    for k, t in enumerate((10.0, 20.0, 30.0)):
        w.user(f't{k}', ' Инерция это свойство тела', t, t + 1.0)
    w.until(34.0)
    assert waits(w), w.state()


def test_the_cap_spent_then_other_speech_releases_it_when_the_listener_never_tried(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    w = lake(tmp_path)
    w.until(12.0)                                    # cue at ~2 s, auto-repeat at ~10 s: the cap (1) is spent
    assert len(w.played) == 2, w.played
    w.user('b1', ' Мы вчера ходили в кино, там было шумно', 13.0, 14.5)
    w.until(16.0)
    assert not waits(w), w.state()
    assert any('reason=portion_abandoned' in r.getMessage() for r in caplog.records)


def test_the_cap_spent_after_a_try_does_not_release_on_a_bystander(tmp_path):
    w = lake(tmp_path)
    w.user('t1', ' Инерция это свойство', 4.5, 5.5)
    w.until(14.0)                                    # the try re-arms the timer: the auto-repeat at ~12.5 s spends the cap
    w.user('b1', ' Мы вчера ходили в кино, там было шумно', 15.0, 16.5)
    w.until(18.0)
    assert waits(w), w.state()


def test_an_attempt_judged_by_the_ear_counts_as_a_try(tmp_path):
    w = lake(tmp_path)
    w.until(5.0)
    w.c.ear_onset(1)
    w.now = 6.0
    w.c.ear_heard({'uid': 1, 'text': 'инерция это свойство', 'offset': 6.0})
    tracker = w.c.abandon
    assert tracker is not None and tracker['engaged'] == 6.0, tracker
