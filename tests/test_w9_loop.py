"""w9-loop: what blocks the loop and the pieces that take it off (echo_sync/loop_guard.py). Fakes only at the boundary: a slow SQLite, a slow disk,
a scripted Silero model; the detector, the loop and the threads are production code."""
import asyncio
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from helpers_r_vad import ScriptedModel                       # noqa: E402
from helpers_s0_audio import RATE, packets, pcm, speech  # noqa: E402
from echo_sync import loop_guard as lg                        # noqa: E402
from echo_sync.vad_silero import SileroOnset                  # noqa: E402


def slow_commit(seconds):
    """A SQLite commit that costs `seconds` (a Windows fsync): the engine's real pattern - connect, write, commit, close - plus the stall."""
    def work():
        db = sqlite3.connect(':memory:')
        db.execute('create table t(x)')
        with db:
            db.execute('insert into t values (1)')
            time.sleep(seconds)
        db.close()
    return work


async def lag_while(body):
    meter = lg.LagMeter(0.005)
    task = asyncio.create_task(meter.run())
    await asyncio.sleep(0.05)
    await body()
    await asyncio.sleep(0.05)
    meter.stop()
    await task
    return meter.summary()


def test_lag_meter_sees_a_blocking_commit_and_the_worker_removes_it():
    async def main():
        async def on_loop():
            for _ in range(5):
                slow_commit(0.04)()                      # today: the controller commits on the loop
                await asyncio.sleep(0)
        async def off_loop():
            worker = lg.SerialWorker()
            for _ in range(5):
                await worker.run(slow_commit(0.04))
            worker.close()
        return await lag_while(on_loop), await lag_while(off_loop)
    blocked, free = asyncio.run(main())
    assert blocked['max_ms'] >= 35
    assert free['max_ms'] < 15


def test_serial_worker_keeps_order_and_returns_errors():
    async def main():
        worker, seen = lg.SerialWorker(), []
        futures = [worker.run(seen.append, k) for k in range(50)]
        await asyncio.gather(*futures)
        def boom():
            raise KeyError('x')
        with pytest.raises(KeyError):
            await worker.run(boom)
        worker.close()
        with pytest.raises(RuntimeError):
            worker.run(seen.append, 1)
        return seen
    assert asyncio.run(main()) == list(range(50))


def test_threaded_file_does_not_wait_for_a_stalled_disk_and_bounds_its_queue():
    class Stalled:
        def __init__(self):
            self.lines = []
        def write(self, line):
            time.sleep(0.05)
            self.lines.append(line)
        def close(self):
            pass
    disk = Stalled()
    out = lg.ThreadedFile(disk, limit=3)
    began = time.perf_counter()
    for k in range(10):
        out.write(f'{k}\n')
    assert time.perf_counter() - began < 0.02
    assert out.dropped >= 5
    out.close()
    assert disk.lines[0] == '0\n' and len(disk.lines) + out.dropped == 10


def speech_script(n=40):
    return [True] * n + [False] * 20


def test_the_ear_does_not_run_silero_a_second_time():
    packs = packets(pcm(speech(1500)))                           # any audio: the model is scripted
    def run(shared):
        wire_model, ear_model = ScriptedModel(speech_script()), ScriptedModel(speech_script())
        wire = lg.SharedOnset(SileroOnset(wire_model, sample_rate=RATE))
        ear = lg.EarTap(wire, SileroOnset(ear_model, sample_rate=RATE)) if shared else SileroOnset(ear_model, sample_rate=RATE)
        verdicts = []
        for p in packs:
            a = wire.feed(p)
            verdicts.append((a, ear.feed(p)))
        return wire_model.calls, ear_model.calls, verdicts
    w0, e0, v0 = run(False)
    w1, e1, v1 = run(True)
    assert w0 == w1 > 0 and e0 == w0                        # before: two models, the same work twice
    assert e1 == 0                                           # after: the ear's model never runs
    assert all(a == b for a, b in v1) and v1 == [(a, a) for a, _ in v0]


def test_ear_tap_falls_back_for_a_packet_the_transport_did_not_hear():
    wire = lg.SharedOnset(SileroOnset(ScriptedModel([True] * 30), sample_rate=RATE))
    own = SileroOnset(ScriptedModel([True] * 30), sample_rate=RATE)
    ear = lg.EarTap(wire, own)
    p = packets(pcm(speech(300)))
    assert ear.feed(p[0]) in ('onset', 'speech', None) and ear.own == 1 and ear.reused == 0
    wire.feed(p[1])
    ear.feed(p[1])
    assert ear.reused == 1
    assert ear.preroll_packets == 4 and ear.engine == 'silero'
    assert lg.EarTap(wire).feed(p[2]) is None


def test_wake_ticker_runs_at_once_on_a_wake_and_keeps_the_ceiling():
    async def main():
        t = lg.WakeTicker(0.1)
        t.bind()
        began = time.perf_counter()
        asyncio.get_running_loop().call_later(0.01, t.wake)
        await t.wait()
        woke = time.perf_counter() - began
        began = time.perf_counter()
        await t.wait()
        return woke, time.perf_counter() - began, t.wakes, t.timeouts
    woke, ceiling, wakes, timeouts = asyncio.run(main())
    assert woke < 0.05 and 0.09 < ceiling < 0.2 and (wakes, timeouts) == (1, 1)


def test_wake_from_another_thread_and_after_close_is_safe():
    import threading
    async def main():
        t = lg.WakeTicker(1)
        t.bind()
        threading.Timer(0.01, t.wake).start()
        began = time.perf_counter()
        await t.wait()
        return time.perf_counter() - began
    assert asyncio.run(main()) < 0.3
    lg.WakeTicker().wake()                                   # unbound: no-op


def test_warm_start_has_no_key_the_server_always_warms():
    from echo_sync import settings
    assert 'warm_start' not in settings.DEFAULTS and 'warm_start' not in settings.resolve({'warm_start': 'off'})


def test_call_trace_threaded_writes_the_same_lines_without_the_loop_waiting(tmp_path):
    from echo_sync.call_trace import CallTrace
    t = CallTrace(tmp_path, 'abc', threaded=True)
    t.open(source='phone')
    for k in range(20):
        t.note('x', k=k)
    t.close(elapsed_ms=1, ready=True, counters={})
    text = t.path.read_text()
    assert text.count('"ev":"x"') == 20
