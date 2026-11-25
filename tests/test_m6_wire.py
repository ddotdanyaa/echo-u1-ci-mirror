"""P02 (M6, the wire side of the speech family): the socket plays only what the controller decided, and the listener always hears a decision.

Every test drives the real ``ControlledMedia`` and the real ``NativeMediaSocket`` (the rigs of helpers_s6_fault: only the phone, the cloud helper, SAPI, the lookup and the clock are fake):
  U52   the owner's voice over a cue cuts it through the controller's gate (``_act``) in the same instant; a voice that is not the owner's does not (the client half, the mic during a cue, needs the phone)
  U142  the cue reaches the phone at least +6 dB louder (RMS of the voiced part) at the owner's gain (``voice_boost.OWNER_GAIN``), never clipped
  P20   a search that gives nothing is an honest phrase for the listener, not an ``error`` frame for the phone (the frame stays in the journal)
  g36   a cloud that goes deaf is told at the bound the owner's rule sets (``CLOUD_DEAF_S``), with no switch to turn on
"""
import array
import asyncio
import base64
import math
import wave

import helpers_s6_fault as F
from helpers_spoken_diagnostics import ASSET_DIR, CHANNEL, LOOKUP_EMPTY, responses, run_wire

from cm_patch import patch_controller
from echo_sync import arch_liveness, native_media_socket, own_voice, voice_boost
from echo_sync.controlled_media import ControlledMedia

try:
    from tools import voice_boost_measure
except ImportError:      # the tools folder is not a package on every checkout
    import importlib.util
    import pathlib
    _spec = importlib.util.spec_from_file_location('voice_boost_measure', pathlib.Path(__file__).resolve().parents[1] / 'tools' / 'voice_boost_measure.py')
    voice_boost_measure = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(voice_boost_measure)


def tone(seconds, amp=5000, f0=140.0, rate=24000):
    """Speech-like PCM: harmonics of f0 under a 4 Hz syllable envelope, whole 20 ms frames."""
    out = []
    for n in range(int(seconds * rate) // 480 * 480):
        t = n / rate
        env = max(0.0, math.sin(2 * math.pi * 4 * t)) ** 2
        out.append(int(amp * env * sum(math.sin(2 * math.pi * f0 * k * t) / k for k in range(1, 12)) / 2.0))
    return array.array('h', out).tobytes()


def wav(name):
    with wave.open(str(ASSET_DIR / (name + '.wav')), 'rb') as audio:
        return audio.readframes(audio.getnframes())


def long_cue(rig, seconds=4.0):
    """The synthesizer of the rig gives a cue that lasts ``seconds`` (the default one lasts 0.1 s)."""
    pcm = tone(seconds)

    async def synthesize(text, end=None):
        return pcm
    rig.wire.synthesize = synthesize


async def cue_in_flight(rig):
    """A question, its answer, and the first cue is on the wire (frames are going out)."""
    long_cue(rig)
    await rig.ask_direct()
    await rig.advance(0.5)
    assert rig.audio() and rig.controller.cue_outstanding, ('the cue must be in flight', rig.timeline())
    return len(rig.audio())


def owner_gate(rig, kind):
    """The real SpeakerGate over a profile whose judgement of the voice is ``kind`` ('own' | 'other')."""
    class Profile:
        def judge(self, pcm):
            return own_voice.Verdict(kind, 0.9)

        def learn(self, *a, **k):
            pass
    gate = own_voice.SpeakerGate(Profile(), speaking=lambda: True, clock=rig.now)
    rig.controller.speaker_gate = gate
    return gate


# ---- U52: the owner's voice stops the cue through the gate ---------------------------------------------------------------------------------------------------------------

def test_u52_the_owners_voice_over_a_cue_cuts_it_through_the_gate_in_the_same_instant(tmp_path, monkeypatch):
    async def body(rig):
        sent = await cue_in_flight(rig)
        owner_gate(rig, 'own')
        t = rig.now()
        await rig.feed({'type': 'input_audio_buffer.speech_started'})
        wires = list(rig.controller._act_wires)
        assert wires, 'the cut did not go through _act (no entry of the gate)'
        action, act, reason, by = wires[-1]
        assert (act, reason) == (ControlledMedia.ACTS['speech_started'][0], 'speech_started') and action['type'] == 'cancel', wires
        cleared = [f for f in rig.of_type('output_audio_buffer.clear') if f.t >= t]
        assert cleared and cleared[0].t - t < 0.1, 'the phone is told to drop the cue within one tick of the voice'
        await rig.advance(1.0)
        assert len(rig.audio()) <= sent + 1, 'the cue went on after it was cut'
    run_wire(tmp_path, monkeypatch, body)


def test_u52_a_voice_that_is_not_the_owners_does_not_cut_the_cue(tmp_path, monkeypatch):
    async def body(rig):
        sent = await cue_in_flight(rig)
        owner_gate(rig, 'other')
        t = rig.now()
        before = len(rig.controller._act_wires)
        await rig.feed({'type': 'input_audio_buffer.speech_started'})
        assert len(rig.controller._act_wires) == before, 'somebody else\'s voice reached the gate\'s steps'
        assert not [f for f in rig.of_type('output_audio_buffer.clear') if f.t >= t]
        await rig.advance(1.0)
        assert len(rig.audio()) > sent, 'the cue must go on'
    run_wire(tmp_path, monkeypatch, body)


def test_u123_the_phones_speech_during_a_cue_reaches_the_helper_and_our_own_ear(tmp_path, monkeypatch):
    """HARVEST U123 (1.01): the server side is not what silences the listener during a cue: every microphone packet the phone sends while a cue plays is forwarded and heard by the local ear, with no
    'a cue is playing' condition. (That the phone sends them at all is the client's: duplex verdict=full, cue_coverage >= 0.75, no mic_gap inside a cue, 'echo cancelling' in the line 'Microphone started:'; needs the phone.)"""
    async def body(rig):
        await cue_in_flight(rig)
        ear, heard = rig.wire.onset, []
        real = ear.feed
        ear.feed = lambda pcm, *a, **k: (heard.append(len(pcm)), real(pcm, *a, **k))[1]
        before = len([k for k, _ in rig.source.frames if k == 'P'])
        packet = tone(0.02, amp=9000)
        for _ in range(25):
            await rig.wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(packet).decode('ascii')})
            await rig.advance(0.02)
        assert rig.controller._cue_playing(rig.now()), 'the cue still plays while the packets come'
        sent = len([k for k, _ in rig.source.frames if k == 'P']) - before
        assert sent == 25 and heard == [len(packet)] * 25, (sent, len(heard))
    run_wire(tmp_path, monkeypatch, body)


# ---- U142: the cue is louder at the phone, never clipped ---------------------------------------------------------------------------------------------------------------

def voiced_rms(pcm):
    s = array.array('h')
    s.frombytes(pcm)
    frames = [s[i:i + 480] for i in range(0, len(s) - 479, 480)]
    power = [sum(x * x for x in f) / 480 for f in frames]
    voiced = [p for p in power if p > voice_boost.VOICED_POWER]
    return math.sqrt(sum(voiced) / len(voiced))


def test_u142_the_cue_reaches_the_phone_at_least_6_db_louder_and_is_never_clipped(tmp_path, monkeypatch):
    source = wav('answer')

    async def body(rig):
        rig.wire.voice_gain = voice_boost.OWNER_GAIN      # what settings.DEFAULTS['voice_gain'] carries into the socket

        async def synthesize(text, end=None):
            return source
        rig.wire.synthesize = synthesize
        await rig.ask_direct()
        await rig.advance(8)
        heard = [r for r in responses(rig.frames) if r['pcm']]
        assert heard, rig.timeline()
        out = heard[0]['pcm']
        gain_db = 20 * math.log10(voiced_rms(out) / voiced_rms(source[:len(out)]))
        samples = array.array('h')
        samples.frombytes(out)
        assert gain_db >= 6.0, f'the cue is only {gain_db:.2f} dB louder'
        assert max(map(abs, samples)) <= voice_boost.CEIL and not any(abs(x) >= 32767 for x in samples), 'the cue is clipped'
    run_wire(tmp_path, monkeypatch, body)


def test_u142_the_measure_tool_reports_the_same_gain_on_every_packaged_wav_with_no_clipping():
    for name in ('answer', 'channel', 'lookup_degraded', 'lookup_empty', 'other', 'synthesis'):
        report = voice_boost_measure.gain_report(wav(name), voice_boost.OWNER_GAIN)
        assert report['rms_gain_db'] >= 6.0 and report['clipped'] == 0 and report['peak'] <= voice_boost.CEIL, (name, report)


# ---- P20: a search that gave nothing is a phrase, not an error frame for the phone ---------------------------------------------------------------------------------------

def test_p20_a_failed_search_is_an_honest_phrase_and_no_error_frame_for_the_phone(tmp_path, monkeypatch):
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(), **kwargs: None)

    async def body(rig):
        c = rig.controller
        c.provider(F.done('u1', 'user', 'Какой штраф за неуплату налога'))
        await rig.wire._lookup({'epoch': c.epoch, 'question': c.question_text})
        await rig.advance(6)
        frames = [f.data for f in rig.frames if f.data.get('type') == 'error']
        assert [f['error']['code'] for f in frames] == ['controlled_sources_unavailable'], 'the journal still has the failure'
        assert all(f.get('echo_local') for f in frames), 'but the host does not send it to the phone'
        heard = responses(rig.frames)
        assert [r['text'] for r in heard] == [LOOKUP_EMPTY] and heard[0]['status'] == 'completed' and heard[0]['pcm'], rig.timeline()
    run_wire(tmp_path, monkeypatch, body, lookup=['raise'])


# ---- g36: a deaf cloud is told, with no switch -------------------------------------------------------------------------------------------------------------------------

def test_g36_the_deaf_bound_is_the_owners_rule_and_one_number():
    assert native_media_socket.CLOUD_DEAF_S == arch_liveness.CLOUD_DEAF_S == 15.0


def test_g36_a_cloud_that_stops_answering_is_told_to_the_listener_at_the_owners_bound(tmp_path, monkeypatch):
    async def body(rig):
        t0 = rig.now()
        await rig.feed(F.created('u1', 'user', 'Что'))
        await rig.advance(native_media_socket.CLOUD_DEAF_S + 8)
        told = [r for r in responses(rig.frames) if r['text'] == CHANNEL and r['status'] == 'completed']
        assert told and told[0]['start'] - t0 <= native_media_socket.CLOUD_DEAF_S + 3, rig.timeline()
        assert rig.errors(t0).count('controlled_upstream_stalled') == 1
        await rig.advance(60)
        assert rig.errors(t0).count('controlled_upstream_stalled') == 1, 'once, not every 15 s'
    run_wire(tmp_path, monkeypatch, body)


# ---- pcm_cache: a write that fails is told, not swallowed -----------------------------------------------------------------------------------------------------------

def test_a_full_disk_under_the_pcm_cache_is_one_warning_with_its_cause_and_the_cue_is_not_held(tmp_path, monkeypatch, caplog):
    import errno
    import pathlib
    from echo_sync import pcm_cache
    caplog.set_level('WARNING', logger='echo-sync')

    def full(self, data):
        raise OSError(errno.ENOSPC, 'No space left on device')
    monkeypatch.setattr(pathlib.Path, 'write_bytes', full)
    cache = pcm_cache.PcmCache(tmp_path, max_bytes=10 ** 6)
    voiced = b'\x02\x00' * 100
    assert cache.put('Один', 'v', 24000, voiced) is False
    assert cache.put('Два', 'v', 24000, voiced) is False
    assert pcm_cache.cached(cache, lambda text: voiced, 'Три', 'v', 24000) == voiced, 'the cue is rendered and returned whatever the disk says'
    assert cache.flush(5)
    rows = [r.getMessage() for r in caplog.records if 'pcm_cache put failed' in r.getMessage()]
    assert rows == ['echo-sync pcm_cache put failed reason=disk_full'], rows


# ---- N153: the clarity proxy for a voiced WAV -----------------------------------------------------------------------------------------------------------------------

def test_the_clarity_proxy_ranks_a_consonant_band_tone_above_a_vowel_band_tone():
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location('voice_clarity', pathlib.Path(__file__).resolve().parents[1] / 'tools' / 'voice_clarity.py')
    clarity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clarity)

    def sine(hz, seconds=1.0, amp=8000, rate=24000):
        return array.array('h', [int(amp * math.sin(2 * math.pi * hz * n / rate)) for n in range(int(seconds * rate))]).tobytes()
    high, low = clarity.clarity(sine(2500)), clarity.clarity(sine(500))
    assert high['cons_share'] > 0.9 > 0.1 > low['cons_share'], (high, low)
    assert high['band_share'] > 0.9 and low['band_share'] > 0.9 and -16 < high['rms_dbfs'] < -14 and high['peak_dbfs'] > high['rms_dbfs']
    assert clarity.clarity(wav('answer'))['band_share'] > 0.5, 'a packaged phrase is mostly in the ear-piece band'


def test_g36_a_silent_cloud_is_not_told_over_a_call_that_answers(tmp_path, monkeypatch):
    """The deaf notice is for the listener who is left with nothing. A cue of the call (here the local reference's, the cloud heard the speech and says nothing) is a sign of life: no «Связь прервалась» after it."""
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(), **kwargs: 'Двадцать процентов от неуплаченной суммы. Это штраф по статье 122.')

    async def body(rig):
        t0 = rig.now()
        await rig.feed(F.created('u1', 'user', 'Какой'))
        await rig.wire.actions(rig.controller.provider(F.done('u1', 'user', 'Какой штраф за неуплату налога')))
        await rig.advance(native_media_socket.CLOUD_DEAF_S + 20)
        said = [r['text'] for r in responses(rig.frames) if r['status'] == 'completed']
        assert any(text.startswith('Двадцать процентов') for text in said), rig.timeline()
        assert CHANNEL not in said and 'controlled_upstream_stalled' not in rig.errors(t0), rig.timeline()
    run_wire(tmp_path, monkeypatch, body)
