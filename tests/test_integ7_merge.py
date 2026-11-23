"""INTEG7: where Task E3c (the cloud's restarts and rewrites, ``EchoEngine.revise``, the 30 s post-publication watchdog) meets Task CL2
(the conversation map, «стоп» as a pause, the quiet progress notes). Coordinator rulings 1-2 of the INTEG7 brief.

1. ``EchoEngine.revise`` keeps the conversation map in sync exactly like ``extend_answer`` does: the entry holds the portions as they will
   be dictated, ``spoken`` and the status follow the listener, and the state is read with ``_read_state`` (a damaged row is set aside).
   Without it a revised answer that is interrupted and resumed («Вернёмся к прошлому вопросу») would dictate the text the cloud withdrew.
2. A pause never brings E3c's post-publication watchdog phrase, and a reply the cloud makes to a quiet note is never taken by E3c's restart
   alignment for a restart of the current answer.

The engine tests drive the real EchoEngine over SQLite; the controller tests drive the real ControlledMedia built with the production keywords
of controlled_host.serve, with the transport's CL2 hook (``note_actions`` after every
event and tick, as native_media_socket does), on an injected clock. No network, no TTS, no server.
"""
import json
import sqlite3

import pytest

import helpers_s6_ack as H
from echo_sync.classifier import waiting_portion
from echo_sync.engine import SILENT, EchoEngine
from echo_sync.generator import StreamingAnswer
from test_first_cue_never_silent import created, delta, done
from test_task1_review_round2 import ORIGIN, Session
from engine_say import engine_reply

# --- 1. EchoEngine.revise and the conversation map -----------------------------------------------------------------------------------

A_QUESTION, A = 'Что такое счёт?', 'Один два три. Четыре пять шесть. Семь восемь девять.'
A_PORTIONS = ['Один два три.', 'Четыре пять шесть.', 'Семь восемь девять.']
B_QUESTION, B = 'Что такое масса?', 'Масса мера инертности. Её измеряют в килограммах.'


class Text:
    """One text-route session: EchoEngine with a scripted generator (A streams, its stream left open) and an injected clock."""

    def __init__(self, directory):
        self.clock = H.FakeClock(5000.0)
        self.answers = {A_QUESTION: lambda: StreamingAnswer(A, [], final=False, retrieval_status='unverified'), B_QUESTION: lambda: B}
        self.engine = EchoEngine(directory / 'map.sqlite3', lambda question, *rest: self.answers[question](),
                                 settings={'words_per_portion': 3}, clock=self.clock)
        self.n = 0

    def say(self, text, gap=2.0):
        self.n += 1
        self.clock.advance(gap)
        return engine_reply(self.engine, session_id='s', turn_id=f't{self.n}', text=text, request={}, model='m')

    @property
    def state(self):
        return self.engine.state('s')

    def entry(self):
        state = self.state
        return state['history'][state['entry']]


def test_a_revision_of_the_stream_is_what_its_map_entry_holds(tmp_path):
    t = Text(tmp_path)
    assert t.say(A_QUESTION) == 'Один два три.'
    assert t.say('Один два три') == 'Четыре пять шесть.'
    reply, _, answer = t.engine.revise(session_id='s', revision=t.state['revision'], keep=1,
                                       tail='Десять одиннадцать двенадцать. Тринадцать четырнадцать.', final=False)
    state, entry = t.state, t.entry()
    assert entry['chunks'] == state['chunks'] and state['chunks'][0] == 'Один два три.', (entry, state['chunks'])
    assert 'Четыре пять шесть.' not in entry['chunks'], 'the entry still holds the portions the revision replaced'
    assert (entry['spoken'], entry['status'], entry['answer']) == (1, 'active', answer)


def test_an_answer_revised_with_a_correction_resumes_with_the_correction_never_with_the_withdrawn_text(tmp_path):
    """The listener confirmed the first portion; the cloud's rewrite became «Поправка: …» (E3c); a new question interrupts it; «Вернёмся к
    прошлому вопросу» (CL2) restores its unspoken part: that part is the correction, never «Четыре пять шесть», which the cloud withdrew."""
    t = Text(tmp_path)
    t.say(A_QUESTION)
    t.say('Один два три')
    reply, _, _ = t.engine.revise(session_id='s', revision=t.state['revision'], keep=1, tail='Поправка: десять одиннадцать двенадцать.',
                                  final=True)
    assert reply.startswith('Поправка'), reply
    assert t.say(B_QUESTION) == 'Масса мера инертности.'
    old = t.state['history'][-2]
    assert old['status'] == 'interrupted' and old['spoken'] == 1 and old['chunks'][1].startswith('Поправка'), old
    resumed = t.say('Вернёмся к прошлому вопросу')
    assert resumed.startswith('Поправка'), resumed


def test_a_revision_that_ends_the_answer_at_the_frontier_completes_its_entry(tmp_path):
    t = Text(tmp_path)
    t.say(A_QUESTION)
    for portion in A_PORTIONS:
        t.say(portion)
    assert t.state['stream_waiting_next'] and (t.entry()['spoken'], t.entry()['status']) == (3, 'active')
    assert t.engine.revise(session_id='s', revision=t.state['revision'], keep=3, tail='', final=True)[0] == SILENT
    assert t.state['completed'] and (t.entry()['spoken'], t.entry()['status']) == (3, 'complete')


def test_revise_refuses_a_stream_that_is_closed_as_extend_answer_does(tmp_path):
    """«None when the state is not the open stream this revision was made for» (revise's contract): a correction ends the answer
    (final), and a closed stream takes nothing more - no extension and no revision (CL2 sends its quiet notes only then: ``_note_safe``)."""
    t = Text(tmp_path)
    t.say(A_QUESTION)
    t.say('Один два три')
    _, revision, _ = t.engine.revise(session_id='s', revision=t.state['revision'], keep=1, tail='Поправка: десять одиннадцать двенадцать.',
                                     final=True)
    before = t.state
    assert not before['streaming'] and not before['completed'], before
    assert t.engine.extend_answer(session_id='s', revision=revision, answer=before['answer'] + ' Тринадцать.', final=True) is None
    assert t.engine.revise(session_id='s', revision=revision, keep=2, tail='Тринадцать четырнадцать.', final=False) is None
    assert t.state == before


def test_revise_reads_the_state_as_every_engine_call_does_a_damaged_row_is_set_aside(tmp_path):
    t = Text(tmp_path)
    t.say(A_QUESTION)
    revision = t.state['revision']
    with sqlite3.connect(str(tmp_path / 'map.sqlite3')) as db:
        db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(t.state)[:40], 's'))
    assert t.engine.revise(session_id='s', revision=revision, keep=0, tail='Десять одиннадцать.', final=True) is None
    assert t.state is None, 'the damaged row is set aside: the session starts clean'


# --- 2. the pause and the quiet notes against E3c's watchdog and restart alignment -------------------------------------------------------

class Wire(Session):
    """``Session`` plus what the transport does for CL2: ``note_actions`` after every
    event and every tick (``notes`` = [(seconds, text)]); ``log`` = [(seconds, action)] of every action. ``repeat``: the listener repeats
    the cue that is current then (if a portion waits for them)."""

    def __init__(self, tmp_path, **overrides):
        super().__init__(tmp_path, **overrides)
        self.c.engine.clock = self.clock           # the map's times follow the injected clock too
        self.notes, self.log, self.said = [], [], {}

    def feed(self, event):
        return self.c.provider(event)

    def user(self, at, tid, text, length=0.6):
        self.at(at, lambda s: s.feed(created(tid, 'user', text.split()[0])))
        self.at(at + length, lambda s: s.feed(done(tid, 'user', text)))

    def repeat(self, at, tid, length=1.2):
        def begin(s):
            if waiting_portion(s.c.state()) is None or not s.cues:
                return []
            s.said[tid] = s.cues[-1][1]
            return s.feed(created(tid, 'user', s.said[tid].split()[0]))
        self.at(at, begin)
        self.at(at + length, lambda s: s.feed(done(tid, 'user', s.said[tid])) if tid in s.said else [])

    def until(self, seconds):
        last = int(round(seconds * 10))
        while self.step <= last:
            now = self.step / 10
            self.clock.now = ORIGIN + now
            due = sorted(item for item in self.agenda if item[0] <= now + 1e-9)
            self.agenda = [item for item in self.agenda if item[0] > now + 1e-9]
            actions = []
            for _, _, event in due:
                actions += (event(self) or []) if callable(event) else self.feed(event)
                actions += self.c.note_actions()
            actions += self.c.tick(now=self.clock.now)
            actions += self.c.note_actions()
            for action in actions:
                self.log.append((now, action))
                if action['type'] == 'note':
                    self.notes.append((now, action['text']))
                elif action['type'] == 'speak':
                    self.cues.append((now, action['text']))
            self.step += 1

    def after(self, seconds, kind):
        return [action for when, action in self.log if when > seconds and action['type'] == kind]


INERTIA = ('Инерция — это свойство тела сохранять скорость. Она зависит от массы тела. Чем больше масса, тем труднее изменить скорость '
           'тела, и')                                           # the segment stays open: the last sentence never ends


@pytest.mark.parametrize('where', ['on_a_portion', 'at_the_frontier'])
def test_a_pause_never_brings_the_post_publication_watchdog_phrase(tmp_path, where):
    """E3c's watchdog ends an open stream once the listener has waited 30 s at its frontier; CL2's «стоп» pauses the answer. The cloud keeps
    its segment open (no turn.done) and still speaks after the stop; for two minutes nothing is spoken and nothing is reported unanswered,
    and the pause is still a pause («Повтори» says the paused portion)."""
    s = Wire(tmp_path)
    s.ask('Что такое инерция', tid='u1')
    words = INERTIA.split(' ')
    s.at(0.3, created('a1', 'assistant', words[0]))
    for n, word in enumerate(words[1:], 1):
        s.at(round(0.3 + 0.1 * n, 2), delta('a1', ' ' + word, n))
    s.repeat(3.0, 'r1')
    if where == 'at_the_frontier':
        for n in range(2, 9):
            s.repeat(3.0 + 2.5 * (n - 1), f'r{n}')
    stop_at = 25.0
    s.user(stop_at, 'u-stop', 'Стоп')
    s.at(stop_at + 1.0, delta('a1', ' и сила трения', 99))                     # the cloud goes on in the segment the stop cut
    s.at(stop_at + 1.5, created('a2', 'assistant', 'Хорошо,'), done('a2', 'assistant', 'Хорошо, остановлюсь.'))
    s.until(stop_at + 120)
    state = s.state()
    if where == 'at_the_frontier':
        assert state.get('completed') or state.get('paused'), state
    else:
        assert state.get('paused'), state
    assert not s.after(stop_at, 'speak') and not s.after(stop_at, 'unanswered'), s.log[-6:]
    if where == 'on_a_portion':
        paused = state['chunks'][state['chunk_index']]
        s.user(stop_at + 121, 'u-again', 'Повтори')
        s.until(stop_at + 123)
        assert [a['text'] for a in s.after(stop_at + 120, 'speak')] == [paused]


TRICTION_A = ('Трение — это сила, которая мешает одному телу скользить по поверхности другого. Оно зависит от материала поверхностей и от '
              'силы, которая прижимает тела друг к другу.')
FRICTION_B = 'Всегда ли трение мешает движению'
B_EARLY = 'Да, трение всегда мешает движению тел.'                 # the head the gate publishes (F1: a sentence, published at once)
B_FINAL = 'Нет, трение иногда помогает движению, например при ходьбе'   # the cloud's rewrite, cut by the listener (no final mark)
NOTE_REPLY = ('Поправка: нет, трение иногда помогает движению, например при ходьбе. А в прошлом ответе осталось: трение зависит от силы '
              'давления.')                                               # the cloud reacting to the note: it retells what was heard


def test_a_reply_the_note_provokes_is_never_taken_for_a_restart_of_the_current_answer(tmp_path):
    """Question A is interrupted by question B: a quiet note about A is due. B's head is rewritten by the cloud into an explicit correction
    (E3c: «Поправка: …», the stream closed) - the note goes up. The listener repeats the correction (the note's reply guard ends there), and
    the cloud then retells what the listener heard and goes on with the rest of A. That reply is no restart of B: nothing of it is spoken,
    and B is dictated to the end of its correction."""
    s = Wire(tmp_path)
    s.ask('Что такое трение', tid='u1')
    s.whole(TRICTION_A, at=0.3, tid='a1')
    s.repeat(1.5, 'r1')
    s.ask(FRICTION_B, at=5.0, tid='u2')
    s.at(5.3, created('a2', 'assistant', B_EARLY))
    s.at(6.5, done('a2', 'assistant', B_FINAL))
    s.repeat(8.0, 'r2')
    s.at(9.4, created('a3', 'assistant', NOTE_REPLY[:9]))
    s.at(9.8, done('a3', 'assistant', NOTE_REPLY))
    for n in range(3, 12):
        s.repeat(10.5 + 2.0 * (n - 3), f'r{n}')
    s.until(60)
    assert s.notes and s.notes[0][0] < 9.4, f'the note about A went up before the reply: {s.notes}'
    assert any(text.startswith('Поправка') for _, text in s.cues), s.cues
    after_reply = [text for when, text in s.cues if when >= 9.4]
    assert not any('давлен' in text or 'прошлом' in text for text in after_reply), after_reply
    state = s.state()
    assert state['completed'] and ' '.join(state['chunks']).endswith('при ходьбе'), state['chunks']
