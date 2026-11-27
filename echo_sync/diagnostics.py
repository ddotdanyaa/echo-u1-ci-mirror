"""Spoken diagnostics: a short Russian phrase for every server-side failure, so the phone is never left in silence.

The iPhone (Conduit) does not speak an ``error`` frame, so before this module every lookup, synthesis or channel
failure was plain silence for the listener. The phrases below are played through the SAME audio path as a normal cue
(a paced ``response.audio.delta`` stream, see NativeMediaSocket._play).

Where the audio comes from: at the start of a call the host renders every phrase once with the SAPI worker and keeps the
PCM in memory (``DiagnosticAudio.prerender``). If that fails (SAPI broken) the phrase is played from a WAV committed next
to this module (``diag_audio/``, 24 kHz mono PCM16 like every cue, made by tools/make_diag_audio.py). So a diagnostic is
playable even when SAPI is down. Nothing here synthesizes at failure time.

Length: the brief asked for <= 1.5 s per phrase. The native Irina voice needs 1.3 s for «Поиск не ответил.» but about
3.0-3.8 s (silence trimmed) for the others at its normal rate, and even SAPI rate +8 only reaches ~1.9 s; the phrases
themselves are fixed, so TARGET_SECONDS is a target that is NOT met and MAX_SECONDS is the ceiling that is enforced.
"""
import asyncio
import inspect
import logging
import re
import wave
from pathlib import Path

from .pcm_trim import trim_silence

logger = logging.getLogger('echo-sync')

# phrase key -> the words the listener hears. Verbatim from the owner's brief (wave2/task-4-brief.md).
PHRASES = {
    'lookup_degraded': 'Поиск не ответил.',                  # lookup failed, the controller has a model-knowledge answer
    'lookup_empty': 'Не нашёл. Повторите вопрос.',           # lookup failed, it has none
    'synthesis': 'Ошибка звука. Повторите.',                 # a cue could not be synthesized twice
    'channel': 'Связь прервалась. Повторите вопрос.',        # GPT-Live channel / helper failure
    'other': 'Ошибка. Повторите вопрос.',                    # anything else that reaches NativeMediaSocket._error
    'answer': 'Нет ответа. Повторите вопрос.',               # the cloud took the question and no usable answer came in time
}

# error code (what the phone's `error` frame carries) -> failure class; every code not listed is class 'other'.
CLASS_OF_CODE = {
    'controlled_sources_unavailable': 'lookup',
    'controlled_synthesis_failed': 'synthesis',
    'controlled_upstream_unavailable': 'channel',
    'controlled_upstream_closed': 'channel',
    'controlled_upstream_stalled': 'channel',      # W9-arch: the helper is open, the cloud has gone deaf (native_media_socket.CLOUD_DEAF_S)
    'controlled_answer_timeout': 'answer',
}

# At most one spoken diagnostic per this many seconds per session (measured from the START of the previous one).
DIAGNOSTIC_MIN_INTERVAL_S = 10
# ... except these codes. The missing-answer phrase is already limited to ONCE PER QUESTION (the controller gives the question up with a new
# epoch, and the wire is told once), and the phrase itself asks the listener to repeat the question: they do so over it, the cloud stays silent
# again, and the next report can fall inside the 10 s of the first. A second limit would leave the listener who was just told to ask again
# with nothing (Task E, ruling 4).
RATE_LIMIT_EXEMPT = frozenset({'controlled_answer_timeout'})
# How long a caller that is about to close the socket waits for a diagnostic that is still playing (longest phrase 3.8 s).
DIAGNOSTIC_FLUSH_S = 4.5
# One phrase may take this long to pre-render before the pre-render is given up.
PRERENDER_TIMEOUT_S = 10

SAMPLE_RATE = 24000
BYTES_PER_SECOND = SAMPLE_RATE * 2                          # 16-bit mono
MAX_PCM_BYTES = BYTES_PER_SECOND * 30                       # what NativeMediaSocket accepts from a synthesizer
TARGET_SECONDS = 1.5                                        # the brief; see the module docstring: not met
MAX_SECONDS = 4.0                                           # enforced ceiling for one phrase

# Silence SAPI adds around a phrase (up to 0.8 s at the end) is cut by ``pcm_trim.trim_silence`` (the one trim of the call: its lead-in and tail keep the first/last phoneme intact).
TRIM_THRESHOLD = 100

ASSET_DIR = Path(__file__).with_name('diag_audio')


def failure_class(code):
    return CLASS_OF_CODE.get(code, 'other')


def phrase_key(code, *, has_model_answer=False):
    """Which phrase a failure is announced with. A lookup failure only says «search did not answer» when the
    controller can go on with a model-knowledge answer; otherwise the listener is asked to repeat the question."""
    kind = failure_class(code)
    if kind == 'lookup':
        return 'lookup_degraded' if has_model_answer else 'lookup_empty'
    return kind


_TOKEN = re.compile(r'[a-z0-9_]{1,40}')


def _degradation_note(component, error, what=''):
    from . import degradation  # noqa: PLC0415 - U78
    degradation.note(component, error, what=what)


def reason_of(error):
    """The cause as it may be logged: an exception TYPE or a fixed lower-case token, never free text (an exception message
    can carry the listener's words, a URL or a token)."""
    if error is None:
        return 'unspecified'
    if isinstance(error, BaseException):
        # g30: the channel's FastTextError carries a fixed token of its own (``http_429``, ``http_401``, ``no_terminal_event``): the breaker of
        # ``reserve_text.Roads._rest`` tells a quota, a dead sign-in and a stall from a model's error by it, and the bare class name told it nothing.
        token = error.args[0] if type(error).__name__ == 'FastTextError' and len(error.args) == 1 else None
        return token if isinstance(token, str) and _TOKEN.fullmatch(token) else type(error).__name__
    if isinstance(error, str) and _TOKEN.fullmatch(error):
        return error
    return 'unknown'


def valid_pcm(pcm, limit=MAX_PCM_BYTES):
    """Playable cue audio: non-empty bytes of whole 16-bit samples, not longer than ``limit``."""
    return isinstance(pcm, bytes) and bool(pcm) and len(pcm) % 2 == 0 and len(pcm) <= limit


def load_wav_pcm(path):
    """The PCM of a packaged phrase; ValueError unless it is exactly the format of every cue."""
    try:
        with wave.open(str(path), 'rb') as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getcomptype()) \
                    != (SAMPLE_RATE, 1, 2, 'NONE'):
                raise ValueError('wav_format')
            pcm = audio.readframes(audio.getnframes())
    except (OSError, EOFError, wave.Error) as error:
        raise ValueError('wav_unreadable') from error
    if not valid_pcm(pcm):
        raise ValueError('wav_empty')
    return pcm


async def _await(value):
    return await value if inspect.isawaitable(value) else value


_PACKAGED = {}                                              # (folder, key) -> PCM; only successes are cached
_REPORTED = set()                                           # (folder, key) already logged as unusable


def _packaged(directory, key):
    slot = (str(directory), key)
    if slot in _PACKAGED:
        return _PACKAGED[slot]
    try:
        pcm = load_wav_pcm(Path(directory) / (key + '.wav'))
    except ValueError as error:
        if slot not in _REPORTED:
            _REPORTED.add(slot)
            logger.warning('echo-sync diagnostic audio %s: packaged WAV unusable reason=%s', key, reason_of(error.args[0]))
        return None
    _PACKAGED[slot] = pcm
    return pcm


class DiagnosticAudio:
    """The PCM of every phrase: rendered once with the live synthesizer, else the packaged WAV, else nothing."""

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else ASSET_DIR
        self._rendered = {}

    def get(self, key):
        pcm = self._rendered.get(key)
        return pcm if pcm is not None else _packaged(self.directory, key)

    @property
    def prerendered(self):
        return sorted(self._rendered)

    def missing(self):
        return [key for key in PHRASES if self.get(key) is None]

    async def prerender(self, synthesize):
        """Render every phrase once and keep the PCM. The first failure stops it: a broken SAPI is not hammered (and does
        not hold the worker against the first real cue), and the packaged WAVs serve every phrase not rendered."""
        for key, text in PHRASES.items():
            try:
                pcm = await asyncio.wait_for(_await(synthesize(text)), PRERENDER_TIMEOUT_S)
                if not valid_pcm(pcm):
                    raise ValueError('invalid_pcm')
                pcm = trim_silence(pcm, threshold=TRIM_THRESHOLD)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _degradation_note('diag_audio', error, 'предсинтез фраз: пакетные WAV')
                logger.warning('echo-sync diagnostic pre-render failed phrase=%s reason=%s: the packaged audio is used',
                               key, reason_of(error))
                break
            self._rendered[key] = pcm
            if len(pcm) > MAX_SECONDS * BYTES_PER_SECOND:
                logger.warning('echo-sync diagnostic phrase=%s is %.1f s long (ceiling %.1f s)',
                               key, len(pcm) / BYTES_PER_SECOND, MAX_SECONDS)
        absent = self.missing()
        if absent:
            logger.warning('echo-sync diagnostic audio missing phrases=%s: no pre-render and no packaged WAV', ','.join(absent))
