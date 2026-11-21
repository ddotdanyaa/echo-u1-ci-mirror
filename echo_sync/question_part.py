"""R06 / W2: the question WITH its conditions out of a long utterance, the talk around it left out. Pure: text in, a ``Part`` out, no I/O, no state, no model.

A long utterance is «remark. conditions. question.» in any order: «Вот сейчас третья минута идёт… что такое пятнадцатый счёт» (E73: «сейчас» of the remark read as a question about
the present), «Я вчера плохо спал. Что такое проводка?» (E72: «я» of the intro made the question personal), «Ответ шёл 13 секунд. Сколько будет 13 на 4?», «Не 15, а 50. Сколько это?»,
«Берём 2024 год, ставка 10%, без НДС. Какова сумма?», «А в тексте что сказано про амортизацию?», «Так, секунду. Пятнадцатый счёт в плане счетов.».

Every piece (a sentence, or the part of one before a question word) is one of: QUESTION (a question word / a request to tell at the start of a clause, or a «?»), CONDITION (a number, a rate, a year, «берём / допустим /
пусть / без / для / если», a correction «не 15, а 50»), CONTEXT (shares a content word with the question), ASIDE (the rest: talk about oneself without a number, greetings, the rehearsal, a number that is a time measure).
Only an ASIDE leaves the text, and only on positive evidence; what is not sure stays in. Nothing found -> ``kind == 'none'`` and the text unchanged: the caller takes its old path.

Privacy is never weakened: ``personal`` is the question's own (the gate patterns of ControlledMedia, plus мне / меня outside «скажи мне»), or a kept condition's; a personal intro that is dropped does not make a public question
personal, a personal request stays personal whatever is dropped around it. ``public_query`` is what a public lookup may see: '' for a personal question and for a question about the listener's material, else the question and its
impersonal conditions. ``current`` (data that changes) is read on the question and its conditions only, never on an aside.
"""
import re
from typing import NamedTuple

from .generator import CHANGES, route_need
from .textutil import MARKER_BASE, STOPWORDS, normalize
from .user_intents import is_preamble, is_small_talk


class Part(NamedTuple):
    kind: str                 # 'question' | 'compound' | 'topic' | 'none'
    text: str                 # what goes on: conditions and question in their order (the input itself for 'none')
    question: str = ''
    conditions: tuple = ()
    context: tuple = ()
    dropped: tuple = ()       # ((text, why), ...)
    personal: bool = False
    current: bool = False
    scope: str = 'public'     # 'public' | 'personal' | 'material'
    public_query: str = ''
    correction: tuple = None  # ('15', '50') for «не 15, а 50»
    material: str = ''        # the title when the question names the material, else '' (scope tells)
    subject: tuple = ()       # E73.1: the pieces said before the question word that NAME what it is about («Нынешний закон о бухучёте, какой год принятия»): they stay with the question


_ABBR = r'(?:ст|п|пп|ч|т|д|е|г|гг|руб|тыс|млн|млрд|см|им|рис|напр|др|т\.е|т\.д|т\.п|т\.к|и\s*т\.д)'
_SENTENCE_END = re.compile(r'[?!…]+|\.+(?=\s|$)')
_TAIL_AFTER_Q = re.compile(r'^[\s,;:—–-]+|[\s,;:—–-]+$')
_STRONG = frozenset('сколько почему зачем каков какова каково каковы какой какая какое какие какого какую каким каком каких какими чему отчего откуда куда где насколько'.split())
_WEAK = frozenset('когда как что кто кого кому кем чем чей чья чье чьи разве неужели'.split())
_IMPER = frozenset('скажи скажите подскажи подскажите объясни объясните расскажи расскажите назови назовите посчитай посчитайте вычисли вычислите рассчитай рассчитайте определи определите '
                   'перечисли перечислите поясни поясните найди найдите проверь проверьте поищи поищите сравни сравните приведи приведите'.split())
_PAIRS = frozenset({('что', 'такое'), ('что', 'значит'), ('что', 'означает'), ('что', 'делать'), ('что', 'будет'), ('в', 'чем'), ('чем', 'отличается'), ('чем', 'отличаются'),
                    ('как', 'считается'), ('как', 'считать'), ('как', 'рассчитать'), ('как', 'рассчитывается'), ('как', 'определить'), ('как', 'посчитать'), ('как', 'называется'),
                    ('как', 'расшифровывается'), ('как', 'работает'), ('как', 'правильно'), ('кто', 'такой'), ('кто', 'такая'), ('кто', 'такие'), ('когда', 'нужно'), ('когда', 'надо'), ('можно', 'ли')})
_LEAD = frozenset('а и ну вот так слушай слушайте значит короче тогда итак пожалуйста же еще ещё'.split())
_BLOCK = frozenset('не знаю понимаю понял поняла пойму видел видела смотрю неважно ни то бы'.split())
_NUMWORD = re.compile(r'^(?:нол|дв[ае]|двух|тр[иё]х?|четыр|пят|шест|сем|восем|вос[еь]м|девят|десят|\w*надцат|\w*дцат|сорок|девяност|сто$|сотн|двест|трист|четыреста|\w*сот$|тысяч|миллион|миллиард|половин|полтор)')
_TIME_UNIT = re.compile(r'\b\d+(?:[.,]\d+)?\s*(?:секунд\w*|сек\b|миллисекунд\w*|мс\b|минут\w*|мин\b|часа?\b|часов\b)', re.I)
_BARE_TIME = re.compile(r'^\W*\d+(?:[.,]\d+)?\s*(?:секунд\w*|сек|миллисекунд\w*|мс)\W*$', re.I)
_WAIT = frozenset('ждал ждала ждали жду ждем ждём долго задержка задержки задержку тормозит тормозишь заняло заняла длилось прошло потребовалось ответил ответила отвечал отвечала отвечает отвечаешь думал думала думает шёл шел шла пришла пришел пришёл пришло'.split())
_MARKERS = re.compile(r'(?:^|\s)(?:' + MARKER_BASE + r'|считаем|считай|учитывай|учитывайте|если(?!\s+(?:честно|что|можно|получится|не\s+затруднит))|год)(?=\s|[,.:;]|$)', re.I)
_ASIDE_WORDS = frozenset('подсказка подсказки подсказку репетиция репетиции репетицию микрофон слышно слышишь слышите скорость быстро медленно качество звук громко тихо следующий начинаем начнем начнём готов готова стоп секунду минутку момент ладно хорошо ок окей'.split())
_PERSONAL = re.compile(r'\b(?:я|мне|меня|мной|мы|нам|нас|нами|мой|моя|мо[её]|моего|моей|моих|моему|мо[её]м|мои|моим|моими|мою|наш\w*|сво[йеяёию]\w*|себе|себя)\b', re.I)
_GATE = re.compile(r'\b(?:мой|моя|мо[её]|моего|моей|моих|моему|мо[её]м|мои)\b|\bу\s+меня\b|\b(?:что|где|когда|как|кому|зачем)\s+я\b|\bобо?\s+мне\b|\b(?:мне|меня|мной|моим|моими|мою)\b', re.I)
_TELL_ME = re.compile(r'\b(?:скажи|скажите|объясни|объясните|расскажи|расскажите|подскажи|подскажите|поясни|поясните|покажи|покажите|напомни|напомните)\s+мне\b', re.I)
_MATERIAL = re.compile(r'\b(?:по|в|из|согласно|исходя\s+из)\s+(?:этому|этом|этого|данному|данном|нашему|нашем|загруженному|выданному|выданном|моему|моем|моём)?\s*'
                       r'(?:материал\w*|текст\w*|документ\w*|лекци\w*|конспект\w*|пособи\w*|учебник\w*|файл\w*|презентаци\w*|заметк\w*)', re.I)
_TOPIC_NOUNS = frozenset('статья статьи статье статью пункт пункта счет счета счету билет билета тема темы глава главы часть части раздел раздела вариант задача номер пбу фсбу мсфо'.split())
_NOT_RELATED = frozenset('сейчас сегодня вчера завтра вообще просто очень вопрос ответ подсказка вот'.split()) | STOPWORDS
_SMALL = 8
# E73.1: a preface that names a document is the SUBJECT of the question after it, not talk around it («Трудовой кодекс, сколько длится испытательный срок»). Positive evidence only: the head noun of a document, whole word
# (no «закончил»), no word of oneself (the check of ``_PERSONAL`` comes first), a short run; anything else stays what it was (an aside when it shares no word with the question).
_SUBJECT_HEAD = re.compile(r'^(?:закон(?:а|е|у|ом|ы|ов|ам|ах|ами)?|кодекс(?:а|е|у|ом|ы|ов|ам|ах|ами)?|положени(?:е|я|ю|ем|и|й)|стандарт(?:а|е|у|ом|ы|ов)?|регламент(?:а|е|у|ом|ы|ов)?|'
                           r'постановлени(?:е|я|ю|ем|и|й)|договор(?:а|е|у|ом|ы|ов)?|конвенци(?:я|и|ю|ей)|приказ(?:а|е|у|ом|ы|ов)?|устав(?:а|е|у|ом|ы|ов)?)$')


def _words(text):
    return normalize(text).split()


def _numeric(word):
    return bool(re.search(r'\d', word) or _NUMWORD.match(word))


# "one" is a number only with a unit; alone it means "a certain" («уточнить одну вещь»)
_ONE_UNIT = re.compile(r'\b(?:один|одн(?:а|у|о|ой|ого|ому|им|ом))\s+(?:процент|рубл|тысяч|миллион|миллиард|год|лет|месяц|дн|день|час|минут|секунд|раз|штук|копе|доллар|евро|градус)')


def _has_number(text):
    return '%' in text or any(_numeric(w) for w in _words(text)) or bool(_ONE_UNIT.search(normalize(text)))


def _segments(text):
    text = ' '.join(str(text or '').split())
    parts, start = [], 0
    for found in _SENTENCE_END.finditer(text):
        if found.group()[0] == '.' and re.search(r'(?:^|[\s(])' + _ABBR + r'$', text[start:found.start()], re.I):
            continue
        parts.append(text[start:found.end()].strip())
        start = found.end()
    parts.append(text[start:].strip())
    return [p for p in parts if re.search(r'\w', p)]


def _question_start(raw, words, closed):
    """The index of the token where a question begins in the clause ``raw`` (tokens) / ``words`` (their normal forms), or None. ``closed``: the sentence ends with «?»."""
    for i, w in enumerate(words):
        if not w:
            continue
        nxt = words[i + 1] if i + 1 < len(words) else ''
        prev = words[i - 1] if i else ''
        if i > 1 and prev in ('знаю', 'понимаю', 'помню', 'уверен', 'уверена', 'важно') and words[i - 2] == 'не':
            continue                              # «я не знаю, сколько это»: said of oneself, not asked
        boundary = i == 0 or bool(re.search(r'[,;:—–-]$', raw[i - 1])) or prev in _LEAD
        if (w in _STRONG or w in _IMPER) and (boundary or prev not in _BLOCK):
            return i if boundary or i > 4 else 0
        if (w, nxt) in _PAIRS and (boundary or prev not in _BLOCK):
            return i if boundary or i > 4 else 0
        if w in _WEAK and boundary and closed and nxt not in ('обычно', 'я', 'мы', 'то', 'бы'):
            return i
    return None


def _split_clause(segment):
    """(prefix, question) of one sentence: question is '' when it asks nothing."""
    raw = segment.split()
    words = [normalize(t) for t in raw]
    closed = segment.rstrip().endswith('?')
    at = _question_start(raw, words, closed)
    if at is None:
        return (segment, segment) if closed and not is_small_talk([w for w in words if w]) and not _is_aside_word(words) else (segment, '')
    if at and all(w in _LEAD for w in words[:at]):
        at = 0
    prefix = _TAIL_AFTER_Q.sub('', ' '.join(raw[:at]))
    return prefix, ' '.join(raw[at:])


def _is_aside_word(words):
    return bool(words) and all(w in _ASIDE_WORDS or w in STOPWORDS or w in ('ты', 'вы', 'меня', 'слышно') or not w for w in words)


def _correction(text):
    found = re.search(r'\bне\s+(?P<x>[^\s,.;]+(?:\s+[^\s,.;]+){0,2}?)\s*,?\s+а\s+(?P<y>[^\s,.;?!]+(?:\s+(?:[^\s,.;?!]+))?)', text, re.I)
    if found:
        x, y = found.group('x').strip(), found.group('y').strip()
        if _has_number(x) and _has_number(y):
            return x, y.split()[0] if not _has_number(y.split()[-1]) else y
    return None


def _measure(text):
    words = set(_words(text))
    return bool(_BARE_TIME.match(text) or (_TIME_UNIT.search(text) and words & _WAIT and not _MARKERS.search(text)))


def _stems(text):
    return {w[:5] for w in _words(text) if w not in _NOT_RELATED and len(w) > 2}


def _names_subject(words):
    return 0 < len(words) <= _SMALL and any(_SUBJECT_HEAD.match(w) for w in words)


def _classify(piece, qstems, tail=False, subject=False):
    """('condition' | 'context' | 'aside', why) for a piece that asks nothing. ``subject``: the piece stands before the question it belongs to (a preface that names a document is its subject, E73.1)."""
    words = _words(piece)
    if _correction(piece):
        return 'condition', 'correction'
    if _MATERIAL.search(piece):
        return 'context', 'material'
    if _measure(piece):
        return 'aside', 'time_measure'
    if _MARKERS.search(piece) or _has_number(piece):
        if _has_number(piece) and not _MARKERS.search(piece) and not tail and is_small_talk(words):
            return 'aside', 'small_talk'
        return 'condition', 'number' if _has_number(piece) else 'marker'
    try:
        if is_preamble(words) or is_small_talk(words):
            return 'aside', 'preamble'
    except Exception:             # noqa: BLE001 - not sure it is one: it stays
        pass
    if _PERSONAL.search(piece):
        return 'aside', 'personal'
    if _is_aside_word(words):
        return 'aside', 'meta'
    if subject and _names_subject(words):
        return 'context', 'subject'
    return ('context', 'related') if _stems(piece) & qstems else ('aside', 'unrelated')


def _personal(question):
    return bool(_GATE.search(_TELL_ME.sub(' ', question)))


def _scope(question, titles):
    if _personal(question):
        return 'personal', ''
    if _MATERIAL.search(question):
        words = _stems(question)
        return 'material', next((t for t in titles if _stems(t) and _stems(t) <= words), '')
    words = _stems(question)
    named = next((t for t in titles if len(_stems(t)) >= 2 and _stems(t) <= words), '')
    return ('material', named) if named else ('public', '')


def extract(text, *, titles=()):
    """The ``Part`` of ``text``. ``titles``: the names of the listener's materials (a question that names one asks about it)."""
    text = ' '.join(str(text or '').split())
    pieces = []                                   # (role, text, why): role 'q' | 'p' (prefix, not classified yet)
    segments = _segments(text)
    for number, segment in enumerate(segments):
        prefix, question = _split_clause(segment)
        if question == segment:
            pieces.append(['q', segment, '', number]); continue
        if question:
            if prefix:
                pieces.append(['p', prefix, '', number])
            pieces.append(['q', question, '', number])
        else:
            pieces.append(['p', segment, '', number])
    questions = [p for p in pieces if p[0] == 'q']
    if not questions and len(pieces) > 1:         # a topic without a question word after a remark
        last = pieces[-1]
        words = _words(last[1])
        if 0 < len(words) <= _SMALL and not _PERSONAL.search(last[1]) and not _measure(last[1]) and not _correction(last[1]) and not _MARKERS.search(last[1]) \
                and (not _has_number(last[1]) or set(words) & _TOPIC_NOUNS) and not is_small_talk(words) and not is_preamble(words) and not _is_aside_word(words) \
                and _classify(pieces[-2][1], set())[0] == 'aside':
            last[0] = 'q'; last[3] = -1
            questions = [last]
    if not questions:
        return Part('none', text)
    qstems = set().union(*(_stems(p[1]) for p in questions))
    conditions, context, dropped, kept, subject = [], [], [], [], []
    correction = None
    for role, body, _, _n in pieces:
        if role == 'q':
            kept.append(body); continue
        verdict, why = _classify(body, qstems, subject=True)
        if verdict == 'aside':
            dropped.append((body, why))
            continue
        kept.append(body)
        (conditions if verdict == 'condition' else context).append(body)
        if why == 'subject':
            subject.append(body)
        correction = correction or _correction(body)
    qtexts = [p[1] for p in questions]
    kept_text = ' '.join(kept)
    scope, material = _scope(' '.join(context + qtexts), titles)
    personal = scope == 'personal' or any(_PERSONAL.search(c) for c in conditions)
    if scope == 'public' and personal:
        scope = 'public'                          # the question is public, a condition is not: the lookup sees the question and the impersonal conditions only
    safe = [c for c in conditions if not _PERSONAL.search(c)]
    public = '' if scope in ('personal', 'material') else ' '.join(safe + [b for b in subject if not _PERSONAL.search(b)] + qtexts)
    current = route_need(' '.join(conditions + qtexts))==CHANGES
    kind = 'compound' if len(questions) > 1 else 'topic' if questions[0][3] == -1 else 'question'
    return Part(kind, kept_text, qtexts[-1] if kind != 'compound' else ' '.join(qtexts), tuple(conditions), tuple(context), tuple(dropped), personal, current, scope, public,
                correction, material, tuple(subject))

