"""Paid escalation coder (rule 4 of 21.11; built 22.11): when the free light engine failed a task, one more
channel kind of the light engine, the Anthropic Messages API, writes the same SEARCH/REPLACE edit blocks. Never first,
never Opus (factory_paid_critic.refuse_opus), capped per day by ANTHROPIC_CODER_BUDGET_USD inside the one
paid_spend.json that the paid critic uses (and by that critic's total budget). No key or no budget: the channel does
not exist and the free contour is unchanged. The key comes from the env file outside the repository, travels only in
the x-api-key header and is never logged. This module is optional: the callers guard its import."""
from __future__ import annotations

import json

from . import factory_paid_critic as paid

PROVIDER = 'anthropic'
MODELS = paid.MODELS                                      # sonnet first, haiku as the fallback; Opus is never listed
MODEL = PROVIDER + '/' + MODELS[0]
DEFAULT_CODER_BUDGET_USD = 25.0
FREE_FILES = 5                                            # the free tier keeps its limit (runner.LIGHT_MAX_FILES)
PROMPT_LIMIT_CHARS = 300000                               # Sonnet's 200k context; the free engine's own limit stays 28000
MAX_FILES = 8                                             # only the paid tier may take a task of up to 8 files
ESCALATE_FROM_ATTEMPT = 2                                 # the free engine had attempt 1 at least
_RETRY_ON = (None, 404, 429, 500, 502, 503, 529)          # a reason to ask the fallback model


def _key() -> str:
    return paid.load_env(paid.env_path()).get('ANTHROPIC_API_KEY', '')


def _under_test() -> bool:
    import os
    return bool(os.environ.get('PYTEST_CURRENT_TEST') and not os.environ.get('FACTORY_PAID_ENV'))


def _number(env: dict, name: str, default: float) -> float:
    try:
        return float(env.get(name) or default)
    except ValueError:
        return default


def coder_budget() -> float:
    return _number(paid.load_env(paid.env_path()), 'ANTHROPIC_CODER_BUDGET_USD', DEFAULT_CODER_BUDGET_USD)


def total_budget() -> float:
    return _number(paid.load_env(paid.env_path()), 'ANTHROPIC_DAILY_BUDGET_USD', paid.DEFAULT_BUDGET_USD)


def available() -> bool:
    """A key, the coding cap not reached and the day's total budget not reached."""
    if _under_test() or not _key():
        return False
    return paid.coder_spent_today() < coder_budget() and paid.spent_today() < total_budget()


def wanted(attempt: int, tier_floor=None) -> bool:
    """Escalation only: the task already had a free attempt (attempt >= 2) or its tier floor was raised to
    'escalation' by the loop; and the channel is available."""
    return (int(attempt or 0) >= ESCALATE_FROM_ATTEMPT or tier_floor == 'escalation') and available()


def files_limit(attempt: int, tier_floor=None) -> int:
    """How many files a task may carry for its NEXT pass: 8 when the paid tier will take it, else 5."""
    return MAX_FILES if wanted(max(int(attempt or 0) + 1, ESCALATE_FROM_ATTEMPT), tier_floor) else FREE_FILES


def post_chat(url, key, body: dict, timeout: float) -> tuple[int | None, bytes]:
    """The light engine's chat call (OpenAI-shaped body) answered by the Messages API, translated back to the
    OpenAI-shaped answer. ``url`` and ``key`` of the caller are ignored: the endpoint and the key are the paid ones."""
    rows = body.get('messages') or []
    system = '\n'.join(str(m.get('content') or '') for m in rows if m.get('role') == 'system')
    chat = [dict(role=m['role'], content=m.get('content') or '') for m in rows if m.get('role') in ('user', 'assistant')]
    secret = _key()
    status, raw = None, b'NoKey'
    for model in MODELS:
        paid.refuse_opus(model)
        request = dict(model=model, max_tokens=int(body.get('max_tokens') or 8000), system=system, messages=chat)
        headers = {'content-type': 'application/json', 'anthropic-version': paid.API_VERSION, 'x-api-key': secret}
        status, raw = paid._post(paid.URL, headers, request, timeout)
        if status not in _RETRY_ON:
            break
        if status == 200:
            break
    if status != 200:
        return status, raw
    try:
        data = json.loads(raw.decode('utf-8', 'replace'))
        text = ''.join(b.get('text', '') for b in data['content'] if isinstance(b, dict) and b.get('type') == 'text')
        usage = data.get('usage') or {}
        tin, tout = int(usage.get('input_tokens') or 0), int(usage.get('output_tokens') or 0)
        used = data.get('model') or model
    except (ValueError, KeyError, TypeError, AttributeError):
        return 200, b'{}'
    paid.add_spend(paid.usd_for(model, tin, tout), coder=True)
    finish = 'length' if data.get('stop_reason') == 'max_tokens' else 'stop'
    return 200, json.dumps(dict(model=used, choices=[dict(message=dict(content=text), finish_reason=finish)],
                                usage=dict(prompt_tokens=tin, completion_tokens=tout))).encode('utf-8')


def record_lesson(task, feedback: str = '') -> None:
    """A paid coder fixed what the free ones could not: the case enters the class registry that the free prompts read."""
    files = [str(f) for f in getattr(task, 'touch_files', ())]
    note = ('free coders failed; the paid coder solved it across %d file(s): %s. Last free feedback: %s'
            % (len(files), ', '.join(files[:8]), str(feedback or 'none')[:120]))
    paid.record_class(task, {'class': 'paid-coder-multi-file-fix' if len(files) > 2 else 'paid-coder-fix',
                             'symptom': note, 'reason': note})
