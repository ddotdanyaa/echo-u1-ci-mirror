"""Task R-VAD: the phone's microphone PCM (24 kHz) must reach the speech model at 16 kHz CORRECTLY.

Silero VAD takes 8 or 16 kHz. Taking every third of two samples (or any nearest-sample pick) folds everything above 8 kHz back into the
speech band: the phone's own 16 -> 24 kHz upsampler (Conduit's GrokInputUpsampler, linear) leaves images up there. ``echo_sync.resample``
is a streaming windowed-sinc polyphase resampler (pure Python, no numpy: the ECHO venv has none): the output sample j sits exactly at the
input position j * in_rate / out_rate (no delay of the waveform), the DC gain is 1, whatever packet sizes the audio arrives in.
"""
import math
import random
import time

import pytest

from echo_sync.resample import Resampler

RATE = 24000
AMPLITUDE = 10000
LATENCY = 16          # the filter looks 16 input samples ahead: that many outputs (at most) are still to come at any moment


def sine(freq, n, rate=RATE):
    return [AMPLITUDE * math.sin(2 * math.pi * freq * i / rate) for i in range(n)]


def rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values))


def db(ratio):
    return 20 * math.log10(max(ratio, 1e-12))


def settled(values, edge=64):
    """The output without the first and last samples (the filter starts and ends on silence)."""
    return values[edge:-edge]


@pytest.mark.parametrize('freq', [300, 1000, 3000, 5000])
def test_a_tone_below_the_new_nyquist_keeps_its_level_and_its_waveform(freq):
    out = Resampler(RATE, 16000).feed(sine(freq, RATE))              # one second
    assert 16000 - LATENCY <= len(out) <= 16000                      # the last few outputs wait for the samples after them
    body = settled(out)
    assert abs(db(rms(body) / (AMPLITUDE / math.sqrt(2)))) < 0.3, f'{freq} Hz changed level'
    # output j sits at the input position 1.5 j: it IS the same sine sampled at 16 kHz, not a delayed or distorted copy
    reference = [AMPLITUDE * math.sin(2 * math.pi * freq * 1.5 * j / RATE) for j in range(len(out))]
    worst = max(abs(a - b) for a, b in zip(settled(out), settled(reference)))
    assert worst < 0.02 * AMPLITUDE, f'{freq} Hz: worst error {worst:.0f}'


@pytest.mark.parametrize('freq', [8500, 9000, 10000, 11000])
def test_a_tone_above_the_new_nyquist_does_not_fold_back_into_the_speech_band(freq):
    out = Resampler(RATE, 16000).feed(sine(freq, RATE))
    attenuation = -db(rms(settled(out)) / (AMPLITUDE / math.sqrt(2)))
    assert attenuation > 40, f'{freq} Hz comes back (folded to {16000 - freq} Hz) only {attenuation:.0f} dB down'


def test_a_constant_stays_the_same_constant():
    out = Resampler(RATE, 16000).feed([1234] * 4800)
    assert all(abs(v - 1234) < 1e-6 for v in settled(out)), (min(out), max(out))


def test_the_gain_scales_every_sample():
    out = Resampler(RATE, 16000, gain=1 / 32768).feed([16384] * 4800)
    assert all(abs(v - 0.5) < 1e-9 for v in settled(out))


def test_packets_of_any_size_give_the_same_samples_as_one_long_stream():
    rng = random.Random(4)
    signal = [int(rng.gauss(0, 3000)) for _ in range(24000)]
    whole = Resampler(RATE, 16000).feed(signal)
    for size in (2400, 1, 7, 100, 333, 4799):
        stream, out = Resampler(RATE, 16000), []
        for start in range(0, len(signal), size):
            out += stream.feed(signal[start:start + size])
        assert out == whole, f'packets of {size} samples'


def test_the_rate_does_not_drift_over_a_long_stream():
    stream, count, behind = Resampler(RATE, 16000), 0, []
    for packet in range(1, 601):                                      # one minute of 100 ms packets
        count += len(stream.feed([0] * 2400))
        if packet in (10, 100, 600):
            behind.append(1600 * packet - count)                      # how many outputs are still waiting for the samples after them
    assert behind[0] == behind[1] == behind[2] and 0 <= behind[0] <= LATENCY, behind


def test_equal_rates_pass_the_samples_through():
    assert Resampler(16000, 16000).feed([1, -2, 3]) == [1, -2, 3]
    assert Resampler(16000, 16000, gain=0.5).feed([2, -4]) == [1.0, -2.0]


def test_another_integer_ratio_works_the_same_way():
    out = Resampler(48000, 16000).feed(sine(1000, 48000, rate=48000))
    assert 16000 - LATENCY <= len(out) <= 16000 and abs(db(rms(settled(out)) / (AMPLITUDE / math.sqrt(2)))) < 0.3


def test_the_cost_is_bounded():
    """A minute of microphone audio at the phone's cadence in a few percent of one core (CPU time, so a busy laptop does not fail it)."""
    rng = random.Random(5)
    packet = [int(rng.gauss(0, 3000)) for _ in range(2400)]
    stream = Resampler(RATE, 16000)
    started = time.process_time()
    for _ in range(600):
        stream.feed(packet)
    elapsed = time.process_time() - started
    assert elapsed < 3.0, f'{elapsed:.2f} s of CPU for 60 s of audio'
