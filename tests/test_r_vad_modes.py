"""Task R-VAD: the engine behind the transport's own ear and behind the shadow ear's speech segmentation.

The speech detector of the transport's own ear is Silero VAD in every call (no setting: the owner's profile took it; the energy detector where
the model is missing or fails - logged). The hold bound of 1.0 s and the isolation of failures stay: whatever the engine does wrong, the call
goes on. The transport's constructor keeps S0's energy detector until ``load_onset`` swaps the engine in, so the S0 tests, which speak with
synthetic tones that are not speech to a neural model, run unchanged.
"""
import asyncio
import json
import logging
import time

import pytest

import helpers_r_vad as R
import helpers_s6_ack as H
from echo_sync import ear_shadow, local_ear, native_media_socket, settings as cfg
from echo_sync.local_ear import SpeechOnset
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.vad_silero import SileroOnset
from helpers_s0_audio import ROOM, appends, mix, ms, noise, packets, pcm, room, talking
from test_ear_shadow import ANSWER, FakeRecognizer, ScriptedDetector, drain, packet, run
from test_s0_onset_modes import Ears, Rig, hold_limit, listen, onset_lines, serve_with










# --- the factory ------------------------------------------------------------------------------------------------------------------

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def test_the_energy_engine_is_s0s_detector():
    detector = local_ear.make_onset('energy')
    assert type(detector) is SpeechOnset and detector.engine == 'energy'


def test_an_unknown_engine_is_refused():
    with pytest.raises(ValueError):
        local_ear.make_onset('webrtc')


def test_silero_that_cannot_be_made_is_the_energy_detector_and_the_log_says_why_once(caplog):
    def broken():
        raise FileNotFoundError('C:\\somewhere\\silero_vad.int8.onnx')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        detector = local_ear.make_onset('silero', model_factory=broken)
    assert type(detector) is SpeechOnset
    lines = [r for r in caplog.records if 'requested=silero' in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING
    assert 'engine=energy' in lines[0].getMessage() and 'reason=FileNotFoundError' in lines[0].getMessage()
    assert 'somewhere' not in lines[0].getMessage(), 'the error type, never its message'


def test_a_model_folder_without_the_model_is_the_energy_detector(tmp_path, monkeypatch):
    monkeypatch.setenv('ECHO_EAR_MODEL_DIR', str(tmp_path))
    assert type(local_ear.make_onset('silero')) is SpeechOnset


@R.needs_model
def test_silero_with_its_model_is_the_silero_detector():
    detector = local_ear.make_onset('silero')
    assert type(detector) is SileroOnset and detector.engine == 'silero'


# --- the transport ------------------------------------------------------------------------------------------------------------------

def test_the_transports_own_default_is_s0s_energy_detector():
    _ears, socket = listen([])
    assert socket.onset_engine == 'energy' and type(socket.onset) is SpeechOnset




def test_the_engine_is_set_and_makes_one_detector(monkeypatch):
    _ears, socket = listen([])
    made = []
    monkeypatch.setattr(native_media_socket, 'make_onset', lambda engine, **options: made.append(engine) or SpeechOnset())
    socket.set_onset('silero')
    assert made == ['silero'] and socket.onset_engine == 'silero'
    socket.onset_engine = 'energy'
    assert made == ['silero', 'energy']


def test_an_unknown_engine_is_refused_and_nothing_changes():
    _ears, socket = listen([])
    detector = socket.onset
    with pytest.raises(ValueError):
        socket.onset_engine = 'webrtc'
    assert socket.onset_engine == 'energy' and socket.onset is detector


@R.needs_model
def test_real_speech_is_heard_through_the_transport_by_silero(caplog):
    data, _span = R.scene('lookup_degraded', lead_ms=1000, tail_ms=1500)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        ears, socket = listen(appends(data), onset_engine='silero')
    assert type(socket.onset) is SileroOnset
    lines = onset_lines(caplog)
    assert len(lines) == 1 and 'engine=silero' in lines[0], lines
    assert 'level_db=' in lines[0] and 'floor_db=' in lines[0]
    assert ears.onsets == 1 and ears.speech >= 5, (ears.onsets, ears.speech)


def test_a_silero_failure_in_the_middle_of_a_call_leaves_the_ear_running_on_the_energy_detector(monkeypatch, caplog):
    monkeypatch.setattr(native_media_socket, 'make_onset',
                        lambda engine, **options: SileroOnset(model=R.ScriptedModel(fail_at=5)))
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        ears, socket = listen(room(1.0) + talking(1.0) + room(1.0), onset_engine='silero')
    assert socket.onset is not None and socket.onset.engine == 'energy'
    assert ears.onsets == 1 and ears.speech >= 8, 'S0 scenario: the energy detector heard the speech'
    assert len([r for r in caplog.records if 'engine=silero failed' in r.getMessage()]) == 1
    starts = onset_lines(caplog)
    assert len(starts) == 1 and 'engine=energy' in starts[0], starts
    assert len(socket.source.frames) == 30, 'every packet still goes to the cloud'


def television_talking(seconds, gain_db=-6.0):
    """A TV next to the phone that never stops: SAPI phrases (real speech), 0.4 s apart, over room tone - the ear hears a new start after each."""
    names, talk, i = ('lookup_empty', 'synthesis', 'channel', 'other', 'answer'), [], 0
    scale = 10 ** (gain_db / 20)
    while len(talk) < ms(int(seconds * 1000)):
        talk += [v * scale for v in R.phrase(names[i % len(names)])] + [0.0] * ms(400)
        i += 1
    return appends(pcm(mix(noise(int(seconds * 1000), ROOM, seed=22), talk[:ms(int(seconds * 1000))])))


@R.needs_model
def test_a_ready_cue_is_held_by_silero_for_one_second_at_most_even_when_a_tv_never_stops_talking(tmp_path):
    """The S0 bound (ONSET_HOLD_MAX_S, the owner's contract R2.5) with the neural engine and REAL speech as the noise: the dictation never stalls."""
    async def run():
        rig = Rig(tmp_path)
        rig.socket.onset_engine = 'silero'
        await rig.hear(room(1.0))
        await rig.ask()                                       # the listener asks; the cloud has the question
        await rig.hear(television_talking(1.0))               # ... and the TV begins
        assert (rig.controller.hearing and rig.controller._heard_locally), 'precondition: the ear (Silero) hears it, the cloud said nothing'
        ready = rig.clock()
        await rig.answer()                                    # the answer arrives: its first cue is ready
        assert rig.started == [], 'precondition: the ear holds the ready cue'
        await rig.hear(television_talking(9.0))               # the TV goes on and on
        return ready, rig.started
    ready, started = asyncio.run(run())
    assert started, 'the dictation stalled behind the TV'
    held = started[0][0] - ready
    assert hold_limit() - 0.11 <= held <= hold_limit() + 1e-6, f'held {held:.2f} s'


# --- built off the event loop, bounded (review fix 2) -----------------------------------------------------------------------------------

def slow_build(delay, made=None):
    """A stand-in for ``local_ear.make_onset``: the Silero detector takes ``delay`` s to build (in whatever thread calls it), like importing
    sherpa-onnx and loading a model from a slow disk; the energy rule is instant."""
    def build(engine, **options):
        if engine == 'silero':
            time.sleep(delay)
        if made is not None:
            made.append(engine)
        return SileroOnset(model=R.ScriptedModel()) if engine == 'silero' else SpeechOnset()
    return build


def slow_everywhere(monkeypatch, delay, made=None):
    """The slow build under BOTH names the host's code could reach it by (local_ear's, and the transport's own import of it), so that no
    way of building it on the event loop goes unnoticed."""
    build = slow_build(delay, made)
    monkeypatch.setattr(local_ear, 'make_onset', build)
    monkeypatch.setattr(native_media_socket, 'make_onset', build)


def test_the_engine_is_built_in_a_thread_and_the_event_loop_keeps_running(monkeypatch):
    monkeypatch.setattr(local_ear, 'make_onset', slow_build(0.4))

    async def run():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1
        watch = asyncio.create_task(ticker())
        detector = await local_ear.make_onset_async('silero')
        watch.cancel()
        return detector, ticks
    detector, ticks = asyncio.run(run())
    assert detector.engine == 'silero' and ticks >= 10, f'the loop ran {ticks} times in the 0.4 s of the build'


def test_an_engine_that_takes_too_long_is_the_energy_detector_and_the_log_says_so(monkeypatch, caplog):
    monkeypatch.setattr(local_ear, 'make_onset', slow_build(1.0))

    async def run():
        began = time.perf_counter()
        detector = await local_ear.make_onset_async('silero', timeout=0.2)
        return detector, time.perf_counter() - began
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        detector, waited = asyncio.run(run())
    assert detector.engine == 'energy' and waited < 0.7, (detector.engine, waited)
    lines = [r.getMessage() for r in caplog.records if 'requested=silero' in r.getMessage()]
    assert len(lines) == 1 and 'engine=energy' in lines[0] and 'reason=TimeoutError' in lines[0], lines


def test_the_energy_engine_needs_no_thread_and_an_unknown_one_is_refused(monkeypatch):
    made = []
    monkeypatch.setattr(local_ear, 'make_onset', slow_build(0.0, made))
    assert asyncio.run(local_ear.make_onset_async('energy')).engine == 'energy' and made == []
    with pytest.raises(ValueError):
        asyncio.run(local_ear.make_onset_async('webrtc'))


class Loading:
    """Hands the transport a Silero detector the moment the test says so (the build of the real one, held)."""

    def __init__(self, monkeypatch):
        self.go = None
        self.made = []

        async def build(engine, **options):
            self.made.append(engine)
            await self.go.wait()
            return SileroOnset(model=R.ScriptedModel())
        monkeypatch.setattr(native_media_socket, 'make_onset_async', build)


def transport():
    async def emit(frame):
        pass
    ears = Ears()
    socket = NativeMediaSocket(ears, emit, None, None, None)
    socket.ready, socket.source = True, H.FakeSource()
    return ears, socket


def test_the_transport_listens_with_the_energy_rule_at_once_and_takes_the_engine_when_it_is_ready(monkeypatch):
    loading = Loading(monkeypatch)

    async def run():
        loading.go = asyncio.Event()
        ears, socket = transport()
        task = asyncio.create_task(socket.load_onset())
        await asyncio.sleep(0)
        assert socket.onset.engine == 'energy' and socket.onset_engine == 'silero'
        for event in room(1.0) + talking(1.0):
            await socket.client(event)
        heard_while_loading = ears.onsets
        loading.go.set()
        await task
        return heard_while_loading, socket
    heard_while_loading, socket = asyncio.run(run())
    assert heard_while_loading == 1, 'the call was usable while the model loaded: the energy rule heard the listener'
    assert socket.onset.engine == 'silero'


def test_an_engine_that_arrives_after_the_call_ended_or_after_the_ear_was_set_again_is_dropped(monkeypatch):
    loading = Loading(monkeypatch)

    async def run(change):
        loading.go = asyncio.Event()
        _ears, socket = transport()
        task = asyncio.create_task(socket.load_onset())
        await asyncio.sleep(0)
        change(socket)
        loading.go.set()
        await task
        return socket
    ended = asyncio.run(run(lambda socket: setattr(socket, 'closed', True)))
    assert ended.onset.engine == 'energy', 'the call is over'
    again = asyncio.run(run(lambda socket: socket.set_onset('energy')))
    assert again.onset.engine == 'energy' and again.onset_engine == 'energy', 'somebody set the ear again meanwhile: that stays'




def test_a_call_opens_without_waiting_for_the_model_and_the_engine_comes_when_it_is_built(tmp_path, monkeypatch):
    made = []
    slow_everywhere(monkeypatch, 0.6, made)
    wire, seen = R.serve_timed(tmp_path / 'home', until=lambda wire: wire.onset is not None and wire.onset.engine == 'silero')
    assert seen['first_receive_s'] < 0.45, f"the host read the phone after {seen['first_receive_s']:.2f} s: it waited for the 0.6 s build"
    assert seen['engine_then'] == 'energy', 'until the engine is built the energy rule listens'
    assert wire.onset.engine == 'silero' and wire.onset_engine == 'silero' and made.count('silero') == 1, made


def test_a_model_that_takes_too_long_leaves_the_call_on_the_energy_rule_and_says_so(tmp_path, monkeypatch, caplog):
    slow_everywhere(monkeypatch, 1.2)
    monkeypatch.setattr(local_ear, 'ONSET_BUILD_TIMEOUT_S', 0.3)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        wire, _seen = R.serve_timed(tmp_path / 'home',
                                    until=lambda wire: any('reason=TimeoutError' in r.getMessage() for r in caplog.records))
    assert wire.onset.engine == 'energy' and wire.onset_engine == 'silero'
    assert len([r for r in caplog.records if 'requested=silero reason=TimeoutError' in r.getMessage()]) == 1


def test_the_shadow_ear_gets_its_detector_off_the_loop_too_and_the_call_does_not_wait_for_it(tmp_path, monkeypatch):
    slow_everywhere(monkeypatch, 0.6)
    monkeypatch.setattr(ear_shadow, 'shared_worker', lambda: ear_shadow.EarWorker(lambda: FakeRecognizer([])))
    wire, seen = R.serve_timed(tmp_path / 'home', {'local_ear': 'shadow'}, until=lambda wire: wire.ear is not None)
    assert seen['first_receive_s'] < 0.45, f"the host read the phone after {seen['first_receive_s']:.2f} s"
    assert wire.ear is not None and wire.ear.detector.engine == 'silero'


def test_no_detector_is_built_for_a_shadow_ear_that_is_off(tmp_path, monkeypatch):
    made = []
    monkeypatch.setattr(local_ear, 'make_onset', slow_build(0.0, made))
    d = H.Dictation(tmp_path / 'ear', ANSWER)
    assert asyncio.run(ear_shadow.for_call_async(cfg.resolve({'local_ear': 'off'}), d.controller)) is None and made == []


# --- the host ---------------------------------------------------------------------------------------------------------------------



def test_a_call_without_a_settings_file_asks_for_silero_and_gets_the_energy_detector_where_the_model_is_missing(tmp_path):
    wire, _seen = R.serve_timed(tmp_path / 'home', until=lambda wire: wire.onset_engine == 'silero' and (not R.MODEL_READY or wire.onset.engine == 'silero'))
    assert wire.onset_engine == 'silero'
    assert wire.onset.engine == ('silero' if R.MODEL_READY else 'energy')




# --- the shadow ear -----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def dictation(tmp_path):
    return H.Dictation(tmp_path / 'ear', ANSWER)




@R.needs_model
def test_the_shadow_ear_segments_with_silero_by_default(dictation):
    worker = ear_shadow.EarWorker(lambda: FakeRecognizer([]))
    ear = ear_shadow.for_call(cfg.resolve({'local_ear': 'shadow'}), dictation.controller, worker=worker)
    assert type(ear.detector) is SileroOnset


@R.needs_model
def test_the_shadow_ear_cuts_one_utterance_out_of_speech_over_noise_and_hands_the_whole_voice_to_the_recognizer(dictation):
    """15 dB SNR, the case the energy rule ended late: Silero starts the utterance after the voice has begun (about 0.16 s) and the
    three packets of pre-roll still hold its first sounds; it ends within a second of the last one."""
    recognizer = FakeRecognizer(['свойство тела'])
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    ear = ear_shadow.for_call(cfg.resolve({'local_ear': 'shadow'}), dictation.controller, worker=worker, clock=dictation.clock)
    assert type(ear.detector) is SileroOnset
    level = R.active_dbfs(R.phrase('lookup_degraded')) - 15
    data, (start, end) = R.scene('lookup_degraded', background=lambda n: noise(n, level, seed=9))
    for index, packet in enumerate(packets(data)):
        ear.feed(packet, input_ms=100 * (index + 1))
        dictation.clock.advance(0.1)
    [record] = drain(ear, 1)
    assert record['speech_ms'] is not None
    [stream] = recognizer.streams
    first = data.find(bytes(stream['pcm']))
    assert first >= 0, 'the recognizer got one contiguous stretch of the audio'
    assert first / 48000 <= start and (first + len(stream['pcm'])) / 48000 >= end, \
        f"voice {start:.2f}-{end:.2f} s, the recognizer got {first / 48000:.2f}-{(first + len(stream['pcm'])) / 48000:.2f} s"
    assert (first + len(stream['pcm'])) / 48000 - end < 1.0, 'the utterance ended within a second of the last sound'


class LateDetector(ScriptedDetector):
    """A detector that is sure of a start only 0.5 s after it began, and says so."""
    preroll_packets = 5


def test_the_ear_keeps_as_many_packets_of_pre_roll_as_its_detector_asks_for(dictation):
    recognizer = FakeRecognizer(['свойство тела'])
    worker = ear_shadow.EarWorker(lambda: recognizer)
    assert worker.wait_ready(5)
    script = ['quiet'] * 8 + ['onset', 'speech', 'end']
    ear = ear_shadow.ShadowEar(worker, ear_shadow.controller_decider(dictation.controller), detector=LateDetector(script), clock=dictation.clock)
    run(ear, len(script))
    assert len(drain(ear, 1)) == 1
    [stream] = recognizer.streams
    assert bytes(stream['pcm']) == b''.join(packet(i) for i in range(3, 11)), 'the 5 packets before the start, the start, the speech, the end'


def test_silero_asks_for_more_pre_roll_than_the_energy_rule_because_its_verdict_comes_later():
    """On the S1 set the energy rule's start came 0.09 s after the first sound (max 0.25 s), Silero's 0.19 s (p95 0.29 s, max 0.40 s):
    three packets are exactly enough for the worst of them; a «не» at the start of an utterance must never be clipped."""
    assert SileroOnset(model=R.ScriptedModel()).preroll_packets > ear_shadow.PREROLL_PACKETS
    assert getattr(SpeechOnset(), 'preroll_packets', ear_shadow.PREROLL_PACKETS) == ear_shadow.PREROLL_PACKETS
