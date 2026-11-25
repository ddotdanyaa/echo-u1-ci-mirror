"""The reserve of the web search (the order of the owner of 11.11.2026: «веб-поиск надо вернуть»; the call's own search needs the cloud
that was out). One request to Groq's built-in ``browser_search`` with the keys the reserve of the text uses (``reserve_text.read_keys``:
never copied, never logged). The answer comes back in the shape the call's lookup gives - rows ``{'url', 'title', 'text'}`` - so nothing of
the controller changes: its gate of privacy, its grounding, its «no source» are the usual ones.

Probe of 11.11 10:05 from this laptop (``scripts/groq_search_probe.py``, one request, ``openai/gpt-oss-20b``): 200 in 3.1 s, 4 574 tokens.
A road that refuses rests as the text's roads do (``reserve_text.REST_S``)."""
import logging, re, time

from . import reserve_text
from .timer_policy import LOOKUP_TIMEOUT_S

logger = logging.getLogger('echo-sync')
SEARCH_S = LOOKUP_TIMEOUT_S      # the whole search of one road IS the call's lookup bound (timer_policy.LOOKUP_TIMEOUT_S), one number
MODELS = ('openai/gpt-oss-20b', 'openai/gpt-oss-120b')
KEYS = ('GROQ_API_KEY', 'GROQ_API_KEY_2')
ASK = ('Найди в интернете ответ на вопрос и ответь кратко по-русски: факт, имя, дата или число, одной-двумя фразами. '
       'Называй только то, что нашёл; если не нашёл - скажи «не нашёл».')
FOUND_CHARS, TEXT_CHARS = 1200, 1500
_URL = re.compile(r'https?://[^\s\'"<>\])】]+')
_MARK = re.compile(r'【[^】]*】')
NO_URL = 'https://console.groq.com/docs/browser-search'


def _post(url, headers, body, timeout):
    """The JSON of the answer; raises ``ReserveError('http_<code>')`` on a refusal. A function of its own: the tests give another."""
    import httpx
    with httpx.Client(http2=False, timeout=timeout) as client:
        response = client.post(url, headers=headers, json=body)
        if response.status_code != 200:
            raise reserve_text.ReserveError(f'http_{response.status_code}')
        return response.json()


def search(question, *, keys=None, post=None, clock=None):
    """Rows of the search for ``question`` (one row: what was found, its first address), ``[]`` when no road answers. Blocking: run off the loop."""
    keys = reserve_text.read_keys() if keys is None else keys
    post, clock = post or _post, clock or time.monotonic
    for model in MODELS:
        for name in KEYS:
            if name not in keys:
                continue
            road = (name, 'search:' + model)
            with reserve_text._LOCK:
                if clock() < reserve_text._REST.get(road, 0.0):
                    continue
            began = clock()
            try:
                body = {'model': model, 'messages': [{'role': 'system', 'content': ASK}, {'role': 'user', 'content': str(question)}],
                        'tools': [{'type': 'browser_search'}], 'tool_choice': 'required', 'temperature': 0.2, 'max_tokens': 500, 'reasoning_effort': 'low'}
                headers = {'Authorization': 'Bearer ' + keys[name], 'Content-Type': 'application/json', 'User-Agent': 'echo-sync/1'}
                message = post(reserve_text.GROQ + '/chat/completions', headers, body, SEARCH_S)['choices'][0]['message']
                said = _MARK.sub('', str(message.get('content') or '')).strip()
                if not said:
                    raise reserve_text.ReserveError('empty')
                found = ' '.join(str(tool.get('output') or '') for tool in message.get('executed_tools') or () if isinstance(tool, dict))
                url = next(iter(_URL.findall(found)), NO_URL).rstrip('.,;')
                logger.info('echo-sync reserve_search road=%s model=%s ms=%d chars=%d', name, model, (clock() - began) * 1000, len(said))
                return [{'url': url, 'title': 'web search', 'text': (said + '\n' + found[:FOUND_CHARS])[:TEXT_CHARS]}]
            except Exception as error:      # noqa: BLE001 - a road that fails is the turn of the next road
                with reserve_text._LOCK:
                    reserve_text._REST[road] = clock() + reserve_text.REST_S
                logger.warning('echo-sync reserve_search road=%s model=%s refused reason=%s', name, model,
                               str(error)[:40] if isinstance(error, reserve_text.ReserveError) else type(error).__name__)
    return []
