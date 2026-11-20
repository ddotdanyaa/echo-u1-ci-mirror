"""Free-model channels: token reservation, structural error classes, cooling.

Quotas are grouped by provider project (never by key text) and live in the checkpoint.
Error classes come from the STRUCTURE of Kilo's JSON events (``type == "error"``,
``error.name``, ``error.data.statusCode/message/responseBody``). Regular expressions touch only the
text of an error (event message, response body, stderr); the stdout of a call that did not fail
is never grepped, because it carries the model's answer and other people's files.

Gemini error semantics: https://ai.google.dev/gemini-api/docs/troubleshooting (400 invalid key,
403 permission/region, 429 ``QuotaFailure.violations[].quotaId`` PerMinute/PerDay and
``RetryInfo.retryDelay``); free-tier limits and the daily reset (midnight Pacific time):
https://ai.google.dev/gemini-api/docs/rate-limits (see <id>/reports/DAY19_RESEARCH_R1_AGENTS_APIS.md).

TPM counts INPUT tokens (checked 19.11.2026 on https://ai.google.dev/gemini-api/docs/rate-limits, which now
redirects to aistudio.google.com/docs/rate-limits: the column is "Tokens per minute (input) (TPM)"). That page
lists no Gemma free tier; Gemma limits come from the channel file.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import math
import re
import time

from .agent_factory import InvalidPlan, MODEL_ID

CHARS_PER_TOKEN = 3.5
# Measured by the canary (<id>/05_WORK/<id>/reports/DAY19_CHANNEL_CANARY.md, "Токены на запрос"): the input of the
# first Kilo step is 6 026 on Gemini, 4 377 on Gemma 26B, 5 045 on OpenRouter; the old guess was 13 000.
KILO_OVERHEAD_TOKENS = 7300    # 6 026 (the largest first step) + 20 %
SMALL_OVERHEAD_TOKENS = 5300   # 4 377 (Gemma, the small tier) + 20 %
# Steps of a small-tier run that land in one minute: canary, gemma-4-31b, 3 steps in 151 s = about 50 s a step,
# so 60 / 50 rounds up to 2 (and never more than the channel's rpm). The input GROWS with every step (the
# canary: first step 4 377, second 5 129 = +17.2 %, rounded up to 0.18).
SMALL_STEP_SECONDS = 50
STEP_GROWTH = 0.18
PROMPT_LIMIT_CHARS = 28000     # a longer prompt is never sent: the triage splits the task
REGION_COOL_S = 3600           # a proxy exit may change: probe again in an hour
MODEL_MISSING_TTL_S = 6 * 3600
BALANCE_COOL_S = 6 * 3600      # 402: negative balance does not fix itself within minutes
TRANSIENT_RETRY_S = 20
DEFAULT_COOL_S = 60
RATE_SUSPECT_COOL_S = 900      # Kilo slept inside the call (its own 429 retries): cool the channel, not the task
OVERLOAD_STATUSES = (500, 502, 503, 504)   # the provider's model is overloaded or failing right now
OVERLOAD_COOL_S = 120          # long enough for the retry and the next pass to take another channel
OVERLOAD_COOL_MAX_S = 900      # a model that stays overloaded is tried 4 times an hour, not 30 (live 19.11: Gemma 4
                               # answered 503 to 11 of 17 reviews, each refusal took 0.6-43 s)
OVERLOAD_FORGET_S = 1800       # no overload of the model for half an hour: the next one starts a new series
TIERS = ('small', 'main', 'escalation')
# The day of a provider's daily quota (requests per day): Google AI Studio resets at midnight Pacific (the page
# above), OpenRouter's free models at 00:00 UTC (live 19.11 20:03: its 429 free-models-per-day carries
# metadata.headers X-RateLimit-Reset). The day window counts from the provider's midnight, not over the last 24 h,
# and a daily 429 cools until that provider's reset (live 20.11 03:00: OpenRouter, reset at 00:00 UTC, stayed
# cooled until midnight Pacific, 8 h of its free quota unused; the rolling window held models after their reset).
UTC_DAY_PROVIDERS = frozenset(('openrouter',))
DAY_RESET_MAX_S = 26 * 3600    # a reset time the provider names further away than this is not believed
DAY_GRACE_S = 3600             # a daily 429 in the first hour of the provider's day with no reset time named:
DAY_GRACE_COOL_S = 900         # the provider's counter may lag its clock, so cool 15 minutes, not the whole day


class ChannelUnavailable(InvalidPlan):
    """Temporary quota exhaustion, not a bad task or scope violation."""

    def __init__(self, message='no channels currently available', reason='unavailable', wait_s=60.0):
        super().__init__(message)
        self.reason = reason
        self.wait_s = float(wait_s)


def estimate_tokens(prompt_chars: int, read_chars: int = 0, overhead: int | None = None) -> int:
    """INPUT tokens of ONE request: the prompt + the files the model will read with its tool (chars / 3.5) +
    the engine overhead: Kilo's system prompt and tool schemas by default, ``overhead`` for the light engine
    (one REST request, no tools). TPM counts input tokens only (see the module docstring), so the answer is not
    booked."""
    return (math.ceil(max(0, prompt_chars) / CHARS_PER_TOKEN) + math.ceil(max(0, read_chars) / CHARS_PER_TOKEN)
            + (KILO_OVERHEAD_TOKENS if overhead is None else max(0, overhead)))


def validate(channels):
    seen = set()
    for channel in channels:
        if channel['id'] in seen or not MODEL_ID.fullmatch(channel['model']):
            raise InvalidPlan('duplicate channel or invalid model')
        seen.add(channel['id'])
        if not channel.get('group') or not channel.get('key_env'):
            raise InvalidPlan('channel requires quota group and key_env')
        if not all(type(channel.get(k)) is int and channel[k] > 0 for k in ('tpm', 'rpd')):
            raise InvalidPlan('actual positive channel quotas required')
        if 'rpm' in channel and not (type(channel['rpm']) is int and channel['rpm'] > 0):
            raise InvalidPlan('rpm must be a positive integer')
        if 'tier' in channel and channel['tier'] not in TIERS:
            raise InvalidPlan('tier must be small, main or escalation')
        if channel['model'].split('/')[0] not in ('google', 'openrouter'):
            raise InvalidPlan('unsupported provider')
    groups = {}
    for c in channels:
        limits = (c['tpm'], c['rpd'], c.get('rpm'))
        if c['group'] in groups and groups[c['group']] != limits:
            raise InvalidPlan('shared quota group has inconsistent limits')
        groups[c['group']] = limits


def tier_of(channel) -> str:
    return channel.get('tier', 'main')


_ROLE_TIERS = {   # candidate order of tiers for a call; a tier that is not listed is not used for that role
    ('code', 1): ('main', 'small', 'escalation'),
    ('code', 2): ('escalation', 'main'),
    'review': ('small', 'main', 'escalation'),
    'cross_review': ('main', 'small', 'escalation'),
}


def minute_steps(channel) -> int:
    """Requests of one run that fit one minute on ``channel``: 60 s / the measured step time, at most its rpm."""
    steps = -(-60 // SMALL_STEP_SECONDS)
    rpm = channel.get('rpm') if isinstance(channel, dict) else None
    return min(steps, rpm) if isinstance(rpm, int) and rpm > 0 else steps


def small_minute_need(tokens: int, channel=None) -> int:
    """Input per MINUTE of a run on the small tier: the Gemma-size first request, then each further step of the
    minute carrying the measured context growth: base * (k + growth * k * (k - 1) / 2) for k steps."""
    base = max(0, tokens - KILO_OVERHEAD_TOKENS + SMALL_OVERHEAD_TOKENS)
    k = minute_steps(channel)
    return int(base * (k + STEP_GROWTH * k * (k - 1) / 2))


def excluded_models(exclude_model) -> frozenset:
    """None, one model id, or a collection of model ids -> the set of excluded models."""
    if exclude_model is None:
        return frozenset()
    if isinstance(exclude_model, str):
        return frozenset((exclude_model,))
    return frozenset(exclude_model)


def route_order(channels, role, attempt, tokens, *, preferred=None, exclude_model=None, skip_tiers=()):
    """Channels in the order a call tries them. Coder, attempt 1: main, small (only when ``tokens`` fit its tpm),
    escalation; attempt 2 and later: escalation, main. Reviewer: small first; cross-review: main first.
    ``exclude_model`` (the coder's model) never reviews its own work; a collection of models excludes them all (the
    tournament's next candidate and the chain's next critic are other models). ``preferred`` breaks ties in a tier.
    ``skip_tiers``: tiers this call may not use (<id> small_follow_up 'off': no small-tier model as a later
    tournament candidate)."""
    key = ('code', 1 if attempt <= 1 else 2) if role == 'code' else role
    ranks = _ROLE_TIERS[key]
    excluded = excluded_models(exclude_model)
    picked = []
    for channel in channels:
        tier = tier_of(channel)
        if tier not in ranks or tier in skip_tiers or channel['model'] in excluded:
            continue
        if tier == 'small' and small_minute_need(tokens, channel) > channel['tpm']:    # Gemma only when a minute of it fits
            continue
        picked.append(channel)
    return sorted(picked, key=lambda c: (ranks.index(tier_of(c)), c['model'] != preferred))


def _fingerprint(env, channel) -> str:
    return hashlib.sha256((env.get(channel['key_env']) or '').encode('utf-8')).hexdigest()[:12]


def _dead_until(dead: dict):
    """When a dead mark ends (None = never, until the key changes). A numeric ``until`` is the answer; a
    non-numeric one is garbage and expires at once; ``model_missing`` without ``until`` ends at since + 6 h
    (garbage ``since``: at once); anything else (key_invalid, an old mark without a reason) never expires."""
    if dead.get('until') is not None:      # until=None means "until the key changes": the reason decides
        until = dead['until']
        return float(until) if isinstance(until, (int, float)) and not isinstance(until, bool) else 0.0
    if dead.get('reason') == 'model_missing':
        since = dead.get('since')
        if isinstance(since, (int, float)) and not isinstance(since, bool):
            return float(since) + MODEL_MISSING_TTL_S
        return 0.0
    return None


def usable(channels, state, env, *, now=None):
    """The channels that can ever take a call now: a key is set and no dead mark for that key is in force."""
    now = time.time() if now is None else now
    live = []
    for channel in channels:
        dead = state.get('dead', {}).get(channel['id'])
        if dead and dead.get('key') == _fingerprint(env, channel):
            until = _dead_until(dead)
            if until is None or until > now:
                continue
        if env.get(channel['key_env']):
            live.append(channel)
    return live


def _numbers(value):
    """A list of plain numbers; anything else (old or corrupted state) reads as empty."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _model_cool(state, channel) -> float:
    table = state.get('model_cool')
    value = table.get(channel['model']) if isinstance(table, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _balanced(channels, state, now):
    """Channels of one model on several keys: the one with the most requests left today first; the order of the
    models stays (owner: the load spreads over all connected keys instead of using one key up first)."""
    def left(channel):
        times = state.get(channel['group'], {}).get('request_times', [])
        start = quota_day(channel['model'], now)[0]
        return channel['rpd'] - sum(1 for t in times if t >= start)
    models, by_model = [], {}
    for channel in channels:
        if channel['model'] not in by_model:
            by_model[channel['model']] = []
            models.append(channel['model'])
        by_model[channel['model']].append(channel)
    return [c for m in models for c in sorted(by_model[m], key=lambda c: -left(c))]


def choose(channels, state, tokens, env, *, now=None, requests=1):
    """First channel that can take ``tokens`` and ``requests`` now, else ChannelUnavailable(reason, wait_s)."""
    now = time.time() if now is None else now
    validate(channels)
    reasons = []  # (reason, wait_s)
    for channel in _balanced(channels, state, now):
        group = state.get(channel['group'], {})
        dead = state.get('dead', {}).get(channel['id'])
        if dead and dead.get('key') == _fingerprint(env, channel):
            until = _dead_until(dead)       # None = until the key changes; a TTL entry expires (the retry probe)
            if until is None or until > now:
                reasons.append(('dead', 3600.0 if until is None else max(1.0, min(3600.0, until - now))))
                continue
        if not env.get(channel['key_env']):
            reasons.append(('no_key', 3600.0))
            continue
        if tokens > channel['tpm']:
            reasons.append(('reservation_exceeds_tpm', 3600.0))
            continue
        cool = max(group.get('cool_until', 0), _model_cool(state, channel))
        if cool > now:
            reasons.append(('cool', cool - now))
            continue
        start, end = quota_day(channel['model'], now)       # the provider's day, not the last 24 h
        used = [t for t in group.get('request_times', []) if t >= start]
        # exactly what reserve() books: the day window the whole run (at most rpd), the minute window at most rpm
        need = min(requests, channel['rpd'])
        if len(used) + need > channel['rpd']:
            reasons.append(('rpd', max(1.0, end - now)))
            continue
        if channel.get('rpm'):
            lately = sorted(t for t in _numbers(group.get('rpm_times')) if now - t < 60)
            if len(lately) + min(requests, channel['rpm']) > channel['rpm']:
                reasons.append(('rpm', max(1.0, 60 - (now - lately[0])) if lately else 1.0))
                continue
        recent = sorted((t, n) for t, n in group.get('minute', []) if now - t < 60)
        if sum(n for _, n in recent) + tokens > channel['tpm']:
            wait = 60 - (now - recent[0][0]) if recent else 60
            reasons.append(('tpm_window', max(1.0, wait)))
            continue
        return channel
    if not reasons:
        raise ChannelUnavailable('no channels configured', 'no_channels', 3600)
    # a channel the request fits but that is busy/dead explains the wait; "too big" only when NO channel fits
    fitting = [r for r in reasons if r[0] != 'reservation_exceeds_tpm'] or reasons
    reason, wait = min(fitting, key=lambda r: r[1])
    raise ChannelUnavailable('no channels currently available: ' + reason, reason, wait)


def next_wait(channel_list, state, tokens, env, *, now=None, requests=1):
    """Seconds until the SOONEST of ``channel_list`` can take the next call (0 when one can now);
    None when there are no channels at all."""
    if not channel_list:
        return None
    waits = []
    for channel in channel_list:
        try:
            choose([channel], state, tokens, env, now=now, requests=requests)
            return 0.0
        except ChannelUnavailable as error:
            waits.append(error.wait_s)
    return min(waits)


def reserve(state, channel, tokens, *, now=None, requests=1):
    """Book ``tokens`` and ``requests``; returns the booking timestamp for reconcile().

    The contract with choose(): the day window gets the whole run (at most rpd), the minute window only what
    fits one minute (at most rpm). reconcile() later replaces both with the fact."""
    now = time.time() if now is None else now
    group = state.setdefault(channel['group'], {})
    day = int(now // 86400)
    if group.get('day') != day:
        group.update(day=day, requests=0)
    times = [t for t in group.get('request_times', []) if now - t < 86400]
    minute_times = [t for t in _numbers(group.get('rpm_times')) if now - t < 60]
    while now in times or now in minute_times or any(t == now for t, _ in group.get('minute', [])):
        now += 1e-6                                  # a booking is identified by its timestamp: keep it unique
    per_day = max(0, min(requests, channel['rpd']))
    per_minute = max(0, min(requests, channel['rpm'])) if channel.get('rpm') else per_day
    group['requests'] = group.get('requests', 0) + per_day
    group['request_times'] = times + [now] * per_day
    group['rpm_times'] = minute_times + [now] * per_minute
    group['minute'] = [(t, n) for t, n in group.get('minute', []) if now - t < 60] + [(now, tokens)]
    return now


def headroom(channels, state, tokens, env, *, now=None, requests=1, cap=16) -> int:
    """How many first calls choose()+reserve() could book right now on ``channels`` (a deep copy of ``state``: nothing
    is booked). The pool admits one more worker only while this exceeds the workers that have not booked yet."""
    work = copy.deepcopy(state)
    now = time.time() if now is None else now
    found = 0
    while found < cap:
        try:
            pick = choose(channels, work, tokens, env, now=now, requests=requests)
        except ChannelUnavailable:
            break
        reserve(work, pick, tokens, now=now, requests=requests)
        found += 1
    return found


def reconcile(state, channel, at, reserved, actual, *, requests=1, actual_requests=None):
    """Replace the booking made at ``at`` with the fact of the call.

    ``actual`` = input tokens the provider counted (sum over steps); ``actual_requests`` = real requests (steps,
    retries included). Less than booked returns the surplus; MORE than booked is added (an overrun is counted)."""
    group = state.get(channel['group'])
    if not group:
        return
    minute = group.get('minute', [])
    for i, (t, n) in enumerate(minute):
        if t == at and n == reserved:
            minute[i] = (t, max(0, int(actual)))
            break
    if actual_requests is None:
        return
    fact = max(0, int(actual_requests))
    for key in ('request_times', 'rpm_times'):
        times = group.setdefault(key, [])
        booked = times.count(at)
        if fact < booked:
            for _ in range(booked - fact):
                times.remove(at)
        else:
            times.extend([at] * (fact - booked))
        if key == 'request_times':
            group['requests'] = max(0, group.get('requests', 0) + fact - booked)


def cool(state, channel, *, now=None, seconds=DEFAULT_COOL_S):
    """Cool the whole quota group; never shortens a longer cooling."""
    now = time.time() if now is None else now
    group = state.setdefault(channel['group'], {})
    group['cool_until'] = max(group.get('cool_until', 0), now + max(1, seconds))


# ---- error classification ---------------------------------------------------------------------

_KEY_TEXT = re.compile(r'api[_ ]?key[_ ]?(?:is )?(?:not )?invalid|api key not valid|invalid api key', re.I)
_REGION_TEXT = re.compile(r'location is not supported|not available in your (?:country|region)', re.I)
_PERDAY = re.compile(r'PerDay|per[ -]day|daily', re.I)
_PERMIN = re.compile(r'PerMinute|per minute', re.I)
_RETRY = re.compile(r'retryDelay"?\s*[:=]\s*"?(\d+(?:\.\d+)?)s', re.I)
_STATUS_TEXT = re.compile(r'\b(?:HTTP(?:/\d(?:\.\d)?)?|status(?:Code)?|code)\D{0,3}([45]\d\d)\b(?!:\d)', re.I)  # never bare numbers: stack lines are file.js:429:15


def _nth_sunday(year: int, month: int, n: int) -> datetime.date:
    day = datetime.date(year, month, 1)
    day += datetime.timedelta(days=(6 - day.weekday()) % 7)  # first Sunday
    return day + datetime.timedelta(weeks=n - 1)


def pacific_offset_hours(utc: datetime.datetime) -> int:
    """UTC-7 during US daylight time (2nd Sunday of March 02:00 local .. 1st Sunday of November
    02:00 local), UTC-8 otherwise. No tzdata needed (it is absent from the factory venv)."""
    start = datetime.datetime.combine(_nth_sunday(utc.year, 3, 2), datetime.time(10, 0))  # 02:00 PST = 10:00 UTC
    end = datetime.datetime.combine(_nth_sunday(utc.year, 11, 1), datetime.time(9, 0))    # 02:00 PDT = 09:00 UTC
    return -7 if start <= utc.replace(tzinfo=None) < end else -8


def _day_offset_hours(model, utc: datetime.datetime) -> int:
    """Hours from UTC of the clock whose midnight resets the daily quota of ``model``'s provider."""
    return 0 if str(model or '').split('/')[0] in UTC_DAY_PROVIDERS else pacific_offset_hours(utc)


def quota_day(model=None, now=None) -> tuple:
    """(start, end) of the provider's current quota day, epoch seconds; ``model`` None: midnight Pacific."""
    now = time.time() if now is None else now
    utc = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(tzinfo=None)
    local = utc + datetime.timedelta(hours=_day_offset_hours(model, utc))
    since = (local - datetime.datetime.combine(local.date(), datetime.time(0, 0))).total_seconds()
    return now - since, now - since + 86400


def seconds_to_daily_reset(now=None, model=None) -> int:
    """Seconds until the daily quota reset of ``model``'s provider: midnight Pacific for Gemini
    (https://ai.google.dev/gemini-api/docs/rate-limits), 00:00 UTC for OpenRouter."""
    now = time.time() if now is None else now
    return max(60, int(quota_day(model, now)[1] - now))


def _reset_at(body, now):
    """The epoch second the provider names for the reset of the exhausted limit (OpenRouter: metadata.headers
    X-RateLimit-Reset, in ms), or None when absent or not believable (past, or further than DAY_RESET_MAX_S)."""
    value = _find(body, 'X-RateLimit-Reset')
    if value is None:
        value = _find(body, 'x-ratelimit-reset')
    try:
        at = float(value)
    except (TypeError, ValueError):
        return None
    if at > 1e11:              # milliseconds
        at /= 1000.0
    return at if 0 < at - now <= DAY_RESET_MAX_S else None


def _walk_details(body):
    quota, retry = [], None
    error = body.get('error') if isinstance(body, dict) else None
    for item in (error or {}).get('details', []) or []:
        if not isinstance(item, dict):
            continue
        for violation in item.get('violations', []) or []:
            if isinstance(violation, dict) and violation.get('quotaId'):
                quota.append(str(violation['quotaId']))
        if item.get('retryDelay'):
            m = re.match(r'(\d+(?:\.\d+)?)s', str(item['retryDelay']))
            if m:
                retry = float(m.group(1))
    return quota, retry


def _find(obj, key, depth=0):
    """First value of ``key`` anywhere inside a parsed event (nested dicts/lists), else None."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        children = obj.values()
    elif isinstance(obj, list):
        children = obj
    else:
        return None
    for child in children:
        found = _find(child, key, depth + 1)
        if found is not None:
            return found
    return None


def _info(kind, status=None, name='', message='', retry=None, quota=''):
    return {'kind': kind, 'status': status, 'name': str(name)[:80], 'message': str(message)[:300],
            'retry_after_s': retry, 'quota': quota[:120]}


def _classify_error_event(error: dict):
    data = error.get('data') if isinstance(error.get('data'), dict) else {}
    name = str(error.get('name', ''))
    status = data.get('statusCode') if type(data.get('statusCode')) is int else None
    message = str(data.get('message', '') or error.get('message', ''))
    raw_body = data.get('responseBody')
    body = None
    if isinstance(raw_body, str):
        try:
            body = json.loads(raw_body)
        except ValueError:
            body = None
    elif isinstance(raw_body, dict):
        body = raw_body
    text = ' '.join(str(x) for x in (message, raw_body if isinstance(raw_body, str) else json.dumps(body or {})))
    if status is None and isinstance(body, dict) and type(body.get('error', {}).get('code')) is int:
        status = body['error']['code']
    quota, retry = _walk_details(body)
    quota_text = ' '.join(quota) or text
    if _REGION_TEXT.search(text) or status == 403:
        return _info('region', status, name, message)
    if status == 401 or _KEY_TEXT.search(text) or 'API_KEY_INVALID' in text:
        return _info('key_invalid', status, name, message)
    if status == 402:
        # OpenRouter says which budget: in-flight (wait and retry), weight (this task is too big), or the balance
        source = str(_find(body, 'limit_source') or '').lower()
        if 'in_flight' in source:
            return _info('rate_minute', status, name, message, math.ceil(retry) if retry else DEFAULT_COOL_S)
        if 'weight_exceeds' in source:
            return _info('too_big', status, name, message)
        return _info('balance', status, name, message)
    if status == 404:
        return _info('model_missing', status, name, message)
    if status == 408:
        return _info('transient', status, name, message)
    if status == 429:
        if _PERDAY.search(quota_text):
            now = time.time()
            at = _reset_at(body, now)
            info = _info('rate_day', status, name, message,
                         math.ceil(at - now) if at else seconds_to_daily_reset(now), quota_text)
            if at:
                info['reset_at'] = at
            return info
        wait = math.ceil(retry) if retry else DEFAULT_COOL_S
        info = _info('rate_minute', status, name, message, wait, quota_text)
        if _find(body, 'provider_code') is not None:       # the UPSTREAM provider of one model, not the account
            info['scope'] = 'model'
        return info
    if status is None and name == 'EmptyAnswer':
        # HTTP 200 and no answer: the model spent its whole output limit (on reasoning); the model, not the account
        return _info('transient', None, name, message)
    if status is None and name == 'NetworkError':
        # no HTTP answer at all (the light engine): the machine's network, the same for every channel; the
        # runner counts it towards the brake instead of postponing one task for ever (critic 19.11)
        return _info('network', None, name, message)
    if (status is not None and status >= 500) or (status is None and name == 'APIError'):
        return _info('transient', status, name, message)
    return _info('other', status, name, message)


def classify(stdout: bytes, stderr: bytes, rc: int, idle: bool = False) -> dict:
    """Class of a finished call: ok | key_invalid | region | rate_minute | rate_day | transient | network
    | too_big | timeout | launcher | other | unknown. ``retry_after_s`` is the cooling the provider asked for.
    ``idle``: the worker did nothing visible (no step, no tool). Kilo retries a 429 by itself and sleeps by
    retry-after (<id>), so a timeout of an idle worker is a rate limit in disguise, not a worker fault."""
    if rc == 124:
        if idle:
            info = _info('rate_minute', None, 'RetryStall', 'Kilo slept inside the call: rate limited?',
                         RATE_SUSPECT_COOL_S)
            info['suspect'] = True
            return info
        return _info('timeout', message='worker-timeout')
    if rc == 125:
        return _info('launcher', message=stderr.decode('utf-8', 'replace')[:200])
    for line in stdout.decode('utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('type') == 'error' and isinstance(event.get('error'), dict):
            return _classify_error_event(event['error'])
    last = None                 # an error AFTER the stream started (HTTP 200) counts only when it is the LAST step
    for line in stdout.decode('utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('type') == 'step_finish' and isinstance(event.get('part'), dict):
            last = event['part']
    if last is not None and last.get('reason') == 'error':
        err = last.get('error') if isinstance(last.get('error'), dict) else {}     # the provider's error object only
        meta = err.get('metadata') if isinstance(err.get('metadata'), dict) else {}
        code = err.get('code') if type(err.get('code')) is int else None
        if meta.get('provider_code') is not None or code == 429:
            info = _info('rate_minute', 429, 'StreamError', 'error after the stream started', DEFAULT_COOL_S)
            if meta.get('provider_code') is not None:
                info['scope'] = 'model'
            return info
        return _info('transient', code, 'StreamError', 'error after the stream started')
    if rc == 0:
        return _info('ok')
    # No structured error: only stderr (never stdout) may be read as error text.
    text = stderr.decode('utf-8', errors='replace')[-2000:]
    if _REGION_TEXT.search(text):
        return _info('region', message=text)
    if _KEY_TEXT.search(text):
        return _info('key_invalid', message=text)
    m = _STATUS_TEXT.search(text)
    status = int(m.group(1)) if m else None
    if status == 429 or re.search(r'rate.?limit|resource[_ ]exhausted', text, re.I):
        return _info('rate_day' if _PERDAY.search(text) else 'rate_minute', 429, message=text,
                     retry=seconds_to_daily_reset() if _PERDAY.search(text) else DEFAULT_COOL_S)
    if status in (401, 403):
        return _info('region' if status == 403 else 'key_invalid', status, message=text)
    if status == 402:
        return _info('balance', status, message=text)
    if status == 404:
        return _info('model_missing', status, message=text)
    if status == 408:
        return _info('transient', status, message=text)
    if status is not None and status >= 500:
        return _info('transient', status, message=text)
    return _info('unknown', message=text)


def apply_failure(state, channel, info, *, env=None, now=None) -> dict:
    """Record a channel/provider failure in the checkpoint quota state. Returns what was done."""
    now = time.time() if now is None else now
    env = env or {}
    kind = info.get('kind')
    if kind == 'key_invalid':
        state.setdefault('dead', {})[channel['id']] = {'key': _fingerprint(env, channel), 'since': now,
                                                       'reason': 'key_invalid'}
        return {'action': 'dead', 'cool_s': 0}
    if kind == 'model_missing':   # one 404 must not kill the channel for good: dead for 6 h, then probed again
        state.setdefault('dead', {})[channel['id']] = {'key': _fingerprint(env, channel), 'since': now,
                                                       'reason': 'model_missing',
                                                       'until': now + MODEL_MISSING_TTL_S}
        return {'action': 'dead', 'cool_s': 0}
    if kind == 'balance':
        cool(state, channel, now=now, seconds=BALANCE_COOL_S)
        return {'action': 'cool', 'cool_s': BALANCE_COOL_S}
    if kind == 'region':
        cool(state, channel, now=now, seconds=REGION_COOL_S)
        return {'action': 'cool', 'cool_s': REGION_COOL_S}
    if kind in ('rate_minute', 'rate_day'):
        seconds = _day_cool(channel, info, now) if kind == 'rate_day' else int(info.get('retry_after_s') or DEFAULT_COOL_S)
        if info.get('scope') == 'model':     # an upstream provider of ONE model: the rest of the account is fine
            return _cool_model(state, channel, now, seconds)
        cool(state, channel, now=now, seconds=seconds)
        return {'action': 'cool', 'cool_s': seconds}
    if kind == 'transient' and (info.get('status') in OVERLOAD_STATUSES or info.get('name') == 'EmptyAnswer'):
        # "This model is currently experiencing high demand" (503): the MODEL is overloaded, not the account. Cooled,
        # the retry and the next pass take another channel (live 19.11 18:18-18:20: two passes were deferred on a
        # 503 of gemini-3.5-flash-lite while three other channels idled).
        return _cool_model(state, channel, now, _overload_seconds(state, channel['model'], now))
    return {'action': 'none', 'cool_s': 0}


def _day_cool(channel, info, now) -> int:
    """Cooling of a daily 429: until the reset time the provider named, else until the midnight of the channel's
    provider; in the first DAY_GRACE_S of the provider's day without a named reset only DAY_GRACE_COOL_S."""
    at = info.get('reset_at')
    if isinstance(at, (int, float)) and not isinstance(at, bool) and 0 < at - now <= DAY_RESET_MAX_S:
        return int(math.ceil(at - now))
    start, end = quota_day(channel['model'], now)
    if now - start < DAY_GRACE_S:
        return DAY_GRACE_COOL_S
    return max(60, int(end - now))


def _overload_seconds(state, model, now) -> int:
    """OVERLOAD_COOL_S, doubled for every further overload of the same model within OVERLOAD_FORGET_S of the
    previous one, at most OVERLOAD_COOL_MAX_S."""
    if not isinstance(state.get('model_overload'), dict):
        state['model_overload'] = {}
    table = state['model_overload']
    last = _numbers(table.get(model))
    series = int(last[0]) + 1 if len(last) == 2 and 0 <= now - last[1] < OVERLOAD_FORGET_S else 1
    table[model] = [series, now]
    return min(OVERLOAD_COOL_MAX_S, OVERLOAD_COOL_S * 2 ** min(series - 1, 8))


def _cool_model(state, channel, now, seconds) -> dict:
    """Cool one MODEL (every channel of it) for ``seconds``; the account and the other models stay usable."""
    if not isinstance(state.get('model_cool'), dict):
        state['model_cool'] = {}
    models = state['model_cool']
    models[channel['model']] = max(models.get(channel['model'], 0), now + max(1, seconds))
    return {'action': 'cool_model', 'cool_s': seconds}
