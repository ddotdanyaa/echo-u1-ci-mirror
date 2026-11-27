"""One private subscription request per unknown question; no display/audio callbacks."""
from __future__ import annotations

import json
import ipaddress
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from .followup import is_followup
from .provider_rule import official_codex      # the one rule of the endpoint lives in provider_rule (read here, by the plugin and by the installer)
from .textutil import NUMBER_WORDS, strip_process_prefix
from .timer_policy import GENERATOR_HTTP_TIMEOUT_S


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


VERIFICATION_UNAVAILABLE = 'Не удалось проверить источники. Попробуйте уточнить вопрос.'


def _unavailable():
    """The one answer of a question that needs a source when none was verified (the search did not complete, no source, nothing to say, or the generation failed)."""
    return SourcedAnswer(VERIFICATION_UNAVAILABLE, retrieval_status='unavailable')


class SourcedAnswer(str):
    """Spoken text plus durable provenance; source-backed is not a truth guarantee."""
    def __new__(cls, text, sources=(), *, retrieval_status='source_backed'):
        result = super().__new__(cls, text)
        result.sources = tuple(dict(source) for source in sources)
        result.retrieval_status = retrieval_status
        result.retrieved_at = datetime.now(timezone.utc).isoformat()
        return result


class StreamingAnswer(SourcedAnswer):
    """A producer-confirmed immutable prefix, not raw unfinished model tokens.

    The producer must hold incomplete words/units and semantic corrections.
    Provenance is checked before a verified question may publish its prefix.
    """
    def __new__(cls, text, sources=(), *, final=False, retrieval_status='unverified',first_chunk=None,raw_text=None):
        result = super().__new__(cls, text, sources, retrieval_status=retrieval_status)
        result.final = bool(final)
        result.first_chunk=first_chunk
        result.raw_text=text if raw_text is None else str(raw_text)   # c8: the model's own text the cue was made from (its hedge kept)
        return result


# c8: the hedge an answer from memory opens with when the lookup gave no source (ControlledMedia.without_source). The model is asked for it (it
# keeps the model careful about rates, sums and dates); the engine takes such an answer ('unsourced') to a question that needs verification
# only when the MODEL's text has it (StreamingAnswer.raw_text). C8 ruling: the listener repeats every portion aloud in front of the examiner,
# so the hedge is never cued - the controller strips it (``unhedged``) and never adds one.
_HEDGE = re.compile(r'^\s*(?:по\s+памяти|без\s+проверки|насколько\s+(?:я\s+)?помню)\s*[:,—–-]\s*', re.I)
_HEDGE_FORMS = ('по памяти:', 'без проверки:', 'насколько помню,', 'насколько я помню,')


def hedged(text, question=''):
    """Does ``text`` open with the hedge of an answer from memory («По памяти: …», «Без проверки: …», «Насколько помню, …»)? Wave G: the text is
    judged after the cloud's process lead, which is never spoken: «Сейчас гляну формулировку. По памяти, статья 27 …» is hedged."""
    text = str(text or '')
    return bool(_HEDGE.match(text) or _HEDGE.match(strip_process_prefix(text, question)))


def unhedged(text):
    """``text`` without its opening hedge, the next word capitalised («По памяти: статья 218.» -> «Статья 218.»); as it is without one. A
    text that may still become a hedge while it streams («По», «По памяти», «Насколько») is ``''``: nothing to cue yet."""
    text = str(text or '')
    found = _HEDGE.match(text)
    if found:
        rest = text[found.end():]
        return rest[:1].upper() + rest[1:]
    folded = ' '.join(text.casefold().split())
    if folded and any(form.startswith(folded) for form in _HEDGE_FORMS):
        return ''
    return text


# Candidate 8 audit, ruling B: the classes of ``route_need`` whose answer CHANGES - a rate, a sum, a limit, a price or a fine, a deadline,
# what holds «сейчас / сегодня / в этом году», the current wording of a norm and its latest changes. When the lookup gives no source, such a
# question is never answered from memory (``ControlledMedia.without_source``): the honest result is «Не нашёл». A STABLE reference - an article's
# number, title or subject, a definition, history - may still be answered from memory, hedged.
_NOW = re.compile(r'\b(?:сегодня|сейчас|актуальн\w*|нынешн\w*|текущ\w*)\b|\bв\s+(?:этом|текущем|нынешнем|следующем|прошлом)\s+году\b|'
                  r'\b(?:на|в|с)\s+20\d\d\b|\b20\d\d\s+год|последн\w*\s+(?:новост\w*|изменен\w*|поправк\w*|редакци\w*)|'
                  r'\bизменени\w*\b.*\b(?:закон\w*|норм\w*|кодекс\w*|правил\w*|ставк\w*)|\b(?:закон\w*|норм\w*|кодекс\w*|правил\w*)\b.*\bизмени\w*')
_VALUE_ASKED = re.compile(r'\b(?:сколько|кака[яю]|како\w*|каки\w*|каков\w*|размер\w*|сумм\w*|величин\w*|до\s+какого|с\s+какого|когда)\b')
_VALUE_NOUNS = re.compile(r'\b(?:процент\w*|ставк\w*|ндс|ндфл|мрот|лимит\w*|взнос\w*|\w*пошлин\w*|пенси\w*|пособи\w*|положен[аоы]?\b|'
                          r'полага\w*|курс\w*|цен[аеуы]\b|стоимост\w*|штраф\w*|срок\w*\s+(?:уплат\w*|сдач\w*|подач\w*)|тариф\w*|'
                          r'порог\w*|прожиточн\w*)')     # «вычет» is a word of the test packs (N20): a deduction question asks a sum or «положен»


_SUM_ASKED = re.compile(r'\bсколько\s+(?:\w+\s+){0,2}?(?:начисл\w*|получ\w*|составл?\w*|выйд\w*|будет|заплат\w*|верн\w*|набеж\w*|остан\w*|остал\w*)')


def _percent_sum(text):
    if not (_SUM_ASKED.search(text) or re.search(r'\bкака[яю]\s+будет\s+сумм\w*', text)) or {m.group()[:7] for m in _VALUE_NOUNS.finditer(text)} - {'процент'}:
        return False
    return len(re.findall(r'\d+', text)) + sum(1 for w in re.findall(r'\w+', text) if w in NUMBER_WORDS) >= 2


# c25-b G10 (c24-e): a leading sentence of pause words alone («Сейчас, подожди, я подумаю.») is no part of the question: its «сейчас» is no live datum
_PAUSE_LEAD = re.compile(r'^\s*(?:(?:ну|так|вот|сейчас|щас|подожди(?:те)?|погоди(?:те)?|секунд(?:у|очку)|минут(?:у|ку|очку)|я|дай(?:те)?|подума(?:ю|ть)|соображу|вспомню)[\s,.\-–—]*)+[.!…]+\s*', re.I)

# a word inside a settled defined term is no question about the current moment: «коэффициент текущей ликвидности»
_STABLE_TERM = re.compile(r'\bкоэффициент\w*\s+текущ\w*\s+ликвидност\w*', re.I)

CHANGES, LOOKUP = 'changes', 'lookup'      # the two levels of ``route_need`` (falsy: ''): CHANGES is the LOOKUP whose answer changes, so it is never answered from memory


def route_need(question, history=()):
    """The router's ONE verdict on whether a question needs a source (merge route 16.11 of two older answers
    to the same question, the second only under ``fast_call``). ``''``: nothing to look up (a settled fact, a computation, a personal matter);
    ``LOOKUP``: a source is wanted (the listener's «проверь», an article's number, a tax, a rate asked about) - a stable reference may still be
    answered from memory, hedged; ``CHANGES`` (Candidate 8 audit, ruling B: a rate, a sum, a limit, a price or a fine, what holds «сейчас / в этом
    году», the current wording of a norm): with no source it is never answered from memory (``ControlledMedia.no_source``: «Не нашёл»). An
    elliptical follow-up («а почему?», «сколько?», «исправь») inherits the level of the question before it, and ``LOOKUP`` at least when that
    answer was source-backed or unavailable. Deterministic, not a learned confidence classifier."""
    text = str(question or '').casefold().replace('ё', 'е')
    text = _PAUSE_LEAD.sub('', text, count=1) or text
    if _NOW.search(_STABLE_TERM.sub(' ', text)):
        return CHANGES
    if re.search(r'\bдействующ\w*\b', text) and re.search(r'\b(?:закон\w*|норм\w*|редакци\w*|ставк\w*)\b', text):
        return CHANGES
    if _VALUE_ASKED.search(text) and _VALUE_NOUNS.search(text) and not _percent_sum(text):
        return CHANGES
    if re.search(r'\b(?:проверь(?:те)?|проверить|найди(?:те)?|поищи(?:те)?|сверь(?:те)?)\b', text):
        return LOOKUP
    if re.search(r'\b(?:стать[яиюе]|пункт)\s+\d+\b|\b\d+(?:-[а-я]+)?\s+стать[яиюе]\b', text):
        return LOOKUP
    if re.search(r'\bстать[яиюе]\b',text) and re.search(r'\b(?:кодекс\w*|конституци\w*|закон\w*|нк|тк|гк|ук|коап|ск)\b',text):
        return LOOKUP
    # F3 fix round 1: an AMOUNT, a rate, a limit or a legal date is a fact that changes with the law («Какой НДС в России?», «Какой МРОТ?», «До какого
    # числа платить налог?»): it is looked up, never answered from memory, and the model is never told that nothing needs searching.
    # integ9: what the law ENTITLES one to («положена», «полагается») is such a fact too - a class, instead of one tax word (T-B N20).
    if re.search(r'\b(?:сколько|како[йеюя]\w*|каков\w*|размер\w*|сумм\w*|до\s+какого|с\s+какого)\b', text) and re.search(r'\bналог\w*', text):
        return LOOKUP
    # A short independent question is not necessarily a follow-up. Inherit only for an elliptical utterance, not every six-word why.
    # the correction of the answer before («исправь», «я имел в виду») hangs on it as well; the ellipsis is the one rule of ``followup``
    asked = [str(item.get('question') or '') for item in history or () if isinstance(item, dict)]
    if history and ((asked and is_followup(text, asked)) or re.match(r'^(?:нет[,\s]+)?(?:исправь(?:те)?|поправь(?:те)?|я\s+имел[а]?\s+в\s+виду)\b', text)):
        previous = history[-1] if isinstance(history[-1], dict) else {}
        inherited = route_need(previous.get('question', ''), history[:-1])
        return inherited or (LOOKUP if previous.get('retrieval_status') in {'source_backed', 'unavailable'} else '')
    return ''


def _citation_source(annotation):
    if _field(annotation,'type') != 'url_citation':
        return None
    url = _field(annotation,'url','')
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').casefold().rstrip('.')
        if parsed.scheme != 'https' or not host or '.' not in host or host.isdigit() \
                or parsed.username is not None or parsed.password is not None or parsed.port not in (None,443) \
                or host == 'localhost' or host.endswith(('.localhost','.local','.internal')) \
                or any(k.casefold() in {'token','api_key','apikey','access_token','password','auth','signature'} for k,_ in parse_qsl(parsed.query)):
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
    except (ValueError, TypeError):
        return None
    return {'url':url, 'title':str(_field(annotation,'title','') or '')[:300]}


def _spoken_search_text(text):
    # Citation metadata is retained separately; don't read provider's citation
    # control tokens aloud. No arbitrary numbers/units/negations are removed.
    return re.sub(r'\ue200cite\ue202[^\ue201]*\ue201', '', text).strip()


class PrivateCodexGenerator:
    def __init__(self, *, resolve=None, client_factory=None, headers=None, trace_path=None, clock=None):
        self.resolve = resolve
        self.client_factory = client_factory
        self.headers = headers
        self.trace_path = trace_path
        self.clock = clock or time.monotonic

    @staticmethod
    def _cancelled(event, is_current=None):
        if event is not None and event.is_set():
            return True
        if is_current is not None:
            try:
                return not is_current()
            except Exception:
                return True
        return False

    def generate_cancellable(self, question, history, context, request, model, *, cancellation_event=None, is_current=None):
        """The one entry of the road: generate with cancellation checks at request and yielded-event boundaries (both default: never cancelled)."""
        trace = None
        if self.trace_path is not None:
            try:
                from .generation_telemetry import GenerationTelemetryCollector, GenerationTrace
                trace = GenerationTrace(GenerationTelemetryCollector(self.trace_path), self.clock)
            except Exception:
                pass
        outcome = 'error'
        need = route_need(question, history)      # the router's ONE verdict (``route_need``, as cm-route reads it), made once for this question: the search below and the refusal after a failure read it
        try:
            if self._cancelled(cancellation_event,is_current):
                raise RuntimeError('Private answer generation was superseded')
            result = self._generate_inner(question, history, context, request, model, need,
                cancellation_event=cancellation_event, is_current=is_current, trace=trace)
            outcome = 'error' if getattr(result,'retrieval_status',None) == 'unavailable' else 'success'
            return result
        except Exception as exc:
            if (isinstance(exc,RuntimeError) and str(exc) == 'Private answer generation was superseded') \
                    or self._cancelled(cancellation_event,is_current):
                outcome = 'cancelled'
                raise RuntimeError('Private answer generation was superseded') from None
            if need:
                return _unavailable()
            raise
        finally:
            try:
                if trace is not None:
                    trace.finish(outcome)
            except Exception:
                pass

    def _generate_inner(self, question, history, context, request, model, need, *, cancellation_event=None, is_current=None, trace=None):
        seen_first_event = False
        seen_first_delta = False
        settled_text = {}
        settled_positions = {}
        search_needed = need      # read, not made here: ``generate_cancellable`` asked the router's one verdict (``route_need``) once
        search_completed = False
        sources_by_part = {}

        def part_key(value, content_index=None, item=None):
            identity = _field(value,'item_id') or _field(item,'id')
            return (('id',identity) if identity else ('index',_field(value,'output_index',0)),
                    _field(value,'content_index',0) if content_index is None else content_index)

        def cite(annotation,key):
            source = _citation_source(annotation)
            if source and sum(len(v) for v in sources_by_part.values()) < 32:
                sources_by_part.setdefault(key,{})[source['url']] = source
        def mark(name):
            try:
                if trace is not None:
                    trace.mark(name)
            except Exception:
                pass
        if self._cancelled(cancellation_event, is_current):
            raise RuntimeError('Private answer generation was superseded')
        if self.resolve is None:
            from hermes_cli.auth_codex import resolve_codex_runtime_credentials
            resolve = resolve_codex_runtime_credentials
        else:
            resolve = self.resolve
        credentials = resolve()
        mark('credentials_resolve')
        base_url = credentials.get('base_url') or 'https://chatgpt.com/backend-api/codex'
        token = credentials.get('api_key') or ''
        if not official_codex(base_url) or token.count('.') != 2 or token.startswith('sk-'):
            raise ValueError('Only the existing official Codex OAuth credentials are accepted')
        if self.client_factory is None:
            from openai import OpenAI
            factory = OpenAI
        else:
            factory = self.client_factory
        if self.headers is None:
            from agent.codex_headers import codex_cloudflare_headers
            headers = codex_cloudflare_headers
        else:
            headers = self.headers
        # This private client is never bound to the foreground agent callbacks.
        # No next_call, AIAgent.run_conversation, tools, or recursive middleware.
        if self._cancelled(cancellation_event, is_current):
            raise RuntimeError('Private answer generation was superseded')
        client = factory(api_key=token, base_url=base_url, default_headers=headers(token, base_url=base_url), max_retries=0, timeout=GENERATOR_HTTP_TIMEOUT_S)
        mark('client_setup')
        try:
            private = {'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': question}]}]}
            if isinstance(request.get('reasoning'), dict):
                private['reasoning'] = request['reasoning']
            private['model'] = model
            private['store'] = False
            private['stream'] = True  # Consumer Codex is SSE-only; consume it privately.
            private['instructions'] = (
                'Режим подготовки устного ответа. Ответь по-русски связным обычным текстом, '
                'без Markdown, списков, заголовков и служебных фраз. Не используй инструменты. '
                'Дай полный ответ на текущий вопрос; разбиение на произносимые порции выполняет программа. '
                'Опирайся на предоставленные документы, не выдумывай отсутствующие сведения.\n'
                'Документы:\n' + str(context or '') + '\n'
                'Полные предыдущие вопросы и ответы (не путать с повторением слов):\n' +
                json.dumps(history, ensure_ascii=False) + '\nТекущий вопрос:\n' + question
            )
            if search_needed:
                # Reuse Hermes Codex transport's native built-in contract. No
                # client tools, API-key backend, retry or managed paid fallback.
                private['tools'] = [{'type':'web_search'}]
                private['instructions'] = private['instructions'].replace('Не используй инструменты.',
                    'Выполни веб-поиск для проверки текущего вопроса. Предпочитай официальные первоисточники, '
                    'проверь дату действия и противоречия. Если достоверных данных нет, прямо скажи об этом. '
                    'Добавь цитаты источников средствами веб-поиска; не читай URL в тексте устного ответа.')
            if self._cancelled(cancellation_event, is_current):
                raise RuntimeError('Private answer generation was superseded')
            stream = client.responses.create(**private)
            mark('request_create')
            try:
                iterator = iter(stream)
                while True:
                    if self._cancelled(cancellation_event, is_current):
                        raise RuntimeError('Private answer generation was superseded')
                    try:
                        event = next(iterator)
                    except StopIteration:
                        break
                    if self._cancelled(cancellation_event, is_current):
                        raise RuntimeError('Private answer generation was superseded')
                    event_type = getattr(event, 'type', '')
                    if trace is not None and not seen_first_event:
                        mark('first_event'); seen_first_event = True
                    if trace is not None and event_type == 'response.output_text.delta' and not seen_first_delta:
                        mark('first_delta'); seen_first_delta = True
                    if event_type in {'response.failed', 'response.incomplete', 'error'}:
                        raise ValueError('Private answer generation failed')
                    if event_type == 'response.web_search_call.completed':
                        search_completed = True
                    if event_type == 'response.output_text.annotation.added':
                        cite(_field(event,'annotation'),part_key(event))
                    if event_type == 'response.output_item.done':
                        item = _field(event,'item')
                        if _field(item,'type') == 'web_search_call' and _field(item,'status') == 'completed':
                            search_completed = True
                        for ci,part in enumerate(_field(item,'content',None) or []):
                            for annotation in (_field(part,'annotations',None) or []):
                                cite(annotation,part_key(event,ci,item))
                    if event_type == 'response.output_text.done':
                        # Some Codex tool turns finish with an empty terminal
                        # output snapshot. Retain only settled content parts;
                        # never publish a delta or a done event before terminal
                        # completion and the usual cancellation/revision checks.
                        value = _field(event, 'text', '')
                        if isinstance(value, str):
                            key = part_key(event)
                            settled_text[key] = value
                            settled_positions[key] = (_field(event,'output_index',0),_field(event,'content_index',0))
                            if sum(map(len, settled_text.values())) > 180000:
                                raise ValueError('Private answer exceeds its text budget')
                    if event_type == 'response.completed':
                        mark('completed')
                        response = event.response
                        if _field(response, 'status', 'completed') != 'completed':
                            raise ValueError('Private answer did not complete')
                        selected=[]
                        for oi,item in enumerate(_field(response,'output',None) or []):
                            if _field(item,'type') == 'web_search_call' and _field(item,'status') == 'completed':
                                search_completed = True
                            for ci,part in enumerate(_field(item,'content',None) or []):
                                if _field(item,'type') != 'message' or _field(part,'type') != 'output_text':
                                    continue
                                key=part_key({'output_index':oi},ci,item)
                                value=str(_field(part,'text','') or '')
                                if value:
                                    selected.append((key,value))
                                for annotation in (_field(part,'annotations',None) or []):
                                    cite(annotation,key)
                        if not selected and not (_field(response,'output',None) or []):
                            selected=[(key,settled_text[key]) for key in sorted(settled_text,key=lambda k:settled_positions[k])]
                        text=''.join(value for _,value in selected).strip()
                        sources={url:source for key,_ in selected for url,source in sources_by_part.get(key,{}).items()}
                        if len(text) > 180000:
                            raise ValueError('Private answer exceeds its text budget')
                        if text and not self._cancelled(cancellation_event, is_current):
                            if search_needed:
                                if not search_completed or not sources:
                                    return _unavailable()
                                spoken = _spoken_search_text(text)
                                if not spoken:
                                    return _unavailable()
                                return SourcedAnswer(spoken,sources.values())
                            return text
                        if self._cancelled(cancellation_event, is_current):
                            raise RuntimeError('Private answer generation was superseded')
                        raise ValueError('Private answer was empty')
                raise ValueError('Private stream had no completed answer')
            finally:
                close = getattr(stream, 'close', None)
                if close:
                    close()
        finally:
            client.close()

