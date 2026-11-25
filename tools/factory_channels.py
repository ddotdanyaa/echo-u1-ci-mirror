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
import logging
import math
import logging
import statistics
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
# W-503 (live 23.11: 7 % of the calls of two healthy Gemini models answered 503, and every single one cooled the model on
# BOTH keys for 120 s, doubling to 900 s: 24 channels were closed at 15:50 with 484 of 2000 requests spent). A 503 is
# an overload only when it repeats: the series counts the model's 503s in a row with no success between them (a success
# of ANY process ends it, model_ok in the shared quota section). The first one cools only that channel for 5 s (the
# other key stays open), the second the model for 15 s, then 30, 60, 120 -- at most 120 s for a model with at least half
# good calls among its recent ones; the others (Gemma now) keep the old 120..300 (900) rule.
OVERLOAD_STEPS = (5, 15, 30, 60, 120)
OVERLOAD_RETRY_S = (5, 15)     # a call with no free channel left asks the same channel again after these pauses
OPEN_SOON_S = 30               # a channel that opens within this many seconds counts as free for the pool's headroom
# A channel whose last STREAK_FAILS calls all failed (any kind, the hours between them do not matter) is cooled for
# STREAK_COOL_S, doubled for every further failure of the series, at most STREAK_COOL_MAX_S; a successful call ends the
# series (live 20.11: g-gemma-4-31b failed 9 calls in a row over 5 h, 1317 s went into calls after 3 failures in a row)
STREAK_FAILS = 3
STREAK_COOL_S = 600
STREAK_COOL_MAX_S = 3600       # 21.11 (was 14400)
# Reliability of a model (recent calls, from note_outcome): the last RATING_WINDOW outcomes of all its channels; fewer than
# RATING_MIN of them say nothing (healthy). A model below RATING_BAD goes last within its tier, and a sticky choice never
# keeps it. A channel whose last MISSING_STREAK calls all answered 404 is skipped until its config changes.
RATING_WINDOW = 20
RATING_MIN = 5
RATING_BAD = 0.5
RATING_SHAKY = 0.8
MISSING_STREAK = 3
# Steps of one task, and tasks of one module family, prefer the key+model they used last while it has room
# (fewer key switches, and Gemini's implicit prompt cache stays warm); the memory is forgotten after this long.
AFFINITY_TTL_S = 1800
AFFINITY_MAX = 200
SMALL_PROMPT_TOKENS = 6000
DRY_SMALL_TOKENS = 12000       # W-gemma 3: with every main channel closed by the day's mark Gemma takes a card this big
SMALL_FIRST_TIMEOUT_S = 30
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
# A daily 429 is a mark until the next PROBE, not until the reset (live 23.11 08:50: 18 channels stood cooled until
# 11:00 while three of the models answered 200 on both keys): 10 minutes, then 20, 40, at most 60 and never past the
# reset. The expired mark lets ONE call through (the probe); the others wait for its outcome; 200 clears the mark and
# the series, a daily 429 sets the next, longer mark.
DAY_PROBE_S = 600
DAY_PROBE_MAX_S = 3600
DAY_PROBE_HOLD_S = 300         # how long the others wait for a probe that has not answered
DAY_PROBE_FORGET_S = 4 * 3600  # a series whose last mark ended this long ago starts again
# A channel with a big daily allowance is never parked for long by a series of failures or a 503: its cooling is at
# most HIGH_RPD_COOL_MAX_S and the series does not count higher than that (live 23.11: Gemma, 14400 a day, made
# 10 calls in 80 minutes).
HIGH_RPD = 1000
HIGH_RPD_COOL_MAX_S = 300
# W-gemma 3: a small-tier channel with a big daily allowance (Gemma) has no series of failures at all; its timeout closes
# it BIG_TIMEOUT_CLOSE_S, and a mark of it that is longer than BIG_MARK_CAP_S (any old streak / suspect / overload mark)
# is cut to that when read -- daily marks (day_probe), a dead key and a balance mark stay
BIG_TIMEOUT_CLOSE_S = 10
BIG_MARK_CAP_S = 20
# W-gemma 1: a 503 of a big-quota model (Gemma: 35 % of the calls succeed, a refusal comes in 1 s and costs no quota) cools
# neither the model nor the key. The call hops to the next channel of the circle (BIG_HOP_PAUSE_S), up to BIG_SENDS_MAX
# sends, then BIG_ROUNDS more rounds (one circle each) after BIG_ROUND_PAUSE_S; only then the last channel is closed
# for BIG_CLOSE_S. The roles below only; the answer limit of a Gemma call is BIG_TIMEOUT_S when no main channel is free.
# 'code' is intentional: repair and unit_test cards call the model under the role 'code', so it cannot be told apart from them;
# it is wider than edit/repair/review/unit_test only while every main channel is closed (gemma_first needs main_dry).
BIG_ROLES = ('edit', 'review', 'repair', 'unit_test', 'code')
BIG_SENDS_MAX = 8
BIG_HOP_PAUSE_S = 2
BIG_ROUNDS = 3
BIG_ROUND_PAUSE_S = 15
BIG_CLOSE_S = 20
BIG_TIMEOUT_S = 90


class ChannelUnavailable(InvalidPlan):
    """Temporary quota exhaustion, not a bad task or scope violation."""

    def __init__(self, message='no channels currently available', reason='unavailable', wait_s=60.0):
        super().__init__(message)
        self.reason = reason
        self.wait_s = float(wait_s)


# Russian text is 2-3x more tokens per char than English (a Cyrillic word splits into many pieces): 3.5 chars a
# token is the Latin rate, about 1.4 is the Cyrillic one (<id>: a Russian file broke the 16K TPM window of Gemma).
CYRILLIC_CHARS_PER_TOKEN = 1.4
# Output limits per model family (<id>); a model that is not listed has the caller's default. Gemma 4 spends its
# output limit on reasoning, so its answer is capped lower and a cut answer is never judged.
MODEL_MAX_OUTPUT = (('google/gemma-4', 4096),)


def max_output_for(model, default: int) -> int:
    for prefix, limit in MODEL_MAX_OUTPUT:
        if str(model or '').startswith(prefix):
            return min(default, limit)
    return default


# Body fields added to EVERY HTTP call of a model (live 23-24.11: Gemma 4 without it spends the whole output limit on
# reasoning, 87 s, no answer; 'minimal' on the same /v1beta/openai address answers in ~24 s). 'none' is refused (400
# "Thinking budget is not supported"), 'minimal' is accepted.
MODEL_BODY = (('google/gemma-4', {'reasoning_effort': 'minimal'}),)
_BODY_OFF: set = set()      # model prefixes whose field the API refused: off until the process ends


def body_extra(model) -> dict:
    """A copy of the extra body fields of ``model`` (empty for a model without a row or with the field switched off)."""
    for prefix, extra in MODEL_BODY:
        if str(model or '').startswith(prefix):
            return {} if prefix in _BODY_OFF else copy.deepcopy(extra)
    return {}


def _refused_field(status, raw) -> bool:
    text = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else str(raw or '')
    return status == 400 and ('reasoning_effort' in text or 'Thinking' in text)


def post_with_extra(post, url, key, body, timeout, model):
    """``post(url, key, body, timeout)`` with the model's extra fields in the body. A 400 naming the field is
    retried once without it and the field is off for this model until the process ends. ``body`` is not changed.
    Returns ``(status, raw, sent)``: ``sent`` is the extra dict actually sent in the answered call."""
    extra = body_extra(model)
    if not extra:
        status, raw = post(url, key, body, timeout)
        return status, raw, {}
    status, raw = post(url, key, {**body, **extra}, timeout)
    if _refused_field(status, raw):
        for prefix, _ in MODEL_BODY:
            if str(model or '').startswith(prefix):
                _BODY_OFF.add(prefix)
        status, raw = post(url, key, body, timeout)
        return status, raw, {}
    return status, raw, extra


def cyrillic_share(text) -> float:
    """Share of the letters of ``text`` that are Cyrillic (0.0 for no letters)."""
    letters = [c for c in str(text or '') if c.isalpha()]
    if not letters:
        return 0.0
    return sum('Ѐ' <= c <= 'ӿ' for c in letters) / len(letters)


def estimate_tokens(prompt_chars: int, read_chars: int = 0, overhead: int | None = None, cyrillic: float = 0.0) -> int:
    """INPUT tokens of ONE request: the prompt + the files the model will read with its tool (chars / 3.5, or
    / 1.4 for the ``cyrillic`` share of them) + the engine overhead: Kilo's system prompt and tool schemas by
    default, ``overhead`` for the light engine (one REST request, no tools). TPM counts input tokens only (see
    the module docstring), so the answer is not booked."""
    share = min(1.0, max(0.0, cyrillic))
    per_char = (1 - share) / CHARS_PER_TOKEN + share / CYRILLIC_CHARS_PER_TOKEN
    chars = max(0, prompt_chars) + max(0, read_chars)
    return math.ceil(chars * per_char) + (KILO_OVERHEAD_TOKENS if overhead is None else max(0, overhead))


def prompt_too_big(prompt) -> bool:
    """A prompt over PROMPT_LIMIT_CHARS Latin characters of weight: Cyrillic text weighs 3.5 / 1.4 = 2.5 times more
    per character (D #23), so its share shortens the limit."""
    # live 22.11 00:05-00:20: the weighted limit blocked 22-25 k character prompts (context_too_large, 5 blocks in 15 min)
    # that passed before; the Cyrillic weight already decides WHICH channel fits (estimate_tokens in the router), so the
    # hard ceiling stays in plain characters.
    return len(str(prompt or '')) > PROMPT_LIMIT_CHARS


prompt_too_large = prompt_too_big

# OpenRouter models that take the unified ``reasoning`` field (D #24; supported_parameters of the model list, 21.11);
# a model that is not listed gets no field, the provider may refuse an unknown parameter.
REASONING_MODELS = ('openrouter/nvidia/nemotron', 'openrouter/google/gemma', 'openrouter/inclusionai/',
                    'openrouter/baidu/', 'openrouter/thinkingmachines/', 'openrouter/recursive/',
                    'openrouter/dots-studio/', 'openrouter/cohere/', 'openrouter/particle-ai/')


def supports_reasoning(model) -> bool:
    return str(model or '').startswith(REASONING_MODELS)


def validate(channels, warn=True):
    """Validate the pool and return it without the rows of unsupported providers (a warning per row when
    ``warn``). The list passed in is not changed: the registry file keeps every row."""
    # Imported at call time: the runner itself imports this module.
    from .agent_factory_runner import LIGHT_ENDPOINTS

    accepted = []
    seen = set()
    for channel in channels:
        provider = channel['model'].split('/')[0]
        if MODEL_ID.fullmatch(channel['model']) and provider not in LIGHT_ENDPOINTS:
            if warn:
                logging.getLogger(__name__).warning('Skipping unsupported channel provider: %s', provider)
            continue
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
        accepted.append(channel)
    groups = {}
    for c in accepted:
        limits = (c['tpm'], c['rpd'], c.get('rpm'))
        if c['group'] in groups and groups[c['group']] != limits:
            raise InvalidPlan('shared quota group has inconsistent limits')
        groups[c['group']] = limits
    return accepted


def tier_of(channel) -> str:
    return channel.get('tier', 'main')


_ROLE_TIERS = {   # candidate order of tiers for a call; a tier that is not listed is not used for that role
    ('code', 1): ('main', 'small', 'escalation'),
    ('code', 2): ('escalation', 'main'),
    ('edit', 1): ('small', 'main'),
    ('edit', 2): ('main', 'escalation'),
    'architect': ('escalation', 'main'),   # the strong tier's quota is small: when it is spent the architect goes to the main tier
    'review': ('small', 'main', 'escalation'),
    'cross_review': ('main', 'small', 'escalation'),
}


# W-path C: no fixed floor: a main channel takes an edit only while its unused share of the day is at least the share of the quota day that is left (day_left_share >= time_left_share): surplus is spent, nothing is left over at the end of the day


def note_edit_outcome(state, tier, green, seconds, now=None):
    """Keep a rolling experiment, evaluating every thirty cards or two hours."""
    now = time.time() if now is None else now
    experiment = state.setdefault('edit_experiment', {})
    samples = experiment.setdefault('samples', {})
    bucket = samples.setdefault(tier, [])
    bucket.append([bool(green), max(0, seconds)])
    del bucket[:-30]
    experiment['pending'] = experiment.get('pending', 0) + 1
    totals = experiment.setdefault('totals', {})
    totals[tier] = totals.get(tier, 0) + 1                  # the window below is cut to 30; the count is not
    state['edit_by_tier'] = {t: {'cards': totals.get(t, len(rows)), 'green': sum(r[0] for r in rows),
                                'median_s': statistics.median(r[1] for r in rows), 'window': len(rows)}
                             for t, rows in samples.items() if rows}
    small, main = (state['edit_by_tier'].get(t, {}) for t in ('small', 'main'))
    if small.get('window', 0) < 30 or not main.get('window'):
        return None
    if experiment['pending'] < 30 and now - experiment.get('checked_at', 0) < 7200:
        return None
    experiment.update(pending=0, checked_at=now)
    worse = (small['green'] / small['window'] < .7 * main['green'] / main['window']
             or small['median_s'] > 1.5 * main['median_s'])
    route = 'small_second' if worse else 'small_first'
    prior = state.get('edit_route', 'small_first')
    state['edit_route'] = route
    return dict(status=route, small=dict(small), main=dict(main)) if route != prior else None


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


def _config_tag(channel) -> str:
    """Identifies the channel's configuration: a changed registry entry (model, key name, limits) is a new tag."""
    return hashlib.sha256(json.dumps(channel, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]


def _stats(state, channel) -> dict:
    """The reliability record of one channel (kept in the checkpoint beside the quotas, so it survives a restart)."""
    table = state.get('channel_stats')
    if not isinstance(table, dict):
        table = state['channel_stats'] = {}
    row = table.get(channel['id'])
    if not isinstance(row, dict):
        row = table[channel['id']] = {}
    tag = _config_tag(channel)
    if row.get('config') != tag:     # the registry entry changed: what was learned about the old one does not apply
        row.clear()
        row['config'] = tag
    row['model'] = channel['model']
    if not isinstance(row.get('results'), list):
        row['results'] = []
    if type(row.get('missing')) is not int:
        row['missing'] = 0
    return row


def rating(state, model) -> float:
    """Share of successful calls among the recent ones of ``model`` (all its channels); 1.0 until RATING_MIN calls are known."""
    table = state.get('channel_stats') if isinstance(state, dict) else None
    results = []
    for row in (table.values() if isinstance(table, dict) else ()):
        if isinstance(row, dict) and row.get('model') == model:
            results.extend(r for r in (row.get('results') or []) if r in (0, 1) and type(r) is int)
    if len(results) < RATING_MIN:
        return 1.0
    return sum(results) / len(results)


def tier_rating(state, channels, tier) -> float:
    """Share of good calls among the recent ones of every model of ``tier`` together; 1.0 until RATING_MIN are known."""
    models = {c['model'] for c in channels if tier_of(c) == tier}
    table = state.get('channel_stats') if isinstance(state, dict) else None
    results = []
    for row in (table.values() if isinstance(table, dict) else ()):
        if isinstance(row, dict) and row.get('model') in models:
            results.extend(r for r in (row.get('results') or []) if r in (0, 1) and type(r) is int)
    if len(results) < RATING_MIN:
        return 1.0
    return sum(results) / len(results)


def missing_for_good(state, channel) -> bool:
    """The last MISSING_STREAK calls of this channel all answered 404 and its config is unchanged since."""
    table = state.get('channel_stats') if isinstance(state, dict) else None
    row = table.get(channel['id']) if isinstance(table, dict) else None
    return (isinstance(row, dict) and row.get('config') == _config_tag(channel)
            and type(row.get('missing')) is int and row['missing'] >= MISSING_STREAK)


def route_order(channels, role, attempt, tokens, *, preferred=None, exclude_model=None, skip_tiers=(), state=None,
                later=False, env=None, now=None):
    """Channels in the order a call tries them. Coder, attempt 1: main, small (only when ``tokens`` fit its tpm),
    escalation; attempt 2 and later: escalation, main. Reviewer: small first; cross-review: main first.
    ``exclude_model`` (the coder's model) never reviews its own work; a collection of models excludes them all (the
    tournament's next candidate and the chain's next critic are other models). ``preferred`` breaks ties in a tier.
    ``skip_tiers``: tiers this call may not use (<id> small_follow_up 'off': no small-tier model as a later
    tournament candidate). ``state`` (the quota state): inside a tier the models that keep failing go last, the
    rest follow the live reliability rating (``preferred`` first among equals), and a channel that answers 404 on
    every call is left out until its config changes. ``later``: a later candidate of one tournament (<id>): the
    earlier one already spent part of the same minute, so the small tier needs room for two runs.
    Unknown roles fall back to the first code route and log a warning."""
    key = (role, 1 if attempt <= 1 else 2) if role in ('code', 'edit') else role
    if key not in _ROLE_TIERS:
        logging.getLogger(__name__).warning('Unknown factory role %s; using code attempt 1', role)
    ranks = _ROLE_TIERS.get(key, _ROLE_TIERS[('code', 1)])
    if role == 'edit' and attempt <= 1 and state and state.get('edit_route') == 'small_second':
        ranks = ('main', 'small')
    # W-gemma 3: every main channel is closed by the day's mark: Gemma is the only free executor and goes FIRST for the
    # edit, repair, review and unit_test calls, whatever its rating, and a card up to DRY_SMALL_TOKENS is let in (the
    # runner cuts a longer one to the part's region)
    gemma_first = (state is not None and role in ('edit', 'code', 'review') and main_dry(channels, state, env, now=now))
    if gemma_first:
        ranks = ('small',) + tuple(t for t in ranks if t != 'small')
    small_cap = DRY_SMALL_TOKENS if gemma_first else SMALL_PROMPT_TOKENS
    if (state is not None and not gemma_first and ranks and ranks[0] == 'small'
            and (role == 'review' or (role == 'edit' and attempt <= 1))
            and (tokens > SMALL_PROMPT_TOKENS or tier_rating(state, channels, 'small') < RATING_BAD)):
        # W-503: the small tier (Gemma) leads only a SHORT review or edit while at least half of its recent calls were
        # good (live 23.11: 10 ok of 45+17 failed calls); otherwise it comes after the main tier
        ranks = tuple(t for t in ranks if t != 'small')
        at = ranks.index('main') + 1 if 'main' in ranks else 0
        ranks = ranks[:at] + ('small',) + ranks[at:]
    excluded = excluded_models(exclude_model)
    picked = []
    for channel in channels:
        tier = tier_of(channel)
        if tier not in ranks or tier in skip_tiers or channel['model'] in excluded:
            continue
        if tier == 'small' and role == 'edit' and tokens > small_cap:
            continue
        if tier == 'small' and role != 'edit' and small_minute_need(tokens, channel) * (2 if later else 1) > channel['tpm']:    # Gemma only when a minute of it fits
            if not (gemma_first and tokens <= small_cap):   # (a single light request waits for the window in choose())
                continue
        if state is not None and missing_for_good(state, channel):
            continue
        if (state is not None and role == 'edit' and tier == 'main' and tokens <= small_cap
                and day_left_share(state, channel, now=now) < time_left_share(channel, now=now)):
            continue
        picked.append(channel)
    if state is None:
        return sorted(picked, key=lambda c: (ranks.index(tier_of(c)), c['model'] != preferred))
    def live(c):
        r = rating(state, c['model'])
        # a model that fails often (503s after its cooling ended) is behind the healthy ones even when preferred (D #25)
        return (ranks.index(tier_of(c)), r < RATING_BAD, r < RATING_SHAKY, c['model'] != preferred, -round(r, 1))
    return sorted(picked, key=live)


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


def _dead_applies(dead, env, channel) -> bool:
    """A dead mark is bound to the key it was made for and, when it carries one, to the channel's config."""
    return (dead.get('key') == _fingerprint(env, channel)
            and dead.get('config') in (None, _config_tag(channel)))


def usable(channels, state, env, *, now=None):
    """The channels that can ever take a call now: a key is set and no dead mark for that key is in force."""
    now = time.time() if now is None else now
    live = []
    for channel in channels:
        dead = state.get('dead', {}).get(channel['id'])
        if dead and _dead_applies(dead, env, channel):
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


def overload_healthy(state, model) -> bool:
    """At least half of the model's recent calls were good (or too few are known): its 503s are single hiccups."""
    return rating(state, model) >= RATING_BAD


def _model_cool(state, channel, now=None) -> float:
    table = state.get('model_cool')
    value = table.get(channel['model']) if isinstance(table, dict) else None
    if not (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return 0.0
    now = time.time() if now is None else now
    model = channel['model']
    if _big_daily(channel):
        # W-gemma 1: a 503 no longer cools a big-quota model: a mark of the old overload rules (recorded as such, or
        # born from the model's last overload with no source) is dropped when read; probes and failure series stay
        sources = state.get('model_cool_src')
        runs = state.get('model_overload')
        last = _numbers(runs.get(model)) if isinstance(runs, dict) else []
        probes = state.get('day_probe')
        if not (isinstance(probes, dict) and 'model:' + str(model) in probes):
            if isinstance(sources, dict) and sources.get(model) == 'overload':
                return 0.0
            if (not (isinstance(sources, dict) and model in sources) and len(last) == 2
                    and 0 <= value - last[1] <= OVERLOAD_COOL_MAX_S + 1):
                return 0.0
    if value > now + OVERLOAD_STEPS[-1]:
        # a mark made by the old overload rule (no source recorded, born from the model's last 503, up to 900 s) is cut
        # to the new limit when it is read; marks of daily quotas, probes and series of failures stay
        sources = state.get('model_cool_src')
        runs = state.get('model_overload')
        last = _numbers(runs.get(model)) if isinstance(runs, dict) else []
        probes = state.get('day_probe')
        if (not (isinstance(sources, dict) and model in sources) and len(last) == 2
                and 0 <= value - last[1] <= OVERLOAD_COOL_MAX_S + 1
                and not (isinstance(probes, dict) and 'model:' + str(model) in probes)
                and overload_healthy(state, model)):
            return float(now + OVERLOAD_STEPS[-1])
    return float(value)


def _channel_cool(state, channel) -> float:
    table = state.get('channel_cool')
    value = table.get(channel['id']) if isinstance(table, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _group_cool(state, channel) -> float:
    group = state.get(channel['group'])
    until = group.get('cool_until', 0) if isinstance(group, dict) else 0
    return float(until) if isinstance(until, (int, float)) and not isinstance(until, bool) else 0.0


def no_streak(channel) -> bool:
    """W-gemma 3: a small-tier channel with a big daily allowance (rpd >= HIGH_RPD): no series of failures closes it."""
    return tier_of(channel) == 'small' and _big_daily(channel)


def day_marked(state, channel, now) -> bool:
    """A daily mark of this channel, of its model or of its key is on (running, or expired and waiting for its probe's 200:
    the 200 removes the row). A row whose series ended DAY_PROBE_FORGET_S ago is forgotten."""
    probes = state.get('day_probe')
    if not isinstance(probes, dict):
        return False
    for key in _probe_keys(channel):
        row = probes.get(key)
        if isinstance(row, dict) and isinstance(row.get('end'), (int, float)) and now - row['end'] < DAY_PROBE_FORGET_S:
            return True
    return False


def read_marks(state, channel, now=None) -> dict:
    """The one reading of the cooling marks of a channel (cooled_until, channel_report and the pool all use it):
    {'model', 'channel', 'group'} -> epoch seconds (0 = none). For a no_streak channel (Gemma) a mark that would hold it
    still longer than BIG_MARK_CAP_S ahead is cut off (read as 0) -- old marks of the series / suspect / overload rules,
    none of them made by this module any more -- unless a daily mark is on it (day_probe) or the mark is longer than
    STREAK_COOL_MAX_S (a balance or a dead mark of the provider). The last BIG_MARK_CAP_S of such an old mark still hold."""
    now = time.time() if now is None else now
    marks = {'model': _model_cool(state, channel, now), 'channel': _channel_cool(state, channel),
             'group': _group_cool(state, channel)}
    sources = state.get('channel_cool_src')
    own = sources.get(channel['id']) if isinstance(sources, dict) else None
    if own == 'big_probe' and not breaker_on(state, channel, now):
        marks['channel'] = 0.0      # W-flow 2: the first 200 (any process) ended the probe mode: the flow is back at once
    if no_streak(channel) and not day_marked(state, channel, now):
        for kind, value in marks.items():
            if kind == 'channel' and own in ('rate', 'big_close', 'big_probe'):
                continue          # the provider's own retry-after (a real 429) and our own short close are never cut
            if now + BIG_MARK_CAP_S < value <= now + STREAK_COOL_MAX_S:
                marks[kind] = 0.0       # ignored (not cut to "now + 20", which would slide for ever); a mark of the last 20 s holds
    return marks


def cooled_until(state, channel, now=None) -> float:
    """When the channel can take a call again as far as cooling goes: the latest of its quota group, its model and
    the channel itself (a per-minute limit cools only the channel)."""
    now = time.time() if now is None else now
    marks = read_marks(state, channel, now)
    return max(marks['group'], marks['model'], marks['channel'], _probe_flight(state, channel))


def _probe_keys(channel) -> tuple:
    return (channel['id'], 'group:' + str(channel['group']), 'model:' + str(channel['model']))


def _probe_flight(state, channel) -> float:
    """Until when a probe of this channel (or of its whole key) is out: nobody else is let through meanwhile."""
    table = state.get('day_probe')
    if not isinstance(table, dict):
        return 0.0
    best = 0.0
    for key in _probe_keys(channel):
        row = table.get(key)
        value = row.get('flight') if isinstance(row, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            best = max(best, float(value))
    return best


def _affinity_names(affinity):
    if not affinity:
        return []
    return [affinity] if isinstance(affinity, str) else [str(a) for a in affinity if a]


def _sticky(ordered, state, affinity, now):
    """``ordered`` with the channel this affinity used last moved to the front of its own tier (never ahead of a
    better tier), unless its model has gone bad since. The first name with a live memory decides."""
    table = state.get('affinity')
    if not isinstance(table, dict):
        return ordered
    for name in _affinity_names(affinity):
        entry = table.get(name)
        if not (isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[1], (int, float))
                and 0 <= now - entry[1] < AFFINITY_TTL_S):
            continue
        mine = [c for c in ordered if c['id'] == entry[0]]
        if not mine or rating(state, mine[0]['model']) < RATING_BAD:
            continue
        pick = mine[0]
        first = next(c for c in ordered if tier_of(c) == tier_of(pick))
        if first is pick:
            return ordered
        rest = [c for c in ordered if c is not pick]
        return rest[:rest.index(first)] + [pick] + rest[rest.index(first):]
    return ordered


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


def choose(channels, state, tokens, env, *, now=None, requests=1, affinity=None, grace=0):
    """First channel that can take ``tokens`` and ``requests`` now, else ChannelUnavailable(reason, wait_s).
    ``grace``: a cooled channel whose cooling ends within this many seconds counts as free (the headroom's view).
    ``affinity``: a name (or a list of names, the closest first: the task, then its module family) whose last
    channel is tried first within its tier while it has room; reserve() with the same names remembers the pick.
    None keeps the plain order."""
    now = time.time() if now is None else now
    channels = validate(channels, warn=False)   # the warning is given once, where the pool is loaded
    reasons = []  # (reason, wait_s)
    ordered = _balanced(channels, state, now)
    if affinity:
        ordered = _sticky(ordered, state, affinity, now)
    for channel in ordered:
        group = state.get(channel['group'], {})
        dead = state.get('dead', {}).get(channel['id'])
        if dead and _dead_applies(dead, env, channel):
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
        cool = cooled_until(state, channel, now)
        if cool > now + grace:
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


def reserve(state, channel, tokens, *, now=None, requests=1, affinity=None):
    """Book ``tokens`` and ``requests``; returns the booking timestamp for reconcile().

    The contract with choose(): the day window gets the whole run (at most rpd), the minute window only what
    fits one minute (at most rpm). reconcile() later replaces both with the fact. ``affinity`` (see choose())
    remembers this channel for those names."""
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
    _remember(state, channel, affinity, now)
    _send_probe(state, channel, now)
    return now


def _send_probe(state, channel, now) -> None:
    """The call booked on a channel whose daily mark has expired IS the probe: the others wait for its outcome."""
    table = state.get('day_probe')
    if not isinstance(table, dict):
        return
    for key in _probe_keys(channel):
        row = table.get(key)
        if isinstance(row, dict) and not (isinstance(row.get('flight'), (int, float)) and row['flight'] > now):
            row['flight'] = now + DAY_PROBE_HOLD_S


def _remember(state, channel, affinity, now) -> None:
    names = _affinity_names(affinity)
    if not names:
        return
    table = state.get('affinity')
    if not isinstance(table, dict):
        table = state['affinity'] = {}
    for name in names:
        table[name] = [channel['id'], now]
    for name in [n for n, e in table.items() if not (isinstance(e, (list, tuple)) and len(e) == 2
                                                      and isinstance(e[1], (int, float))
                                                      and 0 <= now - e[1] < AFFINITY_TTL_S)]:
        del table[name]
    for name in sorted(table, key=lambda n: table[n][1])[:max(0, len(table) - AFFINITY_MAX)]:
        del table[name]


def headroom(channels, state, tokens, env, *, now=None, requests=1, cap=16) -> int:
    """How many first calls choose()+reserve() could book right now on ``channels`` (a deep copy of ``state``: nothing
    is booked). The pool admits one more worker only while this exceeds the workers that have not booked yet. A channel
    that opens within OPEN_SOON_S counts as free: the card waits for it itself (2.3), the pool must not refuse for it."""
    work = copy.deepcopy(state)
    now = time.time() if now is None else now
    found = 0
    while found < cap:
        try:
            pick = choose(channels, work, tokens, env, now=now, requests=requests, grace=OPEN_SOON_S)
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


def note_sent(state, channel, *, now=None, count=1) -> float:
    """W-dry 3: a request that went out WITHOUT a booking (the watchdog's probe, any call outside reserve()) is counted
    the same: today's day window and the minute window of the channel's quota group. Returns the stamp used."""
    now = time.time() if now is None else now
    group = state.setdefault(channel['group'], {})
    times = [t for t in _numbers(group.get('request_times')) if now - t < 86400]
    minute_times = [t for t in _numbers(group.get('rpm_times')) if now - t < 60]
    while now in times or now in minute_times:
        now += 1e-6
    n = max(0, int(count))
    group['request_times'] = times + [now] * n
    group['rpm_times'] = minute_times + [now] * n
    group['requests'] = group.get('requests', 0) + n
    return now


def time_left_share(channel, *, now=None) -> float:
    """W-path C: the share of the provider's quota day that is still ahead (1.0 at its start, 0.0 at its end)."""
    now = time.time() if now is None else now
    start, end = quota_day(channel['model'], now)
    return max(0.0, min(1.0, (end - now) / (end - start)))


def day_left_share(state, channel, *, now=None) -> float:
    """The share of the channel's daily allowance not yet used today (its quota group's count over the provider's day)."""
    now = time.time() if now is None else now
    group = state.get(channel['group']) if isinstance(state.get(channel['group']), dict) else {}
    start, _ = quota_day(channel['model'], now)
    calls = sum(1 for t in _numbers(group.get('request_times')) if t >= start)
    return max(0.0, (channel['rpd'] - calls) / channel['rpd'])


def align_day(state, channel, quota_value, *, now=None) -> int:
    """W-dry 3: a 429 that names the day's limit (quotaValue) says the provider counted that many requests today: our
    calls_day of the channel's group is raised to it (never lowered). Returns the number of requests added."""
    now = time.time() if now is None else now
    if type(quota_value) is not int or quota_value <= 0:
        return 0
    group = state.setdefault(channel['group'], {})
    start, _ = quota_day(channel['model'], now)
    times = _numbers(group.get('request_times'))
    have = sum(1 for t in times if t >= start)
    missing = quota_value - have
    if missing <= 0:
        return 0
    group['request_times'] = times + [now - 1e-3 * (i + 1) for i in range(missing)]
    group['requests'] = group.get('requests', 0) + missing
    return missing


def main_dry(channels, state, env=None, *, now=None) -> bool:
    """W-gemma 3, the one condition of every Gemma rule: NO channel that can take an edit call (the edit route of the main
    and escalation tiers: a card's prompt is over the small tier's limit; a channel with no key or a dead key is no
    channel) is open -- open means: it takes a call now or by its marks within OPEN_SOON_S, and its day has room. What
    closed a channel does not matter (the day's mark, a channel / group / model cooling of any length). A channel with a
    daily mark (day_probe) is not open until its probe has answered 200, also when the mark has expired. ``env`` None:
    every key is taken as present (route_order has no environment). No usable channel at all: False (nothing to be dry)."""
    now = time.time() if now is None else now
    live = _edit_live(channels, state, env, now)
    return bool(live) and not any(_open_soon(state, c, now) for c in live)


def main_open(channels, state, env=None, *, now=None) -> bool:
    """Some main / escalation channel is open (the opposite of main_dry's reading, but also False with no usable channel at
    all): the small tier's answer limit is the quick one only while this is True."""
    now = time.time() if now is None else now
    return any(_open_soon(state, c, now) for c in _edit_live(channels, state, env, now))


def _edit_live(channels, state, env, now) -> list:
    """The usable channels of the edit route of the main and escalation tiers (a prompt over the small tier's limit)."""
    if env is None:
        env = {c['key_env']: 'x' for c in channels if 'key_env' in c}
    edit = {}
    for attempt in (1, 2):
        for channel in route_order(channels, 'edit', attempt, SMALL_PROMPT_TOKENS + 1):
            edit[channel['id']] = channel
    return usable(list(edit.values()), state, env, now=now)


def _open_soon(state, channel, now) -> bool:
    """main_dry's reading of one channel: no daily mark waiting for its 200, cooled at most OPEN_SOON_S more, and today's
    count under its rpd."""
    if day_marked(state, channel, now):
        return False
    if cooled_until(state, channel, now) > now + OPEN_SOON_S:
        return False
    group = state.get(channel['group']) if isinstance(state.get(channel['group']), dict) else {}
    start, _ = quota_day(channel['model'], now)
    return sum(1 for t in _numbers(group.get('request_times')) if t >= start) < channel['rpd']


def small_open(channels, state, env, *, now=None) -> bool:
    """W-gemma 4: some small-tier channel (Gemma) can still take calls today: it has a key, is not dead and is not closed
    by the day's mark (a rest of seconds or minutes does not close it)."""
    now = time.time() if now is None else now
    small = usable([c for c in channels if tier_of(c) == 'small'], state, env, now=now)
    return any(row['closed_by'] not in DAILY_CLOSED for row in channel_report(small, state, env, now=now))


BIG_PER_CHANNEL = 2            # W-gemma 4: calls at once the pool counts on one open Gemma channel
RESERVE_PREFIXES = ('openrouter/', 'cohere/')   # the spare channels of other providers: their exhaustion holds nobody


def is_reserve(channel) -> bool:
    """A spare channel of another provider (OpenRouter, Cohere): the pool's headroom never waits for it."""
    return str(channel.get('model') or '').startswith(RESERVE_PREFIXES)


def big_headroom(channels, state, env, *, now=None, cap=16) -> int:
    """W-gemma 4: with every main channel closed by the day's mark (main_dry) but Gemma open, the pool counts the Gemma
    channels instead: BIG_PER_CHANNEL calls at once on each channel that is usable and not closed by anything longer than
    OPEN_SOON_S (a 503 costs no quota and no cooling, so two calls per channel are what it carries: four channels run
    eight cards). 0 when a main channel is open (the normal count of headroom() holds) or Gemma is closed."""
    now = time.time() if now is None else now
    if not main_dry(channels, state, env, now=now):
        return 0
    small = [c for c in usable([c for c in channels if tier_of(c) == 'small' and not is_reserve(c)], state, env, now=now)
             if _big_daily(c)]
    count = 0
    for channel in small:
        try:
            choose([channel], state, 1, env, now=now, grace=OPEN_SOON_S)
        except ChannelUnavailable:
            continue
        count += 1
    return min(cap, BIG_PER_CHANNEL * count)


def edit_dry(channels, state, env, *, now=None) -> bool:
    """W-dry 1, the one definition: the main edit is out for the day (main_dry) AND, since W-gemma 4, Gemma is closed too
    -- while Gemma is open the factory works the normal way, on it."""
    now = time.time() if now is None else now
    return bool(main_dry(channels, state, env, now=now)) and not small_open(channels, state, env, now=now)


DAILY_CLOSED = ('daily_quota', 'rpd')


def cool(state, channel, *, now=None, seconds=DEFAULT_COOL_S):
    """Cool the whole quota group; never shortens a longer cooling."""
    now = time.time() if now is None else now
    group = state.setdefault(channel['group'], {})
    group['cool_until'] = max(group.get('cool_until', 0), now + max(1, seconds))


def cool_channel(state, channel, *, now=None, seconds=DEFAULT_COOL_S, src=None) -> dict:
    """Cool ONE channel (its model on its key); the key's other models and the model on other keys stay usable.
    Never shortens a longer cooling. ``src``: what made the mark ('rate' = the provider's own retry-after, which read_marks
    never cuts); recorded when this mark is the longest."""
    now = time.time() if now is None else now
    if not isinstance(state.get('channel_cool'), dict):
        state['channel_cool'] = {}
    table = state['channel_cool']
    until = now + max(1, seconds)
    if src and until > _channel_cool(state, channel):
        if not isinstance(state.get('channel_cool_src'), dict):
            state['channel_cool_src'] = {}
        state['channel_cool_src'][channel['id']] = src
    table[channel['id']] = max(_channel_cool(state, channel), until)
    for cid in [c for c, until in table.items() if not isinstance(until, (int, float)) or until <= now - 3600]:
        del table[cid]                                       # old terms are history
    return {'action': 'cool_channel', 'cool_s': seconds}


# ---- error classification ---------------------------------------------------------------------

_KEY_TEXT = re.compile(r'api[_ ]?key[_ ]?(?:is )?(?:not )?invalid|api key not valid|invalid api key', re.I)
_REGION_TEXT = re.compile(r'location is not supported|not available in your (?:country|region)', re.I)
_PERDAY = re.compile(r'PerDay|per[ -]day|daily', re.I)
_PERDAY_ID = re.compile(r'PerDay', re.I)      # the quotaId that confirms a daily refusal
_PERMODEL = re.compile(r'PerModel', re.I)     # Google quotaId ...PerDayPerProjectPerModel-FreeTier: one model of the key
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


def _quota_value(body) -> int:
    """The daily limit the provider names in a PerDay violation (Google: quotaValue "500"), else 0."""
    error = body.get('error') if isinstance(body, dict) else None
    for item in (error or {}).get('details', []) or []:
        for violation in (item.get('violations', []) or []) if isinstance(item, dict) else ():
            if isinstance(violation, dict) and _PERDAY_ID.search(str(violation.get('quotaId') or '')):
                try:
                    value = int(float(str(violation.get('quotaValue'))))
                except (TypeError, ValueError):
                    continue
                if 0 < value <= 10 ** 7:
                    return value
    return 0


_TOKEN_LIMIT_TEXT = re.compile(r'token.{0,60}(exceed|limit|too (many|large|long)|maximum)|(exceed|too (many|large|long)).{0,40}token|context.{0,10}(length|window)', re.I | re.S)


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
    header = _find(body, '_retry_after')
    if retry is None and isinstance(header, (int, float)) and not isinstance(header, bool) and header > 0:
        retry = float(header)      # the Retry-After header of the answer (the runner puts it into the body)
    if text and status == 400 and _TOKEN_LIMIT_TEXT.search(text):
        return _info('too_big', status, name, message)      # the request is over the model's window: shrink it
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
        now = time.time()
        at = _reset_at(body, now)
        # a real daily refusal is confirmed by a quotaId with PerDay; the word "daily" in the text without a quotaId
        # is a per-minute refusal -- unless the provider names a reset time (OpenRouter's free models)
        is_day = (any(_PERDAY_ID.search(q) for q in quota) if quota
                  else bool(at) and bool(_PERDAY.search(text)))
        if is_day:
            info = _info('rate_day', status, name, message,
                         math.ceil(at - now) if at else seconds_to_daily_reset(now), quota_text)
            if at:
                info['reset_at'] = at
            if value := _quota_value(body):
                info['quota_value'] = value      # W-dry 3: the provider's own count of today (align_day)
            if _PERMODEL.search(quota_text):      # a per-model-per-project daily quota: only this model on this key
                info['scope'] = 'channel'
            return info
        wait = math.ceil(retry) if retry else DEFAULT_COOL_S
        info = _info('rate_minute', status, name, message, wait, quota_text)
        if _find(body, 'provider_code') is not None:       # the UPSTREAM provider of one model, not the account
            info['scope'] = 'model'
        return info
    if status is None and name in ('EmptyAnswer', 'TruncatedAnswer'):
        # HTTP 200 and no answer: the model spent its whole output limit on reasoning for THIS task. Not an outage
        # of the model: the call hops to another model, and the rating/streak (note_outcome) judges a model that
        # does it again and again (D #22).
        info = _info('transient', None, name, message)
        info['scope'] = 'task'
        return info
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
        return _info('rate_minute', 429, message=text, retry=DEFAULT_COOL_S)   # no quotaId in stderr text: never daily
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


def apply_failure(state, channel, info, *, env=None, now=None, others=()) -> dict:
    """Record a channel/provider failure in the checkpoint quota state. Returns what was done."""
    now = time.time() if now is None else now
    env = env or {}
    kind = info.get('kind')
    if kind == 'key_invalid':
        state.setdefault('dead', {})[channel['id']] = {'key': _fingerprint(env, channel), 'since': now,
                                                       'reason': 'key_invalid'}
        return {'action': 'dead', 'cool_s': 0}
    if kind == 'model_missing':   # one 404 must not kill the channel for good: dead for 6 h, then probed again
        row = _stats(state, channel)
        row['missing'] += 1
        if row['missing'] >= MISSING_STREAK:      # every recent call answered 404: only a changed config revives it
            state.setdefault('dead', {})[channel['id']] = {'key': _fingerprint(env, channel), 'since': now,
                                                           'reason': 'model_missing_streak', 'until': None,
                                                           'config': _config_tag(channel)}
            return {'action': 'dead', 'cool_s': 0, 'reason': 'model_missing_streak'}
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
    if no_streak(channel) and (info.get('timed_out') or info.get('suspect')):
        # W-gemma 3: the answer limit of a Gemma call passed (also an idle one: Kilo's own sleep is no rate limit here):
        # this channel rests BIG_TIMEOUT_CLOSE_S, never more, and the 30 s cut-off is no rate_minute
        return cool_channel(state, channel, now=now, seconds=BIG_TIMEOUT_CLOSE_S)
    if kind in ('rate_minute', 'rate_day'):
        if kind == 'rate_day':
            note_day_429(state, channel, now=now)         # W-gemma 5: BEFORE the count is aligned to the provider's
            if info.get('quota_value'):
                align_day(state, channel, info['quota_value'], now=now)
            whole = not (info.get('scope') in ('model', 'channel'))
            seconds = _day_cool(channel, info, now, state, whole=whole, model=info.get('scope') == 'model')
        else:
            seconds = int(info.get('retry_after_s') or DEFAULT_COOL_S)
        if info.get('scope') == 'model':     # an upstream provider of ONE model: the rest of the account is fine
            return _cool_model(state, channel, now, seconds)
        if info.get('scope') == 'channel' or (kind == 'rate_minute' and info.get('status') != 402):
            # a per-model daily quota (D #18) or a per-minute limit is the limit of one model on one key
            # a per-minute limit is the limit of one model on one key: the other models of the project keep working
            # (live 20.11: 15 suspected per-minute stalls each cooled a whole project for 15 minutes)
            return cool_channel(state, channel, now=now, seconds=seconds, src='rate')
        cool(state, channel, now=now, seconds=seconds)     # a daily quota or the account's own budget: the whole key
        return {'action': 'cool', 'cool_s': seconds}
    if kind == 'transient' and info.get('scope') == 'task':
        return {'action': 'none', 'cool_s': 0}       # D #22: this task was too big for the model, the model is fine
    if kind == 'transient' and info.get('status') in OVERLOAD_STATUSES and _big_daily(channel):
        # W-gemma 1: the call hops (runner), nothing cools; W-flow 2: BREAKER_FAILS in a row put the channel in probe mode
        return {'action': 'none', 'cool_s': 0, 'reason': 'big_overload',
                'probe_mode': breaker_503(state, channel, now=now, others=others)}
    if kind == 'transient' and (info.get('status') in OVERLOAD_STATUSES):
        # "This model is currently experiencing high demand" (503): the MODEL is overloaded, not the account. Cooled,
        # the retry and the next pass take another channel (live 19.11 18:18-18:20: two passes were deferred on a
        # 503 of gemini-3.5-flash-lite while three other channels idled).
        if overload_healthy(state, channel['model']):
            run = _overload_run(state, channel['model'], now)
            if run == 1:      # one 503 is a hiccup: this channel rests 5 s, the model on the other key stays open
                return cool_channel(state, channel, now=now, seconds=OVERLOAD_STEPS[0])
            return _cool_model(state, channel, now, OVERLOAD_STEPS[min(run - 1, len(OVERLOAD_STEPS) - 1)],
                               src='overload')
        return _cool_model(state, channel, now, _overload_seconds(state, channel['model'], now, _big_daily(channel)),
                           src='overload')
    return {'action': 'none', 'cool_s': 0}


def _overload_run(state, model, now) -> int:
    """The model's 503s in a row: this one's number. A success of any process since the previous 503 (model_ok), or
    OVERLOAD_FORGET_S of quiet, starts the series again."""
    table = state.get('overload_run')
    if not isinstance(table, dict):
        table = state['overload_run'] = {}
    last = _numbers(table.get(model))
    oks = state.get('model_ok')
    ok_at = oks.get(model) if isinstance(oks, dict) else None
    ok_at = ok_at if isinstance(ok_at, (int, float)) and not isinstance(ok_at, bool) else 0
    run = 1
    if len(last) == 2 and 0 <= now - last[1] < OVERLOAD_FORGET_S and not ok_at > last[1]:
        run = min(int(last[0]), 1000) + 1
    table[model] = [run, now]
    return run


def absorb_foreign_ok(state, others) -> None:
    """Take the latest success of every model from the other processes' sections (``others``: quota_ledger.others())
    into ``state['model_ok']``: their success ends our series of 503s too."""
    oks = state.get('model_ok')
    if not isinstance(oks, dict):
        oks = state['model_ok'] = {}
    for other in others or ():
        table = other.get('model_ok') if isinstance(other, dict) else None
        for model, at in (table.items() if isinstance(table, dict) else ()):
            if isinstance(at, (int, float)) and not isinstance(at, bool) and at > oks.get(model, 0):
                oks[model] = at


def _day_cool(channel, info, now, state=None, *, whole=False, model=False) -> int:
    """Cooling of a daily 429: not until the reset but until the next PROBE -- DAY_PROBE_S, doubled for every
    further daily 429 of the same series, at most DAY_PROBE_MAX_S and never past the reset (the time the provider
    named, else the midnight of the channel's provider); in the first DAY_GRACE_S of the provider's day without a
    named reset at most DAY_GRACE_COOL_S. ``state`` keeps the series (state['day_probe']), and the expired mark
    lets one call through (reserve()); without ``state`` the first step is given."""
    at = info.get('reset_at')
    if isinstance(at, (int, float)) and not isinstance(at, bool) and 0 < at - now <= DAY_RESET_MAX_S:
        to_reset = int(math.ceil(at - now))
        named = True
    else:
        start, end = quota_day(channel['model'], now)
        to_reset = max(60, int(end - now))
        named = False
    n = 1
    # the series and the probe flight belong to what the mark is on: the key, the model (a per-model quota of a
    # provider: every channel of the model waits for one probe) or the channel
    key = 'group:' + str(channel['group']) if whole else 'model:' + str(channel['model']) if model else channel['id']
    if isinstance(state, dict):
        table = state.get('day_probe')
        if not isinstance(table, dict):
            table = state['day_probe'] = {}
        prior = table.get(key)
        if (isinstance(prior, dict) and type(prior.get('n')) is int and prior['n'] > 0
                and isinstance(prior.get('end'), (int, float)) and now - prior['end'] < DAY_PROBE_FORGET_S):
            n = prior['n'] + 1
    seconds = min(DAY_PROBE_MAX_S, DAY_PROBE_S * 2 ** min(n - 1, 8), to_reset)
    if not named and now - quota_day(channel['model'], now)[0] < DAY_GRACE_S:
        seconds = min(seconds, DAY_GRACE_COOL_S)
    seconds = max(60, seconds) if to_reset >= 60 else seconds
    if isinstance(state, dict):
        table[key] = {'n': n, 'end': now + seconds, 'flight': 0}
        for other in [k for k, v in table.items()
                      if not (isinstance(v, dict) and isinstance(v.get('end'), (int, float))
                              and now - v['end'] < DAY_PROBE_FORGET_S)]:
            del table[other]
    return seconds


def _big_daily(channel) -> bool:
    """A channel with a big daily allowance (rpd >= HIGH_RPD): parked for minutes at most, never for long."""
    rpd = channel.get('rpd')
    return type(rpd) is int and rpd >= HIGH_RPD


def is_big(channel) -> bool:
    """Public name of _big_daily (the runner asks it)."""
    return _big_daily(channel)


def big_hop(run, circle) -> tuple:
    """The next step after a 503 of a big channel; ``run`` is the call's own {'sends', 'round'} (changed here),
    ``circle`` the number of big channels the call may hop over. Returns ('hop', pause_s) or ('close', 0): the first
    BIG_SENDS_MAX sends hop after BIG_HOP_PAUSE_S; then each of BIG_ROUNDS rounds of one circle starts after
    BIG_ROUND_PAUSE_S; after the last one the channel is closed."""
    run['sends'] = int(run.get('sends') or 0) + 1
    rounds = int(run.get('round') or 0)
    if rounds == 0:
        if run['sends'] < BIG_SENDS_MAX:
            return 'hop', BIG_HOP_PAUSE_S
    elif run['sends'] < max(1, circle):
        return 'hop', BIG_HOP_PAUSE_S
    if rounds < BIG_ROUNDS:
        run['round'], run['sends'] = rounds + 1, 0
        return 'hop', BIG_ROUND_PAUSE_S
    return 'close', 0


SHARED_WINDOW_S = 3600         # W-gemma 5: daily 429s of the two keys of one model this close together
SHARED_TOLERANCE = 0.15        # ... and a sum of their own counts this close to the model's daily limit


def note_day_429(state, channel, *, now=None) -> dict | None:
    """W-gemma 5: two keys of two projects may share ONE daily quota of the same model (3.5-flash-lite: 274 + 236 = 510
    calls of a limit of 500). Every daily 429 notes the channel's own count of the day (before align_day raises it to the
    provider's number); when the 429 of the model's other key came within SHARED_WINDOW_S and the counts of the keys add up
    to about the limit, ``state['shared_project_suspect'][model]`` says so. Only a note: nothing is cooled or silenced by
    it. Returns the note or None."""
    now = time.time() if now is None else now
    table = state.get('day_429')
    if not isinstance(table, dict):
        table = state['day_429'] = {}
    group = state.get(channel['group']) if isinstance(state.get(channel['group']), dict) else {}
    start, _ = quota_day(channel['model'], now)
    calls = sum(1 for t in _numbers(group.get('request_times')) if t >= start)
    prior = table.get(channel['id'])
    if isinstance(prior, dict) and prior.get('start') == start and type(prior.get('calls')) is int:
        calls = prior['calls']      # a repeated 429 (probe) of the same day keeps the key's own first count, not the aligned one
    table[channel['id']] = {'model': channel['model'], 'group': channel['group'], 'at': now, 'calls': calls,
                            'rpd': channel['rpd'], 'start': start}
    for cid in [c for c, row in table.items() if not (isinstance(row, dict) and isinstance(row.get('at'), (int, float))
                                                      and now - row['at'] < DAY_RESET_MAX_S)]:
        del table[cid]
    rows = [r for r in table.values() if isinstance(r, dict) and r.get('model') == channel['model']
            and r.get('start') == start and abs(now - r['at']) <= SHARED_WINDOW_S]
    by_group = {}
    for row in rows:
        by_group[row['group']] = row
    limit = channel['rpd']
    total = sum(r['calls'] for r in by_group.values())
    if (len(by_group) >= 2 and abs(total - limit) <= SHARED_TOLERANCE * limit
            and all(r['calls'] < (1 - SHARED_TOLERANCE) * limit for r in by_group.values())):
        note = {'model': channel['model'], 'groups': sorted(by_group), 'sum_calls_day': total, 'limit': limit, 'at': now}
        if not isinstance(state.get('shared_project_suspect'), dict):
            state['shared_project_suspect'] = {}
        state['shared_project_suspect'][channel['model']] = note
        return note
    return None


def main_free(channel_list, state, tokens, env, *, now=None) -> bool:
    """Some main-tier channel can take a one-request call now (not cooled, not dead, day and minute windows have room)."""
    mains = [c for c in channel_list if tier_of(c) == 'main']
    if not mains:
        return False
    try:
        choose(mains, state, tokens, env, now=now)
    except ChannelUnavailable:
        return False
    return True


def small_timeout(channel_list, state, tokens, env, *, now=None) -> int:
    """W-gemma 2/4: how long a call of the small tier (Gemma, already chosen by the card) may wait for its answer:
    BIG_TIMEOUT_S always, except SMALL_FIRST_TIMEOUT_S while a main-tier channel (not escalation) is free right now with
    room in its minute window (a half-open channel after a 429 with rpm 5 is no reason to cut Gemma at 30 s)."""
    return SMALL_FIRST_TIMEOUT_S if main_free(channel_list, state, tokens, env, now=now) else BIG_TIMEOUT_S


def close_big(state, channel, *, now=None) -> dict:
    """After the rounds: this channel only is closed for BIG_CLOSE_S (a mark of our own, never cut when read)."""
    now = time.time() if now is None else now
    out = cool_channel(state, channel, now=now, seconds=BIG_CLOSE_S)
    if not isinstance(state.get('channel_cool_src'), dict):
        state['channel_cool_src'] = {}
    state['channel_cool_src'][channel['id']] = 'big_close'
    return out


BREAKER_FAILS = 2          # W-flow 2: 503s in a row that put a big channel in probe mode
BREAKER_PROBE_S = 45       # ... one send per channel per this many seconds from ALL cards (the mark is cool_channel's)
BREAKER_FORGET_S = 600     # a run of 503s older than this says nothing (nobody probed: the mode ends)


def _breaker_row(state, channel, create=False):
    table = state.get('big_breaker')
    if not isinstance(table, dict):
        if not create:
            return None
        table = state['big_breaker'] = {}
    row = table.get(channel['id'])
    if not isinstance(row, dict):
        if not create:
            return None
        row = table[channel['id']] = {'fails': 0, 'last': 0, 'ok': 0, 'claim': 0}
    return row


def breaker_on(state, channel, now=None) -> bool:
    """The channel is in probe mode: BREAKER_FAILS 503s in a row (no 200 since, in any process: the rows of the shared
    ledger are merged by the quota view) and the last one not older than BREAKER_FORGET_S."""
    now = time.time() if now is None else now
    row = _breaker_row(state, channel)
    if not row or not is_big(channel):
        return False
    last, ok = row.get('last') or 0, row.get('ok') or 0
    return (type(row.get('fails')) is int and row['fails'] >= BREAKER_FAILS and last > ok
            and 0 <= now - last < BREAKER_FORGET_S)


def breaker_open(state, channel_list, now=None) -> bool:
    """Some big channel of the list is in probe mode."""
    return any(breaker_on(state, c, now) for c in channel_list if is_big(c))


def breaker_503(state, channel, *, now=None, others=()) -> bool:
    """A 503 of a big channel: the run grows; at BREAKER_FAILS the channel goes into probe mode (a cool_channel mark of
    BREAKER_PROBE_S, kept by the next probe's claim). Returns whether the mode is on."""
    now = time.time() if now is None else now
    table = state.setdefault('big_breaker', {})
    for other in others or ():
        if isinstance(other, dict):
            _merge_breaker(table, other.get('big_breaker'))
    row = _breaker_row(state, channel, create=True)
    live = row['last'] > row['ok'] and 0 <= now - row['last'] < BREAKER_FORGET_S
    row['fails'] = (int(row['fails']) if live else 0) + 1
    row['last'] = now
    if row['fails'] >= BREAKER_FAILS:
        row['claim'] = now
        cool_channel(state, channel, now=now, seconds=BREAKER_PROBE_S, src='big_probe')
        return True
    return False


def breaker_ok(state, channel, *, now=None) -> None:
    """A 200 of a big channel: the mode ends at once (the mark of the probe is dropped when read, in every process)."""
    now = time.time() if now is None else now
    row = _breaker_row(state, channel)
    if row is None:
        return
    row['ok'], row['fails'] = now, 0
    table = state.get('channel_cool')
    if isinstance(table, dict) and (state.get('channel_cool_src') or {}).get(channel['id']) == 'big_probe':
        table.pop(channel['id'], None)


def breaker_claim(state, channel, *, now=None) -> None:
    """A send to a channel in probe mode is booked: nobody else sends there for BREAKER_PROBE_S."""
    now = time.time() if now is None else now
    if breaker_on(state, channel, now):
        _breaker_row(state, channel)['claim'] = now
        cool_channel(state, channel, now=now, seconds=BREAKER_PROBE_S, src='big_probe')


def _merge_breaker(into, other) -> None:
    from . import factory_quota
    factory_quota.merge_breaker(into, other)


def _overload_seconds(state, model, now, big=False) -> int:
    """OVERLOAD_COOL_S, doubled for every further overload of the same model within OVERLOAD_FORGET_S of the
    previous one, at most OVERLOAD_COOL_MAX_S -- for a ``big`` (rpd >= HIGH_RPD) channel at most HIGH_RPD_COOL_MAX_S,
    and the series stops counting where that limit is reached."""
    if not isinstance(state.get('model_overload'), dict):
        state['model_overload'] = {}
    table = state['model_overload']
    last = _numbers(table.get(model))
    series = int(last[0]) + 1 if len(last) == 2 and 0 <= now - last[1] < OVERLOAD_FORGET_S else 1
    limit = HIGH_RPD_COOL_MAX_S if big else OVERLOAD_COOL_MAX_S
    while big and series > 1 and OVERLOAD_COOL_S * 2 ** min(series - 2, 8) >= limit:
        series -= 1                    # the series does not count higher than the cooling it can still grow
    table[model] = [series, now]
    return min(limit, OVERLOAD_COOL_S * 2 ** min(series - 1, 8))


def note_outcome(state, channel, ok, *, now=None, channels=(), overload=False) -> dict:
    """Count the failed calls of ``channel`` in a row (kept in its quota group, per channel); the STREAK_FAILS-th and
    every further one cools it through cool() -- or only its model through _cool_model() when ``channels`` shows other
    models in the same group. A successful call ends the series. Returns what was done, with the reason."""
    now = time.time() if now is None else now
    group = state.setdefault(channel['group'], {})
    table = group.get('fail_streak') if isinstance(group.get('fail_streak'), dict) else {}
    group['fail_streak'] = table
    row = _stats(state, channel)
    row['results'] = (row['results'] + [1 if ok else 0])[-RATING_WINDOW:]
    if ok:
        row['missing'] = 0
        table.pop(channel['id'], None)
        breaker_ok(state, channel, now=now)          # W-flow 2: the first 200 ends the probe mode
        if isinstance(state.get('overload_run'), dict):
            state['overload_run'].pop(channel['model'], None)    # a success ends the model's series of 503s
        if not isinstance(state.get('model_ok'), dict):
            state['model_ok'] = {}
        state['model_ok'][channel['model']] = now      # the other processes see it in the shared section
        probes = state.get('day_probe')
        if isinstance(probes, dict):             # a 200 is the end of the daily mark: the probe worked
            if probes.pop(channel['id'], None) is not None and isinstance(state.get('channel_cool'), dict):
                state['channel_cool'].pop(channel['id'], None)
            if (probes.pop('group:' + str(channel['group']), None) is not None
                    and isinstance(group.get('cool_until'), (int, float)) and group['cool_until'] > now):
                group['cool_until'] = now
            if (probes.pop('model:' + str(channel['model']), None) is not None
                    and isinstance(state.get('model_cool'), dict)):
                state['model_cool'].pop(channel['model'], None)
        return {'action': 'none', 'cool_s': 0}
    if overload and (overload_healthy(state, channel['model']) or _big_daily(channel)):
        return {'action': 'none', 'cool_s': 0}     # a 503 of a healthy (or big-quota) model has its own rule (apply_failure)
    if no_streak(channel):
        table.pop(channel['id'], None)     # W-gemma 3: Gemma has no series of failures: a timeout or a 503 closes nothing here
        return {'action': 'none', 'cool_s': 0}
    prior = table.get(channel['id'])
    n = (prior if type(prior) is int and prior > 0 else 0) + 1
    big = _big_daily(channel)
    if big:
        n = min(n, STREAK_FAILS)       # the series does not count higher than its cooling can grow
    table[channel['id']] = n
    if n < STREAK_FAILS:
        return {'action': 'none', 'cool_s': 0}
    seconds = min(STREAK_COOL_MAX_S, STREAK_COOL_S * 2 ** min(n - STREAK_FAILS, 8))
    if channels and not _other_route(state, channel, channels, now):
        seconds = STREAK_COOL_S     # no other model is free now: never park the whole factory for hours on a series
    if big:
        seconds = min(seconds, HIGH_RPD_COOL_MAX_S)
    if any(c.get('group') == channel['group'] and c.get('model') != channel['model'] for c in channels):
        out = _cool_model(state, channel, now, seconds)
    else:
        cool(state, channel, now=now, seconds=seconds)
        out = {'action': 'cool', 'cool_s': seconds}
    out['reason'] = 'fail_streak'
    return out


def _other_route(state, channel, channels, now) -> bool:
    """Some channel of ANOTHER model is neither cooled nor marked dead now (key and quotas are choose()'s business)."""
    dead = state.get('dead') if isinstance(state.get('dead'), dict) else {}
    for other in channels:
        if other.get('model') == channel['model'] or 'group' not in other:
            continue
        mark = dead.get(other.get('id'))
        if isinstance(mark, dict):
            until = _dead_until(mark)
            if until is None or until > now:
                continue
        if cooled_until(state, other, now) <= now:
            return True
    return False


def probe_targets(channels, state, env, *, now=None) -> list:
    """The watchdog's pick: of the channels that are cooled now (and neither dead nor without a key) the one whose
    cooling ends EARLIEST, for every tier -- one per tier, in the order of TIERS."""
    now = time.time() if now is None else now
    dead = state.get('dead') if isinstance(state.get('dead'), dict) else {}
    best = {}
    for channel in channels:
        if not env.get(channel['key_env']):
            continue
        mark = dead.get(channel['id'])
        if isinstance(mark, dict) and _dead_applies(mark, env, channel):
            until = _dead_until(mark)
            if until is None or until > now:
                continue
        until = cooled_until(state, channel, now)
        if until <= now:
            continue
        tier = tier_of(channel)
        if tier not in best or until < best[tier][0]:
            best[tier] = (until, channel)
    return [best[t][1] for t in TIERS if t in best] + [best[t][1] for t in best if t not in TIERS]


def probe_outcome(state, channel, info, *, env=None, now=None, channels=()) -> dict:
    """Account one probe call made by the watchdog (the answer already classified): 200 lifts every cooling mark of
    the channel (its daily mark and series, its own mark, its model's mark, its series of failures); anything else is
    a failure like any other (apply_failure). Returns {'result': kind, 'cool_s': ..., 'lifted': bool}."""
    now = time.time() if now is None else now
    if info.get('kind') != 'ok':
        done = apply_failure(state, channel, info, env=env, now=now)
        return {'result': info.get('kind') or 'unknown', 'cool_s': done.get('cool_s', 0), 'lifted': False}
    note_outcome(state, channel, True, now=now, channels=channels)
    for key in _probe_keys(channel):
        if isinstance(state.get('day_probe'), dict):
            state['day_probe'].pop(key, None)
    if isinstance(state.get('channel_cool'), dict):
        state['channel_cool'].pop(channel['id'], None)
    if isinstance(state.get('model_cool'), dict):
        state['model_cool'].pop(channel['model'], None)
    if isinstance(state.get('model_overload'), dict):
        state['model_overload'].pop(channel['model'], None)
    if isinstance(state.get('overload_run'), dict):
        state['overload_run'].pop(channel['model'], None)
    group = state.get(channel['group'])
    if isinstance(group, dict) and isinstance(group.get('cool_until'), (int, float)) and group['cool_until'] > now:
        group['cool_until'] = now       # the key answered: the whole key's mark ends too
    return {'result': 'ok', 'cool_s': 0, 'lifted': True}


def channel_report(channels, state, env, *, now=None) -> list:
    """stats.json, one row per channel: calls today on its quota group (a group shares one count over its models),
    what closes it now ('' when open) and until when (epoch seconds, None when open)."""
    now = time.time() if now is None else now
    dead = state.get('dead') if isinstance(state.get('dead'), dict) else {}
    rows = []
    for channel in channels:
        group = state.get(channel['group']) if isinstance(state.get(channel['group']), dict) else {}
        start, end = quota_day(channel['model'], now)
        calls = sum(1 for t in _numbers(group.get('request_times')) if t >= start)
        closed, until = '', None
        mark = dead.get(channel['id'])
        probes = state.get('day_probe') if isinstance(state.get('day_probe'), dict) else {}
        probe = next((probes[k] for k in _probe_keys(channel) if isinstance(probes.get(k), dict)), None)
        marks = read_marks(state, channel, now)      # W-gemma 3: the same reading as choose() and main_dry
        candidates = []
        if isinstance(mark, dict) and _dead_applies(mark, env, channel):
            when = _dead_until(mark)
            if when is None or when > now:
                candidates.append(('dead', when))
        if not env.get(channel['key_env']):
            candidates.append(('no_key', None))
        if calls >= channel['rpd']:
            candidates.append(('rpd', end))
        for kind, when in (('model', marks['model']), ('channel', marks['channel']), ('group', marks['group'])):
            if when > now:
                label = kind
                if isinstance(probe, dict) and probe.get('end', 0) > now - 1 and kind in ('channel', 'group'):
                    label = 'daily_quota'
                elif kind == 'model':
                    label = 'model_overload_or_series'
                candidates.append((label, when))
        flight = _probe_flight(state, channel)
        if flight > now:
            candidates.append(('probe_out', flight))
        if candidates:
            closed, until = max(candidates, key=lambda c: (c[1] is None, c[1] or 0))
        rows.append({'id': channel['id'], 'model': channel['model'], 'group': channel['group'],
                     'calls_day': calls, 'rpd': channel['rpd'], 'closed_by': closed or None,
                     'until': int(until) if until is not None else None})
    return rows


def _cool_model(state, channel, now, seconds, src='other') -> dict:
    """Cool one MODEL (every channel of it) for ``seconds``; the account and the other models stay usable. ``src``
    says what made the mark (a mark of ours is never cut like an old overload mark when it is read)."""
    if not isinstance(state.get('model_cool'), dict):
        state['model_cool'] = {}
    models = state['model_cool']
    until = now + max(1, seconds)
    if until > models.get(channel['model'], 0):
        if not isinstance(state.get('model_cool_src'), dict):
            state['model_cool_src'] = {}
        state['model_cool_src'][channel['model']] = src
    models[channel['model']] = max(models.get(channel['model'], 0), until)
    return {'action': 'cool_model', 'cool_s': seconds}
