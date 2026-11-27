"""R08/R09: a long call on the real controller, wire and engine, driven by a seed. The world and the invariants S0..S14 are those of
helpers_s6_state (nothing there is changed); this file only adds the clock of a long call (a gap is stepped coarsely: 1 s instead of 0.5 s)
and the driver that fills 60-180 minutes of simulated time with topics, repeats, «стоп», reconnects, barge-ins and silences."""
import asyncio
import gc
import os
import random
from collections import Counter

from echo_sync.classifier import waiting_portion
from echo_sync.controlled_media import RECONNECT_WINDOW_S
from helpers_s6_state import NOISE_PHRASES, START_TIME, TOPICS, Dialogue, World, norm

WALL_START = 1_793_000_000.0      # the engine's wall clock at the start of a call (a day in Nov 2026)


def weight(obj, seen=None, depth=0):
    """How many containers and items hang off ``obj`` (dicts, lists, sets, objects): a count of things, not bytes, so a leak shows as a line."""
    seen = seen if seen is not None else set()
    if id(obj) in seen or depth > 6:
        return 0
    seen.add(id(obj))
    n = 1
    if isinstance(obj, dict):
        n += sum(weight(k, seen, depth + 1) + weight(v, seen, depth + 1) for k, v in obj.items())
    elif isinstance(obj, (list, tuple, set, frozenset)):
        n += sum(weight(v, seen, depth + 1) for v in obj)
    elif hasattr(obj, '__dict__') and not callable(obj):
        n += weight(vars(obj), seen, depth + 1)
    return n


class LongWorld(World):
    """The s6 world with ONE more thing on the simulated clock: the engine's wall clock (``issued_at``, the history's ``at``, the age of a plan
    at ``begin_call``). helpers_s6_state leaves it on ``time.time``, so there an hour of silence is 0.5 s old to the engine (finding R09-H1)."""

    async def _pump_until(self, frames, max_turns=60):
        """World._pump_until returns at once when no cue is open yet. Whether the task that makes the cue has started by the time ``feed(settle=False)`` returns
        depends on the interpreter (3.14 on the laptop: yes; 3.13 here: no, finding R09-H3), so the loop gets its turns first."""
        for _ in range(8):
            if self.open is not None:
                break
            await asyncio.sleep(0)
        await super()._pump_until(frames, max_turns)

    def connect_peer(self):
        super().connect_peer()
        self.controller.engine.clock = lambda: WALL_START + self.clock.t - START_TIME
        self.version += 1
        self.controller.begin_call()          # as controlled_host.serve does for every call (F3): a stale plan of an earlier call is retired


class LongCall(Dialogue):
    """A Dialogue whose gaps cost less: ``idle`` steps the clock by ``step`` seconds (the wire ticks at each step)."""

    def __init__(self):
        super().__init__(LongWorld())

    def stale_plan(self):
        """Does a plan wait that the next call retires (``begin_call``): nothing was said for more than RECONNECT_WINDOW_S of the wall clock?"""
        c = self.w.controller
        state = self.w.state()
        return bool(state) and waiting_portion(state) is not None and not state.get('pending_turn') and not (0 <= (c._age_of(state) or -1) <= RECONNECT_WINDOW_S)

    def reconnect(self):
        """Dialogue.reconnect, except that a stale plan is retired by the new call (F3) - the one change a reconnect may make to the stored state."""
        if not self.stale_plan():
            return super().reconnect()
        w = self.w
        cues_before = len(w.cues)
        w.reconnect()
        self.stats['reconnects'] += 1
        after = self.snap()
        if not after['completed']:
            self.fail('R08', f'a plan nobody had touched for more than {RECONNECT_WINDOW_S} s survived the new call: {after}')
        if len(w.cues) != cues_before:
            self.fail('S10', 'the reconnect itself produced audio')
        self.conn_seq, self.presented, self.sent, self.dictating, self.old_turns = w.seq, False, [], None, []
        if self.q is not None:
            self.q.first_cue_owed = False
        for turn in [self.q.assistant] if self.q and self.q.assistant else []:
            turn.live = False
        self.cues_checked = len(w.cues)
        self.prev_cue = next((c for c in reversed(w.cues) if not c.diagnostic), None)
        self.stats['retired_on_reconnect'] = self.stats.get('retired_on_reconnect', 0) + 1

    def idle(self, seconds, step=1.0):
        advance = self.w.advance
        self.w.advance = lambda s, step=step, _a=advance: _a(s, step=step)
        try:
            return self.silence(seconds)
        finally:
            del self.w.advance

    def minutes(self):
        return (self.w.clock.t - START_TIME) / 60

    def sizes(self):
        """Containers of the controller that could grow with the number of questions, as counts of things (see ``weight``)."""
        c = self.w.controller
        out = {name: weight(value) for name, value in vars(c).items()}
        state = self.w.state() or {}
        out['state.history'] = len(state.get('history') or ())
        out['state.chunked'] = sum(1 for e in state.get('history') or () if e.get('chunks'))
        out['db_bytes'] = os.path.getsize(self.w.db)
        return out


def drive(d, seed, minutes, *, gaps=(5, 20, 60, 180), reconnects=True):
    """Fill ``minutes`` of simulated time. Returns a Counter of what was done. Every step goes through ``Dialogue`` and its invariants."""
    rng = random.Random(seed)
    did = Counter()
    end = START_TIME + minutes * 60
    topics = list(TOPICS)
    while d.w.clock.t < end:
        topic = rng.choice(topics)
        group = rng.randint(1, 4)
        shape = rng.random()
        if d.dictating is not None:
            d.finish_dictation_without_a_question('ну')
        d.ask(topic, partial_first=rng.random() < .3)
        did['question'] += 1
        while d.has_stale() and rng.random() < .7:                      # the model's late words of the question that was replaced
            d.stale_assistant(); did['stale'] += 1
        if shape < .1:
            d.assistant_only_done()
        elif shape < .35:                      # the answer streams, and the next question comes while it does
            d.assistant_begin(group)
            for _ in range(rng.randint(0, 3)):
                if d.assistant_can_stream():
                    d.assistant_delta()
            did['cut_stream'] += 1
            continue
        else:
            d.assistant_begin(group)
            for _ in range(rng.randint(0, 6)):
                if d.assistant_can_stream():
                    d.assistant_delta()
            if d.assistant_can_stream() or d.assistant_open():
                while d.assistant_can_stream():
                    d.assistant_delta()
                d.assistant_done()
        for _ in range(rng.randint(0, 4)):
            act = rng.random()
            if d.dictating is not None:
                d.finish_dictation_without_a_question('ну')
            if act < .45 and d.cue_ready() is not None:
                d.ack(relaxed_text=rng.random() < .5); did['ack'] += 1
            elif act < .55 and d.cue_ready() is not None and len(d.cue_ready().text.split()) >= 2:
                d.partial_repeat(rng.randint(1, 3)); did['partial'] += 1
            elif act < .62 and d.cue_ready() is not None:
                d.wrong_repeat(rng.choice(['negate', 'digit', 'swap'])); did['wrong'] += 1
            elif act < .72 and (d.active_answer() or d.assistant_open()):
                d.repeat(rng.choice(('повтори', 'ещё раз'))); did['repeat'] += 1
            elif act < .82 and d.active_answer():
                d.stop(); did['stop'] += 1
                d.idle(rng.choice(gaps)); did['idle'] += 1
                if rng.random() < .5:
                    d.repeat('повтори'); did['resume'] += 1
            elif act < .90 and reconnects:
                d.reconnect(); did['reconnect'] += 1
                d.idle(rng.choice(gaps)); did['idle'] += 1
                if d.can_replay_ack() and rng.random() < .5:
                    d.replay_last_ack(); did['replay'] += 1
            else:
                d.idle(rng.choice(gaps)); did['idle'] += 1
        if rng.random() < .4 and d.active_answer() and d.dictating is None and not d.w.hold:
            kind = rng.choice(['half', 'orphan', 'duplicate', 'hold', 'barge'])
            if kind == 'half' and d.w.open is None:
                d.interrupt_a_portion(rng.choice(['barge_in', 'speech_started', 'stop', 'silence']), rng.randint(1, 4), rng.choice(topics))
                if d.dictating is not None:
                    d.finish_dictation_without_a_question('ну')
            elif kind == 'orphan':
                d.orphan_delta()
            elif kind == 'duplicate' and d.sent:
                d.duplicate(rng.choice(d.duplicable()))
            elif kind == 'hold':
                d.hold_synthesis()
                d.idle(rng.choice((1, 3, 9)), step=.5)
                d.release_synthesis()
            elif kind == 'barge':
                d.barge_in(rng.choice(['client_cancel', 'client_clear', 'provider_speech_started']))
                d.noise(rng.choice(NOISE_PHRASES))
            else:
                kind = None
            did[kind or 'skipped'] += 1
        d.idle(rng.choice(gaps)); did['idle'] += 1
    return did
