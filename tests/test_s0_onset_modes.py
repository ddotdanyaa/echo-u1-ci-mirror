"""Task S0, fix round 1 (coordinator ruling; the owner's contract ECHO_NIGHT_RECOVERY_MASTER_20261102.md R2 item 5 and R4).

The transport's own ear (S0 ruling 2) is the rule of every call (the setting ``local_onset`` is gone: the owner's profile had it ``on``): ruling 2 as
built (the silence auto-repeat waits while the listener is heard), plus a hard bound: a ready cue is never held by the ear for more than
ONSET_HOLD_MAX_S (1.0 s) in all, so continuous noise or a TV cannot stall the dictation. The tail trim and the clear of an abandoned cue are
rules of the call as well.
"""
import asyncio
import json
import logging
import time
from types import SimpleNamespace

import pytest

import helpers_s6_ack as H
from echo_sync import local_ear, settings as cfg
from echo_sync.cm_speech import SpeechMixin
from echo_sync.controlled_media import ControlledMedia, HEARING_SECONDS
from echo_sync.native_media_socket import NativeMediaSocket
from helpers_s0_audio import ROOM, appends, cue_pcm, mix, ms, noise, pcm, room, speech, talking

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
PORTION = 'Свойство тела'










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




def test_every_call_runs_the_transports_own_ear_with_no_key_asking_for_it(tmp_path):
    wire = serve_with(tmp_path / 'home')
    assert wire.onset is not None and 'local_onset' not in cfg.resolve(None)


# --------------------------------------------------------------------------------------------------------------------
# the transport's own ear
# --------------------------------------------------------------------------------------------------------------------

class Ears:
    """A controller that only counts what the transport's ear tells it."""

    def __init__(self):
        self.onsets, self.speech = 0, 0

    def local_onset(self):
        self.onsets += 1

    def local_speech(self):
        self.speech += 1


def listen(events, **options):
    """Feed ``events`` (microphone packets) to a ready transport."""
    ears = Ears()

    async def run():
        async def emit(frame):
            pass

        now = [0.0]        # U77: the packets arrive in real time (100 ms apart); at one instant the queue trim would give the quiet ones back
        socket = NativeMediaSocket(ears, emit, None, None, None, **{'clock': lambda: now[0], **options})
        socket.ready, socket.source = True, H.FakeSource()
        for event in events:
            await socket.client(event)
            now[0] += 0.1
        return socket

    return ears, asyncio.run(run())


SPEECH = room(1.0) + talking(1.0) + room(1.0)


def onset_lines(caplog):
    return [r.getMessage() for r in caplog.records if 'local speech onset' in r.getMessage()]






def test_the_ear_tells_the_controller_and_logs_the_start_of_speech(caplog):
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        ears, socket = listen(SPEECH)
    assert ears.onsets == 1 and ears.speech >= 8
    lines = onset_lines(caplog)
    assert len(lines) == 1 and 'level_db=' in lines[0] and 'floor_db=' in lines[0], lines










# --------------------------------------------------------------------------------------------------------------------
# 'on': a ready cue is held by the ear for ONSET_HOLD_MAX_S in all, never longer
# --------------------------------------------------------------------------------------------------------------------

def hold_limit():
    from echo_sync import timer_policy
    return timer_policy.ONSET_HOLD_MAX_S


def test_the_bound_is_one_second():
    assert hold_limit() == 1.0


def test_the_controller_tells_whether_only_the_local_ear_hears_the_listener(tmp_path):
    d = H.Dictation(tmp_path, ANSWER)
    c = d.controller
    assert not (c.hearing and c._heard_locally)
    c.local_onset()
    assert (c.hearing and c._heard_locally), 'the ear alone'
    c.speech_started()
    assert c.hearing and not (c.hearing and c._heard_locally), 'the cloud has heard the listener too'
    c.local_onset()
    assert not (c.hearing and c._heard_locally), 'an onset does not take the flag away from the cloud'
    c.hearing = False
    c.local_onset()
    d.clock.advance(HEARING_SECONDS + 0.1)
    assert not (c.hearing and c._heard_locally), 'released like any other flag'


class Rig:
    """NativeMediaSocket over ControlledMedia on ONE fake clock: microphone packets every 100 ms, and the host's tick after
    each, as controlled_host does. ``started``: (clock, text) of every cue the transport began to synthesize."""

    def __init__(self, directory):
        self.clock = H.FakeClock()
        self.controller = c = ControlledMedia(directory / 'state.sqlite3', session_id=H.SESSION, clock=self.clock, **H.HOST_KWARGS)
        c.engine.clock = self.clock
        self.started = []

        async def emit(frame):
            pass

        async def synthesize(text, end=None):
            self.started.append((self.clock(), text))
            return cue_pcm(60)

        self.socket = NativeMediaSocket(c, emit, None, None, synthesize, clock=self.clock)
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
        assert (rig.controller.hearing and rig.controller._heard_locally), 'precondition: the ear hears it, the cloud said nothing'
        ready = rig.clock()
        await rig.answer()                                    # the answer arrives: its first cue is ready
        assert rig.started == [], 'precondition: the ear holds the ready cue'
        await rig.hear(source(8.0))                           # the noise goes on and on
        return ready, rig.started
    ready, started = asyncio.run(run())
    assert started, 'the dictation stalled behind the noise'
    held = started[0][0] - ready
    assert hold_limit() - 0.11 <= held <= hold_limit() + 1e-6, f'held {held:.2f} s'


class Listener(SpeechMixin):
    """The controller as the transport sees it, its flags set by hand; the verdict ``hold`` is the real one (wire-hold)."""

    def __init__(self):
        self.hearing, self.local, self.question_id = False, False, None
        self.ledger = SimpleNamespace(snapshot=lambda tid: None)
        self.user_boundaries, self.clock = {}, None

    @property
    def _heard_locally(self):
        return self.local

    def first_cue_hold(self):
        return None

    def authorized(self, cue):
        return True

    def held_cue(self, cue):        # U58 (34cfdf3f): the transport asks the controller for a held cue before it releases one; the fake holds none
        return None

    def cue_started(self, cue, *, voiced_seconds=None):
        pass

    def playback_done(self, cue, *, now, voiced_until=None):
        pass


def parked():
    """A ready transport over a Listener on a fake clock; ``started`` records every cue it began."""
    clock, listener, started = H.FakeClock(), Listener(), []
    listener.clock = clock

    async def emit(frame):
        pass

    async def synthesize(text, end=None):
        started.append((clock(), text))
        return cue_pcm(60)

    socket = NativeMediaSocket(listener, emit, None, None, synthesize, clock=clock)
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




def test_the_tail_trim_and_the_clear_of_an_abandoned_cue_are_rules_of_the_call():
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

        async def synthesize(text, end=None):
            return cue_pcm(400, 780)

        socket = NativeMediaSocket(Controller(), emit, None, None, synthesize)
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
        socket.clock, listener.clock, started = time.monotonic, time.monotonic, []      # the verdict of the controller and the timer of the socket count on one clock (as in the host)

        async def synthesize(text, end=None):
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
