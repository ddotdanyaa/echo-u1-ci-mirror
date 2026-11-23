"""Task S0, ruling 2 (scripts/DUAL_SYSTEM_DESIGN.md §3.2, §3.8 b): the transport's own ear sets «the listener is speaking».

The ear is the rule of every call (no setting; tests/test_s0_onset_modes.py).

The owner's call of 2 Nov 21:46: «как запоздалый диктофон с таймером» - the silence auto-repeat fired while he was about to speak,
because the cloud announces a turn 0.3-2.3 s after the speech began. The transport hears the microphone first: when its energy
detector (echo_sync/local_ear.py) hears speech START it sets the controller's ``hearing`` (``local_onset``), so the silence timer
does not fire into the listener's speech and a new cue waits, exactly as for the cloud's start of speech. Unlike that one it cuts
NOTHING: a cue that is playing goes on (only the cloud's speech start may cut a cue, as before). While the detector still hears speech
a flag that is set stays set (``local_speech``, like a growing transcript); it is released like any other (HEARING_SECONDS).
"""
import asyncio
import logging

import helpers_s6_ack as H
from echo_sync.controlled_media import HEARING_SECONDS
from echo_sync.native_media_socket import NativeMediaSocket
from helpers_s0_audio import appends, cue_pcm, pcm, room, talking

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
# F1 (wave F): the first cue is the first meaning portion - the whole first sentence (WAVE 2 / L2 had cut it to «Свойство тела»)
PORTION = 'Свойство тела сопротивляться изменению своего движения.'


def speaks(actions):
    return [a['text'] for a in actions if a['type'] == 'speak']


# --------------------------------------------------------------------------------------------------------------------
# the controller
# --------------------------------------------------------------------------------------------------------------------

def test_a_local_onset_holds_the_silence_timer_and_cuts_nothing(tmp_path):
    d = H.Dictation(tmp_path, ANSWER, play_first=False)
    c, cue = d.controller, d.cues[-1]
    c.cue_started(cue, voiced_seconds=2.0)                     # the cue is in flight (full duplex: the phone sends audio meanwhile)
    window = list(c.cue_window)
    d.clock.advance(0.5)
    assert c.local_onset() is None, 'no action: nothing is cut off on the phone'
    assert c.hearing and c.repeat_at is None
    assert c.cue_outstanding and c.cue_window == window and c.authorized(cue), 'the cue in flight is left alone'


def test_the_auto_repeat_never_fires_into_the_listeners_speech(tmp_path):
    d = H.Dictation(tmp_path, ANSWER)                          # the first cue was played: the silence timer runs
    c = d.controller
    d.clock.now = c.repeat_at - 0.3
    c.local_onset()                                            # the listener starts just before it is due; the cloud is silent yet
    for _ in range(20):
        d.clock.advance(0.1)
        assert speaks(c.tick(now=d.clock())) == [], 'the auto-repeat fired into the listener\'s speech'


def test_a_local_onset_is_released_like_the_hearing_latch(tmp_path):
    d = H.Dictation(tmp_path, ANSWER)
    c = d.controller
    d.clock.advance(1.0)
    c.local_onset()                                            # a cough: no transcript follows
    d.clock.advance(HEARING_SECONDS - 0.1)
    assert c.tick(now=d.clock()) == [] and c.hearing
    d.clock.advance(0.2)
    assert c.tick(now=d.clock()) == [] and not c.hearing, 'released HEARING_SECONDS after the last sign of speech'
    d.clock.advance(c.repeat_seconds - 0.2)
    assert c.tick(now=d.clock()) == [], 'the silence timer counts from the release'
    d.clock.advance(0.2)
    assert speaks(c.tick(now=d.clock())) == [PORTION]


def test_speech_still_heard_keeps_the_flag_but_never_sets_it_again(tmp_path):
    d = H.Dictation(tmp_path, ANSWER)
    c = d.controller
    c.local_onset()
    for _ in range(6):                                         # a long utterance, the cloud has not announced it yet
        d.clock.advance(1.0)
        c.local_speech()
        assert c.hearing
    d.clock.advance(HEARING_SECONDS + 0.1)
    assert not c.hearing, 'released HEARING_SECONDS after the last speech heard'
    c.local_speech()
    assert not c.hearing, 'only a new START of speech sets it again'


def test_an_accepted_final_releases_it_at_once_and_the_dictation_goes_on(tmp_path):
    d = H.Dictation(tmp_path, ANSWER)
    c = d.controller
    d.clock.advance(1.0)
    c.local_onset()
    out = d.say(PORTION, gap=0.5)
    assert not c.hearing and out.after == 1 and out.speaks == [d.chunks[1]]


def test_more_speech_after_an_accepted_final_does_not_hold_the_next_cue(tmp_path):
    """The stable partial confirms the portion while the listener is still talking: the next cue must not wait for the detector."""
    d = H.Dictation(tmp_path, ANSWER)
    c = d.controller
    c.local_onset()
    out = d.say(PORTION, gap=0.5)
    c.local_speech()                                           # the detector still hears the end of the same utterance
    assert not c.hearing and out.speaks == [d.chunks[1]]


# --------------------------------------------------------------------------------------------------------------------
# the transport
# --------------------------------------------------------------------------------------------------------------------

def test_the_transport_tells_the_controller_when_speech_starts_and_while_it_goes_on():
    class Ears:
        def __init__(self):
            self.onsets, self.speech = 0, 0

        def local_onset(self):
            self.onsets += 1

        def local_speech(self):
            self.speech += 1

    ears = Ears()

    async def run():
        async def emit(frame):
            pass

        now = [0.0]        # U77 (mic_path deleted, the trim is the only path): the packets arrive in real time, 100 ms apart, as in test_s0_onset_modes (a1e67710)
        socket = NativeMediaSocket(ears, emit, None, None, None, clock=lambda: now[0])
        socket.ready, socket.source = True, H.FakeSource()
        for event in room(1.0) + talking(1.0) + room(1.0):
            await socket.client(event)
            now[0] += 0.1
        return socket.source.frames

    forwarded = asyncio.run(run())
    assert len(forwarded) == 30 and all(kind == 'P' for kind, _ in forwarded), 'every packet still goes to the cloud'
    assert ears.onsets == 1 and ears.speech >= 8, (ears.onsets, ears.speech)


def test_speech_on_the_microphone_is_heard_before_the_cloud_says_anything(tmp_path, caplog):
    async def run():
        wire = H.Wire(tmp_path / 'heard')
        try:
            await wire.begin(ANSWER)
            for event in room(1.0):
                await wire.socket.client(event)
            quiet = wire.controller.hearing
            cleared = wire.cleared()
            with caplog.at_level(logging.INFO, logger='echo-sync'):
                for event in talking(0.3):
                    await wire.socket.client(event)
            return quiet, wire.controller.hearing, wire.cleared() - cleared
        finally:
            await wire.close()

    quiet, hearing, cleared = asyncio.run(run())
    assert not quiet, 'room noise is not speech'
    assert hearing, 'the listener speaks: the controller must know before the cloud announces the turn'
    assert cleared == 0, 'and nothing is cut off on the phone'
    onset = [r.getMessage() for r in caplog.records if 'local speech onset' in r.getMessage()]
    assert len(onset) == 1 and 'level_db=' in onset[0] and 'floor_db=' in onset[0], onset


def test_through_the_transport_the_auto_repeat_waits_while_the_listener_speaks(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'wait')
        try:
            await wire.begin(ANSWER)
            assert wire.synthesized == [PORTION]
            for event in room(1.0):
                await wire.socket.client(event)
            await wire.elapse(wire.controller.repeat_seconds - 0.5)        # the silence timer is due in half a second ...
            for event in talking(0.4):                                     # ... and the listener starts to speak
                await wire.socket.client(event)
            await wire.elapse(1.0)
            held = list(wire.synthesized)
            for event in room(0.5):                                        # the listener has stopped; the cloud never answers
                await wire.socket.client(event)
            await wire.elapse(HEARING_SECONDS + 0.2)
            await wire.elapse(wire.controller.repeat_seconds + 0.2)
            return held, list(wire.synthesized)
        finally:
            await wire.close()

    held, later = asyncio.run(run())
    assert held == [PORTION], f'the auto-repeat fired into the listener\'s speech: {held}'
    assert later == [PORTION, PORTION], 'released like the hearing latch, the silence timer runs again'


def test_a_cue_that_is_playing_is_not_cut_by_speech_on_the_microphone(tmp_path):
    """Full duplex (headphones, «Talk over Hermes»): the phone sends audio while our cue plays. The local ear may hold the next cue,
    never cut this one: only the cloud's speech start does that."""
    async def run():
        wire = H.Wire(tmp_path / 'duplex')

        async def synthesize(text, end=None):
            wire.synthesized.append(text)
            return cue_pcm(900, 120)

        wire.socket.synthesize = synthesize
        try:
            await wire.begin(ANSWER, settle=False)
            for _ in range(300):
                if wire.audio_frames >= 3:
                    break
                await asyncio.sleep(0.01)
            assert wire.audio_frames >= 3 and not wire.socket.audio.done(), 'precondition: the cue is playing'
            cleared = wire.cleared()
            for event in room(0.3) + talking(0.4):
                await wire.socket.client(event)
            hearing = wire.controller.hearing
            await wire.settle(timeout=3.0)
            kinds = [f['type'] for f in wire.sent]
            return hearing, wire.cleared() - cleared, kinds
        finally:
            await wire.close()

    hearing, cleared, kinds = asyncio.run(run())
    assert hearing, 'the listener was heard'
    assert cleared == 0 and kinds[-1] == 'response.done', f'the playing cue was cut: {kinds[-6:]}'


def test_digital_silence_on_the_microphone_changes_nothing(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'muted')
        try:
            await wire.begin(ANSWER)
            for event in appends(pcm([0] * 24000 * 3)):
                await wire.socket.client(event)
            return wire.controller.hearing, wire.controller.repeat_at is not None
        finally:
            await wire.close()

    assert asyncio.run(run()) == (False, True)


def test_a_broken_detector_never_fails_the_call(tmp_path, caplog):
    class Broken:
        def feed(self, pcm):
            raise RuntimeError('broken')

    async def run():
        wire = H.Wire(tmp_path / 'broken')
        try:
            await wire.begin(ANSWER)
            wire.socket.onset = Broken()
            with caplog.at_level(logging.WARNING, logger='echo-sync'):
                for event in talking(0.5):
                    await wire.socket.client(event)
            return wire.socket.source.frames, wire.socket.onset, wire.socket.input_ms()
        finally:
            await wire.close()

    forwarded, onset, input_ms = asyncio.run(run())
    assert len([kind for kind, _ in forwarded if kind == 'P']) == 5 and input_ms == 500, 'the audio still reaches the cloud'
    assert onset is None, 'the detector is switched off for the rest of the call'
    assert len([r for r in caplog.records if 'local speech onset disabled' in r.getMessage()]) == 1
