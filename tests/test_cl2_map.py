"""CL2, ruling 3: the conversation map lives in the engine state.

Every history entry (one per answered question) also records ``at`` (the engine clock when the answer was published), ``chunks`` (the
portions as dictated, streaming extensions included), ``spoken`` (how many portions the listener confirmed) and ``status`` ('active',
'complete', 'interrupted', 'paused', 'revised'). The state stays bounded, the model still sees only questions and answers, and
``conversation_map`` gives the recent entries as {question, status, spoken_text, unspoken_text}.

The pause / resume / retire updates are pinned with their rulings (tests/test_cl2_pause.py, test_cl2_resume.py).
"""
from pathlib import Path

import pytest

import helpers_s6_ack as H
from echo_sync.engine import EchoEngine, SILENT, conversation_map
from echo_sync.generator import StreamingAnswer
from engine_say import engine_reply

A_QUESTION, A = 'Что такое счёт?', 'Один два три. Четыре пять шесть. Семь восемь девять.'
A_PORTIONS = ['Один два три.', 'Четыре пять шесть.', 'Семь восемь девять.']
B_QUESTION, B = 'Что такое масса?', 'Масса мера инертности. Её измеряют в килограммах.'


class Session:
    """One text-route session: EchoEngine with a scripted generator and an injected clock."""

    def __init__(self, directory, answers=None, settings=None):
        self.clock = H.FakeClock(5000.0)
        self.answers = {A_QUESTION: A, B_QUESTION: B, **(answers or {})}
        self.calls = []

        def generate(question, history, context, request, model):
            self.calls.append((question, [dict(row) for row in history]))
            return self.answers[question]

        Path(directory).mkdir(parents=True, exist_ok=True)
        self.engine = EchoEngine(Path(directory) / 'map.sqlite3', generate, settings=settings or {'words_per_portion': 3},
                                 clock=self.clock)
        self.n = 0

    def say(self, text, gap=5.0):
        self.n += 1
        self.clock.advance(gap)
        return engine_reply(self.engine, session_id='s', turn_id=f't{self.n}', text=text, request={}, model='m')

    @property
    def state(self):
        return self.engine.state('s')

    @property
    def history(self):
        return self.state['history']


def test_a_published_answer_is_entered_with_its_time_portions_and_no_confirmation_yet(tmp_path):
    s = Session(tmp_path)
    assert s.say(A_QUESTION) == 'Один два три.'
    entry = s.history[-1]
    assert entry['at'] == 5005.0                       # the engine clock of the publication
    assert entry['chunks'] == A_PORTIONS
    assert (entry['spoken'], entry['status']) == (0, 'active')


def test_each_confirmation_counts_and_the_last_one_completes_the_entry(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    assert s.say('Один два три') == 'Четыре пять шесть.'
    assert (s.history[-1]['spoken'], s.history[-1]['status']) == (1, 'active')
    s.say('Четыре пять шесть')
    assert s.history[-1]['spoken'] == 2
    assert s.say('Семь восемь девять') == SILENT
    assert (s.history[-1]['spoken'], s.history[-1]['status']) == (3, 'complete')


def test_a_streaming_extension_is_part_of_the_entry(tmp_path):
    prefix, full = 'Первый второй третий', 'Первый второй третий четвёртый пятый шестой.'
    s = Session(tmp_path, answers={'Что такое ряд?': StreamingAnswer(prefix)})
    assert s.say('Что такое ряд?') == prefix
    assert s.history[-1]['chunks'] == [prefix]
    s.engine.extend_answer(session_id='s', revision=s.state['revision'], answer=full, final=True)
    assert s.history[-1]['chunks'] == [prefix, 'четвёртый пятый шестой.']


def test_a_new_question_leaves_the_old_answer_interrupted_where_the_listener_stopped(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say('Один два три')
    assert s.say(B_QUESTION) == 'Масса мера инертности.'
    old, new = s.history[-2], s.history[-1]
    assert (old['status'], old['spoken'], old['chunks']) == ('interrupted', 1, A_PORTIONS)
    assert (new['status'], new['question']) == ('active', B_QUESTION)


def test_an_answer_said_to_the_end_stays_complete_when_the_next_question_comes(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    for portion in A_PORTIONS:
        s.say(portion)
    s.say(B_QUESTION)
    assert (s.history[-2]['status'], s.history[-2]['spoken']) == ('complete', 3)


def test_an_answer_that_begins_with_a_correction_marks_the_previous_answer_revised(tmp_path):
    s = Session(tmp_path, answers={'Нет, это неверно, счёт начинается с нуля': 'Поправка: счёт начинается с нуля.'})
    s.say(A_QUESTION)
    s.say('Один два три')
    assert s.say('Нет, это неверно, счёт начинается с нуля').startswith('Поправка')
    assert s.history[-2]['status'] == 'revised'
    assert s.history[-1]['status'] == 'active'


def test_an_ordinary_next_answer_revises_nothing(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say(B_QUESTION)
    assert s.history[-2]['status'] == 'interrupted'


def test_the_history_keeps_twenty_entries_and_the_portions_of_the_newest_five(tmp_path):
    questions = {f'Что такое термин {n}?': f'Термин {n} это слово. Его значение простое.' for n in range(1, 26)}
    s = Session(tmp_path, answers=questions)
    for question in questions:
        s.say(question)
    history = s.history
    assert len(history) == 20
    assert [row['question'] for row in history] == list(questions)[-20:]
    assert all('chunks' in row for row in history[-5:])
    assert not any('chunks' in row for row in history[:-5])
    for row in history[:-5]:                             # what stays of an old entry
        assert {'question', 'answer', 'status', 'spoken', 'at'} <= set(row)


def test_the_model_sees_questions_and_answers_only(tmp_path):
    s = Session(tmp_path)
    s.say(A_QUESTION)
    s.say('Один два три')
    s.say(B_QUESTION)
    _, history = s.calls[-1]
    assert history == [{'question': A_QUESTION, 'answer': A}]


def test_a_stable_definition_asked_again_is_generated_again_the_engine_reuses_no_answer(tmp_path):
    """The engine keeps no answer-reuse path (it was a second owner of «answer again?» beside the cache): an identical repeat, even after the
    history was trimmed, is a new question for the model and a new revision."""
    questions = {f'что такое термин {n}': f'Это слово номер {n}. Его значение простое.' for n in range(1, 24)}
    s = Session(tmp_path, answers=questions)
    for question in questions:
        s.say(question)
    calls = len(s.calls)
    revision = s.state['revision']
    assert s.say('что такое термин 23') == 'Это слово номер'
    assert len(s.calls) == calls + 1, 'the same definition asked again must go to the model'
    assert s.state['revision'] == revision + 1 and s.state['chunk_index'] == 0


# ---- conversation_map ------------------------------------------------------------------------------------------------------------

def entry(question, chunks, spoken, status, at):
    return {'question': question, 'answer': ' '.join(chunks), 'chunks': list(chunks), 'spoken': spoken, 'status': status, 'at': at}


def test_the_map_splits_each_answer_into_what_was_said_and_what_was_not():
    state = {'history': [entry('Что такое счёт?', A_PORTIONS, 1, 'interrupted', 100.0),
                         entry('Что такое масса?', ['Масса мера', 'инертности.'], 2, 'complete', 200.0)]}
    rows = conversation_map(state, now=300.0, limit=3, window_s=600)
    assert rows == [{'question': 'Что такое счёт?', 'status': 'interrupted', 'spoken_text': 'Один два три.',
                     'unspoken_text': 'Четыре пять шесть. Семь восемь девять.'},
                    {'question': 'Что такое масса?', 'status': 'complete', 'spoken_text': 'Масса мера инертности.',
                     'unspoken_text': ''}]


def test_the_map_leaves_out_entries_older_than_the_window_and_keeps_the_newest_up_to_the_limit():
    state = {'history': [entry(f'Вопрос {n}', ['раз', 'два'], 1, 'interrupted', at) for n, at in
                         ((1, 0.0), (2, 1000.0), (3, 1100.0), (4, 1200.0), (5, 1300.0))]}
    rows = conversation_map(state, now=1500.0, limit=3, window_s=600)
    assert [row['question'] for row in rows] == ['Вопрос 3', 'Вопрос 4', 'Вопрос 5']
    assert [row['question'] for row in conversation_map(state, now=1500.0, limit=10, window_s=600)] == \
           ['Вопрос 2', 'Вопрос 3', 'Вопрос 4', 'Вопрос 5']
    assert conversation_map(state, now=99999.0, limit=3, window_s=600) == []


def test_the_map_hands_the_texts_whole_and_the_notes_cut_them():
    long_said = ['сказано' + str(n) for n in range(200)]
    state = {'history': [entry('вопрос ' * 100, long_said, 100, 'interrupted', 10.0)]}
    row = conversation_map(state, now=20.0, limit=3, window_s=600)[0]
    assert row['spoken_text'].endswith('сказано99') and row['unspoken_text'].startswith('сказано100') and len(row['question']) > 300


@pytest.mark.parametrize('history', [None, 'text', [None, 5, 'x'], [{'question': 'q', 'status': 'complete'}],
                                     [{'question': 'q', 'status': 'complete', 'at': 'yesterday'}]])
def test_the_map_of_an_old_or_odd_state_is_empty_rather_than_an_error(history):
    assert conversation_map({'history': history}, now=10.0, limit=3, window_s=600) == []
    assert conversation_map(None, now=10.0, limit=3, window_s=600) == []
