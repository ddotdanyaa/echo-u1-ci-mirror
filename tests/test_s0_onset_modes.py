"""Task S0, fix round 1 (coordinator ruling; the owner's contract ECHO_NIGHT_RECOVERY_MASTER_20261102.md R2 item 5 and R4).

The transport's own ear (S0 ruling 2) is separable from the tail trim and the clear, observable, switchable, and never a new
unbounded HOLD. The profile setting ``local_onset``:
* ``'off'``    - the detector is not even run;
* ``'shadow'`` - the default: it runs and logs every start of speech it hears with its level, and nothing else changes (no
  ``hearing``, no timer, no cue);
* ``'on'``     - ruling 2 as built (the silence auto-repeat waits while the listener is heard), plus a hard bound: a ready cue is
  never held by the ear for more than ONSET_HOLD_MAX_S (1.0 s) in all, so continuous noise or a TV cannot stall the dictation.
The tail trim and the clear of an abandoned cue stay on whatever the mode.
"""
import asyncio
import json
import logging
import time
from types import SimpleNamespace

import pytest

import helpers_s6_ack as H
from echo_sync import local_ear, settings as cfg
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from helpers_s0_audio import ROOM, appends, cue_pcm, mix, ms, noise, pcm, room, speech, talking

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
PORTION = 'Свойство тела'


# --------------------------------------------------------------------------------------------------------------------
# the setting
# --------------------------------------------------------------------------------------------------------------------

def test_the_setting_defaults_to_shadow():
    assert cfg.DEFAULTS['local_onset'] == 'shadow'
    assert cfg.resolve(None)['local_onset'] == 'shadow'


def test_the_setting_takes_exactly_its_three_modes():
    for mode in ('off', 'shadow', 'on'):
        assert cfg.resolve({'local_onset': mode})['local_onset'] == mode


@pytest.mark.parametrize('bad', ['ON', 'yes', 'true', '', True, 1, None, ['on']])
def test_any_other_value_is_the_default(bad):
    assert cfg.resolve({'local_onset': bad})['local_onset'] == 'shadow'


def test_the_setting_is_read_from_the_profile_file(tmp_path):
    path = tmp_path / cfg.SETTINGS_FILE
    path.write_text(json.dumps({'local_onset': 'off'}), encoding='utf-8')
    assert cfg.load(path)['local_onset'] == 'off'


class Hangup(Exception):
    pass


def serve_with(home, settings=None):
    """Open one call with controlled_host.serve against fakes (no helper, no SAPI, no network) and hang up at once; the transport it
    built. ``settings``: what the profile's materials/echo_settings.json holds (None: no file)."""
    from unittest.mock import patch
    from echo_sync import controlled_host
    (home / 'echo-sync').mkdir(parents=True)
    if settings is not None:
        (home / 'materials').mkdir()
        (home / 'materials' / cfg.SETTINGS_FILE).write_text(json.dumps(settings), encoding='utf-8')
    built = {}

    class Spy(controlled_host.NativeMediaSocket):
        def __init__(self, *args, **options):
            super().__init__(*args, **options)
            built['wire'] = self

            async def no_pre_render(synthesize):
                return
            self.diagnostic_audio.prerender = no_pre_render

    class Phone:
        query_params = {}

        async def receive_text(self):
            raise Hangup()

        async def send_text(self, text):
            pass

    class Worker:
        def keep_resident(self):
            pass

        def release(self):
            pass

    async def run_scoped(profile, function, executor=None):
        return function()

    api = SimpleNamespace(__file__=str(home / 'plugin_api.py'), _run_scoped=run_scoped, _gpt_live_settings=lambda: {},
                          _watch_audio_runtime=SimpleNamespace(python=lambda: ('python', {}, [], None)))
    with patch.object(controlled_host, 'profile_sapi_worker', return_value=Worker()), \
            patch.object(controlled_host, 'NativeMediaSocket', Spy):
        with pytest.raises(Hangup):
            asyncio.run(controlled_host.serve(Phone(), api=api, profile=None, home=home))
    return built['wire']


@pytest.mark.parametrize('mode', ['off', 'shadow', 'on'])
def test_a_call_takes_the_mode_from_the_profile(tmp_path, mode):
    wire = serve_with(tmp_path / 'home', {'local_onset': mode})
    assert wire.local_onset == mode and (wire.onset is None) == (mode == 'off')


def test_a_call_without_a_settings_file_is_in_shadow(tmp_path):
    assert serve_with(tmp_path / 'home').local_onset == 'shadow'


# --------------------------------------------------------------------------------------------------------------------
# the modes of the transport
# --------------------------------------------------------------------------------------------------------------------

class Ears:
    """A controller that only counts what the transport's ear tells it."""

    def __init__(self):
        self.onsets, self.speech = 0, 0

    def local_onset(self):
        self.onsets += 1

    def local_speech(self):
        self.speech += 1


def listen(mode, events, **options):
    """Feed ``events`` (microphone packets) to a ready transport in ``mode`` (None: the constructor's default)."""
    ears = Ears()

    async def run():
        async def emit(frame):
            pass

        kwargs = {} if mode is None else {'local_onset': mode}
        now = [0.0]        # U77: the packets arrive in real time (100 ms apart); at one instant the queue trim would give the quiet ones back
        socket = NativeMediaSocket(ears, emit, None, None, None, **kwargs, **{'clock': lambda: now[0], **options})
        socket.ready, socket.source = True, H.FakeSource()
        for event in events:
            await socket.client(event)
            now[0] += 0.1
        return socket

    return ears, asyncio.run(run())


SPEECH = room(1.0) + talking(1.0) + room(1.0)


def onset_lines(caplog):
    return [r.getMessage() for r in caplog.records if 'local speech onset' in r.getMessage()]


def test_off_the_ear_is_not_even_run(monkeypatch, caplog):
    def never(self, pcm):
        raise AssertionError('the detector ran')
    monkeypatch.setattr(local_ear.SpeechOnset, 'feed', never)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        ears, socket = listen('off', SPEECH)
    assert socket.onset is None and (ears.onsets, ears.speech) == (0, 0) and onset_lines(caplog) == []
    assert len(socket.source.frames) == 30, 'every packet still goes to the cloud'


@pytest.mark.parametrize('mode', ['shadow', None])
def test_shadow_runs_and_logs_every_start_of_speech_and_tells_nobody(mode, caplog):
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        ears, socket = listen(mode, SPEECH)
    assert socket.local_onset == 'shadow', 'shadow is the default'
    assert (ears.onsets, ears.speech) == (0, 0), 'shadow must not touch the controller'
    lines = onset_lines(caplog)
    assert len(lines) == 1 and 'mode=shadow' in lines[0] and 'level_db=' in lines[0] and 'floor_db=' in lines[0], lines


def test_on_tells_the_controller_and_logs_the_mode(caplog):
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        ears, socket = listen('on', SPEECH)
    assert ears.onsets == 1 and ears.speech >= 8
    assert 'mode=on' in onset_lines(caplog)[0]


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        listen('loud', [])


def test_the_mode_can_be_switched_on_a_transport():
    ears, socket = listen('shadow', [])
    socket.local_onset = 'off'
    assert socket.onset is None
    socket.local_onset = 'on'
    assert isinstance(socket.onset, local_ear.SpeechOnset)
    with pytest.raises(ValueError):
        socket.local_onset = 'loud'
    assert socket.local_onset == 'on'


def run_chain(directory, mode):
    """The owner's half-duplex call through the whole chain (NativeMediaSocket over ControlledMedia): a cue, the room, the listener
    starting to speak just before the silence timer is due, then the cloud's turn for the repeat. What the phone and the controller
    see, by step."""
    async def run():
        wire = H.Wire(directory)
        wire.socket.local_onset = mode
        steps = []

        def look(name):
            kinds = [(f['type'], f.get('delta') if f['type'] == 'response.audio_transcript.delta' else None)
                     for f in wire.sent if f['type'] != 'response.audio.delta']
            steps.append((name, kinds, list(wire.synthesized), wire.index, wire.controller.hearing, wire.controller.repeat_at is None))

        try:
            await wire.begin(ANSWER)
            look('first cue')
            for event in room(1.0):
                await wire.socket.client(event)
            await wire.elapse(wire.controller.repeat_seconds - 0.5)
            for event in talking(0.4):
                await wire.socket.client(event)
            look('speech starts')
            await wire.elapse(1.0)
            look('the silence timer was due')
            await wire.user(PORTION, reaction=0.5)
            look('the cloud took the repeat')
            for event in talking(0.4) + room(0.5):
                await wire.socket.client(event)
            await wire.elapse(0.3)
            look('more speech while the next cue plays')
            return steps
        finally:
            await wire.close()

    return asyncio.run(run())


def test_shadow_changes_nothing_observable_in_the_whole_chain(tmp_path):
    off = run_chain(tmp_path / 'off', 'off')
    shadow = run_chain(tmp_path / 'shadow', 'shadow')
    assert shadow == off
    on = run_chain(tmp_path / 'on', 'on')
    assert on != off, 'precondition: the scenario is one where the ear, switched on, does change what happens'


# --------------------------------------------------------------------------------------------------------------------
# 'on': a ready cue is held by the ear for ONSET_HOLD_MAX_S in all, never longer
# --------------------------------------------------------------------------------------------------------------------

def hold_limit():
    from echo_sync import native_media_socket
    return native_media_socket.ONSET_HOLD_MAX_S


def test_the_bound_is_one_second():
    assert hold_limit() == 1.0


def test_the_controller_tells_whether_only_the_local_ear_hears_the_listener(tmp_path):
    d = H.Dictation(tmp_path, ANSWER)
    c = d.controller
    assert not c.heard_only_locally()
    c.local_onset()
    assert c.heard_only_locally(), 'the ear alone'
    c.speech_started()
    assert c.hearing and not c.heard_only_locally(), 'the cloud has heard the listener too'
    c.local_onset()
    assert not c.heard_only_locally(), 'an onset does not take the flag away from the cloud'
    c.hearing = False
    c.local_onset()
    d.clock.advance(c.hearing_seconds + 0.1)
    assert not c.heard_only_locally(), 'released like any other flag'


class Rig:
    """NativeMediaSocket (mode 'on') over ControlledMedia on ONE fake clock: microphone packets every 100 ms, and the host's tick after
    each, as controlled_host does. ``started``: (clock, text) of every cue the transport began to synthesize."""

    def __init__(self, directory, mode='on'):
        self.clock = H.FakeClock()
        self.controller = c = ControlledMedia(directory / 'state.sqlite3', session_id=H.SESSION, clock=self.clock, **H.HOST_KWARGS)
        c.engine.clock = self.clock
        self.started = []

        async def emit(frame):
            pass

        async def synthesize(text):
            self.started.append((self.clock(), text))
            return cue_pcm(60)

        self.socket = NativeMediaSocket(c, emit, None, None, synthesize, clock=self.clock, local_onset=mode)
        self.socket.ready, self.socket.source = True, H.FakeSource()

    async def ask(self):
        await self.socket.provider(H.created('q1', 'user', ''))
        await self.socket.provider(H.done('q1', 'user', H.Dictation.QUESTION))

    async def answer(self):
        await self.socket.provider(H.done('a1', 'assistant', ANSWER))
        await asyncio.sleep(0)

    async def hear(self, events):
        for event in events:
            self.clock.advance(0.1)
            await self.socket.client(event)
            await self.socket.tick()
            for _ in range(20):                                     # the tasks the tick spawned finish on THIS clock reading, not after the next step
                await asyncio.sleep(0)


def vacuum_cleaner(seconds):
    """A loud noise that starts and stays (the ear takes it for speech until its floor has adapted)."""
    return appends(pcm(noise(int(seconds * 1000), -28, seed=21)))


def television(seconds):
    """A TV next to the phone: phrases of 1.2 s with 0.4 s pauses, each one a new start of speech, for as long as it is on."""
    talk = []
    while len(talk) < ms(int(seconds * 1000)):
        talk += speech(1200, -27) + [0.0] * ms(400)
    return appends(pcm(mix(noise(int(seconds * 1000), ROOM, seed=22), talk[:ms(int(seconds * 1000))])))


@pytest.mark.parametrize('source', [vacuum_cleaner, television])
def test_a_ready_cue_is_held_by_the_ear_for_one_second_at_most(tmp_path, source):
    async def run():
        rig = Rig(tmp_path)
        await rig.hear(room(1.0))
        await rig.ask()                                       # the listener asks; the cloud has the question
        await rig.hear(source(0.5))                           # ... and the noise begins
        assert rig.controller.heard_only_locally(), 'precondition: the ear (mode on) hears it, the cloud said nothing'
        ready = rig.clock()
        await rig.answer()                                    # the answer arrives: its first cue is ready
        assert rig.started == [], 'precondition: the ear holds the ready cue'
        await rig.hear(source(8.0))                           # the noise goes on and on
        return ready, rig.started
    ready, started = asyncio.run(run())
    assert started, 'the dictation stalled behind the noise'
    held = started[0][0] - ready
    assert hold_limit() - 0.11 <= held <= hold_limit() + 1e-6, f'held {held:.2f} s'


class Listener:
    """The controller as the transport sees it, its flags set by hand."""

    def __init__(self):
        self.hearing, self.local, self.question_id = False, False, None
        self.ledger = SimpleNamespace(snapshot=lambda tid: None)

    def heard_only_locally(self):
        return self.hearing and self.local

    def authorized(self, cue):
        return True

    def held_cue(self, cue):        # U58 (34cfdf3f): the transport asks the controller for a held cue before it releases one; the fake holds none
        return None

    def cue_started(self, cue, *, voiced_seconds=None):
        pass

    def playback_done(self, cue, *, now, voiced_until=None):
        pass


def parked(mode='on'):
    """A ready transport over a Listener on a fake clock; ``started`` records every cue it began."""
    clock, listener, started = H.FakeClock(), Listener(), []

    async def emit(frame):
        pass

    async def synthesize(text):
        started.append((clock(), text))
        return cue_pcm(60)

    socket = NativeMediaSocket(listener, emit, None, None, synthesize, clock=clock, local_onset=mode)
    socket.ready = True
    return socket, listener, clock, started


async def wait(socket, clock, seconds, step=0.05):
    for _ in range(round(seconds / step)):
        clock.advance(step)
        await socket._release_pending()
        await asyncio.sleep(0)


def test_the_ear_holds_one_cue_for_one_second_in_all_and_the_clouds_hold_is_not_counted():
    async def run():
        socket, listener, clock, started = parked()
        listener.hearing = listener.local = True
        await socket.actions([{'type': 'speak', 'text': 'первая'}])
        await wait(socket, clock, 0.6)                        # 0.6 s held by the ear
        listener.local = False                                # the cloud hears the listener now: its hold, as long as it lasts
        await wait(socket, clock, 5.0)
        held_by_cloud = list(started)
        listener.local = True                                 # the ear alone again: 0.4 s are left of this cue's second
        await wait(socket, clock, 0.35)
        before = list(started)
        await wait(socket, clock, 0.1)
        return held_by_cloud, before, started
    held_by_cloud, before, after = asyncio.run(run())
    assert held_by_cloud == [] and before == [], 'held: by the cloud without limit, by the ear for its 1 s in all'
    assert [text for _, text in after] == ['первая'], "the ear's second is spent: the cue plays"


def test_every_cue_has_its_own_second():
    async def run():
        socket, listener, clock, started = parked()
        listener.hearing = listener.local = True
        await socket.actions([{'type': 'speak', 'text': 'первая'}])
        await wait(socket, clock, 0.8)
        await socket.actions([{'type': 'speak', 'text': 'вторая'}])          # a newer cue replaces the parked one
        await wait(socket, clock, 0.8)
        early = list(started)
        await wait(socket, clock, 0.3)
        return early, started
    early, started = asyncio.run(run())
    assert early == [] and [text for _, text in started] == ['вторая']


def test_in_shadow_and_off_a_hold_is_the_clouds_without_limit_as_before():
    async def run(mode):
        socket, listener, clock, started = parked(mode)
        listener.hearing = True                                # the cloud hears the listener
        await socket.actions([{'type': 'speak', 'text': 'первая'}])
        await wait(socket, clock, 5.0)
        return started
    assert asyncio.run(run('shadow')) == [] and asyncio.run(run('off')) == []


@pytest.mark.parametrize('mode', ['off', 'shadow', 'on'])
def test_the_tail_trim_and_the_clear_of_an_abandoned_cue_do_not_depend_on_the_mode(mode):
    """Guard (passes by construction): the ruling keeps S0 rulings 1 and 3 always on, whatever the ear does."""
    import base64
    from echo_sync import pcm_trim
    frames, allowed = [], [3]

    class Controller:
        def authorized(self, cue):
            allowed[0] -= 1
            return allowed[0] >= 0

        def cue_started(self, cue, *, voiced_seconds=None):
            pass

        def playback_done(self, cue, *, now, voiced_until=None):
            pass

    async def run():
        async def emit(frame):
            frames.append(frame)

        async def synthesize(text):
            return cue_pcm(400, 780)

        socket = NativeMediaSocket(Controller(), emit, None, None, synthesize, local_onset=mode)
        allowed[0] = 10 ** 6
        await socket._speak({'text': 'целиком'}, socket.audio_generation)            # played to its end
        whole = [f for f in frames if f['type'] == 'response.audio.delta']
        frames.clear()
        allowed[0] = 3
        await socket._speak({'text': 'брошена'}, socket.audio_generation)            # no longer authorized after 3 frames
        return whole

    whole = asyncio.run(run())
    assert sum(len(base64.b64decode(f['delta'])) for f in whole) == 48 * (400 + pcm_trim.TAIL_KEEP_MS)
    assert frames[-1]['type'] == 'output_audio_buffer.clear'


def test_the_cue_is_released_on_time_without_waiting_for_a_tick():
    """The host ticks every 0.1 s; the release does not wait for it: real time, no tick, no packet."""
    async def run():
        socket, listener, clock, _ = parked()
        socket.clock, started = time.monotonic, []

        async def synthesize(text):
            started.append(time.monotonic())
            return cue_pcm(60)

        socket.synthesize = synthesize
        listener.hearing = listener.local = True
        ready = time.monotonic()
        await socket.actions([{'type': 'speak', 'text': 'первая'}])
        await asyncio.sleep(hold_limit() + 0.3)
        return ready, started
    ready, started = asyncio.run(run())
    assert len(started) == 1, started
    assert started[0] - ready == pytest.approx(hold_limit(), abs=0.08)
