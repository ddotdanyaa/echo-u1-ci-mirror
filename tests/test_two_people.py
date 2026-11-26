"""w20 / g29-two-people: the owner and a friend share the call. The friend asks, corrects, thanks, reads from a sheet, goes quiet; both talk at once.

Verdicts are the production ``analyze`` (the controlled profile) and the production ``EchoEngine`` (test_cl2_resume.Session: a scripted model, an injected
clock). Rules: a new question wins and the old portion never comes back by itself; a remark between people (thanks, «правильно», a correction of a figure)
moves nothing and asks nothing; a question said over the owner's own words is still the question; «вернись» (and its forms) brings the earlier place back.
The owner, 06.11: «пятьдесят девятый счёт это» (a new question) was counted as a wrong repeat; «вернись» in any form must be a return, not a question for the model.
"""
import pytest

import helpers_s6_ack as H
from echo_sync.classifier import ACK, CORRECTION, GREETING, QUESTION, QUIET, RESUME, analyze
from echo_sync.engine import SILENT
from test_cl2_resume import A, A_PORTIONS, A_QUESTION, B, B_QUESTION, Session

PORTION = 'Активный счёт учитывает имущество организации'
WAITS = H.waiting(PORTION, 'Пассивный счёт учитывает источники его образования.')
STATE_AFTER_A = dict(H.waiting(A_PORTIONS[0], *A_PORTIONS[1:]))


def kind(text, state=WAITS):
    return analyze(text, state, [], H.PROD_SETTINGS)


# ---- 1. the friend cuts in with a question: the new question wins ---------------------------------------------------------------------

FRIEND_QUESTIONS = ('а какой срок уплаты НДС', 'какой срок уплаты НДС', 'так какой срок уплаты НДС', 'а что такое пассивный счёт',
                    'ставка налога на прибыль двадцать процентов сколько', 'сколько дней на уплату налога')


@pytest.mark.parametrize('text', FRIEND_QUESTIONS)
def test_a_friends_question_over_a_waiting_portion_is_a_new_question(text):
    decision = kind(text)
    assert decision.kind == QUESTION, (text, decision)
    assert decision.question, 'the question is kept, to be answered'


def test_a_bare_topic_line_while_a_portion_waits_is_a_question():
    assert kind('срок уплаты НДС').kind == QUESTION


@pytest.mark.parametrize('text', ['пассивный счёт учитывает какой срок уплаты НДС', 'активный счёт учитывает имущество какой срок уплаты НДС за квартал',
                                  'активный счёт учитывает а какой срок уплаты НДС'])
def test_the_question_said_over_the_owners_own_words_is_still_the_question(text):
    """Both talk at once: the start is the portion's words (or near), the rest is the friend's question. Not silence, not an ack."""
    decision = kind(text)
    assert decision.kind == QUESTION, (text, decision)
    assert 'срок уплаты ндс' in decision.question.lower(), 'the question carries the friend\'s words'


def test_the_owners_partial_repeat_and_the_friends_question_after_it():
    decision = kind('активный счёт что такое пассивный счёт')
    assert decision.kind == QUESTION and 'что такое пассивный сч' in decision.question.lower(), decision


def test_the_owners_own_repeat_alone_is_not_made_a_question_by_that_rule():
    """The split needs a real question after the owner's words: a repeat that merely contains «какой» of the portion stays an attempt."""
    waits = H.waiting('Назовите какой счёт активный', 'Дальше.')
    assert kind('назовите какой счёт активный', waits).kind in (ACK, QUIET)
    assert kind('назовите какой', waits).kind in (ACK, QUIET, 'replay')


def test_the_friend_reads_a_long_question_from_a_sheet():
    text = ('Назовите основные принципы бухгалтерского учёта, которые закреплены в федеральном законе о бухгалтерском учёте, и поясните, '
            'чем отличается метод начисления от кассового метода при признании доходов и расходов организации')
    decision = kind(text)
    assert decision.kind == QUESTION and decision.question.startswith('Назовите основные принципы'), decision


def test_the_friend_stays_silent_after_the_question():
    for text in ('', '   ', 'э-э', 'хм'):
        assert kind(text).kind == QUIET, text


# ---- 2. remarks between people: nothing moves, nothing asks ------------------------------------------------------------------------

REMARKS = ('правильно', 'да правильно', 'всё верно', 'спасибо', 'понятно', 'ясно', 'хорошо', 'отлично', 'ну да', 'понял', 'ладно', 'угу',
           'нет там двадцать процентов', 'нет там двадцать процентов а не двадцать пять', 'а нет там двадцать процентов не двадцать пять')


@pytest.mark.parametrize('text', REMARKS)
def test_a_remark_between_the_people_asks_and_moves_nothing(text):
    decision = kind(text)
    assert decision.kind in (QUIET, GREETING), (text, decision)


@pytest.mark.parametrize('text', REMARKS)
def test_a_remark_between_the_people_moves_the_engine_nowhere(tmp_path, text):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    before = (s.state['chunk_index'], s.state['revision'], list(s.calls))
    reply = s.say(text)
    assert reply != A_PORTIONS[1], 'a remark is not a confirmation of the portion'
    assert (s.state['chunk_index'], s.state['revision']) == before[:2] and s.calls == before[2], (text, reply, s.calls)


# ---- 3. the engine: who wins, what never comes back ------------------------------------------------------------------------------

def _drain(s, limit=12):
    out = []
    for _ in range(limit):
        if s.state['completed']:
            break
        out.append(s.say(s.state['chunks'][s.state['chunk_index']]))
    return out


def test_the_friends_question_cuts_the_portion_and_the_old_answer_does_not_come_back_by_itself(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    first_b = s.say(B_QUESTION)
    assert first_b and first_b not in A_PORTIONS
    said = [first_b] + [r for r in _drain(s) if r]
    assert not set(said) & set(A_PORTIONS), said
    assert s.state['question'] == B_QUESTION and s.calls == [A_QUESTION, B_QUESTION]
    assert s.say('понятно') not in A_PORTIONS and s.say('спасибо') not in A_PORTIONS


def test_the_owner_repeats_the_friends_question_and_it_is_answered_not_lost(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(B_QUESTION)
    again = s.say(B_QUESTION)
    assert again and again not in A_PORTIONS, 'the same question said again is a question: B, never the old A'
    assert s.state['question'] == B_QUESTION


def test_a_friend_who_corrects_a_figure_does_not_make_a_question_of_the_answers_words(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say('нет там три процента')
    assert s.calls == [A_QUESTION] and s.state['chunk_index'] == 0


def test_both_talk_at_once_the_question_reaches_the_model(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say('Один два что такое масса')
    assert s.calls[-1].lower().endswith('что такое масса') and len(s.calls) == 2, s.calls
    assert s.state['chunk_index'] == 0


def test_the_friend_reads_a_long_question_and_the_model_gets_all_of_it(tmp_path):
    long = 'Назовите основные принципы бухгалтерского учёта и поясните, чем отличается метод начисления от кассового метода'
    s = Session(tmp_path)
    s.say(A_QUESTION)
    reply = s.say(long)
    assert s.calls[-1] == long and reply not in A_PORTIONS


def test_the_friend_is_quiet_after_the_question_nothing_is_invented(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    first = s.say(B_QUESTION)
    for text in ('', 'э-э', 'хм'):
        assert s.say(text, gap=20.0) in (SILENT, first), text
    assert s.calls == [A_QUESTION, B_QUESTION]


# ---- 4. «вернись»: back to the earlier place ------------------------------------------------------------------------------------

RETURN_WORDS = ('Вернись.', 'вернись назад', 'вернись к ответу', 'вернись к прошлому месту', 'вернись на прошлое место', 'давай вернёмся',
                'а теперь вернись', 'вернись к предыдущему ответу', 'Вернёмся к прошлому вопросу.', 'вернитесь пожалуйста',
                'вернись к тому что было')


@pytest.mark.parametrize('text', RETURN_WORDS)
def test_the_return_words_are_a_return_not_a_question(text):
    decision = kind(text)
    assert (decision.kind, decision.reason.startswith('resume_return')) == (RESUME, True), (text, decision)


@pytest.mark.parametrize('text', ['вернись к ответу', 'вернись', 'вернись назад', 'вернись к прошлому месту'])
def test_after_the_friends_answer_the_word_back_brings_the_earlier_place(tmp_path, text):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])                  # one portion confirmed
    s.say(B_QUESTION)                     # the friend's question wins
    s.to_the_end()
    assert s.say(text) == A_PORTIONS[1], 'A comes back at its first unconfirmed portion'
    assert s.calls == [A_QUESTION, B_QUESTION], 'a return is never a question for the model'


def test_the_return_word_with_nothing_earlier_asks_nothing(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say('вернись')
    assert s.calls == [A_QUESTION]


@pytest.mark.parametrize('text', ['вернись к цунами', 'вернись и расскажи про инерцию', 'вернуться домой', 'не возвращайся'])
def test_a_return_word_inside_another_request_is_not_a_return(text):
    assert kind(text).reason != 'resume_return', text


def test_one_word_of_the_portion_said_twice_is_not_the_owners_words():
    """integ-c19 (test_chaos seed 6): «если у меня было 70 рублей и я потратил 80 рублей сколько денег осталось» over «осталось 10 рублей» is the friend's whole
    question, not the owner's «рублей … рублей» and then «сколько денег осталось» cut off from its condition."""
    from echo_sync.classifier import analyze
    state = {'revision': 1, 'question': 'Если у меня было 20 рублей и я потратил 30 рублей, сколько денег осталось?', 'answer': 'Не хватает 10 рублей. Осталось 10 рублей.',
             'chunks': ['Не хватает 10 рублей.', 'Осталось 10 рублей.'], 'chunk_index': 1, 'completed': False, 'pending_turn': None, 'history': []}
    decision = analyze('если у меня было 70 рублей и я потратил 80 рублей сколько денег осталось', state, [])
    assert decision.reason != 'question_over_owner_words', decision


@pytest.mark.parametrize('said,portion,bad', [
    ('вторая мировая когда это началось', 'Вторая мировая война закончилась второго сентября.', 'когда это началось'),
    ('лед плавает потому что он легче лампочка', 'Лёд плавает, потому что он легче воды.', 'что он легче лампочка'),
], ids=['points_back', 'because'])
def test_no_question_cut_out_of_the_owners_words(said, portion, bad):
    """integ-c19 (w3_scenes, w9_long): a rest that points back with «это» asks about the words before it; «потому что» asks nothing."""
    from echo_sync.classifier import analyze
    state = dict(H.waiting(portion, 'Дальше.'))
    decision = analyze(said, state, [])
    assert not (decision.reason == 'question_over_owner_words' and decision.question == bad), decision


def test_the_preposition_stays_with_the_question_word():
    """integ-c19: «… статья восемьдесят восемь а в каком году приняли первую часть налогового кодекса»: the question keeps its «в»."""
    from echo_sync.classifier import analyze
    state = dict(H.waiting('Так установлено Налоговым кодексом, статья 88.', 'Дальше.'))
    decision = analyze('так установлено налоговым кодексом статья восемьдесят восемь а в каком году приняли первую часть налогового кодекса', state, [])
    assert decision.reason != 'question_over_owner_words' or decision.question.startswith('в каком'), decision
