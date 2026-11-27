"""Registry 5.01a "Голос и громкость" (state per registry: РАБОТАЕТ НА СЕРВЕРЕ, not checked on a phone).

Proved through the real controlled_host.serve (helpers_s6_fault.HostRig: real ControlledMedia + NativeMediaSocket + engine, fake phone, fake
cloud helper, fake working SAPI on virtual time): the same call, once with the live profile of the server (voice_gain 4.0, voice_presence 3.0, written
to <home>/materials/echo_settings.json as the owner does) and once with the code defaults (1.0 / 0.0). Observed only at the edge: the PCM frames the
phone receives, the text handed to synthesis, the spoken text. Proof: live frames are louder than what synthesis returned, defaults are
byte-identical to it (so the comparison is not a dummy), no clipping, same length and same words. Not provable here: how it sounds in an iPhone earbud.
Clarity: at the SAME voice_gain 4.0 the share of energy in the 2-4 kHz band (pure-Python Goertzel at the harmonics, source has low and high parts) is
clearly higher with voice_presence 3.0 than with 0.0. Not reproduced: the registry figure "+5.7 dB on 30 recordings" (measured on recordings, not here).
Dummy check (private copy): voice_gain/voice_presence not passed on to NativeMediaSocket in controlled_host.serve -> the loudness test fails; only
voice_presence forced to 0.0 at that point -> the presence test fails, loudness stays green; the synthesis text altered -> the text test fails.
Code defaults: voice_gain 1.0, voice_presence 0.0; the test sets the live 4.0 / 3.0 explicitly for the live run.
"""
import array
import base64
import json
import math
import wave

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

LIVE = {'voice_gain': 4.0, 'voice_presence': 3.0}
FULL = 32768.0


F0 = 140
HARMONICS = {k: (1.0 / k if k <= 8 else 0.3) for k in range(1, 28)}      # low part 140-1120 Hz, high part 1260-3780 Hz (2-4 kHz from the 15th)


def speech_like(seconds=1.0, amp=1800.0, rate=24000):
    """A quiet voiced signal (harmonics of 140 Hz, low and high parts, under a 4 Hz syllable envelope) as 16-bit PCM."""
    out = array.array('h')
    for n in range(int(seconds * rate)):
        t = n / rate
        env = max(0.0, math.sin(2 * math.pi * 4 * t)) ** 2
        out.append(int(amp * env * sum(a * math.sin(2 * math.pi * F0 * k * t) for k, a in HARMONICS.items())))
    return out.tobytes()


SOURCE = speech_like()


def samples(pcm):
    a = array.array('h')
    a.frombytes(pcm)
    return a


def rms(pcm):
    s = samples(pcm)
    return math.sqrt(sum(x * x for x in s) / len(s))


def peak(pcm):
    return max(abs(x) for x in samples(pcm))


def goertzel(pcm, hz, rate=24000):
    """Power of one frequency (Goertzel recursion over the whole signal)."""
    c, s1, s2 = 2 * math.cos(2 * math.pi * hz / rate), 0.0, 0.0
    for x in samples(pcm):
        s1, s2 = x + c * s1 - s2, s1
    return s1 * s1 + s2 * s2 - c * s1 * s2


def band_share(pcm):
    """Share of the harmonic energy that lies in 2-4 kHz."""
    power = {k: goertzel(pcm, F0 * k) for k in HARMONICS}
    return sum(p for k, p in power.items() if 2000 <= F0 * k <= 4000) / sum(power.values())


def synth_calls(host):
    return [text for _t, text in host.synth_plan.calls]


def write_source(path):
    with wave.open(str(path), 'wb') as target:
        target.setframerate(24000)
        target.setnchannels(1)
        target.setsampwidth(2)
        target.writeframes(SOURCE)


def call(tmp_path, monkeypatch, settings):
    """One call: a question, the cloud's answer; returns (spoken texts, PCM the phone got per response, texts sent to synthesis)."""
    got = {}

    async def body(host):
        host.worker.synthesize = lambda text, path, end=None: (host.synth_plan.next(text), write_source(path))[1]
        (host.home / 'materials').mkdir(parents=True, exist_ok=True)
        (host.home / 'materials' / 'echo_settings.json').write_text(json.dumps(settings), encoding='utf-8')
        await host.handshake()
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(3)
        pcm, current = [], b''
        for frame in host.ws.frames:
            kind = frame.data.get('type')
            if kind == 'response.audio.delta':
                current += base64.b64decode(frame.data['delta'])
            elif kind == 'response.done' and current:
                pcm.append(current)
                current = b''
        got.update(spoken=host.spoken(), pcm=pcm, synth=synth_calls(host), errors=host.errors())
    run_host(tmp_path / 'run', monkeypatch, body, handshake=False)
    return got


def test_live_profile_makes_the_voice_louder_without_clipping(tmp_path, monkeypatch):
    live = call(tmp_path / 'live', monkeypatch, LIVE)
    plain = call(tmp_path / 'plain', monkeypatch, {})
    assert live['spoken'] and live['pcm'] and not live['errors'] and not plain['errors']
    # same call, same words, same synthesis input: only the level differs
    assert live['spoken'] == plain['spoken'] and live['synth'] == plain['synth'] and live['synth']
    assert len(live['pcm']) == len(plain['pcm']) and [len(x) for x in live['pcm']] == [len(x) for x in plain['pcm']]
    for loud, quiet in zip(live['pcm'], plain['pcm']):
        assert quiet == SOURCE[:len(quiet)]                          # defaults: the synthesized bytes go out untouched (not a dummy)
        assert rms(loud) > 2.5 * rms(quiet)                          # live: clearly louder than what synthesis returned (about +8 dB or more)
        assert peak(loud) <= 0.95 * FULL                             # soft limiter: never digital clipping
        assert 20 * math.log10(peak(loud) / FULL) > -12              # and loud enough to matter: peak above -12 dBFS


def test_presence_lifts_the_2_4_khz_band_at_the_same_gain(tmp_path, monkeypatch):
    on = call(tmp_path / 'on', monkeypatch, LIVE)
    off = call(tmp_path / 'off', monkeypatch, {'voice_gain': 4.0, 'voice_presence': 0.0})
    assert on['pcm'] and off['pcm'] and not on['errors'] and not off['errors'] and on['spoken'] == off['spoken']
    share_on, share_off = band_share(on['pcm'][0]), band_share(off['pcm'][0])
    assert 0.2 < share_off < 0.8                                     # the source really carries both parts (not a dummy band)
    assert share_on > 1.15 * share_off                               # same gain, clearer: more of the energy sits in 2-4 kHz
    assert 0.7 < rms(on['pcm'][0]) / rms(off['pcm'][0]) < 1.5        # and it is a lift of the band, not a different loudness class


def test_synthesis_gets_the_answer_text_the_phone_is_told_it_hears(tmp_path, monkeypatch):
    live = call(tmp_path / 'live', monkeypatch, LIVE)
    # the portion cued to the phone is the cloud's answer text and it is exactly what was last handed to synthesis (diagnostic phrases are pre-rendered earlier)
    assert len(live['spoken']) == 1 and live['spoken'][0] in F.DIRECT_ANSWER and live['synth'][-1] == live['spoken'][0]
