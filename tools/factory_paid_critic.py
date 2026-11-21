"""Paid control critic (owner ~14:30, rule 4): the free review chain approved a candidate and the gates passed;
only then one call to the Anthropic Messages API judges it again. Every catch is written to the error-class registry,
and the free review prompt reads the relevant entries, so the free contour keeps the quality when the key is switched
off. The key is read at run time from an env file outside the repository and travels only in the x-api-key header; it is
never logged, stored in a result or written to the registry. A missing key or budget means the step is skipped silently.
Never an Opus model: refused in code (refuse_opus), whatever the env file says."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
MODELS = ('claude-sonnet-5-5', 'claude-haiku-5-5')      # the first is asked, the second is the fallback
DEFAULT_ENV = r'C:\agent-factory\secrets\anthropic.env'
DEFAULT_DIR = r'C:\agent-factory\echo'
DEFAULT_BUDGET_USD = 100.0
TIMEOUT_S = 90
DIFF_LIMIT = 30000
GOAL_LIMIT = 3000
FAIL_LIMIT = 3000
LESSONS_MAX = 400
LESSONS_COUNT = 3
# USD per million tokens (input, output). Source: the claude-api skill's model table (cached 2026-11-03, Anthropic
# first-party prices): Sonnet 5.5 $2 / $10; Haiku 5.5 $0.10 / $0.50 for prompts up to 100K tokens, $0.50 / $2.50 above.
PRICES = {'claude-sonnet-5-5': (2.0, 10.0), 'claude-haiku-5-5': (0.10, 0.50)}
HAIKU_LONG = (0.50, 2.50)
HAIKU_LONG_FROM = 100_000


def refuse_opus(model: str) -> None:
    """Owner: no API Opus. A hard refusal, not a setting."""
    if 'opus' in str(model).lower():
        raise ValueError('an Opus model is never used by the paid critic: %s' % model)


def env_path() -> Path:
    return Path(os.environ.get('FACTORY_PAID_ENV') or DEFAULT_ENV)


def state_dir() -> Path:
    return Path(os.environ.get('FACTORY_PAID_DIR') or DEFAULT_DIR)


def load_env(path: Path) -> dict:
    out = {}
    try:
        text = path.read_text(encoding='utf-8-sig')
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            name, value = line.split('=', 1)
            out[name.strip()] = value.strip().strip('"\'')
    return out


def usd_for(model: str, tokens_in: int, tokens_out: int) -> float:
    price = PRICES.get(model) or max(PRICES.values())
    if model == 'claude-haiku-5-5' and tokens_in > HAIKU_LONG_FROM:
        price = HAIKU_LONG
    return tokens_in * price[0] / 1e6 + tokens_out * price[1] / 1e6


def _spend_file() -> Path:
    return state_dir() / 'paid_spend.json'


def spent_today() -> float:
    try:
        data = json.loads(_spend_file().read_text(encoding='utf-8'))
        if data.get('date') == datetime.date.today().isoformat():
            return float(data.get('usd') or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return 0.0


def add_spend(usd: float) -> None:
    path = _spend_file()
    row = dict(date=datetime.date.today().isoformat(), usd=round(spent_today() + usd, 6))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(row), encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):      # the key must never follow a redirect to another host
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int | None, bytes]:
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST', headers=headers)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        try:
            return error.code, error.read()
        except OSError:
            return error.code, b''
    except (OSError, ValueError) as error:
        return None, type(error).__name__.encode()


ASK = ('You are the control critic of an automated code factory. Free critics already approved this candidate and the '
       'task tests pass. Find a defect they missed: hard-coding to the test, lost behaviour, a stub, scope creep, a '
       'wrong fix of the real cause. The task tests are the specification: never dispute what a test expects. Answer '
       'ONLY with JSON {"verdict":"approve"|"reject","reason":"the concrete defect or empty","class":"short-kebab-slug '
       'naming the class of the defect or empty","symptom":"one sentence a weaker reviewer could check for"}.\n')


def _parse(raw: bytes):
    try:
        data = json.loads(raw.decode('utf-8', 'replace'))
        text = ''.join(b.get('text', '') for b in data['content'] if isinstance(b, dict) and b.get('type') == 'text')
        answer, _ = json.JSONDecoder().raw_decode(text[text.index('{'):])
        usage = data.get('usage') or {}
        tin, tout = int(usage.get('input_tokens') or 0), int(usage.get('output_tokens') or 0)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if not isinstance(answer, dict) or answer.get('verdict') not in ('approve', 'reject'):
        return None
    return answer, tin, tout


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')[:60] or 'unnamed'


def control(task, diff: str, failure: str = '') -> dict | None:
    """One paid judgement of a candidate, or None (no key, no budget, a refused model, any fault). The free verdict
    stands when None. The dict never holds the key."""
    if os.environ.get('PYTEST_CURRENT_TEST') and not os.environ.get('FACTORY_PAID_ENV'):
        return None                                     # a test never spends the real key
    env = load_env(env_path())
    key = env.get('ANTHROPIC_API_KEY', '')
    if not key:
        return None
    try:
        budget = float(env.get('ANTHROPIC_DAILY_BUDGET_USD') or DEFAULT_BUDGET_USD)
    except ValueError:
        budget = DEFAULT_BUDGET_USD
    if spent_today() >= budget:
        return None
    prompt = (ASK + 'Task: %s\nTask text:\n%s\nGuard test failure text (what the tests failed on before the fix):\n%s\n'
              'Candidate diff:\n%s\n') % (getattr(task, 'title', ''), str(getattr(task, 'goal', '') or '')[:GOAL_LIMIT],
                                          failure[-FAIL_LIMIT:], diff[:DIFF_LIMIT])
    for model in MODELS:
        try:
            refuse_opus(model)
        except ValueError:
            continue
        body = dict(model=model, max_tokens=2000, output_config=dict(effort='low'),
                    messages=[dict(role='user', content=prompt)])
        headers = {'content-type': 'application/json', 'anthropic-version': API_VERSION, 'x-api-key': key}
        status, raw = _post(URL, headers, body, TIMEOUT_S)
        if status != 200:
            continue
        parsed = _parse(raw)
        if parsed is None:
            continue
        answer, tin, tout = parsed
        usd = usd_for(model, tin, tout)
        add_spend(usd)
        return dict(verdict=answer['verdict'], reason=str(answer.get('reason') or '')[:600],
                    **{'class': _slug(answer.get('class') or '')}, symptom=str(answer.get('symptom') or '')[:300],
                    model=model, usd=round(usd, 6), tokens_in=tin, tokens_out=tout)
    return None


def record_class(task, result: dict, *, ts: str = '') -> None:
    """A paid reject of a candidate the free chain approved: the free chain missed it, so it goes to the registry of
    error classes (tools/factory_classes.py, the one registry)."""
    from tools import factory_classes
    try:
        factory_classes.record_paid(getattr(task, 'id', ''), getattr(task, 'title', ''),
                                    [str(f) for f in getattr(task, 'touch_files', ())][:8], result['class'],
                                    result['symptom'] or result['reason'], ts=ts)
    except OSError:
        pass


def lessons_for(task, failure: str = '') -> str:
    """What the free critic is told of past catches: the matched class's short lesson and the paid catches related by
    files, at most LESSONS_MAX characters (factory_classes.critic_lesson)."""
    from tools import factory_classes
    return factory_classes.critic_lesson(task, failure)
