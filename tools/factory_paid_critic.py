"""Paid control critic (owner ~14:30, rule 4): the free review chain approved a candidate and the gates passed;
only then one call to the Anthropic Messages API judges it again. Every catch is written to the error-class registry,
and the free review prompt reads the relevant entries, so the free contour keeps the quality when the key is switched
off. The key is read at run time from an env file outside the repository and travels only in the x-api-key header; it is
never logged, stored in a result or written to the registry. A missing key or budget means the step is skipped silently.
Never an Opus model: refused in code (refuse_opus), whatever the env file says."""
from __future__ import annotations

import datetime
from contextlib import contextmanager
import math
import time
import uuid
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
ALLOWANCE_FIRST_USD = 120.0
ALLOWANCE_DAILY_USD = 10.0
ALLOWANCE_TOTAL_USD = 200.0
ALLOWANCE_FROM = '2026-11-22'
UNKNOWN_RESERVE_USD = 5.0
TIMEOUT_S = 90
DIFF_LIMIT = 30000
GOAL_LIMIT = 3000
FAIL_LIMIT = 3000
LESSONS_MAX = 400
LESSONS_COUNT = 3
# USD per million tokens (input, output). Source: the claude-api skill's model table (cached 2026-11-03, Anthropic
# first-party prices): Sonnet 5.5 $2 / $10; Haiku 5.5 $0.10 / $0.50 for prompts up to 100K tokens, $0.50 / $2.50 above.
PRICES = {'claude-sonnet-5-5': (2.0, 10.0, 2.5, 0.2), 'claude-haiku-5-5': (0.10, 0.50, 0.125, 0.01)}
HAIKU_LONG = (0.50, 2.50, 0.625, 0.05)
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


def usd_for(model: str, tokens_in: int, tokens_out: int,
            cache_creation_input_tokens: int = 0, cache_read_input_tokens: int = 0) -> float:
    price = PRICES.get(model) or max(PRICES.values())
    if model == 'claude-haiku-5-5' and tokens_in + cache_creation_input_tokens + cache_read_input_tokens > HAIKU_LONG_FROM:
        price = HAIKU_LONG
    # Five-minute cache writes cost 1.25x base input; reads cost 0.1x (Anthropic prompt-caching docs).
    return (tokens_in * price[0] + tokens_out * price[1] + cache_creation_input_tokens * price[2]
            + cache_read_input_tokens * price[3]) / 1e6


def _today() -> str:
    return datetime.date.today().isoformat()


def allowance(day: str) -> float:
    days = max(0, (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(ALLOWANCE_FROM)).days)
    return min(ALLOWANCE_TOTAL_USD, ALLOWANCE_FIRST_USD + ALLOWANCE_DAILY_USD * min(8, days))


def _spend_file() -> Path:
    return state_dir() / 'paid_spend.json'


def _spend_row() -> dict:
    try:
        row = json.loads(_retry_perm(lambda: _spend_file().read_text(encoding='utf-8')))
    except FileNotFoundError:
        row = {}
    if not isinstance(row, dict):
        raise ValueError('invalid paid spend state')
    if row and 'total_usd' not in row:
        row['total_usd'] = float(row.get('usd', 0)) + UNKNOWN_RESERVE_USD
    if row.get('date') != _today():
        row.update(date=_today(), usd=0.0, coder_usd=0.0, day_roles={})
    return row


def spent_today() -> float:
    return float(_spend_row().get('usd', 0))


def coder_spent_today() -> float:
    return float(_spend_row().get('coder_usd', 0))


def spent_total() -> float:
    return float(_spend_row().get('total_usd', 0))


def architect_spent_total() -> float:
    return float(_spend_row().get('architect_total_usd', 0))


def _external(path_name, fields):
    path = os.environ.get(path_name)
    if not path:
        return 0.0
    try:
        row = json.loads(_retry_perm(lambda: Path(path).read_text(encoding='utf-8-sig')))
    except FileNotFoundError:
        return 0.0
    amount = sum(float(row.get(f, 0)) for f in fields)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError('invalid builders spend')
    return amount


def _left(day, row):
    return allowance(day) - float(row.get('total_usd', 0)) - float(row.get('reserved_usd', 0)) - _external(
        'FACTORY_BUILDERS_SPEND', ('total_usd', 'reserved_usd'))


def left(day) -> float:
    return _left(day, _spend_row())


@contextmanager
def _spend_lock():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / 'paid_spend.lock'
    deadline = time.monotonic() + 30
    while True:
        try:
            lock.mkdir()
            break
        except (FileExistsError, PermissionError):     # Windows: PermissionError while the old lock folder is being removed
            try:
                if time.time() - lock.stat().st_mtime > 30:
                    lock.rmdir()
                    continue
            except (FileNotFoundError, PermissionError):
                if time.monotonic() >= deadline:
                    raise TimeoutError('paid spend lock busy')
                time.sleep(0.005)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError('paid spend lock busy')
            time.sleep(0.005)
    try:
        yield
    finally:
        _retry_perm(lock.rmdir)


def _retry_perm(action, tries=8, pause=0.05):
    """Windows answers PermissionError while another process holds the file for a moment (a read racing a replace,
    a lock folder being removed): the operation is repeated after a short pause, the last error is raised."""
    for attempt in range(tries):
        try:
            return action()
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(pause)


def _write_spend(row):
    path = _spend_file()
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        _retry_perm(lambda: tmp.write_text(json.dumps(row), encoding='utf-8'))
        _retry_perm(lambda: os.replace(tmp, path))
    finally:
        tmp.unlink(missing_ok=True)


def _amount(usd):
    usd = float(usd)
    if not math.isfinite(usd) or usd < 0:
        raise ValueError('invalid spend amount')
    return usd


def _add(row, usd, *, coder=False, architect=False, agent=False, critic=False):
    for name, enabled in (('usd', True), ('total_usd', True), ('coder_usd', coder),
                          ('architect_total_usd', architect), ('agent_total_usd', agent), ('critic_total_usd', critic)):
        if enabled:
            row[name] = round(float(row.get(name, 0)) + usd, 9)
    for name in ('total_usd', 'architect_total_usd', 'agent_total_usd', 'critic_total_usd', 'credit_dead_until'):
        row.setdefault(name, 0.0)
    role = 'agent' if agent else 'critic' if critic else 'architect' if architect else 'coder' if coder else ''
    if role and usd:
        roles = row.get('day_roles') if isinstance(row.get('day_roles'), dict) else {}
        roles[role] = round(float(roles.get(role, 0)) + usd, 9)
        row['day_roles'] = roles


def add_spend(usd, architect=False, agent=False, critic=False):
    usd = _amount(usd)
    with _spend_lock():
        row = _spend_row()
        _add(row, usd, architect=architect, agent=agent, critic=critic)
        _write_spend(row)


def reserve(usd, architect=False, critic=False) -> bool:
    usd = _amount(usd)
    with _spend_lock():
        row = _spend_row()
        available = _left(_today(), row)
        waiting = _external('FACTORY_BUILDERS_WAITING', ('usd',))
        if float(row.get('credit_dead_until', 0)) > time.time() or available < usd + waiting:
            return False
        _add(row, 0.0)
        row['reserved_usd'] = round(float(row.get('reserved_usd', 0)) + usd, 9)
        _write_spend(row)
        return True


def settle(reserved, actual, architect=False, agent=False, critic=False, coder=False):
    reserved, actual = _amount(reserved), _amount(actual)
    with _spend_lock():
        row = _spend_row()
        row['reserved_usd'] = round(max(0, float(row.get('reserved_usd', 0)) - reserved), 9)
        _add(row, actual, coder=coder, architect=architect, agent=agent, critic=critic)
        _write_spend(row)


class CreditExhausted(ValueError):
    pass


def mark_credit_dead(now=None):
    with _spend_lock():
        row = _spend_row()
        row['credit_dead_until'] = (time.time() if now is None else now) + 3600
        _write_spend(row)


def credit_dead(now=None) -> bool:
    return float(_spend_row().get('credit_dead_until', 0)) > (time.time() if now is None else now)


AGENT_PAUSE_S = 3600


def key_available() -> bool:
    """The one answer to "is there a paid key we may use now": the key sits in the file of env_path() (the key is
    never printed or returned) and the API credit is not marked dead. Read on every call, so a revived key counts."""
    if os.environ.get('PYTEST_CURRENT_TEST') and not os.environ.get('FACTORY_PAID_ENV'):
        return False                                    # a test never looks at the real key
    try:
        return bool(load_env(env_path()).get('ANTHROPIC_API_KEY', '')) and not credit_dead()
    except (ValueError, TypeError, OSError):
        return False


def mark_agent_credit_dead(now=None):
    """Claude Code (stage "agent") was refused for lack of credit: only that stage waits an hour. The API key's own
    credit_dead_until stays untouched: paid and the critic go on."""
    with _spend_lock():
        row = _spend_row()
        row['agent_dead_until'] = (time.time() if now is None else now) + AGENT_PAUSE_S
        _write_spend(row)


def agent_credit_dead(now=None) -> bool:
    try:
        return float(_spend_row().get('agent_dead_until', 0)) > (time.time() if now is None else now)
    except (ValueError, TypeError, OSError):
        return False


def day_report() -> dict:
    """Today's spend by role and what is still allowed (for stats.json). No key, no secrets."""
    row = _spend_row()
    roles = {name: round(float(value), 6) for name, value in (row.get('day_roles') or {}).items()}
    return dict(day=_today(), usd=round(float(row.get('usd', 0)), 6), by_role=roles,
                left=round(_left(_today(), row), 6), credit_dead=float(row.get('credit_dead_until', 0)) > time.time(),
                agent_paused=float(row.get('agent_dead_until', 0)) > time.time())


def check_credit(status, raw):
    try:
        error = json.loads(raw).get('error', {})
    except (ValueError, AttributeError):
        return
    if (status == 402 and error.get('type') == 'billing_error') or (status == 400 and
            'credit balance' in str(error.get('message', '')).lower()):
        mark_credit_dead()
        raise CreditExhausted('credit exhausted')


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


def _review_source(task, baseline, workdir):
    """Verbatim tests and named function regions, bounded across both snapshots."""
    from tools import agent_factory as F, factory_cards as K
    if baseline is None or workdir is None:
        return ''
    try:
        contract = json.loads(getattr(task, 'contract', '') or '{}')
        parts = {p['file']: p for p in contract.get('parts', [])}
    except (ValueError, TypeError, KeyError):
        parts = {}
    chunks, remaining = [], 60000
    files = list(getattr(task, 'tests', ())) + list(getattr(task, 'touch_files', ()))
    for file in dict.fromkeys(files):
        try:
            F.safe_path(file)
        except ValueError:
            continue
        for label, root in (('BEFORE', baseline), ('AFTER', Path(workdir))):
            try:
                if isinstance(root, dict):     # the runner's snapshot: {name: bytes}
                    if file not in root or len(root[file]) > 2_000_000:
                        continue
                    text = root[file].decode('utf-8-sig', 'replace')
                else:
                    root = Path(root)
                    path = root / file
                    if not path.resolve().is_relative_to(root.resolve()):
                        continue
                    if path.stat().st_size > 2_000_000:
                        continue
                    text = path.read_text(encoding='utf-8-sig')
                part = parts.get(file)
                if part:
                    _, text = K.part_region(text, part.get('symbols', []), part.get('anchor', ''), cap=60000)
            except (OSError, UnicodeError, ValueError, SyntaxError):
                continue
            chunk = label + ' ' + file + '\n' + F.redact(text)
            chunks.append(chunk[:remaining])
            remaining -= min(remaining, len(chunk))
            if remaining <= 0:
                return '\n'.join(chunks)
    return '\n'.join(chunks)


def available() -> bool:
    """Whether ``control`` could spend now (a key, live credit, budget left): the same guards, no call, nothing booked.
    The review precheck uses it to keep the paid second voice reachable (W-review fix 2)."""
    if os.environ.get('PYTEST_CURRENT_TEST') and not os.environ.get('FACTORY_PAID_ENV'):
        return False
    try:
        return bool(load_env(env_path()).get('ANTHROPIC_API_KEY', '')) and not credit_dead() and left(_today()) > 0
    except (ValueError, TypeError, OSError, TimeoutError):
        return False


def control(task, diff: str, failure: str = '', exclude_model: str = '', *, baseline=None, workdir=None) -> dict | None:
    """One paid judgement of a candidate, or None (no key, no budget, a refused model, any fault). The free verdict
    stands when None. The dict never holds the key. ``exclude_model``: the coder's model never judges its own
    candidate (a paid coder's Sonnet is judged by Haiku or not at all)."""
    if os.environ.get('PYTEST_CURRENT_TEST') and not os.environ.get('FACTORY_PAID_ENV'):
        return None                                     # a test never spends the real key
    try:
        key = load_env(env_path()).get('ANTHROPIC_API_KEY', '')
        if not key or credit_dead():
            return None
        return _control(task, diff, failure, exclude_model, baseline, workdir, key)
    except (ValueError, TypeError, OSError, TimeoutError):
        return None                                     # a broken state file or a busy lock: no paid voice, never a fault


def _control(task, diff, failure, exclude_model, baseline, workdir, key):
    prompt = (ASK + 'Task: %s\nTask text:\n%s\nGuard test failure text (what the tests failed on before the fix):\n%s\n'
              'Candidate diff:\n%s\n') % (getattr(task, 'title', ''), str(getattr(task, 'goal', '') or '')[:GOAL_LIMIT],
                                          failure[-FAIL_LIMIT:], diff[:DIFF_LIMIT])
    prompt += '\nTests and source regions:\n' + _review_source(task, baseline, workdir)
    try:
        multifile = len(json.loads(getattr(task, 'contract', '') or '{}').get('parts', [])) > 1
    except (ValueError, TypeError, AttributeError):
        multifile = False
    approvals, total_usd, total_in, total_out = [], 0.0, 0, 0
    for model in MODELS:
        try:
            refuse_opus(model)
        except ValueError:
            continue
        if model in ({str(m).rpartition('/')[2] for m in exclude_model} if isinstance(exclude_model, (list, tuple, set, frozenset))
                     else {str(exclude_model).rpartition('/')[2]}):
            continue
        body = dict(model=model, max_tokens=2000, output_config=dict(effort='medium'),
                    messages=[dict(role='user', content=prompt)])
        headers = {'content-type': 'application/json', 'anthropic-version': API_VERSION, 'x-api-key': key}
        estimate = (len(prompt.encode('utf-8')) * 2 + 2000 * 10) / 1e6 * 1.3
        if not reserve(estimate, critic=True):
            return None
        usd = 0.0
        try:
            status, raw = _post(URL, headers, body, TIMEOUT_S)
            check_credit(status, raw)
            if status != 200:
                continue
            usage = json.loads(raw).get('usage') or {}
            usd = usd_for(model, usage.get('input_tokens', 0), usage.get('output_tokens', 0),
                          usage.get('cache_creation_input_tokens', 0), usage.get('cache_read_input_tokens', 0))
            parsed = _parse(raw)
            if parsed is None:
                continue
            answer, tin, tout = parsed
        except CreditExhausted:
            return None
        except (ValueError, TypeError, OSError):
            continue
        finally:
            settle(estimate, usd, critic=True)
        total_usd += usd
        total_in += tin
        total_out += tout
        if multifile and answer['verdict'] == 'approve':
            approvals.append(model)
            if len(approvals) < 2:
                continue
        return dict(verdict=answer['verdict'], reason=str(answer.get('reason') or '')[:600],
                    **{'class': _slug(answer.get('class') or '')}, symptom=str(answer.get('symptom') or '')[:300],
                    model='+'.join(approvals) if len(approvals) > 1 else model, usd=round(total_usd, 6), tokens_in=total_in, tokens_out=total_out)
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
