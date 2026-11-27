"""The transport's own ear (task S0, ruling 2; scripts/DUAL_SYSTEM_DESIGN.md §3.2): when does the listener START to speak?

The cloud announces a user turn 0.3-2.3 s after the speech began, and until then the controller thought nobody was speaking: its silence
auto-repeat fired into the listener's repeat («как запоздалый диктофон с таймером», the owner's call of 2 Nov 21:46). The transport
sees the microphone PCM before anybody else (PCM16LE mono 24 kHz, ~100 ms packets from the phone), so a cheap energy detector there
tells the controller at once (NativeMediaSocket._listen -> ControlledMedia.local_onset / local_speech).

How it decides, on 20 ms frames:
* the level of a frame is its mean power in dBFS (a full-scale square wave is 0 dBFS; digital silence about -90);
* the noise floor is the quietest frame of the last FLOOR_WINDOW_MS of audio received (a sliding minimum: steady noise of any level
  is the floor itself, and a noise that starts and stays becomes the floor once it fills the window);
* a START of speech: ONSET_MS of consecutive frames at least ONSET_DB above the floor and not quieter than MIN_SPEECH_DBFS (nothing
  quieter is speech, whatever the floor: digital silence has none);
* the speech goes on while frames stay OFFSET_DB above the floor (hysteresis: the dips between syllables do not end it) and is over
  after OFFSET_MS below that; only then can a new start be heard.

No model, no numpy: one sum of squares per frame (``math.sumprod``), well under 1 ms of CPU for a 100 ms packet on the N95. Nothing here
knows what was said; it only says THAT somebody speaks. On the open speaker the phone sends no audio while our cue plays (§1.2): the
detector simply hears nothing then.

Task R-VAD: this is the ``'energy'`` ENGINE of the transport's own ear (no setting any more); the other one, ``'silero'`` (vad_silero.py: Silero VAD
through sherpa-onnx, the profile's default), has the same contract (``feed`` -> ``'onset'`` | ``'speech'`` | ``None``, ``speaking``,
``level``, ``floor``, ``engine``). ``make_onset(engine)`` makes the one the profile asks for and falls back to this one, logged, when
Silero cannot be had.
"""
import asyncio
import logging
import math
import operator
import sys
from array import array
from collections import deque

from . import degradation
from .diagnostics import reason_of

logger = logging.getLogger('echo-sync')

SAMPLE_RATE = 24000          # Hz, what the phone sends (controlled_host announces input_rate 24000)
FRAME_MS = 20
ONSET_DB = 12.0              # a frame this far above the floor is loud ...
ONSET_MS = 60                # ... and this long of loud frames in a row is a start of speech
OFFSET_DB = 6.0              # speech goes on while the frames stay this far above the floor ...
OFFSET_MS = 300              # ... and is over after this long below it
MIN_SPEECH_DBFS = -50.0      # nothing quieter is speech, whatever the floor
FLOOR_WINDOW_MS = 3000       # the floor: the quietest frame of this much audio
FULL_SCALE_POWER = 32768.0 ** 2
ZERO_HOLD_MS = 3000          # U27: digital zero (every sample 0: a hole the helper or the phone filled, never room tone) is no silence - while speaking it holds the speech for this long, then it counts as silence
# one-research (EOT-RU): the release wait of a question asked whole (classifier.turn_end == CLOSED) follows the speaker's own pauses: an EMA of the pauses after which
# they went on in the same turn, plus a margin, clamped. Starts at the cap = controlled_media.EAR_RELEASE_SILENCE_SECONDS (today's wait), so it only ever shortens a
# closed question's wait, never an open or unsure one. livekit/agents DynamicEndpointing (voice/endpointing.py:49,170): alpha 0.9, learns only 0 < pause <= max_delay.
CLOSED_MIN_S = 0.5           # livekit min_delay default; the floor of the wait of a closed question
CLOSED_MAX_S = 0.9           # = controlled_media.EAR_RELEASE_SILENCE_SECONDS: nothing learned, nothing changes
PAUSE_MARGIN_S = 0.15        # the wait sits this far above the speaker's usual inner pause
PAUSE_ALPHA = 0.9

_sum_of_squares = (lambda frame: math.sumprod(frame, frame)) if hasattr(math, 'sumprod') else \
    (lambda frame: sum(map(operator.mul, frame, frame)))


def frame_level(frame):
    """The mean power of ``frame`` (16-bit samples) in dBFS; about -90 for digital silence."""
    power = _sum_of_squares(frame) / len(frame)
    return 10 * math.log10(max(power, 1.0) / FULL_SCALE_POWER)


class SpeechOnset:
    """Feed it the microphone PCM as it arrives; ``feed`` says per packet: ``'onset'`` (speech started in it), ``'speech'`` (the
    speech goes on: a frame above the offset level while speaking) or ``None``. Packets of any size: an incomplete frame waits for the
    next packet. ``level`` and ``floor``: the last frame's level and the floor it was judged against (dBFS), for the log. ``voiced``: some
    frame of the last packet stood out of the floor (above the offset level) whatever the state - the evidence that sound is still going
    on, which the Silero engine asks of this meter before it says «speech» (vad_silero.py)."""

    engine = 'energy'

    def __init__(self, *, sample_rate=SAMPLE_RATE):
        self.frame_samples = sample_rate * FRAME_MS // 1000
        self.onset_frames = max(1, ONSET_MS // FRAME_MS)
        self.offset_frames = max(1, OFFSET_MS // FRAME_MS)
        self.window = max(1, FLOOR_WINDOW_MS // FRAME_MS)
        self.rest = b''
        self.frames = 0
        self.lows = deque()          # (frame number, level), increasing levels: the sliding minimum of the window
        self.speaking = False
        self.loud = 0                # loud frames in a row while not speaking
        self.quiet = 0               # frames below the offset level in a row while speaking
        self.level = self.floor = None
        self.voiced = False
        self.zero = 0                # U27: frames of digital zero in a row

    @property
    def quiet_ms(self):
        """The silence so far while speaking (ms, frames below the offset level in a row): ear-early takes a text on 120-150 ms of it."""
        return self.quiet * FRAME_MS if self.speaking else 0

    def feed(self, pcm):
        self.voiced = False
        data = self.rest + bytes(pcm)
        size = self.frame_samples * 2
        whole = len(data) - len(data) % size
        self.rest = data[whole:]
        if not whole:
            return None
        samples = array('h')
        samples.frombytes(data[:whole])
        if sys.byteorder == 'big':
            samples.byteswap()
        heard = None
        for start in range(0, len(samples), self.frame_samples):
            frame = samples[start:start + self.frame_samples]
            event = self._frame(frame_level(frame), not any(frame))
            if event == 'onset' or (event and heard is None):
                heard = event
        return heard

    def _frame(self, level, zero=False):
        number = self.frames
        self.zero = self.zero + 1 if zero else 0
        self.frames += 1
        lows = self.lows
        while lows and lows[-1][1] >= level:
            lows.pop()
        lows.append((number, level))
        while lows[0][0] <= number - self.window:
            lows.popleft()
        self.level, self.floor = level, lows[0][1]
        if level >= max(self.floor + OFFSET_DB, MIN_SPEECH_DBFS - (ONSET_DB - OFFSET_DB)):
            self.voiced = True
        if not self.speaking:
            if level >= max(self.floor + ONSET_DB, MIN_SPEECH_DBFS):
                self.loud += 1
                if self.loud >= self.onset_frames:
                    self.speaking, self.loud, self.quiet = True, 0, 0
                    return 'onset'
            else:
                self.loud = 0
            return None
        if level >= max(self.floor + OFFSET_DB, MIN_SPEECH_DBFS - (ONSET_DB - OFFSET_DB)):
            self.quiet = 0
            return 'speech'
        if zero and self.zero * FRAME_MS <= ZERO_HOLD_MS:
            return None                   # U27: a hole of zeros inside the speech is neither speech nor silence: the utterance waits, it is not closed
        self.quiet += 1
        if self.quiet >= self.offset_frames:
            self.speaking, self.loud = False, 0
        return None


ENGINES = ('energy', 'silero')
ONSET_BUILD_TIMEOUT_S = 2.0  # the longest a call waits for the Silero detector to be built (in a thread); then the energy rule stays


class PauseLearner:
    """The speaker's own pause, per call (one-research EOT-RU). ``went_on(pause_s)``: the ear's silence lasted ``pause_s`` and the same turn went on (no release
    between). ``wait()``: how long a closed question waits for silence. Pure: no clock, no I/O; garbage and pauses over the cap are not learned."""

    def __init__(self, lo=CLOSED_MIN_S, hi=CLOSED_MAX_S, alpha=PAUSE_ALPHA, margin=PAUSE_MARGIN_S):
        self.lo, self.hi, self.alpha, self.margin = lo, hi, alpha, margin
        self.reset()

    def reset(self):
        self.value, self.count = self.hi, 0

    def went_on(self, pause_s):
        try:
            pause = float(pause_s)
        except (TypeError, ValueError):
            return
        if not 0.0 < pause <= self.hi:
            return                        # NaN, inf, <= 0, or longer than the cap: an end, not a pause inside a turn
        self.value = self.alpha * self.value + (1.0 - self.alpha) * (pause + self.margin)
        self.count += 1

    def wait(self):
        return min(self.hi, max(self.lo, self.value))


def make_onset(engine='energy', *, model_factory=None, sample_rate=SAMPLE_RATE):
    """The speech detector of ``engine`` (the engine of the transport's own ear): ``'energy'`` is ``SpeechOnset``; ``'silero'`` is
    ``vad_silero.SileroOnset`` and, where the package or the model is missing or will not load, ``SpeechOnset`` - said once in the log,
    by the error TYPE (never its message). ``model_factory``: a callable that returns the Silero model (None: the real one)."""
    if engine not in ENGINES:
        raise ValueError('Unknown local onset engine')
    if engine == 'silero':
        try:
            from .vad_silero import SileroOnset              # noqa: PLC0415 - sherpa-onnx is imported only when this engine is wanted
            return SileroOnset(model_factory() if model_factory else None, sample_rate=sample_rate)
        except Exception as error:                           # noqa: BLE001 - no package, no model, a model that will not load
            degradation.note('local_ear.silero', error, what='детектор речи: правило по энергии')
            logger.warning('echo-sync local speech onset engine=energy requested=silero reason=%s', reason_of(error))
    return SpeechOnset(sample_rate=sample_rate)


async def make_onset_async(engine='energy', *, timeout=None, model_factory=None, sample_rate=SAMPLE_RATE):
    """``make_onset`` that never blocks the event loop: the Silero detector is built in a thread (importing sherpa-onnx and loading the model take
    0.1-0.4 s, a stalled disk much longer) and, if that takes more than ``timeout`` seconds (``ONSET_BUILD_TIMEOUT_S``), the energy rule is
    returned and the log says why (reason=TimeoutError). The thread cannot be stopped: its detector is dropped when it finishes."""
    if engine not in ENGINES:
        raise ValueError('Unknown local onset engine')
    if engine == 'silero':
        try:
            return await asyncio.wait_for(asyncio.to_thread(make_onset, engine, model_factory=model_factory, sample_rate=sample_rate),
                                          ONSET_BUILD_TIMEOUT_S if timeout is None else timeout)
        except Exception as error:                           # noqa: BLE001 - too slow (TimeoutError) or broken: the energy rule
            degradation.note('local_ear.silero', error, what='сборка детектора: правило по энергии')
            logger.warning('echo-sync local speech onset engine=energy requested=silero reason=%s', reason_of(error))
    return SpeechOnset(sample_rate=sample_rate)
