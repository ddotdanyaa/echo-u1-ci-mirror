"""g28-guards (wave 20): no path that opens a question opens one on words that were just in the cue, and none loses a real new question.

The paths: the final (classifier), the job of the text channel (the cloud's/brain's admission), the reference base, the model's delegation,
the cloud's own reply. The owner's call of 06.11 09:03: «источники его образования» said while «Активный счёт учитывает имущество,
пассивный —» waited became a question and «Пассивный счёт учитывает…» went round; «пятьдесят девятый счёт это» while a portion waited
was taken for a wrong repeat of it. A wrong repeat is only what looks like the portion; other words are a new question or talk.

REAL: the chain of the stand (helpers_g28.Scene: ControlledMedia, the acting ear, the text channel, the classifier, the engine).
SCRIPTED: the listener, the ear's and the cloud's texts, the model (a table of replies; it answers anything it is asked, the worst case).
"""
import logging

from cm_patch import patch_controller
import pytest

import echo_sync.controlled_media as cm
from echo_sync import reference_kb
from helpers_g28 import Scene

ACTIVE_Q = 'Чем активный счёт отличается от пассивного?'
ACTIVE = 'Активный счёт учитывает имущество, пассивный — источники его образования.'
ACTIVE_1 = 'Активный счёт учитывает имущество, пассивный —'
PASSIVE = 'Пассивный счёт учитывает источники образования имущества.'
ACC51_Q = 'Что такое пятьдесят первый счёт?'
ACC51 = 'Пятьдесят первый счёт — это расчётные счета организации в банке.'
ACC59 = 'Пятьдесят девятый счёт — резервы под обесценение финансовых вложений.'
NEW = 'Это ответ на новый вопрос.'


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


@pytest.fixture(autouse=True)
def quiet_base(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(), **_: None)


@pytest.fixture
def scene():
    made = []

    def build(replies, **keywords):
        made.append(Scene(replies, **keywords))
        return made[-1]
    yield build
    for s in made:
        s.close()


def asked(s, question, at=1.0, until=4.6):
    s.say(at, question)
    s.until(until)
    assert s.cues(), 'precondition: the first portion was cued'
    return s.state()['revision']


def opened(caplog):
    return [r.getMessage() for r in caplog.records if 'decision kind=question' in r.getMessage()]


# =====================================================================================================================================
# 1. words of the answer in play open nothing
# =====================================================================================================================================

def test_the_next_portion_said_ahead_opens_no_question(scene, caplog):
    """The owner, 06.11 09:03: the words of the answer that the listener knows before they are cued are no question."""
    s = scene({'чем активный счет': ACTIVE, 'источники его образования': PASSIVE})
    rev = asked(s, ACTIVE_Q)
    s.say(4.7, 'источники его образования')
    s.until(14)
    assert PASSIVE not in s.cues(), s.cues()
    assert s.state()['revision'] == rev and s.state()['question'] == ACTIVE_Q, s.state()['question']


@pytest.mark.parametrize('late', [0.8, 2.5, 4.5])
def test_the_last_portion_repeated_with_a_late_final_opens_no_question(scene, late):
    s = scene({'чем активный счет': ACTIVE, 'источники его образования': PASSIVE})
    rev = asked(s, ACTIVE_Q)
    s.repeat(4.7)
    s.until(6.8)
    s.say(6.9, 'источники его образования', late=late)
    s.until(20)
    assert PASSIVE not in s.cues() and s.state()['revision'] == rev, s.cues()


def test_the_last_portion_said_again_after_the_answer_is_over_opens_no_question(scene):
    s = scene({'чем активный счет': ACTIVE, 'источники его образования': PASSIVE})
    rev = asked(s, ACTIVE_Q)
    s.repeat(4.7)
    s.until(6.8)
    s.repeat(6.9)
    s.until(10)
    s.say(12, 'источники его образования это')
    s.until(20)
    assert PASSIVE not in s.cues() and s.state()['revision'] == rev, s.cues()


def test_the_cue_said_back_with_its_question_opens_no_question(scene):
    """The cloud glues the question and the cue into one final (the 06.11 call of 65f46fe91e81)."""
    s = scene({'чем активный счет': ACTIVE, 'учитывает имущество': PASSIVE})
    rev = asked(s, ACTIVE_Q)
    s.say(4.7, 'чем активный счёт отличается от пассивного активный счёт учитывает имущество', late=1.0)
    s.until(14)
    assert PASSIVE not in s.cues() and s.state()['revision'] == rev, s.cues()


def test_a_portion_with_a_question_word_in_it_repeated_is_a_repeat(scene):
    s = scene({'что уточнить': 'Сколько это в рублях. Потом спросите про скидку.', 'сколько это в рублях': NEW})
    rev = asked(s, 'Что уточнить у продавца?')
    assert s.cues()[0].startswith('Сколько это в рублях'), s.cues()
    s.repeat(4.7)
    s.until(12)
    assert NEW not in s.cues() and s.state()['revision'] == rev, s.cues()
    assert s.state()['chunk_index'] >= 1, 'the repeat moved on'


def test_the_clouds_own_reply_to_a_repeat_is_not_said(scene):
    s = scene({'чем активный счет': ACTIVE})
    rev = asked(s, ACTIVE_Q)
    s.repeat(4.7, reply=PASSIVE)
    s.until(14)
    assert PASSIVE not in ' '.join(s.cues()) and s.state()['revision'] == rev, s.cues()


def test_a_delegation_on_a_repeat_opens_no_lookup(scene):
    s = scene({'чем активный счет': ACTIVE})
    rev = asked(s, ACTIVE_Q)
    u = s.repeat(4.7)
    s.until(7.5)
    actions = s.w.controller.provider({'type': 'delegation.created', 'item': {'id': 'd-echo', 'target': 'client', 'user_bidi_turn_id': f'u{u.n}'}})
    assert not [a for a in actions or [] if a['type'] in ('lookup', 'route')], actions
    s.until(14)
    assert s.state()['revision'] == rev


def test_a_delegation_on_the_next_portion_said_ahead_opens_no_lookup(scene):
    s = scene({'чем активный счет': ACTIVE})
    rev = asked(s, ACTIVE_Q)
    u = s.say(4.7, 'источники его образования')
    s.until(7.5)
    actions = s.w.controller.provider({'type': 'delegation.created', 'item': {'id': 'd-ahead', 'target': 'client', 'user_bidi_turn_id': f'u{u.n}'}})
    assert not [a for a in actions or [] if a['type'] in ('lookup', 'route')], actions
    s.until(14)
    assert s.state()['revision'] == rev


def test_the_reference_base_does_not_answer_the_cue_said_back(scene, monkeypatch):
    """«Статья 59 Налогового кодекса —» (the owner's first portion cut at the dash): its repeat names an article the base knows."""
    patch_controller(monkeypatch, 'reference_lookup', reference_kb.lookup)
    s = scene({'статья пятьдесят девять': 'Статья 59 Налогового кодекса — безнадёжные долги, их списание.', 'статья 59': 'Статья 59 Налогового кодекса — безнадёжные долги, их списание.'})
    s.say(1.0, 'О чём статья пятьдесят девять Налогового кодекса?')
    s.until(5.0)
    assert s.cues(), s.cues()
    rev = s.state()['revision']
    s.repeat(5.1)
    s.until(14)
    assert s.state()['revision'] == rev, (s.cues(), s.state()['question'])


# =====================================================================================================================================
# 2. a real new question is never lost, and a wrong repeat is only what looks like the portion
# =====================================================================================================================================

def test_a_new_account_while_a_portion_waits_is_a_new_question(scene):
    """The owner, 06.11 09:03: «пятьдесят девятый счёт это» while «…расчётные счета организации в банке.» waits is no wrong repeat of it."""
    s = scene({'пятьдесят первый': ACC51, 'пятьдесят девятый': ACC59})
    rev = asked(s, ACC51_Q)
    s.say(4.7, 'пятьдесят девятый счёт это')
    s.until(14)
    assert any('резервы' in cue or 'Пятьдесят девятый' in cue for cue in s.cues(4.7)), s.cues()
    assert s.state()['revision'] != rev


def test_own_words_after_a_cue_are_no_wrong_repeat(scene, caplog):
    """The owner, 06.11 09:03: «приходный кассовый ордер, то есть наоборот» after a cue is his own words, not a try at the portion."""
    s = scene({'расходный кассовый ордер': 'Расходный кассовый ордер оформляет выдачу денег из кассы.'})
    asked(s, 'Что оформляет расходный кассовый ордер?')
    cues = len(s.cues())
    s.say(4.7, 'приходный кассовый ордер, то есть наоборот')
    s.until(7.0)
    assert not [r for r in caplog.records if 'attempt_shared_stem' in r.getMessage() and r.created], 'judged a try at the portion'
    assert len(s.cues()) == cues, s.cues()


def test_a_question_about_a_word_of_the_plan_is_a_question(scene):
    s = scene({'чем активный счет': ACTIVE, 'что такое источники образования': 'Источники образования — это капитал и обязательства.'})
    rev = asked(s, ACTIVE_Q)
    s.say(4.7, 'А что такое источники образования?')
    s.until(14)
    assert any('капитал' in cue for cue in s.cues(4.7)), s.cues()
    assert s.state()['revision'] != rev


def test_a_neighbour_term_is_a_question_of_its_own(scene):
    s = scene({'срок выездной': 'Срок выездной проверки два месяца.', 'срок камеральной': 'Срок камеральной проверки три месяца.'})
    asked(s, 'Какой срок выездной проверки?')
    s.repeat(4.7)
    s.until(8)
    s.say(9, 'а срок камеральной проверки')
    s.until(18)
    assert any('три месяца' in cue or 'Срок камеральной' in cue for cue in s.cues(9)), s.cues()


def test_another_number_of_the_same_words_is_a_question_of_its_own(scene):
    s = scene({'пятьдесят первый': ACC51, 'пятьдесят второй': 'Пятьдесят второй счёт — валютные счета организации.'})
    rev = asked(s, ACC51_Q)
    s.repeat(4.7)
    s.until(8)
    s.say(9, 'а пятьдесят второй')
    s.until(18)
    assert any('валютные' in cue or 'Пятьдесят второй' in cue for cue in s.cues(9)), s.cues()
    assert s.state()['revision'] != rev


def test_a_bystanders_question_with_no_mark_while_a_portion_waits_is_answered(scene):
    s = scene({'чем активный счет': ACTIVE, 'сколько стоит билет до москвы': 'Билет до Москвы стоит около трёх тысяч рублей.'})
    rev = asked(s, ACTIVE_Q)
    s.say(4.7, 'сколько стоит билет до москвы')
    s.until(14)
    assert any('Билет' in cue or 'тысяч' in cue for cue in s.cues(4.7)), s.cues()
    assert s.state()['revision'] != rev


def test_a_wrong_number_in_a_repeat_is_still_a_wrong_repeat(scene):
    s = scene({'сколько стоит час': 'Один час работы стоит полторы тысячи рублей.', 'две тысячи': NEW})
    rev = asked(s, 'Сколько стоит час работы?')
    s.say(4.7, 'один час работы стоит две тысячи рублей')
    s.until(12)
    assert NEW not in s.cues() and s.state()['revision'] == rev and s.state()['chunk_index'] == 0, s.cues()


def test_the_next_portion_said_ahead_that_only_the_ear_heard_opens_no_question(scene):
    s = scene({'чем активный счет': ACTIVE, 'источники его образования': PASSIVE})
    rev = asked(s, ACTIVE_Q)
    s.say(4.7, 'источники его образования', lost=True)
    s.until(14)
    assert PASSIVE not in s.cues() and s.state()['revision'] == rev, s.cues()


def test_the_next_portion_said_ahead_with_a_filler_opens_no_question(scene):
    s = scene({'чем активный счет': ACTIVE, 'источники его образования': PASSIVE})
    rev = asked(s, ACTIVE_Q)
    s.say(4.7, 'ну вот источники его образования', late=2.0)
    s.until(14)
    assert PASSIVE not in s.cues() and s.state()['revision'] == rev, s.cues()


@pytest.mark.xfail(strict=True, reason='g31: a bare «пример» stays a stray word by design (user_intents.clarification_request); the start of the portion and it is a try')
def test_a_word_of_the_plan_and_a_word_that_asks_is_a_question(scene):
    s = scene({'чем активный счет': ACTIVE, 'пример': 'Например, счёт 01 «Основные средства».'})
    rev = asked(s, ACTIVE_Q)
    s.say(4.7, 'активный счёт пример')
    s.until(14)
    assert any('Основные средства' in cue or 'Например' in cue for cue in s.cues(4.7)), s.cues()
    assert s.state()['revision'] != rev


def test_a_question_asked_again_alone_is_still_answered(scene):
    s = scene({'чем активный счет': ACTIVE})
    asked(s, ACTIVE_Q)
    s.repeat(4.7)
    s.until(7)
    s.repeat(7.1)
    s.until(10)
    n = len(s.cues())
    s.say(12, ACTIVE_Q)
    s.until(20)
    assert len(s.cues()) > n, s.cues()


BUYERS_Q = 'Где учитывают расчёты с покупателями?'
BUYERS = 'Расчёты с покупателями и заказчиками ведут в бухгалтерии отдельно. Для этого служит шестьдесят второй счёт.'


@pytest.fixture
def real_base(monkeypatch):
    patch_controller(monkeypatch, 'reference_lookup', reference_kb.lookup)


def test_the_plan_said_ahead_that_the_reference_base_knows_opens_no_question(scene, real_base):
    s = scene({'где учитывают расчеты': BUYERS})
    rev = asked(s, BUYERS_Q)
    assert 'шестьдесят втором' not in s.cues()[0], s.cues()
    s.say(4.7, 'шестьдесят второй счёт')
    s.until(14)
    assert not any('Счёт 62' in cue for cue in s.cues()), s.cues()
    assert s.state()['revision'] == rev, s.state()['question']


def test_the_last_cue_said_again_that_the_reference_base_knows_does_not_go_round(scene, real_base):
    s = scene({'где учитывают расчеты': BUYERS})
    rev = asked(s, BUYERS_Q)
    for at in (4.7, 7.7, 10.7, 13.7):
        if s.state().get('completed'):
            break
        s.repeat(at)
        s.until(at + 2.9)
    assert s.state().get('completed'), (s.cues(), s.state()['chunk_index'])
    last = s.cues()[-1]
    n = len(s.cues())
    s.say(s.now() + 1.0, last.rstrip('.'))
    s.until(s.now() + 10)
    assert len(s.cues()) == n and s.state()['revision'] == rev, s.cues()[n:]


def test_an_earlier_question_asked_again_in_few_words_is_answered(scene, real_base):
    s = scene({})
    asked(s, ACC51_Q)
    s.repeat(4.7)
    s.until(8)
    s.say(9, 'Что такое пятьдесят второй счёт?')
    s.until(12.6)
    s.repeat(12.7)
    s.until(16)
    assert s.state().get('completed') and '52' in s.cues()[-1], s.cues()
    n = len(s.cues())
    s.say(17, 'пятьдесят первый счёт')
    s.until(24)
    assert any('51' in cue for cue in s.cues()[n:]), s.cues()


# =====================================================================================================================================
# 3. the same with the text channel off: the cloud's delegation and its own reply are the evidence
# =====================================================================================================================================

OFF = {'fast_text': 'off'}


def cloud_asked(s, question, answer):
    s.say(1.0, question, reply=answer)
    s.until(6.0)
    assert s.cues(), 'precondition: the first portion was cued'
    return s.state()['revision']


def test_off_the_next_portion_said_ahead_and_the_clouds_reply_open_no_question(scene):
    s = scene({}, flags=OFF)
    rev = cloud_asked(s, ACTIVE_Q, ACTIVE)
    s.say(6.1, 'источники его образования', reply=PASSIVE)
    s.until(16)
    assert PASSIVE not in s.cues() and s.state()['revision'] == rev, s.cues()


def test_off_the_next_portion_said_ahead_and_a_delegation_open_no_lookup(scene):
    s = scene({}, flags=OFF)
    rev = cloud_asked(s, ACTIVE_Q, ACTIVE)
    u = s.say(6.1, 'источники его образования', late=0.5)
    s.until(7.3)
    actions = s.w.controller.provider({'type': 'delegation.created', 'item': {'id': 'd-off', 'target': 'client', 'user_bidi_turn_id': f'u{u.n}'}})
    s.until(16)
    assert not [a for a in actions or [] if a['type'] in ('lookup', 'route')], actions
    assert s.state()['revision'] == rev, s.state()['question']


def test_off_a_new_account_while_a_portion_waits_is_answered_by_the_cloud(scene):
    s = scene({}, flags=OFF)
    rev = cloud_asked(s, ACC51_Q, ACC51)
    s.say(6.1, 'пятьдесят девятый счёт это', reply=ACC59)
    s.until(16)
    assert any('резервы' in cue or 'Пятьдесят девятый' in cue for cue in s.cues(6.1)), s.cues()
    assert s.state()['revision'] != rev
