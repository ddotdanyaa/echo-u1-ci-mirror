"""Task S0, ruling 1 (scripts/DUAL_SYSTEM_DESIGN.md §1.4.2, §3.8 a): the phone's «рация» window opens as soon as the voice stops.

On the open speaker Conduit «Локально» drops the microphone while our cue plays and 0.35 s after it. Our PCM kept SAPI's ~0.78 s of
silence after the voice, so the microphone reopened ~1.2 s after the voice had stopped and a quick repeat lost its first words. The
transport now cuts that silence to pcm_trim.TAIL_KEEP_MS for every cue and every spoken diagnostic.

The silence timer (the auto-repeat) and the window in which the cue can be heard back (own voice) keep their meaning: both count from
where the VOICE stopped (``playback_done(voiced_until=)``), so the trim does not change how long the listener is given. A transport
that cannot tell where the voice stopped (no ``voiced_until``) still arms the timer from the PCM end.
"""
import asyncio
import base64
import time
from array import array

import pytest

import helpers_s6_ack as H
from echo_sync import pcm_trim
from echo_sync.native_media_socket import NativeMediaSocket

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
# F1 (wave F): the first cue is the first meaning portion - the whole first sentence (WAVE 2 / L2 had cut it to «Свойство тела»)
PORTION = 'Свойство тела сопротивляться изменению своего движения.'
RATE = 24000
VOICED, SAPI_TAIL = 2.0, 0.78                  # a 2 s cue and the silence SAPI leaves after every cue
KEPT = pcm_trim.TAIL_KEEP_MS / 1000            # what is left of that silence since S0


def speaks(actions):
    return [a['text'] for a in actions if a['type'] == 'speak']


def pcm_of(voiced_ms, silence_ms, *, lead_ms=0):
    samples = [0] * (RATE * lead_ms // 1000)
    samples += [6000 if (i // 40) % 2 == 0 else -6000 for i in range(RATE * voiced_ms // 1000)]
    samples += [0] * (RATE * silence_ms // 1000)
    return array('h', samples).tobytes()


def played_cue(tmp_path, tail):
    """The first cue (VOICED s of voice, then ``tail`` s of silence) has been paced out; the transport reports where its voice stopped."""
    d = H.Dictation(tmp_path, ANSWER, play_first=False)
    cue = d.cues[-1]
    d.t0 = d.clock()
    d.controller.cue_started(cue, voiced_seconds=VOICED)
    d.clock.now = d.t0 + VOICED + tail
    d.controller.playback_done(cue, now=d.clock(), voiced_until=d.t0 + VOICED)
    return d


# --------------------------------------------------------------------------------------------------------------------
# the controller: timers from the voice
# --------------------------------------------------------------------------------------------------------------------

def test_the_trim_does_not_change_when_the_portion_is_repeated(tmp_path):
    untrimmed = played_cue(tmp_path / 'untrimmed', SAPI_TAIL)
    trimmed = played_cue(tmp_path / 'trimmed', KEPT)
    assert untrimmed.controller.repeat_at - untrimmed.t0 == pytest.approx(trimmed.controller.repeat_at - trimmed.t0)
    assert trimmed.controller.repeat_at == pytest.approx(trimmed.t0 + VOICED + trimmed.controller.repeat_seconds)


def test_the_trim_does_not_change_the_window_in_which_the_cue_is_heard_back(tmp_path):
    untrimmed = played_cue(tmp_path / 'untrimmed', SAPI_TAIL)
    trimmed = played_cue(tmp_path / 'trimmed', KEPT)
    assert untrimmed.controller.cue_window[1] - untrimmed.t0 == pytest.approx(trimmed.controller.cue_window[1] - trimmed.t0)


def test_the_listener_is_given_the_whole_silence_timer_after_the_voice(tmp_path):
    d = played_cue(tmp_path, KEPT)
    c = d.controller
    d.clock.now = d.t0 + VOICED + c.repeat_seconds - 0.05
    assert speaks(c.tick(now=d.clock())) == [], 'the silence timer is not due yet'
    d.clock.now = d.t0 + VOICED + c.repeat_seconds + 0.05
    assert speaks(c.tick(now=d.clock())) == [PORTION]


def test_without_the_voiced_end_the_timer_is_armed_from_the_pcm_end(tmp_path):
    """A transport that does not say where the voice stopped (tests, an older host) gets the old behaviour."""
    d = H.Dictation(tmp_path, ANSWER, play_first=False)
    cue = d.cues[-1]
    d.clock.advance(VOICED + SAPI_TAIL)
    d.controller.playback_done(cue, now=d.clock())
    assert d.controller.repeat_at == pytest.approx(d.clock() + d.controller.repeat_seconds)


# --------------------------------------------------------------------------------------------------------------------
# the transport: what is sent, and what it reports
# --------------------------------------------------------------------------------------------------------------------

class Recorder:
    """A controller that authorizes every cue and records what the transport reports."""

    def __init__(self):
        self.calls = []

    def authorized(self, cue):
        return True

    def cue_started(self, cue, *, voiced_seconds=None):
        self.calls.append(('started', time.monotonic(), voiced_seconds))

    def playback_done(self, cue, *, now, voiced_until=None):
        self.calls.append(('done', now, voiced_until))


def sent_audio(frames):
    return b''.join(base64.b64decode(f['delta']) for f in frames if f['type'] == 'response.audio.delta')


def test_a_cue_is_sent_without_the_engines_silence_after_its_voice():
    synthesized = pcm_of(400, 780, lead_ms=40)
    controller, frames = Recorder(), []

    async def run():
        async def emit(frame):
            frames.append(frame)

        async def synthesize(text, end=None):
            return synthesized

        socket = NativeMediaSocket(controller, emit, None, None, synthesize)
        await socket._speak({'text': 'тест'}, socket.audio_generation)

    asyncio.run(run())
    audio = sent_audio(frames)
    assert synthesized.startswith(audio), 'a prefix of what was synthesized: no sample is altered'
    assert len(audio) == 48 * (40 + 400 + pcm_trim.TAIL_KEEP_MS), 'the voice and the kept tail, nothing more'
    assert frames[-1]['type'] == 'response.done'
    (_, began, voiced), (_, ended, voiced_until) = controller.calls
    assert voiced == pytest.approx(0.44, abs=0.001), 'where the voice stops does not move'
    assert ended - voiced_until == pytest.approx(KEPT, abs=0.002), 'the response is over TAIL_KEEP_MS after the voice'


def test_a_spoken_diagnostic_gets_the_same_tail_trim():
    phrase = pcm_of(300, 780)
    frames = []

    class Phrases:
        def get(self, key):
            return phrase

    async def run():
        async def emit(frame):
            frames.append(frame)

        socket = NativeMediaSocket(Recorder(), emit, None, None, None, diagnostic_audio=Phrases())
        await socket._error('controlled_invalid_pcm', 'invalid_pcm')
        await socket.finish_diagnostic()

    asyncio.run(run())
    audio = sent_audio(frames)
    assert phrase.startswith(audio) and len(audio) == 48 * (300 + pcm_trim.TAIL_KEEP_MS)
    assert frames[-1]['type'] == 'response.done'


def test_through_the_transport_the_response_is_over_soon_after_the_voice():
    """The phone ends its turn at response.done (and reopens its microphone 0.35 s later): that is TAIL_KEEP_MS after the voice now,
    where it used to be the ~0.78 s of the engine's silence."""
    voiced_ms, tail_ms = 400, 780
    times = []

    async def run():
        async def emit(frame):
            times.append((time.monotonic(), frame['type']))

        async def synthesize(text, end=None):
            return pcm_of(voiced_ms, tail_ms)

        socket = NativeMediaSocket(Recorder(), emit, None, None, synthesize)
        await socket._speak({'text': 'тест'}, socket.audio_generation)

    asyncio.run(run())
    first_audio = next(t for t, kind in times if kind == 'response.audio.delta')
    done = next(t for t, kind in times if kind == 'response.done')
    assert done - first_audio == pytest.approx(voiced_ms / 1000 + KEPT, abs=0.06)

def test_through_the_transport_the_silence_timer_counts_from_the_voice_of_the_cue(tmp_path):
    """End to end: the transport reports the voiced end of the PCM it really paced out and the controller arms the timer from it."""
    voiced_ms, tail_ms = 400, 780

    async def run():
        wire = H.Wire(tmp_path / 'wire')
        times = []
        emit = wire.socket.emit

        async def timed(frame):
            times.append((time.monotonic(), frame.get('type')))
            await emit(frame)

        async def synthesize(text, end=None):
            wire.synthesized.append(text)
            return pcm_of(voiced_ms, tail_ms)

        wire.socket.emit, wire.socket.synthesize = timed, synthesize
        try:
            await wire.begin(ANSWER, settle=True)
            first_audio = next(t for t, kind in times if kind == 'response.audio.delta')
            assert any(kind == 'response.done' for _, kind in times), 'precondition: the cue was played to its end'
            return wire.controller.repeat_at - first_audio, wire.controller.repeat_seconds
        finally:
            await wire.close()

    after_first_audio, repeat_seconds = asyncio.run(run())
    assert after_first_audio == pytest.approx(voiced_ms / 1000 + repeat_seconds, abs=0.06)
