"""g9-boot: the order of what a call needs. Lanes run beside each other, the first question is kept while the channel is not ready, the server's warm parts survive a long life."""
import asyncio
import base64
import threading
import time

from echo_sync import warm
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket


def test_lanes_run_beside_each_other_and_keep_their_own_order():
    seen, lock = [], threading.Lock()
    def mk(tag, wait=0.0):
        def fn():
            time.sleep(wait)
            with lock:
                seen.append(tag)
        return fn
    plan = [warm.Step('a1', mk('a1', .15), lane='a'), warm.Step('b1', mk('b1', .15), lane='b'), warm.Step('a2', mk('a2'), lane='a'), warm.Step('c1', mk('c1', .15), lane='c')]
    began = time.perf_counter()
    done = warm.run_plan(plan)
    assert time.perf_counter() - began < .28                       # 3 x 0.15 s in a row would be 0.45
    assert [d['name'] for d in done] == ['a1', 'b1', 'a2', 'c1'] and all(d['ok'] for d in done)
    assert seen.index('a1') < seen.index('a2')


def test_default_steps_put_the_slow_ear_and_voice_beside_the_question_path():
    lanes = {s.name: s.lane for s in warm.default_steps('.')}
    assert lanes['reference_kb'] == lanes['classifier'] == lanes['material']
    assert len({lanes['voice'], lanes['vad'], lanes['ear_model'], lanes['classifier']}) == 4


def test_pool_failure_is_forgotten_once_a_model_is_built():
    state = {'n': 0}
    def factory():
        state['n'] += 1
        if state['n'] == 1:
            raise OSError('x')
        return object()
    pool = warm.ModelPool(factory)
    pool.fill()
    assert pool.failed == 'OSError'
    pool.fill()
    assert pool.failed is None and len(pool.items) == 1


def test_a_changed_file_with_the_same_size_and_time_is_still_read_again(tmp_path):
    (tmp_path / 'materials').mkdir()
    f = tmp_path / 'materials' / 'context.md'
    f.write_text('aaaa')
    import os
    os.utime(f, ns=(10**18, 10**18))
    reads = []
    cache = warm.MaterialCache(lambda home: reads.append(1) or f.read_text())
    assert cache.load(tmp_path) == 'aaaa'
    f.unlink()
    f.write_text('bbbb')
    os.utime(f, ns=(10**18, 10**18))
    assert cache.load(tmp_path) == 'bbbb'


def test_idle_guard_thread_pings_and_revives_a_dead_resource():
    log = []
    guard = warm.IdleGuard()
    def ping():
        log.append('ping')
        raise RuntimeError('dead')
    guard.add('r', ping, idle_s=0.0, revive=lambda: log.append('revive'))
    thread = guard.start(period=0.02)
    deadline = time.time() + 2
    while 'revive' not in log and time.time() < deadline:
        time.sleep(.01)
    guard.stop()
    assert log[:2] == ['ping', 'revive'] and thread.daemon


def test_a_hanging_ping_does_not_stop_the_other_resources():
    guard, log = warm.IdleGuard(), []
    gate = threading.Event()
    guard.add('hang', gate.wait, idle_s=0.0)
    guard.add('ok', lambda: log.append('ok'), idle_s=0.0)
    guard.start(period=0.02)
    deadline = time.time() + 2
    while not log and time.time() < deadline:
        time.sleep(.01)
    guard.stop()
    gate.set()
    assert log


def test_start_server_warm_keeps_the_ear_and_the_voice_alive_after_start():
    class Voice:
        n = 0
        def keep_resident(self):
            Voice.n += 1
    thread = warm.start_server_warm('.', voice=Voice(), ear=None, guard_period=0.02, voice_idle_s=0.0)
    thread.join(5)
    deadline = time.time() + 2
    while Voice.n < 3 and time.time() < deadline:
        time.sleep(.01)
    warm.guard.stop()
    assert Voice.n >= 3


class Source:
    def __init__(self):
        self.frames = []
    async def send(self, kind, payload=b''):
        self.frames.append((kind, payload))
    async def close(self):
        pass


def _pcm(ms):
    return b'\x01\x02' * (24 * ms)


def _append(pcm):
    return {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode()}


def _wire(tmp_path):
    out = []
    async def emit(event):
        out.append(event)
    async def lookup(q):
        return []
    async def synth(t, end=None):
        return b''
    wire = NativeMediaSocket(ControlledMedia(tmp_path / 'c.db', session_id='s'), emit, lambda: None, lookup, synth)
    wire.source = Source()
    return wire, out


def _until_ready(wire):
    async def go():
        await wire.client({'type': 'response.create', 'response': {'conversation': 'none', 'input': [{'content': [{'text': 'conduit-ready-1'}]}]}})
        await wire.client({'type': 'conduit.turn.done', 'turn_id': wire.marker_id})
    return go()


def test_the_first_question_spoken_before_the_channel_is_ready_is_kept(tmp_path):
    async def go():
        wire, _ = _wire(tmp_path)
        for _ in range(5):
            await wire.client(_append(_pcm(20)))
        assert wire.source.frames == []
        await _until_ready(wire)
        sent = [p for k, p in wire.source.frames if k == 'P']
        assert len(sent) == 5 and wire.ready
        await wire.client(_append(_pcm(20)))
        assert len([1 for k, _ in wire.source.frames if k == 'P']) == 6
    asyncio.run(go())


def test_the_kept_audio_is_bounded_and_keeps_the_newest(tmp_path):
    async def go():
        wire, _ = _wire(tmp_path)
        last = None
        for i in range(400):                           # 8 s of 20 ms packets
            last = bytes([i % 250 + 1, 0]) * (24 * 20)
            await wire.client(_append(last))
        await _until_ready(wire)
        sent = [p for k, p in wire.source.frames if k == 'P']
        assert 0 < sum(len(p) for p in sent) <= 6 * 48000 and sent[-1] == last
    asyncio.run(go())


def test_audio_after_close_before_ready_is_not_kept(tmp_path):
    async def go():
        wire, _ = _wire(tmp_path)
        wire.closed = True
        await wire.client(_append(_pcm(20)))
        assert not wire.pre_ready
    asyncio.run(go())


def test_audio_before_ready_is_kept_by_default_there_is_no_switch(tmp_path):      # U76, on purpose: it was "not forwarded by default"; the buffer is now the only path, keep_pre_ready is gone
    async def go():
        wire, _ = _wire(tmp_path)
        assert not hasattr(wire, 'keep_pre_ready')
        await wire.client(_append(_pcm(20)))
        assert len(wire.pre_ready) == 1 and wire.source.frames == []
        await _until_ready(wire)
        assert len([1 for k, _ in wire.source.frames if k == 'P']) == 1 and not wire.pre_ready
    asyncio.run(go())
