"""G3 Part 2: the rules of the turn arbiter one by one, on the wire of tests/helpers_w1f.py (the matrix, tests/test_g3_matrix.py, crosses them)."""
import logging

from cm_patch import patch_controller
import pytest

import echo_sync.controlled_media as cm
from echo_sync.textutil import talks_about_itself
from helpers_w1f import Wire

Q = 'Как считают амортизацию станка?'
A = 'Обычно станок списывают за 10 лет. Линейный способ не меняет ежегодную сумму начисления. Первый учёт амортизации ввели в 1885 году.'
FIRST, SECOND = 'Обычно станок списывают за 10 лет.', 'Линейный способ не меняет ежегодную сумму начисления.'
THIRD = 'Первый учёт амортизации ввели в 1885 году.'
BYSTANDER = 'Вася уже подъехал к заправке на углу'
INTRUDER = 'Заправка на углу работает круглосуточно.'


class Recorder(Wire):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen = []

    def _act(self, actions):
        self.seen.extend(actions or [])
        super()._act(actions)

    def of(self, kind):
        return [action for action in self.seen if action['type'] == kind]


def decisions(caplog, reason):
    return [r for r in (x.getMessage() for x in caplog.records) if f'reason={reason}' in r]


@pytest.fixture(autouse=True)
def info_log(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(): None)


def waiting(tmp_path):
    w = Recorder(tmp_path)
    w.user('u1', Q, 0.0, 1.0)
    w.assistant('a1', ' ' + A, 1.05, 2.0)
    w.until(4.0)
    assert w.state()['chunks'][:2] == [FIRST, SECOND] and w.state()['chunk_index'] == 0
    return w


# -- rule 2: a repeat that goes on ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('tail', ['А почему?', 'А что такое дебиторская задолженность?'], ids=['why', 'new'])
def test_a_repeat_and_a_question_in_one_breath_confirm_once_and_the_question_is_answered(tmp_path, tail):
    w = waiting(tmp_path)
    w.user('u2', FIRST + ' ' + tail, 4.5, 6.0)
    w.assistant('a2', ' Дебиторская задолженность — это долги покупателей.', 6.05, 6.8)
    w.until(9.0)
    assert any('долги покупателей' in text for text in w.played_after(4.5)), w.played
    assert SECOND not in w.played_after(4.5), 'the next portion is not spoken over the question'
    assert w.state()['history'][0]['spoken'] == 1, 'the repeat counted once'
    assert w.state()['question'].startswith(FIRST.rstrip('.')), w.state()['question']


@pytest.mark.parametrize('rest', [' не', ' но это не так', ' а наоборот нет'])
def test_words_that_take_the_repeat_back_are_no_repeat(tmp_path, rest):
    w = waiting(tmp_path)
    w.user('u2', FIRST.rstrip('.') + rest, 4.5, 5.5)
    w.until(7.0)
    assert w.state()['chunk_index'] == 0


def test_a_near_copy_with_the_last_word_replaced_is_no_repeat_and_a_tail(tmp_path):
    """The lenient rule forgives a loose word left out; the words after it are what replaced it."""
    w = waiting(tmp_path)
    w.user('u2', 'Обычно станок списывают за 10 лет', 4.5, 5.3)
    w.until(7.0)
    assert w.state()['chunk_index'] == 1
    w.user('u3', 'Линейный способ не меняет ежегодную сумму', 8.0, 9.0)
    w.until(9.5)
    assert w.state()['chunk_index'] == 1


def test_a_number_after_a_portion_that_ends_in_a_number_is_no_repeat(tmp_path):
    w = Recorder(tmp_path)
    w.user('u1', 'Что показывает коэффициент текущей ликвидности?', 0.0, 1.0)
    # w3-integ: since r21-core (R21-03) «от 1,5 до 2,5» is one portion, a range is not cut in half; the portion that ends in a number is now this one
    # c23: since c22-merge G15 joins the next clause while it fits the cap of 9 words; the clause after the number is made longer than that,
    # so the first portion still ends in the number (the premise of this test)
    w.assistant('a1', ' Нормой считают значение больше 1,5, это хороший уровень для большинства крупных производственных компаний страны. Показатель ниже единицы не означает банкротства.', 1.05, 2.0)
    w.until(4.0)
    assert w.state()['chunks'][0] == 'Нормой считают значение больше 1,5,'
    w.user('u2', 'Нормой считают значение больше 1,5 пять', 4.5, 5.5)
    w.until(7.0)
    assert w.state()['chunk_index'] == 0


def test_extra_plain_words_after_a_repeat_only_confirm(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', FIRST + ' вот так вот', 4.5, 5.5)
    w.until(8.0)
    assert w.state()['chunk_index'] == 1 and w.played_after(4.5) == [SECOND], w.played


def test_a_tail_the_classifier_cannot_place_waits_for_the_cloud_and_the_plan_goes_on(tmp_path, caplog):
    w = waiting(tmp_path)
    w.user('u2', FIRST + ' сорок восемь рублей умножить на десять', 4.5, 5.5)
    w.until(5.7)
    assert w.state()['chunk_index'] == 1
    w.assistant('a2', ' Четыреста восемьдесят.', 5.75, 6.3)
    w.until(9.0)
    assert decisions(caplog, 'cloud_admitted') and 'Четыреста восемьдесят.' in w.played_after(4.5), w.played


# -- rule 3: a partial, a stuck listener ------------------------------------------------------------------------------------------------------------------

def test_the_same_start_again_gets_only_what_is_missing_at_once(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Обычно станок', 4.5, 5.0)
    w.until(5.2)
    assert w.played_after(4.5) == []
    w.user('u3', 'Обычно станок', 5.5, 6.0)
    w.until(6.3)
    assert w.played_after(4.5) == ['списывают за 10 лет.'] and w.state()['chunk_index'] == 0, w.played


def test_a_word_said_twice_gets_only_what_is_missing_at_once(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Обычно станок станок', 4.5, 5.2)
    w.until(5.5)
    assert w.played_after(4.5) == ['списывают за 10 лет.'], w.played


def test_a_listener_who_stops_after_a_start_gets_only_what_is_missing_after_the_silence(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Обычно станок', 4.5, 5.0)
    w.until(12.5)
    assert w.played_after(4.5) == ['списывают за 10 лет.'] and w.state()['chunk_index'] == 0, w.played


def test_the_repeat_of_the_tail_confirms_the_portion_once(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Обычно станок станок', 4.5, 5.2)
    w.until(7.5)
    w.user('u3', 'списывают за 10 лет', 7.6, 8.4)
    w.until(10.0)
    assert w.state()['chunk_index'] == 1 and w.played_after(7.6) == [SECOND], w.played


def test_only_the_last_try_decides_how_soon_the_portion_comes_back(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Обычно станок списывают за 12 лет', 4.5, 5.3)
    w.user('u3', 'Обычно', 5.4, 5.7)
    w.until(8.0)
    assert w.played_after(4.5) == [], 'a listener who stopped gets the silence, not the replay of a wrong repeat'
    w.until(12.5)
    assert w.played_after(4.5) == ['станок списывают за 10 лет.'], w.played


def test_a_tail_heard_long_ago_is_still_the_tail(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Обычно станок станок', 4.5, 5.2)
    w.until(20.0)
    assert w.played_after(4.5)[0] == 'списывают за 10 лет.'
    w.user('u3', 'списывают за 10 лет', 20.5, 21.2)
    w.until(23.0)
    assert w.state()['chunk_index'] == 1, w.played


def test_a_wrong_repeat_stays_and_the_portion_is_said_again_at_once(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Обычно станок списывают за 12 лет', 4.5, 5.3)
    w.until(5.4)
    assert w.played_after(4.5) == [], 'a wrong final speaks nothing in its own tick (S6)'
    w.until(6.5)
    assert w.state()['chunk_index'] == 0 and w.played_after(4.5) == [FIRST], w.played


# -- round 2: preparing is not releasing ------------------------------------------------------------------------------------------------------------------

def test_a_candidate_is_released_after_the_silence_and_not_before(tmp_path, caplog):
    w = waiting(tmp_path)
    w.user('u2', BYSTANDER, 4.5, 5.5)
    w.assistant('a2', ' ' + INTRUDER, 5.55, 6.3)
    w.until(6.6)
    assert w.played_after(4.5) == [] and w.state()['chunks'][0] == FIRST, w.played
    w.until(7.2)
    assert w.played_after(4.5) == [INTRUDER], w.played


def test_speech_right_after_the_reply_keeps_it_unreleased_and_the_next_final_is_judged(tmp_path, caplog):
    w = waiting(tmp_path)
    w.user('u2', BYSTANDER, 4.5, 5.5)
    w.assistant('a2', ' ' + INTRUDER, 5.55, 6.3)
    w.user('u3', 'Ну да, я тоже так подумал тогда', 6.6, 7.6)
    w.until(10.0)
    assert not decisions(caplog, 'cloud_admitted') and w.state()['chunks'][0] == FIRST and INTRUDER not in w.played_after(4.5), w.played


def test_a_cough_in_the_window_only_starts_it_again(tmp_path, caplog):
    w = waiting(tmp_path)
    w.user('u2', BYSTANDER, 4.5, 5.5)
    w.assistant('a2', ' ' + INTRUDER, 5.55, 6.3)
    w.at(6.5, lambda wire: wire.c.speech_started())
    w.until(8.5)
    assert w.played_after(4.5) == [], w.played
    w.until(10.0)
    assert INTRUDER in w.played_after(4.5), w.played


def test_a_backchannel_of_the_listener_keeps_the_prepared_reply(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', BYSTANDER, 4.5, 5.5)
    w.assistant('a2', ' ' + INTRUDER, 5.55, 6.3)
    w.user('u3', 'Угу', 6.5, 6.8)
    w.until(8.0)
    assert INTRUDER in w.played_after(4.5), w.played


def test_a_question_form_is_not_held(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Что такое дебиторская задолженность?', 4.5, 5.5)
    w.assistant('a2', ' Дебиторская задолженность — это долги покупателей.', 5.55, 6.3)
    w.until(6.5)
    assert any('долги покупателей' in text for text in w.played_after(4.5)), w.played


def test_a_lower_case_answer_of_the_right_form_right_after_a_cut_is_the_answer_and_the_old_rest_is_not(tmp_path):
    def cut(said, tid):
        w = Recorder(tmp_path / tid)
        w.user('u1', Q, 0.0, 1.0)
        w.at(1.05, {'type': 'turn.created', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ' ' + FIRST + ' Линейный способ не меняет'}})
        w.until(3.5)
        w.at(3.9, {'type': 'turn.done', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ' ' + FIRST + ' Линейный способ не меняет'}})
        w.user('u2', 'Когда появился налог на прибыль?', 4.0, 5.0)
        w.assistant('a2', said, 5.05, 5.6)
        w.until(9.0)
        return w
    assert any('1992' in text for text in cut(' в 1992 году.', 'real').played_after(4.0))
    assert not any('ежегодную' in text for text in cut(' ежегодную сумму начисления.', 'old').played_after(4.0))


# -- rule 4: the binding of a reply, first-person content ---------------------------------------------------------------------------------------------------

def test_a_real_new_answer_during_an_old_stream_admits_and_the_old_stream_is_no_longer_cued(tmp_path, caplog):
    w = Recorder(tmp_path)
    w.user('u1', Q, 0.0, 1.0)
    w.at(1.05, {'type': 'turn.created', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ' ' + FIRST + ' Линейный способ не меняет'}})
    w.until(3.5)
    w.user('u2', 'сорок две тысячи умножить на двенадцать', 4.0, 5.0)
    w.assistant('a2', ' Пятьсот четыре тысячи.', 5.05, 5.6)
    w.at(5.8, {'type': 'turn.delta', 'turn_id': 'a1', 'delta': ' ежегодную сумму начисления.'})
    w.until(9.0)
    assert decisions(caplog, 'cloud_admitted') and 'Пятьсот четыре тысячи.' in w.played_after(4.0), w.played
    assert 'ежегодную' not in w.plan()


def test_a_real_new_answer_right_after_a_cut_admits_and_the_rest_of_the_old_sentence_does_not(tmp_path, caplog):
    def cut(said):
        w = Recorder(tmp_path / said[:6])
        w.user('u1', Q, 0.0, 1.0)
        w.at(1.05, {'type': 'turn.created', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ' ' + FIRST + ' Линейный способ не меняет'}})
        w.until(3.5)
        w.at(3.9, {'type': 'turn.done', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ' ' + FIRST + ' Линейный способ не меняет'}})
        w.user('u2', 'сорок две тысячи рублей умножить на двенадцать', 4.0, 5.0)
        w.assistant('a2', said, 5.05, 5.6)
        w.until(9.0)
        return w
    w = cut(' Пятьсот четыре тысячи.')
    assert 'Пятьсот четыре тысячи.' in w.played_after(4.0) and decisions(caplog, 'cloud_admitted'), w.played
    caplog.clear()
    w = cut(' ежегодную сумму начисления.')
    assert not decisions(caplog, 'cloud_admitted') and 'ежегодную сумму' in w.plan() and w.c.question_id == 'u1', w.plan()


def test_a_real_answer_that_uses_the_old_answers_words_admits_a_retelling_does_not(tmp_path, caplog):
    w = waiting(tmp_path)
    w.user('u2', 'Не 10 лет, а 15', 4.5, 5.2)
    w.assistant('a2', ' Тогда станок списывают за 15 лет.', 5.25, 5.9)
    w.until(8.0)
    assert any('15 лет' in text for text in w.played_after(4.5)), w.played
    w = waiting(tmp_path / 'b')
    caplog.clear()
    w.user('u2', BYSTANDER, 4.5, 5.2)
    w.assistant('a2', ' Обычно станок списывают за 10 лет, линейный способ не меняет сумму.', 5.25, 5.9)
    w.until(8.0)
    assert not decisions(caplog, 'cloud_admitted') and w.state()['chunks'][0] == FIRST


@pytest.mark.parametrize('sentence', ['Я пять лет работал главным бухгалтером в строительной компании.', 'Я держу облигации федерального займа в своём портфеле.',
                                      'Я работаю бухгалтером.', 'Мы продаём станки в Казахстан.', 'Амортизация уменьшает прибыль.'])
def test_own_first_person_content_is_content(sentence):
    assert not talks_about_itself(sentence)


@pytest.mark.parametrize('sentence', ['Я сейчас посмотрю.', 'Попробую разобраться по сути и найти корень проблемы.', 'Понял, давай разберём по частям.',
                                      'Я всего лишь ассистент и не могу этого знать.', 'Я готов ответить на любой вопрос.', 'Постараюсь отвечать быстрее.',
                                      'Я вас слушаю.', 'Как ты сам?', 'Здорово, надеюсь, понравилось.', 'Я думаю над вашей задачей.', 'Понятно, едем.'])
def test_talk_about_the_assistant_is_not(sentence):
    assert talks_about_itself(sentence)


def test_an_answer_that_explains_the_same_thing_in_other_words_is_an_answer(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'А почему так?', 4.5, 5.2)
    w.assistant('a2', ' Потому что станок служит примерно 10 лет и дешевеет равномерно.', 5.25, 6.0)
    w.until(8.0)
    assert any('служит' in text for text in w.played_after(4.5)), w.played


def test_a_second_intruder_leaves_the_plan_where_it_was(tmp_path):
    w = admitted_intruder(tmp_path)
    w.user('u3', 'Лена сказала, что заказ привезут к пяти', 7.5, 8.5)
    w.assistant('a3', ' Заказ к пяти часам успеют доставить.', 8.55, 9.1)
    w.until(10.0)
    assert any('доставить' in text for text in w.played_after(7.5)), w.played
    w.user('u4', FIRST, 10.5, 11.2)
    w.until(13.0)
    assert w.state()['question'] == Q and w.played_after(10.5) == [SECOND], w.played


def test_a_first_person_content_answer_admits_a_promise_does_not(tmp_path, caplog):
    w = waiting(tmp_path)
    w.user('u2', 'сорок две тысячи рублей умножить на двенадцать', 4.5, 5.2)
    w.assistant('a2', ' Я сейчас посмотрю.', 5.25, 5.8)
    w.until(7.0)
    assert not decisions(caplog, 'cloud_admitted')
    w = waiting(tmp_path / 'b')
    w.user('u2', 'Расскажите о своём опыте работы', 4.5, 5.2)
    w.assistant('a2', ' Я пять лет работал главным бухгалтером в строительной компании.', 5.25, 6.2)
    w.until(9.0)
    assert any('главным бухгалтером' in text for text in w.played_after(4.5)), w.played


# -- rule 5: soft preemption -----------------------------------------------------------------------------------------------------------------------------

def admitted_intruder(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', BYSTANDER, 4.5, 5.5)
    w.assistant('a2', ' ' + INTRUDER, 5.55, 6.3)
    w.until(7.3)
    assert INTRUDER in w.played_after(4.5) and w.state()['chunks'] == [INTRUDER], w.played
    return w


def test_a_wrong_admission_costs_one_whisper_the_next_words_at_the_portion_take_the_plan_back(tmp_path, caplog):
    w = admitted_intruder(tmp_path)
    w.user('u3', FIRST, 7.5, 8.2)
    w.until(10.0)
    state = w.state()
    assert state['question'] == Q and state['chunks'][state['chunk_index']] == SECOND, state
    assert w.played_after(7.5) == [SECOND], w.played
    assert decisions(caplog, 'suspended_plan_taken_back')


def test_a_stop_said_to_the_new_answer_keeps_it(tmp_path):
    """F19: the listener worked with the new answer: a late repeat of the old portion moves nothing."""
    w = admitted_intruder(tmp_path)
    w.user('u3', 'Стоп', 7.5, 7.9)
    w.until(8.5)
    w.user('u4', FIRST, 9.0, 9.7)
    w.until(11.0)
    assert w.state()['chunks'] == [INTRUDER], w.state()['chunks']


def test_a_start_of_the_portion_takes_the_plan_back_too(tmp_path):
    w = admitted_intruder(tmp_path)
    w.user('u3', 'Обычно станок', 7.5, 8.0)
    w.until(9.0)
    assert w.state()['question'] == Q and w.state()['chunk_index'] == 0


def test_prodolzhay_over_an_answer_nobody_took_up_brings_the_plan_back(tmp_path):
    w = admitted_intruder(tmp_path)
    w.user('u3', 'Продолжай', 7.5, 8.0)
    w.until(9.5)
    assert w.state()['question'] == Q and w.played_after(7.5) == [FIRST], w.played


def test_after_the_new_answer_was_taken_up_the_plan_comes_back_by_prodolzhay_as_before(tmp_path):
    w = admitted_intruder(tmp_path)
    w.user('u3', INTRUDER, 8.0, 8.7)
    w.until(10.0)
    assert w.state()['completed']
    w.user('u4', 'Продолжай', 10.5, 11.0)
    w.until(12.5)
    assert w.state()['question'] == Q and w.played_after(10.5) == [FIRST], w.played


def test_a_try_at_the_new_answer_that_shares_the_old_words_stays_with_the_new_answer(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Не 10 лет, а 15', 4.5, 5.2)
    w.assistant('a2', ' Тогда станок списывают за 15 лет.', 5.25, 5.9)
    w.until(7.0)
    w.user('u3', 'Тогда станок', 7.5, 8.0)
    w.until(9.0)
    assert '15 лет' in w.plan(), w.plan()


def test_late_text_of_the_dropped_answer_is_never_cued(tmp_path):
    w = admitted_intruder(tmp_path)
    w.user('u3', FIRST, 7.5, 8.2)
    w.assistant('a3', ' Она закрывается только в праздники.', 8.25, 8.8)
    w.until(11.0)
    assert not any('праздники' in text for text in w.played_after(0)) and 'праздники' not in w.plan(), w.played


def test_a_question_the_cloud_declines_gives_the_plan_back(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Маш, а ты не видела ключи от машины?', 4.5, 5.5)
    w.assistant('a2', ' Угу.', 5.55, 5.8)
    w.until(8.5)
    assert w.state()['question'] == Q and w.played_after(4.5) == [FIRST] and not w.of('unanswered'), (w.played, w.state()['question'])


def test_an_objection_nobody_answers_never_brings_the_disputed_portion_back(tmp_path):
    w = waiting(tmp_path)
    w.user('u2', 'Это неправильно', 4.5, 5.0)
    w.until(16.0)
    assert w.played_after(4.5) == [] and w.of('unanswered'), w.played


# -- rule 6: owned by its question ---------------------------------------------------------------------------------------------------------------------------

def test_a_repeat_never_asks_anything_and_the_prepared_tail_is_not_made_again(tmp_path):
    w = waiting(tmp_path)
    made = w.c.engine.generate
    calls = []
    w.c.engine.generate = lambda *a, **k: calls.append(a) or made(*a, **k)
    for n, (t, text) in enumerate(((4.5, FIRST), (8.0, SECOND), (12.0, THIRD))):
        w.user(f'r{n}', text, t, t + 0.8)
        w.assistant(f'c{n}', ' Хорошо, идём дальше по порядку.', t + 0.85, t + 1.2)
        w.until(t + 3.0)
    assert w.state()['completed'] and calls == [] and not w.of('lookup') and not w.of('context')


def test_a_late_repeat_of_the_finished_portion_is_no_candidate(tmp_path, caplog):
    w = waiting(tmp_path)
    for n, (t, text) in enumerate(((4.5, FIRST), (8.0, SECOND), (12.0, THIRD))):
        w.user(f'r{n}', text, t, t + 0.8)
        w.until(t + 3.0)
    w.user('late', THIRD, 16.0, 16.8)
    w.assistant('c', ' Этот учёт вводили ради налогов.', 16.85, 17.4)
    w.until(19.0)
    assert not decisions(caplog, 'cloud_admitted') and w.state()['completed']


# -- rule 7: verify-class -----------------------------------------------------------------------------------------------------------------------------------

def test_a_verify_class_reply_before_the_sources_stays_unpublished_and_the_lookup_answer_replaces_it(tmp_path):
    w = Recorder(tmp_path)
    w.user('u1', 'Какая сейчас ключевая ставка Банка России?', 0.0, 1.0)
    w.assistant('a1', ' Ключевая ставка, по памяти, двадцать один процент.', 1.05, 1.6)
    w.until(2.0)
    assert w.played == [] and len(w.of('lookup')) == 1

    def found(wire):
        return wire.c.grounding(wire.of('lookup')[0]['epoch'], [{'url': 'https://example.org/a', 'text': 'Ключевая ставка Банка России составляет 16 процентов.'}])
    w.at(2.2, found)
    w.until(2.4)
    context = w.of('context')
    assert len(context) == 1
    w.c.delivery_sent(context[0]['epoch'], context[0].get('delegation_id'))
    w.assistant('a2', ' Ключевая ставка составляет 16 процентов.', 2.6, 3.2)
    w.at(3.3, {'type': 'delegation.created', 'item': {'id': 'late', 'target': 'client', 'user_bidi_turn_id': 'u1'}})
    w.until(5.0)
    assert len(w.of('lookup')) == 1 and len(w.of('context')) == 1, 'one lookup, one question to the model'
    assert not any('двадцать один' in text for text in w.played_after(0)) and any('16' in text for text in w.played_after(0)), w.played

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
