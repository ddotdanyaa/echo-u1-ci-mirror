"""WAVE 2 / Task D, part 2 (DEF-FAULT-11): the stall and the close against a REAL pipe to a REAL child process.

Everything else about the stall is tested on a fake pipe and a virtual clock. What a fake cannot show is that the real
``ThreadedHelperBridge`` (a private Proactor loop in its own thread, asyncio's Windows pipes) behaves the way the writer
assumes: a child that stops reading its stdin really blocks ``drain()``, a cancelled write really lets go, and ``close()``
does not hang behind the data that nobody reads (its ``Q`` frame is queued behind them) but ends the child.

The child here never reads a byte (it sleeps); the limits are shortened so that the test takes a few real seconds.
"""
import asyncio
import os
import sys
import time

import pytest

from echo_sync import helper_bridge
from echo_sync.helper_bridge import BoundedWriter, ThreadedHelperBridge

DEAF = "import time\ntime.sleep(120)\n"        # a helper that is alive and never reads stdin


def runner(coro_factory):
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as loop:
        return loop.run(coro_factory())


@pytest.fixture
def quick_close(monkeypatch):
    monkeypatch.setattr(helper_bridge, 'CLOSE_QUIT_S', 0.3)
    monkeypatch.setattr(helper_bridge, 'CLOSE_WAIT_S', 0.5)
    monkeypatch.setattr(helper_bridge, 'CLOSE_KILL_S', 3.0)


async def wait_for_condition(predicate, within):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


def test_a_real_child_that_never_reads_is_a_stall_and_its_bridge_still_closes(tmp_path, quick_close):
    script = tmp_path / 'deaf.py'
    script.write_text(DEAF, encoding='utf-8')

    async def run():
        bridge = ThreadedHelperBridge(script, python=sys.executable)
        failures = []
        await bridge.start()
        writer = BoundedWriter(bridge.send, on_failure=failures.append, timeout=1.0)
        writer.start()
        t0 = time.monotonic()
        for _ in range(12):                                         # 720 kB: far above the pipe and the transport's buffer
            writer.put('P', b'\0' * 60000)
        assert await wait_for_condition(lambda: failures, 10), 'a pipe nobody reads was never called a stall'
        stalled_after = time.monotonic() - t0
        assert failures == ['helper_write_stalled'], failures
        assert stalled_after >= 1.0, f'{stalled_after:.2f} s: a write was called a stall before its time'
        await writer.close()
        t1 = time.monotonic()
        exit_code = await asyncio.wait_for(bridge.close(), 15)
        assert time.monotonic() - t1 < 8, 'the close of a bridge with a deaf child took too long'
        assert exit_code is not None and bridge.process.returncode is not None, 'the child is still running'
        assert not bridge.thread.is_alive()
    runner(run)


def test_close_alone_does_not_hang_behind_the_data_nobody_reads(tmp_path, quick_close):
    """Nobody called the writer's close: a write is still stuck in the pipe when the bridge is closed (the order of a crash)."""
    script = tmp_path / 'deaf.py'
    script.write_text(DEAF, encoding='utf-8')

    async def run():
        bridge = ThreadedHelperBridge(script, python=sys.executable)
        await bridge.start()
        stuck = asyncio.ensure_future(bridge.send('P', b'\0' * 900000))      # blocks in drain(): the buffer never empties
        await asyncio.sleep(0.5)
        assert not stuck.done(), 'precondition: the write must be blocked'
        t0 = time.monotonic()
        exit_code = await asyncio.wait_for(bridge.close(), 15)
        assert time.monotonic() - t0 < 8, 'close() hung behind the stuck write'
        assert exit_code is not None and bridge.process.returncode is not None
        stuck.cancel()
        await asyncio.gather(stuck, return_exceptions=True)
    runner(run)


@pytest.mark.skipif(os.name != 'nt', reason='Windows event-loop regression')
def test_a_child_that_reads_everything_never_trips_the_writer(tmp_path):
    script = tmp_path / 'reader.py'
    script.write_text("import sys\nwhile sys.stdin.buffer.read(65536):\n    pass\n", encoding='utf-8')

    async def run():
        bridge = ThreadedHelperBridge(script, python=sys.executable)
        failures = []
        await bridge.start()
        writer = BoundedWriter(bridge.send, on_failure=failures.append, timeout=10.0)     # generous: the child may start slowly on a busy machine
        writer.start()
        for _ in range(40):                                         # 2.4 MB in total, in arrival order, with the child reading all of it
            assert writer.put('P', b'\0' * 60000)
            await asyncio.sleep(0.02)
        await asyncio.sleep(1.0)
        assert failures == [] and writer.failed is None
        await writer.close()
        assert await asyncio.wait_for(bridge.close(), 15) == 0
    runner(run)


def test_close_with_a_reader_waiting_on_the_pipe_ends_the_child_and_the_reader(tmp_path, quick_close):
    """c22-reviewfix (review 4a91807, local-lifecycle): on helper_write_stalled / helper_write_failed / helper_queue_full local mode closes
    the bridge while the call's reader still waits in ``receive``. ``communicate()`` then meets that reader on stdout and raised
    RuntimeError: the child was never terminated, the reader's future never resolved, and a second close was a no-op."""
    script = tmp_path / 'deaf.py'
    script.write_text(DEAF, encoding='utf-8')

    async def run():
        bridge = ThreadedHelperBridge(script, python=sys.executable)
        await bridge.start()
        reader = asyncio.ensure_future(bridge.receive(30))
        await asyncio.sleep(0.3)
        assert not reader.done(), 'precondition: the reader waits on the pipe'
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(bridge.close(), 15)
        except RuntimeError as error:
            pytest.fail(f'close met the reader: {error}')
        assert time.monotonic() - t0 < 8
        assert bridge.process.returncode is not None, 'the child outlives the close'
        assert await wait_for_condition(reader.done, 5), 'the reader waits for ever on a closed bridge'
        await asyncio.gather(reader, return_exceptions=True)
    runner(run)
