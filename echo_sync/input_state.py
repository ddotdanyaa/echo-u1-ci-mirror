"""U17-S3: the state of the listener's input in one listening window, and what the repeat does about it. Pure: no clock, no log, no audio (every call is given ``now`` in seconds).

The window opens when a cue ends (``cue_end``) or the controller resets it (``reset``: the owner's words were taken). Inside it the meter counts what arrived: packets (and their level), the speech the VAD saw, the text the ear or the cloud gave, a fault.
``state(now)`` is the first row of this table that holds (the table counts, it lists no phrase):
  1 no_packets     the last packet is older than NO_PACKET_GAP_S (or none came at all); on a half-duplex phone the cue itself is no gap
  2 warming        fewer than DUPLEX_MIN_PACKETS packets so far: too early to judge
  3 asr_fault      the ear or the cloud reported a fault in this window
  4 dead_input     the packets are digital zero for DEAD_INPUT_S and more
  5 heard          text came (ear or cloud) in this window
  6 pending_asr    speech of MIN_SPEECH_MS and more, no text yet, and the ASR still has its ASR_GRACE_S (or the language hold, ``ear_other_language``)
  7 unintelligible speech, no text, the wait is over
  8 quiet_speech   the same, but the loudest packet is under QUIET_DBFS (the voice was too quiet to read)
  9 silence        nothing else
``repeat_action`` reads it: hold (no repeat, not counted), defer (half duplex: the listener has not had HALF_LISTEN_S of real sound yet), unconfirmed (repeat, but counted on the cap after unplaced speech), repeat."""
from collections import namedtuple

from .call_trace import DUPLEX_MIN_CUE_S, DUPLEX_MIN_PACKETS, PCM_BYTES_PER_SECOND, DuplexMeter

NO_PACKET_GAP_S = 1.0           # no packet this long = the channel is lost
DEAD_INPUT_S = 2.0              # digital zero this long = the microphone is muted
ASR_GRACE_S = 1.5               # after the last speech the ear is given this long to give a text (inside TEMPO_HOLD_SECONDS, U20 R10)
HALF_LISTEN_S = 2.0             # half duplex: real sound the listener must have had since the cue before it is said again
MIN_SPEECH_MS = 300             # less voiced time than this is not speech
DEAD_DBFS = -90.0
QUIET_DBFS = -45.0

NO_PACKETS, WARMING, ASR_FAULT, DEAD_INPUT, HEARD = 'no_packets', 'warming', 'asr_fault', 'dead_input', 'heard'
PENDING_ASR, UNINTELLIGIBLE, QUIET_SPEECH, SILENCE = 'pending_asr', 'unintelligible', 'quiet_speech', 'silence'

OTHER_LANGUAGE = 'ear_other_language'

Action = namedtuple('Action', 'act state got_s why')

_ACT = {NO_PACKETS: 'hold', WARMING: 'hold', ASR_FAULT: 'hold', DEAD_INPUT: 'hold', PENDING_ASR: 'hold',
        UNINTELLIGIBLE: 'unconfirmed', QUIET_SPEECH: 'unconfirmed', HEARD: 'repeat', SILENCE: 'repeat'}


class InputMeter:
    def __init__(self, anchor):
        self.anchor = anchor
        self.packets = 0
        self.last_packet = None
        self._duplex = DuplexMeter(anchor)
        self._in_cue = False
        self._cue_end = None
        self._dead_since = None
        self._seen = None
        self._states = {}
        self.reset(anchor)

    def reset(self, now):
        """A new listening window (the owner's words were taken, or a cue ended)."""
        self.window_at = now
        self.got_s = 0.0
        self.voiced_ms = 0
        self.last_voice_at = None
        self.empty_at = None
        self.pending_until = None
        self.heard_at = None
        self.fault_at = None
        self.peak_dbfs = None

    # --- events
    def packet(self, now, nbytes, dbfs=None):
        self.packets += 1
        self.last_packet = now
        self.got_s += nbytes / PCM_BYTES_PER_SECOND
        self._duplex.packet(now, nbytes)
        if dbfs is not None:
            if self.peak_dbfs is None or dbfs > self.peak_dbfs:
                self.peak_dbfs = dbfs
            if dbfs <= DEAD_DBFS:
                if self._dead_since is None:
                    self._dead_since = now
            else:
                self._dead_since = None

    def vad(self, now, voiced_ms):
        """The VAD saw ``voiced_ms`` more of speech."""
        if voiced_ms > 0:
            self.voiced_ms += voiced_ms
            self.last_voice_at = now

    def ear(self, now, text='', reason='', speech_ms=0, hold_s=None):
        """The ear gave a final. A text is heard; an empty one is only the end of the wait, except ``ear_other_language``, which stays pending while the language hold lasts."""
        if text and str(text).strip():
            self.heard_at = now
            return
        self.voiced_ms = max(self.voiced_ms, speech_ms)
        self.empty_at = now
        if reason == OTHER_LANGUAGE:
            self.voiced_ms = max(self.voiced_ms, MIN_SPEECH_MS)
            self.pending_until = now + (ASR_GRACE_S if hold_s is None else hold_s)

    def cloud(self, now, has_text=True):
        if has_text:
            self.heard_at = now

    def fault(self, now, kind=''):
        self.fault_at = now

    def cue_begin(self, now):
        self._in_cue = True
        self._duplex.response_created()
        self._duplex.audio_frame(now)

    def cue_end(self, now):
        if self._in_cue:
            self._duplex.audio_frame(now)
            self._duplex.end_response()
        self._in_cue = False
        self._cue_end = now
        self.reset(now)

    # --- reading
    def duplex(self, now):
        return self._duplex.summary(now)['verdict']

    def _gap_lost(self, now):
        half = self.duplex(now) == 'half'
        if half and self._in_cue:
            return False
        last = self.last_packet
        if last is None:
            last = self.anchor
        elif half and self._cue_end is not None and self._cue_end > last:
            last = self._cue_end
        return now - last > NO_PACKET_GAP_S

    def state(self, now):
        label = self._label(now)
        if label != self._seen:
            self._seen = label
            self._states[label] = self._states.get(label, 0) + 1
        return label

    def _label(self, now):
        if self._gap_lost(now):
            return NO_PACKETS
        if self.packets < DUPLEX_MIN_PACKETS:
            return WARMING
        if self.fault_at is not None:
            return ASR_FAULT
        if self._dead_since is not None and now - self._dead_since >= DEAD_INPUT_S:
            return DEAD_INPUT
        if self.heard_at is not None:
            return HEARD
        if self.voiced_ms >= MIN_SPEECH_MS:
            evidence = max(t for t in (self.last_voice_at, self.empty_at, self.window_at) if t is not None)
            until = evidence + ASR_GRACE_S
            if self.pending_until is not None:
                until = max(until, self.pending_until)
            if now < until:
                return PENDING_ASR
            if self.peak_dbfs is not None and self.peak_dbfs < QUIET_DBFS:
                return QUIET_SPEECH
            return UNINTELLIGIBLE
        return SILENCE

    def repeat_action(self, now, half_listen_s=HALF_LISTEN_S):
        state = self.state(now)
        act = _ACT[state]
        why = state
        if state == SILENCE and self.duplex(now) == 'half' and self.got_s < half_listen_s:
            act, why = 'defer', 'half_duplex'
        return Action(act, state, round(self.got_s, 2), why)

    def summary(self, now):
        """Numbers and labels only, for the call_close line."""
        return {'state': self.state(now), 'packets': self.packets, 'duplex': self.duplex(now), 'got_s': round(self.got_s, 2),
                'voiced_ms': self.voiced_ms, 'states': dict(self._states)}
