"""Task R-VAD: a streaming rational resampler for the microphone audio (pure Python, no numpy - the ECHO venv has none).

The phone sends PCM16 mono at 24 kHz; Silero VAD listens at 16 kHz. Picking samples would fold the 8-12 kHz band back into the speech
band (the phone's own 16 -> 24 kHz upsampler is linear, so there IS energy up there). This is the textbook polyphase windowed-sinc
resampler: output sample ``j`` sits exactly at input position ``j * in_rate / out_rate`` (the waveform is not delayed), every output is
one dot product of ``2 * half_width`` input samples with the kernel of its phase (``math.sumprod``), the kernel is a Kaiser-windowed sinc
with its cutoff at 87.5 % of the output Nyquist (24 -> 16 kHz: flat to 5 kHz, -0.5 dB at 6 kHz, about -50 dB from 8.5 kHz up), and its
taps sum to 1 (DC gain 1). ``gain`` is folded into the taps, so 16-bit samples can come out as floats in [-1, 1] with no extra pass.

Streaming: ``feed`` takes any number of samples and returns the outputs that are complete; the rest waits for the next call. The
first outputs see zeros before the start of the audio. About 2 ms of CPU per 100 ms packet at 24 -> 16 kHz.
"""
import math
import operator
from math import gcd

_dot = math.sumprod if hasattr(math, 'sumprod') else (lambda a, b: sum(map(operator.mul, a, b)))

HALF_WIDTH = 16              # taps on each side of the centre: 32 in all
KAISER_BETA = 7.0            # about 70 dB of stopband
CUTOFF_OF_NYQUIST = 0.875    # of the lower of the two Nyquist frequencies


def _bessel_i0(x):
    total = term = 1.0
    k = 1
    while term > 1e-12 * total:
        term *= (x / (2 * k)) ** 2
        total += term
        k += 1
    return total


def _kernel(frac, half, band, beta, gain):
    """The taps for an output that falls ``frac`` of an input sample after input sample ``floor(position)``, normalised to sum to ``gain``."""
    norm = _bessel_i0(beta)
    taps = []
    for i in range(-half + 1, half + 1):
        t = i - frac
        x = band * t
        sinc = 1.0 if x == 0 else math.sin(math.pi * x) / (math.pi * x)
        edge = 1.0 - (t / half) ** 2
        taps.append(band * sinc * _bessel_i0(beta * math.sqrt(max(0.0, edge))) / norm)
    total = math.fsum(taps)
    return tuple(tap * gain / total for tap in taps)


class Resampler:
    """``Resampler(24000, 16000, gain=1/32768).feed(pcm16_samples)`` -> the 16 kHz samples that are complete, as floats."""

    def __init__(self, in_rate, out_rate, *, gain=1.0, half_width=HALF_WIDTH, beta=KAISER_BETA):
        divisor = gcd(int(in_rate), int(out_rate))
        self.down, self.up = int(in_rate) // divisor, int(out_rate) // divisor      # output j at input position j * down / up
        self.gain = gain
        self.passthrough = self.up == self.down
        self.buf = [0] * (half_width - 1)         # buf[k] is the input sample (blocks done * down - (half_width - 1) + k)
        self.width = 2 * half_width
        band = CUTOFF_OF_NYQUIST * min(in_rate, out_rate) / in_rate      # the cutoff as a share of the INPUT Nyquist (2 * 7000 / 24000)
        self.offsets = [(r * self.down) // self.up for r in range(self.up)]
        self.kernels = [_kernel(((r * self.down) % self.up) / self.up, half_width, band, beta, gain) for r in range(self.up)]

    def feed(self, samples):
        if self.passthrough:
            return list(samples) if self.gain == 1 else [value * self.gain for value in samples]
        buf, down, up, width = self.buf, self.down, self.up, self.width
        buf.extend(samples)
        blocks = (len(buf) - width - self.offsets[-1]) // down + 1       # whole blocks of ``up`` outputs that can be computed
        if blocks <= 0:
            return []
        out = [0.0] * (blocks * up)
        for phase in range(up):
            first, kernel = self.offsets[phase], self.kernels[phase]
            out[phase::up] = [_dot(buf[start:start + width], kernel) for start in range(first, first + blocks * down, down)]
        del buf[:blocks * down]
        return out
