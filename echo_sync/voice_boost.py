"""c22-voice: louder, clearer voice for the owner's quiet ear-piece, applied at the very point where PCM goes to the phone (``NativeMediaSocket._play``).

The PCM cache (800 MB), the SAPI worker and the packaged diagnostic WAVs stay as they are (raw, shared by every setting); a cue is boosted frame by frame
as it is paced out, so there is nothing to rebuild and the added time is a few hundred microseconds per 20 ms frame (tools/voice_boost_measure.py).
Chain, per portion: (1) normalise the portion's voiced RMS to ``REF_RMS`` (a quiet portion is lifted, a loud one is not lifted further; clamped to
``NORM_MIN..NORM_MAX``), times ``voice_gain``; (2) optional presence: a peaking biquad at ``PRESENCE_HZ`` (+``voice_presence`` dB, about 2-4 kHz) before the
level, so the consonants carry; (3) a limiter that never clips: one-frame look-ahead gain (the frame's gain is the lowest that keeps this frame AND the next
under ``LIMIT_IN``, ramped over the frame), then a soft knee (tanh) that can never reach ``CEIL``. The speech of the SAPI voice has a crest factor near 17 dB
(peaks -7 dBFS at RMS -24 dBFS), so gain 2 fits almost untouched and gain 3 leans on the soft knee: the loudness gain then is less than 3 (see the report).
With ``voice_gain`` 1.0 and ``voice_presence`` 0 (the defaults) ``active`` is False and the bytes go out untouched. Format in = format out: 24 kHz mono
16-bit little-endian, 960-byte frames, same length. Pure Python (array, math), never raises into the caller: a failure sends the raw frame."""
import array
import math
import sys

FRAME = 480                    # samples: 20 ms at 24 kHz = one 960-byte wire frame
RATE = 24000
FULL = 32767.0
CEIL = 0.95 * FULL             # nothing leaves above this (no digital clipping)
KNEE = 0.55 * FULL             # linear below, tanh above
LIMIT_IN = 1.6 * FULL          # what the frame gain lets into the soft knee
REF_RMS = 2100.0               # voiced RMS of the packaged phrases (-23.9 dBFS): the loudness one portion is brought to
NORM_MIN, NORM_MAX = 0.5, 4.0
VOICED_POWER = (32768.0 ** 2) * 10 ** (-4.5)   # a 20 ms frame above -45 dBFS counts as voice in the portion's RMS
PRESENCE_HZ, PRESENCE_Q = 3000.0, 0.9
GAIN_MIN, GAIN_MAX, PRESENCE_MAX_DB = 0.25, 4.0, 9.0
# U142 (the owner, 14.11: the cue is about twice too quiet in the ear-piece): the gain a cue goes to the phone with. Measured by tools/voice_boost_measure.py on the six packaged WAVs: +6.7 .. +8.0 dB of RMS (2.0 gave 5.85 on one of them,
# the knee takes a little off), peaks 23754 .. 30225 under CEIL, clipped samples 0. The speech of the SAPI voice has a crest factor near 17 dB, so this fits under the limiter; a louder phrase leans on the soft knee. This is the
# level ``settings.DEFAULTS['voice_gain']`` carries into ``NativeMediaSocket(voice_gain=...)``. No intra-portion compressor on purpose (HARVEST, quiet word endings): add one only after a phone check of the endings, and with no key.
OWNER_GAIN = 2.2


def active(gain, presence_db):
    return gain != 1.0 or presence_db > 0.0


def _samples(pcm):
    a = array.array('h')
    a.frombytes(pcm)
    if sys.byteorder == 'big':
        a.byteswap()
    return a


def _bytes(values):
    a = array.array('h', values)
    if sys.byteorder == 'big':
        a.byteswap()
    return a.tobytes()


def portion_norm(samples):
    """The factor that brings the portion's voiced RMS to ``REF_RMS`` (1.0 for silence)."""
    total = count = 0
    for start in range(0, len(samples) - FRAME + 1, FRAME):
        frame = samples[start:start + FRAME]
        power = (math.sumprod(frame, frame) if hasattr(math, 'sumprod') else sum(x * x for x in frame)) / FRAME
        if power > VOICED_POWER:
            total += power;count += 1
    if not count:
        return 1.0
    return min(NORM_MAX, max(NORM_MIN, REF_RMS / math.sqrt(total / count)))


def _biquad(db):
    a = 10 ** (db / 40);w = 2 * math.pi * PRESENCE_HZ / RATE;alpha = math.sin(w) / (2 * PRESENCE_Q);c = math.cos(w)
    a0 = 1 + alpha / a
    return ((1 + alpha * a) / a0, -2 * c / a0, (1 - alpha * a) / a0, -2 * c / a0, (1 - alpha / a) / a0)


def _soft(x):
    """Beyond the knee: tanh towards CEIL (never reaches it)."""
    span = CEIL - KNEE
    m = KNEE + span * math.tanh((abs(x) - KNEE) / span)
    return m if x > 0 else -m


def _frames_eq(samples, db):
    """Float frames of ``samples``, through the presence filter when ``db`` > 0 (the filter state runs on across frames)."""
    if db <= 0:
        for start in range(0, len(samples), FRAME):
            yield [float(x) for x in samples[start:start + FRAME]]
        return
    b0, b1, b2, a1, a2 = _biquad(db);x1 = x2 = y1 = y2 = 0.0
    for start in range(0, len(samples), FRAME):
        out = []
        for x in samples[start:start + FRAME]:
            y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1, y2, y1 = x1, x, y1, y
            out.append(y)
        yield out


def boost_frames(pcm, gain=1.0, presence_db=0.0):
    """Yield ``pcm`` as wire frames (960 bytes, the last one shorter), boosted. Same total length; untouched when not ``active``."""
    pcm = bytes(pcm)
    if not active(gain, presence_db) or len(pcm) < 2:
        for offset in range(0, len(pcm), 2 * FRAME):
            yield pcm[offset:offset + 2 * FRAME]
        return
    index = 0
    whole = len(pcm) - len(pcm) % 2
    tail = pcm[whole:]
    try:
        samples = _samples(pcm[:whole])
        total = max(GAIN_MIN, min(GAIN_MAX, gain)) * portion_norm(samples)
        frames = _frames_eq(samples, min(PRESENCE_MAX_DB, presence_db))
        cur = next(frames, None)
        peak_cur = max(map(abs, cur)) if cur else 0.0
        previous = total
        while cur is not None:
            nxt = next(frames, None)
            peak_next = max(map(abs, nxt)) if nxt else 0.0
            peak = max(peak_cur, peak_next)
            target = min(total, LIMIT_IN / peak) if peak > 0 else total
            n = len(cur)
            if target == previous:
                scaled = [x * target for x in cur]
            else:
                step = (target - previous) / n
                scaled = [x * (previous + step * (i + 1)) for i, x in enumerate(cur)]
            previous = target
            out = [int(round(y if -KNEE <= y <= KNEE else _soft(y))) for y in scaled]
            chunk = _bytes(out)
            index += 1
            if nxt is None and tail:
                chunk += tail
            yield chunk
            cur, peak_cur = nxt, peak_next
        return
    except Exception:
        done = index * 2 * FRAME   # a fault: the rest goes out raw, the length is kept
        for offset in range(done, len(pcm), 2 * FRAME):
            yield pcm[offset:offset + 2 * FRAME]
