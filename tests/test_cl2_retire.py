"""CL2, ruling 1 (second half): the controller's own retire of a superseded answer is not the listener's «стоп».

ControlledMedia retires the answer being dictated the moment a new question is accepted. It used to do that by saying «стоп» to the
engine, so the engine had to guess from the text. Now ``EchoEngine.retire`` is an explicit path: the state is cleared exactly as the
stop used to clear it (a new revision, no portions, no provenance, the running generation cancelled) and the history entry says how far
the listener got: 'interrupted' while something is left unsaid, else 'complete'.
"""
import threading

import helpers_s6_ack as H
from echo_sync.engine import EchoEngine, SILENT
from engine_say import engine_reply

A = 'Один два три. Четыре пять шесть. Семь восемь девять.'
A_PORTIONS = ['Один два три.', 'Четыре пять шесть.', 'Семь восемь девять.']


def engine(tmp_path, answer=A):
    clock = H.FakeClock(100.0)
    return EchoEngine(tmp_path / 'retire.sqlite3', lambda *args: answer, settings={'words_per_portion': 3}, clock=clock)


def say(e, text, tid):
    return engine_reply(e, session_id='s', turn_id=tid, text=text, request={}, model='m')


def test_a_retire_clears_the_answer_and_records_it_interrupted_where_the_listener_was(tmp_path):
    e = engine(tmp_path)
    say(e, 'Что такое счёт?', 'q')
    say(e, 'Один два три', 'ack')
    revision = e.state('s')['revision']
    closed = e.retire('s', 'new_question')
    state = e.state('s')
    assert (state['revision'], state['answer'], state['chunks'], state['completed'], state['pending_turn']) == \
           (revision + 1, '', [], True, None)
    entry = state['history'][-1]
    assert (entry['status'], entry['spoken'], entry['chunks']) == ('interrupted', 1, A_PORTIONS)
    assert closed == {'question': 'Что такое счёт?', 'spoken_text': 'Один два три.',
                      'unspoken_text': 'Четыре пять шесть. Семь восемь девять.'}
    assert say(e, 'повтори', 'again') == SILENT, 'nothing of a retired answer is spoken again'


def test_a_retire_of_an_answer_said_to_the_end_has_nothing_unfinished(tmp_path):
    e = engine(tmp_path)
    say(e, 'Что такое счёт?', 'q')
    for n, portion in enumerate(A_PORTIONS):
        say(e, portion, f'ack{n}')
    assert e.retire('s', 'new_question') is None
    assert e.state('s')['history'][-1]['status'] == 'complete'


def test_a_retire_without_a_session_is_harmless(tmp_path):
    assert engine(tmp_path).retire('nobody', 'new_question') is None


def test_a_retire_cancels_a_generation_that_is_still_running(tmp_path):
    started, release, tokens = threading.Event(), threading.Event(), []

    class Slow:
        def generate_cancellable(self, question, history, context, request, model, *, cancellation_event, is_current):
            tokens.append(cancellation_event)
            started.set()
            release.wait(5)
            return 'Этот ответ опоздал.'

    e = EchoEngine(tmp_path / 'slow.sqlite3', Slow())
    result = []
    worker = threading.Thread(target=lambda: result.append(say(e, 'Что такое счёт?', 'q')))
    worker.start()
    assert started.wait(2)
    e.retire('s', 'new_question')
    assert tokens[0].is_set(), 'the running generation was not cancelled'
    release.set()
    worker.join(5)
    assert result == [SILENT] and e.state('s')['answer'] == ''


def test_through_the_controller_a_new_question_retires_the_old_answer_as_interrupted_not_paused(tmp_path):
    d = H.Dictation(tmp_path / 'chain', A, question='Что такое счёт')
    d.say(d.current)                                   # one portion confirmed
    assert d.index == 1
    out = d.say('Что такое масса')
    assert out.types[:2] == ['cancel', 'route']
    state = d.state
    entry = state['history'][-1]
    assert (entry['question'], entry['status'], entry['spoken']) == ('Что такое счёт', 'interrupted', 1)
    assert not state.get('paused') and state['chunks'] == [] and state['completed']
