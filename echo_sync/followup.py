"""g31-context: a short follow-up completed with the question before it, before the bank and the model see it.

``complete(text, history)`` -> ``Followup(kind, question, bank)`` or None (``text`` is no follow-up, or there is nothing to complete it with).
* ``swap``: «а пассивный» after «Что учитывает активный счёт?» is «Что учитывает пассивный счёт?»: one slot of the question before changes (a form code
  «КО-1», a number said in figures or in words, the phrase after the same preposition, an abbreviation, an adjective in the case of the word it replaces);
  everything else of it stays: the other numbers, the condition, «не». ``bank`` is the same question: the bank answers it.
* ``topic``: «почему», «а пример», «сколько это», «а если нет», «и ещё», «то есть», «а это что», «а для ИП» with no «для» before: the follow-up as said
  and the whole question it is about, for the model. ``bank`` is '': the bank would find the old question in it and say the old answer again.
``history`` is the questions asked before, oldest first (the state's history); a follow-up in it is completed on the one before it, so a chain works.
A whole question («а сколько стоит баррель нефти», «а что такое налог») and a topic that stands alone with no slot to take («а счёт 62» after «Что такое
налог?») are no follow-up: None, the usual way. Pure, no I/O, never raises, no logging of the words."""
from __future__ import annotations

import functools
import re
import threading
from typing import NamedTuple, Optional

MAX_WORDS = 4                      # of the follow-up after its lead
MAX_BASE = 300
TOPIC_MARK = ' К вопросу: '
_TOKEN = re.compile(r'\d+(?:[.,]\d+)?|[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё0-9]+)*')
_CODE = re.compile(r'([A-Za-zА-Яа-яЁё]{1,6})-(\d{1,3})', re.I)
_LEADS = frozenset({'а', 'и', 'ну', 'так', 'вот', 'слушай', 'э', 'эм', 'хм'})
_SWAP_LEADS = frozenset({'а', 'и'})
_QWORDS = frozenset({'что', 'чем', 'чего', 'чему', 'как', 'какой', 'какая', 'какое', 'какие', 'каков', 'сколько', 'почему', 'зачем', 'когда', 'где',
                     'куда', 'откуда', 'кто', 'кого', 'кому', 'ли', 'чей', 'отчего'})
_MEASURES = frozenset({'процентов', 'процента', 'процент', 'дней', 'дня', 'лет', 'года', 'месяцев', 'рублей', 'раз', 'стоит', 'длится', 'времени', 'денег',
                       'штраф', 'ставка', 'срок'})
# The follow-ups about the topic: the core said (leads off, «ё» as «е») -> the head the model reads.
_TOPIC = {'почему': 'Почему', 'почему так': 'Почему так', 'зачем': 'Зачем', 'а почему': 'Почему', 'отчего': 'Почему',
          'приведи пример': 'Приведи пример', 'а пример': 'Приведи пример',      # a bare «пример» is a word read aloud (test_short_followups)
          'подробнее': 'Расскажи подробнее', 'поподробнее': 'Расскажи подробнее', 'а подробнее': 'Расскажи подробнее',
          'сколько это': 'Сколько это', 'это сколько': 'Сколько это', 'а сколько это': 'Сколько это',
          'если нет': 'А если нет', 'если не': 'А если нет', 'если наоборот': 'А если наоборот', 'а если нет': 'А если нет',
          'еще': 'Что ещё', 'что еще': 'Что ещё', 'а еще': 'Что ещё', 'и еще': 'Что ещё', 'еще что': 'Что ещё',
          'то есть': 'То есть? Объясни проще', 'в смысле': 'В смысле? Объясни проще', 'это как': 'Как это', 'как это': 'Как это',
          'это что': 'Что это', 'что это': 'Что это', 'что это значит': 'Что это значит', 'это что значит': 'Что это значит',
          'что это такое': 'Что это', 'это что такое': 'Что это', 'а это что': 'Что это'}
_ASK_ALONE = frozenset({'сколько', 'когда', 'где', 'кто', 'зачем', 'куда', 'откуда'})      # «а когда?»: asks of the topic; «и что», «а как же», «а какой» are talk
_IDIOMS = frozenset({'общем', 'целом', 'принципе', 'итоге', 'смысле', 'частности', 'основном', 'курсе', 'общем-то', 'общий', 'целый'})
_MARKED = frozenset({'пример'})      # a core that read bare is a word read aloud («пример»): it continues the question before with ANY lead («ну», «так», «а вот», «и») or asked («пример?»), whatever the particle
_SOFT = frozenset({'то есть', 'в смысле', 'еще', 'а еще', 'и еще', 'это как', 'как это'})     # owner's own words too: a question only when nothing waits


class Followup(NamedTuple):
    kind: str          # 'swap' | 'topic'
    question: str      # for the model (and the route)
    bank: str          # for the bank; '' - ask the bank nothing
    base: str          # the question it completes


class _Tok(NamedTuple):
    text: str
    start: int
    end: int


_LOCK = threading.Lock()
_MORPH = None


def _morph():
    global _MORPH
    with _LOCK:
        if _MORPH is None:
            import pymorphy3
            _MORPH = pymorphy3.MorphAnalyzer()
    return _MORPH


@functools.lru_cache(maxsize=4096)
def _parses(word):
    try:
        return tuple(_morph().parse(word))
    except Exception:                                   # noqa: BLE001 - no analyzer: no morphology, the swaps that need it do not happen
        return ()


def _pos(word):
    found = _parses(word.lower())
    return str(found[0].tag.POS) if found else ''


def _adj(word):
    """The adjective reading of ``word`` (not «какой», «этот»: pronouns), else None."""
    for parse in _parses(word.lower()):
        if parse.tag.POS in ('ADJF', 'PRTF') and 'Apro' not in parse.tag and parse.score >= 0.05:
            return parse
    return None


def _lemma(word):
    found = _parses(word.lower())
    return (found[0].normal_form if found else word.lower()).replace('ё', 'е')


def _fold(text):
    return ' '.join(re.sub(r'[^\w\s-]', ' ', str(text).lower().replace('ё', 'е')).split())


def _tokens(text):
    return [_Tok(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _abbr(word):
    return 2 <= len(word) <= 6 and word.isalpha() and word.isupper()


def _number(words):
    """The number ``words`` say (figures or words, «шестьдесят второй»), as digits, else None."""
    try:
        from .fast_text import _atoms
        found = [a.atom for a in _atoms(' '.join(words)) if a.kind == 'n']
    except Exception:                                   # noqa: BLE001
        found = [w for w in words if w.isdigit()]
    if len(found) != 1:
        return None
    value = found[0].lstrip('#').split(':')[-1]
    return value if re.fullmatch(r'\d+(?:[.,]\d+)?', value) else None


def _same_case(word, like):
    """``word`` (an adjective) in the case, number and gender of ``like``; ``word`` as it is when the analyzer cannot."""
    mine, theirs = _adj(word), _adj(like)
    if mine is None or theirs is None:
        return word
    want = {g for g in (theirs.tag.case, theirs.tag.number, theirs.tag.gender if theirs.tag.number == 'sing' else None) if g}
    try:
        made = mine.inflect(want)
    except Exception:                                   # noqa: BLE001
        made = None
    if made is None:
        return word
    out = made.word
    if 'ё' in word.lower() and 'ё' not in out:
        out = out.replace('е', 'ё', 1) if out.replace('е', 'ё', 1).startswith(word.lower()[:word.lower().index('ё') + 1]) else out
    return out[:1].upper() + out[1:] if like[:1].isupper() else out


def _put(base, spans):
    """``base`` with each ``(start, end, text)`` of ``spans`` put in."""
    for start, end, text in sorted(spans, reverse=True):
        base = base[:start] + text + base[end:]
    return base


def _head(text):
    """The follow-up without its lead words: ``(lead, rest)`` as tokens."""
    toks = _tokens(text)
    i = 0
    while i < len(toks) and toks[i].text.lower() in _LEADS:
        i += 1
    return toks[:i], toks[i:]


# ---- the slots -------------------------------------------------------------------------------------------------------------------------------------

def _swap_code(said, base, btoks):
    codes = [m for m in (_CODE.fullmatch(t.text) for t in said) if m]
    if len(codes) != 1 or len(said) > 2:
        return None
    letters = codes[0].group(1).lower()
    found = [t for t in btoks if (m := _CODE.fullmatch(t.text)) and m.group(1).lower() == letters]
    if len(found) != 1 or found[0].text.lower() == codes[0].group().lower():
        return None
    return _put(base, [(found[0].start, found[0].end, said[[t.text for t in said].index(codes[0].group())].text)])


def _numword(word):
    """A number in figures or a word of one («пятьдесят», «второй»)."""
    if re.fullmatch(r'\d+(?:[.,]\d+)?', word):
        return True
    found = _parses(word.lower())
    return bool(found) and (found[0].tag.POS == 'NUMR' or 'Anum' in found[0].tag)


def _runs(btoks):
    """The numbers of the question: runs of number tokens as ``(first, last)`` indices (the ear writes «пятьдесят один» for 51)."""
    runs, k = [], 0
    while k < len(btoks):
        if _numword(btoks[k].text):
            j = k
            while j + 1 < len(btoks) and _numword(btoks[j + 1].text) and not btoks[j].text.isdigit():
                j += 1
            runs.append((k, j))
            k = j + 1
        else:
            k += 1
    return runs


def _swap_number(said, base, btoks):
    words = [t.text for t in said]
    value = _number(words)
    if value is None:
        return None
    lemmas = {_lemma(w) for w in words if not _numword(w)}
    if not lemmas <= {_lemma(t.text) for t in btoks}:
        return None
    runs = _runs(btoks)
    if len(runs) > 1:
        scored = sorted(((len({_lemma(btoks[j].text) for j in (a - 1, b + 1) if 0 <= j < len(btoks)} & lemmas), (a, b)) for a, b in runs), reverse=True)
        if not scored[0][0] or scored[0][0] == scored[1][0]:
            return None
        runs = [scored[0][1]]
    if not runs:
        return None
    a, b = runs[0]
    if _number([t.text for t in btoks[a:b + 1]]) == value:
        return None
    return _put(base, [(btoks[a].start, btoks[b].end, value)])


def _phrase_after(btoks, k):
    """The noun phrase after the preposition ``btoks[k]``: its tokens up to and with the first noun (abbreviation, number) and the words agreeing after it."""
    out = []
    for tok in btoks[k + 1:]:
        pos = _pos(tok.text)
        if _abbr(tok.text) or tok.text.isdigit() or pos in ('NOUN', 'ADJF', 'PRTF', 'NUMR'):
            out.append(tok)
            if _abbr(tok.text) or pos == 'NOUN':
                break
        else:
            break
    return out


def _swap_preposition(said, base, btoks):
    if not _prep_phrase(said):
        return None
    prep = said[0].text.lower()
    at = [k for k, t in enumerate(btoks) if t.text.lower() == prep]
    if len(at) != 1:
        return None
    phrase = _phrase_after(btoks, at[0])
    if not phrase:
        return None
    rest = said[1:]
    if any(t.text.lower() in _IDIOMS for t in rest):          # «а в общем», «а в целом»: talk, not a phrase of the question
        return None
    if all(_adj(t.text) is not None and _pos(t.text) != 'NOUN' for t in rest):        # «а в налоговом»: the adjective of the phrase changes, its noun stays
        adjectives = [t for t in phrase if _adj(t.text) is not None and _pos(t.text) != 'NOUN']
        if len(adjectives) < len(rest):
            return None
        return _put(base, [(a.start, a.end, _same_case(r.text, a.text)) for a, r in zip(adjectives, rest)])
    return _put(base, [(phrase[0].start, phrase[-1].end, base[0:0] + ' '.join(t.text for t in rest))])


def _swap_abbreviation(said, base, btoks):
    mine = [t for t in said if _abbr(t.text)]
    if len(mine) != 1 or len(said) > 2:
        return None
    found = [t for t in btoks if _abbr(t.text) and t.text != mine[0].text and not _CODE.fullmatch(t.text)]
    if len(found) != 1:
        return None
    return _put(base, [(found[0].start, found[0].end, mine[0].text)])


def _swap_adjective(said, base, btoks):
    if not 1 <= len(said) <= 2 or not all(_adj(t.text) is not None and _pos(t.text) != 'NOUN' for t in said):
        return None
    lemmas = {_lemma(t.text) for t in said}
    found = [t for t in btoks if _adj(t.text) is not None and _pos(t.text) != 'NOUN' and t.text.lower() not in _QWORDS and _lemma(t.text) not in lemmas]
    if any(_numword(t.text) for t in said):
        return None                 # «а второй» is no kind of account
    tails = {_lemma(t.text)[-4:] for t in said}         # the one of the same kind: «активный» / «пассивный», «приходный» / «расходный»; never «новый» for «активный»
    found = [t for t in found if _lemma(t.text)[-4:] in tails]
    if len(found) != len(said):
        return None
    return _put(base, [(b.start, b.end, _same_case(s.text, b.text)) for b, s in zip(found, said)])


def _prep_phrase(said):
    """«для ИП», «в налоговом», «за 60 дней»: a lower-case preposition and up to two names after it, nothing else («у нас завтра экскурсия», «С. Пушкин», «в то же время» are talk)."""
    if not 2 <= len(said) <= 3 or _pos(said[0].text) != 'PREP' or not said[0].text.islower():
        return False
    return all(_abbr(t.text) or _numword(t.text) or _CODE.fullmatch(t.text) or (_pos(t.text) in ('NOUN', 'ADJF', 'PRTF') and _adj(t.text) is not None or _pos(t.text) == 'NOUN')
               and t.text.lower() not in _IDIOMS for t in said[1:])


def _stands_alone(said):
    """A phrase that can be a question by itself: a noun, an abbreviation, a number; never a phrase after a preposition."""
    if said and _pos(said[0].text) == 'PREP':
        return False
    return any(_abbr(t.text) or t.text.isdigit() or _CODE.fullmatch(t.text) or _pos(t.text) == 'NOUN' for t in said)


# ---- the follow-up ---------------------------------------------------------------------------------------------------------------------------------

def _marked(core, lead, text):
    """One short turn with no topic of its own that names a thing to be given of the question before: marked by a lead (any of ``_LEADS``) or by a «?», in any form of the word («пример», «примеры»)."""
    words = core.split()
    return len(words) == 1 and _lemma(words[0]) in _MARKED and (bool(lead) or str(text).rstrip().endswith('?'))


def _topic(core, said_text, base):
    head = _TOPIC.get(core)
    if head is None:
        return None
    end = '' if head.endswith(('?', '.', 'Объясни проще')) else '?'
    if head.endswith('Объясни проще'):
        head += '.'
    return Followup('topic', f'{head}{end}{TOPIC_MARK}{base}', '', base)


def _complete(text, base):
    text = ' '.join(str(text).split())
    lead, said = _head(text)
    if not said and lead and lead[-1].text.lower() in ('еще', 'ещё'):
        said = lead[-1:]
    folded = _fold(' '.join(t.text for t in said))
    if not said or len(said) > MAX_WORDS + 2:
        return None
    if folded in _TOPIC:
        return _topic(folded, text, base)
    if _marked(folded, lead, text):
        return _topic('а пример', text, base)
    words = folded.split()
    qwords = [w for w in words if w in _QWORDS]
    if qwords:                    # «а сколько процентов», «а когда»: a question word with nothing that names a topic
        content = [w for w in words if w not in _QWORDS and w not in ('это', 'же', 'там', 'тут', 'тогда', 'такое')]
        if (content and len(content) <= 1 and all(w in _MEASURES for w in content)) or (not content and set(qwords) <= _ASK_ALONE):
            return Followup('topic', f'{text[0].upper()}{text[1:].rstrip("?.! ")}?{TOPIC_MARK}{base}', '', base)
        return None
    if not lead or lead[-1].text.lower() not in _SWAP_LEADS or len(said) > MAX_WORDS:
        return None
    btoks = _tokens(base)
    for swap in (_swap_code, _swap_preposition, _swap_number, _swap_abbreviation, _swap_adjective):
        made = swap(said, base, btoks)
        if made and made != base:
            return Followup('swap', made, made, base)
    if _stands_alone(said) or not _prep_phrase(said):
        return None                 # only «а для ИП» with no «для» before is «the same question about it»; «а потом», «а сегодня» are talk
    if not any(_abbr(t.text) or t.text.isdigit() or _pos(t.text) == 'NOUN' for t in said[1:]):
        return None
    phrase = ' '.join(t.text for t in said)
    return Followup('topic', f'А {phrase}? Тот же вопрос.{TOPIC_MARK}{base}', '', base)


def _base(history):
    """The question the next follow-up is about: the last one asked, completed on the one before when it was a follow-up itself."""
    base = None
    for item in history or ():
        if not isinstance(item, str) or not item.strip():
            continue
        item = ' '.join(item.split())[:MAX_BASE]
        if TOPIC_MARK in item:
            base = item.split(TOPIC_MARK, 1)[1] or base
            continue
        got = _complete(item, base) if base else None
        if got is None:
            if base and _shape(item):
                continue            # a follow-up that could not be completed leaves the topic as it was
            base = item
        elif got.kind == 'swap':
            base = got.question
    return base


def _shape(text):
    """Does ``text`` look like a follow-up (a lead and a few words, or a topic form)?"""
    lead, said = _head(text)
    return _fold(' '.join(t.text for t in said)) in _TOPIC or (bool(lead) and lead[-1].text.lower() in _SWAP_LEADS and 0 < len(said) <= MAX_WORDS
                                                              and not any(t.text.lower() in _QWORDS for t in said))


def complete(text, history) -> Optional[Followup]:
    """``text`` completed with the question before it (see the module), or None. Never raises."""
    try:
        if not isinstance(text, str) or not text.strip() or isinstance(history, str):
            return None
        base = _base(list(history) if history else ())
        if not base:
            return None
        return _complete(text, base)
    except Exception:                                   # noqa: BLE001 - a follow-up not understood goes the usual way
        return None


def asked_of(state):
    """The questions of the engine's ``state``, oldest first: the ONE base of every follow-up (the classifier, the judge's rows, the controller).
    Its history and the question in play when the history has not got it yet; the floor of the call (``state['call_began']``, set by the controller when a call
    began anew): a call that began after an answer was given does not inherit it («а почему?» is no follow-up to yesterday's question); no floor (a redial
    inside the window) sees the whole history."""
    if not isinstance(state, dict):
        return []
    began = state.get('call_began')
    old = lambda at: type(began) in (int, float) and type(at) in (int, float) and at < began      # noqa: E731
    entries = [entry for entry in state.get('history') or () if isinstance(entry, dict) and not old(entry.get('at'))]
    # a question the ear opened and the cloud's final took back («revised», nothing of its answer heard) was never asked: it is no topic of a follow-up
    void = {str(entry.get('question') or '') for entry in entries if entry.get('status') == 'revised' and not entry.get('spoken')}
    asked = [str(entry.get('question') or '') for entry in entries if str(entry.get('question') or '') not in void]
    if state.get('question') and state['question'] not in void and not old(state.get('issued_at')) and (not asked or asked[-1] != state.get('question')):
        asked.append(str(state['question']))
    return asked


def soft(text):
    """«то есть», «и ещё», «как это»: owner's own words as often as a question; a question only when nothing waits."""
    _, said = _head(str(text or ''))
    folded = _fold(' '.join(t.text for t in said)) or _fold(text or '')
    return folded in _SOFT or folded in ('еще', 'ещё')


def is_followup(text, history=None, *, loose=False, strict=False) -> bool:
    """U15-S7, the one follow-up predicate: is ``text`` a follow-up that needs what came before it? Never raises.
    * a swap or a topic that ``complete`` makes with ``history`` (the questions asked before) - only when there is a history;
    * a topic core of ``_TOPIC`` (also without history: the words are the same on their own); a bare «пример» is a word read aloud, «а пример» is not;
    * ``strict``: only the cores that are safe while a portion waits - two words or more, never ``soft`` («то есть», «и ещё») nor a single «почему»;
    * ``loose``: also the shape of a follow-up (a lead and a few words, no question word), for the places that only ask «does it hang on the question before»."""
    try:
        if not isinstance(text, str) or not text.strip():
            return False
        lead, said = _head(' '.join(text.split()))
        if not said and lead and lead[-1].text.lower() in ('еще', 'ещё'):
            said = lead[-1:]
        core = _fold(' '.join(t.text for t in said))
        if core in _TOPIC:
            return not strict or (len(core.split()) >= 2 and not soft(text))
        if _marked(core, lead, text):
            return not strict or (bool(lead) and lead[-1].text.lower() in _SWAP_LEADS)      # while a portion waits only «а»/«и» (as it was) count: «ну пример» may be the owner's own words
        if strict:
            return False
        if history and complete(text, history) is not None:
            return True
        return bool(loose) and _shape(text)
    except Exception:                                   # noqa: BLE001 - not understood: no follow-up, the usual way
        return False
