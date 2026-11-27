"""W-vgs: Verifier-Guided Search. The universal core: k independent generations asked at once, every answer goes through
an error-free verifier (a plugin: the domain lives there, the core knows nothing of code), the valid ones are grouped by
the fingerprint of their result (votes). Imports nothing of the factory."""
from __future__ import annotations

import hashlib
import ast
import queue
import random
import threading
import time
from dataclasses import dataclass, field

TEMPERATURES = (0.2, 0.5, 0.8, 0.35, 0.65, 1.0)
FIRST_GOOD_S = 60.0       # the run ends this long after the first valid candidate
TOTAL_S = 120.0           # ... or this long in all
RETRY_PAUSES_S = (0.0, 0.0, 0.5, 1.0)     # fac-68b: a 503 is a refusal of one request, the repeat passes at once (27.11 direct measure); 1 s from the 4th
RETRY_JITTER = 0.3                         # +-30 %
OTHER_REFUSALS_MAX = 3                     # refusals of no known kind a branch survives before it gives up
LOCAL_WAIT_MAX_S = 60.0                    # W-prio3: a branch waits its own channel's minute window at most this long
NO_ATTEMPT_PAUSE_S = 2.0                   # W-prio3: pause after a yield / sem refusal (not an attempt)
REFUSAL_NAMES = {'overload': 'overload_503', 'minute_local': 'minute_local', 'minute': 'minute_429', 'day': 'day',
                 'yield': 'yield', 'sem': 'sem', 'timeout': 'timeout'}
REFUSAL_KINDS = ('overload_503', 'minute_local', 'minute_429', 'day', 'yield', 'sem', 'timeout', 'other')


class ChannelRefused(Exception):
    """A 503 / 429 / timeout of a channel: not an answer. The branch is asked again within the term. ``kind``:
    'overload' (503: the next channel of the circle after a pause), 'minute' (429 of the minute: the channel waits
    ``wait_s``, another one at once), 'day' (429 of the day: the channel is out), anything else: an unknown refusal.
    W-prio3: 'minute_local' (our own TPM/RPM booking gave no place: the branch waits ITS channel for ``wait_s``, the end of the
    window, and asks it again), 'yield' / 'sem' (the slicing gives way / waits for a place: no attempt, a short pause), 'timeout'."""

    def __init__(self, message: str = '', kind: str = 'other', wait_s: float = 0.0):
        super().__init__(message)
        self.kind, self.wait_s = kind, float(wait_s or 0)


@dataclass
class Candidate:
    key: str
    payload: object
    votes: int = 1
    callers: list = field(default_factory=list)     # the call numbers that gave this key
    order: int = 0                                  # arrival number of the first one


def fingerprint(text: str, name: str = '') -> str:
    """The fingerprint of a result: a .py file -> sha1 of its ast.dump (formatting and comments do not matter), a text that
    does not parse or another file -> sha1 of the text without trailing spaces."""
    if name.endswith('.py'):
        try:
            return hashlib.sha1(ast.dump(ast.parse(text)).encode('utf-8', 'replace')).hexdigest()
        except (SyntaxError, ValueError):
            pass
    body = '\n'.join(line.rstrip() for line in text.replace('\r\n', '\n').split('\n')).rstrip()
    return hashlib.sha1(body.encode('utf-8', 'replace')).hexdigest()


class Ensemble:
    """``ask(n, temperature, channel)`` -> an answer (or raises ChannelRefused); ``verify(answer)`` -> ``(ok, why, key)``.
    ``channels``: the channel names (None = one unnamed channel), call n starts on channels[n % len]. A refused branch
    is asked AGAIN (W-vgs2) until the common term ends: 503 -> the next channel of the circle after 2, 4, 8, 12, 12 s
    (+-30 %); 429 of the minute -> that channel rests ``wait_s``, another one at once; 429 of the day -> the channel is out.
    ``sleep(seconds)`` / ``rng`` are for tests. ``run()`` -> the valid candidates, votes descending, then the earlier
    arrival first.
    W-a2: ``capacity()`` -> the free places of the small channels in the head (factory_head.capacity), None / an
    exception = the head does not answer. With a live head the head is the ONE owner of retries, channel hops and window
    waits: a branch is one ticket (``ask(n, temperature, None)``: the head picks the channel), a refusal ends the branch
    with no pause of its own, and the branches open at once are the head's free places (plus the ones already open),
    never more than k. Without an answering head the old path above (the branch's own circle and pauses) stays."""

    def __init__(self, k, ask, verify, channels=None, temperatures=TEMPERATURES, first_good_s=FIRST_GOOD_S,
                 total_s=TOTAL_S, clock=time.monotonic, sleep=None, rng=None, capacity=None):
        self.k, self.ask, self.verify = max(1, int(k)), ask, verify
        self.channels = list(channels) if channels else [None]
        self.temperatures = tuple(temperatures)
        self.first_good_s, self.total_s, self.clock = first_good_s, total_s, clock
        self.sleep, self.rng, self.capacity = sleep, rng or random.Random(), capacity
        self.stats = dict(k=self.k, asked=0, answered=0, valid=0, unique=0, votes_top=0, refused=0, retries_503=0,
                          open_max=0, head=0)
        self.refused_by = {name: 0 for name in REFUSAL_KINDS}      # W-prio3: every refusal of a branch by its kind
        self.rejected: list = []        # (why) of the answers the verifier threw out
        self.early = False

    def _free(self):
        """The head's free places now, or None when there is no head or it does not answer."""
        if self.capacity is None:
            return None
        try:
            free = self.capacity()
        except Exception:       # noqa: BLE001 - a head that does not answer is the old path
            return None
        return None if free is None else max(0, int(free))

    def run(self) -> list:
        events: queue.Queue = queue.Queue()
        stop = threading.Event()
        start = self.clock()
        lock = threading.Lock()
        blocked: dict = {}      # channel -> the time its minute window frees
        dead: set = set()       # channels out for the day

        def pause(seconds: float) -> None:
            seconds = max(0.0, min(seconds, start + self.total_s - self.clock()))
            if self.sleep is not None:
                self.sleep(seconds)
            else:
                stop.wait(seconds)

        def worker(n: int) -> None:
            temperature = self.temperatures[n % len(self.temperatures)]
            hop, overloads, others = 0, 0, 0
            while not stop.is_set() and self.clock() - start < self.total_s:
                with lock:
                    alive = [c for c in self.channels if c not in dead]
                    now = self.clock()
                    if alive:
                        shift = (n + hop) % len(alive)
                        ring = alive[shift:] + alive[:shift]
                        free = [c for c in ring if blocked.get(c, 0) <= now]
                        soonest = min(blocked.get(c, 0) for c in alive)
                if not alive:
                    break
                if not free:                    # every live channel waits for its minute window
                    pause(max(0.05, soonest - now))
                    continue
                channel = free[0]
                with lock:
                    self.stats['asked'] += 1
                try:
                    answer = self.ask(n, temperature, channel)
                except ChannelRefused as refused:
                    with lock:
                        self.stats['refused'] += 1
                        self.refused_by[REFUSAL_NAMES.get(refused.kind, 'other')] += 1
                        if refused.kind in ('yield', 'sem', 'minute_local'):
                            self.stats['asked'] -= 1            # W-prio3: no request went out: not an attempt
                        if refused.kind in ('yield', 'sem', 'minute_local'):
                            pass
                        elif refused.kind == 'day':
                            dead.add(channel)
                        elif refused.kind == 'minute':
                            blocked[channel] = self.clock() + max(1.0, refused.wait_s)
                        elif refused.kind == 'overload':
                            self.stats['retries_503'] += 1
                        else:
                            others += 1
                    if refused.kind == 'minute_local':
                        pause(min(LOCAL_WAIT_MAX_S, max(1.0, refused.wait_s)))    # its OWN channel, to the end of its window
                        continue
                    if refused.kind in ('yield', 'sem'):
                        pause(NO_ATTEMPT_PAUSE_S)
                        continue
                    hop += 1
                    if refused.kind == 'overload':
                        base = RETRY_PAUSES_S[min(overloads, len(RETRY_PAUSES_S) - 1)]
                        overloads += 1
                        pause(base * (1 + self.rng.uniform(-RETRY_JITTER, RETRY_JITTER)))
                    elif refused.kind not in ('day', 'minute') and others >= OTHER_REFUSALS_MAX:
                        break
                    continue
                except Exception as error:          # noqa: BLE001 - a broken call is no answer
                    with lock:
                        self.stats['refused'] += 1
                        self.rejected.append('ask failed: %s' % error)
                    hop += 1
                    others += 1
                    if others >= OTHER_REFUSALS_MAX:
                        break
                    continue
                checked(n, answer)
                return
            events.put((n, None, None, 'no channel answered', ''))

        def checked(n: int, answer) -> None:
            with lock:
                self.stats['answered'] += 1
            try:
                ok, why, key = self.verify(answer)
            except Exception as error:          # noqa: BLE001 - a verifier that fails rejects
                ok, why, key = False, 'verify failed: %s' % error, ''
            events.put((n, answer, ok, why, key))

        def head_branch(n: int) -> None:
            """W-a2: one ticket of the head; the head hops, retries and waits the windows. A refusal ends the branch."""
            with lock:
                self.stats['asked'] += 1
            try:
                try:
                    answer = self.ask(n, self.temperatures[n % len(self.temperatures)], None)
                finally:
                    with lock:
                        asking[0] -= 1          # its ticket left the head: the place is free again
            except ChannelRefused as refused:
                with lock:
                    self.stats['refused'] += 1
                    self.refused_by[REFUSAL_NAMES.get(refused.kind, 'other')] += 1
                    if refused.kind in ('yield', 'sem', 'minute_local'):
                        self.stats['asked'] -= 1            # no request went out: not an attempt
                events.put((n, None, None, 'head refused: %s' % refused.kind, ''))
                return
            except Exception as error:          # noqa: BLE001 - a broken call is no answer
                with lock:
                    self.stats['refused'] += 1
                    self.rejected.append('ask failed: %s' % error)
                events.put((n, None, None, 'ask failed', ''))
                return
            checked(n, answer)

        launched, limit, next_poll, poll_now = 0, self.k, 0.0, True
        asking = [0]        # head branches whose ticket is in the head now

        def launch_more(done: int) -> None:
            """Open branches up to the limit: k without a head, else the head's free places plus our tickets in it now."""
            nonlocal launched, limit, next_poll, poll_now
            if launched >= self.k:
                return
            if self.capacity is not None and (poll_now or time.monotonic() >= next_poll):
                free = self._free()
                next_poll, poll_now = time.monotonic() + 1.0, False
                with lock:
                    limit = self.k if free is None else min(self.k, max(1, asking[0] + free))
                self.stats['head'] = int(free is not None)
            head = bool(self.stats['head'])
            while launched < self.k:
                with lock:
                    if (asking[0] if head else launched - done) >= limit:
                        break
                    if head:
                        asking[0] += 1
                    self.stats['open_max'] = max(self.stats['open_max'], asking[0] if head else launched - done + 1)
                threading.Thread(target=head_branch if head else worker, args=(launched,), daemon=True).start()
                launched += 1

        groups: dict = {}
        arrived, done, first_good = 0, 0, None
        launch_more(0)
        while done < self.k:
            launch_more(done)
            now = self.clock()
            limit = self.total_s if first_good is None else min(self.total_s, (first_good - start) + self.first_good_s)
            wait = start + limit - now
            if wait <= 0:
                break
            try:
                n, answer, ok, why, key = events.get(timeout=min(wait, 0.05))
            except queue.Empty:
                continue
            done += 1
            poll_now = True         # a place came free: ask the head again
            if ok is None:
                continue
            if not ok:
                self.rejected.append(why)
                continue
            self.stats['valid'] += 1
            arrived += 1
            if first_good is None:
                first_good = self.clock()
            found = groups.get(key)
            if found is None:
                groups[key] = Candidate(key, answer, 1, [n], arrived)
            else:
                found.votes += 1
                found.callers.append(n)
                if len(set(found.callers)) >= 2:       # two equal results from different calls: the rest is not awaited
                    self.early = True
                    break
        stop.set()
        result = sorted(groups.values(), key=lambda c: (-c.votes, c.order))
        self.stats['unique'] = len(result)
        self.stats['votes_top'] = result[0].votes if result else 0
        return result
