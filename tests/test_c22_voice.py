"""c22-voice: the software boost of everything that goes to the phone (voice_boost.py, applied in NativeMediaSocket._play)."""
import array
import asyncio
import base64
import math
import wave
from pathlib import Path

import pytest

from echo_sync.local_ear import SpeechOnset
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.controlled_media import ControlledMedia
from echo_sync.settings import resolve
from echo_sync import voice_boost as vb

RATE = 24000
DIAG = Path(vb.__file__).with_name('diag_audio')


def pcm_of(samples):
    return array.array('h', [max(-32768, min(32767, int(round(s)))) for s in samples]).tobytes()


def samples_of(pcm):
    a = array.array('h');a.frombytes(pcm);return a


def voice(seconds, amp, f0=140.0, rate=RATE):
    """Speech-like: harmonics of f0 under a syllable envelope (4 Hz) with quiet gaps."""
    out = []
    for n in range(int(seconds * rate)):
        t = n / rate
        env = max(0.0, math.sin(2 * math.pi * 4 * t)) ** 2
        x = sum(math.sin(2 * math.pi * f0 * k * t) / k for k in range(1, 20))
        out.append(amp * env * x / 2.2)
    return pcm_of(out)


def run_boost(pcm, gain, presence=0.0):
    return b''.join(vb.boost_frames(pcm, gain, presence))


def peak(pcm):
    return max((abs(s) for s in samples_of(pcm)), default=0)


def rms(pcm):
    s = samples_of(pcm);return math.sqrt(sum(x * x for x in s) / len(s))


def test_defaults_change_nothing_bytewise():
    pcm = voice(1.0, 9000)
    assert run_boost(pcm, 1.0, 0.0) == pcm
    assert not vb.active(1.0, 0.0) and vb.active(2.0, 0.0) and vb.active(1.0, 4.0)


@pytest.mark.parametrize('gain', [2.0, 3.0])
@pytest.mark.parametrize('amp', [3000, 12000, 30000])
def test_no_digital_clipping_and_length_kept(gain, amp):
    pcm = voice(1.5, amp)
    out = run_boost(pcm, gain, 6.0)
    assert len(out) == len(pcm)
    s = samples_of(out)
    assert max(abs(x) for x in s) < 32767 * 0.97
    assert sum(1 for x in s if abs(x) >= 32700) == 0


def test_quiet_voice_gets_about_double_loudness_without_clipping():
    pcm = voice(2.0, 2500)
    out = run_boost(pcm, 2.0)
    assert rms(out) / rms(pcm) > 1.8
    assert peak(out) < 32767 * 0.97


def test_portions_are_normalised_to_one_loudness():
    quiet, loud = voice(1.5, 2200), voice(1.5, 6000)
    a, b = rms(run_boost(quiet, 2.0)), rms(run_boost(loud, 2.0))
    assert 0.8 < a / b < 1.25                      # 9 dB apart before (the lift is clamped at NORM_MAX = 12 dB)
    assert rms(quiet) / rms(loud) < 0.4


def test_silence_and_empty_and_odd_input_do_not_raise():
    assert run_boost(b'', 3.0) == b''
    z = b'\0' * 4800
    assert run_boost(z, 3.0) == z                 # silence is not amplified into noise
    assert len(run_boost(b'\1\0' * 7, 2.0, 4.0)) == 14


def test_presence_lifts_2_to_4_khz_more_than_the_low_voice():
    def tone(f):
        return pcm_of([2970 * math.sin(2 * math.pi * f * n / RATE) for n in range(RATE // 2)])
    gain_at = lambda f: rms(run_boost(tone(f), 1.0, 6.0)[2000:]) / rms(tone(f)[2000:])
    assert gain_at(3000) > 1.6 * gain_at(300)
    assert gain_at(3000) > 1.5 and 0.8 < gain_at(200) < 1.25


def test_chunks_are_wire_frames():
    pcm = voice(0.5, 5000)
    chunks = list(vb.boost_frames(pcm, 2.0))
    assert all(len(c) == 960 for c in chunks[:-1]) and 0 < len(chunks[-1]) <= 960


def test_added_latency_per_frame_is_milliseconds():
    import time
    pcm = voice(3.0, 5000)
    worst = 0.0
    it = vb.boost_frames(pcm, 3.0, 6.0)
    while True:
        t = time.perf_counter()
        try:next(it)
        except StopIteration:break
        worst = max(worst, time.perf_counter() - t)
    assert worst < 0.010


def test_repo_wavs_stay_below_full_scale_and_are_louder():
    for path in sorted(DIAG.glob('*.wav')):
        pcm = vb.load = None or wave.open(str(path)).readframes(10**7)
        out = run_boost(pcm, 3.0, 4.0)
        assert len(out) == len(pcm) and peak(out) < 32767 * 0.97
        assert rms(out) > 1.6 * rms(pcm)


def test_settings_defaults_and_validation():
    s = resolve({})
    assert s['voice_gain'] == 1.0 and s['voice_presence'] == 0.0
    assert resolve({'voice_gain': 2})['voice_gain'] == 2.0
    assert resolve({'voice_gain': 9})['voice_gain'] == 1.0
    assert resolve({'voice_gain': 'x'})['voice_gain'] == 1.0
    assert resolve({'voice_presence': 4})['voice_presence'] == 4.0
    assert resolve({'voice_presence': -1})['voice_presence'] == 0.0


def _play_frames(pcm, **kw):
    async def run():
        sent = []
        async def emit(x):sent.append(x)
        wire = NativeMediaSocket(ControlledMedia(':memory:' if False else kw.pop('db'), session_id='s'), emit, lambda: None, lambda _: None, lambda _: None, **kw)
        assert await wire._play(pcm, 'т', wire.audio_generation, lambda: True)
        await wire.close()
        return sent
    return asyncio.run(run())


def test_play_sends_same_wire_format_and_defaults_are_identical(tmp_path):
    pcm = voice(0.2, 5000)
    for kw in ({}, {'voice_gain': 2.0, 'voice_presence': 3.0}):
        sent = _play_frames(pcm, db=tmp_path / 's.db', **kw)
        types = [x['type'] for x in sent]
        assert types[0] == 'response.created' and types[-1] == 'response.done'
        deltas = [base64.b64decode(x['delta']) for x in sent if x['type'] == 'response.audio.delta']
        assert all(len(d) == 960 for d in deltas[:-1])
        assert len(b''.join(deltas)) == len(pcm)
        assert set(x.keys() for x in sent if 0) == set()
        if not kw:
            assert b''.join(deltas) == pcm
        else:
            assert rms(b''.join(deltas)) > 1.8 * rms(pcm)


def test_boosted_cue_keeps_the_echo_window_and_the_ear_hears_only_the_microphone():
    """The own-voice guard of the controller works on the cue's TIME window (length, voiced end) and on the transcript, never on level: the boost
    keeps the length and the voiced end. The transport's ear is fed from the phone's microphone only (``_listen``); with the phone's own gating a
    leak at -50 dB coupling stays below the ear's -50 dBFS floor even at gain 3 (tools/voice_boost_measure.py prints the other couplings)."""
    from echo_sync.pcm_trim import voiced_seconds
    cue = voice(3.0, 4000) + b'\0' * 48000
    for gain in (2.0, 3.0):
        out = run_boost(cue, gain, 4.0)
        assert len(out) == len(cue) and abs(voiced_seconds(out) - voiced_seconds(cue)) < 0.03
        leak = pcm_of([x * 10 ** (-50 / 20) for x in samples_of(out)])
        floor = pcm_of([25 * math.sin(n * 0.37) for n in range(RATE // 2)])
        ear = SpeechOnset();ear.feed(floor)
        assert 'onset' not in [ear.feed(leak[i:i + 960]) for i in range(0, len(leak), 960)]
    import inspect, echo_sync.native_media_socket as m
    assert inspect.getsource(m.NativeMediaSocket._play).count('onset') == 0
