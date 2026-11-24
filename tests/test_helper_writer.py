"""WAVE 2 / Task D, part 2 (DEF-FAULT-11), the piece in helper_bridge.py: a writer that never makes its caller wait for the pipe.

Before: ``NativeMediaSocket.client`` awaited ``source.send('P', pcm)`` in the loop that reads the phone. A helper that stopped
reading its stdin (a full pipe) never let ``drain()`` return, so the phone's ``response.cancel`` was never read, nothing timed
out and nothing was logged, while the ticker went on repeating the cue (17 repeats in 55 s measured).

Required (wave2/task-d-brief.md): writes never block the event loop or the audio path; a bounded writer queue with a timeout;
on a stall the channel diagnostic and a clean close.

The contract tested here: ``put`` never waits and never raises; frames reach the pipe in order; ONE write may stay pending for
``HELPER_WRITE_TIMEOUT_S``; more than ``HELPER_QUEUE_MAX_BYTES`` un-written bytes is a stall too; a failure is reported once, with a
fixed token (never free text), and nothing is written afterwards; ``close`` returns at once even when a write is stuck.
Pure asyncio on the virtual clock of helpers_s6_fault: nothing sleeps.
"""
import asyncio
import logging

import pytest

import helpers_s6_fault as F
from echo_sync import helper_bridge
from echo_sync.helper_bridge import BoundedWriter, HELPER_QUEUE_MAX_BYTES, HELPER_WRITE_TIMEOUT_S


class Pipe:
    """The helper's stdin seen from the writer: records what was written; ``delay`` per write, ``stuck`` never returns."""

    def __init__(self, *, delay=0.0, stuck=False, fail=None):
        self.written, self.delay, self.stuck, self.fail = [], delay, stuck, fail
        self.calls = 0

    async def send(self, kind, payload=b''):
        self.calls += 1
        if self.stuck:
            await asyncio.Event().wait()
        if self.fail is not None:
            raise self.fail
        if self.delay:
            await asyncio.sleep(self.delay)
        self.written.append((kind, payload))


def run(coro_factory):
    return F.run(coro_factory)


def test_the_limits_are_named_constants_with_a_reason():
    assert HELPER_WRITE_TIMEOUT_S == 5.0
    # 1 MiB of 24 kHz 16-bit PCM is 21 s of audio: far more than the 5 s a stall is tolerated, so only a stall can overflow it.
    assert HELPER_QUEUE_MAX_BYTES == 1 << 20
    assert HELPER_QUEUE_MAX_BYTES / 48000 > 4 * HELPER_WRITE_TIMEOUT_S


def test_frames_reach_the_pipe_in_the_order_they_were_put_whatever_their_kind():
    async def main():
        pipe, failures = Pipe(), []
        writer = BoundedWriter(pipe.send, on_failure=failures.append)
        writer.start()
        frames = [('P', b'a' * 960), ('E', b'{"x":1}'), ('P', b'b' * 960), ('E', b'{"y":2}'), ('P', b'')]
        assert all(writer.put(kind, payload) for kind, payload in frames)
        await asyncio.sleep(1)
        assert pipe.written == frames and failures == [] and writer.failed is None
        await writer.close()
    run(main)


def test_put_never_waits_for_the_pipe_and_never_raises():
    """The point of the writer: with a pipe that never takes a byte, a caller still gets control back at once."""
    async def main():
        pipe = Pipe(stuck=True)
        writer = BoundedWriter(pipe.send)
        writer.start()
        loop = asyncio.get_running_loop()
        before = loop.time()
        results = [writer.put('P', b'x' * 960) for _ in range(200)]
        assert loop.time() == before, 'put waited'
        assert all(results[:200]), 'all of them fit in the queue'
        await writer.close()
    run(main)


def test_a_write_that_never_returns_is_a_stall_after_the_timeout_and_reported_once():
    async def main():
        pipe, failures = Pipe(stuck=True), []
        loop = asyncio.get_running_loop()
        writer = BoundedWriter(pipe.send, on_failure=failures.append)
        writer.start()
        t0 = loop.time()
        writer.put('P', b'x' * 960)
        await asyncio.sleep(HELPER_WRITE_TIMEOUT_S - 0.5)
        assert failures == [] and writer.failed is None, 'a write that has not had its time yet was called a stall'
        await asyncio.sleep(1.0)
        assert failures == ['helper_write_stalled'] and writer.failed == 'helper_write_stalled'
        await asyncio.sleep(60)
        assert failures == ['helper_write_stalled'], 'reported more than once'
        assert pipe.calls == 1, 'a stalled pipe was written to again'
        await writer.close()
    run(main)


def test_after_a_failure_nothing_is_queued_or_written():
    async def main():
        pipe, failures = Pipe(stuck=True), []
        writer = BoundedWriter(pipe.send, on_failure=failures.append)
        writer.start()
        for _ in range(5):
            writer.put('P', b'x' * 960)
        await asyncio.sleep(HELPER_WRITE_TIMEOUT_S + 1)
        assert writer.failed
        assert writer.put('P', b'late') is False and writer.put('E', b'{}') is False
        assert writer.queued_bytes == 0, 'the frames behind the stalled one are dropped with the channel'
        await writer.close()
    run(main)


def test_a_write_that_raises_is_a_failure_with_its_own_token_and_the_type_is_logged_not_the_text(caplog):
    async def main():
        pipe, failures = Pipe(fail=BrokenPipeError('secret-token-1234 in the message')), []
        writer = BoundedWriter(pipe.send, on_failure=failures.append)
        writer.start()
        writer.put('P', b'x' * 960)
        await asyncio.sleep(1)
        assert failures == ['helper_write_failed']
        await writer.close()
    with caplog.at_level(logging.DEBUG):
        run(main)
    assert 'BrokenPipeError' in caplog.text and 'secret-token' not in caplog.text


def test_more_un_written_bytes_than_the_bound_is_a_stall_at_once_and_the_queue_never_exceeds_it():
    async def main():
        pipe, failures = Pipe(stuck=True), []
        writer = BoundedWriter(pipe.send, on_failure=failures.append)
        writer.start()
        peak, accepted = 0, 0
        for _ in range(500):                                       # 500 * 96000 B = 46 MB from a phone, into a pipe that takes nothing
            if writer.put('P', b'\0' * 96000):
                accepted += 1
            peak = max(peak, writer.queued_bytes)
            if writer.failed:
                break
        assert failures == ['helper_queue_full'], failures
        assert peak <= HELPER_QUEUE_MAX_BYTES, f'{peak} bytes queued'
        assert 1 <= accepted <= HELPER_QUEUE_MAX_BYTES // 96000 + 1
        assert writer.queued_bytes == 0
        await writer.close()
    run(main)


def test_a_slow_but_living_pipe_is_not_a_stall():
    async def main():
        pipe, failures = Pipe(delay=HELPER_WRITE_TIMEOUT_S - 1), []
        writer = BoundedWriter(pipe.send, on_failure=failures.append)
        writer.start()
        for n in range(4):
            writer.put('P', bytes([n]) * 960)
        await asyncio.sleep(4 * HELPER_WRITE_TIMEOUT_S)
        assert [payload[0] for _, payload in pipe.written] == [0, 1, 2, 3] and failures == []
        await writer.close()
    run(main)


def test_close_returns_at_once_even_when_a_write_is_stuck_and_leaves_nothing_behind():
    async def main():
        pipe, failures = Pipe(stuck=True), []
        loop = asyncio.get_running_loop()
        writer = BoundedWriter(pipe.send, on_failure=failures.append)
        writer.start()
        writer.put('P', b'x' * 960)
        await asyncio.sleep(0.5)
        t0 = loop.time()
        await writer.close()
        assert loop.time() - t0 < 0.1, 'close waited for the stuck write'
        assert writer.put('P', b'x') is False
        await asyncio.sleep(HELPER_WRITE_TIMEOUT_S * 3)
        assert failures == [], 'a closed writer reported a stall'
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()], 'a task was left behind'
    run(main)


def test_a_failing_callback_cannot_break_the_writer_or_the_caller_of_put():
    async def main():
        def boom(reason):
            raise RuntimeError('the callback is broken')
        pipe = Pipe(stuck=True)
        writer = BoundedWriter(pipe.send, on_failure=boom)
        writer.start()
        writer.put('P', b'x')
        await asyncio.sleep(HELPER_WRITE_TIMEOUT_S + 1)
        assert writer.failed == 'helper_write_stalled'
        await writer.close()
        # the other way in: the overflow is found inside put(), whose caller must never see the callback's error
        other = BoundedWriter(Pipe(stuck=True).send, on_failure=boom, max_bytes=100)
        other.start()
        assert other.put('P', b'x' * 200) is False and other.failed == 'helper_queue_full'
        await other.close()
    run(main)


def test_a_failure_is_reported_once_whoever_notices_it_again():
    """The contract the host relies on (one announcement, one close): a second path to the same failure reports nothing."""
    async def main():
        pipe, failures = Pipe(stuck=True), []
        writer = BoundedWriter(pipe.send, on_failure=failures.append)
        writer.start()
        writer.put('P', b'x')
        await asyncio.sleep(HELPER_WRITE_TIMEOUT_S + 1)
        writer._fail('helper_queue_full')
        writer._fail('helper_write_failed')
        assert failures == ['helper_write_stalled'] and writer.failed == 'helper_write_stalled'
        await writer.close()
    run(main)


def test_the_timeout_and_the_bound_can_be_given_to_one_writer():
    async def main():
        pipe, failures = Pipe(stuck=True), []
        writer = BoundedWriter(pipe.send, on_failure=failures.append, timeout=0.5, max_bytes=2000)
        writer.start()
        writer.put('P', b'x' * 960)
        await asyncio.sleep(0.4)
        assert failures == []
        await asyncio.sleep(0.2)
        assert failures == ['helper_write_stalled']
        other = BoundedWriter(Pipe(stuck=True).send, on_failure=failures.append, max_bytes=2000)
        other.start()
        assert other.put('P', b'x' * 1000) and other.put('P', b'x' * 1000) is False
        assert failures[-1] == 'helper_queue_full'
        await writer.close()
        await other.close()
    run(main)
