"""fac-40: ONE host of the free small-tier calls. The loop starts it (local only, random port and token in a state file); a
runner or the loop sends {role, tokens, body, channels in order, deadline} and gets the answer or what holds it. One queue,
one counter per channel (factory_channels' choose/reserve/reconcile on the factory_quota ledger). Keys stay in the host."""
import collections
import itertools
import json
import os
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import factory_channels as C
from . import factory_quota as Q

PRIORITY = {'review': 0, 'repair': 1, 'edit': 2, 'code': 2}        # slice / keywords / the rest: 3
OVERLOAD = (500, 502, 503, 504)
STATE_NAME, DEADLINE_S = 'head.json', 240    # next to channels.json; the longest a caller waits (5-minute rule)
REVIEW_KEEP = 4500       # tokens of every minute window only a review may take: 100 queued edits never shut a finished candidate out
PER_CHANNEL = 3          # calls in flight on one channel
ROUND_PAUSE_S = 1.5      # every allowed channel refused: the circle again after this
ANSWER_WAIT_S, DOWN_REST_S = 5.0, 30.0     # no accept in 5 s = a dead host: the old path; it is not asked again for 30 s
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_DOWN = {'until': 0.0}
HOST = '.'.join(('127', '0', '0', '1'))     # this machine only


class HeadDown(Exception):
    """The host does not answer: the caller takes its old path and writes a telemetry event."""


def _json(raw) -> dict:
    try:
        data = json.loads(raw.decode('utf-8'))
        return data if isinstance(data, dict) else {}
    except (ValueError, AttributeError, UnicodeDecodeError):
        return {}


class _Ticket:
    def __init__(self, seq, req, now):
        self.seq, self.role, self.tokens = seq, str(req.get('role') or ''), max(1, int(req.get('tokens') or 1))
        self.prio = int(req['priority']) if req.get('priority') is not None else PRIORITY.get(self.role, 3)
        self.body, self.allowed = dict(req.get('body') or {}), list(req.get('channels') or [])
        self.deadline = now + float(req.get('deadline_s') or 120)
        self.call_timeout = float(req.get('call_timeout_s') or 90)
        self.tried, self.retry_at, self.last, self.hold = set(), 0.0, (None, b''), None
        self.done, self.result = threading.Event(), None


class Head:
    def __init__(self, channels, env, post=None, *, clock=time.time, folder=None, inline=False, urls=None):
        self.ch = {c['id']: c for c in C.validate(channels, warn=False)}
        self.keys, self.clock, self.folder, self.inline, self.post, self.urls = env, clock, folder, inline, post, urls
        self.section = 'head@%d' % os.getpid()
        self.q, self.closed, self.flight, self.pending, self.tickets = {}, {}, {}, [], {}
        self.hist = collections.deque()          # (time, channel, 'ok' | '503' | '429' | 'other')
        self.lock, self.wake, self.stopping = threading.RLock(), threading.Event(), False
        self.seq, self._others, self._others_at = itertools.count(1), [], -1e9

    def submit(self, req) -> int:
        with self.lock:
            t = _Ticket(next(self.seq), req, self.clock())
            self.tickets[t.seq] = t
            self.pending.append(t)
        self.wake.set()
        return t.seq

    def result(self, ticket, wait=0.0):
        t = self.tickets.get(ticket)
        if t is None:
            return {'status': None, 'why': 'unknown ticket'}
        if wait > 0:
            t.done.wait(wait)
        if t.done.is_set():
            self.tickets.pop(ticket, None)
            return t.result
        return {'pending': True, 'held': t.hold}

    def _finish(self, t, status, raw, ch=None, **extra):
        t.result = dict({'status': status, 'body': (raw or b'').decode('utf-8', 'replace'),
                         'channel': ch and ch['id'], 'model': ch and ch['model']}, **extra)
        self.pending = [x for x in self.pending if x is not t]
        t.done.set()

    def _seen(self, now) -> dict:
        if self.folder is not None and now - self._others_at > 3:
            self._others_at = now
            try:
                self._others = Q.others(self.folder, self.section, now=now)
            except OSError:
                pass
        return Q.view(self.q, self._others, now=now) if self._others else self.q      # no foreign sections: our own books

    def _publish(self) -> None:
        try:
            if self.folder is not None:
                Q.publish(self.folder, self.section, self.q, now=self.clock())
        except OSError:
            pass

    def step(self) -> int:
        """Dispatch what can go now, by priority then queue order; returns the number of calls started."""
        started = 0
        with self.lock:
            now = self.clock()
            seen, failed = self._seen(now), {}      # failed: a request shape that found no channel (booking more cannot help it)
            for t in sorted(self.pending, key=lambda x: (x.prio, x.seq)):
                if now >= t.deadline:
                    self._finish(t, *t.last, ch=None, expired=True, held=t.hold)
                    continue
                if t.retry_at > now:
                    continue
                shape = (tuple(t.allowed), tuple(sorted(t.tried)), t.tokens)
                pick, holds = None, []
                for cid in (t.allowed if shape not in failed else ()):
                    ch = self.ch.get(cid)
                    if ch is None or cid in t.tried:
                        continue
                    shut = self.closed.get(cid)
                    if shut and shut[0] > now:
                        holds.append((shut[0] - now, cid, shut[1]))
                    elif self.flight.get(cid, 0) >= PER_CHANNEL:
                        holds.append((1.0, cid, 'flight'))
                    else:
                        try:
                            C.choose([ch], seen, max(t.tokens, min(ch['tpm'], t.tokens + (REVIEW_KEEP if t.prio else 0))), self.keys, now=now)
                        except C.ChannelUnavailable as error:
                            holds.append((float(error.wait_s), cid, error.reason))
                            continue
                        pick = ch
                        break
                if pick is None:
                    if shape not in failed:
                        row = min(holds) if holds else (0.0, None, 'no_channel')
                        failed[shape] = {'wait_s': round(row[0], 1), 'channel': row[1], 'reason': row[2]}
                    t.hold = failed[shape]
                    if t.tried:                                  # the circle is done: again after a pause
                        t.tried, t.retry_at = set(), now + ROUND_PAUSE_S
                    continue
                at = C.reserve(self.q, pick, t.tokens, now=now)
                if seen is not self.q:
                    C.reserve(seen, pick, t.tokens, now=now)
                self.flight[pick['id']] = self.flight.get(pick['id'], 0) + 1
                self.pending.remove(t)
                t.hold, started = None, started + 1
                self._publish()
                if self.inline:
                    self._run(t, pick, at)
                else:
                    threading.Thread(target=self._run, args=(t, pick, at), daemon=True).start()
        return started

    def _run(self, t, ch, at) -> None:
        provider, _, model_id = ch['model'].partition('/')
        try:
            from .agent_factory_runner import _light_post, LIGHT_ENDPOINTS
            post, LIGHT_ENDPOINTS = self.post or _light_post, self.urls or LIGHT_ENDPOINTS
            left = max(10.0, min(t.call_timeout, t.deadline - self.clock()))
            status, raw, _ = C.post_with_extra(post, LIGHT_ENDPOINTS.get(provider, ''), self.keys.get(ch['key_env'], ''),
                                               dict(t.body, model=model_id), left, ch['model'])
        except Exception as error:    # noqa: BLE001 - the ticket gets a refusal, never a hang
            status, raw = None, type(error).__name__.encode()
        self._done(t, ch, at, status, raw)

    def _done(self, t, ch, at, status, raw) -> None:
        with self.lock:
            now = self.clock()
            self.flight[ch['id']] = max(0, self.flight.get(ch['id'], 1) - 1)
            kind = ('ok' if status == 200 else '429' if status == 429 else
                    '503' if status in OVERLOAD or (status is None and raw != b'TimeoutError') else 'other')
            self.hist.append((now, ch['id'], kind))
            while now - self.hist[0][0] > 3600:
                self.hist.popleft()
            if status == 200:
                used = (_json(raw).get('usage') or {}).get('prompt_tokens')
                C.reconcile(self.q, ch, at, t.tokens, used if type(used) is int else t.tokens, requests=1, actual_requests=1)
                self.closed.pop(ch['id'], None)
                self._gate(ch, clear=True)
                self._finish(t, status, raw, ch)
            elif kind == '503':      # refused: nothing was read, nothing is charged; another channel at once
                C.reconcile(self.q, ch, at, t.tokens, 0, requests=1, actual_requests=0)
                self._retry(t, ch, status, raw)
            elif status is None:     # a timeout reached the provider: counted; the next channel
                self._retry(t, ch, status, raw)
            elif status == 429:
                low = (raw or b'').lower()
                if b'perday' in low or b'per_day' in low or b'daily' in low:
                    until, why = C.quota_day(ch['model'], now)[1], 'rate_day'
                    self._gate(ch)
                else:
                    after = _json(raw).get('_retry_after')
                    until, why = now + max(1.0, min(60.0, after if isinstance(after, (int, float)) else 60 - now % 60)), 'rate_minute'
                self.closed[ch['id']] = (until, why)
                self._retry(t, ch, status, raw)
            else:
                self._finish(t, status, raw, ch)      # 400 / 401 / 404 ...: the caller's own class of answer
            self._publish()
        self.wake.set()

    def _retry(self, t, ch, status, raw) -> None:
        t.tried.add(ch['id'])
        t.last = (status, raw)
        self.pending.append(t)

    def _gate(self, ch, clear=False) -> None:      # the shared day gate of the ledger (closed until a probe answers)
        try:
            if self.folder is not None:
                Q.gate_clear(self.folder, ch['id']) if clear else Q.gate_note(self.folder, ch['id'], now=self.clock())
        except OSError:
            pass

    def capacity(self, allowed) -> dict:
        """W-a2: the free places of the ``allowed`` channels now: live channels (not shut by a 429) x PER_CHANNEL, minus the
        calls in flight on them and the tickets queued for them. An ensemble opens no more branches than this."""
        with self.lock:
            now = self.clock()
            live = [cid for cid in allowed if cid in self.ch and not (self.closed.get(cid) and self.closed[cid][0] > now)]
            places = sum(max(0, PER_CHANNEL - self.flight.get(cid, 0)) for cid in live)
            queued = sum(1 for t in self.pending if set(t.allowed) & set(live))
            return {'live': len(live), 'free': max(0, places - queued)}

    def stats(self) -> dict:
        """stats.json 'head': per channel ok / 503 / 429 of the last hour, tokens booked in the last minute; queue by role."""
        with self.lock:
            now = self.clock()
            out = {cid: {'ok': 0, '503': 0, '429': 0, 'in_flight': self.flight.get(cid, 0), 'tpm_busy': sum(
                n for t, n in self.q.get(ch['group'], {}).get('minute', []) if now - t < 60)} for cid, ch in self.ch.items()}
            for at, cid, kind in self.hist:
                if cid in out and kind in out[cid]:
                    out[cid][kind] += 1
            return {'channels': out, 'queue': dict(collections.Counter(t.role for t in self.pending))}

    def pump(self) -> None:
        while not self.stopping:
            if not self.step():
                self.wake.wait(0.25)
            self.wake.clear()


def serve(channels, env, state_file, *, folder=None, post=None) -> tuple:
    """Start the host: (Head, close()). The state file holds pid, port and the token (never the keys)."""
    head, token, state = Head(channels, env, post, folder=folder), secrets.token_hex(16), Path(state_file)

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
                    return self._reply(200, {'ticket': head.submit(data)})
                if self.path == '/wait':
                    return self._reply(200, head.result(int(data['ticket']), min(30.0, float(data.get('wait') or 20))))
                if self.path == '/capacity':
                    return self._reply(200, head.capacity(list(data.get('channels') or [])))
            except (ValueError, KeyError, TypeError) as error:
                return self._reply(400, {'error': type(error).__name__})
            self._reply(404, {})

    server = ThreadingHTTPServer((HOST, 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=head.pump, daemon=True).start()
    tmp = state.with_name(state.name + '.tmp%d' % os.getpid())
    tmp.write_text(json.dumps({'pid': os.getpid(), 'port': server.server_address[1], 'token': token, 'at': time.time()}),
                   encoding='utf-8')
    os.replace(tmp, state)

    def close():
        head.stopping = True
        server.shutdown()
        state.unlink(missing_ok=True)
    return head, close


def _rpc(state_file, path, payload, timeout):
    state = json.loads(Path(state_file).read_text(encoding='utf-8'))
    request = urllib.request.Request('http:' + '//%s:%d%s' % (HOST, state['port'], path), data=json.dumps(payload).encode('utf-8'),
                                     headers={'X-Head-Token': state['token'], 'Content-Type': 'application/json'})
    with _NO_PROXY.open(request, timeout=timeout) as response:
        return json.loads(response.read())


def capacity(state_file, channels) -> int:
    """W-a2: the free places of ``channels`` in the head (Head.capacity); HeadDown when the head does not answer at once
    (the ensemble then takes its old path)."""
    if time.time() < _DOWN['until']:
        raise HeadDown('resting')
    try:
        return max(0, int(_rpc(state_file, '/capacity', {'channels': list(channels)}, ANSWER_WAIT_S)['free']))
    except (OSError, ValueError, KeyError, TypeError) as error:
        _DOWN['until'] = time.time() + DOWN_REST_S
        raise HeadDown(type(error).__name__) from error


def ask(state_file, role, tokens, body, channels, *, deadline_s=120.0, call_timeout_s=90.0, priority=None) -> dict:
    """The answer {status, body, channel, model[, expired, held]} of the host; HeadDown when it does not accept in 5 s
    or dies while we wait (the caller then takes its own path)."""
    if time.time() < _DOWN['until']:
        raise HeadDown('resting')
    try:
        ticket = _rpc(state_file, '/ask', {'role': role, 'tokens': tokens, 'body': body, 'channels': channels, 'priority': priority,
                                           'deadline_s': deadline_s, 'call_timeout_s': call_timeout_s}, ANSWER_WAIT_S)['ticket']
        end = time.time() + deadline_s + 15
        while True:
            answer = _rpc(state_file, '/wait', {'ticket': ticket, 'wait': 20}, 30)
            if not answer.get('pending'):
                return answer
            if time.time() > end:
                raise HeadDown('no answer')
    except (OSError, ValueError, KeyError) as error:
        _DOWN['until'] = time.time() + DOWN_REST_S
        raise HeadDown(type(error).__name__) from error
