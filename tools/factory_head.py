"""fac-40 / W-bucket: the ONE place that decides "send / wait / refuse" for every channel it serves (every Google tier).
The loop starts it (local only, random port and token in head.json; a pulse file proves it lives); a runner or the loop
sends {role, tokens, body, channels in order, deadline} and gets the answer or what holds it. Keys stay in the host.

The rules (W-bucket, 27.11):
  1. A bucket is one channel (key + model): no merging of keys into one project.
  2. Books by the fact: a 200 charges usage.prompt_tokens; a 503 / 5xx / exception / timeout keeps the full estimate and
     the request (Google counts them too). The estimate is learned per role (the fact over the caller's tokens).
  3. Even pace with no bunches: a token bucket per channel (capacity tpm_eff, refilled continuously, tpm_eff 0.9 x tpm,
     x0.9 on a per-minute 429 down to 0.6 x tpm, x1.03 per 10 clean minutes up to 0.95 x tpm), plus the 60 s window of
     what was sent, a minimum gap of 60 / (0.8 x rpm) between two sends and the day count against rpd.
  4. 503 of a model: an exponential pause min(60, 2 * 2^(n-1)) * U(0.5, 1.5) s; all its channels wait; then ONE probe;
     the ticket moves at once to another channel that can go (another model or key, then the next tier).
  5. 429 by quotaId: PerMinute (or none) empties the bucket and closes the channel for retryDelay or 60 s + U(0, 5) s;
     PerDay closes it until the provider's day reset and notes the ledger's day gate.
  6. A ticket waits in the head until its deadline (DEADLINE_S of waiting + the call time on top) and is never sent with
     less than its call time left: then it is given back at once with the head's ETA.
  7. Places (free / grant / capacity) are counted in tokens: per channel floor(tokens free within PLACE_S / estimate),
     minus the tokens already queued. Queue order: review, repair, edit / code, the rest.
The old cooling marks of the shared ledger (model / channel / group cool, breaker, day probe) are not read here: the
head's own buckets and pauses decide. Bookings of the other processes (day count, the minute window) are still counted."""
import collections
import copy
import itertools
import json
import logging
import os
import random
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import factory_channels as C
from . import factory_quota as Q

PRIORITY = {'review': 0, 'repair': 1, 'edit': 2, 'code': 2}        # architect / slice / keywords / the rest: 3
OVERLOAD = (500, 502, 503, 504)
STATE_NAME, PULSE_NAME, BOOKS_NAME = 'head.json', 'head.pulse', 'head_books.json'    # beside channels.json
SERVED = ('google',)     # the providers whose channels the head serves, every tier
DEADLINE_S = 240         # the longest a ticket waits UNSENT (5-minute rule); its call time comes on top (ticket_deadline)
FILL, FLOOR, CEIL = 0.9, 0.6, 0.95       # tpm_eff: start / lowest after per-minute 429s / highest after clean minutes (x tpm)
LEARN_DOWN, LEARN_UP, CLEAN_S = 0.9, 1.03, 600.0
RPM_FILL = 0.8           # the minimum gap between two sends to one channel is 60 / (0.8 x rpm)
BACKOFF_BASE_S, BACKOFF_MAX_S = 2.0, 60.0
MINUTE_CLOSE_S, MINUTE_JITTER_S = 60.0, 5.0
PROBE_ETA_S = 5.0        # the half-open probe of a model is out: the ETA its tickets are told
PLACE_S = 30.0           # free / grant: the tokens a channel frees within this many seconds
PLACE_TOKENS = 3000      # free / grant without a size: one Gemma edit (26.11 telemetry: median 2.4K, mean 3.0K)
RATIO_MIN, RATIO_MAX, RATIO_STEP = 0.25, 2.0, 0.3     # the learned fact / caller-estimate ratio per role
CREDIT_TTL_S = 20.0      # places granted to a card are kept for it this long (the card's tickets use them up)
ANSWER_WAIT_S = 15.0     # the head accepts a ticket within this (else HeadDown; alive -> the card waits, dead -> old path)
PULSE_S, PULSE_FRESH_S = 5.0, 20.0       # the head touches its pulse file this often; older than 20 s = dead
IO_GAP_S, OTHERS_GAP_S = 1.0, 3.0        # the head's file IO (outside its lock) at most this often
SPILL_S = 20.0           # a tier whose next send is only a pacing wait this short keeps its tickets (no spill to the next tier)
PACING = ('tpm_bucket', 'tpm_window', 'rpm_gap', 'queue')
AGE_S = 60.0             # a waiting ticket climbs one priority level per AGE_S (architect / slice never starve)
ABANDON_S = 60.0         # a remote ticket nobody polled for this long is dropped unsent (its caller is gone)
KEEP_DONE_S = 120.0      # an answer nobody collected is forgotten after this
REFUSED_CLOSE_S = 3600.0     # 401 / 403 / 404 of a channel: it rests an hour, the ticket moves on
NET_CLOSE_S = 10.0       # no connection at all (not the provider's answer): the channel rests briefly, the model is not paused
NET_ERRORS = (b'URLError', b'ConnectionRefusedError', b'gaierror', b'ProxyError')
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
HOST = '.'.join(('127', '0', '0', '1'))     # this machine only
INF = float('inf')


class HeadDown(Exception):
    """The host does not answer. ``alive``: its pulse is fresh (the card waits); dead: the caller takes its old path."""

    def __init__(self, message='', alive=False):
        super().__init__(message)
        self.alive = alive


def serves(channel) -> bool:
    """A channel the head serves (every tier of the providers in SERVED)."""
    return str(channel.get('model') or '').split('/')[0] in SERVED


def _json(raw) -> dict:
    try:
        data = json.loads(raw.decode('utf-8'))
        if isinstance(data, list) and len(data) == 1:      # fac-farm 1: Gemini's OpenAI-compatible error is a one-element list
            data = data[0]
        return data if isinstance(data, dict) else {}
    except (ValueError, AttributeError, UnicodeDecodeError):
        return {}


def _quota_of(raw, now) -> tuple:
    """(is_day, quotaIds, retry hint, reset epoch or None) of a 429 body. A day refusal is a quotaId with PerDay (the word
    "daily" without a quotaId is a minute refusal unless the provider names a reset time)."""
    body = _json(raw)
    ids, retry = C._walk_details(body)
    reset = C._reset_at(body, now)
    low = (raw or b'').lower()
    day = any('perday' in q.lower() for q in ids) if ids else bool(reset) and (b'perday' in low or b'daily' in low or b'per_day' in low)
    return day, ids, retry, reset if day else None


def backoff_s(n, rng=random) -> float:
    """The pause of a model after its n-th 503 in a row: min(60, 2 * 2^(n-1)) * U(0.5, 1.5) seconds."""
    return min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (max(1, n) - 1)) * rng.uniform(0.5, 1.5)


class _Ticket:
    def __init__(self, seq, n, req, now, remote=False):
        self.seq, self.n, self.remote, self.polled, self.done_at = seq, n, remote, now, None
        self.probe = False
        self.role, self.tokens = str(req.get('role') or ''), max(1, int(req.get('tokens') or 1))
        self.prio = int(req['priority']) if req.get('priority') is not None else PRIORITY.get(self.role, 3)
        self.body, self.allowed = dict(req.get('body') or {}), list(req.get('channels') or [])
        self.born = now
        self.call_timeout = float(req.get('call_timeout_s') or 90)
        self.deadline = now + float(req.get('deadline_s') or ticket_deadline(self.call_timeout))
        self.last, self.hold, self.quota, self.est = (None, b''), None, '', self.tokens
        self.done, self.result = threading.Event(), None
        self.entry, self.backoff_n = None, 0


class Head:
    def __init__(self, channels, env, post=None, *, clock=time.time, folder=None, inline=False, urls=None, books=None,
                 log=None, rng=None):
        self.ch = {c['id']: c for c in C.validate(channels, warn=False)}
        self.keys, self.clock, self.folder, self.inline, self.post, self.urls = env, clock, folder, inline, post, urls
        self.books, self.log, self.rng = (Path(books) if books else None), log, rng or random.Random()
        self.section = 'head@%d' % os.getpid()
        self.q, self.flight, self.pending, self.tickets = {}, {}, [], {}
        self.hist = collections.deque()          # (time, channel, 'ok' | '503' | '429' | 'timeout' | 'other')
        self.lock, self.wake, self.stopping = threading.RLock(), threading.Event(), False
        self.seq = itertools.count(1)
        self.run = secrets.token_hex(4)          # a ticket id names this run: a restarted head never answers an old ticket
        self.io_lock = threading.Lock()          # one file writer at a time (pump and close)
        self.pump_thread = None
        self.credits = {}                        # card -> [expires, places granted and not yet used by a ticket]
        self.quota_log = collections.deque(maxlen=200)    # (time, channel, quotaId, 'day' | 'minute') of the 429 answers
        self.ratio = {}                          # role -> learned fact / caller tokens
        self.models = {}                         # model -> {'n': 503s in a row, 'until': paused until, 'probe': one out}
        now = self.clock()
        self.b = {cid: {'level': 0.0, 'at': now, 'eff': FILL * ch['tpm'], 'clean': now, 'last': -INF, 'closed': 0.0,
                        'why': '', 'day': 0.0, 'day_n': 0, 'day_start': C.quota_day(ch['model'], now)[0],
                        'win': collections.deque()} for cid, ch in self.ch.items()}
        self._odays, self._omin = {}, {}         # the other processes' bookings: group -> day count / [(t, tokens)] of the minute
        self._io, self._io_at, self._others_at, self._dirty = [], -INF, -INF, False
        self.pulse = None
        self._load()

    # -- the estimate --------------------------------------------------------------------------------------------------
    def _est(self, role, tokens) -> int:
        return max(1, int(round(max(1, int(tokens or 1)) * self.ratio.get(role, 1.0))))

    def _learn(self, t, used) -> None:
        if type(used) is int and used > 0:
            old = self.ratio.get(t.role, 1.0)
            new = (1 - RATIO_STEP) * old + RATIO_STEP * (used / t.tokens)
            self.ratio[t.role] = min(RATIO_MAX, max(RATIO_MIN, new))

    # -- the bucket of a channel ---------------------------------------------------------------------------------------
    def _bucket(self, cid, now) -> dict:
        b, ch = self.b[cid], self.ch[cid]
        if now > b['at']:
            b['level'] = min(b['eff'], b['level'] + (now - b['at']) * b['eff'] / 60.0)
            b['at'] = now
        if now - b['clean'] >= CLEAN_S:          # ten clean minutes WITH sends: the learned ceiling grows a little (idle: not)
            if b['last'] >= b['clean']:
                b['eff'] = min(CEIL * ch['tpm'], b['eff'] * LEARN_UP)
            b['clean'] = now
        while b['win'] and now - b['win'][0][0] >= 60:
            b['win'].popleft()
        start = C.quota_day(ch['model'], now)[0]
        if start > b['day_start']:
            b['day_start'], b['day_n'] = start, 0
        return b

    def _window(self, cid, now) -> list:
        """The (time, tokens) sent on this channel in the last 60 s: our own and the other processes' bookings."""
        own = [(e[0], e[1]) for e in self.b[cid]['win']]
        return own + [(t, n) for t, n in self._omin.get(self.ch[cid]['group'], ()) if 0 <= now - t < 60]

    def _gap(self, ch) -> float:
        return 60.0 / (RPM_FILL * ch['rpm']) if ch.get('rpm') else 0.0

    def _shut(self, cid, now) -> tuple:
        """(until, reason) of what keeps a channel shut regardless of its bucket (0 when nothing), INF when never today."""
        ch, b = self.ch[cid], self._bucket(cid, now)
        if not self.keys.get(ch['key_env']):
            return INF, 'no_key'
        if b['day'] > now:
            return b['day'], 'rate_day'
        if b['day_n'] + self._odays.get(ch['group'], 0) >= ch['rpd']:
            return C.quota_day(ch['model'], now)[1], 'rpd'
        m = self.models.get(ch['model'])
        holds = [(b['closed'], b['why'])] + ([(m['until'], 'backoff')] if m else [])
        holds = [h for h in holds if h[0] > now]
        if holds:
            return max(holds)
        if m and m['n'] and m['probe']:
            return now + PROBE_ETA_S, 'probe'
        return 0.0, ''

    def _eta(self, cid, est, now) -> tuple:
        """(seconds until this channel can take a call of ``est`` tokens, why): 0 = now."""
        until, why = self._shut(cid, now)
        if until > now:
            return until - now, why
        ch, b = self.ch[cid], self.b[cid]
        need = min(est, b['eff'])
        waits = [(b['last'] + self._gap(ch) - now, 'rpm_gap')]
        if b['level'] < need:
            waits.append(((need - b['level']) * 60.0 / b['eff'], 'tpm_bucket'))
        win = self._window(cid, now)
        over = sum(n for _, n in win) + need - b['eff']
        if over > 0:
            acc, wait = 0, 60.0
            for t, n in sorted(win):
                acc += n
                if acc >= over:
                    wait = t + 60 - now
                    break
            waits.append((wait, 'tpm_window'))
        wait, why = max(waits)
        return max(0.0, wait), why

    def _stock(self, cid, now) -> float:
        b = self.b[cid]
        return min(b['level'], b['eff'] - sum(n for _, n in self._window(cid, now)))

    def _surplus(self, cid, now) -> float:
        """fac-51: the requests per hour this channel must take to spend its day before the provider's reset (what is
        left of rpd today / hours to the reset): what it does not take now is lost at the reset."""
        ch, b = self.ch[cid], self.b[cid]
        left = ch['rpd'] - b['day_n'] - self._odays.get(ch['group'], 0)
        hours = max(1.0 / 60, (C.quota_day(ch['model'], now)[1] - now) / 3600.0)
        return max(0, left) / hours

    def _score(self, cid, est, now) -> tuple:
        """fac-51: the choice among the READY channels of one tier (each of them can take this call now): the one that
        loses the most of its day at the reset goes first (its day surplus per hour, one unit for every channel), then
        the bigger stock. The tier order is kept (Gemma with room stays first); the channels of a tier take calls side
        by side because the leader's rpm gap hands the next call to the next surplus. A channel with a small rpd (flash,
        20 a day) ranks low and is spent when the bigger days are busy: there is no pace gate (<id>)."""
        return self._surplus(cid, now), self._stock(cid, now)

    # -- tickets -------------------------------------------------------------------------------------------------------
    def submit(self, req, remote=False) -> str:
        with self.lock:
            n = next(self.seq)
            t = _Ticket('%s-%d' % (self.run, n), n, req, self.clock(), remote)
            t.est = self._est(t.role, t.tokens)
            card = req.get('card')
            if card in self.credits and t.role in ('edit', 'code'):     # only an ensemble call spends a place granted to its card
                self.credits[card][1] -= 1
                if self.credits[card][1] <= 0:
                    del self.credits[card]
            self.tickets[t.seq] = t
            self.pending.append(t)
        self.wake.set()
        return t.seq

    def result(self, ticket, wait=0.0):
        t = self.tickets.get(ticket)
        if t is None:      # another run's ticket (a restarted head) or one already collected: the caller's HeadDown
            return {'status': None, 'unknown': True, 'why': 'unknown ticket'}
        t.polled = self.clock()
        if wait > 0:
            t.done.wait(wait)
            t.polled = self.clock()
        if t.done.is_set():
            self.tickets.pop(ticket, None)
            return t.result
        return {'pending': True, 'held': t.hold}

    def cancel(self, ticket) -> bool:
        """The caller gave up: a ticket not sent yet is dropped (no quota is spent on an answer nobody reads)."""
        with self.lock:
            t = self.tickets.pop(ticket, None)
            if t is None or t.done.is_set():
                return False
            if t in self.pending:
                self._finish(t, None, b'', cancelled=True)
            return True

    def _finish(self, t, status, raw, ch=None, **extra):
        t.result = dict({'status': status, 'body': (raw or b'').decode('utf-8', 'replace'),
                         'channel': ch and ch['id'], 'model': ch and ch['model'],
                         'queued_s': round(getattr(t, 'queued_s', None) if ch is not None and hasattr(t, 'queued_s')
                                           else max(0.0, self.clock() - t.born), 1)}, **extra)
        self.pending = [x for x in self.pending if x is not t]
        if t.quota:
            t.result['quota'] = t.quota
        t.done_at = self.clock()
        t.done.set()

    def _tiers(self, t) -> list:
        """The ticket's channels the head serves, grouped by tier in the order the caller gave them."""
        out, at = [], {}
        for cid in t.allowed:
            ch = self.ch.get(cid)
            if ch is None:
                continue
            tier = C.tier_of(ch)
            if tier not in at:
                at[tier] = len(out)
                out.append([])
            out[at[tier]].append(cid)
        return out

    def step(self) -> int:
        """Dispatch what can go now, by priority then queue order; returns the number of calls started. Inline (tests):
        a ticket that came back from a refusal is sent again in the same step (up to 4 passes)."""
        started = 0
        for _ in range(4 if self.inline else 1):
            n = self._pass()
            started += n
            if not n:
                break
        return started

    def _pass(self) -> int:
        sends = []
        with self.lock:
            now = self.clock()
            # fac-51: channel -> [tokens, tickets] of the more urgent tickets that wait for it in this pass: a later ticket
            # sees that queue as its own wait, so a tier that gives it no place within SPILL_S spills to the next tier
            ahead = {}
            for cid in [k for k, t in self.tickets.items() if t.done_at is not None and now - t.done_at > KEEP_DONE_S]:
                del self.tickets[cid]                    # an answer nobody came for
            for t in sorted(self.pending, key=lambda x: (max(0, x.prio - int((now - x.born) // AGE_S)), x.n)):
                if t.remote and now - t.polled > ABANDON_S:      # its caller is gone: never sent for nobody
                    self.tickets.pop(t.seq, None)
                    self._finish(t, None, b'', abandoned=True)
                    continue
                if now >= t.deadline:
                    self._finish(t, *t.last, ch=None, expired=True, held=t.hold, eta_s=(t.hold or {}).get('wait_s'))
                    continue
                pick, best, own = None, (INF, None, 'no_channel'), INF
                for at, tier in enumerate(self._tiers(t)):
                    ready, near = [], (INF, None, 'no_channel')
                    for i, cid in enumerate(tier):
                        wait, why = self._eta(cid, t.est, now)
                        own = min(own, max(0.0, wait))
                        queue = ahead.get(cid)
                        if wait <= 0 and not queue:
                            score, stock = self._score(cid, t.est, now)
                            ready.append((-score, -stock, i, cid))
                            continue
                        if queue and (wait <= 0 or why in PACING):     # the tickets ahead pass first: their tokens and gaps
                            b = self.b[cid]                # the queue's tokens beyond the bucket's level, its gaps after ours
                            toks = max(0.0, queue[0] + min(t.est, b['eff']) - b['level']) * 60.0 / b['eff']
                            gaps = max(0.0, b['last'] + self._gap(self.ch[cid]) - now) + queue[1] * self._gap(self.ch[cid])
                            wait = max(wait, toks, gaps, 0.5)
                            why = 'queue'
                        if wait < near[0]:
                            near = (wait, cid, why)
                    if ready:
                        pick = min(ready)[-1]
                        break
                    if near[0] < best[0]:
                        best = near
                    if near[0] + (now - t.born if at == 0 else 0.0) <= SPILL_S and near[2] in PACING:
                        break        # only the even pace holds this tier a moment: wait for it, never spill to the next tier
                    # fac-51: on the FIRST tier the moment counts from the ticket's birth (a review the small tier cannot
                    # place within SPILL_S of its arrival leaves it for good, never back and forth); a later tier holds it
                    # whenever its own wait is within SPILL_S, whatever its age: an old review waits 5 s for main, it does
                    # not burn the 20-a-day escalation
                if pick is None:
                    t.hold = {'wait_s': round(best[0], 1) if best[0] < INF else None, 'channel': best[1], 'reason': best[2]}
                    if now + own + t.call_timeout > t.deadline:      # not even its own channel's wait fits: given back now
                        # (the queue ahead is not counted: those tickets may go to other tiers before it)
                        self._finish(t, *t.last, ch=None, expired=True, held=t.hold, eta_s=t.hold['wait_s'])
                    elif best[1] is not None and best[2] in PACING:
                        queue = ahead.setdefault(best[1], [0, 0])
                        queue[0] += min(t.est, self.b[best[1]]['eff'])
                        queue[1] += 1
                    continue
                if t.deadline - now < t.call_timeout:                    # never sent with less than its call time left
                    t.hold = {'wait_s': 0.0, 'channel': pick, 'reason': 'deadline'}
                    self._finish(t, *t.last, ch=None, expired=True, held=t.hold, eta_s=0.0)
                    continue
                sends.append(self._send(t, pick, now))
        for t, ch, at in sends:
            if self.inline:
                self._run(t, ch, at)
            else:
                threading.Thread(target=self._run, args=(t, ch, at), daemon=True).start()
        if self.inline:
            self.flush()
        return len(sends)

    def _send(self, t, cid, now) -> tuple:
        ch, b = self.ch[cid], self.b[cid]
        b['level'] -= t.est
        b['last'] = now
        t.entry = [now, t.est]
        b['win'].append(t.entry)
        b['day_n'] += 1
        at = C.reserve(self.q, ch, t.est, now=now)          # the shared ledger: the other processes see the booking
        m = self.models.setdefault(ch['model'], {'n': 0, 'until': 0.0, 'probe': False, 'mark': -INF})
        t.probe = bool(m['n'])
        if t.probe:
            m['probe'] = True                               # the one half-open probe after the pause (only ITS answer ends it)
        t.backoff_n, t.queued_s = m['n'], now - t.born
        self.pending.remove(t)
        self.flight[cid] = self.flight.get(cid, 0) + 1
        t.hold, self._dirty = None, True
        return t, ch, at

    def _run(self, t, ch, at) -> None:
        provider, _, model_id = ch['model'].partition('/')
        try:
            from .agent_factory_runner import _light_post, LIGHT_ENDPOINTS
            post, endpoints = self.post or _light_post, self.urls or LIGHT_ENDPOINTS
            body = dict(t.body, model=model_id)
            if isinstance(body.get('max_tokens'), int):
                body['max_tokens'] = C.max_output_for(ch['model'], body['max_tokens'])
            # the model's own body fields (Gemma's reasoning_effort) are added here, per channel (post_with_extra)
            status, raw, _ = C.post_with_extra(post, endpoints.get(provider, ''), self.keys.get(ch['key_env'], ''),
                                               body, t.call_timeout, ch['model'])
        except Exception as error:    # noqa: BLE001 - the ticket gets a refusal, never a hang
            status, raw = None, type(error).__name__.encode()
        self._done(t, ch, at, status, raw)

    def _done(self, t, ch, at, status, raw) -> None:
        with self.lock:
            now = self.clock()
            cid, b = ch['id'], self.b[ch['id']]
            self.flight[cid] = max(0, self.flight.get(cid, 1) - 1)
            kind = ('ok' if status == 200 else '429' if status == 429 else 'timeout' if status is None and raw == b'TimeoutError'
                    else 'net' if status is None and raw in NET_ERRORS
                    else '503' if status in OVERLOAD or status is None else 'other')
            self.hist.append((now, cid, kind))
            while now - self.hist[0][0] > 3600:
                self.hist.popleft()
            m = self.models.setdefault(ch['model'], {'n': 0, 'until': 0.0, 'probe': False, 'mark': -INF})
            if t.probe:
                m['probe'] = False                  # the probe's own answer ends the half-open state, no other one
            fresh = t.entry[0] >= m.get('mark', -INF)      # sent after the pause began: a call in flight from before never
            used = None                                    # resets nor doubles the pause
            if status == 200:
                got = (_json(raw).get('usage') or {}).get('prompt_tokens')
                used = got if type(got) is int and got >= 0 else t.est
                b['level'] -= used - t.est                      # the fact, not the estimate
                t.entry[1] = used
                C.reconcile(self.q, ch, at, t.est, used, requests=1, actual_requests=1)
                self._learn(t, got)
                if fresh:
                    m['n'], m['until'] = 0, 0.0
                self._io.append(('gate_clear', cid))
                self._finish(t, status, raw, ch)
            elif kind == 'timeout':     # charged in full; the caller's timeout contract (124 worker-timeout), never a re-send
                self._finish(t, status, raw, ch)
            elif kind == 'net':         # no connection: the channel rests briefly, the model is not paused, the ticket moves on
                b['closed'], b['why'] = max(b['closed'], now + NET_CLOSE_S), 'network'
                self._retry(t, status, raw)
            elif kind == '503':         # charged in full (the estimate and the request stay booked); the ticket moves on
                if fresh:
                    m['n'] += 1
                    m['until'], m['mark'] = now + backoff_s(m['n'], self.rng), now
                self._retry(t, status, raw)
            elif status == 429:
                day, ids, hint, reset = _quota_of(raw, now)
                t.quota = ','.join(ids)[:120]
                for qid in ids or ['']:
                    self.quota_log.append((now, cid, qid, 'day' if day else 'minute'))
                if day:       # PerDay: the channel is shut until the provider's reset; the ledger's day gate notes it
                    b['day'] = reset or C.quota_day(ch['model'], now)[1]
                    self._io.append(('gate_note', cid))
                else:         # PerMinute (or no quotaId): the bucket is emptied, the ceiling learns, the channel rests
                    b['level'] = min(b['level'], 0.0)
                    b['eff'] = max(FLOOR * ch['tpm'], b['eff'] * LEARN_DOWN)
                    b['clean'] = now
                    after = hint if isinstance(hint, (int, float)) and hint > 0 else MINUTE_CLOSE_S
                    b['closed'], b['why'] = now + after + self.rng.uniform(0, MINUTE_JITTER_S), 'rate_minute'
                self._retry(t, status, raw)
            elif status in (401, 403, 404):           # this key / model refuses: the channel rests, the ticket moves on
                b['closed'], b['why'] = now + REFUSED_CLOSE_S, 'refused_%d' % status
                self._retry(t, status, raw)
            else:
                self._finish(t, status, raw, ch)      # 400 ...: the request's own class of answer
            self._io.append(('log', {'channel': cid, 'model': ch['model'], 'role': t.role, 'status': status, 'kind': kind,
                                     'est': t.est, 'prompt_tokens': used if status == 200 else None,
                                     'quota_id': t.quota or None, 'queued_s': round(getattr(t, 'queued_s', 0.0), 1),
                                     'backoff_n': t.backoff_n}))
            self._dirty = True
        self.wake.set()
        if self.inline:
            self.flush()

    def _retry(self, t, status, raw) -> None:
        t.last = (status, raw)
        self.pending.append(t)

    # -- places --------------------------------------------------------------------------------------------------------
    def free(self, allowed, *, tokens=None, k_max=None, card=None, role='edit') -> dict:
        """The places the head offers an ensemble NOW, in tokens: per served channel of ``allowed`` that opens within
        PLACE_S, floor(the tokens it frees within PLACE_S / the role's estimate) (a model after its 503 pause: its one
        probe); each queued ticket takes one request and its tokens on the channel it waits for, and the places granted to
        other cards are taken off."""
        with self.lock:
            now = self.clock()
            est = self._est(role, tokens or PLACE_TOKENS)
            ids = [cid for cid in dict.fromkeys(allowed) if cid in self.ch]
            total, live, bad, probing = 0, 0, set(), set()
            room = {}       # fac-51: channel -> [requests it can still take within PLACE_S, tokens it frees, one call's size]
            for cid in ids:
                ch = self.ch[cid]
                until, why = self._shut(cid, now)
                if why == 'backoff':
                    bad.add(ch['model'])
                if until > now + PLACE_S:
                    continue
                live += 1
                m = self.models.get(ch['model'])
                if m and m['n']:                     # after its pause a model takes ONE probe (one place per model, not per key)
                    bad.add(ch['model'])
                    if ch['model'] not in probing:
                        probing.add(ch['model'])
                        total += 0 if m['probe'] else 1
                    continue
                b = self.b[cid]
                win = self._window(cid, now)
                freed = sum(n for t, n in win if t + 60 <= now + PLACE_S)
                avail = min(b['level'] + PLACE_S * b['eff'] / 60.0, b['eff'], b['eff'] - sum(n for _, n in win) + freed)
                need = min(est, b['eff'])                # a call bigger than the bucket takes the whole bucket
                gap = self._gap(ch)
                day_left = ch['rpd'] - b['day_n'] - self._odays.get(ch['group'], 0)    # never more places than the day has left
                rest = max(0.0, b['last'] + gap - now)       # the gap after its last send is not a place
                requests = min(int(max(0.0, PLACE_S - rest) / gap) + 1 if rest <= PLACE_S else 0, day_left) if gap else day_left
                room[cid] = [max(0, requests), max(0.0, avail), need]
            # the queued tickets take their places in the dispatch order, on the channel they wait for (their hold), else
            # the first channel of their route with a place left: a big review queued on Gemma takes Gemma's place, not main's
            for t in sorted(self.pending, key=lambda x: (max(0, x.prio - int((now - x.born) // AGE_S)), x.n)):
                fits = [cid for cid in t.allowed if cid in room and self._room(room[cid]) > 0]
                held = (t.hold or {}).get('channel')
                if held is not None and held in self.ch and held not in room:
                    continue                                 # it waits for a channel outside these: none of their places
                if fits:
                    cid = held if held in fits else fits[0]
                    room[cid][0] -= 1
                    room[cid][1] -= min(t.est, self.b[cid]['eff'])
            total += sum(self._room(r) for r in room.values())
            self.credits = {c: v for c, v in self.credits.items() if v[0] > now}
            reserved = sum(v[1] for c, v in self.credits.items() if c != card)
            free = max(0, total - reserved)
            return {'live': live, 'free': min(free, int(k_max)) if k_max else free, 'bad': sorted(bad)}

    @staticmethod
    def _room(row) -> int:
        """The places of one channel's [requests, tokens, size of a call]: the smaller of its requests and its tokens."""
        return max(0, min(row[0], int(max(0.0, row[1]) // row[2])))

    def capacity(self, allowed, **kw) -> dict:
        """The free places of the ``allowed`` channels now (see ``free``): the pool and an ensemble open no more."""
        out = self.free(allowed, **kw)
        return {'live': out['live'], 'free': out['free']}

    def grant(self, allowed, want, *, tokens=None, k_max=None, card=None, role='edit') -> dict:
        """The head gives a card ``k`` of the ``want`` branches it asks for (kept for the card for CREDIT_TTL_S, so 20 cards
        do not open their branches on the same place). k < 2: no ensemble, the card's main step."""
        with self.lock:
            out = self.free(allowed, tokens=tokens, k_max=k_max, card=card, role=role)
            k = max(0, min(int(want), out['free']))
            if card is not None:
                self.credits.pop(card, None)
                if k:
                    self.credits[card] = [self.clock() + CREDIT_TTL_S, k]
            return {'live': out['live'], 'free': out['free'], 'k': k, 'bad': out['bad']}

    def stats(self) -> dict:
        """stats.json 'head': per channel ok / 503 / 429 of the last hour, tokens sent in the last minute, the bucket and
        the learned ceiling; the queue by role; the 503 pause of every model; the quotaIds of the hour."""
        with self.lock:
            now = self.clock()
            out = {}
            for cid, ch in self.ch.items():
                b = self._bucket(cid, now)
                out[cid] = {'ok': 0, '503': 0, '429': 0, 'timeout': 0, 'in_flight': self.flight.get(cid, 0),
                            'tpm_busy': int(sum(n for _, n in self._window(cid, now))), 'level': int(b['level']),
                            'tpm_eff': int(b['eff']), 'day': b['day_n']}
            for at, cid, kind in self.hist:
                if cid in out and kind in out[cid]:
                    out[cid][kind] += 1
            backoff = {m: {'n': v['n'], 'wait_s': round(max(0.0, v['until'] - now), 1)} for m, v in self.models.items() if v['n']}
            return {'channels': out, 'queue': dict(collections.Counter(t.role for t in self.pending)), 'backoff': backoff,
                    'ratio': {r: round(v, 2) for r, v in self.ratio.items()},
                    'quota': dict(collections.Counter(q for at, _, q, _ in self.quota_log if now - at < 3600 and q))}

    # -- file IO, outside the lock -------------------------------------------------------------------------------------
    def flush(self, force=False) -> None:
        """The head's file IO, never under its lock and at most once per IO_GAP_S: the ledger section, the books (buckets
        and 503 pauses survive a restart), the day gate, the telemetry rows, the other processes' bookings."""
        with self.io_lock:          # the pump and close() never write the same files at once
            self._flush(force)

    def _flush(self, force) -> None:
        now = self.clock()
        if not force and now - self._io_at < IO_GAP_S:
            return
        self._io_at = now
        with self.lock:
            jobs, self._io = self._io, []
            snap = copy.deepcopy(self.q) if self._dirty and self.folder is not None else None
            books = self._books_snapshot() if self._dirty and self.books is not None else None
            self._dirty = False
            read_others = self.folder is not None and now - self._others_at >= OTHERS_GAP_S
            if read_others:
                self._others_at = now
        for job, arg in jobs:
            try:
                if job == 'log':
                    if self.log is not None:
                        self.log(arg)
                elif self.folder is not None:
                    (Q.gate_clear(self.folder, arg) if job == 'gate_clear' else Q.gate_note(self.folder, arg, now=now))
            except Exception:     # noqa: BLE001 - an aid: the answer stands
                pass
        try:
            if snap is not None:
                Q.publish(self.folder, self.section, snap, now=now)
            if books is not None:
                tmp = self.books.with_name(self.books.name + '.tmp%d' % os.getpid())
                tmp.write_text(json.dumps(books), encoding='utf-8')
                os.replace(tmp, self.books)
        except OSError:
            pass
        if read_others:
            try:
                others = Q.others(self.folder, self.section, now=now)
            except OSError:
                others = None
            if others is not None:
                days, mins = self._fold(others, now)
                with self.lock:
                    self._odays, self._omin = days, mins

    def _fold(self, others, now) -> tuple:
        """group -> today's requests (deduplicated: two copies of one section count once) / the minute's (time, tokens)."""
        days, mins = {}, {}
        for ch in self.ch.values():
            group, start = ch['group'], C.quota_day(ch['model'], now)[0]
            if group in days:
                continue
            stamps, minute = set(), set()
            for other in others:
                row = other.get(group) if isinstance(other, dict) else None
                if not isinstance(row, dict):
                    continue
                stamps.update(t for t in C._numbers(row.get('request_times')) if t >= start)
                for item in row.get('minute') or ():
                    if isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(x, (int, float)) for x in item):
                        if 0 <= now - item[0] < 60:
                            minute.add((float(item[0]), float(item[1])))
            days[group], mins[group] = len(stamps), sorted(minute)
        return days, mins

    def _books_snapshot(self) -> dict:
        keep = ('level', 'at', 'eff', 'clean', 'last', 'closed', 'why', 'day')
        return {'channels': {cid: {k: b[k] for k in keep if b[k] not in (INF, -INF)} for cid, b in self.b.items()},
                'models': {m: dict({'n': v['n'], 'until': v['until']}, **({'mark': v['mark']} if v.get('mark', -INF) > -INF else {}))
                           for m, v in self.models.items()},
                'ratio': self.ratio, 'saved': self.clock()}

    def _load(self) -> None:
        if self.books is None:
            return
        try:
            data = json.loads(self.books.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        now = self.clock()
        for cid, row in (data.get('channels') or {}).items():
            if cid in self.b and isinstance(row, dict):
                b, tpm = self.b[cid], self.ch[cid]['tpm']
                for k in ('level', 'at', 'clean', 'last', 'closed', 'day'):
                    if isinstance(row.get(k), (int, float)):
                        b[k] = float(row[k])
                if isinstance(row.get('eff'), (int, float)):
                    b['eff'] = min(CEIL * tpm, max(FLOOR * tpm, float(row['eff'])))
                b['why'] = str(row.get('why') or '')
                b['at'] = min(b['at'], now)
        for model, row in (data.get('models') or {}).items():
            if isinstance(row, dict):
                self.models[model] = {'n': int(row.get('n') or 0), 'until': float(row.get('until') or 0.0), 'probe': False,
                                      'mark': float(row['mark']) if isinstance(row.get('mark'), (int, float)) else -INF}
        self.ratio.update({r: min(RATIO_MAX, max(RATIO_MIN, float(v))) for r, v in (data.get('ratio') or {}).items()
                           if isinstance(v, (int, float))})

    def beat(self) -> None:
        if self.pulse is not None:
            try:
                self.pulse.write_text('%d %.0f' % (os.getpid(), time.time()), encoding='utf-8')
            except OSError:
                pass

    def pump(self) -> None:
        beat_at = -INF
        try:
            self.flush(force=True)       # the other processes' bookings (day count, minute window) are read BEFORE the first send
        except Exception as error:       # noqa: BLE001 - logged below on the next fault too; the pump goes on
            logging.getLogger(__name__).warning('head first flush: %s', type(error).__name__)
        while not self.stopping:
            try:
                started = self.step()
                self.flush()
            except Exception as error:   # noqa: BLE001 - one bad step never kills the pump (callers would wait on a dead head)
                logging.getLogger(__name__).exception('head pump step failed: %s', type(error).__name__)
                started = 0
                time.sleep(1.0)
            if time.monotonic() - beat_at >= PULSE_S:
                beat_at = time.monotonic()
                self.beat()
            if not started:
                self.wake.wait(0.25)
            self.wake.clear()


def serve(channels, env, state_file, *, folder=None, post=None, log=None) -> tuple:
    """Start the host: (Head, close()). The state file holds pid, port and the token (never the keys); the pulse file
    beside it is touched every PULSE_S; the books file keeps the buckets and the 503 pauses across a restart."""
    state = Path(state_file)
    head, token = Head(channels, env, post, folder=folder, books=state.with_name(BOOKS_NAME), log=log), secrets.token_hex(16)
    head.pulse = state.with_name(PULSE_NAME)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code, data):
            raw = json.dumps(data).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if self.headers.get('X-Head-Token') != token:
                return self._reply(403, {})
            try:
                data = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                if self.path == '/ask':
                    return self._reply(200, {'ticket': head.submit(data, remote=True)})
                if self.path == '/wait':
                    return self._reply(200, head.result(str(data['ticket']), min(30.0, float(data.get('wait') or 20))))
                if self.path == '/cancel':
                    return self._reply(200, {'cancelled': head.cancel(str(data['ticket']))})
                kw = dict(tokens=int(data.get('tokens') or 0) or None, k_max=int(data['k_max']) if data.get('k_max') else None,
                          card=data.get('card'), role=str(data.get('role') or 'edit'))
                if self.path == '/capacity':
                    return self._reply(200, head.capacity(list(data.get('channels') or []), **kw))
                if self.path == '/grant':
                    return self._reply(200, head.grant(list(data.get('channels') or []), int(data.get('want') or 1), **kw))
            except (ValueError, KeyError, TypeError) as error:
                return self._reply(400, {'error': type(error).__name__})
            self._reply(404, {})

    server = ThreadingHTTPServer((HOST, 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    head.beat()
    head.pump_thread = threading.Thread(target=head.pump, daemon=True)
    head.pump_thread.start()
    tmp = state.with_name(state.name + '.tmp%d' % os.getpid())
    tmp.write_text(json.dumps({'pid': os.getpid(), 'port': server.server_address[1], 'token': token, 'at': time.time()}),
                   encoding='utf-8')
    os.replace(tmp, state)

    def close():
        head.stopping = True
        server.shutdown()
        state.unlink(missing_ok=True)
        head.pulse.unlink(missing_ok=True)
        head._dirty = True
        head.flush(force=True)
    return head, close


def alive(state_file) -> bool:
    """The head lives: its state file names a live pid AND its pulse file is younger than PULSE_FRESH_S (a crashed head
    leaves head.json behind; the pulse tells it)."""
    if state_file is None:
        return False
    state = Path(state_file)
    try:
        pid = int(json.loads(state.read_text(encoding='utf-8')).get('pid') or 0)
        fresh = time.time() - state.with_name(PULSE_NAME).stat().st_mtime < PULSE_FRESH_S
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    if not fresh or pid <= 0:
        return False
    from .agent_factory import pid_alive
    return pid_alive(pid)


def _rpc(state_file, path, payload, timeout):
    state = json.loads(Path(state_file).read_text(encoding='utf-8'))
    request = urllib.request.Request('http:' + '//%s:%d%s' % (HOST, state['port'], path), data=json.dumps(payload).encode('utf-8'),
                                     headers={'X-Head-Token': state['token'], 'Content-Type': 'application/json'})
    with _NO_PROXY.open(request, timeout=timeout) as response:
        return json.loads(response.read())


def _places(state_file, path, payload, field) -> int:
    if not alive(state_file):
        raise HeadDown('dead', alive=False)
    try:
        return max(0, int(_rpc(state_file, path, payload, ANSWER_WAIT_S)[field]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HeadDown(type(error).__name__, alive=alive(state_file)) from error


def capacity(state_file, channels, *, tokens=None, k_max=None, card=None, role='edit') -> int:
    """The free places of ``channels`` in the head (Head.capacity); HeadDown when it does not answer."""
    return _places(state_file, '/capacity', {'channels': list(channels), 'tokens': tokens, 'k_max': k_max, 'card': card,
                                             'role': role}, 'free')


def grant(state_file, channels, want, *, tokens=None, k_max=None, card=None, role='edit') -> int:
    """How many of ``want`` ensemble branches the head gives this card (0 when none: the main step); HeadDown as capacity."""
    return _places(state_file, '/grant', {'channels': list(channels), 'want': want, 'tokens': tokens, 'k_max': k_max,
                                          'card': card, 'role': role}, 'k')


def ticket_deadline(call_timeout_s, wait_s=None) -> float:
    """The deadline of a ticket = the longest wait unsent (DEADLINE_S, or the caller's own smaller budget ``wait_s``) +
    the time of the call: the head never sends a ticket with less than its call time left, so a wait never eats the call."""
    wait = DEADLINE_S if wait_s is None else max(0.0, min(DEADLINE_S, float(wait_s)))
    return wait + float(call_timeout_s)


def ask(state_file, role, tokens, body, channels, *, deadline_s=None, call_timeout_s=90.0, priority=None, card=None) -> dict:
    """The answer {status, body, channel, model[, expired, held, eta_s]} of the host; HeadDown when it is dead (alive=False:
    the caller's old path) or does not accept in ANSWER_WAIT_S / dies while we wait (alive tells which)."""
    if not alive(state_file):
        raise HeadDown('dead', alive=False)
    deadline_s = ticket_deadline(call_timeout_s) if deadline_s is None else float(deadline_s)
    ticket = None
    try:
        ticket = _rpc(state_file, '/ask', {'role': role, 'tokens': tokens, 'body': body, 'channels': channels, 'priority': priority,
                                           'deadline_s': deadline_s, 'call_timeout_s': call_timeout_s, 'card': card},
                      ANSWER_WAIT_S)['ticket']
        end = time.time() + deadline_s + 15
        while True:
            answer = _rpc(state_file, '/wait', {'ticket': ticket, 'wait': 20}, 30)
            if answer.get('unknown'):         # a restarted head: it never answers another run's ticket
                raise HeadDown('unknown ticket', alive=alive(state_file))
            if not answer.get('pending'):
                return answer
            if not alive(state_file):         # the pump stopped (no pulse): the old path, not a wait to the deadline
                raise HeadDown('died while waiting', alive=False)
            if time.time() > end:
                raise HeadDown('no answer', alive=alive(state_file))
    except (OSError, ValueError, KeyError, HeadDown) as error:
        if ticket is not None:                # given up: the head drops the ticket unsent (no quota for nobody)
            try:
                _rpc(state_file, '/cancel', {'ticket': ticket}, 3)
            except (OSError, ValueError, KeyError):
                pass
        if isinstance(error, HeadDown):
            raise
        raise HeadDown(type(error).__name__, alive=alive(state_file)) from error
