"""Local reference base: settled references answered exactly and at once (wave G / G2).

``lookup(text, history)`` recognises a plain question about the NAME of a numbered thing in a public official text and
answers it from a table that ships with the add-on - no network, no model, a few microseconds:

* an article of the Tax Code (parts 1-2), the Civil Code (parts 1-4) or the Labour Code - «статья 19 НК», «19-я статья
  налогового кодекса», «ст. 19 НК РФ», «статьи девятнадцать», «а 27-я?» (the code comes from the history);
* an account of the Plan of accounts (Order of the Ministry of Finance 94n) - «71 счёт», «семьдесят первый счёт»,
  «что за 62 счёт», «счёт 001».

The answer is one spoken sentence, «Статья 19 Налогового кодекса — налогоплательщики, плательщики сборов, ...» or
«Счёт 71 — расчёты с подотчётными лицами.».  Anything else returns ``None`` and the normal path answers: another
document, a number that is not in the table, an account of a bank, a ratio «2:1», and every question that asks more than
the title can say (a rate, a sum, a deadline, «почему», «сколько», «пример», «объясни» ...).  The test is a whitelist:
after the reference itself (keyword + number + code name) only filler and question words may be left in the utterance;
one word that is not on the list and the answer is ``None``.

``history`` is the earlier lines of the conversation (user turns and the answers given), OLDEST FIRST, newest last.
The code of a follow-up («а 27-я?») is the one named in the newest of the last three lines that names one.

Importing this module costs a few regular expressions: the tables (``kb_nk``, ``kb_gk``, ``kb_tk``, ``kb_accounts``,
``kb_yo``) are imported on the first question that needs them (``preload()`` does it ahead of time).  ``lookup`` never
raises.  Numbers are read with ``ru_numbers`` (the same reader as the acknowledgement matcher); no morphology library is
loaded - the case forms of the number words are generated from stems.
"""
from __future__ import annotations

import importlib
import re
from collections import namedtuple
from decimal import Decimal
from typing import Optional, Sequence

from . import ru_numbers as numbers
from .speech_text import article_said, title_said      # law-speak: the voice's rules for a title and an article number are speech_text's (tts-render)

# Capture date of the tables (each kb_* module carries its own CAPTURED too).
CAPTURED = '2026-11-04'

_DOCS = {            # code -> (data module, spoken name in the genitive)
    'nk': ('kb_nk', 'Налогового кодекса'),
    'gk': ('kb_gk', 'Гражданского кодекса'),
    'tk': ('kb_tk', 'Трудового кодекса'),
}
_MAX_TOKENS = 16
_MAX_CHARS = 240

# -- words ------------------------------------------------------------------------------------------------------------

_ARTICLE_WORDS = frozenset({'статья', 'статьи', 'статье', 'статью', 'статьей', 'статьею', 'ст'})
_ACCOUNT_WORDS = frozenset({'счет', 'счета', 'счету', 'счете', 'счетом'})
_PLAN_WORDS = frozenset({'план', 'плана', 'плане', 'плану', 'планом'})        # «план счетов»
_NUMBER_WORDS = frozenset({'номер', 'номером'})                               # «статья номер 19», «под номером»
_OFF_BALANCE_WORDS = frozenset({'забалансовый', 'забалансовом', 'забалансового', 'забалансовые', 'забалансовых'})
_DOT_WORDS = frozenset({'точка'})                                             # «сто пять точка один» = 105.1

# The only words that may stand around the reference.  A word that is not here (a rate, a sum, a deadline, «почему»,
# «сколько», «пример», «объясни», «расскажи», a name of another document ...) means the person asks more than a title can
# answer: the lookup returns None and the normal path answers.
_FILLER = frozenset('''
так ну а и да вот хорошо ладно итак значит окей ага угу эм э мм ммм хм ой
слушай слушайте скажи скажите подскажи подскажите напомни напомните смотри смотрите давай давайте получается короче типа
теперь дальше еще кстати там тут нам мне у нас меня пожалуйста же ли то вопрос следующий
что это эта этот эти такое за про о об обо чем чему какая какой какое как называется название наименование заголовок тема
посвящена посвящен означает речь идет она он
в во по из на насчет
статья статьи статье статью российской федерации рф план плане плана плану счетов бухгалтерского бухучета учета
забалансовый забалансовом забалансового забалансовые номер номером
'''.split())

# H4: the recognizers put these in front of a reference («А с двадцать первой статье Налогового кодекса»). Read behind the text channel only (``lookup``).
_PREPOSITIONS = frozenset({'с', 'со'})
_WITH_PREPOSITIONS = _FILLER | _PREPOSITIONS
# H7 item 0: what may stand after a reference and asks nothing (``without_tail``). A number with a word for time is a time counted aloud, unless a preposition makes it part of what is said.
_TAIL_WORDS = frozenset('вот да ну так ладно хорошо ага угу все понял поняла спасибо пожалуйста'.split())
_TIME_UNITS = frozenset('секунда секунды секунд секунду минута минуты минут минуту'.split())
_COUNT_LEADS = (['за'], ['через'], ['на'], ['в'], ['до'], ['после'], ['по'])

_CARDINALS = {}
for _i, _w in enumerate(('ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать '
                         'четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать').split()):
    _CARDINALS[_w] = _i
_CARDINALS.update({'нуль': 0, 'одна': 1, 'одно': 1, 'две': 2})
_CARDINALS.update(zip('двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split(), range(20, 100, 10)))
_CARDINALS.update(zip('сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот'.split(), range(100, 1000, 100)))

_ORDINAL_STEMS = {
    'нулев': 0, 'перв': 1, 'втор': 2, 'четверт': 4, 'пят': 5, 'шест': 6, 'седьм': 7, 'восьм': 8, 'девят': 9, 'десят': 10,
    'одиннадцат': 11, 'двенадцат': 12, 'тринадцат': 13, 'четырнадцат': 14, 'пятнадцат': 15, 'шестнадцат': 16,
    'семнадцат': 17, 'восемнадцат': 18, 'девятнадцат': 19, 'двадцат': 20, 'тридцат': 30, 'сороков': 40, 'пятидесят': 50,
    'шестидесят': 60, 'семидесят': 70, 'восьмидесят': 80, 'девяност': 90, 'сот': 100, 'двухсот': 200, 'трехсот': 300,
    'четырехсот': 400, 'пятисот': 500, 'шестисот': 600, 'семисот': 700, 'восьмисот': 800, 'девятисот': 900,
}
_HARD_ENDINGS = ('ый', 'ой', 'ая', 'ое', 'ые', 'ого', 'ому', 'ую', 'ым', 'ом', 'ых', 'ыми')
_THIRD_FORMS = ('третий', 'третья', 'третье', 'третьи', 'третьего', 'третьему', 'третью', 'третьим', 'третьем', 'третьей',
                'третьих', 'третьими')
_SCALE_WORDS = {'тысяча': 1000, 'тысячу': 1000}
_SCALE_AFTER_NUMBER = {'тысячи': 1000, 'тысяч': 1000}

_LEXICON = None


def _lexicon():
    """Word -> (kind, value) for every case form of the number words an article or an account number is said with."""
    global _LEXICON
    if _LEXICON is None:
        lex = {word: ('card', value) for word, value in _CARDINALS.items()}
        for stem, value in _ORDINAL_STEMS.items():
            for ending in _HARD_ENDINGS:
                lex[stem + ending] = ('ord', value)
        for form in _THIRD_FORMS:
            lex[form] = ('ord', 3)
        _LEXICON = lex
    return _LEXICON


# -- tokens ----------------------------------------------------------------------------------------------------------

_HINT = re.compile(r'стат|\bст\b|сч[её]т|план|^\W*(?:(?:ну|так|и|да|ладно|хорошо)\W+)?[аи]\b')
_SENTENCE = re.compile(r'[.!?…]+\s+')
_CLAUSE = re.compile(r'[,;:—–]\s*')
_ASKS_MORE = frozenset('как почему зачем сколько когда где чем кто какой какая какое какие можно'.split())
_RATIO = re.compile(r'\d\s*:\s*\d|(?<!\w)[-–—−]\s?\d')          # «2:1», «12:30», «-19» are not a reference
_TOKEN = re.compile(r'\d+(?:[.,]\d+)*(?:-(?:[а-я]+|\d+))?|[a-zа-я]+')
_DIGITS = re.compile(r'(?:0|[1-9]\d*)')
_ZERO_LED = re.compile(r'0\d+')                                    # account «01», «001»
_ORDINAL_DIGITS = re.compile(r'(\d+)-(я|й|е|го|му|ой|ая|ый|ое|ые|ю|ую|ом|м|х|ий)')
_DOTTED = re.compile(r'\d+(?:\.\d+)+(?:-\d+)?')                    # article «105.1», «25.12-1»
_PLAIN_KEY = re.compile(r'[1-9]\d{0,3}(?:\.\d+)?(?:-\d+)?')

Mention = namedtuple('Mention', 'start end key ordinal gender literal')
Reference = namedtuple('Reference', 'kind mention doc lead consumed tokens')


def _gender(token):
    if token.endswith(('ая', 'ую', 'ья', 'ью')) or re.fullmatch(r'\d+-(?:я|ая|ю|ую)', token):
        return 'f'
    if token.endswith(('ый', 'ий')) or re.fullmatch(r'\d+-(?:й|ый|ий)', token):
        return 'm'
    return None


def _items(tokens):
    lex = _lexicon()
    items = []
    for token in tokens:
        if _DIGITS.fullmatch(token):
            items.append(numbers.Item('digits', Decimal(token), token))
        elif token in lex:
            kind, value = lex[token]
            items.append(numbers.Item(kind, value, token))
        elif token in _SCALE_WORDS:
            items.append(numbers.Item('scale', _SCALE_WORDS[token], token))
        elif token in _SCALE_AFTER_NUMBER and items and items[-1].kind in ('card', 'digits'):
            items.append(numbers.Item('scale', _SCALE_AFTER_NUMBER[token], token))
        else:
            items.append(numbers.Item('word', token, token))
    return items


def _mentions(tokens):
    """Every number said or written in the utterance: ``Mention(start, end, key, ordinal, gender, literal)``."""
    items = _items(tokens)
    found, i, n = [], 0, len(tokens)
    while i < n:
        token = tokens[i]
        ordinal = _ORDINAL_DIGITS.fullmatch(token)
        if ordinal:
            found.append(Mention(i, i + 1, str(int(ordinal.group(1))), True, _gender(token), False))
            i += 1
        elif _DOTTED.fullmatch(token) or _ZERO_LED.fullmatch(token):
            found.append(Mention(i, i + 1, token, False, None, True))
            i += 1
        else:
            read = numbers.read_number(items, i)
            if isinstance(read, numbers.Read):
                atom = read.atom
                is_ordinal = atom.startswith('#ord:')
                value = atom[5:] if is_ordinal else atom[1:]
                found.append(Mention(i, read.end, value, is_ordinal, _gender(tokens[read.end - 1]) if is_ordinal else None, '.' in value))
                i = read.end
            elif isinstance(read, numbers.Fail):
                i = max(read.end, i + 1)
            else:
                i += 1
    return _join_dots(tokens, found)


def _join_dots(tokens, found):
    """«сто пять точка один» -> 105.1: two plain numbers around the word «точка» are one article number."""
    out = []
    for mention in found:
        if (out and not mention.ordinal and not mention.literal and mention.key.isdigit()
                and not out[-1].ordinal and not out[-1].literal and out[-1].key.isdigit()
                and mention.start == out[-1].end + 1 and tokens[out[-1].end] in _DOT_WORDS):
            previous = out.pop()
            out.append(Mention(previous.start, mention.end, previous.key + '.' + mention.key, False, None, True))
        else:
            out.append(mention)
    return out


def _docs(tokens):
    """Names of the codes in the utterance: ``[(code, start, end)]`` («налоговый кодекс», «НК», «НК РФ»)."""
    found, n = [], len(tokens)
    for i, token in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < n else ''
        if nxt.startswith('кодекс'):
            for prefix, code in (('налогов', 'nk'), ('гражданск', 'gk'), ('трудов', 'tk')):
                if token.startswith(prefix):
                    found.append((code, i, i + 2))
        if token in ('нк', 'гк', 'тк'):
            found.append(({'нк': 'nk', 'гк': 'gk', 'тк': 'tk'}[token], i, i + 1))
        elif token in ('эн', 'гэ', 'ге', 'тэ', 'те') and nxt == 'ка':
            found.append(({'эн': 'nk', 'гэ': 'gk', 'ге': 'gk', 'тэ': 'tk', 'те': 'tk'}[token], i, i + 2))
    return found


def _keywords(tokens):
    """«статья», «счёт», «план счетов»: ``[(kind, start, end)]``."""
    found, n = [], len(tokens)
    for i, token in enumerate(tokens):
        if token in _ARTICLE_WORDS:
            found.append(('article', i, i + 1))
        elif token in _ACCOUNT_WORDS:
            found.append(('account', i, i + 1))
        elif token in _PLAN_WORDS and i + 1 < n and tokens[i + 1] == 'счетов':
            found.append(('account', i, i + 2))
    return found


def _adjacent(tokens, mention, keyword):
    """The number stands right before the keyword («19 статья») or right after it («статья 19», «статья номер 19»)."""
    _, start, end = keyword
    if mention.end == start:
        return set()
    if mention.start == end:
        return set()
    if mention.start == end + 1 and tokens[end] in _NUMBER_WORDS:
        return {end}
    return None


def _reference(tokens, fillers=_FILLER):
    """The one reference in the utterance, or ``None`` when there is none, more than one, or anything else is said."""
    if not tokens or len(tokens) > _MAX_TOKENS:
        return None
    mentions = _mentions(tokens)
    if len(mentions) != 1:
        return None
    mention = mentions[0]
    docs = _docs(tokens)
    if len({code for code, _, _ in docs}) > 1:
        return None
    consumed = set(range(mention.start, mention.end))
    for _, start, end in docs:
        consumed.update(range(start, end))
    hits = []
    for keyword in _keywords(tokens):
        extra = _adjacent(tokens, mention, keyword)
        if extra is not None:
            hits.append((keyword, extra))
    if len({keyword[0] for keyword, _ in hits}) > 1:
        return None
    kind = None
    if hits:
        kind = hits[0][0][0]
        for keyword, extra in hits:
            consumed.update(range(keyword[1], keyword[2]))
            consumed.update(extra)
    for i, token in enumerate(tokens):
        if i in consumed or token in fillers and (token != 'как' or tokens[i + 1:i + 2] == ['называется']):
            continue
        return None                                      # a word that is not filler: the person asks more than the title says
    lead = any(token in ('а', 'и') for token in tokens[:mention.start])
    return Reference(kind, mention, docs[0][0] if docs else None, lead, frozenset(consumed), tokens)


def _said_last(low, tokens, fillers=_FILLER, numbered=False):
    """Real speech comes with a preface: «Ну и короче я готов. А какой вопрос? Вопрос получается двадцать первая статья налогового кодекса», «Тебе нужно
    обязательно сказать, что такое девятая статья налогового кодекса». A whole reference (the word, and the code for an article) that is the last clause
    of the utterance is read alone, when the utterance names no other number and the clause before it in its sentence does not ask something of its
    own («как применяется вычет, статья 218 НК» wants more than a title). ``None`` otherwise. H7 item 0, ``numbered`` (behind the text channel): a remark that names numbers of its own before that clause is one all the same
    (253.7 of the call of 5 Nov: «… было 14 секунд, а он ответил в 16 секунд, … значит 55 статья налогового кодекса»), unless the clause right before it has one, or it names a reference."""
    if not numbered and len(_mentions(tokens)) != 1:
        return None
    sentences = _SENTENCE.split(low.rstrip(' .!?…'))
    clauses = _CLAUSE.split(sentences[-1])
    if len(sentences) + len(clauses) < 3:
        return None
    found = _reference(_TOKEN.findall(numbers.merge_digit_groups(clauses[-1])), fillers)
    if found is None or not found.kind or not (found.doc or found.kind == 'account'):
        return None
    before = _TOKEN.findall(numbers.merge_digit_groups(clauses[-2])) if len(clauses) > 1 else []
    if numbered and (_mentions(before) or _names_a_reference(tokens[:-len(found.tokens)])):
        return None
    return None if _ASKS_MORE.intersection(before) else found


def _names_a_reference(tokens):
    """Is there a number with its «статья» or «счёт» in ``tokens``? Then a last clause is no question of its own: it may be that reference said again (H4: the repeat in the question's turn)."""
    mentions = _mentions(tokens)
    return any(_adjacent(tokens, mention, keyword) is not None for keyword in _keywords(tokens) for mention in mentions)


def _context(line):
    """What an earlier line was about: a code (``'nk'``, ``'gk'``, ``'tk'``), ``'accounts'`` or ``None``."""
    if not isinstance(line, str) or len(line) > 2000:
        return None
    low = line.lower().replace('ё', 'е')
    tokens = _TOKEN.findall(numbers.merge_digit_groups(low))[:60]
    docs = _docs(tokens)
    if docs:
        return docs[-1][0]
    mentions = _mentions(tokens)
    for keyword in _keywords(tokens):
        if keyword[0] == 'account' and any(_adjacent(tokens, mention, keyword) is not None for mention in mentions):
            return 'accounts'
    return None


def newest(history, found):
    """THE one reading of the history a follow-up is attached to (reference-history, memory family): ``found`` of the newest line that gives an answer, else ``None``.
    ``history`` is what the controller hands over (``call_questions``: the call's last ``CALL_QUESTIONS``, the one window): no second window here; a ``str`` is one line."""
    if isinstance(history, str):
        history = (history,)
    try:
        lines = list(history)
    except TypeError:
        return None
    for line in reversed(lines):
        answer = found(line)
        if answer:
            return answer
    return None


# -- data and spoken text ----------------------------------------------------------------------------------------------

_DATA = {}


def _table(module, name):
    """A data table from ``kb_*`` (imported once); ``None`` when it cannot be loaded."""
    key = (module, name)
    if key not in _DATA:
        try:
            _DATA[key] = getattr(importlib.import_module('.' + module, __package__), name)
        except Exception:
            _DATA[key] = None
    return _DATA[key]


def preload():
    """Import every table now (the first question then costs no import).  Returns True when all of them are there."""
    tables = [_table(module, 'TITLES') for module, _ in _DOCS.values()]
    tables += [_table('kb_accounts', 'ACCOUNTS'), _table('kb_yo', 'YO')]
    return all(table is not None for table in tables)


def _answer_article(code, key):
    module, genitive = _DOCS[code]
    titles = _table(module, 'TITLES')
    title = titles.get(key) if titles else None
    if not title:
        return None
    if title.lower().startswith('утратил'):
        return 'Статья %s %s утратила силу.' % (article_said(key), genitive)
    return 'Статья %s %s — %s.' % (article_said(key), genitive, title_said(title))


def _answer_account(reference):
    accounts = _table('kb_accounts', 'ACCOUNTS')
    mention = reference.mention
    if not accounts:
        return None
    key = mention.key
    if mention.literal:                                  # «01», «001»: as written
        if not key.isdigit():
            return None
        off_balance = len(key) == 3
    elif key.isdigit():                                  # «71», «семьдесят первый»; «забалансовый счёт 1» is 001
        off_balance = any(token in _OFF_BALANCE_WORDS for token in reference.tokens)
        number = int(key)
        if number > (999 if off_balance else 99):
            return None
        key = '%03d' % number if off_balance else '%02d' % number
    else:
        return None
    name = accounts.get(key)
    if not name:
        return None
    return '%s %s — %s.' % ('Забалансовый счёт' if off_balance else 'Счёт', key, title_said(name))


# -- lookup ----------------------------------------------------------------------------------------------------------

def without_tail(text):
    """H7 item 0 (the owner's call of 5 Nov 10:27, «что такое пятнадцатый счёт в плане счетов ? 13 секунд»: he counted the seconds aloud): ``text`` without the short tail that asks nothing at its end: a word that
    closes speech (``_TAIL_WORDS``) or a time counted aloud («13 секунд», not «за две минуты», which says how). The text itself when there is none. The tail may be all of it: ``''``."""
    text = str(text or '')
    found = list(_TOKEN.finditer(text.lower().replace('ё', 'е')))
    tokens = [match.group() for match in found]
    end = len(tokens)
    while end:
        if tokens[end - 1] in _TAIL_WORDS:
            end -= 1
            continue
        counted = [mention for mention in _mentions(tokens[:end - 1]) if mention.end == end - 1] if tokens[end - 1] in _TIME_UNITS else ()
        if not counted or tokens[max(counted[-1].start - 1, 0):counted[-1].start] in _COUNT_LEADS:
            break
        end = counted[-1].start
    if end == len(tokens):
        return text
    return text[:found[end - 1].end()] if end else ''


def _lookup(text, history, fillers=_FILLER, tails=False):
    if not isinstance(text, str):
        return None
    text = text.strip()
    if tails:          # what stands after the reference and what is long before it: only the end of speech is read (``_said_last``)
        text = without_tail(text)[-_MAX_CHARS:]
    if not text or len(text) > _MAX_CHARS:
        return None
    low = text.lower().replace('ё', 'е')
    if not _HINT.search(low) or _RATIO.search(low):
        return None
    tokens = _TOKEN.findall(numbers.merge_digit_groups(low))
    reference = _reference(tokens, fillers) or _said_last(low, tokens, fillers, tails)
    if reference is None:
        return None
    mention, kind, code = reference.mention, reference.kind, reference.doc
    if kind is None:                                    # «а 27-я?», «а двадцать седьмая?», «а 62?»: the kind comes from the line before
        if not reference.lead or (fillers is not _FILLER and _PREPOSITIONS.intersection(tokens)):      # «а с пятого?» is a date, not an article
            return None
        context = newest(history, _context)
        if context is None:
            return None
        if code is not None:
            kind = 'article'
        elif mention.gender == 'f':
            kind = 'article' if context != 'accounts' else None
        elif mention.gender == 'm':
            kind = 'account' if context == 'accounts' else None
        else:
            kind = 'account' if context == 'accounts' else 'article'
        if kind is None:
            return None
        if kind == 'article':
            code = code or context
    elif kind == 'article' and code is None:          # «а статья 27?»: the code is the one just spoken about
        context = newest(history, _context)
        if context is None or context == 'accounts':
            return None
        code = context
    if kind == 'account':
        return None if code is not None else _answer_account(reference)
    if code not in _DOCS or not _PLAIN_KEY.fullmatch(mention.key):
        return None
    return _answer_article(code, mention.key)


def lookup(text: str, history: Sequence[str] = (), *, prepositions: bool = False, tails: bool = False) -> Optional[str]:
    """The exact spoken answer for a plain reference question («статья 19 НК», «71 счёт»), else ``None``.  Never raises.
    ``prepositions``: «с», «со» may stand around the reference (H4). ``tails``: H7 item 0: a short tail that asks nothing may stand after it (``without_tail``), and a remark of any length before it (``_said_last``).
    The controller asks for both behind the text channel: with that off it reads as it did."""
    try:
        found = _lookup(text, history, _WITH_PREPOSITIONS if prepositions else _FILLER, tails)
        if found is None:                                  # w4-law: verbatim text, parts and points, search by words (None without a base file)
            from . import law_base
            found = law_base.lookup(text, history)
        return found
    except Exception:
        return None
