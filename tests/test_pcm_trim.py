"""Leading-silence trim for synthesized cue PCM (16-bit mono, 24 kHz).

The Windows SAPI voice (Microsoft Irina Desktop) starts every WAV with about 55 ms of exact digital
zero, then a content-independent pre-roll click (peaks up to ~75), and only then the first phoneme:
the first sample above 128 sits at 105-130 ms for most cues and at ~250 ms when the cue opens with a
plosive closure (measured locally on the real worker, 2026-11-01). That silence is paced out in real
time by the transport, so the listener hears the cue that much later. The trim removes it but keeps
a short lead-in so the first phoneme is never clipped. This trim never touches the tail: the silence
after the voice has its own trim (task S0, tests/test_pcm_tail_trim.py).

Pure functions, no TTS engine, no server, nothing sleeps.
"""
import random
import unittest
from array import array

try:
    from echo_sync import pcm_trim
except ImportError:
    pcm_trim = None

RATE = 24000


def samples_for(ms):
    return RATE * ms // 1000


def to_pcm(samples):
    return array('h', samples).tobytes()


def silence(ms):
    return [0] * samples_for(ms)


def preroll(ms, peak):
    """The engine's quiet click/noise: alternating +-peak, never above `peak`."""
    return [peak if i % 2 == 0 else -peak for i in range(samples_for(ms))]


def speech(ms, amplitude=6000):
    return [amplitude if (i // 60) % 2 == 0 else -amplitude for i in range(samples_for(ms))]


def first_audible(pcm, threshold):
    values = array('h')
    values.frombytes(pcm)
    for index, value in enumerate(values):
        if abs(value) > threshold:
            return index
    return None


def from_envelope(peaks):
    """Rebuild PCM from measured 5 ms window peaks: each window is alternating +-peak."""
    out = []
    for peak in peaks:
        out.extend(peak if i % 2 == 0 else -peak for i in range(RATE // 200))
    return out


# 5 ms window peaks of the first 300 ms of real Irina cues (measured locally on the real worker).
ENVELOPES = {
    'vowel_opening (Да.)': (110, [
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 10, 11, 12, 22, 37, 34, 48, 31, 26, 48, 114, 366, 1113, 2611, 2876,
        3410, 3098, 2634, 2553, 2409, 2560, 2153, 2202, 2238, 2146, 1646, 1714, 1386, 940, 690, 537, 1452,
        1622, 2454, 5701, 6868, 7131, 7256, 7087, 7507, 7422, 7030, 7071, 6752, 5721, 5495, 5125, 5246, 4817]),
    'plosive_opening (Продолжайте)': (250, [
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 6, 17, 19, 36, 43, 60, 51, 69, 38, 34, 33, 52, 45, 53, 35, 46, 49, 53,
        39, 41, 46, 39, 44, 50, 39, 61, 57, 44, 44, 44, 32, 46, 61, 34, 69, 50, 49, 65, 34, 102, 219, 907, 1373,
        923, 713, 1660, 1275, 3018, 4817, 3678]),
    'fricative_opening (Хорошо)': (115, [
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 6, 18, 20, 40, 43, 60, 53, 69, 44, 39, 39, 112, 111, 151, 242, 218, 368,
        464, 513, 606, 784, 521, 872, 1280, 1481, 1390, 1103, 1484, 857, 946, 1797, 2278, 1822, 2564, 1718,
        1338, 1981, 3751, 4558, 4832, 6617, 7864, 8686, 8638, 8635, 8652, 8129, 7205, 7771, 5303]),
}


class LeadingSilenceTrimTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(pcm_trim, 'leading-silence trim has not been implemented')
        self.threshold = pcm_trim.AUDIBLE_THRESHOLD
        self.keep = samples_for(pcm_trim.LEAD_IN_KEEP_MS)

    def test_lead_in_kept_is_at_most_forty_milliseconds(self):
        self.assertLessEqual(pcm_trim.LEAD_IN_KEEP_MS, 40)
        self.assertGreater(pcm_trim.LEAD_IN_KEEP_MS, 0)

    def test_zeros_and_preroll_are_cut_but_the_lead_in_and_all_sound_survive(self):
        audio = silence(55) + preroll(50, 75) + speech(500)
        first = samples_for(105)
        original = to_pcm(audio)
        result = pcm_trim.trim_leading_silence(original)
        self.assertEqual(result, to_pcm(audio[first - self.keep:]))
        self.assertTrue(original.endswith(result), 'the result must be a suffix: no sample is altered')
        self.assertEqual(first_audible(result, self.threshold), self.keep, 'exactly the lead-in precedes sound')

    def test_a_quiet_onset_just_above_the_threshold_is_not_clipped(self):
        quiet = self.threshold + 1
        audio = silence(300) + [quiet, -quiet, quiet, -quiet] * 30 + speech(200)
        result = pcm_trim.trim_leading_silence(to_pcm(audio))
        self.assertEqual(first_audible(result, self.threshold), self.keep)
        self.assertTrue(to_pcm(audio).endswith(result))
        self.assertEqual(array('h', [quiet, -quiet, quiet, -quiet]).tobytes(),
                         result[self.keep * 2:self.keep * 2 + 8])

    def test_sound_at_or_below_the_threshold_counts_as_silence(self):
        audio = silence(100) + preroll(100, self.threshold) + speech(300)
        result = pcm_trim.trim_leading_silence(to_pcm(audio))
        self.assertEqual(result, to_pcm(audio[samples_for(200) - self.keep:]))

    def test_negative_samples_are_sound_too(self):
        for onset in (-(self.threshold + 1), -32768):
            with self.subTest(onset=onset):
                audio = silence(250) + [onset] + speech(100)
                result = pcm_trim.trim_leading_silence(to_pcm(audio))
                self.assertEqual(first_audible(result, self.threshold), self.keep)

    def test_a_lead_in_that_is_already_short_is_returned_unchanged(self):
        for lead_ms in (0, 10, 40):
            with self.subTest(lead_ms=lead_ms):
                original = to_pcm(silence(lead_ms) + speech(200))
                self.assertEqual(pcm_trim.trim_leading_silence(original), original)

    def test_all_silent_audio_is_never_emptied(self):
        original = to_pcm(silence(500) + preroll(100, self.threshold))
        self.assertEqual(pcm_trim.trim_leading_silence(original), original)

    def test_silence_longer_than_the_scan_window_is_left_alone(self):
        original = to_pcm(silence(pcm_trim.MAX_SCAN_MS + 500) + speech(100))
        self.assertEqual(pcm_trim.trim_leading_silence(original), original)

    def test_empty_and_odd_length_input_do_not_raise(self):
        self.assertEqual(pcm_trim.trim_leading_silence(b''), b'')
        odd = to_pcm(silence(200) + speech(50)) + b'\x01'
        result = pcm_trim.trim_leading_silence(odd)
        self.assertTrue(odd.endswith(result))
        self.assertEqual((len(odd) - len(result)) % 2, 0, 'cuts only on sample boundaries')

    def test_real_engine_onsets_keep_the_first_phoneme_and_save_time(self):
        for name, (onset_ms, peaks) in ENVELOPES.items():
            with self.subTest(cue=name):
                original = to_pcm(from_envelope(peaks) + speech(500))
                result = pcm_trim.trim_leading_silence(original)
                self.assertTrue(original.endswith(result))
                saved_ms = (len(original) - len(result)) // 2 * 1000 // RATE
                self.assertEqual(saved_ms, onset_ms - pcm_trim.LEAD_IN_KEEP_MS)
                before = first_audible(original, self.threshold)
                after = first_audible(result, self.threshold)
                self.assertEqual(before - after, (len(original) - len(result)) // 2,
                                 'the first sound moved by exactly what was cut')
                self.assertLessEqual(after, self.keep)

    def test_properties_over_random_audio(self):
        rng = random.Random(20261101)
        for case in range(300):
            lead = silence(rng.randrange(0, 400)) + [rng.randint(-self.threshold, self.threshold)
                                                    for _ in range(rng.randrange(0, samples_for(50)))]
            body = [rng.randint(-20000, 20000) for _ in range(rng.randrange(1, 4000))]
            body[0] = rng.choice([self.threshold + 1, -(self.threshold + 1), 5000, -32768])
            original = to_pcm(lead + body)
            first = len(lead)
            with self.subTest(case=case):
                result = pcm_trim.trim_leading_silence(original)
                offset = len(original) - len(result)
                self.assertTrue(original.endswith(result))
                self.assertEqual(offset % 2, 0)
                self.assertEqual(offset // 2, max(0, first - self.keep))
                self.assertEqual(first_audible(result, self.threshold), min(first, self.keep))
                self.assertEqual(pcm_trim.trim_leading_silence(result), result, 'idempotent')


if __name__ == '__main__':
    unittest.main()
