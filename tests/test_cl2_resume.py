"""CL2, ruling 4 + amendment A: going on - NEXT («дальше») and RESUME (return to the unclosed part).

* NEXT (amendment A, DEF-T-05; owner ruling QUESTION-T-06): «дальше», «далее», «следующая(ее)», «давай дальше» while a portion waits =
  one portion forward and the next portion cued, locally (a listener who cannot repeat a portion exactly has a way on). «продолжай» is
  NEXT only after an attempt at the portion; without one it says the portion again (ruling 4a: the interlocutor's «продолжайте» while the
  speaker hesitates helps, never cancels).
* RESUME (ruling 4): «продолжай», «доскажи», «закончи мысль», «на чём мы остановились», «вернёмся к прошлому вопросу»...
  a. an answer waits -> its current portion again;  b. the answer is paused -> its current portion again (ruling 1);
  c. nothing is active and the newest interrupted/paused entry is fresh (resume_window_s) -> its unspoken portions become the plan;
  d. nothing to resume -> the words go to the model as a question;  e. «вернёмся к <тема>» resumes an entry whose question shares a
  content stem with the topic, else it stays the question it is today.
  In every branch but (d) the model's own reply to the utterance is never dictated; quiet_reopen lets RESUME (and NEXT) present the stored
  position like a repeat.
"""
import pytest

import helpers_s6_ack as H
from echo_sync.classifier import NEXT, QUESTION, REPLAY, QUIET, RESUME, analyze
from echo_sync.engine import EchoEngine, SILENT
from echo_sync.timer_policy import CONVERSATION_CARRY_S
from echo_sync.generator import StreamingAnswer
from engine_say import engine_reply

A_QUESTION, A = 'Что такое счёт?', 'Один два три. Четыре пять шесть. Семь восемь девять.'
A_PORTIONS = ['Один два три.', 'Четыре пять шесть.', 'Семь восемь девять.']
B_QUESTION, B = 'Что такое масса?', 'Масса мера инертности. Её измеряют в килограммах.'
OTHER = 'Это ответ модели на просьбу продолжить.'


# ---- the words ------------------------------------------------------------------------------------------------------------------

NEXT_FORMS = ('Дальше.', 'далее', 'Следующая.', 'следующее', 'Следующую, пожалуйста.', 'Давай дальше.', 'Хорошо, дальше.', 'а дальше?',
              'ну дальше', 'Дальше, пожалуйста.', 'давайте дальше', 'Далее, далее.')
CONTINUE_FORMS = ('Продолжай.', 'продолжайте', 'Продолжи.', 'продолжите', 'Давай продолжим.', 'продолжаем', 'Доскажи.', 'договорите',
                  'Закончи мысль.', 'закончите ответ', 'Что там было дальше?', 'что было дальше', 'Ну продолжай, пожалуйста.')
# W1F-C (task-w1fix-briefs.md): «Return/position meta as clauses (… на чём/где (мы) (там) остановились|прервались|закончили; что было
# последним; с какого места; что ты последним сказал) inside longer utterances», and the W1 analysis (G4, w1_08 / w1_12): «POSITION/REPEAT
# alone → reissue the waiting portion». «На чём мы остановились?» is a position question now (``resume_position``): the waiting portion
# again, also after a try at it (a ``resume_continue`` would then move on to a portion nobody has confirmed).
POSITION_FORMS = ('На чём мы остановились?', 'на чем остановились')
RETURN_FORMS = ('Вернёмся к прошлому вопросу.', 'вернемся к предыдущему ответу', 'Вернись к тому вопросу.', 'Давай вернёмся к прошлому вопросу.',
                'А что там с прошлым вопросом?', 'а что с предыдущим вопросом', 'Вернёмся к тому, что ты говорил раньше.',
                'Вернёмся к тому, о чём вы рассказывали.')
RETURN_FIRST_FORMS = ('Вернёмся к первому вопросу.', 'А что с первым вопросом?')
STILL_OTHER = ('Продолжай рассказывать про инерцию', 'давай дальше разберём этот пример подробно', 'Дальше будет интереснее',
               'не стоп а продолжай говорить дальше', 'дальше не надо', 'Вернёмся к инерции', 'Следующая станция Маяковская',
               'что дальше делать с этим законом')
WAITS = H.waiting('Масса мера инертности', 'тела.')


@pytest.mark.parametrize('settings', [H.PROD_SETTINGS], ids=['controlled'])
@pytest.mark.parametrize('text', NEXT_FORMS)
def test_the_next_forms_are_next(text, settings):
    assert analyze(text, WAITS, [], settings).kind == NEXT, text


@pytest.mark.parametrize('settings', [H.PROD_SETTINGS], ids=['controlled'])
@pytest.mark.parametrize('text', CONTINUE_FORMS)
def test_the_continue_forms_are_a_resume(text, settings):
    decision = analyze(text, WAITS, [], settings)
    assert (decision.kind, decision.reason) == (RESUME, 'resume_continue'), (text, decision)
    assert decision.question == text.strip(), 'the words as said: (d) hands them to the model'


@pytest.mark.parametrize('settings', [H.PROD_SETTINGS], ids=['controlled'])
@pytest.mark.parametrize('text', POSITION_FORMS)
def test_the_position_forms_are_a_resume_that_says_the_portion_again(text, settings):
    decision = analyze(text, WAITS, [], settings)
    assert (decision.kind, decision.reason) == (RESUME, 'resume_position'), (text, decision)
    assert decision.question == text.strip(), 'the words as said: (d) hands them to the model'


@pytest.mark.parametrize('text', RETURN_FORMS)
def test_the_return_forms_are_a_resume_to_an_earlier_answer(text):
    decision = analyze(text, WAITS, [], H.PROD_SETTINGS)
    assert (decision.kind, decision.reason) == (RESUME, 'resume_return'), (text, decision)


@pytest.mark.parametrize('text', RETURN_FIRST_FORMS)
def test_the_return_to_the_first_question(text):
    assert analyze(text, WAITS, [], H.PROD_SETTINGS).reason == 'resume_return_first'


@pytest.mark.parametrize('state', [WAITS, None], ids=['waiting', 'idle'])
@pytest.mark.parametrize('text', STILL_OTHER)
def test_a_longer_request_or_a_sentence_with_those_words_stays_what_it_was(text, state):
    """At most a few words, a closed list: «продолжай рассказывать про инерцию» is not a RESUME, «дальше будет интереснее» is no NEXT;
    «вернёмся к инерции» stays the topic change it is today (ruling 4e is decided against the conversation map, not by the words)."""
    assert analyze(text, state, [], H.PROD_SETTINGS).kind not in (NEXT, RESUME), text


@pytest.mark.parametrize('settings', [H.PROD_SETTINGS], ids=['controlled'])
def test_a_next_word_that_is_part_of_the_portion_is_an_attempt_at_it(settings):
    waits = H.waiting('Дальше будет больше', 'тела.')
    assert analyze('Дальше', waits, [], settings).kind in (REPLAY, QUIET)
    waits = H.waiting('Продолжайте наблюдение', 'тела.')
    assert analyze('продолжайте', waits, [], settings).kind in (REPLAY, QUIET)


# ---- the engine (the text route) ------------------------------------------------------------------------------------------------

class Session:
    """EchoEngine with a scripted generator and an injected clock (resume_window_s comes from the settings)."""

    def __init__(self, directory, settings=None, answer=None):
        self.clock = H.FakeClock(5000.0)
        self.calls = []

        def generate(question, history, context, request, model):
            self.calls.append(question)
            if answer is not None:
                return answer
            return {A_QUESTION: A, B_QUESTION: B}.get(question, OTHER)

        directory.mkdir(parents=True, exist_ok=True)
        self.engine = EchoEngine(directory / 'resume.sqlite3', generate, settings={'words_per_portion': 3, **(settings or {})},
                                 clock=self.clock)
        self.n = 0

    def say(self, text, gap=5.0):
        self.n += 1
        self.clock.advance(gap)
        return engine_reply(self.engine, session_id='s', turn_id=f't{self.n}', text=text, request={}, model='m')

    @property
    def state(self):
        return self.engine.state('s')

    def entry(self, question):
        return [e for e in self.state['history'] if e['question'] == question][-1]

    def to_the_end(self):
        """Confirm every portion that is left."""
        while not self.state['completed']:
            self.say(self.state['chunks'][self.state['chunk_index']])


def test_next_moves_one_portion_forward_and_speaks_the_next(tmp_path):
    s = Session(tmp_path)
    assert s.say(A_QUESTION) == A_PORTIONS[0]
    assert s.say('Дальше.') == A_PORTIONS[1]
    assert s.say('далее') == A_PORTIONS[2]
    assert s.say('следующая') == SILENT, 'NEXT on the last portion completes the answer'
    assert s.state['completed'] and s.entry(A_QUESTION)['status'] == 'complete'
    assert s.calls == [A_QUESTION], 'no model call'


def test_next_at_the_frontier_of_a_stream_waits_for_the_text_like_a_repeat(tmp_path):
    prefix = 'Первый второй третий'
    s = Session(tmp_path, answer=StreamingAnswer(prefix))
    assert s.say('Что такое ряд?') == prefix
    revision = s.state['revision']
    assert s.say('дальше') == SILENT and s.state['stream_waiting_next']
    assert s.say('дальше') == SILENT, 'a second NEXT at the frontier consumes nothing'
    assert s.engine.extend_answer(session_id='s', revision=revision, answer=prefix + ' четвёртый пятый шестой.', final=True) == \
        'четвёртый пятый шестой.'


def test_continue_says_the_portion_again_without_an_attempt_and_moves_on_after_one(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    assert s.say('Продолжай.') == A_PORTIONS[0], 'no attempt yet: the portion again (ruling 4a)'
    assert s.say('Один два') == A_PORTIONS[0]                 # a partial try (replay_if_attempt says it again)
    assert s.say('Продолжай.') == A_PORTIONS[1], 'after an attempt «продолжай» is NEXT (ruling QUESTION-T-06)'
    assert s.say('продолжай') == A_PORTIONS[1], 'the attempt was at the previous portion: this one is said again'


def test_the_other_continue_forms_say_the_waiting_portion_again(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    for text in ('Доскажи.', 'Закончи мысль.', 'На чём мы остановились?'):
        assert s.say(text) == A_PORTIONS[1], text
    assert s.state['chunk_index'] == 1 and s.calls == [A_QUESTION]


def test_after_a_pause_next_and_continue_bring_the_paused_portion_not_the_one_after(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    s.say('стоп')
    assert s.say('Дальше.') == A_PORTIONS[1], 'the paused portion was cut: it is said again (ruling 4b / ruling 1)'
    assert not s.state.get('paused') and s.state['chunk_index'] == 1
    s.say('стоп')
    assert s.say('продолжай') == A_PORTIONS[1]


def test_continue_after_an_interruption_restores_the_unspoken_part_of_the_answer(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])                                          # one portion confirmed
    s.say(B_QUESTION)                                             # B interrupts A
    s.to_the_end()                                                # B is dictated to the end
    assert s.entry(A_QUESTION)['status'] == 'interrupted'
    assert s.say('Продолжай.') == A_PORTIONS[1], 'A comes back at its first unconfirmed portion'
    state = s.state
    assert (state['chunks'], state['chunk_index'], state['completed']) == (A_PORTIONS[1:], 0, False)
    assert s.entry(A_QUESTION)['status'] == 'active' and s.entry(A_QUESTION)['spoken'] == 1
    assert s.say(A_PORTIONS[1]) == A_PORTIONS[2]
    assert s.entry(A_QUESTION)['spoken'] == 2
    assert s.say(A_PORTIONS[2]) == SILENT and s.state['completed']
    assert (s.entry(A_QUESTION)['status'], s.entry(A_QUESTION)['spoken']) == ('complete', 3)
    assert s.calls == [A_QUESTION, B_QUESTION], 'the return made no model call'


def test_a_return_form_while_another_answer_waits_interrupts_it_and_brings_the_earlier_one_back(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    b_first = s.say(B_QUESTION)
    assert s.say('Вернёмся к прошлому вопросу.') == A_PORTIONS[1]
    assert (s.entry(B_QUESTION)['status'], s.entry(B_QUESTION)['spoken']) == ('interrupted', 0)
    assert s.say('Вернёмся к прошлому вопросу.') == b_first, 'and back again: B is now the unfinished one'
    assert s.calls == [A_QUESTION, B_QUESTION]


def test_continue_while_another_answer_waits_goes_on_with_that_answer(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    b_first = s.say(B_QUESTION)
    assert s.say('Продолжай.') == b_first, 'ruling 4a: the waiting answer is the one that goes on'


def test_an_unfinished_answer_older_than_the_window_is_not_resumed_the_words_go_to_the_model(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    s.say(B_QUESTION)
    s.to_the_end()
    s.clock.advance(CONVERSATION_CARRY_S + 1)      # 6.04 resume_next_day always on (bcc98bdd): an explicit «продолжай» reaches back 36 h, the window of 60 s is for the other words
    assert s.say('Продолжай.') != A_PORTIONS[1]
    assert s.calls[-1] == 'Продолжай.', '(d): the words as said are the question to the model'
    assert s.entry(A_QUESTION)['status'] == 'interrupted', 'the stale entry is left as it was'


def test_continue_after_a_complete_answer_asks_the_model_to_say_more(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.to_the_end()
    s.say('продолжай')
    assert s.calls == [A_QUESTION, 'продолжай']


def test_with_nothing_said_yet_next_and_continue_stay_silent(tmp_path):
    s = Session(tmp_path)
    assert s.say('Дальше.') == SILENT and s.say('Продолжай.') == SILENT
    assert s.calls == []


@pytest.mark.parametrize('topic', ['Вернёмся к счёту.', 'вернемся к вопросу про счёт'])
def test_a_return_to_a_topic_resumes_the_unfinished_answer_about_it(tmp_path, topic):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    s.say(B_QUESTION)
    s.to_the_end()
    assert s.say(topic) == A_PORTIONS[1]
    assert s.calls == [A_QUESTION, B_QUESTION]


def test_a_return_to_another_topic_stays_a_question_for_the_model(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    s.say(B_QUESTION)
    s.to_the_end()
    s.say('Вернёмся к погоде.')
    assert s.calls[-1] in ('Вернёмся к погоде.', 'вернёмся к погоде.'), s.calls


def test_the_first_question_is_the_oldest_unfinished_one(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    s.say(B_QUESTION)                                             # A interrupted after one portion
    s.say('Что такое вес?')                                       # B interrupted before its first confirmation
    s.to_the_end()
    assert s.say('Вернёмся к первому вопросу.') == A_PORTIONS[1]


# ---- through ControlledMedia, as the host builds it --------------------------------------------------------------------------------

REPLY = 'Конечно, продолжаю. Итак, это было про инерцию и массу.'


def test_through_the_controller_the_interlocutor_s_continue_says_the_portion_again_and_cancels_nothing(tmp_path):
    d = H.Dictation(tmp_path / 'continue', H.LONG_ANSWERS[0])
    d.say(d.current)
    waiting = d.current
    out = d.say('Продолжайте.')
    assert out.speaks == [waiting] and out.after == out.before
    assert out.model_calls == 0 and not out.destroyed, out.actions
    assert d.deliver(H.done('reply-continue', 'assistant', REPLY)).actions == [], 'the model\'s reply to «продолжайте» was dictated'


def test_through_the_controller_next_moves_on_without_the_cloud(tmp_path):
    d = H.Dictation(tmp_path / 'next', H.LONG_ANSWERS[0])
    chunks = d.chunks
    out = d.say('Дальше.')
    assert out.after == out.before + 1 and out.speaks == [chunks[1]]
    assert out.model_calls == 0 and not out.destroyed, out.actions
    assert d.deliver(H.done('reply-next', 'assistant', 'Хорошо, дальше. ' + REPLY)).actions == []


def test_through_the_controller_continue_after_an_attempt_moves_on(tmp_path):
    d = H.Dictation(tmp_path / 'attempt', H.LONG_ANSWERS[0])
    chunks = d.chunks
    first = chunks[0].split()
    d.say(' '.join(first[:max(1, len(first) - 1)]))              # a partial try: held
    assert d.index == 0
    out = d.say('Продолжай.')
    assert out.after == 1 and out.speaks == [chunks[1]], out.actions


def test_through_the_controller_a_paused_answer_resumes_on_continue_and_the_reply_is_never_spoken(tmp_path):
    d = H.Dictation(tmp_path / 'paused', H.LONG_ANSWERS[0])
    d.say(d.current)
    waiting = d.current
    d.say('Стоп.')
    out = d.say('Продолжай.')
    assert out.speaks == [waiting] and out.model_calls == 0
    assert d.deliver(H.done('reply-paused', 'assistant', REPLY)).actions == []


def test_through_the_controller_a_return_restores_the_interrupted_answer_and_the_reply_is_never_spoken(tmp_path):
    d = H.Dictation(tmp_path / 'return', A, question=A_QUESTION.rstrip('?'))
    a_chunks = d.chunks
    d.say(a_chunks[0])
    asked = d.say(B_QUESTION.rstrip('?'))
    assert asked.types[:2] == ['cancel', 'route']
    answer = d.deliver(H.done('a2', 'assistant', B))
    d.play(answer.actions)
    while not d.completed:
        d.say(d.current)
    back = d.say('Вернёмся к прошлому вопросу.')
    assert back.types == ['cancel', 'speak'] and back.speaks == [a_chunks[1]], back.actions
    assert back.model_calls == 0
    assert d.controller.authorized(back.actions[-1])
    assert d.deliver(H.done('reply-return', 'assistant', 'Конечно. Мы говорили о счёте: один два три.')).actions == []
    assert d.say(a_chunks[1]).speaks == [a_chunks[2]]
    d.say(a_chunks[2])
    assert d.completed and d.state['history'][-2]['status'] == 'complete'


def test_through_the_controller_nothing_to_resume_makes_the_words_a_question_and_its_answer_is_dictated(tmp_path):
    d = H.Dictation(tmp_path / 'say-more', H.ANSWERS[0])
    while not d.completed:
        d.say(d.current)
    out = d.say('Продолжай.')
    assert out.types[:2] == ['cancel', 'route'], out.actions
    answer = d.deliver(H.done('more', 'assistant', 'Добавлю ещё одну мысль.'))
    assert [a['type'] for a in answer.actions] == ['speak']


def test_in_a_reopened_call_next_and_continue_present_the_stored_position(tmp_path):
    d = H.Dictation(tmp_path / 'reopen', H.LONG_ANSWERS[0])
    d.say(d.current)
    stored = d.current
    r = d.reconnect()
    out = r.say('Дальше.')
    assert out.speaks == [stored] and out.after == out.before, 'a new call presents the stored portion, it never skips it'
    assert r.say('Дальше.').after == out.before + 1, 'once presented, NEXT moves on'
    r2 = r.reconnect()
    assert r2.say('Продолжай.').speaks == [r2.current]
