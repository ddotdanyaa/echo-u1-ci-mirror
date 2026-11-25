"""SYNTH: a deterministic stand-in for the SAPI voice, for a machine that has none (the cloud, Linux).

Why: ``SapiWorkerManager._start_locked`` raises ``windows_only`` off Windows, so every scenario that drives the REAL worker owner (``profile_sapi_worker`` ->
``say`` -> ``render_cue_pcm``) ends in the error frame ``controlled_synthesis_failed`` before the decision under test is reached.

What it is: the PowerShell child is replaced, nothing else. ``SapiWorkerManager`` stays the real class (``synthesize``: text checks, language markup, atomic temp file,
``_validate_wav``, ``os.replace``, telemetry traces, idle timer, supervisor, restart bookkeeping), and ``render_cue_pcm``, the PCM cache, the trims and the wire stay the
product's. Only the two methods that touch the child (``_start_locked``, ``_request_locked``) answer in-process, and ONLY for a manager that would have started the
real ``powershell.exe`` (its ``popen_factory`` is the stock ``subprocess.Popen``): a manager built with a fake Popen (``test_sapi_resident``) keeps the real code path.

What the sound is (a function of the text alone, so a rerun is byte-identical): 0.10 s of silence in front (the engine's pre-roll, which ``trim_leading_silence`` cuts to
40 ms), a voiced body of ``len(text) / 15`` s (the speech pace the product measures, ``echo_sync/fast_text.py``; floor 0.25 s, cap 25 s so the wire's 30 s limit holds),
then 0.78 s of silence (the SAPI tail the product's ``trim_trailing_silence`` cuts to 120 ms). The body is a quiet 500 Hz square wave (+-600, about -35 dBFS), above the
product's 128 audible threshold on purpose: an all-zero cue would read as ``voiced_seconds == 0`` and change the timing under test. It is NOT speech: a test that
measures the real voice (frequencies, phonemes, the intonation of ``end``, a pitch) cannot pass on it and stays in tools/data/cloud_env_red.txt as «needs SAPI».
It makes no claim about synthesis latency (the real voice takes ~95 ms warm): it answers at once.

Marked: every use is counted (``USED``), shown in the pytest summary and set as the ``synthetic_voice`` property of the test (junit xml); the first use logs once.
"""
import logging
import os
import queue
import subprocess
import sys
import threading
import wave
from array import array
from contextlib import contextmanager
from pathlib import Path

MARK = 'синтез подставной'
SAMPLE_RATE = 24000                    # SapiWorkerManager.SAMPLE_RATE: mono, 16-bit
CHARS_PER_SECOND = 15.0                # echo_sync/fast_text.py: «speech pace (~15 chars/s)»
LEAD_SILENCE_S = 0.10
TAIL_SILENCE_S = 0.78                  # echo_sync/pcm_trim.py, controlled_host: «SAPI leaves ~0.78 s of silence after the voice»
MIN_VOICED_S = 0.25
MAX_VOICED_S = 25.0
AMPLITUDE = 600
PERIOD = 48                            # samples: 500 Hz at 24 kHz

REAL_POPEN = subprocess.Popen          # what a manager that starts the real child holds as its popen_factory
USED = {'cues': 0, 'tests': 0}         # whole session
_THIS_TEST = {'cues': 0}
_LOGGED = []
logger = logging.getLogger('tests.fake_voice')      # not under 'echo-sync': a test that counts the product's log lines does not see this one


def voiced_seconds_of(text):
    """The length of the voiced body for ``text``: ``len / CHARS_PER_SECOND`` between ``MIN_VOICED_S`` and ``MAX_VOICED_S``, rounded to whole samples."""
    seconds = min(MAX_VOICED_S, max(MIN_VOICED_S, len(str(text).strip()) / CHARS_PER_SECOND))
    return int(seconds * SAMPLE_RATE) / SAMPLE_RATE


def pcm_for(text):
    """The 24 kHz mono 16-bit PCM bytes of the stand-in cue for ``text`` (little endian)."""
    lead = int(LEAD_SILENCE_S * SAMPLE_RATE)
    body = int(voiced_seconds_of(text) * SAMPLE_RATE)
    tail = int(TAIL_SILENCE_S * SAMPLE_RATE)
    period = array('h', [AMPLITUDE] * (PERIOD // 2) + [-AMPLITUDE] * (PERIOD // 2))
    voiced = period * (body // PERIOD) + period[:body % PERIOD]
    samples = array('h', [0] * lead) + voiced + array('h', [0] * tail)
    if sys.byteorder == 'big':
        samples.byteswap()
    return samples.tobytes()


def write_wav(path, text):
    """The stand-in cue as a WAV file at ``path`` (what ``sapi_worker.ps1`` writes: 24 kHz, mono, 16-bit PCM)."""
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(pcm_for(text))


class FakeChild:
    """The part of ``subprocess.Popen`` that ``SapiWorkerManager`` reads from its child (``poll``, ``wait``, ``terminate``, ``kill``, ``stdin``/``stdout``)."""
    stdin = None
    stdout = None

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def available():
    """True when the real voice exists here (the same test the product's worker makes)."""
    return os.name == 'nt'


def _stock(manager):
    """A manager that would start the real PowerShell child (an injected fake Popen keeps the real code path)."""
    return getattr(manager, '_popen_factory', None) is REAL_POPEN


def _count():
    USED['cues'] += 1
    _THIS_TEST['cues'] += 1
    if not _LOGGED:
        _LOGGED.append(1)
        logger.info('%s: the SAPI voice is not here (os.name=%s), cues are silent PCM by text length (tests/helpers_fake_voice.py)', MARK, os.name)


def install(manager_cls, *, force=False):
    """Replace the two child-touching methods of ``manager_cls`` (``SapiWorkerManager``). -> an undo function, or ``None`` when nothing was done (the voice is real here, or this class already carries it)."""
    if (available() and not force) or vars(manager_cls).get('_fake_voice_original') is not None:
        return None
    real_start, real_request = manager_cls._start_locked, manager_cls._request_locked

    def start(self):
        if not _stock(self):
            return real_start(self)
        if self._alive_locked():
            return
        self._stop_locked()
        self._process = FakeChild()
        self._primed = False
        self._eof = False
        self._responses = queue.Queue()
        self._last_used = self._clock()

    def request(self, text, output, trace=None, ssml=None):
        if not _stock(self):
            return real_request(self, text, output, trace, ssml)
        from echo_sync.tts_telemetry import safe_trace_set
        self._cancel_idle_locked()
        was_cold = not self._alive_locked()
        safe_trace_set(trace, 'cold_warm', 'cold' if was_cold else 'warm')
        self._start_locked()
        if text != self.PRIME_TEXT and ssml != self.PRIME_LANG_SSML:        # the two throwaway priming words are not a cue of the test
            _count()
        write_wav(output, text)
        self._last_used = self._clock()
        self._primed = True
        self._schedule_idle_locked()

    manager_cls._start_locked, manager_cls._request_locked = start, request
    manager_cls._fake_voice_original = (real_start, real_request)

    def undo():
        manager_cls._start_locked, manager_cls._request_locked = manager_cls._fake_voice_original
        manager_cls._fake_voice_original = None

    return undo


@contextmanager
def installed(force=False):
    """The stand-in for the length of the block (the fixture's undo is not needed: the class is put back). Imports the product lazily."""
    from echo_sync.sapi_worker import SapiWorkerManager
    undo = install(SapiWorkerManager, force=force)
    try:
        yield SapiWorkerManager
    finally:
        if undo is not None:
            undo()


def begin_test():
    _THIS_TEST['cues'] = 0


def end_test(node):
    """Mark the test in the junit xml when the stand-in spoke in it."""
    if _THIS_TEST['cues']:
        USED['tests'] += 1
        try:
            node.user_properties.append(('synthetic_voice', f'{MARK}: {_THIS_TEST["cues"]} cues'))
        except Exception:
            pass
    _THIS_TEST['cues'] = 0
