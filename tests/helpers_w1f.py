"""Test helper of the W1F-B tests (tests/test_w1f_*.py): one utterance, one decision; no stale cue; no foreign reply in the plan.

REAL: ControlledMedia built with the keywords of ``controlled_host.serve`` (HOST_KWARGS, plus the profile defaults of the silence
auto-repeat: ``repeat_seconds`` 6, ``max_auto_repeats`` 1, settings.py), EchoEngine and its SQLite file, the ledger, the classifier.
EMULATED, the way NativeMediaSocket does it: the playback rule of the transport (``_can_play``): a cue that comes while the listener is
heard (``controller.hearing``) or while the question is not final is parked and played as soon as it can, if it is still authorized; a
newer cue replaces a parked one, and «cancel» drops it. A played cue counts as heard to its end (``playback_done`` 1 s after it began),
which is what arms the silence timer in the host. Time is the probe clock of the field reports, in seconds; ticks every 50 ms.
"""
import re

from echo_sync.controlled_media import ControlledMedia
from echo_sync.settings import DEFAULTS
from helpers_live_line import LiveLine
from test_first_cue_never_silent import HOST_KWARGS

# controlled_host.serve passes the profile's silence auto-repeat (settings.py defaults: 6 s, once).
PROFILE = dict(repeat_seconds=DEFAULTS['repeat_seconds'], max_auto_repeats=DEFAULTS['max_auto_repeats'])


def created(tid, role, text):
    return {'type': 'turn.created', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def delta(tid, text):
    return {'type': 'turn.delta', 'turn_id': tid, 'delta': text}


def done(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def pieces(text):
    return re.findall(r'\s*\S+', text)


class Wire:
    mic_stream = True      # False: the test's own fake phone sends the microphone packets
    """``ack``: the listener repeats every cue played at a moment that is in one of these ``(from, to)`` spans, ``ack_after`` seconds after
    its playout ended (start of speech, the words, the final 0.5 s later)."""

    def __init__(self, tmp_path, *, playback_seconds=1.0, ack=(), ack_after=0.3, **overrides):
        self.ack, self.ack_after, self.acks = tuple(ack), ack_after, 0
        self.now, self.tick_at = 0.0, 0.0
        self.c = ControlledMedia(tmp_path / 'w1f-state.sqlite3', session_id='native-probe-' + '0' * 32, clock=lambda: self.now,
                                 **{**HOST_KWARGS, **PROFILE, **overrides})
        self.playback_seconds = playback_seconds
        self.agenda, self.order = [], 0
        self.issued, self.played = [], []          # [(seconds, text)]: every speak action / what the phone played
        self.parked = None
        self.playing = None                        # (cue, ends at)
        self.line = LiveLine(self.c, 0.0) if self.mic_stream else None      # the phone streams its microphone all call long (helpers_live_line); the meter is the repeat gate of every call

    # -- the schedule -------------------------------------------------------------------------------------------------
    def at(self, seconds, what):
        self.order += 1
        self.agenda.append((round(seconds, 4), self.order, what))

    def user(self, tid, text, start, end, *, speech=True, grow=None, times=None):
        """A user turn: the start of speech (the provider's speech_started) and turn.created at ``start``, the transcript growing until
        ``end`` - 0.3 s (word by word, or as recorded: ``grow`` characters at ``times``), and the final at ``end``."""
        if speech:
            self.at(start, lambda wire: wire.c.speech_started())
        self._grow(tid, 'user', text, start, max(start, end - 0.3), grow, times)
        self.at(end, done(tid, 'user', text))

    def assistant(self, tid, text, start, end, *, final=True, grow=None, times=None):
        """An assistant segment: created at ``start``, growing word by word (or as recorded) until ``end``, done at ``end``."""
        self._grow(tid, 'assistant', text, start, end, grow, times)
        if final:
            self.at(end, done(tid, 'assistant', text))

    def confirm(self, at):
        """At ``at`` the listener repeats whatever portion waits then."""
        def go(wire):
            state = wire.state()
            chunks, index = state.get('chunks') or [], state.get('chunk_index', 0)
            if 0 <= index < len(chunks) and not state.get('completed'):
                wire.acks += 1
                wire.user(f'confirm{wire.acks}', chunks[index], wire.now, wire.now + 0.5)
        self.at(at, go)

    def _grow(self, tid, role, text, start, end, grow, times):
        if grow is None:
            cuts = []
            for piece in pieces(text):
                cuts.append((cuts[-1] if cuts else 0) + len(piece))
            times = [start + n * (end - start) / max(1, len(cuts)) for n in range(len(cuts))]
        else:
            cuts = list(grow)
            assert times is not None and len(times) == len(cuts) and times[0] == start
        cuts[-1] = len(text) if grow is None else cuts[-1]
        self.at(times[0], created(tid, role, text[:cuts[0]]))
        for previous, cut, moment in zip(cuts, cuts[1:], times[1:]):
            self.at(moment, delta(tid, text[previous:cut]))

    # -- the transport ------------------------------------------------------------------------------------------------
    def _can_play(self):
        if self.c.hearing:
            return False
        tid = self.c.question_id
        user = self.c.ledger.snapshot(tid) if tid else None
        return not tid or bool(user and user['valid'] and user['final'])

    def _act(self, actions):
        for action in actions or []:
            if action['type'] == 'speak':
                self.issued.append((self.now, action['text']))
                self.parked = action
            elif action['type'] == 'cancel':
                self.parked = None
                if self.playing:
                    self.playing = None
        self._release()

    def _release(self):
        if self.parked is not None and self._can_play() and self.c.authorized(self.parked):
            cue, self.parked = self.parked, None
            self.played.append((self.now, cue['text']))
            self.c.cue_started(cue)
            self.playing = (cue, self.now + self.playback_seconds)
            if any(start <= self.now <= end for start, end in self.ack):
                self.acks += 1
                begin = self.now + self.playback_seconds + self.ack_after
                self.user(f'ack{self.acks}', cue['text'], begin, begin + 0.5)

    def _line(self):
        if self.line is not None:
            self.line.run_to(self.now)

    def _playout(self):
        if self.playing and self.now >= self.playing[1]:
            cue, _ = self.playing
            self.playing = None
            self.c.playback_done(cue, now=self.now)

    def until(self, seconds, step=0.05):
        """Events at their own instants (the clock is set to each), a tick every ``step`` seconds in between."""
        while True:
            self.agenda.sort(key=lambda item: item[:2])
            if self.agenda and self.agenda[0][0] <= min(self.tick_at, seconds) + 1e-9:
                moment, _, what = self.agenda.pop(0)
                self.now = max(self.now, moment)
                self._line()
                self._act(what(self) if callable(what) else self.c.provider(what))
                continue
            if self.tick_at > seconds + 1e-9:
                return self
            self.now = max(self.now, self.tick_at)
            self._line()
            self._playout()
            self._act(self.c.tick(now=self.now))
            self.tick_at = round(self.tick_at + step, 3)

    # -- observation ----------------------------------------------------------------------------------------------------
    def played_after(self, seconds):
        return [text for at, text in self.played if at >= seconds - 1e-9]

    def state(self):
        return self.c.state() or {}

    def plan(self):
        return ' '.join(self.state().get('chunks') or [])
