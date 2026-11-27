"""Task S1: the local ear in SHADOW mode (scripts/DUAL_SYSTEM_DESIGN.md §3.2 and §3.8 S1; offline bake-off of its recognizer:
U1/05_WORK/scripts/local_ear_bakeoff.py).

Next to the cloud, the transport's own ear listens to the phone's microphone, recognizes every utterance with a local model and writes
down what the EXISTING classifier would decide on that text for the portion that waits (``analyze(text, controller.state(), [],
controller.settings)``, the very call the controller makes for a cloud final). That is all it does: it never changes the controller's
state, never sends anything to the phone or the cloud, never holds the call. The point is to measure, on the owner's real speech and
next to the cloud's own verdicts in the call trace, whether a local ear may later decide repeats and commands itself (S3).

* ``ShadowEar`` (one per call, on the transport's event loop): ``feed(pcm, input_ms=)`` after every microphone packet has been forwarded
  to the cloud - a speech detector (task S0's ``SpeechOnset``) finds the utterances; their audio, with ``PREROLL_PACKETS`` before the
  detected start, goes to the worker's queue (no decoding here). ``poll()`` on the transport's tick takes the worker's texts, decides
  and logs them. ``close()`` at the end of the call.
* ``EarWorker`` (one per process, a daemon thread): owns the recognizer (``ear_sherpa.SherpaEngine``), loads it in the thread, decodes
  the queued utterances one by one. Decoding releases the GIL; the queue of a call is bounded (``MAX_PENDING_S``).
* Off unless the profile's ``local_ear`` is ``"shadow"`` (``for_call``). Whatever goes wrong - no model, no detector, a recognizer
  error, a bug - switches the ear off for the call (once, logged by type) or costs one utterance; the call goes on as before.
* R-EAR-ACT: ``local_ear = "act"`` (opt-in) builds the same ear ``acting``: it also tells the controller every start of speech
  (``ControlledMedia.ear_onset``), and the transport hands each record of ``poll`` to ``ControlledMedia.ear_heard``, which applies a
  confirmation, a repeat request, a stop or «дальше» at once and leaves everything else to the cloud. What the ear itself does (hear,
  decide with the classifier, log, write the trace) is unchanged.
* H4: with ``fast_text`` on, ``ear_heard`` also opens a plain reference the base answers from the ear's text, and with the ear acting a question the job prepared on it has answered (``ControlledMedia._ear_first``).
* H3: the ear (shadow or act) always tells the controller what the detector hears as it hears it (``on_speech``: ``ControlledMedia.ear_speech``, onset and offset of every
  utterance, and that the ear is gone), and the transport hands it the records of ``poll`` (``ControlledMedia.tempo_heard``): the local ear keeps the tempo of the prompter.
* L3 (long speech; the only way: a cut word is lost speech). A stretch of speech longer than MAX_UTTERANCE_S stays ONE recognizer stream. At the bound the words
  the recognizer has so far - all but the last, which may still be growing - are the final of that window (``more``), the next window is a new utterance for whoever listens (``part``)
  and the stream goes on, at most MAX_STREAM_S: no word is cut in two at a bound, a window without words resets nothing. The bias of the stream is the one of its start.
  One thread owns the recognizer: nothing of it ever runs twice at once.
* L3 (load; the only way: a dropped utterance was silent loss). A full queue (the recognizer is MAX_PENDING_S behind) costs what waits of the window, not the rest of the
  utterance: the window has what was recognized of it (``cut = "overflow"``), the speech goes on as a new window as soon as the recognizer has caught up, and every record says how
  much of its audio was not recognized (``lost_ms``) and how much audio waited for the recognizer at its end or at the overflow (``behind_ms``). A window that lost audio is speech nobody knows
  for whoever acts on the record, as a dropped utterance was (``kind = "error"``, ``reason = "overflow"``, no ``text``); the words recognized of it are in ``heard``.
* U64: every utterance also has the numbers of its voice (``prosody.Track``: the pitch slope and loudness fall at its end, the last voiced stretch, the pause after it) in the journal's ``ear_final``
  (``prosody``). A meter only: no threshold, no setting, nothing reads it back; the record for the controller does not have it.

Logged (agent log, never the words): ``echo-sync ear uid=… kind=… reason=… revision=… index=… speech_ms=… lag_ms=… decode_ms=…
chars=…`` per utterance and ``echo-sync ear state=…`` once per state change - not the ``echo-sync decision`` prefix, so nothing that
counts the controller's decisions mistakes a shadow verdict for one. The call trace (``report``: the host's ``CallTrace.note``) gets
``ear_final`` with the text and the same fields, and ``ear_state``.
"""
import collections
from array import array
import itertools
import logging
import queue
import re
import threading
import time

from .classifier import analyze, waiting_portion
from .diagnostics import reason_of
from .ear_sherpa import base_terms, hotwords_for
from .settings import environment, resolve
from . import near_voice, prosody

logger = logging.getLogger('echo-sync')
PREROLL_PACKETS = 3          # ~300 ms of the phone's ~100 ms packets before the detected start (it needs 60 ms of loud frames)
BYTES_PER_SECOND = 48000     # PCM16LE mono 24 kHz, what the phone sends
MAX_PENDING_S = 3.0          # audio of a call waiting for the worker; more = it cannot keep up: the window loses what waits (``_overflow``)
MAX_UTTERANCE_S = 15.0       # a recognizer stream this long is finished and the speech goes on as a new utterance
VOICE_BUFFER_S = 15.0        # w9-ear-voice: the newest audio of one utterance kept for near_voice (16 kHz s16 mono = 32000 bytes/s); older bytes of a longer one are dropped
MAX_STREAM_S = 300.0         # L3: a stream carried over the window bounds is finished after this much speech all the same (its bias is the one of its start; its text grows; measured: a packet of a stream costs about 12 % more CPU with every minute of the stream's age - 1.4-1.9 times in the fifth minute, REVIEW_20261112/night/L3_ear.md)
CARRY_HOLD_WORDS = 1         # L3 carry: so many of the last words of the text so far are not given at a bound - the last one may still be growing (measured: REVIEW_20261112/night/L3_ear.md)
_tokens = itertools.count(1)


def _resume(given, words):
    """L3 carry: ``given`` are the words of a stream already handed out as the finals of its earlier windows, ``words`` its text so far now.
    ``(at, revised)``: the new words are ``words[at:]``. The recognizer only adds words: ``at`` is ``len(given)``. When it has changed what it gave
    (a beam that took another path), the place is found by position - where the last words given stand now, at most two words off - and
    ``revised`` says so; never a search through the whole text (a repeated word would move the place)."""
    n = len(given)
    if words[:n] == given:
        return n, False
    for size in (3, 2, 1):
        tail = given[-size:]
        if len(tail) < size:
            continue
        for shift in (0, 1, -1, 2, -2):
            end = n + shift
            if size <= end <= len(words) and words[end - size:end] == tail:
                return end, True
    return min(n, len(words)), True


def to16k(pcm):
    """PCM16LE 24 kHz (the phone) -> 16 kHz by linear interpolation (near_voice's rate); a level and a crude tilt survive it, a spectrum does not."""
    a = array('h');a.frombytes(bytes(pcm[:len(pcm) // 2 * 2]))
    n = len(a) * 2 // 3;out = array('h', bytes(2 * n))
    for j in range(n):
        x = j * 1.5;i = int(x);k = min(i + 1, len(a) - 1);out[j] = int(a[i] + (a[k] - a[i]) * (x - i))
    return out.tobytes()


class EarWorker:
    """The recognizer in a daemon thread, shared by the calls of a process. ``engine_factory()`` (run in the thread) returns an object
    with ``start(hotwords) -> stream``, ``accept(stream, pcm)`` and ``finish(stream) -> text``. ``state``: loading | ready | failed.

    L3: this thread is the only one that ever calls the recognizer, one operation at a time - several calls, a text so far, a window bound all
    wait their turn in ``_jobs``. ``can_carry``: the recognizer can say its text so far (``peek``), so a stream may go on over a window bound
    (op ``'carry'``: the words so far, without the last CARRY_HOLD_WORDS, are the final of the window that ends; the stream belongs to the next
    window, whose final and texts so far are only the words after them)."""

    def __init__(self, engine_factory):
        self.engine_factory = engine_factory
        self.state, self.reason = 'loading', None
        self.can_carry = False
        self._ready = threading.Event()
        self._jobs = queue.SimpleQueue()
        threading.Thread(target=self._run, name='echo-ear', daemon=True).start()

    def wait_ready(self, timeout=None):
        """Wait for the model; True when it is ready (False: it failed, or not yet)."""
        self._ready.wait(timeout)
        return self.state == 'ready'

    def submit(self, sink, uid, op, payload=None):
        self._jobs.put((sink, uid, op, payload))

    def _run(self):
        try:
            engine = self.engine_factory()
        except BaseException as error:              # noqa: BLE001 - no model, no package: the ear is off, the call is not
            self.state, self.reason = 'failed', reason_of(error)
            self._ready.set()
            return
        self.can_carry = callable(getattr(engine, 'peek', None))
        self.state = 'ready'
        self._ready.set()
        streams = {}
        given = {}                                  # L3 carry: stream key -> the words of the stream given as the finals of its earlier windows
        while True:
            sink, uid, op, payload = self._jobs.get()
            key = (sink.token, uid)
            try:
                if op == 'start':
                    streams[key] = engine.start(payload)
                elif op == 'audio':
                    if key in streams and sink._wants(uid):
                        engine.accept(streams[key], payload)
                    else:                                    # not recognized: the ear counts it where it says what it lost (L3, ``_overflow``)
                        skipped = getattr(sink, '_skipped', None)
                        if skipped is not None:
                            skipped(uid, len(payload))
                elif op == 'end' and key in streams:
                    began = time.perf_counter()
                    text = engine.finish(streams.pop(key))
                    if key in given:                         # the last window of a carried stream: its own words
                        words = (text or '').split()
                        at, revised = _resume(given.pop(key), words)
                        if revised:
                            sink._revised(uid)
                        text = ' '.join(words[at:])
                    sink._heard(uid, text, round((time.perf_counter() - began) * 1000))
                elif op == 'carry':                          # L3: the window ``uid`` ends at a bound, the stream goes on as the window ``payload``
                    began = time.perf_counter()
                    if key not in streams:                   # it failed meanwhile: its error is this window's record, and the next one has no stream
                        sink._heard(payload, None, None, 'no_stream')
                        continue
                    words = (engine.peek(streams[key]) or '').split()
                    at, revised = _resume(given.pop(key, []), words)
                    fresh = words[at:len(words) - CARRY_HOLD_WORDS] if len(words) - CARRY_HOLD_WORDS > at else []
                    after = (sink.token, payload)
                    streams[after], given[after] = streams.pop(key), words[:at] + fresh
                    if revised:
                        sink._revised(uid)
                    sink._heard(uid, ' '.join(fresh), round((time.perf_counter() - began) * 1000))
                elif op == 'drop':
                    streams.pop(key, None)
                    given.pop(key, None)
                elif op == 'peek' and key in streams:        # ear-early: the text so far; a recognizer without ``peek``, or a failing one, costs only this
                    began = time.perf_counter()
                    peek = getattr(engine, 'peek', None)
                    try:
                        text = peek(streams[key]) if peek else None
                        if text is not None and key in given:        # of a carried stream: the words of this window
                            words = text.split()
                            text = ' '.join(words[_resume(given[key], words)[0]:])
                    except Exception:                      # noqa: BLE001 - the stream may be half-decoded; the final still comes
                        text = None
                    sink._early(uid, payload, text, round((time.perf_counter() - began) * 1000))
            except Exception as error:                 # noqa: BLE001 - one utterance is lost, the worker goes on
                streams.pop(key, None)
                given.pop(key, None)
                sink._heard(uid, None, None, reason_of(error))
                if op == 'carry':                          # the window that was to go on has no stream either
                    sink._heard(payload, None, None, reason_of(error))
            finally:
                if op == 'audio':
                    sink._consumed(len(payload))


class ShadowEar:
    """The ear of one call. ``decide(text) -> (kind, reason, revision, index)``; ``detector``: S0's ``SpeechOnset`` contract
    (``feed(pcm) -> 'onset' | 'speech' | None`` and ``speaking``); ``report(ev, **fields)``: the call trace; ``hotwords()``: the bias
    for the next utterance (the waiting portion), or None.

    R-EAR-ACT: ``acting`` (mode "act", ``for_call``) says that the transport hands the records of ``poll`` to the controller
    (``ControlledMedia.ear_heard``), and ``on_onset(uid)`` is told every start of speech the detector hears, when it is heard (the
    controller notes where the call stood then). Neither changes what the ear itself does."""

    def __init__(self, worker, decide, *, detector, report=None, clock=None, hotwords=None, on_onset=None, acting=False, on_speech=None,
                 early_ms=None, on_early=None, partial_ms=None, voice=None, portion=None, lang=None):
        self.worker, self.decide, self.detector, self.report, self.hotwords = worker, decide, detector, report, hotwords
        self.revised = set()                      # carry: uids of the windows at whose end the recognizer had changed words it gave before (the worker thread adds)
        self.skip = set()                         # the windows an overflow ended - what still waits of them is not recognized, and is counted
        self.lost = {}                            # live: uid -> bytes of its audio that were not recognized (both threads, under ``lock``)
        self.feeding_ms = None                    # the input clock of the packet being fed
        self.prosody_errors = 0                   # U64: meters that failed (the utterance has no numbers)
        self.on_onset, self.acting, self.on_speech = on_onset, bool(acting), on_speech
        self.clock = clock or time.monotonic
        self.token = next(_tokens)
        self.uid = 0
        self.current = None                       # the utterance being heard (its uid), None between utterances
        self.ring = collections.deque(maxlen=getattr(detector, 'preroll_packets', PREROLL_PACKETS))   # a late detector (Silero) asks for more
        self.voice_ring = collections.deque(maxlen=getattr(detector, 'preroll_packets', PREROLL_PACKETS))
        self.spans = {}                           # uid -> onset / offset times and input_ms, bytes sent (the loop side only)
        self.dropped = set()                      # uids whose audio is no longer wanted (overflow, warming, error, close)
        self.pending = 0                          # bytes queued for the worker and not yet taken
        self.lock = threading.Lock()
        self.heard = collections.deque()          # (uid, text, decode_ms, error) from the worker thread
        self.wake = None                          # H7 item 6: thread-safe, set by the host with ``prepare_wide``: asks the loop to take the text now
        self.told = set()
        self.off = False
        # w9-ear-voice (E78): ``voice`` is near_voice's NearGate (``on_audio(pcm16k)``, ``on_utterance(pcm16k, text, portion, uid)``), ``portion()`` the waiting portion. The audio of the utterance heard is kept (16 kHz, bounded) until its
        # end and judged when its text comes; the numbers go into the record as ``voice`` (no text, no audio). Never changes ``kind``/``reason``; a failure costs only the voice.
        self.voice, self.portion = voice, portion
        self.lang = lang                          # U19-S7: () -> the language of the turn ('ru' | 'en'); the recognizer of the utterance follows it (ear_sherpa.LangEngine). Only text comes out of the ear.
        self.voice_open = {}                      # uid -> bytearray of the utterance so far (16 kHz)
        self.voice_bytes_max = 0
        self.voice_errors = 0
        # ear-early (C7): on ``early_ms`` of silence inside an utterance (the detector's ``quiet_ms``) the recognizer's text so far is taken, once per
        # pause. It is only measured: it goes to ``on_early(**record)`` and the trace, never to ``poll`` (what ``ear_heard`` acts on). Speech that goes on
        # marks it discarded; a final that says the same marks it confirmed.
        self.early_ms, self.on_early = (early_ms if early_ms and early_ms > 0 else None), on_early
        self.early_counts = {'sent': 0, 'taken': 0, 'discarded': 0, 'confirmed': 0}
        self.early_results = collections.deque()  # (uid, seq, text, decode_ms) from the worker thread
        # W5 instant: every ``partial_ms`` of speech the recognizer's text so far is taken (the same ``peek``) and kept in ``partials`` for the transport
        # (``ControlledMedia.ear_partial``). It never goes to ``poll``; a peek still in flight is not asked again.
        self.partial_ms = partial_ms if partial_ms and partial_ms > 0 else None
        self.partials = collections.deque(maxlen=32)

    # --- the transport's side ---------------------------------------------------------------------------------------------------------
    def feed(self, pcm, *, input_ms=None):
        """One microphone packet, AFTER it was forwarded to the cloud. Never raises, never waits for the recognizer."""
        if self.off:
            return
        try:
            self._feed(pcm, input_ms)
        except Exception as error:                     # noqa: BLE001 - the ear never breaks the call
            self._switch_off('broken', reason=reason_of(error))

    def poll(self):
        """On the transport's tick: decide and log what the worker has heard. Returns the records (for whoever wants them)."""
        if self.off:
            return []
        try:
            return self._poll()
        except Exception as error:                     # noqa: BLE001 - the ear never breaks the call
            self._switch_off('broken', reason=reason_of(error))
            return []

    def close(self):
        """The call is over: what is open is dropped, and nothing more is decided or written for this call."""
        if not self.off:
            self._drop_current()
            self.off = True

    def _feed(self, pcm, input_ms):
        if self.worker.state == 'failed':
            self._switch_off('failed', reason=self.worker.reason)
            return
        pcm = bytes(pcm)
        self.feeding_ms = input_ms
        pcm16 = self._voice_audio(pcm)
        verdict = self.detector.feed(pcm)
        if verdict == 'onset':
            if self.current is not None:          # a new start before the end was seen: the speech before it is one utterance
                self._end(input_ms)
            self._start(pcm, input_ms)
            self._prosody_add(pcm)
        elif self.current is None:
            self.ring.append(pcm)
            if pcm16 is not None:self.voice_ring.append(pcm16)
        else:
            self._prosody_add(pcm)
            self._audio(pcm)
            if verdict == 'speech':
                self._resumed()
            elif self.early_ms and self.detector.speaking:
                self._maybe_peek()
            if self.partial_ms and self.detector.speaking:
                self._maybe_partial()
            if not self.detector.speaking:
                self._end(input_ms)
            elif self.spans.get(self.current, {}).get('bytes', 0) >= MAX_UTTERANCE_S * BYTES_PER_SECOND:
                self._bound(input_ms)

    def _bound(self, input_ms):
        """The window bound: the speech goes on as a new utterance, and so does the recognizer stream, for MAX_STREAM_S at most (L3) - the window that
        ends gets the words so far without the last, the next window is told as a start of speech like any other and is that many windows into the
        stream (``part``). Only a recognizer that cannot say its words so far (no ``peek``), a dropped window or the end of the stream cut it: the stream
        is finished and a new one begins, the word being said is heard by neither."""
        old = self.current
        span = self.spans.get(old)
        if (not getattr(self.worker, 'can_carry', False) or span is None or old in self.dropped
                or span.get('part', 1) * MAX_UTTERANCE_S >= MAX_STREAM_S):
            self._end(input_ms)                   # a recognizer stream is bounded
            self._start(b'', input_ms)
            return
        new = self.uid + 1
        self._end(input_ms, carry=new)
        self.uid = self.current = new
        if self.on_onset is not None:
            self.on_onset(new)
        if self.on_speech is not None:
            self.on_speech(new, 'onset')
        self.spans[new] = {'onset': self.clock(), 'onset_input_ms': input_ms, 'bytes': 0, 'part': span.get('part', 1) + 1, 'track': prosody.Track(), 'lang': span.get('lang', 'ru')}

    def _prosody_add(self, pcm):
        """U64: the packet goes to the meter of the utterance open (``prosody.Track``: numbers for the journal, nothing decided on them); a meter that fails is gone for that utterance."""
        span = self.spans.get(self.current)
        track = span.get('track') if span else None
        if track is None:
            return
        try:track.add(pcm)
        except Exception:span.pop('track', None);self.prosody_errors += 1      # noqa: BLE001 - a witness, not the ear

    def _voice_audio(self, pcm):
        """The live packet for near_voice (the noise floor needs the quiet too) and for the buffer of the utterance open; None when off or it failed."""
        if self.voice is None:
            return None
        try:
            pcm16 = to16k(pcm);self.voice.on_audio(pcm16)
            if self.current is not None:self._voice_add(self.current, pcm16)
            return pcm16
        except Exception:                          # noqa: BLE001 - the voice is a witness, not the ear
            self.voice_errors += 1;return None

    def _voice_add(self, uid, pcm16):
        buf = self.voice_open.setdefault(uid, bytearray());buf += pcm16
        limit = int(VOICE_BUFFER_S * 32000)
        if len(buf) > limit:del buf[:len(buf) - limit]
        self.voice_bytes_max = max(self.voice_bytes_max, len(buf))

    def _maybe_peek(self):
        span = self.spans.get(self.current)
        if span is None or span.get('peeking') or self.current in self.dropped or (getattr(self.detector, 'quiet_ms', 0) or 0) < self.early_ms:
            return
        span['peeking'] = True
        seq = span['peek_seq'] = span.get('peek_seq', 0) + 1
        span.setdefault('peeks', {})[seq] = {'sent': self.clock(), 'discarded': False}
        self.early_counts['sent'] += 1
        self.worker.submit(self, self.current, 'peek', seq)

    def _maybe_partial(self):
        span = self.spans.get(self.current)
        if span is None or span.get('partial_flight') or self.current in self.dropped:
            return
        if span['bytes'] - span.get('partial_at', 0) < self.partial_ms * BYTES_PER_SECOND // 1000:
            return
        span['partial_at'], span['partial_flight'] = span['bytes'], True
        seq = span['peek_seq'] = span.get('peek_seq', 0) + 1
        span.setdefault('peeks', {})[seq] = {'sent': self.clock(), 'discarded': False, 'partial': True}
        self.worker.submit(self, self.current, 'peek', seq)

    def take_partials(self):
        """W5 instant: the partial texts taken since the last call, ``{'uid', 'text', 'decode_ms'}``, oldest first."""
        out = list(self.partials)
        self.partials.clear()
        return out

    def _resumed(self):
        span = self.spans.get(self.current)
        if span and span.get('peeking'):
            span['peeking'] = False               # the pause is over: the text taken in it is stale, and the next pause may take another
            span['peeks'][span['peek_seq']]['discarded'] = True
            self.early_counts['discarded'] += 1

    def _early_poll(self):
        while self.early_results:
            uid, seq, text, decode_ms = self.early_results.popleft()
            span = self.spans.get(uid)
            mark = span and span.get('peeks', {}).get(seq)
            if mark is None or text is None:
                if mark is not None and mark.get('partial'):
                    span['partial_flight'] = False
                continue
            if mark.get('partial'):
                span['partial_flight'] = False
                if text.strip():
                    self.partials.append({'uid': uid, 'text': text, 'decode_ms': decode_ms})
                continue
            self.early_counts['taken'] += 1
            mark['text'] = text
            if self.on_early is None and not self.report:
                continue
            record = {'uid': uid, 'text': text, 'discarded': mark['discarded'], 'decode_ms': decode_ms, 'lag_ms': round((self.clock() - mark['sent']) * 1000)}
            if self.report:
                self.report('ear_early', **record)
            if self.on_early is not None:
                self.on_early(**record)

    def _start(self, pcm, input_ms):
        self.uid += 1
        uid = self.current = self.uid
        if self.on_onset is not None:             # R-EAR-ACT: every start, heard or not (a dropped one is speech all the same)
            self.on_onset(uid)
        if self.on_speech is not None:            # H3: the same
            self.on_speech(uid, 'onset')
        if self.worker.state != 'ready':          # the model is still loading: this utterance is not heard
            self.dropped.add(uid)
            self.ring.clear()
            self._tell('warming')
            return
        self.spans[uid] = {'onset': self.clock(), 'onset_input_ms': input_ms, 'bytes': 0, 'track': prosody.Track()}
        bias = self._bias()
        self.spans[uid]['lang'] = getattr(bias, 'lang', 'ru')
        self.worker.submit(self, uid, 'start', bias)
        if self.voice is not None:
            for before in self.voice_ring:self._voice_add(uid, before)
            self.voice_ring.clear()
            if pcm:
                try:self._voice_add(uid, to16k(pcm))
                except Exception:self.voice_errors += 1
        ring = list(self.ring)                    # (a copy: L3 live - the pre-roll of a window may itself begin the next one, ``_audio``)
        self.ring.clear()
        for before in ring:
            self._audio(before)
        if pcm:
            self._audio(pcm)

    def _bias(self):
        """What ``start`` is given: the bias of the waiting portion, and for a turn that is not Russian the language it is in (a ``Bias``; a plain string or None when it is Russian, as always)."""
        bias = self.hotwords() if self.hotwords else None
        try:
            lang = self.lang() if self.lang else 'ru'
        except Exception:                                # noqa: BLE001 - the language is a hint, never a failure
            lang = 'ru'
        if lang == 'ru':
            return bias
        from .ear_sherpa import Bias                     # noqa: PLC0415
        return Bias(bias, lang)

    def _audio(self, pcm):
        uid = self.current
        if uid in self.dropped:
            return
        if uid in self.skip:                      # L3: the window an overflow ended (``_overflow``) is deaf until the recognizer has caught up
            if self.pending > 0:
                return self._lose(uid, len(pcm))
            self._end(self.feeding_ms)            # caught up: the speech goes on as a new window, heard from this packet on
            self._start(b'', self.feeding_ms)
            uid = self.current
            if uid in self.dropped:
                return
        with self.lock:
            full = self.pending + len(pcm) > MAX_PENDING_S * BYTES_PER_SECOND
            if not full:
                self.pending += len(pcm)
        if full:
            return self._overflow(uid, pcm)
        self.spans[uid]['bytes'] += len(pcm)
        self.worker.submit(self, uid, 'audio', pcm)

    def _overflow(self, uid, pcm):
        """L3: the recognizer is MAX_PENDING_S behind and ``pcm`` does not fit. What was recognized of the window so
        far is all there will be of it (``cut``): what still waits of it is given up and counted (``_skipped``), and so is what comes while
        the recognizer works off what waits of the utterances before (``_audio``). When nothing waits any more the window ends and the speech
        goes on as a new one with the whole queue before it - one window with a hole per overflow, not a row of scraps. The ear is never more
        than MAX_PENDING_S behind, and every record says what was not recognized of its window (``_poll``)."""
        self._tell('overflow', uid=uid)
        self.skip.add(uid)
        self.spans[uid].update(cut='overflow', behind=self.pending)
        self._lose(uid, len(pcm))

    def _lose(self, uid, nbytes):
        with self.lock:
            self.lost[uid] = self.lost.get(uid, 0) + nbytes

    def _end(self, input_ms, carry=None):
        """The utterance heard is over. ``carry`` (L3, ``_bound``): the uid of the window that takes its recognizer stream over."""
        uid, self.current = self.current, None
        if self.on_speech is not None:            # H3: the end of every utterance, its text or not
            self.on_speech(uid, 'offset')
        span = self.spans.get(uid)
        heard = self.voice_open.pop(uid, None)
        if uid in self.dropped or span is None:
            self.spans.pop(uid, None)
            return
        if heard is not None:
            try:span['voice'] = (bytes(heard), self.portion() if self.portion else None)
            except Exception:self.voice_errors += 1
        span.update(offset=self.clock(), offset_input_ms=input_ms, behind=max(span.get('behind', 0), self.pending))
        track = span.pop('track', None)
        if track is not None:
            try:span['prosody'] = track.features()
            except Exception:self.prosody_errors += 1      # noqa: BLE001
        if carry is None:
            self.worker.submit(self, uid, 'end')
        else:
            span['more'] = True
            self.worker.submit(self, uid, 'carry', carry)

    def _drop_current(self):
        if self.current is not None:
            self.dropped.add(self.current)
            self.worker.submit(self, self.current, 'drop')
            self.current = None

    def _switch_off(self, state, **fields):
        self.off = True
        self._drop_current()
        if self.on_speech is not None:            # H3: nobody will tell the end of what was being heard
            self.on_speech(None, 'lost')
        self._tell(state, level=logging.WARNING, **fields)

    def _tell(self, state, level=logging.INFO, **fields):
        """A change of the ear's own state, once per call: the agent log (no words) and the call trace."""
        if state in self.told:
            return
        self.told.add(state)
        logger.log(level, 'echo-sync ear state=%s reason=%s', state, fields.get('reason'))
        if self.report:
            self.report('ear_state', state=state, **fields)

    def _poll(self):
        records = []
        if self.worker.state == 'failed':
            self._switch_off('failed', reason=self.worker.reason)
            return records
        self._early_poll()
        while self.heard:
            uid, text, decode_ms, error = self.heard.popleft()
            span = self.spans.pop(uid, None)
            if span is None:                      # dropped meanwhile
                continue
            self._confirm(span, text)
            heard = None
            with self.lock:                       # L3: how much of this window's audio was not recognized (``_lose``)
                lost = self.lost.pop(uid, 0)
            self.skip.discard(uid)
            if error:
                self.dropped.add(uid)             # what is still to come of it is not recognized any more
                kind, reason, revision, index = 'error', error, None, None
            elif lost:                            # L3 live: speech with a hole in it is speech nobody knows, as a dropped utterance was - no text to act on, no verdict; the words recognized of it are ``heard``
                heard, text = text, None
                kind, reason, revision, index = 'error', 'overflow', None, None
            else:
                kind, reason, revision, index = self.decide(text)
            now, offset = self.clock(), span.get('offset')
            record = {'uid': uid, 'text': text, 'kind': kind, 'reason': reason, 'revision': revision, 'index': index,
                      'speech_ms': None if offset is None else round((offset - span['onset']) * 1000),
                      'lag_ms': None if offset is None else round((now - offset) * 1000),
                      'decode_ms': decode_ms, 'onset_input_ms': span['onset_input_ms'], 'offset_input_ms': span.get('offset_input_ms')}
            if 'part' in span:                    # L3 carry: which window of its stream this is (the first says nothing) ...
                record['part'] = span['part']
            if span.get('more'):                  # ... the stream goes on after it: the text is the words so far without the last ...
                record['more'] = True
            if uid in self.revised:               # ... and the recognizer had changed words given by the windows before
                self.revised.discard(uid)
                record['revised'] = True
            record['lost_ms'] = lost * 1000 // BYTES_PER_SECOND      # L3: how much of this window was not recognized, how far behind the recognizer was when it ended, and why it ended
            record['behind_ms'] = span.get('behind', 0) * 1000 // BYTES_PER_SECOND
            if span.get('cut'):
                record['cut'] = span['cut']
            if heard is not None:
                record['heard'] = heard
            voice = self._voice_record(uid, span, text, error)
            logger.info('echo-sync ear uid=%s kind=%s reason=%s revision=%s index=%s speech_ms=%s lag_ms=%s decode_ms=%s chars=%s',
                        uid, kind, reason, revision, index, record['speech_ms'], record['lag_ms'], decode_ms, len(text) if text else 0)
            if self.report:
                self.report('ear_final', lang=span.get('lang', 'ru'), **record, **({'prosody': span['prosody']} if span.get('prosody') else {}))      # U64: numbers of the voice, for the journal only
            # R-EAR-ACT: where the speech began and ended on the ear's clock (the controller's: ``for_call``), for whoever acts on it.
            if voice is not None:record['voice'] = voice
            records.append({**record, 'onset': span['onset'], 'offset': offset})
        return records

    def _voice_record(self, uid, span, text, error):
        """near_voice's numbers for the utterance (judged before it taught anything); None when off, no audio, no text or a failure."""
        got = span.pop('voice', None)
        if self.voice is None or got is None or error or not text:
            return None
        try:
            rec = self.voice.on_utterance(got[0], text, got[1], uid)
            return None if not rec else {k: rec.get(k) for k in ('kind', 'conf', 'rel_db', 'tilt_off', 'level_db', 'own_db', 'noise_db', 'peak_db', 'crest_db', 'frames', 'pieces', 'aligned')}
        except Exception:                          # noqa: BLE001
            self.voice_errors += 1;return None

    # --- the worker thread's side -----------------------------------------------------------------------------------------------------
    def _wants(self, uid):
        return uid not in self.dropped and uid not in self.skip

    def _skipped(self, uid, nbytes):
        """Audio of ``uid`` that waited and was not given to the recognizer: of a window an overflow ended, it is what that window lost."""
        if uid in self.skip:
            self._lose(uid, nbytes)

    def _consumed(self, nbytes):
        with self.lock:
            self.pending -= nbytes

    def _confirm(self, span, text):
        last = span.get('peeks', {}).get(span.get('peek_seq'))
        if last and not last['discarded'] and last.get('text') and text and _plain(last['text']) == _plain(text):
            self.early_counts['confirmed'] += 1

    def _early(self, uid, seq, text, decode_ms):
        self.early_results.append((uid, seq, text, decode_ms))

    def _revised(self, uid):
        self.revised.add(uid)

    def _heard(self, uid, text, decode_ms, error=None):
        self.heard.append((uid, text, decode_ms, error))
        if self.wake:
            try:
                self.wake()
            except Exception:                     # noqa: BLE001 - the tick takes it then
                pass


def _plain(text):
    return ' '.join(re.sub(r'[^\w]+', ' ', (text or '').casefold().replace('ё', 'е')).split())


def controller_decider(controller):
    """What the controller would decide on ``text`` now: the very ``analyze`` call it makes for a cloud final. Only reads."""
    def decide(text):
        state = controller.state()
        decision = analyze(text, state, [], controller.settings)
        state = state or {}
        return decision.kind, decision.reason, state.get('revision'), state.get('chunk_index')
    return decide


class BaseTerms:
    """E60: the terms of the BASE for the recognizer's bias - the owner's materials (``<HERMES_HOME>/materials/context.md``, the text the call is given) as ``ear_sherpa.base_terms``.
    Read ONCE per call, off the loop (``prime`` starts a daemon thread; the first utterance finds the list there, an earlier one the empty list: a bias without the base is the bias
    it always was). Nothing usable (no home, no file, a placeholder, too large, unreadable) is the empty list, never a failure of the call. ``text`` replaces the reading (a test)."""

    def __init__(self, home=None, *, text=None):
        self.home, self.text, self.terms, self.thread = home, text, [], None

    def read(self):
        try:
            text = self.text
            if text is None:
                home = self.home or environment('HERMES_HOME')
                if not home:
                    return []
                from .material_pick import load_whole          # noqa: PLC0415
                text = load_whole(home)
            self.terms = base_terms(text)
        except Exception as error:                             # noqa: BLE001 - a hint for the ear, never a failure (said once, by the error type)
            self.terms = []
            logger.warning('echo-sync ear base terms unavailable reason=%s', reason_of(error))
        return self.terms

    def prime(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.read, name='echo-ear-base', daemon=True)
            self.thread.start()
        return self

    def __call__(self):
        return self.terms


def controller_hotwords(controller, base=None):
    """The bias for the next utterance: the waiting portion and the plain words of the whole answer (no numbers, no negation: C6), the terms of the base (E60, ``base``: a callable
    that gives a list of terms; ``BaseTerms``), and the command words (ear_sherpa)."""
    def hotwords():
        state = controller.state()
        return hotwords_for(waiting_portion(state), material=(state or {}).get('chunks'), base=base() if base else None)      # C6: the whole answer is the material (a rule of the ear, no key)
    return hotwords


def _detector():
    """The ear's speech detector (R-VAD): Silero VAD, or S0's energy rule where its model is missing."""
    from .local_ear import make_onset                   # noqa: PLC0415 - task S0's detector module, with the R-VAD engines
    return make_onset('silero')


_shared = None
_shared_lock = threading.Lock()


def shared_worker():
    """The process's one recognizer (sherpa-onnx), created with the first call that wants it."""
    global _shared
    with _shared_lock:
        if _shared is None:
            from .ear_sherpa import ear_engine          # noqa: PLC0415 - Russian always, English where its model is (U19-S7)
            _shared = EarWorker(ear_engine)
        return _shared


async def for_call_async(settings, controller, *, worker=None, report=None, clock=None, timeout=None, base=None):
    """``for_call`` with the speech detector built off the event loop, bounded (R-VAD): the Silero model is loaded in a thread and, if that takes more
    than ``timeout`` seconds (local_ear.ONSET_BUILD_TIMEOUT_S), the ear uses S0's energy rule. None when the profile's ``local_ear`` is off
    (nothing is built then). The ear starts when its detector is there; the call does not wait for it."""
    resolved = resolve(settings)
    if resolved['local_ear'] not in ('shadow', 'act'):
        return None
    from .local_ear import make_onset_async              # noqa: PLC0415
    detector = await make_onset_async('silero', timeout=timeout)
    return for_call(settings, controller, detector_factory=lambda: detector, worker=worker, report=report, clock=clock, base=base)


FLOW_PARTIAL_MS = 100             # f3-reaction: with ``flow_ahead`` the text so far every 100 ms of speech (w5-flow report: «каждые 100 мс»); it feeds ControlledMedia.ear_partial -> flow


def instant_partial_ms():
    from .instant import PARTIAL_MS                      # noqa: PLC0415
    return PARTIAL_MS


def for_call(settings, controller, *, detector_factory=None, worker=None, report=None, clock=None, base=None):
    """The ear of one call, or None: off unless the profile's ``local_ear`` is ``"shadow"`` or ``"act"``, and off when there is no speech
    detector. R-EAR-ACT: in "act" the ear is ``acting`` (the transport hands its verdicts to ``controller.ear_heard``) and tells the
    controller every start of speech (``controller.ear_onset``). Its clock is the controller's unless one is given. R-VAD: its speech
    detector is Silero VAD (energy rule where its model is missing)."""
    resolved = resolve(settings)
    mode = resolved['local_ear']
    if mode not in ('shadow', 'act'):
        return None
    try:
        detector = (detector_factory or _detector)()
    except Exception as error:                         # noqa: BLE001 - no detector in this build: no ear, the call goes on
        logger.warning('echo-sync ear state=unavailable reason=%s', reason_of(error))
        return None
    acting = mode == 'act'
    flow = acting      # f3-reaction: the controller's FlowAhead (always with an acting ear) reads the text so far
    voice = None
    if near_voice.enabled(settings):         # w9-ear-voice: the raw setting (``near_voice``: shadow | act), off by default; the journal gets the numbers, the gate acts only in ``act``
        voice = near_voice.NearGate(speaking=lambda: ear.current is not None, clock=clock or getattr(controller, 'clock', None) or time.monotonic, act=near_voice.mode(settings) == 'act', log=logger.info)
    ear = ShadowEar(worker or shared_worker(), controller_decider(controller), detector=detector, report=report,
                    clock=clock or getattr(controller, 'clock', None), hotwords=controller_hotwords(controller, base if base is not None else BaseTerms().prime()),
                    on_onset=controller.ear_onset if acting else None, acting=acting, on_speech=controller.ear_speech,
                    early_ms=resolved['ear_early_ms'] or None, partial_ms=FLOW_PARTIAL_MS if flow else instant_partial_ms() if acting or resolved['instant'] == 'on' else None,      # U54: an acting ear gives the text so far (the tail of the portion, ControlledMedia._ear_tail_note)
                    voice=voice, portion=lambda: waiting_portion(controller.state()),
                    lang=(lambda: controller.turn_lang.lang) if hasattr(controller, 'turn_lang') else None)
    if report is not None:
        from .call_trace import RECOGNIZERS          # noqa: PLC0415 - E07.2/U71: the trace says who recognizes the speech of this call (the cloud always, and this ear)
        report('input_readers', recognizers=list(RECOGNIZERS), ear=mode)
    if voice is not None and voice.act:
        controller.speaker_gate = voice      # w10 item 10 (w5-near act): somebody else's speech holds a cue only for the bounded times of near_voice.HoldPolicy (12 s first, 0.3 s next, 30 s unknown)
    controller.ear_speech(None, 'live')      # H3: the local ear keeps the tempo of the prompter, in either mode
    if resolved['prompt_pace'] == 'on' and hasattr(controller, 'pace_on'):
        controller.pace_on()       # W5: the wait of a start that stopped is the listener's own (echo_sync.pace)
    return ear
