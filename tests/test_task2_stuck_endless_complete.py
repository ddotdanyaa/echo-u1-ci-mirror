"""Wave 2 / Task 2: the controlled route is never stuck, never endless and always complete.

Three P1 defects of scripts/MULTITURN_FINDINGS.md (offline replays of the real controller):

G2  Playback died for good after 21-62 ACKs inside ONE answer. The 64-turn ledger (voice_turns.FramelessTurns) evicted the
    turn of the question that was still being answered, and NativeMediaSocket._can_play() needs that turn in the ledger,
    so every later cue stayed in ``pending_cue``. The same eviction could take the assistant turn that streams the answer.
G3  An answer whose final text does not end in «.!?…» lost its last portions (a single provider-final turn: all but the
    first one). The delegation transport must not call a segment ending in letters final, because a continuation segment
    may follow, and nothing ever finished the stream when none came.
G5  An unconfirmed portion was re-spoken in silence for ever (70 repeats in 300 s).

Everything here runs the real ControlledMedia / NativeMediaSocket built with the production keywords of
controlled_host.serve. Only the I/O is fake and time is an injected clock: nothing sleeps, no network, no TTS, no server.
"""
import ast
import asyncio
import inspect
import logging
import re
import time
from pathlib import Path

import pytest

import echo_sync
from echo_sync import controlled_media
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.voice_turns import FramelessTurns
from engine_say import engine_reply

# Same keywords as the ControlledMedia(...) call in echo_sync/controlled_host.py (checked below).
HOST_KWARGS = dict(source_delivery='delegation', session_context_fallback=True, lookup_policy='required',
                   first_useful_gate=True, coalesce_seconds=3.2, quiet_reopen=True)


# --- provider wire events (shapes of the field fixtures: turn.created / turn.delta / turn.done) -----------------

def created(tid, role, text):
    return {'type': 'turn.created', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def delta(tid, text, n):
    return {'type': 'turn.delta', 'turn_id': tid, 'delta': text, 'start_ms': n * 40, 'end_ms': n * 40 + 39}


def done(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def words(text):
    return re.findall(r'\s*\S+', text)


def squeeze(text):
    return ' '.join(text.split())


class Clock:
    """Injectable time for ControlledMedia(clock=...) and NativeMediaSocket(clock=...)."""

    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def host_controller(tmp_path, clock=None, **overrides):
    extra = {'clock': clock} if clock is not None else {}
    return ControlledMedia(tmp_path / 'controlled-state.sqlite3', session_id='native-probe-' + '0' * 32,
                           **{**HOST_KWARGS, **extra, **overrides})


def test_the_harness_is_built_exactly_like_the_host(tmp_path):
    source = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', None) == 'ControlledMedia']
    assert len(calls) == 1
    host = {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords if isinstance(k.value, ast.Constant)}
    assert {k: v for k, v in host.items() if k != 'session_id'} == HOST_KWARGS
    assert [ast.unparse(k.value) for k in calls[0].keywords if k.arg == 'settings'] == ['controller_settings(profile_settings)']      # ROOT-1: the host builds the controller's settings once, at construction


# --- the transport: NativeMediaSocket on fake I/O ---------------------------------------------------------------

class Wire:
    """``spoken`` is every text handed to the voice, in order: what the phone would hear."""

    def __init__(self, controller, clock=None):
        self.sent, self.spoken = [], []

        async def emit(frame):
            self.sent.append(frame)

        async def synthesize(text):
            self.spoken.append(text)
            return b'\0' * 960  # 20 ms of PCM: _speak has nothing to wait for

        self.socket = NativeMediaSocket(controller, emit, lambda: None, lambda _: None, synthesize, clock=clock)
        self.socket.ready = True

    async def feed(self, *events):
        for event in events:
            await self.socket.provider(event)

    async def settle(self):
        await asyncio.gather(*self.socket.tasks, return_exceptions=True)


def user_turn(tid, text):
    """What the wire carries for one spoken utterance: a partial turn, then its final."""
    return [created(tid, 'user', text[:3]), done(tid, 'user', text)]


# ===================================================================================================================
# G2: eviction must never take the question (or the answer) that is being worked on
# ===================================================================================================================

def timed(kind, tid, role, text, start):
    return {'type': kind, 'turn': {'id': tid, 'role': role, 'transcript': text, 'start_ms': start, 'end_ms': start + 100}}


def test_ledger_eviction_spares_the_turns_its_owner_still_needs_and_stays_bounded():
    needed = {'q'}
    ledger = FramelessTurns(max_turns=4, keep=lambda: needed)
    ledger.apply(timed('turn.done', 'q', 'user', 'Вопрос', 0))
    for n in range(1, 40):
        ledger.apply(timed('turn.done', f't{n}', 'user', f'Реплика {n}', n * 1000))
    ids = [turn['id'] for turn in ledger.history()]
    assert ids == ['q', 't37', 't38', 't39']       # bounded; the 39 newer turns pushed out only finished history
    needed.clear()                                  # once nobody needs it, it is evictable like everything else
    ledger.apply(timed('turn.done', 't40', 'user', 'Реплика 40', 40000))
    assert [turn['id'] for turn in ledger.history()] == ['t37', 't38', 't39', 't40']


def test_ledger_without_a_keep_hook_evicts_exactly_as_before():
    ledger = FramelessTurns(max_turns=2)
    for n in range(4):
        ledger.apply(timed('turn.created', str(n), 'user', 'Текст', n * 1000))
    assert [turn['id'] for turn in ledger.history()] == ['2', '3']


def test_ledger_never_spins_when_every_turn_is_needed():
    ledger = FramelessTurns(max_turns=1, keep=lambda: {'a', 'b', 'c'})
    for n, tid in enumerate('abc'):
        ledger.apply(timed('turn.done', tid, 'user', 'Текст', n * 1000))
    assert sorted(turn['id'] for turn in ledger.history()) == ['a', 'b', 'c']  # the owner's call; no endless loop


SENTENCES = ['Вода кипит при ста градусах.', 'Лёд плавится при нуле.', 'Пар легче воды.',
             'Солнце нагревает землю днём.', 'Ночью земля остывает быстро.', 'Ветер переносит тепло.',
             'Облака собирают влагу.', 'Дождь питает реки.', 'Реки текут к морю.', 'Море хранит тепло.']


def long_answer(sentences):
    return ' '.join(SENTENCES[i % len(SENTENCES)] for i in range(sentences))


# (user turns the provider adds before the ACK, does the model chatter after each ACK): the real number of turns the
# wire produces per ACK is not measured yet (U-2), so the stall must be gone for every shape, not for one.
ACK_SHAPES = {'one_user_turn_per_ack': (0, False),
              'model_chatter_after_each_ack': (0, True),
              'two_user_turns_and_chatter': (1, True)}


@pytest.mark.parametrize('shape', ACK_SHAPES)
def test_a_long_answer_is_dictated_to_its_last_portion_whatever_the_provider_adds_per_ack(tmp_path, shape):
    extra_user_turns, chatter = ACK_SHAPES[shape]

    async def run():
        clock = Clock()                          # the listener's time: a repeat begins after the cue is over (Wave 2 / Task B)
        c = host_controller(tmp_path, clock)
        wire = Wire(c)
        await wire.feed(*user_turn('u1', 'Как устроена погода'))
        answer = long_answer(130)                # F1: one meaning portion per sentence (100 sentences made >= 120 short portions)
        await wire.feed(created('a1', 'assistant', answer[:20]), done('a1', 'assistant', answer))
        await wire.settle()
        chunks = c.state()['chunks']
        assert len(chunks) >= 120        # far beyond the 64 turns of the ledger: 21-62 ACKs used to be the limit
        for k, portion in enumerate(chunks):
            assert len(wire.spoken) == k + 1, (f'the phone fell silent after {k} ACKs: cue {k + 1} of {len(chunks)} '
                                               f'was never spoken (pending_cue={wire.socket.pending_cue is not None})')
            assert wire.spoken[k] == portion
            clock.now += 2.0                     # the listener needs a moment after the cue
            for j in range(extra_user_turns):
                await wire.feed(*user_turn(f'mumble{k}-{j}', 'угу'))
            await wire.feed(*user_turn(f'ack{k}', portion))
            if chatter:
                await wire.feed(created(f'chatter{k}', 'assistant', 'Хорошо'),
                                done(f'chatter{k}', 'assistant', 'Хорошо, продолжаем.'))
            await wire.settle()
        state = c.state()
        assert wire.spoken == chunks and state['completed'] and state['chunk_index'] == len(chunks)
        # Memory stays bounded: finished history is what is evicted; the turn of the question is not finished.
        assert len(c.ledger.history()) <= c.ledger.max_turns
        assert c.ledger.snapshot('ack0') is None
        assert c.ledger.snapshot('u1') is not None
        await wire.socket.close()
    asyncio.run(run())


def test_the_turn_that_streams_the_active_answer_is_never_evicted(tmp_path):
    """More than a hundred other turns pass while ONE answer is still streaming: its later deltas must still arrive."""
    c = host_controller(tmp_path, Clock())
    for event in user_turn('u1', 'Как устроена погода'):
        c.provider(event)
    text = long_answer(12)
    pieces = words(text)
    c.provider(created('a1', 'assistant', pieces[0]))
    for n, piece in enumerate(pieces[1:18], 1):          # F1: stopped inside a sentence (the 20th word ends one: all of it is said)
        c.provider(delta('a1', piece, n))
    before = len(c.published.split())
    assert 0 < before < 20
    for n in range(70):                       # the user mumbles, the model chatters: 140 other turns
        for event in user_turn(f'm{n}', 'угу'):
            c.provider(event)
        c.provider(done(f'c{n}', 'assistant', 'Хорошо.'))
    for n, piece in enumerate(pieces[18:], 18):
        c.provider(delta('a1', piece, n))
    # The rest of the stream was published as it arrived (only the last portion and word are withheld while it
    # streams). Before the fix the turn was gone from the ledger, so every later delta was dropped on the floor.
    assert len(c.published.split()) >= len(pieces) - 10, 'the deltas after the other turns went by were lost'
    c.provider(done('a1', 'assistant', text))
    assert squeeze(' '.join(c.state()['chunks'])) == squeeze(text)
    assert len(c.ledger.history()) <= c.ledger.max_turns


# ===================================================================================================================
# The driver for G3 and G5: the host's 0.1 s tick on an injected clock, with a transport and a listener
# ===================================================================================================================

class Run:
    """The production-profile controller driven the way the host drives it, on an injected clock.

    ``at(seconds, event)`` schedules a provider event; ``until(seconds)`` advances time in the host's 0.1 s ticks, feeding
    events when they are due and calling ``tick`` after them. ``play`` is how long the transport takes to play a cue; it then
    reports the end of the playout the way NativeMediaSocket._speak does (None: never reports). ``ack_after`` makes the
    listener repeat every cue aloud that long after it was produced (None: the listener is silent).
    """
    ORIGIN = 100.0

    def __init__(self, tmp_path, *, play=None, ack_after=None, **overrides):
        self.clock = Clock(self.ORIGIN)
        self.c = host_controller(tmp_path, self.clock, **overrides)
        self.play, self.ack_after = play, ack_after
        self.cues = []        # (seconds since the start, text)
        self.agenda, self.step, self.order, self.acks = [], 0, 0, 0

    def _add(self, seconds, kind, payload):
        self.order += 1
        self.agenda.append((seconds, self.order, kind, payload))

    def at(self, seconds, *events):
        for event in events:
            self._add(seconds, 'event', event)

    def ask(self, question, at=0.0, tid='u1'):
        self.at(at, created(tid, 'user', question.split()[0]), done(tid, 'user', question))

    def whole(self, text, at, tid='a1'):
        """The assistant turn arrives in one piece."""
        self.at(at, created(tid, 'assistant', words(text)[0]), done(tid, 'assistant', text))

    def stream(self, text, start, end, tid='a1'):
        """The assistant turn streams word by word from ``start`` and ends at ``end``."""
        pieces = words(text)
        step = (end - start) / len(pieces)
        self.at(start, created(tid, 'assistant', pieces[0]))
        for n, piece in enumerate(pieces[1:], 1):
            self.at(round(start + n * step, 3), delta(tid, piece, n))
        self.at(end, done(tid, 'assistant', text))

    def until(self, seconds):
        last = int(round(seconds * 10))
        while self.step <= last:
            now = self.step / 10
            self.clock.now = self.ORIGIN + now
            due = sorted(item for item in self.agenda if item[0] <= now + 1e-9)
            self.agenda = [item for item in self.agenda if item[0] > now + 1e-9]
            actions = []
            for _, _, kind, payload in due:
                if kind == 'event':
                    actions += self.c.provider(payload)
                else:
                    self.c.playback_done(payload, now=self.clock.now)
            actions += self.c.tick(now=self.clock.now)
            for action in actions:
                if action['type'] != 'speak':
                    continue
                self.cues.append((now, action['text']))
                if self.play is not None:
                    self._add(now + self.play, 'played', action)
                if self.ack_after is not None:
                    self.acks += 1
                    self._add(now + self.ack_after, 'event', done(f'ack{self.acks}', 'user', action['text']))
            self.step += 1

    @property
    def heard(self):
        return squeeze(' '.join(text for _, text in self.cues))

    @property
    def texts(self):
        return [text for _, text in self.cues]

    def state(self):
        return self.c.state()


# ===================================================================================================================
# G3: an answer that ends without «.!?…» is still dictated to its last word
# ===================================================================================================================

LEVER = 'Как работает рычаг'
# The model forgot the final period (the findings: «...тянет вперёд»). Every word of it must reach the listener.
LEVER_OPEN = ('Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в силе. '
              'Короткое плечо даёт выигрыш в пути и скорости')

UNTERMINATED = [  # (id, question, the whole answer, without terminal punctuation)
    ('three_sentences', LEVER, LEVER_OPEN),
    ('one_sentence', 'Как устроен термос', 'Двойные стенки с вакуумом между ними почти не пропускают тепло'),
    ('lone_word', 'Как называется наука о насекомых', 'Энтомология'),
    ('held_follow_up', 'Зачем?', 'Чтобы сохранять тепло в доме зимой'),
]


@pytest.mark.parametrize('ack_after', [0.3, 0.8, 2.5], ids=['fast_listener', 'normal_listener', 'slow_listener'])
@pytest.mark.parametrize('arrival', ['streamed', 'whole'])
@pytest.mark.parametrize('case', UNTERMINATED, ids=[c[0] for c in UNTERMINATED])
def test_an_answer_without_terminal_punctuation_is_dictated_to_its_last_word(tmp_path, case, arrival, ack_after):
    _, question, answer = case
    run = Run(tmp_path, ack_after=ack_after)
    run.ask(question)
    if arrival == 'streamed':
        run.stream(answer, 0.3, 2.0)
    else:
        run.whole(answer, 2.0)
    run.until(40)
    assert run.heard == squeeze(answer), 'the end of the answer was never spoken'
    state = run.state()
    assert not state.get('streaming') and not state.get('stream_waiting_next')
    assert state['completed'] and state['chunk_index'] == len(state['chunks'])   # the last ACK really ends the answer


def test_a_punctuated_answer_is_not_delayed_by_the_grace_window(tmp_path):
    run = Run(tmp_path)
    run.ask(LEVER)
    run.whole(LEVER_OPEN + '.', 1.0)
    run.until(1.0)
    state = run.state()
    assert squeeze(' '.join(state['chunks'])) == LEVER_OPEN + '.' and not state['streaming']
    assert run.cues and run.cues[0][0] == pytest.approx(1.0, abs=0.05)


def test_the_tail_is_released_when_the_grace_window_ends_not_before(tmp_path):
    """turn.done at 1.0 s; the listener repeats the first cue at 1.3 s and waits for more text."""
    run = Run(tmp_path, ack_after=0.3)
    run.ask(LEVER)
    run.whole(LEVER_OPEN, 1.0)
    run.until(2.1)                                    # 1.1 s after turn.done: inside the 1.2 s window
    assert len(run.cues) == 1
    state = run.state()
    assert state['streaming'] and state['stream_waiting_next'] and len(state['chunks']) == 1
    run.until(2.4)                                    # 1.4 s after turn.done: the window is over (the next ACK is at 2.5)
    assert len(run.cues) == 2
    assert 2.2 - 0.05 <= run.cues[1][0] <= 2.2 + 0.15  # at the end of the window, one tick or so late at most
    state = run.state()
    assert not state['streaming'] and squeeze(' '.join(state['chunks'])) == LEVER_OPEN


def test_the_grace_window_is_a_constant_and_configurable(tmp_path):
    assert controlled_media.ANSWER_GRACE_SECONDS == 1.2
    assert inspect.signature(ControlledMedia.__init__).parameters['answer_grace_seconds'].default == 1.2
    for grace in (0.4, 2.0):
        run = Run(tmp_path / f'g{grace}', ack_after=0.3, answer_grace_seconds=grace)
        run.ask(LEVER)
        run.whole(LEVER_OPEN, 1.0)
        run.until(6)
        assert len(run.cues) > 1
        assert 1.0 + grace - 0.05 <= run.cues[1][0] <= 1.0 + grace + 0.25
        assert run.heard == squeeze(LEVER_OPEN)


MID_WORD_A = 'Рычаг уравнивает моменты сил. Длинное пле'      # the turn ends in the middle of «плечо»
MID_WORD_B = 'чо даёт выигрыш в силе.'


def test_a_continuation_inside_the_window_is_still_merged_and_the_half_word_never_spoken(tmp_path):
    # The listener has not repeated anything yet: a user turn between two segments would own the next segment
    # (controlled_media.provider: owner = the latest user turn at first sight), which is a different matter.
    run = Run(tmp_path)
    run.ask(LEVER)
    run.at(1.0, created('a1', 'assistant', MID_WORD_A), done('a1', 'assistant', MID_WORD_A))
    run.at(1.8, created('a2', 'assistant', 'чо даёт'))              # 0.8 s after turn.done: inside the window
    run.at(2.0, done('a2', 'assistant', MID_WORD_B))
    run.until(5)
    state = run.state()
    merged = 'Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в силе.'
    assert squeeze(' '.join(state['chunks'])) == merged and not state['streaming']
    assert 'пле' not in ' '.join(state['chunks']).split()
    for k, portion in enumerate(state['chunks']):                   # and the listener can walk it to the end
        run.at(5.0 + k, done(f'walk{k}', 'user', portion))
    run.until(5.0 + len(state['chunks']) + 1)
    assert run.heard == merged and run.state()['completed']


def test_each_continuation_restarts_the_window(tmp_path):
    run = Run(tmp_path, ack_after=0.3)               # a listener who keeps up: the end is declared once the window is over
    run.ask(LEVER)
    run.at(1.0, created('a1', 'assistant', MID_WORD_A), done('a1', 'assistant', MID_WORD_A))
    run.at(1.9, created('a2', 'assistant', 'чо даёт выигрыш'))
    run.at(2.0, done('a2', 'assistant', 'чо даёт выигрыш в силе'))   # unpunctuated again
    run.until(2.9)                                    # 1.9 s after the FIRST turn.done, 0.9 s after the last one
    assert run.state()['streaming']
    run.until(3.5)                                    # 1.5 s after the last turn.done
    state = run.state()
    assert not state['streaming']
    assert squeeze(' '.join(state['chunks'])) == 'Рычаг уравнивает моменты сил. Длинное плечо даёт выигрыш в силе'


def test_a_late_continuation_cannot_corrupt_the_finished_answer(tmp_path):
    run = Run(tmp_path, ack_after=0.3)               # a listener who keeps up: the end is declared once the window is over
    run.ask(LEVER)
    run.at(1.0, created('a1', 'assistant', MID_WORD_A), done('a1', 'assistant', MID_WORD_A))
    run.until(2.5)
    finished = list(run.state()['chunks'])
    assert not run.state()['streaming']
    run.at(3.0, created('a2', 'assistant', MID_WORD_B), done('a2', 'assistant', MID_WORD_B))   # far too late
    run.until(8)
    assert run.state()['chunks'] == finished


def test_the_window_counts_from_the_end_of_the_turn_not_from_the_last_word(tmp_path):
    run = Run(tmp_path, ack_after=0.3)               # a listener who keeps up: the end is declared once the window is over
    run.ask(LEVER)
    pieces = words(LEVER_OPEN)
    run.at(0.5, created('a1', 'assistant', pieces[0]))
    for n, piece in enumerate(pieces[1:], 1):
        run.at(0.5 + n * 0.1, delta('a1', piece, n))
    run.until(20)                                     # the producer goes quiet WITHOUT finishing its turn
    assert run.state()['streaming']                  # silence alone never ends an answer: it may still be coming
    run.at(20.2, done('a1', 'assistant', LEVER_OPEN))
    run.until(20.9)
    assert run.state()['streaming']
    run.until(21.8)
    state = run.state()
    assert not state['streaming'] and squeeze(' '.join(state['chunks'])) == LEVER_OPEN


def test_a_new_question_inside_the_window_discards_the_old_tail(tmp_path):
    run = Run(tmp_path, ack_after=0.3)
    run.ask(LEVER)
    run.whole(LEVER_OPEN, 1.0)
    run.ask('Что такое масса', at=1.6, tid='u2')                   # 0.6 s after turn.done
    run.whole('Масса — это мера инертности тела и количества вещества в нём.', 2.0, tid='a2')
    run.until(10)
    assert 'скорости' not in run.heard and 'Короткое' not in run.heard   # nothing of the old answer after its question
    assert run.heard.endswith('мера инертности тела и количества вещества в нём.')


def test_stop_inside_the_window_pauses_and_keeps_the_held_tail(tmp_path):
    """Coordinator ruling (W1F-B, 3 Nov 2026), binding: «under CL2 ruling 1 «стоп» is a PAUSE that keeps the plan. Consistently, text of
    the CURRENT answer that has already arrived when the user pauses — published or not yet published — and text of the same answer that
    keeps arriving after the pause are kept in the plan (never spoken while paused; spoken from the paused portion on «продолжай / ещё
    раз / повтори» or by a resume). Only a NEW question (internal retire) discards the old answer's tail.»
    Until then this test pinned the opposite (the tail held back in the grace window never joined the plan)."""
    run = Run(tmp_path, ack_after=0.3)
    run.ask(LEVER)
    run.whole(LEVER_OPEN, 1.0)
    run.at(1.6, done('stop', 'user', 'стоп'))
    run.until(10)
    assert len(run.cues) == 1                                       # the first cue only: nothing is spoken while paused
    assert run.state()['paused'] and not run.state()['completed']
    run.at(12.0, done('go', 'user', 'продолжай'))                   # the resume: the held tail is dictated from the paused portion on
    run.until(60)
    assert run.heard == squeeze(LEVER_OPEN) and run.state()['completed']


def test_the_host_tick_releases_the_tail_after_the_grace_window(tmp_path):
    """Through NativeMediaSocket.tick, the object the host ticks every 0.1 s."""
    async def run():
        clock = Clock()
        c = host_controller(tmp_path, clock)
        wire = Wire(c, clock=clock)
        await wire.feed(*user_turn('u1', LEVER))
        clock.now += 1.0
        await wire.feed(created('a1', 'assistant', 'Рычаг'), done('a1', 'assistant', LEVER_OPEN))   # turn.done now
        await wire.settle()
        assert len(wire.spoken) == 1
        clock.now += 0.3
        await wire.feed(*user_turn('ack0', wire.spoken[0]))         # the listener repeats it and waits for the rest
        await wire.settle()
        assert len(wire.spoken) == 1
        clock.now += 0.8                                            # 1.1 s after turn.done: inside the window
        await wire.socket.tick()
        await wire.settle()
        assert len(wire.spoken) == 1
        clock.now += 0.3                                            # 1.4 s: the window is over
        await wire.socket.tick()
        await wire.settle()
        assert len(wire.spoken) == 2 and LEVER_OPEN.startswith(' '.join(wire.spoken[:1]))
        assert squeeze(' '.join(c.state()['chunks'])) == LEVER_OPEN
        await wire.socket.close()
    asyncio.run(run())


# ===================================================================================================================
# G5: an unconfirmed portion is repeated a bounded number of times
# ===================================================================================================================

SILENT_Q = 'Как работает рычаг'
SILENT_A = LEVER_OPEN + '.'


def silent_listener(tmp_path, **overrides):
    run = Run(tmp_path, play=1.2, **overrides)       # a cue takes 1.2 s to play out
    run.ask(SILENT_Q)
    run.whole(SILENT_A, 0.3)
    return run


def test_the_constants_sit_next_to_the_others_and_feed_the_defaults():
    assert controlled_media.MAX_AUTO_REPEATS == 3
    assert inspect.signature(ControlledMedia.__init__).parameters['max_auto_repeats'].default == 3


def test_an_unconfirmed_portion_is_repeated_at_most_three_times_in_silence(tmp_path):
    run = silent_listener(tmp_path)
    run.until(300)
    first = run.cues[0][1]
    assert run.texts == [first] * 4                  # the portion itself, then three repeats, then silence
    # No other behaviour changes: a repeat comes repeat_seconds (3 s) after the playout (1.2 s) of the one before.
    times = [t for t, _ in run.cues]
    assert times[0] == pytest.approx(0.3, abs=0.05) and times[1] == pytest.approx(4.5, abs=0.15)
    assert all(b - a == pytest.approx(4.2, abs=0.15) for a, b in zip(times[1:], times[2:]))
    state = run.state()
    assert state['chunk_index'] == 0 and not state['completed']      # the cursor never moved on its own


@pytest.mark.parametrize('cap', [0, 1, 5])
def test_the_repeat_cap_is_configurable(tmp_path, cap):
    run = silent_listener(tmp_path, max_auto_repeats=cap)
    run.until(300)
    assert len(run.cues) == 1 + cap


def test_the_cap_is_logged_without_any_conversation_content(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        run = silent_listener(tmp_path)
        run.until(60)
    lines = [r.getMessage() for r in caplog.records if 'auto_repeat_cap' in r.getMessage()]
    assert len(lines) == 1                           # once, not every tick
    assert 'index=0' in lines[0] and 'revision=' in lines[0]
    assert not any(word in lines[0] for word in ('Рычаг', 'уравнивает', LEVER))


def capped(tmp_path, **overrides):
    run = silent_listener(tmp_path, **overrides)
    run.until(40)                                    # long after the third repeat (12.9 s)
    assert len(run.cues) == 4
    return run, list(run.state()['chunks'])


def test_after_the_cap_the_users_repeat_resumes_with_the_next_portion_which_has_its_own_repeats(tmp_path):
    run, chunks = capped(tmp_path)
    run.at(40.5, done('ack-late', 'user', chunks[0]))
    run.until(300)
    assert run.texts == [chunks[0]] * 4 + [chunks[1]] * 4
    assert run.cues[4][0] == pytest.approx(40.5, abs=0.15)           # the next portion comes at once
    assert run.state()['chunk_index'] == 1


def test_after_the_cap_povtori_speaks_the_portion_again_and_repeating_resumes(tmp_path):
    run, chunks = capped(tmp_path)
    run.at(40.5, done('again', 'user', 'повтори'))
    run.until(300)
    assert run.texts == [chunks[0]] * 8              # the one asked for, then a fresh set of three
    assert run.cues[4][0] == pytest.approx(40.5, abs=0.15)
    assert run.state()['chunk_index'] == 0


def test_after_the_cap_a_new_question_is_answered_and_its_portion_is_repeated_normally(tmp_path):
    run, chunks = capped(tmp_path)
    run.ask('Что такое масса', at=40.5, tid='u2')
    run.whole('Масса — это мера инертности тела и количества вещества в нём.', 41.0, tid='a2')
    run.until(300)
    fresh = run.texts[4:]
    assert len(fresh) == 4 and len(set(fresh)) == 1 and fresh[0] not in chunks
    assert run.cues[4][0] == pytest.approx(41.0, abs=0.15)


def test_the_cap_belongs_to_the_portion_whoever_moves_the_cursor(tmp_path):
    """Every reachable cursor move goes through a user turn, which also starts the count again. The cap must still be
    per PORTION, so that another control path (here: the engine advanced directly) cannot hand a spent budget on."""
    run, chunks = capped(tmp_path)
    c = run.c
    engine_reply(c.engine, session_id=c.session_id, turn_id='manual-next', text=chunks[0], request={}, model='manual')
    state = c.state()
    assert state['chunk_index'] == 1
    cue = {'type': 'speak', 'text': chunks[1], 'epoch': c.epoch, 'nonce': c.nonce,
           'revision': state['revision'], 'index': 1}
    assert c.authorized(cue)
    run.c.playback_done(cue, now=run.clock.now)       # the transport played it; the listener stays silent
    run.until(300)
    assert run.texts[4:] == [chunks[1]] * 3


def test_after_the_cap_a_failed_repeat_is_not_silence_and_gets_a_fresh_set(tmp_path):
    run, chunks = capped(tmp_path)
    run.at(40.5, done('try', 'user', 'Рычаг'))       # the user tries but it is not the portion: not an ACK
    run.until(300)
    # re-presented after the usual pause, three times, then silence. G3, rule 3 (changed on purpose): the first time only what is missing after «Рычаг»
    assert run.texts == [chunks[0]] * 4 + [chunks[0].split(' ', 1)[1]] * 2 + [chunks[0]]
    assert run.state()['chunk_index'] == 0


def test_after_the_cap_a_stalled_partial_attempt_is_not_silence_either(tmp_path):
    run, chunks = capped(tmp_path)
    run.at(40.5, created('p', 'user', 'Рычаг'))      # the user starts to repeat and stops; the 3 s quiet rule fires
    run.until(43.6)
    assert run.c.partial_quiet(now=run.clock.now)
    run.until(300)
    assert run.texts == [chunks[0]] * 7


def test_the_host_loop_stops_repeating_after_the_cap(tmp_path):
    """Through NativeMediaSocket.tick: _speak reports the real end of every playout to playback_done."""
    async def run():
        offset = [0.0]
        c = host_controller(tmp_path)                # the default monotonic clock, as in the host
        wire = Wire(c, clock=lambda: time.monotonic() + offset[0])
        await wire.feed(*user_turn('u1', SILENT_Q))
        await wire.feed(created('a1', 'assistant', 'Рычаг'), done('a1', 'assistant', SILENT_A))
        await wire.settle()
        first = wire.spoken[0]
        for _ in range(60):
            offset[0] += 10                          # ten more silent seconds; the host ticks
            await wire.socket.tick()
            await wire.settle()
        assert wire.spoken == [first] * 4
        await wire.socket.close()
    asyncio.run(run())
