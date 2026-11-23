"""W-vgs: Verifier-Guided Search. The universal core: k independent generations asked at once, every answer goes through
an error-free verifier (a plugin: the domain lives there, the core knows nothing of code), the valid ones are grouped by
the fingerprint of their result (votes). Imports nothing of the factory."""
from __future__ import annotations

import hashlib
import ast
import queue
import threading
import time
from dataclasses import dataclass, field

TEMPERATURES = (0.2, 0.5, 0.8, 0.35, 0.65, 1.0)
FIRST_GOOD_S = 60.0       # the run ends this long after the first valid candidate
TOTAL_S = 120.0           # ... or this long in all


class ChannelRefused(Exception):
    """A 503 / 429 / timeout of a channel: not an answer. The place is filled by another channel within the term."""


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
    ``channels``: the channel names (None = one unnamed channel), call n starts on channels[n % len] and, refused, goes to
    the next one. ``run()`` -> the valid candidates, votes descending, then the earlier arrival first."""

    def __init__(self, k, ask, verify, channels=None, temperatures=TEMPERATURES, first_good_s=FIRST_GOOD_S,
                 total_s=TOTAL_S, clock=time.monotonic):
        self.k, self.ask, self.verify = max(1, int(k)), ask, verify
        self.channels = list(channels) if channels else [None]
        self.temperatures = tuple(temperatures)
        self.first_good_s, self.total_s, self.clock = first_good_s, total_s, clock
        self.stats = dict(k=self.k, asked=0, answered=0, valid=0, unique=0, votes_top=0, refused=0)
        self.rejected: list = []        # (why) of the answers the verifier threw out
        self.early = False

    def run(self) -> list:
        events: queue.Queue = queue.Queue()
        stop = threading.Event()
        start = self.clock()
        lock = threading.Lock()

        def worker(n: int) -> None:
            temperature = self.temperatures[n % len(self.temperatures)]
            for hop in range(len(self.channels)):
                if stop.is_set() or self.clock() - start >= self.total_s:
                    break
                channel = self.channels[(n + hop) % len(self.channels)]
                with lock:
                    self.stats['asked'] += 1
                try:
                    answer = self.ask(n, temperature, channel)
                except ChannelRefused:
                    with lock:
                        self.stats['refused'] += 1
                    continue
                except Exception as error:          # noqa: BLE001 - a broken call is no answer
                    with lock:
                        self.stats['refused'] += 1
                    self.rejected.append('ask failed: %s' % error)
                    continue
                with lock:
                    self.stats['answered'] += 1
                try:
                    ok, why, key = self.verify(answer)
                except Exception as error:          # noqa: BLE001 - a verifier that fails rejects
                    ok, why, key = False, 'verify failed: %s' % error, ''
                events.put((n, answer, ok, why, key))
                return
            events.put((n, None, None, 'no channel answered', ''))

        threads = [threading.Thread(target=worker, args=(n,), daemon=True) for n in range(self.k)]
        for t in threads:
            t.start()
        groups: dict = {}
        arrived, done, first_good = 0, 0, None
        while done < self.k:
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
