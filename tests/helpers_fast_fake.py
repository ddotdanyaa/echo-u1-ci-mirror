"""A scripted first road for the channel tests: ``Fake`` (what ``FastText`` is given as a stream; every ask is a ``Run`` the test feeds by ``script``), the clock the test drives and
the channel over them (``FastText`` wraps it in ``reserve_text.Roads``, the one owner of the roads)."""
import queue
import threading
import time

from echo_sync import fast_text as FT


class Run:
    def __init__(self, request, cancelled):
        self.request, self.cancelled, self.script, self.ended = request, cancelled, queue.Queue(), threading.Event()

    def generate(self):
        try:
            while True:
                try:
                    kind, value = self.script.get(timeout=0.01)
                except queue.Empty:
                    if self.cancelled.is_set():
                        return
                    continue
                if kind == 'delta':
                    yield value
                elif kind == 'end':
                    return
                else:
                    raise RuntimeError(value)
        finally:
            self.ended.set()


class Fake:
    def __init__(self):
        self.runs = []

    def __call__(self, request, cancelled):
        self.runs.append(Run(request, cancelled))
        return self.runs[-1].generate()


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


def channel():
    fake, clock = Fake(), Clock()
    fast = FT.FastText(fake, instructions=lambda: 'POLICY', history=lambda: [], clock=clock, wake=lambda: None)      # the roads own the fake: it is the first road alone
    return fast, fake, clock


def open_question(fast, text='Что такое инерция?'):
    return fast.release(qid='q1', turn='t1', epoch=1, question=text)


class SecondAsk:
    """The reserve of a rig whose scripted stream is asked again after a failure: the road after the first road is the SAME scripted stream, but it is asked only when the request before it has ENDED (a failure: the old tests'
    second chance of a job, H5 item 7); while that request hangs the road waits and makes no request, so a hung job costs one request as it did. A harness of the roads, no rule of the product."""
    roads = [('FAKE_KEY', 'http://fake', 'fake-model')]
    spent = {}

    def __init__(self, stream):
        self.stream = stream

    def __bool__(self):
        return True

    def _order(self, request):
        return self.roads

    def holds(self, road, request):
        return True

    def one(self, name, base, model, request, cancelled, screen=False):
        runs = getattr(self.stream, 'runs', None)
        before = runs[-1] if runs else None
        while not cancelled.is_set() and before is not None and not before.ended.is_set():
            time.sleep(0.003)
        if cancelled.is_set():
            return iter(())
        return self.stream(request, cancelled)


def two_asks(stream, clock=None):
    """``stream`` as the first road and again as the road after it (``SecondAsk``)."""
    from echo_sync.reserve_text import Roads
    return Roads(stream, SecondAsk(stream), clock=clock)
