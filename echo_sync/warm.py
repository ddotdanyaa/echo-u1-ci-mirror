"""w9-warm (N107, N108, N109): what the first call loads, loaded when the server starts and kept warm. Pure module, nothing imports it yet (patches in
cloud_context/reports/w9-warm.md). The inventory of what a first call pays for is in that report.

* ``Step`` / ``run_plan`` - an ordered plan; every step runs in turn on ONE background thread, a failing step is recorded and the rest still run,
  nothing here raises. ``run_plan`` returns ``[{'name', 'ok', 'ms', 'reason'}]`` (reason = the error TYPE, never its text).
* ``ModelPool`` - ``take()`` hands out a ready, stateful model (the Silero VAD one call uses) and refills in the background; empty, it builds one
  on the spot like before. N108: the first call finds one waiting.
* ``MaterialCache`` - ``load_call_context(home)`` keyed by the (size, mtime_ns) of the two files it reads: the result is reused while they are
  unchanged and read again the moment they change (a new lecture is still used by the next call).
* ``IdleGuard`` - N109: ``touch(name)`` on use; ``check(now)`` pings every resource idle longer than its ``idle_s`` (a cheap call that keeps the OS
  from paging it out and notices a dead one); ``run`` loops it. A ping that raises is recorded as ``failed`` and the resource's ``revive`` runs.
"""
import asyncio
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger('echo-sync')


class Step:
    """``lane``: steps of one lane run in turn (the question path needs the tables before the classifier); lanes run beside each other (g9-boot).
    U31/U127 (a part of the call that may be dead at its start is a step with its own verdict): ``alive`` says after the step whether what it warmed lives (a step that ran and left a dead part is not ok), ``fallback``
    is what is done when it does not (a second source, a later retry), ``phrase_key`` is the key of ``diagnostics.PHRASES`` the call says when the part is dead in the end (never silence)."""
    def __init__(self, name, fn, *, budget_s=10.0, lane=None, alive=None, fallback=None, phrase_key=None):
        self.name, self.fn, self.budget_s, self.lane = name, fn, budget_s, lane or name
        self.alive, self.fallback, self.phrase_key = alive, fallback, phrase_key


def run_plan(steps, *, clock=time.perf_counter, report=None):
    """Lanes in parallel, each lane in order; the result keeps the plan's order. One lane's slow step (the ear's 30 s) holds no other."""
    lanes, results, lock = {}, {}, threading.Lock()
    for index, step in enumerate(steps):
        lanes.setdefault(step.lane, []).append((index, step))

    def lane(items):
        for index, step in items:
            record = _run_step(step, clock, report)
            with lock:
                results[index] = record

    if len(lanes) <= 1:
        for items in lanes.values():
            lane(items)
    else:
        threads = [threading.Thread(target=lane, args=(items,), name='echo-warm-' + str(name), daemon=True) for name, items in lanes.items()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    return [results[i] for i in sorted(results)]


def _run_step(step, clock, report):
    began, ok, reason = clock(), True, None
    try:
        step.fn()
    except Exception as error:                           # noqa: BLE001 - one cold part must not stop the others, or the server
        ok, reason = False, type(error).__name__
    extra = {}
    if step.alive is not None or step.fallback is not None or step.phrase_key is not None:
        alive = ok and _lives(step.alive)
        if not alive and step.fallback is not None:
            try:
                step.fallback()
                extra['fallback'] = 'ok'
                alive = _lives(step.alive)
            except Exception as error:                   # noqa: BLE001 - the fallback may fail too: the part is dead, the phrase says so
                extra['fallback'] = type(error).__name__
        if not alive and ok:
            ok, reason = False, 'dead'
        extra['alive'] = alive
        if not alive and step.phrase_key is not None:
            extra['phrase_key'] = step.phrase_key
    ms = round((clock() - began) * 1000)
    record = {'name': step.name, 'ok': ok, 'ms': ms, 'reason': reason, 'over_budget': ms > step.budget_s * 1000, **extra}
    if report:
        try:
            report(record)
        except Exception:                                # noqa: BLE001
            pass
    if not ok:
        logger.warning('echo-sync warm step=%s failed reason=%s', step.name, reason)
    return record


def _lives(check):
    """The verdict of a step's ``alive`` (None: nothing to ask, alive); a check that raises says dead."""
    if check is None:
        return True
    try:
        return bool(check())
    except Exception:                                    # noqa: BLE001
        return False


def start_plan(steps, *, report=None, on_done=None):
    """The plan on a daemon thread; returns the thread. The server does not wait for it."""
    def work():
        result = run_plan(steps, report=report)
        if on_done:
            on_done(result)
    thread = threading.Thread(target=work, name='echo-warm', daemon=True)
    thread.start()
    return thread


class ModelPool:
    def __init__(self, factory, *, size=1):
        self.factory, self.size, self.items, self.lock, self.building = factory, size, [], threading.Lock(), False
        self.failed = None

    def fill(self):
        """Build until the pool is full (call from the warm thread or from ``take``'s refill)."""
        while True:
            with self.lock:
                if len(self.items) >= self.size:
                    return
            try:
                item = self.factory()
            except Exception as error:                   # noqa: BLE001
                self.failed = type(error).__name__
                return
            with self.lock:
                self.items.append(item)
                self.failed = None                       # a build that worked: an old failure no longer speaks for the pool

    def take(self):
        """A ready model (reset), or one built now. Refills in the background."""
        with self.lock:
            item = self.items.pop() if self.items else None
        if item is None:
            item = self.factory()                        # built now; the refill starts only after, so one call never builds two
        with self.lock:
            refill = not self.building
            self.building = True
        if refill:
            def again():
                try:
                    self.fill()
                finally:
                    self.building = False
            threading.Thread(target=again, name='echo-pool', daemon=True).start()
        reset = getattr(item, 'reset', None)
        if callable(reset):
            reset()
        return item


class MaterialCache:
    def __init__(self, loader, names=('echo_settings.json', 'context.md')):
        self.loader, self.names, self.key, self.value, self.lock = loader, names, None, None, threading.Lock()
        self.hits = self.reads = 0

    def _key(self, home):
        out = []
        for name in self.names:
            try:
                stat = (Path(home) / 'materials' / name).stat()
                out.append((stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))     # ctime cannot be set back: a rewrite with the same size and a restored mtime is still seen
            except OSError:
                out.append(None)
        return (str(home), tuple(out))

    def load(self, home):
        key = self._key(home)
        with self.lock:
            if key == self.key:
                self.hits += 1
                return self.value
        value = self.loader(home)
        with self.lock:
            self.key, self.value = key, value
            self.reads += 1
        return value


class IdleGuard:
    def __init__(self, *, clock=time.monotonic):
        self.clock, self.items, self.log = clock, {}, []

    def add(self, name, ping, *, idle_s, revive=None):
        self.items[name] = {'ping': ping, 'idle_s': idle_s, 'revive': revive, 'last': self.clock()}

    def touch(self, name):
        if name in self.items:
            self.items[name]['last'] = self.clock()

    def check(self, now=None):
        now = self.clock() if now is None else now
        for name, item in self.items.items():
            if now - item['last'] < item['idle_s']:
                continue
            try:
                item['ping']()
                self.log.append((name, 'ok'))
            except Exception:                            # noqa: BLE001
                self.log.append((name, 'failed'))
                try:
                    if item['revive']:
                        item['revive']()
                except Exception:                        # noqa: BLE001
                    self.log.append((name, 'revive_failed'))
            item['last'] = now

    def start(self, period=5.0):
        """Own daemon thread (the host's loop is not needed). A ping runs on its own thread, so one that hangs holds no other resource; a resource
        whose ping is still running is not pinged again."""
        self._stop = threading.Event()
        self.running = set()

        def loop():
            while not self._stop.wait(period):
                now = self.clock()
                for name, item in list(self.items.items()):
                    if name in self.running or now - item['last'] < item['idle_s']:
                        continue
                    item['last'] = now
                    self.running.add(name)
                    threading.Thread(target=self._one, args=(name, item), name='echo-ping-' + name, daemon=True).start()
        thread = threading.Thread(target=loop, name='echo-idle-guard', daemon=True)
        thread.start()
        return thread

    def _one(self, name, item):
        try:
            try:
                item['ping']()
                self.log.append((name, 'ok'))
            except Exception:                            # noqa: BLE001
                self.log.append((name, 'failed'))
                try:
                    if item['revive']:
                        item['revive']()
                except Exception:                        # noqa: BLE001
                    self.log.append((name, 'revive_failed'))
        finally:
            self.running.discard(name)
        del self.log[:-200]                              # a server that lives for weeks does not grow a list

    def stop(self):
        stop = getattr(self, '_stop', None)
        if stop is not None:
            stop.set()

    async def run(self, period=5.0):
        while True:
            await asyncio.sleep(period)
            await asyncio.to_thread(self.check)


def default_steps(home, *, settings=None, material_cache=None, vad_pool=None, voice=None, ear=None, roads=None):
    """The real steps, in the order of what the first call needs first (the question path before the voice before the ear). Imports are inside the
    steps, so building the plan costs nothing. ``voice``: the profile's SAPI manager (``keep_resident``); ``ear``: ``ear_shadow.shared_worker``-like; ``roads``: a callable giving the call's ``reserve_text.Roads`` (the model source is a row of it): the step 'model_road' is
    ok while some road does not rest, else the call says the phrase 'channel' (U31: a cold start with no way to a model is told, not found out by the first question)."""
    def kb():
        from .reference_kb import preload                # noqa: PLC0415
        if not preload():
            raise RuntimeError('tables')

    def classifier():
        from .classifier import analyze                  # noqa: PLC0415 - pymorphy3 and the stems are built by the first sentence
        analyze('Какой срок исковой давности по статье 196?', [], [])

    def material():
        if material_cache is not None:
            material_cache.load(home)

    def bank():
        from .instant import for_home                    # noqa: PLC0415 - the call takes the index built here, its own build costs seconds
        for_home(settings, home)

    def voice_step():
        if voice is not None:
            voice.keep_resident()

    def ear_step():
        if ear is not None and not ear().wait_ready(30):
            raise RuntimeError('ear')

    def vad():
        if vad_pool is not None:
            vad_pool.fill()
            if vad_pool.failed:
                raise RuntimeError(vad_pool.failed)

    def model_road():
        if roads is not None and not roads().alive():
            raise RuntimeError('no_road')

    # g9-boot: four lanes beside each other. The question path (tables, then the classifier that uses them, then the material) is one lane; the voice,
    # the VAD and the ear's 30 s model each have their own, so none waits for another (before, the VAD stood behind the voice and the tables).
    return [Step('reference_kb', kb, budget_s=1, lane='question'), Step('classifier', classifier, budget_s=1, lane='question'),
            Step('material', material, budget_s=1, lane='question'), Step('instant', bank, budget_s=20, lane='question'),
            Step('voice', voice_step, budget_s=2), Step('vad', vad, budget_s=1),
            Step('ear_model', ear_step, budget_s=30)] + ([Step('model_road', model_road, budget_s=2, alive=lambda: roads().alive(), phrase_key='channel')] if roads is not None else [])


# --- the process's singletons (the host uses these; nothing is built until a step or a call touches them) ------------------------------------
def _load_context(home):
    from .content_policy import load_call_context      # noqa: PLC0415
    return load_call_context(home)


def _silero():
    from .vad_silero import SherpaVad                  # noqa: PLC0415
    return SherpaVad()


material_cache = MaterialCache(_load_context)
vad_pool = ModelPool(_silero)


guard = IdleGuard()


def _roads():
    from .reserve_text import for_stream                # noqa: PLC0415 - the reserve of this process, read from the key file as a call reads it
    return for_stream(None)


def start_server_warm(home, *, settings=None, voice=None, ear=None, report=None, guard_period=5.0, voice_idle_s=60.0, ear_idle_s=120.0):
    """The plugin's one call at start (``plugin.register``), only with the profile's ``warm_start`` = "on". Returns the thread.
    g9-boot: the server lives for days, so after the plan the guard keeps the parts alive: an idle voice worker is re-armed (``keep_resident`` is
    idempotent and restarts a dead one), a dead ear is asked for again, the VAD pool is topped up. A second call, a call after a drop and the tenth
    find them warm; none of this touches a running call."""
    if settings is not None and settings.get('warm_start') != 'on':
        return None
    thread = start_plan(default_steps(home, settings=settings, material_cache=material_cache, vad_pool=vad_pool, voice=voice, ear=ear, roads=_roads), report=report)
    guard.stop()
    guard.items.clear()
    if voice is not None:
        guard.add('voice', voice.keep_resident, idle_s=voice_idle_s)
    if ear is not None:
        guard.add('ear', lambda: ear().wait_ready(5) or (_ for _ in ()).throw(RuntimeError('ear')), idle_s=ear_idle_s)
    guard.add('vad', vad_pool.fill, idle_s=voice_idle_s)
    guard.start(period=guard_period)
    return thread
