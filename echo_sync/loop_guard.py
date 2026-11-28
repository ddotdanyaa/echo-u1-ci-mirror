"""w9-loop (N105, N111, N112, B12): what blocks the event loop of a call, and the small pieces that take it off. Pure module, nothing imports it yet
(patches in cloud_context/reports/w9-loop.md); every piece is inert until the host builds it.

* ``LagMeter`` - the loop's own lag: a coroutine that sleeps ``period`` and records how late it woke. Max/p99 of that is "how long the loop was
  blocked" whatever the cause (SQLite commit, classifier, Silero, a log write). It is the measurement the patches are judged by.
* ``SerialWorker`` - ONE thread, FIFO: ``await worker.run(fn, *a)``. Calls keep their order, so state that is not thread-safe (the controller)
  is only ever touched by this thread when ALL its calls go through it; ``run`` from the loop never blocks the loop.
* ``ThreadedFile`` - a file-like (``write``/``flush``/``close``) whose writes are queued to a writer thread: the journal's ``_write_line``
  (call_trace) returns at once, a stalled disk costs the loop nothing. Bounded: past ``limit`` queued lines new ones are dropped and counted.
* ``SharedOnset`` / ``EarTap`` - Silero ran TWICE per packet (``NativeMediaSocket.onset`` and the shadow ear's own detector, both fed the same
  PCM on the loop thread). ``SharedOnset`` wraps the transport's detector and remembers the verdict of the last packet; ``EarTap`` is the ear's
  detector and returns that verdict for the SAME packet, feeding its own fallback detector only for a packet the transport did not hear.
* ``WakeTicker`` - the 100 ms ``asyncio.sleep`` of ``tick()`` as an event: ``wake()`` (thread-safe via ``loop.call_soon_threadsafe``) runs the
  tick now, ``max_wait`` stays the ceiling for timers that have no event (the controller's deadlines).
"""
import asyncio
import queue
import threading
import time

from .timer_policy import CLOSE_WAIT_S, LAG_PERIOD_S, WAKE_TICK_S


class LagMeter:
    """``await meter.run()`` as a task. ``samples``: lateness in ms of each wake-up (bounded)."""

    def __init__(self, period=LAG_PERIOD_S, *, clock=time.perf_counter, keep=20000):
        self.period, self.clock, self.keep, self.samples, self.stopped = period, clock, keep, [], False

    async def run(self):
        while not self.stopped:
            began = self.clock()
            await asyncio.sleep(self.period)
            self.samples.append(max(0.0, (self.clock() - began - self.period) * 1000))
            if len(self.samples) > self.keep:
                del self.samples[:len(self.samples) - self.keep]

    def stop(self):
        self.stopped = True

    def percentile(self, q):
        data = sorted(self.samples)
        return data[min(len(data) - 1, int(len(data) * q))] if data else 0.0

    def summary(self):
        return {'n': len(self.samples), 'p50_ms': round(self.percentile(.5), 1), 'p99_ms': round(self.percentile(.99), 1),
                'max_ms': round(max(self.samples, default=0.0), 1)}


class SerialWorker:
    """One worker thread; ``run`` returns a future-like awaitable. A raised error comes back to the awaiting caller."""

    def __init__(self, name='echo-serial'):
        self.jobs = queue.Queue()
        self.closed = False
        self.thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            loop, future, fn, args = job
            try:
                result = fn(*args)
            except BaseException as error:               # noqa: BLE001 - handed to the awaiting caller
                loop.call_soon_threadsafe(_settle, future, None, error)
            else:
                loop.call_soon_threadsafe(_settle, future, result, None)

    def run(self, fn, *args):
        if self.closed:
            raise RuntimeError('worker closed')
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.jobs.put((loop, future, fn, args))
        return future

    def close(self):
        if not self.closed:
            self.closed = True
            self.jobs.put(None)


def _settle(future, result, error):
    if future.cancelled():
        return
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(result)


class ThreadedFile:
    """Wraps an open text file: ``write`` queues, a thread writes. ``dropped``: lines refused because the queue was full."""

    def __init__(self, file, *, limit=5000):
        self.file, self.limit, self.dropped, self.error = file, limit, 0, None
        self.lines = queue.Queue()
        self.thread = threading.Thread(target=self._loop, name='echo-journal', daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            line = self.lines.get()
            if line is None:
                return
            try:
                self.file.write(line)
            except Exception as error:                  # noqa: BLE001 - kept; the journal never breaks the call
                self.error = error

    def write(self, line):
        if self.lines.qsize() >= self.limit:
            self.dropped += 1
            return 0
        self.lines.put(line)
        return len(line)

    def flush(self):
        pass

    def close(self):
        self.lines.put(None)
        self.thread.join(CLOSE_WAIT_S)
        try:
            self.file.close()
        except Exception:                               # noqa: BLE001
            pass


class SharedOnset:
    """The transport's detector, remembering its verdict for the packet it just heard (``last_pcm`` is that very object)."""

    def __init__(self, detector):
        self.detector, self.last_pcm, self.last_verdict = detector, None, None

    def feed(self, pcm):
        verdict = self.detector.feed(pcm)
        self.last_pcm, self.last_verdict = pcm, verdict
        return verdict

    def __getattr__(self, name):
        return getattr(self.detector, name)


class EarTap:
    """The ear's detector built on ``SharedOnset``: the same packet is not analysed twice. ``fallback`` (a detector or None) feeds packets the
    transport did not hear (its ear is off or was dropped); without one such a packet is no verdict. Attributes (speaking, quiet_ms,
    preroll_packets, level, floor, engine) come from the shared detector."""

    def __init__(self, shared, fallback=None):
        self.shared, self.fallback, self.reused, self.own = shared, fallback, 0, 0

    def feed(self, pcm):
        if self.shared.last_pcm is pcm:
            self.reused += 1
            return self.shared.last_verdict
        self.own += 1
        return self.fallback.feed(pcm) if self.fallback is not None else None

    def __getattr__(self, name):
        return getattr(self.shared, name)


class WakeTicker:
    """``await ticker.wait()`` returns when ``wake()`` was called (from any thread) or after ``max_wait`` seconds, whichever is first."""

    def __init__(self, max_wait=WAKE_TICK_S):
        self.max_wait, self.loop, self.event, self.wakes, self.timeouts = max_wait, None, None, 0, 0

    def bind(self):
        self.loop, self.event = asyncio.get_running_loop(), asyncio.Event()

    def wake(self):
        if self.loop is None:
            return
        try:
            self.loop.call_soon_threadsafe(self.event.set)
        except RuntimeError:
            pass

    async def wait(self):
        try:
            await asyncio.wait_for(self.event.wait(), self.max_wait)
            self.wakes += 1
        except asyncio.TimeoutError:
            self.timeouts += 1
        self.event.clear()
