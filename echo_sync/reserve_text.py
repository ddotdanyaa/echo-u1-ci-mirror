"""The reserve of the text channel (the order of the owner of 10.11.2026 23:50: the Codex quota ran out the evening before a talk and the
call had no model at all). A second road for the SAME job - the same instructions, history and question ``fast_text.build_request`` made -
through an OpenAI-compatible chat endpoint with the keys of the file the owner keeps for his other project (never copied, never logged;
read when a call opens). Nothing of the controller changes: the job, its guards, the portions and the go-on rules are the usual ones; only
where the text comes from differs.

Order of the roads (measured 11.11 00:30 from this laptop): Groq ``openai/gpt-oss-120b`` (a whole answer in 1.1 s), its second key, its
other model, then Gemini (refused from the present network exit: "User location is not supported"; tried last, 0.5 s when refused).
A road that refuses (quota, sign-in, location) rests for ``REST_S``: nothing is asked twice of a provider that has just said no."""
import functools, io, json, logging, os, re, threading, time
from collections import namedtuple
from .settings import environment

logger = logging.getLogger('echo-sync')
ENV_VAR = 'ECHO_RESERVE_ENV'
DEFAULT_ENV = os.path.join(os.path.expanduser('~'), 'mwp2', 'config', 'providers.env')
GROQ, GEMINI = 'https://api.groq.com/openai/v1', 'https://generativelanguage.googleapis.com/v1beta/openai'
# Probe of 11.11 01:10 with the call's instructions (15 000 chars, about 6 500 tokens a question): the free quota of one Groq key and model is
# about one such question a minute, so the roads are many: every key with every model, each with its own minute.
ROADS = (('GROQ_API_KEY', GROQ, 'openai/gpt-oss-120b'), ('GROQ_API_KEY_2', GROQ, 'openai/gpt-oss-120b'),
         ('GROQ_API_KEY', GROQ, 'openai/gpt-oss-20b'), ('GROQ_API_KEY_2', GROQ, 'openai/gpt-oss-20b'),
         # 11.11 10:15, exit DE, the call's instructions, n=4 a model: gemini-3.5-flash timed out (6 s) 3 of 4, gemini-3.5-flash-lite gave its first text in 1.2-2.4 s, right answers.
         # It has a quota of its own, so it stands before the third Groq model; refused by the exit (FR: «User location is not supported») it rests like any road.
         ('GEMINI_API_KEY', GEMINI, 'gemini-3.5-flash-lite'), ('GEMINI_API_KEY_2', GEMINI, 'gemini-3.5-flash-lite'),
         # 13.11 00:05 (REVIEW_20261112/night/H_roads.md, n=1 a road): every road above answers; qwen is alive and gave a wrong year, so it stays last.
         # OpenRouter's free gemma answered 429 (and has 50 requests a day): it is no road, and its key is not read any more.
         ('GROQ_API_KEY', GROQ, 'qwen/qwen3.8-27b'), ('GROQ_API_KEY_2', GROQ, 'qwen/qwen3.8-27b'))
REST_S = 60.0                 # a road that refused is not asked again for this long
PRIMARY_QUOTA_REST_S = 600.0  # the first road (Codex) after a quota or sign-in refusal: not asked again for this long
PRIMARY_FAIL_REST_S = 30.0    # after any other failure before its first word
FIRST_TEXT_S = 6.0
MAX_TOKENS = 900
SCREEN_TOKENS = 200           # the answer of a screening request is a dash, a mark or the first words of an answer that is thrown away: the minute of the road is charged this much of it, not MAX_TOKENS
TOKENS_PER_CHAR = 0.35        # what a character of a request weighs until an answer has told (measured 13.11 on the call's instructions: 0.30-0.34 tokens a character)
_REST = {}                    # (key name, model) -> not before; kept across the calls of this process
_BUDGET = {}                  # (key name, model) -> what the provider last said of the road's limits (``limits``): numbers only; kept across the calls of this process
_PRIMARY = {'until': 0.0}
_LOCK = threading.Lock()
_SPAN = re.compile(r'(\d+(?:\.\d+)?)(ms|h|m|s)')
_UNITS = {'ms': 0.001, 's': 1.0, 'm': 60.0, 'h': 3600.0}
_SAID = re.compile(r'\((TPM|TPD|RPM|RPD)\)\s*:\s*Limit\s+(\d+),\s*Used\s+(\d+),\s*Requested\s+(\d+)')      # Groq's own words of a 429
_AGAIN = re.compile(r'try again in\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)')


class ReserveError(Exception):
    """A road's refusal. ``headers``: what its answer said of the key's limits (``_limit_headers``); ``said``: the limit a 429 names, by numbers (``_refusal``). Either may be missing."""
    headers = said = None


def _seconds(text):
    """A provider's duration (``7.66s``, ``360ms``, ``1m2.5s``, a bare number of seconds) in seconds; None when it is none."""
    text = str(text if text is not None else '').strip()
    if re.fullmatch(r'\d+(?:\.\d+)?', text):
        return float(text)
    spans = _SPAN.findall(text)
    if not spans or ''.join(number + unit for number, unit in spans) != text:
        return None
    return round(sum(float(number) * _UNITS[unit] for number, unit in spans), 3)


def _whole(text):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _limit_headers(headers):
    """Of the headers of an answer only those that speak of the key's limits, their names in lower case: never a cookie, an id or a key."""
    try:
        return {str(name).lower(): str(value) for name, value in dict(headers).items() if str(name).lower().startswith('x-ratelimit-') or str(name).lower() == 'retry-after'}
    except Exception:      # noqa: BLE001 - headers nobody can read say nothing
        return {}


def _refusal(body):
    """What a 429 says of the limit it met, by numbers: ``{'kind': 'TPM', 'limit', 'used', 'asked', 'again'}`` (``again``: seconds until it may be asked again); ``{}`` when it names none.
    The words themselves (they hold the organization) are not kept."""
    try:
        text = body.decode('utf-8', 'replace') if isinstance(body, (bytes, bytearray)) else str(body or '')
        found, again = _SAID.search(text), _AGAIN.search(text)
        said = {'kind': found.group(1), 'limit': int(found.group(2)), 'used': int(found.group(3)), 'asked': int(found.group(4))} if found else {}
        if again and _seconds(again.group(1)) is not None:
            said['again'] = _seconds(again.group(1))
        return said
    except Exception:      # noqa: BLE001 - a refusal nobody can read is still a refusal
        return {}


def _cost(event):
    """The numbers of ``usage`` in a chunk of the stream (Groq keeps it under ``x_groq``), named as ``fast_text._usage`` names them; ``{}`` when the chunk has none."""
    usage = (event.get('usage') or (event.get('x_groq') or {}).get('usage')) if isinstance(event, dict) else None
    if not isinstance(usage, dict):
        return {}
    found = {'input_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens'), 'total_tokens': usage.get('total_tokens'),
             'cached_tokens': (usage.get('prompt_tokens_details') or {}).get('cached_tokens'), 'reasoning_tokens': (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')}
    return {name: value for name, value in found.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}


def _note(road, now, headers=None, cost=None, chars=None, allowance=None):
    """Keeps what the provider said of ``road`` = (key name, model): by its headers the tokens of its minute (``limit``, ``left``, ``back`` seconds until all are there, ``at`` on the stream's
    clock) and the requests of its day (``day_limit``, ``day_left``); by the usage of an answer what the request cost (``prompt``, ``cached``, ``out`` tokens for ``chars`` characters) and
    ``spare``: the tokens of its ``allowance`` (max_tokens) the answer did not write - the minute was charged them when the request was asked and has them back when the answer ends."""
    entry = {}
    headers = headers if isinstance(headers, dict) else {}
    limit, left = _whole(headers.get('x-ratelimit-limit-tokens')), _whole(headers.get('x-ratelimit-remaining-tokens'))
    if limit is not None and left is not None and limit > 0:
        entry.update(limit=limit, left=left, at=now, spare=0)
        back = _seconds(headers.get('x-ratelimit-reset-tokens'))
        if back is not None:
            entry['back'] = back
    day_limit, day_left = _whole(headers.get('x-ratelimit-limit-requests')), _whole(headers.get('x-ratelimit-remaining-requests'))
    if day_limit is not None and day_left is not None:
        entry.update(day_limit=day_limit, day_left=day_left)
        day_back = _seconds(headers.get('x-ratelimit-reset-requests'))
        if day_back is not None:
            entry['day_back'] = day_back
    if cost and cost.get('input_tokens') is not None:
        entry.update(prompt=cost['input_tokens'], cached=cost.get('cached_tokens', 0), out=cost.get('output_tokens', 0))
        if chars:
            entry['chars'] = chars
        if isinstance(allowance, int) and not isinstance(allowance, bool):
            entry['spare'] = max(0, allowance - int(cost.get('output_tokens', 0)))
    if entry:
        with _LOCK:
            if 'limit' in entry:
                _BUDGET.get(road, {}).pop('back', None)
            _BUDGET.setdefault(road, {}).update(entry)


def _day_rest(road, now, headers):
    """U50: the requests of the day of ``road`` are all spent by its provider's word (``x-ratelimit-remaining-requests: 0`` and when they return): the road rests until then, not for a minute or ten (the day's
    1 000 are the free quota; a question asked of it meanwhile is a 429 and a request lost). A rest is an order, never a ban: ``Roads.order`` still asks it when no other road is left."""
    headers = headers if isinstance(headers, dict) else {}
    back = _seconds(headers.get('x-ratelimit-reset-requests'))
    if _whole(headers.get('x-ratelimit-remaining-requests')) == 0 and back:
        with _LOCK:
            _REST[road] = max(_REST.get(road, 0.0), now + back)
        logger.warning('echo-sync reserve_text road=%s model=%s day=spent back_s=%d', road[0], road[1], back)


SPEND = ('requests', 'answered', 'cancelled', 'errors', 'input_tokens', 'output_tokens', 'reasoning_tokens', 'cached_tokens')
TOKENS = SPEND[4:]


def _spend(table, *, requests=0, cost=None, cancelled=0, errors=0):
    """U107, E32: ``table`` (a call's count for one kind of road) takes ``requests`` asked, of those the ``cancelled`` ones (let go before their end) and the ones that failed (``errors``), and, of an answer that told its usage
    (``cost``: ``fast_text._usage``, ``_cost``), one answered and its tokens. Numbers only."""
    with _LOCK:
        for key, count in (('requests', requests), ('cancelled', cancelled), ('errors', errors)):
            if count:
                table[key] = table.get(key, 0) + count
        if isinstance(cost, dict) and cost:
            table['answered'] = table.get('answered', 0) + 1
            for key in TOKENS:
                table[key] = table.get(key, 0) + (cost[key] if type(cost.get(key)) is int else 0)


def limits(name, model):
    """What the provider last said of the road (``_note``), as a copy; ``{}`` when it has said nothing yet."""
    with _LOCK:
        return dict(_BUDGET.get((name, model), {}))


# --- the budget: which road a question is asked first ----------------------------------------------------------------------------
# What 60 answers of Groq showed on 13.11 03:41-03:49 (REVIEW_20261112/night/L4_answers.md): the minute of a road (a key with a model: 8 000 tokens) is charged the prompt and the whole of
# max_tokens when the request is asked; its tokens return at limit / 60 a second (the reset header is exactly (limit - left) * 60 / limit); what the answer did not write of max_tokens comes back
# after it. So the room of a road is known without asking it, and a question that would not fit is asked of another road first instead of meeting a 429 and a flat rest.

def _room(road, now):
    """The tokens of the minute of ``road`` = (key name, model) that are there at ``now``, by what its provider last said (``_note``): those left then, those the answer did not write, those
    returned since; never more than the limit. None when the provider has said nothing of the road (a road never asked, a provider that tells no limits)."""
    with _LOCK:
        known = dict(_BUDGET.get(road) or {})
    if not known.get('limit') or known.get('left') is None or known.get('at') is None:
        return None
    return min(float(known['limit']), known['left'] + known.get('spare', 0) + max(0.0, now - known['at']) * known['limit'] / 60.0)


def _weight(body):
    """What the minute of a road is charged when ``body`` is asked: its prompt - the characters by the most tokens a character has cost in an answer so far (``TOKENS_PER_CHAR`` until one has
    told; never more than a token a character: a tiny request tells nothing of a big one) - and the whole of its ``max_tokens``."""
    chars = sum(len(str(message.get('content') or '')) for message in body.get('messages') or ())
    with _LOCK:
        told = [entry['prompt'] / entry['chars'] for entry in _BUDGET.values() if entry.get('prompt') and entry.get('chars')]
    return int(chars * (min(1.0, max(told)) if told else TOKENS_PER_CHAR)) + int(body.get('max_tokens') or 0)


def _told(failure):
    """What a refusal says of the minute of its road, as the headers of an answer say it: its own headers, or - when they name no remainder - the numbers of its words (Limit, Used)."""
    headers, said = dict(getattr(failure, 'headers', None) or {}), getattr(failure, 'said', None) or {}
    if said.get('kind') == 'TPM' and 'x-ratelimit-remaining-tokens' not in headers and said.get('limit') and said.get('used') is not None:
        headers.update({'x-ratelimit-limit-tokens': str(said['limit']), 'x-ratelimit-remaining-tokens': str(max(0, said['limit'] - said['used']))})
    return headers


def _wait(failure):
    """The seconds a provider that refused said to wait (``retry-after``, «try again in»: the longer); None when it named none."""
    said, headers = getattr(failure, 'said', None) or {}, getattr(failure, 'headers', None) or {}
    waits = [wait for wait in (said.get('again'), _seconds(headers.get('retry-after'))) if isinstance(wait, (int, float)) and not isinstance(wait, bool) and wait > 0]
    return max(waits) if waits else None


def read_keys(path=None):
    """``{name: value}`` of the provider keys in the file; ``{}`` when there is none. The values go nowhere but the Authorization header."""
    path = path or environment(ENV_VAR, DEFAULT_ENV)
    found = {}
    try:
        with io.open(path, encoding='utf-8', errors='replace') as lines:
            for line in lines:
                match = re.match(r'\s*((?:GROQ|GEMINI)_API_KEY\w*)\s*=\s*["\']?([^"\'\s#]+)', line)
                if match:
                    found[match.group(1)] = match.group(2)
    except OSError:
        return {}
    return found


def chat_body(request, model, screen=False):
    """The request of the job (``fast_text.build_request``: instructions + user messages) as a chat completion. A reserve road always gets the instructions in their short form
    (``brain_short.brief_instructions``: the short BRAIN, of the material the parts nearest to what was heard: its minute is small); a brief that fails is the instructions as they came.
    ``screen``: the request of a remark with no form of a question (``ReserveStream.one``): the short BRAIN, the last exchanges short, no material, an answer of ``SCREEN_TOKENS`` at most; None when there is no
    material to leave out (the request is its own screen)."""
    system, messages = str(request.get('instructions') or ''), []
    for item in request.get('input') or ():
        text = ' '.join(str(part.get('text') or '') for part in item.get('content') or () if isinstance(part, dict)) if isinstance(item, dict) else ''
        if text.strip():
            messages.append({'role': 'user', 'content': text})
    try:
        from . import brain_short      # noqa: PLC0415 - only a reserve road needs it
        if screen:
            system = brain_short.screen_instructions(system)
            if system is None:
                return None
        else:
            system = brain_short.brief_instructions(system, messages[-1]['content'] if messages else '')
    except Exception as error:      # noqa: BLE001 - the brief is a saving, never a failed job
        logger.warning('echo-sync reserve_text brief=failed type=%s', type(error).__name__)
        if screen:
            return None
    messages.insert(0, {'role': 'system', 'content': system})
    body = {'model': model, 'messages': messages, 'stream': True, 'temperature': 0.2, 'max_tokens': SCREEN_TOKENS if screen else MAX_TOKENS}
    if 'gpt-oss' in model:
        body['reasoning_effort'] = 'low'
    return body


# --- S1: what a reserve road may be sent -------------------------------------------------------------------------------------------------
# Groq and Gemini are PUBLIC third parties (the owner allowed their free keys). The ONE gate of what leaves for such a host is ``privacy_gate.allowed(text, search=True)``, the very gate of the public lookup; every
# request of a reserve road passes ``_sendable`` in ``_talk`` (the only place that posts). What it holds back: a heard question that is not public (the listener's own affairs, a phone, a card); the exchanges of the history
# whose question is not public; the parts of the owner's material that carry contact or document data (an e-mail, a phone, a card, a passport number: the rules of ``privacy_gate``). No rule of content_policy or
# materials marks the material closed (the first road, brain_short and the importer treat it as the lesson the answer stands on), so the rest of it goes as it always did. A failure of the gate holds back too.
_HISTORY_HEAD = 'Последние реплики этого разговора (для связи с вопросом):'
_HISTORY_ENTRY = re.compile(r'(?m)^(?=(?:Вопрос|Прозвучало без ответа): )')
_MATERIAL_BLOCK = re.compile(r'(⟦МАТЕРИАЛЫ ([0-9a-f]{12}) — [^\n]*⟧\n)(.*?)(\n⟦КОНЕЦ МАТЕРИАЛОВ \2⟧)', re.S)
_PARAGRAPH = re.compile(r'\n[ \t]*\n')
_HEARD_MARK = 'Сейчас прозвучало: '


@functools.lru_cache(maxsize=256)
def _public(text):
    """May ``text`` (what was heard, a question of the history) go to a public host? A gate that fails says no."""
    try:
        from . import privacy_gate      # noqa: PLC0415 - only a reserve road needs it
        from .gate_text import public_address_allowed
        return bool(privacy_gate.allowed(text, True) and public_address_allowed(text))
    except Exception:      # noqa: BLE001 - the one policy of a failure: nothing leaves
        return False


def _heard(text):
    """What was heard in the last user text of a job (``fast_text.build_request``: the question, with the answer in play and the ear's other words around it)."""
    text = str(text or '')
    if _HEARD_MARK in text:
        text = text.rsplit(_HEARD_MARK, 1)[1]
    return re.sub(r'^Распознано:\s*', '', text.strip())


def withheld(request):
    """True when the heard question of ``request`` may not go to a reserve road (the roads are not asked, nor rested)."""
    for item in reversed(request.get('input') or ()):
        if isinstance(item, dict):
            text = ' '.join(str(part.get('text') or '') for part in item.get('content') or () if isinstance(part, dict))
            if text.strip():
                return not _public(_heard(text))
    return False


def _contact_free(text):
    """``text`` (a part of the material) holds no e-mail, card or document number and no personal data by shape (phone, account, name, address, secret: ``privacy_gate.personal_data_reason``, independent of the first person); a gate that fails says no."""
    try:
        from . import privacy_gate      # noqa: PLC0415
        return not any(rule.search(text) for rule in (privacy_gate._EMAIL, privacy_gate._DOCUMENT, privacy_gate._CARD)) and privacy_gate.personal_data_reason(text) is None
    except Exception:      # noqa: BLE001
        return False


def _closed(system):
    """``system`` with the material of the owner kept except the parts that carry contact or document data, and without the exchanges whose question is not public; None when a material marker is left that is no whole block (nothing leaves then)."""
    found = _MATERIAL_BLOCK.search(system)
    if found:
        parts = [part for part in _PARAGRAPH.split(found.group(3)) if _contact_free(part)]
        system = system[:found.start()] + found.group(1) + '\n\n'.join(parts) + found.group(4) + system[found.end():]
    head, sep, block = system.partition(_HISTORY_HEAD + '\n')
    if sep:
        kept = [entry for entry in _HISTORY_ENTRY.split(block) if entry.strip() and _public(_heard(entry.partition('\nОтвет: ')[0].partition(': ')[2]))]
        system = head + sep + ''.join(kept) if kept else head.rstrip('\n')
    marks = len(re.findall('⟦МАТЕРИАЛЫ', system))
    return None if marks != (1 if found else 0) else system


def _sendable(body):
    """The body a reserve road may be sent (the contact data of the material and the non-public history out), or None: not sent."""
    messages = body.get('messages') or []
    if not messages or not _public(_heard(messages[-1].get('content'))):
        return None
    system = _closed(str(messages[0].get('content') or ''))
    if system is None:
        return None
    return {**body, 'messages': [{**messages[0], 'content': system}] + messages[1:]}


def _post(url, headers, body, timeout):
    """One dict - what the headers of the answer say of the key's limits (``_limit_headers``) - and then the lines of the streamed answer. Raises ``ReserveError('http_<code>')`` on a
    refusal, with that dict and, for a 429, the limit it names (``_refusal``). A function of its own: the tests give another (theirs may give the lines alone)."""
    import httpx
    with httpx.Client(http2=False, timeout=timeout) as client:
        with client.stream('POST', url, headers=headers, json=body) as response:
            told = _limit_headers(response.headers)
            if response.status_code != 200:
                error = ReserveError(f'http_{response.status_code}')
                error.headers = told
                try:
                    error.said = _refusal(response.read()) if response.status_code == 429 else {}
                except Exception:      # noqa: BLE001 - the refusal stands without its words
                    error.said = {}
                raise error
            yield told
            yield from response.iter_lines()


class ReserveStream:
    """The reserve roads: ``one`` talks to ONE road, ``_order`` says which are asked first; the walk of the roads is ``Roads`` (``stream(request, cancelled)`` is its walk without the first road): the first road that answers gives the whole answer.
    The budget (always): a question is asked first of the roads whose minute holds it (``_order``), a road that refused rests as long as its provider said and not the
    flat ``REST_S``, and after the text the stream gives one ``{'usage': …}`` - what the answer cost and which road gave it - as the first road does (``fast_text._usage``).
    The roads are always sent the instructions in their short form (``chat_body``)."""
    reserve = True

    def __init__(self, keys, *, post=None, clock=None, roads=None):
        self.keys, self.post, self.clock = dict(keys), post or _post, clock or time.monotonic
        self.roads = [road for road in (ROADS if roads is None else roads) if road[0] in self.keys]      # S5: a model source is ONE ROW of ``ROADS`` (key name, base url, model), read when the call starts: a new road is a row and its key, no line of the walk changes (tests/test_r_roads_slot.py)
        self.first_text_s = FIRST_TEXT_S
        self.spent = {}      # U107: what this call asked of the reserve and what the answers told (``_spend``)

    def __bool__(self):
        return bool(self.roads)

    def _order(self, request):
        """The roads in the order this request is asked of them. First, in their own order, those whose minute holds the request by their provider's word (``_room`` against
        ``_weight``) and those nothing is known of; then, in theirs, the roads it would not fit. Those are asked all the same when no road before them answered - the estimate is no verdict,
        and no question has fewer roads than without the order."""
        if not self.roads:
            return self.roads
        if withheld(request):      # S1: no reserve road is asked of a question that is not public; none is rested for it (it asked nothing)
            return []
        try:
            now, need, fits, short = self.clock(), _weight(chat_body(request, self.roads[0][2])), [], []
            for road in self.roads:
                room = _room((road[0], road[2]), now)
                if room is not None and room < need:
                    short.append(road)
                    logger.info('echo-sync reserve_text budget road=%s model=%s room=%d need=%d', road[0], road[2], room, need)
                else:
                    fits.append(road)
            return fits + short
        except Exception as error:      # noqa: BLE001 - the order is a saving, never a failed job
            logger.warning('echo-sync reserve_text budget=failed type=%s', type(error).__name__)
            return self.roads

    def holds(self, road, request):
        """Does the minute of ``road`` = (key name, model) hold ``request`` by its provider's last word (``_room`` against ``_weight``)? None when the provider has said nothing of it."""
        room = _room(road, self.clock())
        return None if room is None else room >= _weight(chat_body(request, road[1]))

    def one(self, name, base, model, request, cancelled, screen=False):
        """ONE road, the whole talk with it: the deltas of its answer (and the usage after the text). A failure is raised as it came; a road with no word ends quietly (``Roads`` says
        ``empty``), a cancelled call returns. What follows a failure (the rest, the next road) is not its business: ``Roads`` owns the roads.
        ``screen`` (U50, the final has no form of a question): the short request first (``chat_body``); «—» is the whole answer (a remark: it cost a fifth of a request), a mark is taken as it came, any word says
        it is a question and the full request goes to the same road, what the short one wrote is never heard."""
        body = chat_body(request, model, screen=True) if screen else None
        if body is None:
            yield from self._talk(name, base, model, chat_body(request, model), cancelled)
            return
        held, stream = '', self._talk(name, base, model, body, cancelled)
        for delta in stream:
            if isinstance(delta, dict):      # the usage of the screen is nobody's
                continue
            held += delta
            if held.lstrip().startswith('['):      # «[стоп]»: a command needs no material
                yield held
                yield from stream
                return
            if re.search(r'\w', held):
                stream.close()
                logger.info('echo-sync reserve_text screen=question road=%s model=%s', name, model)
                yield from self._talk(name, base, model, chat_body(request, model), cancelled)
                return
        if held.strip() and not cancelled.is_set():
            logger.info('echo-sync reserve_text screen=remark road=%s model=%s', name, model)
            yield held

    def _talk(self, name, base, model, body, cancelled):
        body = _sendable(body)      # S1: the one place that posts is the one place that asks the gate
        if body is None:
            logger.info('echo-sync reserve_text withheld road=%s model=%s', name, model)
            return
        began, cost, said = self.clock(), {}, False
        _spend(self.spent, requests=1)
        headers = {'Authorization': 'Bearer ' + self.keys[name], 'Content-Type': 'application/json', 'Accept': 'text/event-stream', 'User-Agent': 'echo-sync/1'}
        for line in self.post(base + '/chat/completions', headers, body, min(self.first_text_s, FIRST_TEXT_S)):
            if cancelled.is_set():
                return
            if isinstance(line, dict):      # the headers of the answer on the key's limits (``_post``)
                _note((name, model), self.clock(), line)
                _day_rest((name, model), self.clock(), line)
                continue
            if not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if not payload or payload == '[DONE]':
                continue
            try:
                event = json.loads(payload)
            except ValueError:
                continue
            cost = _cost(event) or cost
            choices = event.get('choices') if isinstance(event, dict) else None
            delta = (choices[0].get('delta') or {}).get('content') if choices else None
            if isinstance(delta, str) and delta:
                if not said:
                    logger.info('echo-sync reserve_text road=%s model=%s first_ms=%d', name, model, (self.clock() - began) * 1000)
                said = True
                yield delta
        _spend(self.spent, cost=cost)
        if said and cost:
            _note((name, model), self.clock(), cost=cost, chars=sum(len(message['content']) for message in body['messages']), allowance=body.get('max_tokens'))
            yield {'usage': {**cost, 'road': name, 'model': model}}

    def __call__(self, request, cancelled):
        yield from Roads(None, self, clock=self.clock)(request, cancelled)      # the walk of the roads is written once (``Roads``)


NEXT_ROAD_S = 2.0             # a road of the question silent this long: the next road is asked TOO (a refusal before the first word: the next at once). Measured: the median first text of Codex 1.1-1.3 s, its twin at 2.0 s (tail_guard.HEDGE_AFTER_S), the first word of Groq 0.76 s, a whole answer 1.1-2.5 s, Gemini flash-lite 1.2-2.4 s
SPENT_RACE_HOLD_S = 5.0       # U50: a healthy first road that is slow is not raced by a reserve road whose minute cannot hold the question until it has stood this long (then the reserve is asked: the sentence is at REFUSE_AFTER_S)
ALL_DEAD_S = 8.0             # no road has a word this long after the question while the cloud has an answer of its own: the question is let go and handed back to it (controlled_media.ANSWER_WAIT_SECONDS)
GIVE_UP_S = 12.0              # no road has a word this long after the question and the cloud has none: the question is let go (FIRST_TEXT_S=4 killed the answers of the 10-s tail and every stall of the net)
REFUSE_AFTER_S = 8.0          # not later than controlled_media.ANSWER_WAIT_SECONDS (8.0): after that the controller drops the question and the refusal is never said (h31 had 11.0: the apology turned into silence); the refusal stays provisional (F20)
REFUSAL = 'Ответа пока нет. Скажи, что сейчас уточнишь.'      # the honest sentence in place of silence: said once a question when no road has a word and the cloud has none
STALLS = 2                    # silent losses of a road in a row (no word of it between) after which it rests as a refused one: one slow answer of a strong road is no verdict
PRIMARY = 'codex'             # the name of the first road in ``Roads``; the roads of the reserve are ``(key name, model)``
Tried = namedtuple('Tried', 'number key started first_at outcome')      # what the loop shows of a walker (a job): ``key`` is what ``Walk.where`` knows it by


class Walk:
    """The roads of ONE question: which are taken (asked already by a walker of it) and where each walker stands. Thread-safe: the job threads write, the loop reads."""

    def __init__(self, request):
        self.request, self.taken, self.muted, self._at, self._lock = request, set(), set(), {}, threading.Lock()
        self.refused = False      # the honest sentence of the question was decided (once)
        self.screen = False       # U50: the question has no form of a question: a reserve road is first asked in the short form (``ReserveStream.one``)

    def mute(self, host):
        """The host of a silent road is silent for this question: a silence is the host's (every road of it hangs), a refusal is a key's (never marked)."""
        with self._lock:
            self.muted.add(host)

    def take(self, road, key, now):
        """The walker ``key`` asks ``road`` from ``now``; False when a walker of the question has asked it already."""
        with self._lock:
            if road in self.taken:
                return False
            self.taken.add(road)
            self._at[key] = (road, now)
            return True

    def where(self, key):
        """``(road, since)`` the walker stands on, None before its first road."""
        with self._lock:
            return self._at.get(key)

    def left(self, roads):
        """Of ``roads`` those no walker of the question has asked."""
        with self._lock:
            return [road for road in roads if road not in self.taken]


class Roads:
    """THE owner of the roads of text: the first road (Codex) and the reserve behind it. One walker (``__call__``, a job thread) walks the roads in ``order`` and goes on at once from a road that
    fails before its first word; the loop (``fast_text``) decides what silence means (``step``, ``lost``). A rest is an order, never a ban: a road that rests is asked when every road before it has
    failed or stalled for this question (that is how an answer comes back with no new call). Everything else of the first road - ``warm``, ``close``, ``http``, ``first_text_s`` - is its own."""
    reserve = True

    def __init__(self, primary, reserve, *, clock=None):
        self.__dict__.update(primary=primary, backup=reserve, clock=clock or time.monotonic, _stalls={}, _guard=threading.Lock(), _spent={})

    def __getattr__(self, name):
        primary = self.__dict__.get('primary')
        if primary is None:
            raise AttributeError(name)
        return getattr(primary, name)

    def __setattr__(self, name, value):
        if name == 'first_text_s' and self.primary is not None and hasattr(self.primary, name):
            setattr(self.primary, name, value)
        else:
            self.__dict__[name] = value

    def __bool__(self):
        return self.primary is not None or bool(self.backup)

    def spend(self):
        """U107: what this call has spent, by numbers: ``{'codex': {...}, 'reserve': {...}}`` with ``SPEND`` in each (requests asked, answers that told their usage, E32: requests of the first road that were cancelled and that failed - so the share of use, answered of asked, can be told from
        the trace - input, output, reasoning and cached tokens). A request of the first road that was let go is counted as asked and as cancelled; its tokens are known only when its answer ended."""
        with _LOCK:
            return {kind: {key: int(table.get(key, 0)) for key in SPEND} for kind, table in (('codex', self._spent), ('reserve', self.backup.spent if self.backup is not None else {}))}

    def names(self):
        return ([PRIMARY] if self.primary is not None else []) + [(name, model) for name, _, model in (self.backup.roads if self.backup else ())]

    @staticmethod
    def _until(road):
        with _LOCK:
            return _PRIMARY['until'] if road == PRIMARY else _REST.get(road, 0.0)

    def resting(self, road, now):
        return now < self._until(road)

    def alive(self, now=None):
        """Some road does not rest now."""
        now = self.clock() if now is None else now
        return any(not self.resting(road, now) for road in self.names())

    def order(self, request):
        """The roads in the order this question is asked of them: those that do not rest (the first road, then the reserve in its own order, the budget's included), then those that rest, the one whose rest ends first first."""
        now = self.clock()
        roads = ([PRIMARY] if self.primary is not None else []) + [(name, model) for name, _, model in (self.backup._order(request) if self.backup else ())]
        return [road for road in roads if not self.resting(road, now)] + sorted((road for road in roads if self.resting(road, now)), key=self._until)

    def host(self, road):
        """The host a road talks to: the first road is ``codex``, a reserve road its base url."""
        return PRIMARY if road == PRIMARY else next((base for name, base, model in self.backup.roads if (name, model) == road), road)

    def pick(self, walk, order):
        """The roads of ``order`` (the walker's, made when it started) this walk has not taken: those of a host not marked silent for the question first, then the others (a silent host is the last resort, never a ban)."""
        left, muted = walk.left(order), walk.muted.copy()
        return [road for road in left if self.host(road) not in muted] + [road for road in left if self.host(road) in muted]

    def _ask(self, road, request, cancelled, walk):
        if road == PRIMARY:
            return self.primary(request, cancelled)
        base = next(base for name, base, model in self.backup.roads if (name, model) == road)
        return self.backup.one(road[0], base, road[1], request, cancelled, screen=walk.screen)

    def __call__(self, request, cancelled, walk=None):
        """ONE walker: the generator of a job thread. A road that fails (or ends with no word) before its first word rests and the next is asked at once; after the first word a failure is the job's.
        Cancelled: returns, records nothing (the loop knows why: ``lost``). No road left: the last failure, or ``no_road``."""
        walk, failure, order = walk or Walk(request), None, self.order(request)
        while True:      # the walk is asked anew for every road: a mark of a silent host may have come while this walker went
            road = next((one for one in self.pick(walk, order) if walk.take(one, cancelled, self.clock())), None)
            if road is None:
                break
            if cancelled.is_set():
                return
            said, held, mine = False, '', (self._spent if road == PRIMARY else None)      # E32: the table of the first road, whose request ends as an answer, a cancel or an error (one of them, once)
            try:
                if mine is not None:
                    _spend(mine, requests=1)
                for delta in self._ask(road, request, cancelled, walk):
                    if cancelled.is_set():
                        if mine is not None:
                            _spend(mine, cancelled=1)
                        return
                    if isinstance(delta, dict) and road == PRIMARY:
                        _spend(self._spent, cost=delta.get('usage'))
                    if not said:
                        if not isinstance(delta, str):
                            continue      # a usage of a road that has said nothing is nobody's
                        if not delta.strip():
                            held += delta      # a word is a delta with a character that is not a space: blanks before it are held and go with it (a road of blanks only says nothing: 'empty')
                            continue
                        said, delta, held = True, held + delta, ''
                        self.spoke(road)
                    yield delta
                if said:
                    return
                if mine is not None:
                    _spend(mine, cancelled=int(cancelled.is_set()), errors=int(not cancelled.is_set()))
                if cancelled.is_set():
                    return
                failure = ReserveError('empty')      # a road that ends with no word and no error
            except Exception as error:      # noqa: BLE001 - a road that fails is the turn of the next road; after its first word the failure is the job's
                if mine is not None:
                    _spend(mine, cancelled=int(cancelled.is_set()), errors=int(not cancelled.is_set()))
                if cancelled.is_set():
                    return
                if said:
                    self._rest(road, error)      # a road that broke after its word rests as one that broke before it: the retry of the controller gets the order with it last (the failure is still the job's, no text of another road is mixed in)
                    raise
                failure = error
            self._rest(road, failure)
        raise failure or ReserveError('no_road')

    def _rest(self, road, failure):
        """``road`` failed before its first word: it rests (the first road: long after a quota or a sign-in, short after anything else; a reserve road: as long as its provider said, or ``REST_S``)."""
        now = self.clock()
        if road == PRIMARY:
            quota = any(mark in f'{type(failure).__name__} {failure}' for mark in ('429', '401', '403', 'TokenError', 'usage'))
            with _LOCK:
                _PRIMARY['until'] = now + (PRIMARY_QUOTA_REST_S if quota else PRIMARY_FAIL_REST_S)
            logger.warning('echo-sync reserve_text primary=rest quota=%d reason=%s', int(quota), type(failure).__name__)
            return
        rest = REST_S
        if isinstance(failure, ReserveError):
            _note(road, now, _told(failure))      # what a refusal says of the minute is its provider's word as an answer's headers are
            wait = _wait(failure)
            if wait is not None:      # the provider named the wait: that long (a day's limit: asked again as the first road is), not the flat minute
                rest = wait if (getattr(failure, 'said', None) or {}).get('kind') in ('RPD', 'TPD') else min(wait, PRIMARY_QUOTA_REST_S)      # a day's limit is the provider's reset, a minute's is capped
        with _LOCK:
            _REST[road] = now + rest
        if isinstance(failure, ReserveError):
            _day_rest(road, now, _told(failure))      # the day's own word (remaining 0, its reset) lengthens it
        logger.warning('echo-sync reserve_text road=%s model=%s refused reason=%s', road[0], road[1], str(failure)[:40] if isinstance(failure, ReserveError) else type(failure).__name__)

    def spoke(self, road):
        """A road gave its first word (thread side): its silent losses in a row are no more."""
        with self._guard:
            self._stalls[road] = 0

    def lost(self, walk, key, now):
        """The loop: the walker ``key`` was cancelled or let go with no word. If it stood on its road ``NEXT_ROAD_S`` or more that is a stall of the road; ``STALLS`` in a row rest it as a failed one
        (the count then stays one short of it: the next trial that stalls rests it again)."""
        at = walk.where(key)
        if at is None or now - at[1] < NEXT_ROAD_S:
            return
        road = at[0]
        with self._guard:
            count = self._stalls[road] = self._stalls.get(road, 0) + 1
            if count < STALLS:
                return
            self._stalls[road] = STALLS - 1
        with _LOCK:
            if road == PRIMARY:
                _PRIMARY['until'] = max(_PRIMARY['until'], now + PRIMARY_FAIL_REST_S)
            else:
                _REST[road] = max(_REST.get(road, 0.0), now + REST_S)
        logger.warning('echo-sync reserve_text road=%s stalled=%d rest=1', road if road == PRIMARY else road[0] + '/' + road[1], STALLS)

    def _held(self, now, one, walk, left, stood):
        """U50 (the Codex quota and the free minute of the reserve are both spent by a slow first road raced every question): the race against a first road that is healthy (it flies, it does not rest) and only slower than
        ``NEXT_ROAD_S`` is held while the road to be asked next is known not to hold the question in its minute (``ReserveStream.holds`` False), until the first road has stood ``SPENT_RACE_HOLD_S``. Only that: a first road
        that failed or rests, a next road with room or with no word of its provider, a first road later than the hold - the next road is asked as ever, so no question goes silent for it."""
        at = walk.where(one.key)
        if self.backup is None or at is None or at[0] != PRIMARY or stood >= SPENT_RACE_HOLD_S or self.resting(PRIMARY, now):
            return False
        nxt = self.pick(walk, left)[:1]
        held = bool(nxt) and nxt[0] != PRIMARY and self.backup.holds(nxt[0], walk.request) is False
        if held:
            logger.info('echo-sync reserve_text race=held road=%s model=%s stood_s=%.1f', nxt[0][0], nxt[0][1], stood)
        return held

    def _silent(self, walk, one):
        at = walk.where(one.key)
        if at is not None:
            walk.mute(self.host(at[0]))

    def step(self, now, tried, walk, *, asked, give_up, refuse_at=None, cloud_silent=True):
        """``_decide`` and the honest sentence: with no word of any walker once ``now`` is ``refuse_at`` and the cloud is silent, ``('refuse', n)`` (once a question: ``walk.refused``); ``refuse_at`` None: none."""
        acts = self._decide(now, tried, walk, asked=asked, give_up=give_up)
        if refuse_at is not None and cloud_silent and now >= refuse_at and tried and not walk.refused and not any(act == 'win' for act, _ in acts) and not any(one.first_at is not None and one.outcome in (None, 'ok') for one in tried):
            walk.refused = True
            acts.append(('refuse', tried[0].number))
        return acts

    def _decide(self, now, tried, walk, *, asked, give_up):
        """The loop's decision for the open question, by what its walkers show (``Tried``): ``('win', n)`` the first text (the others ``('cancel', m)``); with no text: ``('stall', n)`` a walker let go
        (``give_up`` since ``asked``, or a reserve walker silent ``2 * NEXT_ROAD_S`` on its road while a road is left to take its place: never the first road), ``('next', None)`` one more walker (a road is left, and nobody flies or the one that flies has been silent ``NEXT_ROAD_S``),
        ``('dead', None)`` (``give_up`` is over, or nobody flies and no road is left; the walkers that fly with no road left live to ``give_up``). Never more than two fly. Numbers only: no word of the dialogue passes here."""
        texted = [one for one in tried if one.first_at is not None and one.outcome in (None, 'ok')]
        if texted:
            win = min(texted, key=lambda one: (one.outcome != 'ok', one.first_at, one.number))      # a whole answer beats a begun one that may still break; then the earlier first word
            return [('win', win.number)] + [('cancel', one.number) for one in tried if one.number != win.number and one.outcome in (None, 'ok')]      # one speaker: the finished loser is let go too
        flying = [one for one in tried if one.outcome is None]
        if now - asked >= give_up:      # before any branch that says nothing: no question outlives the give-up time with a walker that flies and no word
            logger.warning('echo-sync reserve_text roads=dead after_s=%.1f flying=%d', now - asked, len(flying))
            return [('stall', one.number) for one in flying] + [('dead', None)]
        if not flying and any(one.first_at is not None for one in tried):      # the job spoke and broke: after its first word the failure is the job's, no other road is asked (the channel shows no other walker's word: nobody heard it)
            return []

        def stood(one):
            at = walk.where(one.key)
            return now - (at[1] if at else one.started)
        left = walk.left(self.order(walk.request))
        stalled = [one for one in flying if stood(one) >= 2 * NEXT_ROAD_S and (walk.where(one.key) or (None,))[0] != PRIMARY] if left else []      # a walker is let go for the stall only to free the place of the next road, and then a silent RESERVE walker: the first road, slow but correct, lives to ``give_up`` (the triple coincidence: it is never given up for a reserve that is silent too); with no road left every walker lives to ``give_up``
        acts, rest = [('stall', one.number) for one in stalled], [one for one in flying if one not in stalled]
        for one in stalled:
            self._silent(walk, one)
        for one in stalled:
            logger.warning('echo-sync reserve_text road stalled after_s=%.1f', stood(one))
        if not rest and not left:
            logger.warning('echo-sync reserve_text roads=dead no_road_left')
            return acts + [('dead', None)]
        if left and (not rest or (len(rest) == 1 and stood(rest[0]) >= NEXT_ROAD_S)):
            if rest and self._held(now, rest[0], walk, left, stood(rest[0])):
                return acts
            for one in rest:
                if stood(one) >= NEXT_ROAD_S:
                    self._silent(walk, one)      # asked for the silence of the flying one: its host is marked (a refusal marks nothing)
            logger.info('echo-sync reserve_text next road asked after_s=%.1f', now - asked)
            acts.append(('next', None))
        return acts


def for_stream(primary, *, keys=None):
    """``primary`` with the reserve behind it: always ``Roads``, the one owner of the roads (the file with no key gives an empty reserve: the first road alone)."""
    reserve = ReserveStream(read_keys() if keys is None else keys)
    if not reserve:
        logger.warning('echo-sync reserve_text reserve=empty reason=no_keys')
    return Roads(primary, reserve)
