"""CL2, ruling 1: the listener's «стоп» is a PAUSE, not a reset.

Measured on bf76690 (sc06): «Стоп, пожалуйста.» then «Ещё раз.» gave no audio, because the engine's STOP emptied the answer. Now the
sound is cut at once (as before) and the plan is kept: the portions and the cursor stay, the answer is marked paused, and nothing is
spoken until an explicit repeat request («повтори», «ещё раз», «как?»), a request to go on (ruling 4), a repeat of the paused portion,
or a new question. The silence timer and the missing-answer watchdog leave a paused answer alone.
"""
import threading

import helpers_s6_ack as H
from echo_sync.engine import EchoEngine, SILENT
from echo_sync.generator import StreamingAnswer
from engine_say import engine_reply

A = 'Один два три. Четыре пять шесть. Семь восемь девять.'
A_PORTIONS = ['Один два три.', 'Четыре пять шесть.', 'Семь восемь девять.']


class Text:
    """The text route: EchoEngine with the classic settings (replay_if_attempt) and an injected clock."""

    def __init__(self, tmp_path, answer=A, **settings):
        self.clock = H.FakeClock(100.0)
        self.calls = []

        def generate(*args):
            self.calls.append(args)
            return answer

        self.engine = EchoEngine(tmp_path / 'pause.sqlite3', generate, settings={'words_per_portion': 3, **settings},
                                 clock=self.clock)
        self.n = 0

    def say(self, text):
        self.n += 1
        self.clock.advance(5)
        return engine_reply(self.engine, session_id='s', turn_id=f't{self.n}', text=text, request={}, model='m')

    @property
    def state(self):
        return self.engine.state('s')


def test_stop_keeps_the_portions_and_the_cursor_and_marks_the_answer_paused(tmp_path):
    t = Text(tmp_path)
    t.say('Что такое счёт?')
    t.say('Один два три')
    assert t.say('стоп') == SILENT
    state = t.state
    assert (state['chunks'], state['chunk_index'], state['completed']) == (A_PORTIONS, 1, False)
    assert state['paused'] is True
    assert state['history'][-1]['status'] == 'paused' and state['history'][-1]['spoken'] == 1
    assert EchoEngine.current(state) == SILENT, 'a paused answer must not be repeated by the silence timer'


def test_a_repeat_request_after_a_pause_speaks_the_current_portion_and_ends_the_pause(tmp_path):
    t = Text(tmp_path)
    t.say('Что такое счёт?')
    t.say('Один два три')
    t.say('Стоп, пожалуйста.')
    assert t.say('Ещё раз.') == 'Четыре пять шесть.'
    assert not t.state.get('paused') and t.state['chunk_index'] == 1
    assert t.state['history'][-1]['status'] == 'active'
    assert len(t.calls) == 1, 'no model call'


def test_how_after_a_pause_is_an_explicit_request_too(tmp_path):
    t = Text(tmp_path)
    t.say('Что такое счёт?')
    t.say('стоп')
    assert t.say('как?') == 'Один два три.'
    assert len(t.calls) == 1 and t.state['revision'] >= 1 and not t.state.get('paused'), 'the paused portion, not a new answer'


def test_an_attempt_or_noise_does_not_end_the_pause(tmp_path):
    t = Text(tmp_path)
    t.say('Что такое счёт?')
    t.say('стоп')
    assert t.say('Один два') == SILENT                       # a partial try: under replay_if_attempt it would replay
    assert t.say('ну') == SILENT
    assert t.state['paused'] is True


def test_the_paused_portion_said_in_full_goes_on_to_the_next(tmp_path):
    t = Text(tmp_path)
    t.say('Что такое счёт?')
    t.say('стоп')
    assert t.say('Один два три') == 'Четыре пять шесть.'
    assert not t.state.get('paused') and t.state['chunk_index'] == 1


def test_a_new_question_after_a_pause_works_as_before_and_the_paused_answer_is_interrupted(tmp_path):
    t = Text(tmp_path)
    t.say('Что такое счёт?')
    t.say('Один два три')
    t.say('стоп')
    assert t.say('Что такое масса?') == 'Один два три.'
    assert len(t.calls) == 2
    assert (t.state['history'][-2]['status'], t.state['history'][-2]['spoken']) == ('interrupted', 1)
    assert not t.state.get('paused')


def test_stop_while_the_answer_is_being_made_still_cancels_it(tmp_path):
    started, release, tokens = threading.Event(), threading.Event(), []

    class Slow:
        def generate_cancellable(self, question, history, context, request, model, *, cancellation_event, is_current):
            tokens.append(cancellation_event)
            started.set()
            release.wait(5)
            return A

    e = EchoEngine(tmp_path / 'slow.sqlite3', Slow())
    result = []
    worker = threading.Thread(target=lambda: result.append(
        engine_reply(e, session_id='s', turn_id='q', text='Что такое счёт?', request={}, model='m')))
    worker.start()
    assert started.wait(2)
    assert engine_reply(e, session_id='s', turn_id='stop', text='стоп', request={}, model='m') == SILENT
    assert tokens[0].is_set()
    release.set()
    worker.join(5)
    assert result == [SILENT] and e.state('s')['chunks'] == [] and not e.state('s').get('paused')


def test_stop_keeps_an_open_stream_open_and_what_arrives_waits_for_the_resume(tmp_path):
    """Coordinator ruling (W1F-B, 3 Nov 2026), binding: «under CL2 ruling 1 «стоп» is a PAUSE that keeps the plan. Consistently, text of
    the CURRENT answer that has already arrived when the user pauses — published or not yet published — and text of the same answer that
    keeps arriving after the pause are kept in the plan (never spoken while paused; spoken from the paused portion on «продолжай / ещё
    раз / повтори» or by a resume). Only a NEW question (internal retire) discards the old answer's tail.»
    Until then the pause closed the stream where its published text ended and refused what came after it."""
    prefix = 'Первый второй третий'
    t = Text(tmp_path, answer=StreamingAnswer(prefix))
    assert t.say('Что такое ряд?') == prefix
    t.say('стоп')
    state = t.state
    assert state['paused'] and state.get('streaming') and state['chunks'] == [prefix]
    revision = state['revision']                                # the stop's revision
    assert t.engine.extend_answer(session_id='s', revision=revision, answer=prefix + ' четвёртый.', final=True) == SILENT
    assert t.state['paused'] and t.state['chunks'] == [prefix, 'четвёртый.'], 'kept in the plan, never spoken while paused'
    assert t.say('повтори') == prefix                           # the resume speaks from the paused portion on
    assert t.say(prefix) == 'четвёртый.'


def test_stop_at_the_frontier_of_an_open_stream_waits_for_the_rest_and_says_nothing(tmp_path):
    """Coordinator ruling (W1F-B, 3 Nov 2026), binding: «under CL2 ruling 1 «стоп» is a PAUSE that keeps the plan. Consistently, text of
    the CURRENT answer that has already arrived when the user pauses — published or not yet published — and text of the same answer that
    keeps arriving after the pause are kept in the plan (never spoken while paused; spoken from the paused portion on «продолжай / ещё
    раз / повтори» or by a resume). Only a NEW question (internal retire) discards the old answer's tail.»
    Until then a stop at the frontier of an open stream completed the answer there. Now the answer waits paused at its frontier: text
    that arrives is the paused portion (never spoken until the resume); a stream that ends with nothing more completes it."""
    prefix = 'Первый второй третий'
    t = Text(tmp_path, answer=StreamingAnswer(prefix))
    t.say('Что такое ряд?')
    t.say(prefix)                                            # the frontier: everything published is confirmed
    assert t.state['stream_waiting_next']
    t.say('стоп')
    assert t.state['paused'] and not t.state['completed'] and t.state.get('streaming')
    revision = t.state['revision']
    assert t.engine.extend_answer(session_id='s', revision=revision, answer=prefix + ' четвёртый пятый.') == SILENT
    assert t.state['paused'] and t.state['chunk_index'] == 1 and not t.state.get('stream_waiting_next')
    assert t.engine.extend_answer(session_id='s', revision=revision, answer=prefix + ' четвёртый пятый.', final=True) == SILENT
    assert t.say('продолжай') == 'четвёртый пятый.'           # the resume speaks the portion that arrived while paused
    assert t.say('четвёртый пятый.') == SILENT and t.state['completed']
    assert t.state['history'][-1]['status'] == 'complete'


def test_stop_at_the_frontier_completes_the_answer_when_its_stream_ends_with_nothing_more(tmp_path):
    prefix = 'Первый второй третий'
    t = Text(tmp_path, answer=StreamingAnswer(prefix))
    t.say('Что такое ряд?')
    t.say(prefix)
    t.say('стоп')
    assert t.engine.extend_answer(session_id='s', revision=t.state['revision'], answer=prefix, final=True) == SILENT
    assert t.state['completed']
    assert t.state['history'][-1]['status'] == 'complete'


# ---- through ControlledMedia, as the host builds it ------------------------------------------------------------------------------

def test_through_the_controller_stop_is_silence_with_no_auto_repeat_and_no_watchdog_then_once_more_brings_the_portion(tmp_path):
    d = H.Dictation(tmp_path / 'pause', H.LONG_ANSWERS[0])
    d.say(d.current)                                         # one portion confirmed: the second waits
    waiting, index, chunks = d.current, d.index, d.chunks
    out = d.say('Стоп, пожалуйста.')
    assert out.types == ['cancel'] and out.speaks == [] and out.model_calls == 0
    assert (d.index, d.chunks, d.state.get('paused')) == (index, chunks, True)
    assert all(not d.controller.authorized(cue) for cue in d.cues), 'audio of the paused answer is still authorized'
    for _ in range(40):                                      # 200 s of silence
        d.clock.advance(5)
        assert d.controller.tick(now=d.clock()) == [], 'a paused answer was repeated or reported as unanswered'
    again = d.say('Ещё раз.')
    assert again.speaks == [waiting] and again.after == index and again.model_calls == 0
    following = d.say(waiting)
    assert following.after == index + 1 and following.speaks == [d.current]


def test_through_the_controller_the_resumed_portion_is_authorized_audio(tmp_path):
    d = H.Dictation(tmp_path / 'pause-auth', H.LONG_ANSWERS[0])
    d.say('стоп')
    again = d.say('повтори', play=False)
    cue = [a for a in again.actions if a['type'] == 'speak']
    assert len(cue) == 1 and d.controller.authorized(cue[0])


def test_through_the_controller_a_new_question_after_a_pause_works_as_before(tmp_path):
    d = H.Dictation(tmp_path / 'pause-question', H.LONG_ANSWERS[0])
    d.say(d.current)
    d.say('стоп')
    asked = d.say('Что такое масса')
    assert asked.types[:2] == ['cancel', 'route']
    answer = d.deliver(H.done('a2', 'assistant', 'Масса — это мера инертности тела.'))
    assert [a['type'] for a in answer.actions] == ['speak']
    assert d.state['history'][-2]['status'] == 'interrupted' and d.state['history'][-2]['spoken'] == 1
