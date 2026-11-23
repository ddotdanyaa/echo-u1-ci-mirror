"""A LOCAL trace of one phone call: ``<profile home>/logs/echo_calls/<YYYYMMDD-HHMMSS>-<call id>.jsonl`` (UX-trace).

Why: the owner's call of 2 Nov 21:46 could only be reconstructed from counters, because no transcripts are logged on phone calls: nobody
could tell what the cloud HEARD, what it ANSWERED (a cut answer and its restart), what the controller DECIDED about each repeat and what
was SPOKEN when. This file puts those side by side, with one monotonic clock, so the next test can be diagnosed from it.

One JSON object per line. ``t`` = milliseconds since the call opened (monotonic clock), ``ev`` = the kind of record:

    call_open       the header: call, wall (local time, ISO), mono_ms, decisions (are the controller's log lines visible?) + what the host adds
                    (U07-S1: build, code, flags - what the call runs, from build_info.fingerprint)
    stage           U07-S1 (U09): a stage of the opening before ready (trace_open, upstream_open, ready): name, ms since serve began. Labels and numbers only
    user_start      the cloud announced a turn of the speaker (id, start_ms, end_ms of the provider's input-audio clock when it carries them)
    user_final      the cloud's final transcript of a speaker turn: id, text, chars (+ truncated), start_ms, end_ms
    assistant_start / assistant_final   the cloud's answer, the text AS THE PROVIDER SENT IT (a cut answer is one more such record)
    provider        any other event of the cloud session, by type (the stream of text deltas is not recorded)
    decision        a controller decision: kind, reason, revision, index (+ the other tokens of the line) - the ``echo-sync decision`` log
                    lines of THIS call (see the tap below)
    cue             the text of a spoken response, at its first audio frame; cue_end (status) when it was played to the end;
                    cue_cut when the phone's audio buffer was cleared. Both carry first_ms / last_ms / frames: when the first and the
                    last PCM frame of that response were sent (ms since the call opened); a response that was dropped without a done
                    or a clear is closed as 'abandoned' by the next one, or as 'open' by the end of the call
    error           an error frame sent to the phone, by its code
    fast_job        H7: a job of the text channel that is over (``fast_text.FastText``): job, on (what it started on: ear, partial, final), after_ear_ms (its start against the ear's last offset), ttft_ms, chars, outcome, reason, released, adopted,
                    first (its first letters), the numbers of ``usage`` of ``response.completed``
    fast_adopted    H7: a release took a prepared job: job, on, ms (how long it has run), ready_ms (how long its first text has been waiting)
    fast_partial    H7: a partial of the cloud stood still with the ear silent: id, text, prepared (1: it got a job, 0: the filter said no)
    fast_refused    H7: a prepared job was refused: job, rule (released, failed, old, played, numbers, words, alike, empty, broken), on, heard (its text), asked (the text it was refused for), ms (its age)
    judge           U15-S2: the ``echo-sync judge`` line of the utterance judge, one per utterance: rule (which rule decided), chain (the rules it passed), analyses (how many times analyze ran), tid. Labels and numbers only
    ready           the handshake is over: the phone may send its microphone (the marker response.done without a response id)
    mic             the phone's microphone packets of ONE second: sec, n (packets), bytes (PCM), first_ms, last_ms (arrival of the first
                    and of the last of them). Numbers only, never audio. A second with no packet has no line: a gap between two lines
                    is the microphone being closed, and first_ms / last_ms are its exact edges. mic_full: the lines' own budget is spent
    duplex          the summary of the call, written at its end: verdict 'half' | 'full' | 'unknown' (did the microphone keep sending
                    while a cue played? see DuplexMeter), packets, mean_packet_ms, ready_s, cues, cue_span_s, mic_missing_cue_s,
                    mic_missing_idle_s, cue_coverage, idle_coverage (DUAL_SYSTEM_DESIGN.md sections 1.2-1.4)
    witness         the answer witness (always, nothing is said): the job's leading number against the first sentence with a number of the cloud's reply: verdict (agree, differ), job, reply, asked, said, sentence; witness_third: when they differ, what the third
                    source says: side (job, live, none), source, proposal (the correction it would have said, nothing is said), passages, ms
    live_delta      ``live_first``: a piece of the cloud's reply as it came (id, text, chars), its first LIVE_DELTAS: what the text of its fragments was and when; live_audio: the cloud's own voice began after LIVE_QUIET_S of none (peak): the moment
                    of its audio against its text. Numbers only: that audio is never kept, and it is dropped as ever (the frames ``p``, ``controlled_host``)
    trace_full      the size cap was reached: nothing more is written except the closing lines
    call_close      the end of the call, with what the host adds (elapsed_ms, ready, counters, U07-S1: close_code - the socket's code when it has one -, closer: phone, cloud or host; U107: spend - what the call asked of the first road and the reserve, requests and tokens, numbers only)

The file is LOCAL. This module imports nothing that talks to a network or starts a program (a test pins it); the host never sends the
file or its content to the phone. It is bounded - the newest ``KEEP_FILES`` files stay, a file stops at ``MAX_FILE_BYTES``, a text is cut
at ``MAX_TEXT_CHARS`` - and it can NEVER affect a call: every hook swallows its own failure (a full disk, a locked folder, a bug), the
first failure switches the trace off for the rest of the call and is logged once, by the type of the error and never by the path.
"""
import array
import contextvars
import json
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from .lang_hint import lang_hint
from .why_journal import PREFIX as WHY_PREFIX

logger = logging.getLogger('echo-sync')

# The newest this many files stay in the folder (13.11: 400, was 50: a server probe is a call too, and six probes after a deploy pushed the owner's real calls towards the edge); the files of other names are never touched.
KEEP_FILES = 400
# One file stops growing here (13.11: 8 MB, was 1 MB: on the night stand 1 MB was full at minute 58 of a dense call and at minute 37 with the facts journal and the shadows on, so three such hours take about 5 MB); the closing lines still fit in the reserve below the cap.
MAX_FILE_BYTES = 8_000_000
RESERVE_BYTES = 2048
# The per-second microphone lines may use this much of a file (13.11: 1 MB, about 3 h 45 min of a call; was 200 kB, about 45 minutes); after that only the summary has the numbers.
MIC_BUDGET_BYTES = 1_000_000
# A text (a transcript, an answer) is cut here; ``chars`` keeps its real length. The policy asks the model for short answers.
MAX_TEXT_CHARS = 2000
# ``live_first``: the pieces of a reply of the cloud that are written, and what counts as the start of its voice: a peak over LIVE_VOICED after LIVE_QUIET_S with none (the rule of the probes: >300).
LIVE_DELTAS = 24
LIVE_VOICED = 300
LIVE_QUIET_S = 0.3

# The audio the phone sends and the cues the transport paces: 24 kHz, 16-bit, mono = 48,000 bytes a second; a cue goes out in 960-byte frames.
PCM_BYTES_PER_SECOND = 48000
FRAME_S = 0.02
# The duplex verdict (DuplexMeter.summary). Less cue time or fewer packets than these says nothing; the microphone audio that arrived
# while a cue was in flight, as a share of the cue time, up to HALF_MAX is half duplex, from FULL_MIN on full duplex, in between unknown.
# Half duplex also needs the microphone to be working while no cue plays (IDLE_MIN), else the phone is muted and nothing was measured.
DUPLEX_MIN_CUE_S = 2.0
DUPLEX_MIN_PACKETS = 20
DUPLEX_HALF_MAX = 0.25
DUPLEX_FULL_MIN = 0.75
DUPLEX_IDLE_MIN = 0.5
DUPLEX_MIN_IDLE_S = 2.0
# U37: a hole in the microphone is a stretch with no packet of at least MIC_HOLE_S. Its cause: a cue in flight or MIC_CUE_GUARD_S after it (the
# phone's echo guard), else a DROP when what is left of it lasts MIC_DROP_S or more (the 10-15 s drops of the owner's calls), else a SWITCH (a short
# hole: a route / mode switch, the server cannot tell which). Data for the owner's decision on the client, not a verdict.
MIC_HOLE_S = 0.25
MIC_CUE_GUARD_S = 0.65
MIC_DROP_S = 10.0
MIC_HOLES_KEPT = 50
MIC_SPANS_MAX = 4000

DECISION_PREFIX = 'echo-sync decision '
JUDGE_PREFIX = 'echo-sync judge '
_FILE = re.compile(r'^\d{8}-\d{6}-[0-9A-Za-z]{1,32}\.jsonl$')
_ERROR_CODE = re.compile(r'[a-zA-Z0-9_]{1,80}')
_TOKEN = re.compile(r'(\w{1,32})=(\S*)')
_INT = re.compile(r'-?\d{1,15}')
_FLOAT = re.compile(r'-?\d{1,15}\.\d{1,12}')

# E07.2 (R22): the map of the paths of the input, as DATA beside the meter that counts it, held by tests/test_ea_input_map.py (every ``owner`` is a real
# ``module:Symbol``, every ``proof`` is a real test file): a path nobody can name here is not a path; a new reader of the phone's PCM is one more row.
# One stream - the phone's PCM16 mono 24 kHz, packets of about 100 ms, NO sequence number on the wire (the server stamps its own, ``mic_facts``) - and several
# readers of the SAME packets (a second reader is not a second source: what the phone did not send no reader brings back).
# Columns: id, what it is for, what switches it, owners (module:Symbol), format and clock, keep, proof (a test file), cost (U71: a measured figure, or what is NOT measured).
INPUT_PATHS = (
    ('wire', "the phone's microphone to the laptop", 'always after ready', ('native_media_socket:NativeMediaSocket.client', 'controlled_host:serve'),
     'input_audio_buffer.append, base64 PCM16 mono 24 kHz, <= 96000 B; no seq on the wire', 'nowhere (the trace counts them)', 'test_native_media_socket.py', 'not measured'),
    ('cloud', "the cloud's recognition (GPT-Live): the questions and the answers; the only reader of every utterance", 'always (no key)',
     ('helper_bridge:BoundedWriter', 'native_media_socket:NativeMediaSocket.client'),
     'helper frame P + PCM, resampled to 48 kHz inside the helper process, queue <= 2 s', 'user_final text in the trace', 'test_native_media_socket.py', 'in the helper process, not in the server thread; not measured'),
    ('clock', 'input_ms: the milliseconds of sound forwarded, the clock of the ear and of the controller', 'always', ('native_media_socket:NativeMediaSocket.input_ms',),
     'bytes / 48000', 'none', 'test_native_media_socket.py', 'no cost'),
    ('onset', 'detector 1: «the owner began to speak» (stops the auto-repeat, holds a new cue)', 'always; engine silero (energy where its model is missing)',
     ('native_media_socket:NativeMediaSocket._listen', 'local_ear:SpeechOnset', 'vad_silero:SileroOnset', 'local_ear:make_onset'),
     'Silero window of 512 samples at 16 kHz, or the energy rule on 20 ms frames', 'numbers in the log, no sound', 'test_s0_local_onset.py',
     'Silero is shared with the ear (loop_guard.SharedOnset): one inference per packet; its cost on a call is not measured'),
    ('ear', 'the local ear: sherpa-onnx text of an utterance for the acknowledge / repeat / stop / continue commands and the text channel', 'local_ear off | shadow | act (default off)',
     ('ear_shadow:ShadowEar', 'ear_shadow:EarWorker', 'ear_shadow:for_call'),
     'ring of 4 packets before the start, queue <= 3 s, one utterance <= 15 s per stream, ONE worker thread with one model thread', 'ear_final text in the trace', 'test_s5_ear_part.py',
     'RTF 0.11-0.13 of CPU time on one thread, N95, 05.11 (ANALYSIS_20261105/14_EAR_N2.md, loaded machine: CPU time counts, wall time does not); on a call not measured'),
    ('trace', 'the trace and its counters: what came, when, the gaps, «did the phone keep sending while a cue played»', 'always on a phone call (no key)',
     ('call_trace:CallTrace.mic', 'call_trace:DuplexMeter'), 'per second n / bytes / first_ms / last_ms; mic_gap, mic_back, mic_facts, ready_verdict', 'the newest files of logs/echo_calls',
     'test_v5_step0_facts.py', 'written by a thread off the loop; not measured'),
    ('record', "the sound of the call (the phone's microphone and the cues): the one file of the owner's voice", 'always on a phone call (the standing rule, no key); a probe: echo_pcm_record=1',
     ('call_audio:CallAudio', 'call_audio:prune'), 'WAV PCM16 mono 24 kHz per channel + timeline.jsonl, a bounded queue and a cap per call', 'pcm_record_calls newest calls, pcm_record_mb in all',
     'test_u07_call_audio.py', 'a writer thread, disk only; not measured'),
    ('state', "the state of the listener's input in one window after a cue (dead input, quiet speech, no text)", 'always', ('input_state:InputMeter', 'input_state:InputMeter.repeat_action'),
     'packets with their level, VAD speech, ear text', 'none (memory)', 'test_u17_input_state.py', 'counters only'),
)
# U71, what recognizes the speech of one call: TWO readers - the cloud (every utterance) and the local ear (only with local_ear shadow or act). There is no third: no Smart Turn
# in the code (a backlog idea, E29.1), and the synthesis of a cue is an OUTPUT path (the sapi worker), not an input one.
RECOGNIZERS = ('cloud', 'ear')


# The trace of the call whose tasks are running right now. The ``echo-sync decision`` lines carry no call id, and a probe (or a second
# call) may share the process and the logger: a line belongs to the trace whose call it was logged in, found through the context that
# every task of a call inherits (the trace is opened before the call's tasks are created).
_CURRENT = contextvars.ContextVar('echo_call_trace', default=None)


def _short(value, limit=64):
    return None if value is None else str(value)[:limit]


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _clip(value, limit):
    """``{'text', 'chars'[, 'truncated']}``: the text cut at ``limit`` and its real length."""
    text = value if isinstance(value, str) else ('' if value is None else str(value))
    clipped = {'text': text[:limit], 'chars': len(text)}
    if len(text) > limit:
        clipped['truncated'] = True
    return clipped


def _plain(value):
    return str(value)[:200]


def _scalar(value):
    """A token of a decision line as the number or the word it is."""
    if value == 'None':
        return None
    if _INT.fullmatch(value):
        return int(value)
    if _FLOAT.fullmatch(value):
        return float(value)
    return value[:64]


def _pcm_length(audio):
    """The number of PCM bytes in a base64 string, from its length alone (the audio is never decoded or looked at here)."""
    n = len(audio)
    if n % 4:
        return n * 3 // 4
    return n // 4 * 3 - (2 if audio.endswith('==') else 1 if audio.endswith('=') else 0)


class DuplexMeter:
    """What the phone's microphone did while the cues played - bookkeeping only (no file, no log, never audio), on one clock in seconds.

    The research (DUAL_SYSTEM_DESIGN.md 1.2-1.4): on the open speaker the Conduit client DROPS its microphone packets while it plays our cue
    (half duplex) and for ~0.35 s after it; with headphones, or with the "talk over" switch, it keeps sending (full duplex). So the audio
    that arrives while a cue is in flight - from its first PCM frame to its last - as a share of the time that cue took says which.
    ``cue_coverage`` is that share. 'half' = 0.25 or less (and the microphone works when no cue plays), 'full' = 0.75 or more, anything in
    between, too little cue time, or too few packets = 'unknown'. The audio time of a packet is its length (48,000 bytes a second)."""

    def __init__(self, anchor):
        self.anchor = anchor                 # the per-second counts start counting here (the moment the trace opened)
        self.ready_at = None                 # the handshake marker, else the first packet (minus its own length)
        self._marked = False                 # the handshake marker has been seen
        self.packets = 0
        self.pcm_bytes = 0
        self.audio_in_cue_s = 0.0            # audio that arrived while a cue was in flight
        self.audio_idle_s = 0.0              # audio that arrived while none was
        self.cue_span_s = 0.0                # the time the finished cues took, first PCM frame to last (+ one frame)
        self.cues = 0
        self._cue = None                     # the spoken response in flight: {'first', 'last', 'frames'} in seconds
        self._second = None                  # the per-second count being filled
        self._spans = []                     # U37: [start, end] of the audio that arrived (packets less than MIC_HOLE_S apart are one span)
        self._cue_spans = []                 # U37: (first, last + one frame) of every cue that was sent

    def ready(self, now):
        """The call is ready, True the first time only, even when a microphone packet came first."""
        if self._marked:
            return False
        self._marked = True
        if self.ready_at is None:
            self.ready_at = now
        return True

    def packet(self, now, nbytes):
        """One packet of the phone's microphone arrived. Returns the per-second count that this packet has just finished, if any."""
        if self.ready_at is None:
            self.ready_at = now - nbytes / PCM_BYTES_PER_SECOND
        self.packets += 1
        self.pcm_bytes += nbytes
        self._span(now - nbytes / PCM_BYTES_PER_SECOND, now)
        if self._cue is not None and self._cue['first'] is not None:
            self.audio_in_cue_s += nbytes / PCM_BYTES_PER_SECOND
        else:
            self.audio_idle_s += nbytes / PCM_BYTES_PER_SECOND
        index = int(now - self.anchor)
        finished = None
        if self._second is not None and self._second['sec'] != index:
            finished, self._second = self._second, None
        if self._second is None:
            self._second = {'sec': index, 'n': 0, 'bytes': 0, 'first': now, 'last': now}
        self._second['n'] += 1
        self._second['bytes'] += nbytes
        self._second['last'] = now
        return finished

    def flush(self):
        """The per-second count still being filled (at the end of the call)."""
        finished, self._second = self._second, None
        return finished

    def response_created(self):
        """A spoken response begins. Returns the one still in flight if it was never ended (it was dropped without a done or a clear)."""
        dropped = self.end_response()
        self._cue = {'first': None, 'last': None, 'frames': 0}
        return dropped

    def audio_frame(self, now):
        """A PCM frame of the response in flight was sent."""
        cue = self._cue
        if cue is not None:
            if cue['first'] is None:
                cue['first'] = now
            cue['last'] = now
            cue['frames'] += 1

    def end_response(self):
        """The response in flight is over (done, cleared, replaced, or the call ended). Its ``first`` / ``last`` / ``frames``, or None."""
        cue, self._cue = self._cue, None
        if cue is not None and cue['first'] is not None:
            self.cue_span_s += cue['last'] - cue['first'] + FRAME_S
            if len(self._cue_spans) < MIC_SPANS_MAX:
                self._cue_spans.append((cue['first'], cue['last'] + FRAME_S))
            self.cues += 1
        return cue

    def _span(self, start, end):
        spans = self._spans
        if spans and start - spans[-1][1] < MIC_HOLE_S:
            spans[-1][1] = max(spans[-1][1], end)
        elif len(spans) < MIC_SPANS_MAX:
            spans.append([start, end])

    def holes(self, now):
        """U37: the coverage of the microphone from ``ready_at`` to ``now`` by the CAUSE of each hole: (coverage, {cue, drop, switch} seconds,
        [{start_ms, end_ms, s, cause, cue_s}]). The seconds add up to the window less the covered time."""
        zero = {'cue': 0.0, 'drop': 0.0, 'switch': 0.0}
        if self.ready_at is None or now <= self.ready_at:
            return None, zero, []
        edges, at, found = [], self.ready_at, []
        for a, b in self._spans:
            if a - at >= MIC_HOLE_S:
                found.append((at, a))
            at = max(at, b)
        if now - at >= MIC_HOLE_S:
            found.append((at, now))
        by, listed = dict(zero), []
        for a, b in found:
            cue = sum(max(0.0, min(b, c1 + MIC_CUE_GUARD_S) - max(a, c0)) for c0, c1 in self._cue_spans)
            cue = min(cue, b - a)
            rest = b - a - cue
            if rest < MIC_HOLE_S:
                cue, rest = cue + rest, 0.0
            kind = 'drop' if rest >= MIC_DROP_S else 'switch'
            by['cue'] += cue
            if rest:
                by[kind] += rest
            if len(listed) < MIC_HOLES_KEPT:
                listed.append({'start_ms': round((a - self.anchor) * 1000), 'end_ms': round((b - self.anchor) * 1000), 's': round(b - a, 2),
                               'cause': 'cue' if cue >= rest else kind, 'cue_s': round(cue, 2)})
        window = now - self.ready_at
        return max(0.0, 1 - sum(by.values()) / window), by, listed

    def summary(self, now):
        """The numbers of the call so far (``now`` ends the idle time). Seconds are rounded to 10 ms, shares to 0.1 %."""
        window = max(0.0, now - self.ready_at) if self.ready_at is not None else 0.0
        idle_span = max(0.0, window - self.cue_span_s)
        cue_coverage = self.audio_in_cue_s / self.cue_span_s if self.cue_span_s > 0 else None
        idle_coverage = self.audio_idle_s / idle_span if idle_span >= DUPLEX_MIN_IDLE_S else None
        verdict = 'unknown'
        if cue_coverage is not None and self.cue_span_s >= DUPLEX_MIN_CUE_S and self.packets >= DUPLEX_MIN_PACKETS:
            if cue_coverage >= DUPLEX_FULL_MIN:
                verdict = 'full'
            elif cue_coverage <= DUPLEX_HALF_MAX and (idle_coverage is None or idle_coverage >= DUPLEX_IDLE_MIN):
                verdict = 'half'
        coverage, by, listed = self.holes(now)
        return {'verdict': verdict, 'packets': self.packets,
                'mean_packet_ms': round(self.pcm_bytes / self.packets / PCM_BYTES_PER_SECOND * 1000, 1) if self.packets else 0.0,
                'ready_s': round(window, 2), 'cues': self.cues, 'cue_span_s': round(self.cue_span_s, 2),
                'mic_missing_cue_s': round(max(0.0, self.cue_span_s - self.audio_in_cue_s), 2),
                'mic_missing_idle_s': round(max(0.0, idle_span - self.audio_idle_s), 2),
                'cue_coverage': None if cue_coverage is None else round(cue_coverage, 3),
                'idle_coverage': None if idle_coverage is None else round(idle_coverage, 3),
                'mic_coverage': None if coverage is None else round(coverage, 3), 'mic_gap_s': {k: round(v, 2) for k, v in by.items()}, 'mic_gaps': listed}


def _for_log(summary):
    """The numbers the host adds to the "Controlled call closed" line of the agent log: a verdict and seconds, nothing else."""
    return {'duplex': summary['verdict'], 'mic_packet_ms': summary['mean_packet_ms'], 'mic_missing_cue_s': summary['mic_missing_cue_s'],
            'mic_missing_idle_s': summary['mic_missing_idle_s'], 'cue_span_s': summary['cue_span_s']}


class _DecisionTap(logging.Handler):
    """Hands the ``echo-sync decision …`` log lines of ONE call to its trace. The lines hold no words of the conversation by design."""

    def __init__(self, trace):
        super().__init__(level=logging.INFO)
        self.trace = trace
        self._busy = False

    def emit(self, record):
        if self._busy or _CURRENT.get() is not self.trace:
            return
        self._busy = True
        try:
            message = record.getMessage()
            if message.startswith(DECISION_PREFIX):
                self.trace.decision(message)
            elif message.startswith(JUDGE_PREFIX):
                self.trace.judge(message)
            elif message.startswith(WHY_PREFIX) and self.trace.facts:
                self.trace.why(message)
        except Exception:
            pass
        finally:
            self._busy = False


class CallTrace:
    """The trace of one call. ``directory=None`` keeps no file (the setting is off, or this is a probe): nothing is written or listened for,
    but the duplex numbers are still measured, because ``close()`` hands them to the agent log.

    ``clock`` is the monotonic clock (seconds) the host runs on; ``t`` of a record is its difference to the moment ``open`` ran."""

    def __init__(self, directory, call_id, *, clock=None, keep=KEEP_FILES, max_bytes=MAX_FILE_BYTES, max_text=MAX_TEXT_CHARS, threaded=False,
                 facts=False, mic_gap_ms=1500, mic_ring_s=60):
        self.threaded = threaded
        self.facts = bool(facts)             # V5 step 0 (the host always sets it: no key): the arrival stamps, mic_gap / mic_back, the ring, why, ready_verdict
        self.directory = Path(directory) if directory else None
        self.call_id = re.sub(r'[^0-9A-Za-z]', '', str(call_id))[:32] or 'call'
        self.clock = clock or time.monotonic
        self.keep, self.max_bytes, self.max_text = max(1, int(keep)), int(max_bytes), int(max_text)
        self.path = None
        self.failure = None                  # the type name of the error that switched the trace off, else None
        self.live_watch = False              # ``live_first``: the host sets it: ``live_delta``, ``live_audio``
        self._replies, self._voice_at = {}, None
        self._file = None
        self._origin = None
        self._size = 0
        self._full = False
        self._tap = None
        self._lock = threading.RLock()
        # The duplex numbers are kept for every call, trace file or not: the agent log wants them even when call_trace is off.
        self.meter = DuplexMeter(self.clock())
        self._mic_bytes = 0
        self._mic_full = False
        self._logged = None                  # the numbers close() returned: set once the call has been closed
        self.mic_gap_s = max(0.2, int(mic_gap_ms) / 1000)
        self._seq = self._samples = self._gaps = 0       # V5 step 0: the server's own counter of the appends and of the received samples
        self._first_at = self._last_at = None
        self._gap_told = False               # a gap that is open has been written (once)
        self._ring = deque(maxlen=max(1, int(mic_ring_s)))     # the last seconds after the microphone line budget is spent
        self._verdict = False

    @property
    def active(self):
        return self._file is not None

    # --- opening and closing ------------------------------------------------------------------------------------------------

    def open(self, **header):
        """Create the file, prune the folder, write the header (``header`` goes into it) and start listening for the decisions of this
        call. True when the trace is on; False when it cannot be (nothing is raised, the reason is logged once)."""
        if self.directory is None:
            return False
        with self._lock:
            if self._file is not None or self._origin is not None:
                return False
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                self.path = self.directory / f'{datetime.now().strftime("%Y%m%d-%H%M%S")}-{self.call_id}.jsonl'
                # Line buffered: every record reaches the operating system at once, so a crash leaves the trace up to that moment.
                self._file = open(self.path, 'a', encoding='utf-8', errors='replace', newline='\n', buffering=1)
                if self.threaded:
                    from .loop_guard import ThreadedFile      # noqa: PLC0415 - w9-loop N111: the write leaves the loop
                    self._file = ThreadedFile(self._file)
                self._origin = self.clock()
                self.meter.anchor = self._origin
                self._prune()
                self._listen()
                fields = {'call': self.call_id, 'wall': datetime.now().astimezone().isoformat(timespec='seconds'),
                          'mono_ms': int(self._origin * 1000), 'decisions': logger.isEnabledFor(logging.INFO)}
                fields['input_paths'] = [row[0] for row in INPUT_PATHS]          # E07.2: the paths of the input of this call, from the map (the readers that join add 'input_readers')
                for key, value in header.items():
                    fields.setdefault(key, value)
                self._emit('call_open', fields)
                return True
            except Exception as error:
                self._fail(error)
                return False

    def close(self, **fields):
        """The end of the call: the last second of the microphone, the summary of the duplex numbers and the closing line (``fields`` goes
        into it), then the file is closed. Returns the numbers for the agent log (``_for_log``; ``{}`` if they could not be made). Safe to
        call again - it returns the same numbers and writes nothing - and after a failure of the file. It runs in the host's ``finally``,
        before the cleanup of the call: nothing that goes wrong in it may escape."""
        try:
            return self._close(fields)
        except Exception as error:
            self._fail(error)
            return dict(self._logged or {})

    def _close(self, fields):
        with self._lock:
            if self._logged is not None:
                return dict(self._logged)
            self._logged = {}
            self._unlisten()
            summary = None
            try:
                last = self.meter.flush()
                if last is not None:
                    self._write_second(last)
                self._write_span('cue_end', self.meter.end_response(), 'open', only_started=True)
                summary = self.meter.summary(self.clock())
                self._logged = _for_log(summary)
            except Exception:
                summary = None
            if self._file is not None:
                try:
                    if self.facts:
                        self._mic_close_facts()
                    if summary is not None:
                        self._emit('duplex', summary, closing=True)
                    self._emit('call_close', fields, closing=True)
                except Exception as error:
                    self._fail(error)
            handle, self._file = self._file, None
            if handle is not None:
                try:
                    handle.close()
                except Exception as error:
                    self.failure = type(error).__name__
            return dict(self._logged)

    # --- what the host reports ------------------------------------------------------------------------------------------------

    def note(self, ev, **fields):
        """One record of kind ``ev``."""
        self._record(ev, fields)

    def provider(self, event):
        """One event of the cloud session, as the host's reader received it (the host calls this BEFORE the controller sees it, so
        the decisions it causes follow it in the file)."""
        if self._file is None or not isinstance(event, dict):
            return
        try:
            kind = event.get('type')
            if self.live_watch and kind == 'turn.delta':
                self._live_delta(event)
            if not isinstance(kind, str) or kind == 'turn.delta':
                return
            turn = event.get('turn')
            if self.live_watch and kind == 'turn.created' and isinstance(turn, dict) and turn.get('role') == 'assistant':
                self._replies[turn.get('id')] = 0
            if kind in ('turn.created', 'turn.done') and isinstance(turn, dict) and turn.get('role') in ('user', 'assistant'):
                fields = {'id': _short(turn.get('id'))}
                for key in ('start_ms', 'end_ms'):
                    if _number(turn.get(key)) is not None:
                        fields[key] = turn[key]
                if kind == 'turn.done':
                    fields.update(_clip(turn.get('transcript'), self.max_text))
                    if turn['role'] == 'user':
                        fields['lang'] = lang_hint(turn.get('transcript') if isinstance(turn.get('transcript'), str) else '')
                    self._record(turn['role'] + '_final', fields)
                else:
                    self._record(turn['role'] + '_start', fields)
                return
            fields = {'type': _short(kind)}
            item = event.get('item')
            if isinstance(item, dict):
                if item.get('id') is not None:
                    fields['id'] = _short(item['id'])
                if item.get('user_bidi_turn_id') is not None:
                    fields['for_turn'] = _short(item['user_bidi_turn_id'])
            self._record('provider', fields)
        except Exception:
            return

    def _live_delta(self, event):
        """``live_first``: a piece of a reply of the cloud, with the moment it came. On 6 Nov the text of the fragments was not there and the moment of its first substance was an estimate."""
        tid = event.get('turn_id')
        count = self._replies.get(tid)
        if count is not None and count < LIVE_DELTAS:
            self._replies[tid] = count + 1
            self._record('live_delta', {'id': _short(tid), **_clip(event.get('delta'), self.max_text)})

    def live_audio(self, pcm):
        """``live_first``: one frame of the cloud's own audio (16-bit, on every 8th sample): when its voice begins. Numbers only: the audio is never kept. It can never touch a call."""
        try:
            samples = array.array('h')
            samples.frombytes(pcm[:len(pcm) // 2 * 2])
            peak = max((abs(sample) for sample in samples[::8]), default=0)
            if peak < LIVE_VOICED:
                return
            now = self.clock()
            if self._voice_at is None or now - self._voice_at >= LIVE_QUIET_S:
                self._record('live_audio', {'peak': peak})
            self._voice_at = now
        except Exception:
            return

    def frame(self, frame):
        """One frame the host sends to the phone: a spoken response (its text, its first and last PCM frame, its end or cut) and the
        errors. The audio is never recorded - only when its frames were sent. The duplex meter follows the frames even when no file is kept."""
        if not isinstance(frame, dict):
            return
        try:
            kind = frame.get('type')
            if kind == 'response.audio.delta':
                self.meter.audio_frame(self.clock())
            elif kind == 'response.created':
                self._write_span('cue_end', self.meter.response_created(), 'abandoned', only_started=True)
            elif kind == 'response.audio_transcript.delta':
                self._record('cue', _clip(frame.get('delta'), self.max_text))
            elif kind == 'response.done':
                response = frame.get('response')
                if isinstance(response, dict) and response.get('id') is not None:
                    self._write_span('cue_end', self.meter.end_response(), _short(response.get('status')))
                elif self.meter.ready(self.clock()):
                    # The ready marker of the handshake: a response.done with no id of a spoken response. The phone may send its microphone now.
                    self._record('ready', {})
            elif kind == 'output_audio_buffer.clear':
                self._write_span('cue_cut', self.meter.end_response(), None)
            elif kind == 'error':
                error = frame.get('error')
                code = str(error.get('code', '')) if isinstance(error, dict) else ''
                self._record('error', {'code': code if _ERROR_CODE.fullmatch(code) else 'redacted_error'})
        except Exception:
            return

    def mic(self, event):
        """One ``input_audio_buffer.append`` of the phone: when it arrived and how long it is. Numbers only - the audio is never decoded."""
        try:
            audio = event.get('audio') if isinstance(event, dict) else None
            if not isinstance(audio, str) or not audio or self._logged is not None:
                return
            now, nbytes = self.clock(), _pcm_length(audio)
            finished = self.meter.packet(now, nbytes)
            if self.facts:
                self._mic_fact(now, nbytes)
            if finished is not None:
                self._write_second(finished)
        except Exception:
            return

    def _mic_fact(self, now, nbytes):
        """V5 step 0: stamp the append (its number, its arrival, its samples) and write the gap that this packet ends. The cause is always ``unknown``:
        the server cannot tell a muted phone, a dropped link and a silent room apart, and a missing packet is not silence."""
        last = self._last_at
        if last is not None and now - last > self.mic_gap_s:
            gap_ms = int(round((now - last) * 1000))
            if not self._gap_told:
                self._gaps += 1
                self._record('mic_gap', {'start_ms': self._rel_ms(last), 'end_ms': self._rel_ms(now), 'gap_ms': gap_ms, 'cause': 'unknown', 'seq_before': self._seq, 'seq_after': self._seq + 1})
            self._record('mic_back', {'at_ms': self._rel_ms(now), 'gap_ms': gap_ms, 'seq': self._seq + 1})
        self._gap_told = False
        self._seq += 1
        self._samples += nbytes // 2
        self._last_at = now
        if self._first_at is None:
            self._first_at = now

    def mic_watch(self):
        """V5 step 0: called by the host's tick. No append for longer than the tolerance while the call is open is written once as an OPEN gap
        (the packet that ends it, if any, writes ``mic_back``). Nothing before the first packet; nothing when the switch is off."""
        try:
            if not self.facts or self._last_at is None or self._gap_told or self._file is None or self._logged is not None:
                return
            now = self.clock()
            if now - self._last_at > self.mic_gap_s:
                self._gap_told = True
                self._gaps += 1
                self._record('mic_gap', {'start_ms': self._rel_ms(self._last_at), 'end_ms': self._rel_ms(now), 'gap_ms': int(round((now - self._last_at) * 1000)),
                                         'cause': 'unknown', 'open': True, 'seq_before': self._seq})
        except Exception:
            return

    def _mic_close_facts(self):
        """At the close, inside the reserve: a gap still open, the ring, the counts."""
        now = self.clock()
        if self._last_at is not None and not self._gap_told and now - self._last_at > self.mic_gap_s:
            self._gaps += 1
            self._emit('mic_gap', {'start_ms': self._rel_ms(self._last_at), 'end_ms': self._rel_ms(now), 'gap_ms': int(round((now - self._last_at) * 1000)),
                                   'cause': 'unknown', 'open': True, 'seq_before': self._seq}, closing=True)
        if self._mic_full and self._ring:
            self._emit('mic_tail', {'secs': [[r[0], r[1], r[2]] for r in self._ring]}, closing=True)
        self._emit('mic_facts', {'appends': self._seq, 'samples': self._samples, 'gaps': self._gaps, 'seconds_kept': len(self._ring),
                                 'first_ms': None if self._first_at is None else self._rel_ms(self._first_at),
                                 'last_ms': None if self._last_at is None else self._rel_ms(self._last_at)}, closing=True)

    def _ready_verdict(self):
        """V5 step 0 (d): once, after the first cue of the call ended or was cut: did the microphone packets keep arriving while it played
        (the DuplexMeter's numbers), and the plain reason when not."""
        if self._verdict or not self.facts:
            return
        self._verdict = True
        m = self.meter
        coverage = m.audio_in_cue_s / m.cue_span_s if m.cue_span_s > 0 else None
        if m.packets == 0:
            kept, reason = False, 'no_packets_at_all_since_the_call_opened'
        elif coverage is None or m.cue_span_s < 0.5:
            kept, reason = None, 'cue_too_short_to_judge'
        elif coverage >= DUPLEX_FULL_MIN:
            kept, reason = True, 'packets_kept_arriving'
        elif coverage <= DUPLEX_HALF_MAX:
            kept, reason = False, 'no_packets_while_the_cue_played: the phone does not send its microphone during a cue (open speaker, or muted)'
        else:
            kept, reason = None, 'packets_arrived_only_part_of_the_cue_time'
        self._record('ready_verdict', {'mic_kept': kept, 'reason': reason, 'coverage': None if coverage is None else round(coverage, 3),
                                       'cue_span_s': round(m.cue_span_s, 2), 'audio_in_cue_s': round(m.audio_in_cue_s, 2), 'packets': m.packets})

    def decision(self, message):
        """A line ``echo-sync decision kind=… reason=… revision=… index=…`` as a record (the tap calls this)."""
        fields = {}
        for key, value in _TOKEN.findall(message[len(DECISION_PREFIX):])[:16]:
            fields.setdefault(key, _scalar(value))
        self._record('decision', fields)

    def why(self, message):
        """V5 step 0 (b): a line ``echo-sync why kind=… subject=… rule=… const=…`` as a record (the tap calls this)."""
        fields = {}
        for key, value in _TOKEN.findall(message[len(WHY_PREFIX):])[:16]:
            fields.setdefault(key, _scalar(value))
        self._record('why', fields)

    def judge(self, message):
        """U15-S2: a line ``echo-sync judge rule=… chain=… analyses=…`` as a record (the tap calls this)."""
        fields = {}
        for key, value in _TOKEN.findall(message[len(JUDGE_PREFIX):])[:16]:
            fields.setdefault(key, _scalar(value))
        self._record('judge', fields)

    # --- inside ---------------------------------------------------------------------------------------------------------------

    def _record(self, ev, fields):
        if self._file is None:
            return
        with self._lock:
            if self._file is None:
                return
            try:
                self._emit(ev, fields)
            except Exception as error:
                self._fail(error)

    def _ms(self):
        return max(0, int(round((self.clock() - self._origin) * 1000)))

    def _rel_ms(self, seconds):
        """A moment of the monotonic clock as milliseconds since the call opened."""
        if self._origin is None:
            return 0
        return int(round((seconds - self._origin) * 1000))

    def _write_second(self, second):
        """The count of one finished second of the phone's microphone as a record, inside the lines' own budget (MIC_BUDGET_BYTES)."""
        if self._file is None:
            return
        if self._mic_full:
            if self.facts:
                self._ring.append((second['sec'], second['n'], second['bytes']))      # V5 step 0: the budget is a ring in memory, written once at the close
            return
        with self._lock:
            if self._file is None or self._mic_full:
                return
            try:
                if self._mic_bytes >= MIC_BUDGET_BYTES:
                    self._mic_full = True
                    self._emit('mic_full', {'budget_bytes': MIC_BUDGET_BYTES})
                    if self.facts:
                        self._ring.append((second['sec'], second['n'], second['bytes']))
                    return
                self._mic_bytes += self._emit('mic', {'sec': second['sec'], 'n': second['n'], 'bytes': second['bytes'],
                                                      'first_ms': self._rel_ms(second['first']), 'last_ms': self._rel_ms(second['last'])})
            except Exception as error:
                self._fail(error)

    def _write_span(self, ev, span, status, *, only_started=False):
        """``cue_end`` / ``cue_cut`` with the span of the response: when its first and its last PCM frame were sent, and how many.
        ``span`` is None when no response was in flight; ``only_started`` writes nothing then (and nothing for a response that never
        sent a frame)."""
        if self._file is None or (only_started and (span is None or span['first'] is None)):
            return
        fields = {} if status is None else {'status': status}
        if span is not None:
            fields['frames'] = span['frames']
            if span['first'] is not None:
                fields['first_ms'] = self._rel_ms(span['first'])
                fields['last_ms'] = self._rel_ms(span['last'])
        self._record(ev, fields)
        if self.facts and span is not None and span['first'] is not None:
            self._ready_verdict()

    def _emit(self, ev, fields, *, closing=False):
        """Serialise one record and write it unless the file is at its cap. Raises only on a failing write (the caller switches off)."""
        record = {'t': self._ms(), 'ev': ev}
        for key, value in fields.items():
            record.setdefault(key, value)           # a field can never replace the time or the kind
        try:
            line = json.dumps(record, ensure_ascii=False, separators=(',', ':'), default=_plain) + '\n'
        except (TypeError, ValueError):
            line = json.dumps({'t': record['t'], 'ev': ev, 'dropped': 'unserializable'}, separators=(',', ':')) + '\n'
        size = len(line.encode('utf-8', 'replace'))
        if self._size + size > (self.max_bytes if closing else self.max_bytes - RESERVE_BYTES):
            if not closing and not self._full:
                self._full = True
                marker = json.dumps({'t': record['t'], 'ev': 'trace_full', 'max_bytes': self.max_bytes}, separators=(',', ':')) + '\n'
                self._write_line(marker)
                self._size += len(marker)
            return 0
        self._write_line(line)
        self._size += size
        return size

    def _write_line(self, line):
        """The one place that writes to the disk."""
        self._file.write(line)

    def _prune(self):
        """Keep the newest ``keep`` files of this folder's own kind (by modification time); anything else is not ours."""
        entries = []
        with os.scandir(self.directory) as scan:
            for entry in scan:
                if _FILE.match(entry.name) and entry.is_file(follow_symlinks=False):
                    entries.append((entry.stat(follow_symlinks=False).st_mtime, entry.name))
        entries.sort()
        for _, name in entries[:max(0, len(entries) - self.keep)]:
            if name != self.path.name:
                try:
                    os.remove(self.directory / name)
                except OSError:
                    pass

    def _listen(self):
        self._tap = _DecisionTap(self)
        logger.addHandler(self._tap)
        _CURRENT.set(self)

    def _unlisten(self):
        tap, self._tap = self._tap, None
        if tap is not None:
            logger.removeHandler(tap)
        if _CURRENT.get() is self:
            _CURRENT.set(None)

    def _fail(self, error):
        """The first failure ends the trace for this call. Never raises; the log line names the type of the error and nothing else."""
        self.failure = type(error).__name__
        handle, self._file = self._file, None
        try:
            self._unlisten()
        except Exception:
            pass
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        try:
            logger.warning('echo-sync call trace stopped type=%s', self.failure)
        except Exception:
            pass
