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


def told_back(phrase, state):
    """Are the words of ``phrase`` a stretch of one portion of a recent answer of this call (the listener's late repeat of a completed or cancelled answer, its duplicated final - T-A F19)? Then they
    are no new topic. The ONE window of «already said» (the answers of ``call_history`` the engine keeps, ``HISTORY_LIMIT``, the same the controller's ``_said_already`` reads: no window of its own) and the answer in play; an exchange
    without its portions is read as one text. ``asked_of`` reads what was asked, this reads what was told: both the engine's history of the call, nothing of their own."""
    if not isinstance(state, dict):
        return False
    from .classifier import _contains      # noqa: PLC0415 - the classifier imports this module: read when asked
    from .engine import call_history                    # noqa: PLC0415
    from .textutil import norm_words, stems
    said = stems(norm_words(phrase))
    if not said:
        return False
    told = [str(chunk) for chunk in state.get('chunks') or ()] or [state.get('answer') or '']
    for entry in call_history(state):
        told += [str(chunk) for chunk in entry.get('chunks') or ()] or [entry.get('answer') or '']
    return any(_contains(stems(norm_words(text)), said) for text in told if text)


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


# --- the asks of a compound question (N133, ex question_map.py): one judge with the follow-up above: what of the question before is still open ---
# The follow-up completes a short reply with the question before it; the map says which asks of that question the answer has settled. One module, one vocabulary of asks.

_ASK = (r'(?:сколько|когда|где|как(?:ой|ая|ое|ие|ую|им|их|ого|ие)?|почему|зачем|что|чем|кто|куда|откуда|чей|чья|чьё|можно\s+ли|есть\s+ли|'
        r'будет\s+ли|над\s+как\w+|в\s+как\w+|на\s+как\w+|по\s+как\w+|с\s+как\w+)')
_JOIN = re.compile(r'(?:\s*,)?\s+(?:а\s+ещё|и\s+ещё|а\s+также|а\s+потом|и\s+потом|и)\s+(?=' + _ASK + r'\b)', re.I)
_ABOUT = re.compile(r'(?<!\w)про\s+', re.I)
_PART_WORD = re.compile(r'\w+(?:-\w+)*', re.U)
_NUMBER = ('ноль', 'нол', 'один', 'одн', 'два', 'две', 'дву', 'три', 'тре', 'четыр', 'пят', 'шест', 'сем', 'вос', 'девят', 'десят', 'двадцат', 'тридцат',
           'сорок', 'пятьдесят', 'шестьдесят', 'девяност', 'сто', 'сот', 'двест', 'тысяч', 'миллион', 'полтор', 'пол')
_DATE_NUMBER = re.compile(r'\d+\s*(?:числа|число|января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)|\d{1,2}[:.]\d{2}', re.I)
_TIME = ('сегодня', 'завтра', 'послезавтра', 'вчера', 'утр', 'вечер', 'днём', 'днем', 'ночь', 'недел', 'месяц', 'числ', 'час', 'минут', 'секунд', 'день', 'дня', 'дней',
         'сразу', 'скоро', 'январ', 'феврал', 'март', 'апрел', 'мая', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр', 'понедельник', 'вторник', 'сред',
         'четверг', 'пятниц', 'суббот', 'воскресень', 'году', 'год', 'лет')
_STOP = frozenset('это этот эта эти как что кто где когда почему зачем чем какой какая какие вы вас вам мы они она оно его её ещё еще уже там тут сейчас вот только очень '
                  'можно ли есть будет такое такой про над для при без под'.split())
_STEM = 4
_MAX_PART = 12                           # a longer piece is a story, not an ask
_PART_LEAD = re.compile(r'^(?:' + _ASK + r')\b', re.I)


def _asks_first(piece):
    """A compound question opens with its ask («Где вы учились и ...»); a preamble («Простите, что перебиваю, а что ...») or a story is not cut."""
    return _PART_LEAD.match(piece) is not None


def _part_words(text):
    return [w.lower() for w in _PART_WORD.findall(text if isinstance(text, str) else '')]


def _clean(part):
    return part.strip(' \t\n,;:?!.—-')


def split_parts(question):
    """The asks of ``question`` in order, each as the words it was said with («Сколько стоит и когда привезут» -> «Сколько стоит», «когда привезут»).
    An enumeration under one head («про НДС, про УСН и про патент») gives one ask per «про». No cut leaves a part of fewer than two words
    («Число пи, сколько там, три и сколько» stays whole). A plain question is its only part; empty or non-text input gives no parts."""
    if not isinstance(question, str) or not _clean(question):
        return []
    text = question.strip()
    heads = [m.start() for m in _ABOUT.finditer(text)]
    if len(heads) >= 2:
        cuts = heads + [len(text)]
        parts = [re.sub(r'\s+и$', '', _clean(text[a:b])) for a, b in zip(cuts, cuts[1:])]
        if all(p for p in parts):
            return parts
    pieces = [_clean(p) for p in _JOIN.split(text) if _clean(p)]
    if len(pieces) > 1 and all(2 <= len(_part_words(p)) <= _MAX_PART for p in pieces) and _asks_first(pieces[0]):
        return pieces
    return [_clean(text)]


def _kind(part):
    words = _part_words(part)
    for word in words[:4]:
        if word == 'сколько':
            return 'amount'
        if word == 'когда':
            return 'time'
    return 'stems'


def _stems(part):
    """Four-letter stems of the content words of an ask; a three-letter word counts only as a capitalised abbreviation («НДС», «УСН»)."""
    out = []
    for word in _PART_WORD.findall(part):
        low = word.lower()
        if low not in _STOP and (len(low) >= 4 or (len(low) == 3 and word.isupper())):
            out.append(low[:_STEM])
    return out


def covers(part, answer):
    """Does the text ``answer`` settle the ask ``part``? A «сколько» ask wants a number (a date or a clock time does not count as one), a «когда» ask a
    time word, any other ask at least one stem (four letters) of its content words. A heuristic of the text, not of its truth."""
    if not isinstance(part, str) or not isinstance(answer, str) or not answer.strip():
        return False
    kind, words = _kind(part), _part_words(answer)
    if kind == 'amount':
        plain = _DATE_NUMBER.sub(' ', answer)
        return bool(re.search(r'\d', plain)) or any(w.startswith(_NUMBER) for w in _part_words(plain))
    if kind == 'time':
        return bool(_DATE_NUMBER.search(answer)) or any(w.startswith(_TIME) for w in words)
    stems = _stems(part)
    return bool(stems) and any(w.startswith(s) for s in stems for w in words)


class QuestionMap:
    """Per question: its parts {'text', 'status': 'open'|'closed'}. ``feed`` closes the parts a text settles; ``open_parts`` are the asks of the question nothing said has settled yet."""

    def __init__(self):
        self._next, self._entries = 1, {}

    def ask(self, question, now):
        entry = self._next
        self._next += 1
        self._entries[entry] = {'question': question if isinstance(question, str) else '', 'at': now,
                                'parts': [{'text': p, 'status': 'open'} for p in split_parts(question)]}
        return entry

    def parts(self, entry):
        return [dict(p) for p in self._entries.get(entry, {}).get('parts', ())]

    def open_parts(self, entry):
        return [p for p in self.parts(entry) if p['status'] == 'open']

    def feed(self, entry, text):
        for part in self._entries.get(entry, {}).get('parts', ()):
            if part['status'] == 'open' and covers(part['text'], text):
                part['status'] = 'closed'


# --- g13 (wave 17): a short follow-up that names a term ----------------------------------------------------------------------------------
# The owner's calls 06.11: «а счёт пятьдесят восемь», «а РКО», «а КО-2 это что», «так а пятьдесят два это какой у нас счёт». A term is an
# account with its number («счёт 58», «шестидесятый счёт»), an abbreviation («РКО», «НДС»), a form code («КО-2», «ко два»). Asked: the lead «а»
# («так а», «ну а», «а вот») and the term alone, or the term and «это что / это какой (у нас) счёт» with or without the lead; a bare number
# only with that tail. A term the waiting portion has (its number, code or abbreviation) is a try at the portion, never a question.
# «ещё пятьдесят один», «аа расчёт», «молодой», «а понятно» name no term after a lead «а» and stay what they were.
_FOLLOW_LEAD = re.compile(r'^\s*(?:(?:так|ну)[\s,]+)?а[\s,]+(?:вот[\s,]+)?', re.I)
_TERM_ABBREVIATIONS = frozenset('рко пко ндс ндфл усн осно енвд псн инн кпп огрн огрнип ккт нма мпз фсс пфр сфр омс есн кудир тмц пбу фсбу '
                                'мсфо коап нк гк тк ук фз ооо зао пао ип енп енс'.split())
_TERM_KINDS = frozenset('счет документ форма ордер книга статья закон указание бланк журнал налог кодекс ведомость отчет'.split())
_TERM_ASKS = frozenset('что какой какая какое какие'.split())


def term_followup(raw, portion_text):
    """The question of a short follow-up naming a term (see the note above), else ``None``."""
    try:
        from .ru_alignment import _canonical
    except ImportError:
        return None
    lead = _FOLLOW_LEAD.match(raw)
    rest_raw = raw[lead.end():] if lead else raw
    tokens = list(_canonical(rest_raw.rstrip('?!. '), ()))
    upper = {w.lower().replace('ё', 'е') for w in re.findall(r'\b[А-ЯЁ]{2,6}\b', rest_raw)}
    number = lambda t: re.fullmatch(r'#(?:ord:)?\d+', t) is not None
    code = lambda t: re.fullmatch(r'#[а-я]{1,4}-\d+', t) is not None
    abbr = lambda t: t in _TERM_ABBREVIATIONS or t in upper
    if tokens[:1] == ['счет'] and len(tokens) > 1 and number(tokens[1]):
        size, named = 2, [tokens[1]]
    elif len(tokens) > 1 and number(tokens[0]) and tokens[1] == 'счет':
        size, named = 2, [tokens[0]]
    elif tokens and (code(tokens[0]) or abbr(tokens[0])):
        size = 2 if len(tokens) > 1 and (number(tokens[1]) or code(tokens[1])) else 1
        named = tokens[:size]
    elif len(tokens) > 1 and tokens[0] in ('к', 'ко') and number(tokens[1]):
        size, named = 2, ['#ко-' + tokens[1].split(':')[-1][1:]]
    elif tokens and number(tokens[0]):
        size, named = 1, [tokens[0]]
    else:
        return None
    tail = tokens[size:]
    asks = tail[:1] == ['это'] and tail[1:2] and tail[1] in _TERM_ASKS
    if asks:
        after = tail[2:]
        after = after[1:] if after[:1] == ['такое'] else after
        after = after[2:] if after[:2] == ['у', 'мы'] or after[:2] == ['у', 'нас'] else after
        if len(after) > 1 or (after and after[0] not in _TERM_KINDS):
            return None
        if named and number(named[0]) and size == 1 and after != ['счет'] and not tail[1:2] == ['что']:
            return None
    elif tail or not lead:
        return None
    elif size == 1 and number(named[0]):
        return None                                               # «а пятьдесят один»: a number alone is too little
    if portion_text:
        told = set(_canonical(portion_text, ()))
        if all(t in told for t in named):
            return None
    return raw.strip()      # integ-c19: the lead «а» stays: followup.complete (g31) puts the term into the question before it
