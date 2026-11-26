"""fac-43: the one router of the rig (roots/ROUTER_DESIGN.md, section 2; steps 0-1).

A score table per "model|role" built from the telemetry (``build``) and the one choice of a model for a call (``pick`` /
``order``): a Thompson draw from the Beta estimate of each live model's ACCEPTED cards per call. The table replaces the
tiers, the ratings, the A/B arms and the small-model rules of the code and edit calls.

The metric is accepted cards only: a card counts when its commit is in a base whose full cloud build was green (the
loop's span ``accepted``, written where a green release takes the card). An accepted card is shared among the models
of each role by their calls on it. The estimate of a row is (accepted + a) / (calls + b); a and b are the role's own
share (its accepted over its calls) at the weight of a mean row, recomputed with every build, never set by hand.

Cooling marks are read here RAW (``raw_until``): what ``apply_failure`` wrote holds in full, nothing is cut or
zeroed on the way. A cooled channel is never dropped from the walk: it goes after the open ones (the one that opens
first, first), so choose() still decides the wait, the half-open probe and the fallback with its own rules."""
from __future__ import annotations

import json
import os
import random
import time
from typing import NamedTuple

from . import factory_channels as C

TABLE_NAME = 'router_table.json'
TELEMETRY_NAMES = ('telemetry.jsonl.2', 'telemetry.jsonl.1', 'telemetry.jsonl')   # oldest first
ROLES = ('slice', 'code', 'edit', 'review', 'paid_review')
ROLE_OF = {'repair': 'code', 'unit_test': 'code', 'cross_review': 'review'}
WINDOW_CARDS = 400


class Choice(NamedTuple):
    model: str
    channel: dict
    note: str = ''          # 'author_allowed': every other model is out, the excluded one takes the call
    walk: tuple = ()        # every channel of the call in the router's order (the chosen one first)


class Wait(NamedTuple):
    seconds: float
    fallback: object = None


def role_of(role) -> str:
    role = str(role or '')
    return ROLE_OF.get(role, role)


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _read_rows(paths):
    for path in paths:
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        yield row
        except OSError:
            continue


def _call_of(row):
    """(role, model) of a telemetry row that is ONE model call, else None. The runner's calls are spans run / review
    with a ``role`` (the pass's own run row and the stage rows have none); a slice names its ``engine``; the paid critic
    is role paid_review."""
    span = row.get('span')
    if span in ('run', 'review') and row.get('role') and row.get('model') and not row.get('stage'):
        return role_of(row['role']), str(row['model'])
    if span == 'slice' and row.get('engine'):
        return 'slice', str(row['engine'])
    if span == 'paid_critic' and row.get('model'):
        return 'paid_review', str(row['model'])
    return None


def _accepted_of(row):
    """The task id of a row that says a card was accepted by a green full build: the span ``accepted`` (step 0), and the
    older ``accept`` event the loop writes at the same place (reason accepted_by_release)."""
    if row.get('span') == 'accepted' and row.get('task_id'):
        return str(row['task_id'])
    if row.get('span') == 'accept' and row.get('status') == 'accepted' and row.get('reason') == 'accepted_by_release' \
            and row.get('task_id'):
        return str(row['task_id'])
    return None


def _pass_row(row) -> bool:
    """The loop's row of one runner pass (span run, no role, no stage): the call rows of the pass follow it."""
    return row.get('span') == 'run' and not row.get('role') and not row.get('stage')


def models_by_role(rows, tids) -> dict:
    """{task_id: {role: {model: calls}}} of the given cards: the models whose calls MADE the commit (the content of the
    span ``accepted``): the answered calls (status not 'error') of the card's last pass that went to review (status
    REVIEW), else of its last pass with an answered call. The calls of the red passes before it are not credited."""
    want = set(tids)
    passes: dict = {}               # tid -> [[status, {role: {model: calls}}], ...]
    for row in rows:
        tid = str(row.get('task_id') or '')
        if tid not in want:
            continue
        if _pass_row(row):
            passes.setdefault(tid, []).append([str(row.get('status') or ''), {}])
            continue
        call = _call_of(row)
        if call is None or row.get('status') == 'error':
            continue
        groups = passes.setdefault(tid, [])
        if not groups:
            groups.append(['', {}])
        per = groups[-1][1].setdefault(call[0], {})
        per[call[1]] = per.get(call[1], 0) + 1
    out: dict = {}
    for tid, groups in passes.items():
        made = [g for g in groups if g[1]]
        best = [g for g in made if g[0] == 'REVIEW'] or made
        if best:
            out[tid] = best[-1][1]
    return out


def telemetry_rows(state_dir) -> list:
    """The rows of the telemetry of ``state_dir``: telemetry.jsonl and its two rotations, oldest first."""
    return list(_read_rows([os.path.join(str(state_dir), n) for n in TELEMETRY_NAMES]))


def build(state_dir, *, rows=None, window: int = WINDOW_CARDS, write: bool = True) -> dict:
    """The score table from the telemetry of ``state_dir`` (or ``rows``): {'rows': {"model|role": {calls, tokens, wall_s,
    accepted, rejected_final, last_ts}}, 'prior': {role: {a, b}}, 'window': n, 'built_at': ts}. Only the calls of the last
    ``window`` cards count. Written to ``state_dir``/router_table.json when ``write``."""
    rows = telemetry_rows(state_dir) if rows is None else list(rows)
    order: list = []                # task ids by their first call
    seen: set = set()
    calls: dict = {}                # tid -> {(model, role): [calls, tokens, wall_s, last_ts]}
    accepted: dict = {}             # tid -> {role: {model: calls}} (from the span; may be empty)
    failed: set = set()
    for row in rows:
        tid = str(row.get('task_id') or '')
        if not tid:
            continue
        acc = _accepted_of(row)
        if acc is not None:
            models = row.get('models') if isinstance(row.get('models'), dict) else {}
            parsed = {role_of(r): (m if isinstance(m, dict) else {str(x): 1 for x in (m or ())})
                      for r, m in models.items()}
            accepted[acc] = {r: m for r, m in parsed.items() if m} or accepted.get(acc) or {}   # 'accept' + 'accepted': one
            failed.discard(acc)
            continue
        if row.get('span') == 'run' and not row.get('role') and row.get('status') == 'FAILED':
            failed.add(tid)         # the pass that ended the card for good
            continue
        call = _call_of(row)
        if call is None:
            continue
        if tid not in seen:
            seen.add(tid)
            order.append(tid)
        cell = calls.setdefault(tid, {}).setdefault((call[1], call[0]), [0, 0.0, 0.0, ''])
        cell[0] += 1
        cell[1] += _num(row.get('tokens_in')) + _num(row.get('tokens_out'))
        cell[2] += _num(row.get('dur_s'))
        cell[3] = max(cell[3], str(row.get('ts') or ''))
    keep = set(order[-window:]) if window else set(order)
    table: dict = {}

    def cell_of(model, role):
        return table.setdefault('%s|%s' % (model, role), dict(calls=0, tokens=0, wall_s=0.0, accepted=0.0,
                                                               rejected_final=0.0, last_ts=''))
    for tid in keep:
        for (model, role), (n, tok, wall, ts) in calls.get(tid, {}).items():
            row = cell_of(model, role)
            row['calls'] += n
            row['tokens'] += int(tok)
            row['wall_s'] = round(row['wall_s'] + wall, 3)
            row['last_ts'] = max(row['last_ts'], ts)

    # an accepted card is credited to the models whose calls made its commit (the span's models; without them the same
    # reading of the call rows), never to every call of the card: the red passes before it earned nothing
    made = models_by_role(rows, [t for t in keep if t in accepted and not accepted[t]])

    def share(per_role, field):
        for role, models in per_role.items():
            total = sum(models.values()) or 1
            for model, n in models.items():
                cell_of(model, role)[field] += n / total
    for tid in keep:            # the window only: a card without a call in it is not in the table
        if tid in accepted:
            share(accepted[tid] or made.get(tid) or {}, 'accepted')
        elif tid in failed:     # the card's final FAILED (the runner gives it only when the attempts are spent)
            per_role: dict = {}
            for (model, role), cell in calls.get(tid, {}).items():
                per_role.setdefault(role, {})[model] = cell[0]
            share(per_role, 'rejected_final')
    for row in table.values():
        row['accepted'] = round(row['accepted'], 4)
        row['rejected_final'] = round(row['rejected_final'], 4)
    out = {'rows': table, 'prior': priors(table), 'window': window, 'built_at': time.time()}
    if write and state_dir is not None:
        path = os.path.join(str(state_dir), TABLE_NAME)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    return out


def priors(rows: dict) -> dict:
    """{role: {'a', 'b'}}: b = the mean calls of a row of the role (at least 1), a = b x the role's share of accepted
    cards per call (Laplace: (accepted + 1) / (calls + 2), so a is never 0)."""
    sums: dict = {}
    for key, row in rows.items():
        role = key.rsplit('|', 1)[-1]
        acc = sums.setdefault(role, [0.0, 0.0, 0])
        acc[0] += _num(row.get('accepted'))
        acc[1] += _num(row.get('calls'))
        acc[2] += 1
    out = {}
    for role, (acc, n, rows_n) in sums.items():
        b = max(1.0, n / rows_n) if rows_n else 1.0
        out[role] = {'a': round(b * (acc + 1) / (n + 2), 6), 'b': round(b, 6)}
    return out


def load(state_dir) -> dict:
    """The table written by build(); an empty one when it cannot be read (every model then has the role's prior)."""
    try:
        with open(os.path.join(str(state_dir), TABLE_NAME), encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def estimate(table: dict, model: str, role: str) -> tuple:
    """(alpha, beta) of the Beta estimate of ``model`` in ``role``: alpha = accepted + a, beta = calls - accepted + b - a."""
    role = role_of(role)
    prior = ((table or {}).get('prior') or {}).get(role) or {}
    b = max(1e-6, _num(prior.get('b')) or 2.0)
    a = min(b - 1e-6, max(1e-6, _num(prior.get('a')) or b / 2))
    row = ((table or {}).get('rows') or {}).get('%s|%s' % (model, role)) or {}
    calls, acc = _num(row.get('calls')), _num(row.get('accepted'))
    acc = min(acc, calls)
    return acc + a, max(1e-6, calls - acc) + (b - a)


def raw_until(state, channel) -> float:
    """When the cooling marks of ``channel`` end, read raw: the model's, the channel's and the key group's marks and a
    probe in flight, exactly as apply_failure / note_outcome wrote them (no cut, no reset)."""
    def num(value):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
    state = state if isinstance(state, dict) else {}
    model = state.get('model_cool')
    chan = state.get('channel_cool')
    group = state.get(channel.get('group'))
    marks = [num(model.get(channel.get('model'))) if isinstance(model, dict) else 0.0,
             num(chan.get(channel.get('id'))) if isinstance(chan, dict) else 0.0,
             num(group.get('cool_until')) if isinstance(group, dict) else 0.0]
    probes = state.get('day_probe')
    if isinstance(probes, dict):
        for key in (channel.get('id'), 'group:' + str(channel.get('group')), 'model:' + str(channel.get('model'))):
            row = probes.get(key)
            if isinstance(row, dict):
                marks.append(num(row.get('flight')))
    return max(marks)


def allowed(candidates, state, env, exclude=(), *, now=None) -> tuple:
    """(usable channels after the exclusion, lifted): ``exclude`` (the authors) is out while another usable model is
    left; with none left the excluded models are let in and ``lifted`` is True."""
    now = time.time() if now is None else now
    live = C.usable(list(candidates), state or {}, env, now=now)
    out = set(exclude or ())
    rest = [c for c in live if c['model'] not in out]
    if rest or not live:
        return rest, False
    return live, True


def order(role, candidates, state, env, *, table=None, exclude=(), preferred=None, now=None, rng=None,
          draws=None) -> list:
    """The channels of ``candidates`` a call of ``role`` walks, best draw first: one Thompson draw per live model from its
    Beta estimate, the model's channels in their given order. ``draws`` (a dict the caller keeps for one pass and role)
    holds the draws, so the calls of one pass (the precheck, the head, every repeat) walk the same order. Every
    candidate cold (the table knows none of them): ``preferred`` first, then the given order. The escalation tier (a
    small quota) walks after the others. A channel cooled by a raw mark is not dropped: it walks after every open one,
    the one that opens first, first. Never raises; no live candidate: the candidates as given (choose() names why)."""
    now = time.time() if now is None else now
    live, _lifted = allowed(candidates, state, env, exclude, now=now)
    if not live:
        return list(candidates)
    models = []
    for c in live:
        if c['model'] not in models:
            models.append(c['model'])
    rows = (table or {}).get('rows') or {}
    if not any(('%s|%s' % (m, role_of(role))) in rows for m in models):
        ranked = sorted(models, key=lambda m: m != preferred)
    else:
        rng = rng or random.Random()
        draws = {} if draws is None else draws
        for m in models:
            if m not in draws:
                draws[m] = rng.betavariate(*estimate(table, m, role))
        ranked = sorted(models, key=lambda m: -draws[m])

    def key(c):
        until = raw_until(state, c)
        cooled = until > now
        return cooled, until if cooled else 0.0, C.tier_of(c) == 'escalation', ranked.index(c['model'])
    return sorted(live, key=key)


def pick(role, card=None, exclude=(), *, channels_list, state, env, table=None, preferred=None, now=None, rng=None,
         draws=None):
    """The one choice of a model for a call: Choice(model, channel, note, walk), or Wait(seconds, fallback) when the
    best channel left is cooled by a raw mark (``fallback``: the Choice of that walk, for a caller that cannot wait).
    ``card`` names the call's card (kept for the caller's record); ``exclude`` (the authors) is out while another model
    is live; with none, the author takes the call with the note 'author_allowed'. No live channel: Wait(3600)."""
    now = time.time() if now is None else now
    live, lifted = allowed(channels_list, state, env, exclude, now=now)
    if not live:
        return Wait(3600.0)
    walk = order(role, channels_list, state, env, table=table, exclude=exclude, preferred=preferred, now=now, rng=rng,
                 draws=draws)
    head = walk[0]
    got = Choice(head['model'], head, 'author_allowed' if lifted else '', tuple(walk))
    until = raw_until(state, head)
    return Wait(until - now, got) if until > now else got
