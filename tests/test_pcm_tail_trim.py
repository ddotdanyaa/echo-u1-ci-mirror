"""S0 (scripts/DUAL_SYSTEM_DESIGN.md §1.4.2, §3.8 a): the silence after the voice of a cue is cut to ``TAIL_KEEP_MS``.

On the open speaker Conduit «Локально» keeps its microphone closed while a response plays and 0.35 s after it. Every SAPI cue ends in
~0.78 s of silence (measured 760-814 ms, wave2/task-l3-report.md), so the phone reopened the microphone ~1.2 s after the voice had
stopped and a quick repeat lost its first words. The trim keeps ~0.12 s after the last audible sample (the decay of the last phoneme)
and drops the rest. It never cuts voice: the result is always a prefix of the input that holds every sample above the audible
threshold, so where the voice stops (``voiced_seconds``) does not move.

Real voice: the six packaged diagnostic phrases (echo_sync/diag_audio, Microsoft Irina through the SAPI worker) with the engine's
silence put back after them. Pure functions, nothing sleeps.
"""
import random
import wave
from array import array

import pytest

from echo_sync import pcm_trim
from echo_sync.diagnostics import ASSET_DIR, PHRASES, TRIM_THRESHOLD

RATE = 24000


def ms(n):
    return RATE * n // 1000


def to_pcm(samples):
    return array('h', samples).tobytes()


def silence(n_ms):
    return [0] * ms(n_ms)


def speech(n_ms, amplitude=6000):
    return [amplitude if (i // 60) % 2 == 0 else -amplitude for i in range(ms(n_ms))]


def engine_floor(n_ms, peak=60):
    """The engine's own quiet noise after a phrase (peaks ~60-80 in the real phrases): never above the audible threshold here."""
    return [peak if i % 2 == 0 else -peak for i in range(ms(n_ms))]


def last_audible(pcm, threshold=None):
    threshold = pcm_trim.AUDIBLE_THRESHOLD if threshold is None else threshold
    values = array('h')
    values.frombytes(pcm[:len(pcm) // 2 * 2])
    for index in range(len(values) - 1, -1, -1):
        if abs(values[index]) > threshold:
            return index
    return None


def trim(pcm):
    return pcm_trim.trim_trailing_silence(pcm)


def keep():
    return ms(pcm_trim.TAIL_KEEP_MS)


def test_the_tail_kept_after_the_voice_is_about_a_tenth_of_a_second():
    assert 100 <= pcm_trim.TAIL_KEEP_MS <= 150


def test_the_silence_after_the_voice_is_cut_to_the_kept_tail():
    original = to_pcm(silence(40) + speech(500) + silence(780))
    result = trim(original)
    assert original.startswith(result), 'the result must be a prefix: no sample is altered'
    assert len(result) // 2 == ms(40) + ms(500) + keep()


def test_the_engines_quiet_noise_after_the_voice_counts_as_silence():
    original = to_pcm(speech(300) + engine_floor(700, peak=pcm_trim.AUDIBLE_THRESHOLD))
    assert len(trim(original)) // 2 == ms(300) + keep()


def test_a_quiet_last_sound_just_above_the_threshold_is_voice_and_kept():
    quiet = pcm_trim.AUDIBLE_THRESHOLD + 1
    original = to_pcm(speech(300) + silence(200) + [quiet, -quiet] + silence(700))
    result = trim(original)
    assert len(result) // 2 == ms(300) + ms(200) + 2 + keep()
    assert last_audible(result) == ms(300) + ms(200) + 1


def test_negative_samples_are_voice_too():
    for last in (-(pcm_trim.AUDIBLE_THRESHOLD + 1), -32768):
        original = to_pcm(speech(200) + silence(100) + [last] + silence(600))
        assert len(trim(original)) // 2 == ms(300) + 1 + keep(), last


def test_a_tail_that_is_already_short_is_returned_unchanged():
    for tail_ms in (0, 50, pcm_trim.TAIL_KEEP_MS):
        original = to_pcm(speech(300) + silence(tail_ms))
        assert trim(original) == original, tail_ms


def test_audio_without_voice_is_never_cut():
    for original in (b'', to_pcm(silence(900)), to_pcm(engine_floor(900, peak=pcm_trim.AUDIBLE_THRESHOLD))):
        assert trim(original) == original


def test_silence_longer_than_the_scan_window_is_left_alone():
    """Where the voice stopped is not known then (``voiced_seconds`` takes the whole length too): nothing surprising is produced."""
    original = to_pcm(speech(200) + silence(pcm_trim.MAX_TAIL_SCAN_MS + 500))
    assert trim(original) == original


def test_odd_length_input_is_not_cut():
    odd = to_pcm(speech(100) + silence(500)) + b'\x01'
    assert trim(odd) == odd


def test_where_the_voice_stops_does_not_move():
    original = to_pcm(silence(40) + speech(700) + silence(780))
    assert pcm_trim.voiced_seconds(trim(original)) == pcm_trim.voiced_seconds(original) == pytest.approx(0.74, abs=0.001)


def real_phrase(key):
    with wave.open(str(ASSET_DIR / (key + '.wav')), 'rb') as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (RATE, 1, 2)
        return audio.readframes(audio.getnframes())


@pytest.mark.parametrize('key', sorted(PHRASES))
def test_real_sapi_phrases_lose_no_voiced_sample(key):
    """The packaged phrase is real SAPI output whose own silence was cut at 0.12 s; the engine's ~0.78 s is put back after it."""
    raw = real_phrase(key) + to_pcm(engine_floor(660) + silence(120))
    result = trim(raw)
    last = last_audible(raw)
    assert raw.startswith(result), 'a prefix of the real audio'
    assert last_audible(result) == last, 'every audible sample of the phrase is still there'
    assert len(result) // 2 == last + 1 + keep(), 'and the kept tail follows its last audible sample'
    assert pcm_trim.voiced_seconds(result) == pcm_trim.voiced_seconds(raw)
    assert (len(raw) - len(result)) / 48000 >= 0.6, 'the phone opens its microphone at least 0.6 s sooner'


def test_real_sapi_phrases_keep_the_decay_of_their_last_phoneme():
    """Past the last audible sample the real voice decays into the engine's own floor (peaks 56-80) within ~40 ms, measured on the six
    phrases. Every sample the diagnostics' own trim counted as sound (its lower threshold) is kept."""
    for key in PHRASES:
        raw = real_phrase(key) + to_pcm(silence(780))
        result = trim(raw)
        decay_end = last_audible(raw, threshold=TRIM_THRESHOLD)
        assert decay_end is not None and decay_end < len(result) // 2, key


def test_properties_over_random_audio():
    rng = random.Random(20261102)
    threshold = pcm_trim.AUDIBLE_THRESHOLD
    for case in range(300):
        body = [rng.randint(-20000, 20000) for _ in range(rng.randrange(1, 6000))]
        body[-1] = rng.choice([threshold + 1, -(threshold + 1), 5000, -32768])
        tail = silence(rng.randrange(0, 1500)) + [rng.randint(-threshold, threshold) for _ in range(rng.randrange(0, ms(60)))]
        original = to_pcm(body + tail)
        result = trim(original)
        assert original.startswith(result) and len(result) % 2 == 0, case
        assert len(result) // 2 == len(body) + min(len(tail), keep()), case
        assert trim(result) == result, f'{case}: idempotent'
