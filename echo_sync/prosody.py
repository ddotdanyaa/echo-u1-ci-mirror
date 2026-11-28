"""U64 (the part that is provable without recordings): the prosody of an utterance as numbers - what a witness of «the phrase is over» would read: the pitch slope
at its end, the loudness fall, the length of the last voiced stretch and the pause after it. A pure meter: ``Track.add(pcm)`` per microphone packet, ``features()`` once
at the end of the utterance. It decides NOTHING and has no threshold, no setting and no mode: ``ear_shadow`` writes the numbers to the call journal (``ear_final``,
``prosody``) so the owner's recordings can say where the thresholds are (U07, «да» of the owner), and nothing reads them back.

PCM16LE mono 24 kHz, ~100 ms packets, as the phone sends. Pure Python like ``local_ear`` (no numpy: one ``math.sumprod`` per frame, a pitch estimate on 40 ms of audio
cut to 6 kHz, looked at once at the end of the utterance and only in its last 600 ms: a packet costs a few frame levels). Numbers are the placeholders of a meter until the laptop has measured them on a real voice.

Features (``None`` where there is nothing to say; ms and dB as written):
* ``voiced_ms``        speech frames (within VOICED_BELOW_PEAK_DB of the loudest frame and above MIN_DBFS) - 20 ms each
* ``trailing_ms``      after the last voiced frame to the end of what was fed - the pause the detector's hang-over saw
* ``last_voiced_ms``   the last voiced stretch (gaps shorter than BRIDGE_MS do not end it): a long one is a final syllable or a continuing phrase, to be told by the recordings
* ``fall_db``          the median level of the voiced 300 ms before the last 200 ms minus that of the last 200 ms: positive = it falls toward the end
* ``pitch_slope_st_s`` the slope of the pitch (semitones per second) over the last PITCH_TAIL_MS of voiced speech; negative = falls (needs MIN_PITCH_POINTS voiced pitch points)
"""
import math
from array import array

from .local_ear import FRAME_MS, SAMPLE_RATE, frame_level

FRAME = SAMPLE_RATE * FRAME_MS // 1000           # 480 samples of 20 ms
STEP = 4                                         # the pitch is looked for on every 4th sample (6 kHz): 70-400 Hz is lags 15-85
MIN_HZ, MAX_HZ, VOICING = 70, 400, 0.6           # the range of a speaking voice; the normalized autocorrelation a periodic frame must reach
MIN_DBFS = -50.0                                 # nothing quieter is speech
VOICED_BELOW_PEAK_DB = 25.0                      # a frame this close to the loudest one is speech
BRIDGE_MS = 100                                  # a gap this short does not end a voiced stretch
TAIL_MS, BEFORE_MS, PITCH_TAIL_MS = 200, 300, 600
MIN_PITCH_POINTS = 4
_dot = (lambda a, b: math.sumprod(a, b)) if hasattr(math, 'sumprod') else (lambda a, b: sum(x * y for x, y in zip(a, b)))


def pitch_of(x):
    """The pitch (Hz) of 40 ms of samples cut to 6 kHz (every STEP-th of the 24 kHz ones), or None when they are not periodic (noise, a fricative, a breath)."""
    mean = sum(x) / len(x)
    x = [v - mean for v in x]
    n = len(x)
    if _dot(x, x) <= 0:
        return None
    lo, hi = SAMPLE_RATE // STEP // MAX_HZ, min(SAMPLE_RATE // STEP // MIN_HZ, n // 2)
    corr = []
    for lag in range(lo - 1, hi + 2):            # one lag either side: the peak at the edge is a peak
        a, b = x[:n - lag], x[lag:]
        corr.append(_dot(a, b) / (math.sqrt(_dot(a, a) * _dot(b, b)) or 1.0))
    best = max(corr[1:-1])
    if best < VOICING:
        return None
    at = next(i for i in range(1, len(corr) - 1) if corr[i] >= 0.9 * best and corr[i] >= corr[i - 1] and corr[i] >= corr[i + 1])    # the shortest period that is nearly as good: not an octave down
    left, mid, right = corr[at - 1], corr[at], corr[at + 1]
    shift = 0.5 * (left - right) / (left - 2 * mid + right) if left - 2 * mid + right else 0.0      # the top of the parabola through the three
    return SAMPLE_RATE / STEP / (lo - 1 + at + shift)


class Track:
    """Feed it every packet of ONE utterance (any size: an incomplete frame waits for the next); ``features()`` at the end."""

    def __init__(self):
        self.levels = []                         # dBFS of every 20 ms frame
        self.cut = array('h')                    # every STEP-th sample: all the pitch needs, looked at only at the end and only in the tail (a packet costs a level per frame)
        self.rest = array('h')                   # the samples of an incomplete frame

    def add(self, pcm):
        samples = array('h')
        samples.frombytes(bytes(pcm[:len(pcm) // 2 * 2]))
        if self.rest:
            samples = self.rest + samples
        whole = len(samples) // FRAME * FRAME
        self.rest = samples[whole:]
        for at in range(0, whole, FRAME):
            frame = samples[at:at + FRAME]
            self.levels.append(frame_level(frame))
            self.cut.extend(frame[::STEP])

    def features(self):
        """The numbers of what was fed (see the module), or None when nothing was."""
        if not self.levels:
            return None
        floor = max(MIN_DBFS, max(self.levels) - VOICED_BELOW_PEAK_DB)
        voiced = [i for i, level in enumerate(self.levels) if level >= floor]
        out = {'voiced_ms': len(voiced) * FRAME_MS, 'trailing_ms': None, 'last_voiced_ms': None, 'fall_db': None, 'pitch_slope_st_s': None}
        if not voiced:
            return out
        last = voiced[-1]
        out['trailing_ms'] = (len(self.levels) - 1 - last) * FRAME_MS
        first = last
        for i in reversed(voiced[:-1]):
            if first - i > BRIDGE_MS // FRAME_MS + 1:
                break
            first = i
        out['last_voiced_ms'] = (last - first + 1) * FRAME_MS
        tail, before = TAIL_MS // FRAME_MS, BEFORE_MS // FRAME_MS
        if len(voiced) >= tail + 3:
            median = lambda items: sorted(items)[len(items) // 2]       # noqa: E731
            out['fall_db'] = round(median([self.levels[i] for i in voiced[-tail - before:-tail]]) - median([self.levels[i] for i in voiced[-tail:]]), 1)
        points = []
        for i in range(last, max(last - PITCH_TAIL_MS // FRAME_MS, 0), -2):         # non-overlapping pairs of frames, the last voiced one on: a pitch every 40 ms of the tail
            if self.levels[i] > MIN_DBFS and self.levels[i - 1] > MIN_DBFS:
                hz = pitch_of(self.cut[(i - 1) * (FRAME // STEP):(i + 1) * (FRAME // STEP)])
                if hz is not None:
                    points.append((i * FRAME_MS / 1000, 12 * math.log2(hz)))
        if len(points) >= MIN_PITCH_POINTS:
            tm, sm = sum(t for t, _ in points) / len(points), sum(s for _, s in points) / len(points)
            spread = sum((t - tm) ** 2 for t, _ in points)
            out['pitch_slope_st_s'] = round(sum((t - tm) * (s - sm) for t, s in points) / spread, 2) if spread else None
        return out
