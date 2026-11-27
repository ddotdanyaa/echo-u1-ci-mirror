"""w8-net (N18, Б11, Ст4/Б10, N17): what the server itself holds of the audio and of the open. Every switch is off by default and
off is the old behaviour, pinned here too. Virtual time (helpers_s6_fault.VirtualLoop): the numbers are the code's schedule, not a
measurement of a network."""
import asyncio
import base64
import json
import math
import struct
import time as real_time
from pathlib import Path

import helpers_s6_fault as F
from echo_sync import controlled_host
from echo_sync import native_media_socket as nms
from echo_sync.controlled_host import SubscriptionSource, open_subscription
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import MIC_QUEUE_TRIM_MS, MicQueue, NativeMediaSocket, pcm_dbfs
from echo_sync.settings import DEFAULTS, resolve


def tone(ms, amplitude=8000):
    n = 24 * ms
    return struct.pack('<%dh' % n, *(int(amplitude * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(n)))


def quiet(ms):
    return b'\0' * (48 * ms)


class Source:
    def __init__(self):self.frames=[]
    async def send(self,kind,payload=b''):self.frames.append((kind,payload))
    async def close(self):pass


def wire_for(tmp_path, **options):
    sent = []
    async def emit(frame):sent.append((asyncio.get_running_loop().time(), frame))
    wire = NativeMediaSocket(ControlledMedia(tmp_path / 's.db', session_id='s'), emit, lambda: None, lambda _: None, lambda _: None, **options)
    return wire, sent


def play(tmp_path, monkeypatch, pcm, *, cancel_at=None, **options):
    """Pace ``pcm`` through ``_play`` on the virtual clock. Returns (start, frames with times, result, played-callback times)."""
    async def main():
        F.patch_clock(monkeypatch)
        wire, sent = wire_for(tmp_path, **options)
        loop = asyncio.get_running_loop();played = []
        start = loop.time()
        task = asyncio.create_task(wire._play(pcm, 'текст', wire.audio_generation, lambda: True, lambda began: played.append(loop.time())))
        if cancel_at is not None:
            await asyncio.sleep(cancel_at);wire.audio_generation += 1
        result = await task
        await wire.close()
        return start, sent, result, played
    return F.run(main)


# --- Б11: the head of a cue goes to the phone at once ----------------------------------------------------------------------------

def test_default_paces_every_frame_in_real_time(tmp_path, monkeypatch):
    start, sent, result, played = play(tmp_path, monkeypatch, tone(1000))
    audio = [t - start for t, f in sent if f['type'] == 'response.audio.delta']
    assert result is True and len(audio) == 50
    assert all(abs(t - i * 0.02) < 1e-6 for i, t in enumerate(audio))
    done = next(t for t, f in sent if f['type'] == 'response.done') - start
    assert abs(done - 0.98) < 1e-6 and abs(played[0] - start - 0.98) < 1e-6


def test_head_sends_the_first_250_ms_at_once_then_paces_ahead(tmp_path, monkeypatch):
    start, sent, result, played = play(tmp_path, monkeypatch, tone(1000), audio_head_ms=250)
    audio = [t - start for t, f in sent if f['type'] == 'response.audio.delta']
    assert result is True and len(audio) == 50
    assert all(t < 1e-6 for t in audio[:13])                   # offsets 0 .. 240 ms: at the first moment
    assert all(abs(t - max(0.0, i * 0.02 - 0.25)) < 1e-6 for i, t in enumerate(audio))
    assert abs(audio[-1] - 0.73) < 1e-6
    # response.done and the controller's «played» stay where the voice really ends: the phone's microphone gate and the silence timer
    # see no change; only the frames are ahead.
    done = next(t for t, f in sent if f['type'] == 'response.done') - start
    assert abs(done - 1.0) < 1e-6 and abs(played[0] - start - 1.0) < 1e-6
    first = [f['type'] for _, f in sent[:3]]
    assert first == ['response.created', 'response.audio_transcript.delta', 'response.audio.delta']


def test_head_cue_superseded_after_its_last_frame_sends_no_done_and_no_played(tmp_path, monkeypatch):
    # The last frame left at 0.73 s; a newer cue (or a cancel, which clears the phone) at 0.8 s: the old one must not claim it was played.
    start, sent, result, played = play(tmp_path, monkeypatch, tone(1000), cancel_at=0.8, audio_head_ms=250)
    assert result is False and played == []
    assert not any(f['type'] == 'response.done' for _, f in sent)


def test_head_is_bounded_and_off_by_default():
    assert DEFAULTS['audio_head_ms'] == 0 and resolve(None)['audio_head_ms'] == 0
    assert resolve({'audio_head_ms': 250})['audio_head_ms'] == 250
    assert resolve({'audio_head_ms': 5000})['audio_head_ms'] == 0          # out of range: the default
    assert resolve({'audio_head_ms': 20})['audio_head_ms'] == 0            # below one useful frame batch: off
    assert NativeMediaSocket.__init__.__kwdefaults__['audio_head_ms'] == 0


# --- Ст4 / Б10: the helper's microphone queue, modelled on the server ------------------------------------------------------------

def test_mic_queue_model_is_a_ratchet_a_stall_stays_as_delay():
    now = [0.0];q = MicQueue(lambda: now[0])
    for i in range(10):now[0] = i * 0.1;q.drain();q.add(100)
    assert abs(q.depth - 100) < 1e-6 and abs(q.max_ms - 100) < 1e-6
    now[0] = 1.4                                      # 400 ms of nothing: the helper sends zeros, its queue is empty
    assert q.drain() == 0.0
    for _ in range(4):q.drain();q.add(100)          # the late packets arrive in one burst
    assert abs(q.depth - 400) < 1e-6
    for i in range(1, 20):now[0] = 1.4 + i * 0.1;q.drain();q.add(100)
    assert abs(q.depth - 400) < 1e-6                  # steady again, and 300 ms later than before for the rest of the call
    assert q.cap_ms == 2000


def test_pcm_dbfs():
    assert pcm_dbfs(b'') == -math.inf and pcm_dbfs(quiet(100)) == -math.inf
    assert -16 < pcm_dbfs(tone(100)) < -14                  # a sine of 8000: RMS 5657, -15.3 dBFS


def feed(tmp_path, packets, **options):
    """``packets``: (arrival time, pcm). The wire's clock is the arrival time."""
    async def main():
        now = [0.0]
        wire, sent = wire_for(tmp_path, clock=lambda: now[0], **options)
        source = Source();wire.source = source;wire.ready = True
        for at, pcm in packets:
            now[0] = at
            await wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode()})
        await wire.close()
        return wire, source
    return asyncio.run(main())


def burst(kind):
    """Steady 100 ms packets, a 600 ms stall, the late ones in one burst, then steady again: ``kind`` is what they carry."""
    packets = [(i * 0.1, tone(100)) for i in range(5)]
    packets += [(1.1, kind(100)) for _ in range(6)]
    packets += [(1.1 + i * 0.1, kind(100)) for i in range(1, 11)]
    return packets


def test_there_is_no_mic_path_switch(tmp_path):      # U77: off/shadow are gone, the trimming path is the only one
    assert 'mic_path' not in DEFAULTS and 'mic_path' not in NativeMediaSocket.__init__.__kwdefaults__


def test_mic_trim_drops_quiet_backlog_only(tmp_path):
    wire, source = feed(tmp_path, burst(quiet))
    dropped = 21 - len(source.frames)
    assert dropped >= 4 and wire.mic_queue.dropped_ms == dropped * 100
    assert wire.mic_queue.depth <= MIC_QUEUE_TRIM_MS + 100
    assert wire.input_ms() == 2100 - dropped * 100                    # the provider's clock counts what was forwarded, as before
    wire, source = feed(tmp_path, burst(tone))      # speech is never dropped, however late
    assert len(source.frames) == 21 and wire.mic_queue.dropped_ms == 0


def test_mic_trim_never_drops_while_the_local_ear_hears_speech(tmp_path):
    class Speaking:
        speaking = True;level = floor = 0.0
        def feed(self, pcm):return None
    async def main():
        now = [0.0]
        wire, _ = wire_for(tmp_path, clock=lambda: now[0])
        wire.onset = Speaking();source = Source();wire.source = source;wire.ready = True
        for at, pcm in burst(quiet):
            now[0] = at
            await wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode()})
        await wire.close()
        return source
    assert len(asyncio.run(main()).frames) == 21


def test_mic_forwards_to_the_helper_before_the_local_detectors_run(tmp_path):
    """Б10/N18: the packet is queued for the helper and the helper's writer runs BEFORE Silero (≈9 ms a packet on the loop)."""
    def order():
        events = []
        class Bridge:
            async def send(self, kind, payload=b''):events.append('write')
            async def close(self):pass
        class Ear:
            speaking = False;level = floor = 0.0
            def feed(self, pcm):events.append('listen')
        async def main():
            wire, _ = wire_for(tmp_path)
            wire.onset = Ear();wire.source = SubscriptionSource(Bridge());wire.ready = True
            await wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(tone(100)).decode()})
            await asyncio.sleep(0.01)
            await wire.close()
        asyncio.run(main())
        return events
    assert order() == ['write', 'listen']


# --- N17: the owner's material is read while the helper starts, not before ---------------------------------------------------------

def test_open_subscription_takes_instructions_that_are_still_being_read():
    events = []
    class Bridge:
        def __init__(self, *a, **k):self.stage = 0
        async def start(self):events.append('start')
        async def send(self, kind, payload):events.append(kind)
        async def receive(self, timeout):
            self.stage += 1
            return [None, ('O', b'v=0\n'), ('R', b''), ('e', b'{"type":"session.started"}')][self.stage]
        async def close(self):pass
    async def scoped(profile, fn):return fn()
    seen = []
    def create(sdp, **kwargs):seen.append(kwargs['_content_instructions']);return {'auth': 'subscription', 'transport': {'sdp': 'a'}}
    from types import SimpleNamespace
    api = SimpleNamespace(_run_scoped=scoped, WATCH_AUDIO_CONNECT_TIMEOUT_S=1, WATCH_AUDIO_STUN=(), create_gpt_live_session=create, _limiter_key=lambda p: 'k')
    async def run():
        text = asyncio.get_running_loop().create_future()
        async def reader():
            await asyncio.sleep(0.05);events.append('read');text.set_result('POLICY+LESSON')
        task = asyncio.create_task(reader())
        await open_subscription(api, 'echo-sync', 'unused', ('python', {}, (), ''), bridge_factory=Bridge, instructions=text)
        await task
    asyncio.run(run())
    assert events.index('C') < events.index('read') < events.index('A')
    assert seen == ['POLICY+LESSON']


def overlap_order(tmp_path, monkeypatch, value):
    folder = Path(tmp_path) / 'home' / 'materials';folder.mkdir(parents=True)
    (folder / 'echo_settings.json').write_text(json.dumps({'open_overlap': value, 'subject': 'Физика'}), encoding='utf-8')
    (folder / 'context.md').write_text('Закон Ома связывает ток и напряжение.', encoding='utf-8')
    order = [];sent = []
    real_load = controlled_host.load_call_context
    def slow_load(home):
        order.append('context_start');real_time.sleep(0.05);order.append('context_end');return real_load(home)
    monkeypatch.setattr(controlled_host, 'load_call_context', slow_load)
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            real_open = controlled_host.open_subscription
            async def spy(*a, **k):
                order.append('open');return await real_open(*a, **k)
            monkeypatch.setattr(controlled_host, 'open_subscription', spy)
            def create(sdp, **kwargs):sent.append(kwargs['_content_instructions']);return {'auth': 'subscription', 'transport': {'sdp': 'a'}}
            host.api.create_gpt_live_session = create
            await host.handshake()
    F.run(main)
    assert len(sent) == 1 and 'Закон Ома' in sent[0] and 'Предмет занятия: Физика' in sent[0]
    return order


def test_open_overlap_off_reads_the_material_before_the_helper_starts(tmp_path, monkeypatch):
    assert overlap_order(tmp_path, monkeypatch, 'off') == ['context_start', 'context_end', 'open']
    assert DEFAULTS['open_overlap'] == 'off'


def test_open_overlap_on_starts_the_helper_while_the_material_is_read(tmp_path, monkeypatch):
    order = overlap_order(tmp_path, monkeypatch, 'on')
    assert order.index('open') < order.index('context_end')


def host_diagnostic_frames(tmp_path, monkeypatch, settings):
    """Through the real serve(): the profile's switches reach the wire. A bad microphone packet is spoken about (a diagnostic, paced by
    the same ``_play`` as a cue); the times of its PCM frames on the phone, from the first one."""
    folder = Path(tmp_path) / 'home' / 'materials';folder.mkdir(parents=True)
    (folder / 'echo_settings.json').write_text(json.dumps(settings), encoding='utf-8')
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
            await host.until(lambda: False, 1)          # the phrases are rendered at the open
            host.ws.push({'type': 'input_audio_buffer.append', 'audio': 'not-base64!'})
            await host.until(lambda: any(f.type == 'response.done' for f in host.ws.frames), 30)
            audio = [f.t for f in host.ws.frames if f.type == 'response.audio.delta']
            return [t - audio[0] for t in audio]
    return F.run(main)


def test_host_passes_the_head_to_the_wire(tmp_path, monkeypatch):
    # The rig's fake SAPI renders 100 ms (5 frames): a head of 40 ms sends three of them at once.
    times = host_diagnostic_frames(tmp_path / 'on', monkeypatch, {'audio_head_ms': 40})
    assert len(times) == 5 and all(abs(t - max(0.0, i * 0.02 - 0.04)) < 1e-6 for i, t in enumerate(times))
    times = host_diagnostic_frames(tmp_path / 'off', monkeypatch, {})
    assert len(times) == 5 and all(abs(t - i * 0.02) < 1e-6 for i, t in enumerate(times))


def test_the_context_line_says_how_long_the_material_took_to_read(tmp_path, monkeypatch):
    """N17: the read of the owner's material sits on the open (before the helper unless open_overlap is on); its time goes in the log
    line that already carries its sizes, so that agent.log splits the open without a new switch. A number only."""
    import re
    import logging
    from helpers_spoken_diagnostics import run_host
    async def body(host):
        await host.handshake()
        line = next(l for l in host.logger.text(logging.INFO).splitlines() if l.startswith('Controlled call context'))
        assert re.search(r' read_ms=\d+ ', line), line
    run_host(tmp_path, monkeypatch, body, handshake=False)
