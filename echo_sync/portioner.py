"""Answer -> spoken portions. Pure functions: the same answer and settings always give the same portions.

Three modes (``portion_mode``):

* ``words``      a fixed number of words (default 3), but a portion never ends on a
                 preposition, conjunction or particle and never cuts a number in half;
* ``syllables``  portions of about ``target_syllables`` (never above ``max_syllables`` or
                 ``max_words`` unless one indivisible unit is longer), cut at punctuation when
                 possible. Number + unit, "статья 228", initials and ALL-CAPS abbreviation
                 pairs are indivisible units.
* ``meaning``    (F1) a sentence when it fits the bounds, else whole clauses, else phrases: never
                 across a sentence end (razdel), never inside a phrase (_plan_meaning).

Portions are slices of the answer text (with its punctuation), so acknowledging them uses
exactly the same ``normalize`` as before.
"""
from __future__ import annotations

import collections
import functools
import re

from .abbrev_state import expand_abbreviations
from .settings import PRESETS, resolve
from .textutil import (ABBREVIATIONS, COPULAS, FUNCTION_WORDS as _RUSSIAN_FUNCTION_WORDS, LATIN_FUNCTION_WORDS, NEEDS_HEAD, STOPWORDS, LOCUTION_TAILS, NUMBER_WORDS, PREPOSITIONS,
                       SCALE_WORDS, WORDS, is_label, is_phone_phrase, is_unit, normalize, symbol_syllables, syllables,
                       word_syllables, MODALS)

FUNCTION_WORDS = _RUSSIAN_FUNCTION_WORDS | LATIN_FUNCTION_WORDS      # R21-09: a portion does not end on «the», «of», «without» either

# g27 portions by sense (U144): the rules below are always on, no key and no per-call switch.

__all__ = ['portions', 'syllables', 'cue_cuts', 'meaning_cuts']

# Cost model of the syllable mode: squared distance from the target length, minus a bonus
# for a cut that falls on punctuation (none, comma, ; : dash ) , sentence end).
BREAK_BONUS = (0, 6, 9, 14)
# The ONE table of the stream's lookahead: a streamed portion is committed once this many portions of the partial text are planned (the
# syllable planner balances a whole chain, so one portion behind it is not enough: DEF-SEG-17). 'meaning': an unfinished sentence planned
# into this many portions lets its first one go (_meaning_stable_end; a cut at a comma is where the whole plan cuts too, nearly always:
# 293 of 298 corpus answers). A listener waiting at the frontier longer than an idle segment takes to flush gets every arrived word that
# does not hang (stable_prefix(starving=True), _open_end).
STREAM_LOOKAHEAD = {'words': 2, 'syllables': 4, 'meaning': 3}
MIN_WORDS_PENALTY = 1000
HEAD_PENALTY = 100                # W1F-A: a portion that ends on a word that needs its head («очень», «это», «плотной»); below
                                  # MIN_WORDS_PENALTY, so a one-word portion is still worse, and the bounds are never broken for it

_NUMBER = re.compile(r'\d+(?:[-’\']\d+)*$')
_SUFFIXED_NUMBER = re.compile(r'\d+-[а-яё]{1,3}')                # «988-ым», «1856-го», «2024-м»
_ROMAN = re.compile(r'[IVXLCDM]{1,6}$')                  # XIX in «XIX веке»
_CENTURY = frozenset('век века веке веку веком веков веках'.split())
_DEGREE_SCALES = frozenset('CFKСК')                       # Latin and Cyrillic C and K: «100 °C», «0 K»
_LETTER_UNITS = frozenset('KVКВ')                         # «0 K» (kelvin), «220 В» (volt): one capital letter after a number
_RANGE_GAP = re.compile(r'\s?[–—]\s?')                     # 1941–1945, 15 — 20
_RATIO_GAP = re.compile(r'\s?:\s?')                        # 10:15, 3 : 1
_OPERATOR_GAP = re.compile(r'\s?(?:[+=×÷*−<>≤≥]|-(?=\s))\s?')   # 2 + 2 = 4, x = 3, 5 - 3
_CURRENCY_AFTER = frozenset('₽$€£¥')                     # «500 ₽» (after the number), unlike «$100» (before it)
_NAME = re.compile(r"[А-ЯЁA-Z][а-яёa-z]+(?:-[А-ЯЁA-Z][а-яёa-z]+)?$")   # Исаак, Ньютон, Римский-Корсаков
_SCALE_ABBREVIATIONS = frozenset('тыс млн млрд трлн'.split())
_OPENING = re.compile(r'(?:(?<=\s)|^)(?:[«“„‘(\[{"]+|[№§#$€₽£¥]\s?)\Z')  # belongs to the NEXT word
_GAP_DASH = re.compile(r'(?:(?<=\s)|^)(?:[—–]|-(?=\s))')     # g27: a dash that stands between words (not «1941–1945», which is glue)
_PUNCTUATION = re.compile(r'[,;:!?…—–()«»]')
_THOUSANDS_GAP = frozenset(' ' + chr(0xA0) + chr(0x202F) + chr(0x2009))  # space, no-break, narrow no-break, thin
_DETERMINERS=frozenset('все весь вся всех всем всему всякий всякая всякое каждый каждая каждое любой любая любое'.split())


class _Token:
    __slots__ = ('start', 'end', 'text', 'norm', 'syl', 'num', 'roman', 'name', 'caps', 'cap', 'initial', 'gap', 'brk')


def _tokenize(text):
    tokens = []
    for match in WORDS.finditer(text):
        t = _Token()
        t.start, t.end, t.text = match.start(), match.end(), match.group()
        t.norm = normalize(t.text)
        t.num = bool(_NUMBER.match(t.text))
        t.roman = bool(_ROMAN.match(t.text))
        t.name = bool(_NAME.match(t.text))
        letters = [c for c in t.text if c.isalpha()]
        t.caps = len(letters) >= 2 and all(c.isupper() for c in letters)
        t.cap = t.text[:1].isupper()
        t.initial = len(t.text) == 1 and t.text.isalpha() and t.text.isupper() and text[t.end:t.end + 1] == '.'
        t.syl = word_syllables(t.text)
        if any(c.isdigit() for c in t.text):
            t.syl += symbol_syllables(text, t.start, t.end)
        tokens.append(t)
    for i, t in enumerate(tokens):
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        t.gap = text[t.end:following.start] if following else text[t.end:]
        t.brk = _break(t, following)
    return tokens


def _break(token, following):
    """0 none, 1 comma, 2 ; : dash bracket or an abbreviation period, 3 sentence end."""
    gap = token.gap
    if following is None or any(c in gap for c in '!?…'):
        return 3
    if '.' in gap:
        # "А. С. Пушкин", "и т. д. Затем", "70 тыс. Человек" are no sentence end
        return 3 if following.cap and not token.initial and token.norm not in ABBREVIATIONS else 2
    if any(c in gap for c in ';:—–)»”') or ' - ' in gap:
        return 2
    return 1 if ',' in gap else 0


# --- what must stay together -----------------------------------------------------

_SHORT_LINKS = {('т', 'е'), ('т', 'к'), ('т', 'н'), ('т', 'о')}      # g27: «т. е.», «т. к.», «т. н.», «т. о.» are conjunctions: never a portion's end


def _abbreviated_link(tokens, i):
    t = tokens[i]
    if i + 1 < len(tokens) and '.' in t.gap and (t.norm, tokens[i + 1].norm) in _SHORT_LINKS:
        return True
    return i > 0 and '.' in tokens[i - 1].gap and (tokens[i - 1].norm, t.norm) in _SHORT_LINKS and i + 1 < len(tokens)


def _function_marks(tokens):
    """True where the token needs the next one (preposition, conjunction, particle, "в течение", «т. е.»)."""
    marks, locution = [], []
    for i, t in enumerate(tokens):
        tail = (i > 0 and t.norm in LOCUTION_TAILS and marks[i - 1] and tokens[i - 1].brk < 3
                and (tokens[i - 1].norm in PREPOSITIONS or locution[i - 1]))
        locution.append(bool(tail))
        # an initial is a letter of a name, not the conjunction: «Иванов И. И., а утвердил»
        marks.append(((t.norm in FUNCTION_WORDS or t.norm in _DETERMINERS or bool(tail)) and t.brk < 3 and not t.initial)
                     or _abbreviated_link(tokens, i))
    return marks


_CASES = {'loc2': 'loct', 'gen2': 'gent', 'acc2': 'accs', 'voct': 'nomn'}
_PRESENTS = frozenset({'представляет', 'представляют'})    # «представляет собой» + its noun


@functools.lru_cache(maxsize=16384)
def _forms(word):
    """``(attributive, nominal)``: the (case, number, gender) of every reading pymorphy3 gives a lower-case word as an adjective,
    participle or ordinal, and as a noun. Both empty without the analyzer (or on a word it cannot describe): no agreement is known
    then, and nothing is glued by it."""
    try:
        from . import ru_alignment as ru
        ru._lemma(word)                                   # creates the shared analyzer under its own lock
        with ru._LOCK:
            parses = ru._MORPH.parse(word)
    except Exception:
        return frozenset(), frozenset()
    attributive, nominal = set(), set()
    for parse in parses:
        tag = parse.tag
        case, number, gender = (str(value) if value else None for value in (tag.case, tag.number, tag.gender))
        form = (_CASES.get(case, case), number, gender)
        if tag.POS in ('ADJF', 'PRTF'):
            attributive.add(form)
        elif tag.POS == 'NOUN':
            nominal.add(form)
    return frozenset(attributive), frozenset(nominal)


def _agrees(adjective, noun):
    """Can ``adjective`` be an attribute of the ``noun`` right after it: the same case and number (and gender in the singular)?"""
    attributive = _forms(adjective)[0]
    if not attributive:
        return False
    for case, number, gender in attributive:
        for noun_case, noun_number, noun_gender in _forms(noun)[1]:
            if case == noun_case and number == noun_number and (
                    number != 'sing' or not gender or not noun_gender or gender == noun_gender
                    or (noun_gender == 'ms-f' and gender in ('masc', 'femn'))):
                return True
    return False


def _agrees_attributive(first, second):
    """R21-06: can ``first`` and ``second`` be attributes of one noun after them (the same case and number, and gender in the singular):
    «сохранённом | товарном» (виде), «новый | кожаный» (чемодан)?"""
    left, right = _forms(first)[0], _forms(second)[0]
    return any(case == other_case and number == other_number and (number != 'sing' or not gender or not other_gender or gender == other_gender)
               for case, number, gender in left for other_case, other_number, other_gender in right)


def _wordlike(token):
    return token.text.replace('-', '').isalpha()


def _copula(tokens, i):
    t = tokens[i]
    return t.norm in COPULAS or (t.norm == 'собой' and i > 0 and tokens[i - 1].norm in _PRESENTS)


def _head_marks(tokens, chains=False):
    """W1F-A, the ONE «cannot end a portion» predicate of portions(), stable_prefix() and cue_cuts(): True where the token needs the
    next word, its head. A degree word («почти нет», «очень яркий»), an existential «нет»/«есть», «самый», «такой», «этот», «который»,
    and an adjective, participle or ordinal that agrees with the noun right after it («плотной атмосферы»), unless punctuation follows
    them («Нет, звук…», «очень, очень»). A copula («это», «является», «представляет собой») needs its predicate even across a comma or
    a dash («масса — это, по сути, мера»): only the end of its sentence or clause (. ! ? : ;) frees it."""
    marks = []
    for i, t in enumerate(tokens):
        if i == len(tokens) - 1 or t.num or t.initial or not _wordlike(t):
            marks.append(False)
            continue
        if _copula(tokens, i):
            marks.append(t.brk < 3 and not any(c in t.gap for c in ':;'))
            continue
        quiet = not t.gap.strip()
        following = tokens[i + 1]
        # «и», «в», «с» have a noun reading too (the letter): a function word is never the noun an adjective agrees with
        marks.append(quiet and (t.norm in NEEDS_HEAD or (_wordlike(following) and following.norm not in FUNCTION_WORDS
                                                          and (_agrees(t.norm, following.norm) or (chains and _agrees_attributive(t.norm, following.norm))))))
    return marks


def number_goes_on(a_text, gap, b_text):
    """The one rule of a number that goes on in the next word (6,5; 1 500): the portioner's marks and the controller's tail cue read it here."""
    return a_text.isdigit() and b_text.isdigit() and (gap in (',', '.') or (gap in _THOUSANDS_GAP and len(b_text) == 3 and len(a_text) <= 3))


def _number_marks(tokens):
    """True where a decimal or a grouped number continues in the next token (6,5; 1 500)."""
    marks = [False] * len(tokens)
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        marks[i] = number_goes_on(a.text, a.gap, b.text)
    return marks


def _operand(token):
    return token.num or (len(token.text) == 1 and token.text.isalpha() and token.text.isascii())


def _joint_marks(tokens):
    """True where a symbol joins the token to the next one into a single value: «100 °C», «1941–1945», «10:15»,
    «3 : 1», «1/2», «км/ч», «2 + 2 = 4»."""
    marks = [False] * len(tokens)
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        gap = a.gap
        if a.num and re.fullmatch(r'\s?°', gap) and len(b.text) == 1 and b.text in _DEGREE_SCALES:
            marks[i] = True
        elif (a.num and b.num or a.roman and b.roman) and _RANGE_GAP.fullmatch(gap):
            marks[i] = True
        elif a.num and b.num and _RATIO_GAP.fullmatch(gap):
            marks[i] = True
        elif gap == '/' and a.text[-1:].isalnum() and b.text[:1].isalnum():
            marks[i] = True
        elif _operand(a) and _operand(b) and (a.num or b.num) and _OPERATOR_GAP.fullmatch(gap):
            marks[i] = True
    return marks


def _name_like(token):
    return token.name and token.norm not in STOPWORDS      # «Это», «Если» start sentences; they are no part of a name


def _name_marks(tokens, cfg):
    """True where a token is glued to the next because both belong to one personal name: «Исаак Ньютон», «Лев Николаевич
    Толстой» - capitalised words side by side, at most three, only when the name FITS the limits (a name longer than
    max_words / max_syllables cannot stay whole without overrunning them, and only an indivisible unit may overrun)."""
    n = len(tokens)
    marks = [False] * n
    i = 0
    while i < n:
        if not _name_like(tokens[i]):
            i += 1
            continue
        j = i
        while j + 1 < n and _name_like(tokens[j + 1]) and not tokens[j].gap.strip():
            j += 1
        first = max(i, j - 2)
        while first < j and (j - first + 1 > cfg['max_words'] or sum(t.syl for t in tokens[first:j + 1]) > cfg['max_syllables']):
            first += 1
        for k in range(first, j):
            marks[k] = True
        i = j + 1
    return marks


_MONTHS = frozenset('января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split())
_YEAR_WORDS = frozenset('год года году годом годе век века веке веку веком'.split())
_ERA_ADJECTIVES = frozenset('нашей новой'.split())


def _year_like(token):
    return token.num and token.text.isdigit() and 3 <= len(token.text) <= 4


def _era_follows(tokens, i):
    """Does the era («до нашей эры», «нашей эры», «до н. э.», «до н.э.») start at ``tokens[i]``?"""
    words = [t.norm for t in tokens[i:i + 4]]
    if words[:1] == ['до']:
        words = words[1:]
    return words[:2] == ['нашей', 'эры'] or words[:2] == ['новой', 'эры'] or words[:2] == ['н', 'э']


_RATE_PREPOSITIONS = frozenset('в за на по'.split())
_PER_NOUNS = frozenset('секунду секунды минуту минуты час часа сутки день дня неделю недели месяц месяца год года килограмм килограмма литр литра '
                       'метр метра человека душу штуку тонну сотку гектар гектара кубометр'.split())
_SCALES = frozenset('цельсию фаренгейту кельвину цельсия фаренгейта кельвина шкале'.split())
_ANNUAL = frozenset('годовых годовой'.split())


def _quantity(token):
    return token.num or token.norm in NUMBER_WORDS or token.norm in SCALE_WORDS


def _rate_marks(tokens, glue):
    """R21-03: a rate, a scale and a range belong to the number they measure; a cue that stops in front of them states another quantity («300 000 километров»
    for «300 000 километров в секунду», «5500 градусов» for «по Цельсию», «от 2500» for «от 2500 до 3500 рублей»). Glued here: the unit to its rate («километров
    в секунду», «рубля в месяц», «килокалорий на 100 граммов», «рублей за килограмм»), to its scale («градусов по Цельсию»), to «годовых» («16 процентов годовых»),
    and a number (or its unit) to the «до» / «по» of a range that opens with «от» / «с» («от 2500 до 3500», «с 1337 по 1453»)."""
    n = len(tokens)
    for i in range(1, n - 1):
        a, b = tokens[i], tokens[i + 1]
        if _PUNCTUATION.search(a.gap) or '.' in a.gap:
            continue
        if is_unit(a.norm) and _quantity(tokens[i - 1]):
            if b.norm in _ANNUAL or (b.norm in _RATE_PREPOSITIONS and i + 2 < n and (
                    (b.norm == 'по' and tokens[i + 2].norm in _SCALES) or (b.norm != 'по' and (is_unit(tokens[i + 2].norm) or tokens[i + 2].norm in _PER_NOUNS))
                    or (b.norm == 'на' and tokens[i + 2].num and i + 3 < n and is_unit(tokens[i + 3].norm)))):
                glue[i] = True
        if b.norm in ('до', 'по') and i + 2 < n and _quantity(tokens[i + 2]) and (
                _quantity(a) or (is_unit(a.norm) and _quantity(tokens[i - 1]))):
            if any(tokens[k].norm in ('от', 'с', 'со') for k in range(max(0, i - 3), i)):
                glue[i] = True


def _unit_marks(tokens, rates=False):
    """True where the token is glued to the next one: number+unit, label+number, initials, abbreviation pairs."""
    n = len(tokens)
    glue = [False] * n
    caps_run = 0
    for i in range(n - 1):
        a, b = tokens[i], tokens[i + 1]
        quiet = not _PUNCTUATION.search(a.gap)
        if a.num and quiet and '.' not in a.gap and (is_unit(b.norm) or b.text in _LETTER_UNITS):
            glue[i] = True
        elif a.norm in SCALE_WORDS and quiet and (is_unit(b.norm) or b.norm in NUMBER_WORDS) and (
                '.' not in a.gap or (a.norm in _SCALE_ABBREVIATIONS and a.gap.startswith('.') and not b.cap)):
            glue[i] = True    # «2,3 млн рублей», «тысяча пятьсот», «70 тыс. человек»
        elif a.norm in NUMBER_WORDS and quiet and '.' not in a.gap and (
                b.norm in NUMBER_WORDS or b.norm in SCALE_WORDS or is_unit(b.norm)):
            glue[i] = True    # «сто восемьдесят градусов», «при ста градусах», «три тысячи километров»
        elif b.num and quiet and (is_label(a.norm) or '№' in a.gap or '§' in a.gap):
            glue[i] = True
        elif a.roman and quiet and b.norm in _CENTURY:
            glue[i] = True  # XIX веке
        elif a.norm in _MONTHS and quiet and _year_like(b):
            glue[i] = True    # R21-01: «28 июля | 1914 года» is one date, the year is what «когда» asks for
        elif a.norm in _YEAR_WORDS and quiet and _era_follows(tokens, i + 1):
            glue[i] = True    # R21-02: «в 490 году | до нашей эры», «в 5 веке до н. э.»: the era changes the answer by two thousand years
        elif a.norm in _ERA_ADJECTIVES and b.norm == 'эры' and quiet:
            glue[i] = True
        elif a.caps and b.caps and caps_run < 2 and not a.gap.strip() and len(a.text) <= 6 and len(b.text) <= 6:
            glue[i] = True
            caps_run += 1
            continue
        elif a.initial and (b.initial or (b.cap and ',' not in a.gap)):
            glue[i] = True    # «А. С. Пушкин»; «Иванов И. И., Петров П. П.» keeps the comma between two names
        elif a.norm in ('т', 'н') and a.gap.startswith('.') and len(b.text) == 1:
            glue[i] = True  # т. д., т. е., т. п., н. э.
        caps_run = 0
    if rates:
        _rate_marks(tokens, glue)           # R21-03: in the call profile only; the older profiles keep their word and syllable bounds exact
    # Initials after the surname ("Иванов И. И."): glue the surname to the run.
    i = 0
    while i < n:
        if tokens[i].initial:
            j = i
            while j < n - 1 and tokens[j].initial and glue[j] and tokens[j + 1].initial:
                j += 1
            surname_follows = j < n - 1 and glue[j]
            if not surname_follows and i > 0 and tokens[i - 1].cap and not tokens[i - 1].initial and tokens[i - 1].brk < 3:
                glue[i - 1] = True
            i = j + 1
        else:
            i += 1
    return glue


# --- planning --------------------------------------------------------------------

def _plan_words(tokens, func, number, size):
    """Token indexes where portions start/end: ``size`` words, never ending on a function word or inside a number."""
    n = len(tokens)
    cuts, i = [0], 0
    while i < n:
        end = min(i + size, n)
        k = end
        while k < n and number[k - 1]:
            k += 1
        while k > i + 1 and (func[k - 1] or number[k - 1]):
            k -= 1  # move the dangling word to the next portion
        if func[k - 1] or number[k - 1]:
            k = end  # nothing but function words: take the following word instead
            while k < n and (func[k - 1] or number[k - 1]):
                k += 1
        cuts.append(k)
        i = k
    return cuts


def _plan_syllables(tokens, glue, cfg, heads=None, counted=None):
    n = len(tokens)
    target, max_syl, max_words = cfg['target_syllables'], cfg['max_syllables'], cfg['max_words']
    min_words, long_word = cfg['min_words'], cfg['long_word_syllables']
    heads, counted = heads or [False] * n, counted or [False] * n
    # (end token index, syllables, words, break strength after, ends on a word that needs its head, is a bare number cut from the
    # word it counts)
    units, i = [], 0
    while i < n:
        j = i
        while j < n - 1 and glue[j]:
            j += 1
        units.append((j + 1, sum(t.syl for t in tokens[i:j + 1]), j + 1 - i, tokens[j].brk, heads[j], j == i and counted[j]))
        i = j + 1
    u = len(units)
    predicates = _predicates(tokens)
    best = [float('inf')] * (u + 1)
    best[0] = 0
    back = [0] * (u + 1)
    for a in range(u):
        syl = words = 0
        for b in range(a, u):
            syl += units[b][1]
            words += units[b][2]
            if b > a and (syl > max_syl or words > max_words):
                break  # a single indivisible unit may overrun; two units may not
            cost = (syl - target) ** 2 - BREAK_BONUS[units[b][3]]
            if words < min_words and not (words == 1 and syl >= long_word):
                cost += MIN_WORDS_PENALTY * (min_words - words)
            if units[b][4] or (a == b and units[b][5]):
                cost += HEAD_PENALTY
            if best[a] + cost < best[b + 1]:
                best[b + 1], back[b + 1] = best[a] + cost, a
    ends, k = [], u
    while k > 0:
        ends.append(units[k - 1][0])
        k = back[k]
    return [0] + ends[::-1]


# --- meaning-sized portions (F1) ---------------------------------------------------------------------------------------------------
# The owner's call of 3 Nov 09:55 was cut «Это статья о правах» | «налогоплательщиков» | «в первой части» | «Налогового кодекса» |
# «РФ. Она»: every portion costs the listener a whole cycle (the cue, the repeat, its recognition: about 5 s), so 1-3-word portions made
# an answer take a minute and sound fake. ``portion_mode='meaning'`` (the preset 'meaning') cuts a sentence when it fits the bounds,
# else at its clause punctuation, else between phrases: the syllable planner's search with a sentence end as a forced cut
# (razdel.sentenize, which knows «РФ.», «т. е.», initials), a cut inside a phrase costing what tearing that phrase costs the listener
# (_meaning_links) and every portion costing a cycle (MEANING_PORTION_COST), so that what fits stays whole. The costs are local to a
# portion, so the plan of a text that ends at a planned cut is the plan of the whole text up to there (stable_prefix relies on it).
MEANING_PORTION_COST = 40         # one more portion is one more cycle
MEANING_ZONE = 5                  # target ± 5 syllables costs nothing for its size (8-18 at the preset's 13); outside: the squared gap
MEANING_FIRST_MAX_WORDS = 8       # the first portion of a call: up to 8 words (first_useful.first_cue)
# C7-A: the first portion of an answer to a question for a number or a date runs on until it holds the number, up to 12 words and
# 10 syllables over max_syllables («Базовая ставка налога на доходы физических лиц составляет 13 процентов.»). Not in a profile that
# asks for shorter portions than a first portion (max_words below MEANING_FIRST_MAX_WORDS): there its own cap stays.
MEANING_NUMBER_FIRST_MAX_WORDS = 12
MEANING_NUMBER_EXTRA_SYLLABLES = 10
# g27: a whole sentence of at most max_words words may run this many syllables over max_syllables: «Налоговая декларация — это письменное заявление
# налогоплательщика.» (28) is one definition, not «… — это | письменное заявление налогоплательщика.»; its zone cost still weighs it against a cheap cut
MEANING_WHOLE_EXTRA_SYLLABLES = 10
MEANING_EARLY_WORDS = 5           # a first clause this long that says something new is spoken as soon as it has arrived
MEANING_MIN_WORDS = 4             # g27: 4-9 words a portion
SHORT_NO_PREDICATE = 40           # g27: per word below MEANING_MIN_WORDS for a portion that says nothing of its own (no predicate)
SHORT_PENALTY = 80                # per word below min_words, for a portion cut out of a longer sentence
CLAUSE_BONUS = (0, 40, 50, 60)    # a cut at: no punctuation, a comma, ; : dash bracket, a sentence end razdel did not see
LINK_HEAD = 100                   # W1F-A: a word that needs its head («плотной | атмосферы», «очень | яркий», «это | масса»)
LINK_GENITIVE = 100               # a noun and the genitive after it: «о правах | налогоплательщиков», «части | Налогового кодекса»
LINK_PRONOUN = 100                # a personal pronoun and its verb: «Она | перечисляет»
LINK_MODIFIER = 60                # an adverb and the word it modifies: «традиционно | относят»
LINK_APPOSITION = 60              # a noun and the name after it: «князь | Владимир»
LINK_NEGATION = 60                # R21-07: a cut right in front of «не», «нельзя»: the portion would end before the word that turns its meaning round
LINK_CONTRAST = 60                # R21-07: «не нагревать, | а охлаждать»: a cost, not a ban - a half that does not fit the window is still cut there
LINK_DASH = 90                    # g27: a term and what the dash says it is: «Статья 59 Налогового кодекса | — безнадёжные долги», «пассивный | — источники»
LINK_DEFINITION = 150             # g27: a term and the copula of its definition: «Налоговая декларация | — это», «Налог | является», «… — это | письменное»
LINK_QUANTITY = 200               # g27: a bound and its number: «не менее | 183 дней»
LINK_VERB_ADVERB = 40             # a verb and its adverb: «распределяются | централизованно»
LINK_COORDINATION = 30            # before «и», «или»: «ресурсы | и производство»
LINK_OBJECT = 30                  # a verb and its object: «получать | бесплатную информацию»
LINK_OTHER = 20
LINK_SUBJECT = 15                 # a noun phrase and its verb: «ресурсы и производство | распределяются»
LINK_BEFORE_PREPOSITION = 5       # a new prepositional phrase: «налогоплательщиков | в первой части»
# A clause starts at these words: a cut before one is free (they are function words, so no cut ever falls right after one).
_CLAUSE_OPENERS = frozenset(
    'что чтобы когда где куда откуда если хотя пока потому поэтому поскольку ибо а но однако зато причём притом будто словно чем '
    'нежели который которая которое которые которого которой которому которым котором которых которую чей чья чьё чьи'.split())
_COORDINATORS = frozenset('и или либо'.split())
_NEGATIONS = frozenset('не ни нельзя нет'.split())         # R21-07: a portion does not end right in front of the negation of its predicate
_CONTRAST = frozenset('а но зато однако'.split())          # «не нагревать, | а охлаждать»: the second half is what the first one is for
_CORRELATIVES = frozenset('то того тому тем том та той ту те тех теми такой такая такое такие таким так столько'.split())
_PERSONAL = frozenset('я ты он она оно мы вы они'.split())
_PREDICATES = frozenset({'VERB', 'INFN', 'PRTS', 'GRND', 'ADJS', 'PRED'})


@functools.lru_cache(maxsize=16384)
def _tag(word):
    """``(part of speech, genitive)`` of a lower-case word: the part of speech of its likeliest pymorphy3 reading, and whether a noun,
    adjective or participle reading of it is genitive. ``('', False)`` without the analyzer."""
    try:
        from . import ru_alignment as ru
        ru._lemma(word)                                   # creates the shared analyzer under its own lock
        with ru._LOCK:
            parses = ru._MORPH.parse(word)
    except Exception:
        return '', False
    if not parses:
        return '', False
    return (str(parses[0].tag.POS or ''),
            any(p.tag.POS in ('NOUN', 'ADJF', 'PRTF') and p.tag.case in ('gent', 'gen2') for p in parses))


# A noun that names what the next name is: «князь Владимир», «озеро Байкал», «планета Венера» (but «в 1812 году | Наполеон» is a subject).
_TITLES = frozenset(
    'князь княгиня царь царица король королева император императрица святой святая генерал адмирал маршал президент '
    'премьер министр ученый писатель поэт композитор художник философ физик химик математик историк инженер изобретатель '
    'река озеро море океан залив пролив гора хребет остров полуостров город село деревня страна государство планета звезда '
    'спутник корабль судно крейсер ракета компания фирма театр музей университет журнал газета роман повесть поэма'.split())


def _title(word):
    try:
        from . import ru_alignment as ru
        return ru._lemma(word) in _TITLES
    except Exception:
        return False


def _phrase_link(tokens, i, heads):
    """What a cut between ``tokens[i]`` and the next word costs when no clause punctuation stands between them (a quotation mark
    may: «безопасный «образец»» still agrees)."""
    a, b = tokens[i], tokens[i + 1]
    pa = _tag(a.norm)[0] if _wordlike(a) else ''
    pb, genitive = _tag(b.norm) if _wordlike(b) else ('', False)
    if pa in ('ADJF', 'PRTF') and _wordlike(b) and b.norm not in FUNCTION_WORDS and _agrees(a.norm, b.norm):
        return LINK_HEAD
    nominal = pa == 'NOUN' or a.caps or a.num                # «статья 421 | Гражданского кодекса» belongs together as well
    if nominal and (b.caps or (genitive and (pb == 'NOUN' or (pb in ('ADJF', 'PRTF') and heads[i + 1])))):
        return LINK_GENITIVE
    if b.num and a.text.isascii() and a.text.replace('-', '').isalpha():
        return LINK_GENITIVE                                   # a Latin name and its version: «Python 3.12», «Windows 11» (DEF-T-13)
    if pa == 'NOUN' and b.cap and _name_like(b) and _title(a.norm):
        return LINK_APPOSITION
    if pa == 'NPRO' and a.norm in _PERSONAL and pb in _PREDICATES:
        return LINK_PRONOUN
    if pa == 'ADVB' and pb in _PREDICATES | {'ADJF', 'PRTF', 'ADVB', 'COMP'}:
        return LINK_MODIFIER
    if pa in ('VERB', 'INFN', 'GRND', 'PRED', 'ADJS', 'PRTS') and pb == 'ADVB':
        return LINK_VERB_ADVERB
    if pa in _PREDICATES and (pb in ('NOUN', 'ADJF', 'PRTF', 'NPRO', 'NUMR', 'INFN') or b.num):
        return LINK_OBJECT
    if (nominal or pa == 'NPRO') and pb in _PREDICATES:
        return LINK_SUBJECT
    return LINK_OTHER


_CLAUSE_PUNCTUATION = re.compile(r'[,;:—–.!?…()]| - ')


def _dash_only(gap):
    """g27: a dash and no other clause mark between two words: «Статья 59 — | безнадёжные», «пассивный — | источники». What stands before it
    is the subject or the term, what follows is what it is: no clause ends there."""
    return bool(_GAP_DASH.search(gap)) and not re.search(r'[,;:.!?…()]', gap)


def _meaning_break(token):
    """``_break`` for clauses: a quotation mark is no boundary («безопасный «образец» возбудителя» is one phrase), nor is a dash alone (g27)."""
    if token.brk == 2 and (not _CLAUSE_PUNCTUATION.search(token.gap) or _dash_only(token.gap)):
        return 0
    return token.brk


# R21-11: a noun that names a measure and the number that measures it: «температурой | около восьмидесяти градусов», «ставка | 20 процентов»
_MEASURES = frozenset('температура скорость длина ширина высота глубина площадь масса вес рост цена стоимость размер возраст сумма ставка срок объём объем '
                      'расстояние давление мощность частота плотность напряжение количество толщина диаметр'.split())
_APPROXIMATELY = frozenset('около примерно приблизительно почти свыше более менее порядка ровно'.split())
# R21-11: a subordinate clause that has not yet got its predicate («потому что вес вытесненной воды | равен», «если налоговый агент | уже удержал»)
_SUBORDINATORS = frozenset('если когда пока потому поскольку хотя чтобы'.split())


def _measure_then_number(tokens, i):
    a, b = tokens[i], tokens[i + 1]
    if not (_wordlike(a) and (b.num or b.norm in NUMBER_WORDS or b.norm in _APPROXIMATELY)):
        return False
    try:
        from . import ru_alignment as ru
        return ru._lemma(a.norm) in _MEASURES
    except Exception:
        return False


_BOUNDS = frozenset('позднее позже ранее раньше'.split())       # g27: «не позднее 28-го числа», «не ранее 1 января»
_SUBUNITS = frozenset('копеек копейки копейка копейку центов цента цент'.split())


def _subunit_follows(tokens, i):
    """g27: ``tokens[i]`` is a currency word and a number of its smaller unit follows: «рублей | 50 копеек»."""
    return (i + 2 < len(tokens) and tokens[i].norm.startswith(('рубл', 'доллар', 'евро')) and tokens[i + 1].text[:1].isdigit()
            and tokens[i + 2].norm in _SUBUNITS)


def _inside_subordinate_clause(tokens, i):
    """Is the cut after ``tokens[i]`` inside a clause that opens with «если», «когда», «потому что» … and holds no predicate yet?"""
    for j in range(i, -1, -1):
        t = tokens[j]
        if t.norm in _SUBORDINATORS:
            return True
        if _wordlike(t) and (_tag(t.norm)[0] in _PREDICATES or t.norm in ('нужно', 'можно', 'нельзя', 'надо', 'пора')):
            return False
        if j and _CLAUSE_PUNCTUATION.search(tokens[j - 1].gap):
            return False
    return False


def _elliptic_contrast(tokens, i):
    """g27: «X, а не Y» with no predicate of its own after «не» («источники, а не имущество»): Y is said only against X. «…, но не даёт
    выигрыша» is a clause of its own."""
    if i + 3 >= len(tokens) or tokens[i + 2].norm not in ('не', 'ни'):
        return False
    return not (_wordlike(tokens[i + 3]) and _tag(tokens[i + 3].norm)[0] in _PREDICATES)


def _negated_clause(tokens, i):
    """R21-07: does the clause that ends at ``tokens[i]`` hold a «не» / «ни» (back to the last clause punctuation)? «Нужно не нагревать, а охлаждать»."""
    for j in range(i, -1, -1):
        if tokens[j].norm in ('не', 'ни'):
            return True
        if j and _CLAUSE_PUNCTUATION.search(tokens[j - 1].gap):
            return False
    return False


def _meaning_links(tokens, heads):
    """What a cut after each token costs the listener: tearing the phrase the token belongs to. Clause punctuation after it frees the
    token (the clause bonus applies there; a quotation mark does not), except a word that needs its head (W1F-A: «это,» still needs its
    predicate)."""
    links, sense = [0] * len(tokens), True
    for i in range(len(tokens) - 1):
        following = tokens[i + 1].norm
        if not sense:
            pass
        elif (tokens[i].norm in _APPROXIMATELY or tokens[i].norm in _BOUNDS) and (tokens[i + 1].text[:1].isdigit() or tokens[i + 1].norm in NUMBER_WORDS):
            links[i] = LINK_QUANTITY                       # g27: «не менее | 183 дней», «около | 20 процентов», «не позднее | 28-го числа»
        elif _subunit_follows(tokens, i):
            links[i] = LINK_QUANTITY                       # g27: «1 250 000 рублей | 50 копеек» is one sum
        if links[i]:
            pass
        elif heads[i]:
            links[i] = LINK_DEFINITION if sense and tokens[i].norm in COPULAS else LINK_HEAD
        elif sense and tokens[i].norm in _CORRELATIVES and ',' in tokens[i].gap:
            links[i] = LINK_HEAD                           # g27: «и те, | кто связан», «кроме той, | по которой»: the clause says who
        elif following in _CONTRAST and (_negated_clause(tokens, i) or (sense and _elliptic_contrast(tokens, i))):
            links[i] = LINK_CONTRAST                       # g27: «отражает источники, | а не имущество» as well
        elif sense and following in COPULAS and not re.search(r'[;:.!?…()]', tokens[i].gap) and (',' not in tokens[i].gap or _GAP_DASH.search(tokens[i].gap)):
            links[i] = LINK_DEFINITION
        elif sense and _dash_only(tokens[i].gap):
            links[i] = LINK_DASH
        elif _CLAUSE_PUNCTUATION.search(tokens[i].gap) or following in _CLAUSE_OPENERS:
            links[i] = 0
        elif following in _NEGATIONS:
            links[i] = LINK_NEGATION
        elif _measure_then_number(tokens, i) or _inside_subordinate_clause(tokens, i):
            links[i] = LINK_HEAD
        elif following in _COORDINATORS:
            links[i] = LINK_COORDINATION
        elif following in PREPOSITIONS:
            # «друг | по другу», «друг | к другу» is one pronoun with its preposition inside; a short participle or adjective needs the complement
            # its preposition brings («повёрнута | к Солнцу», «основан | на», «способен | на»): R21-11
            reciprocal = tokens[i].norm == 'друг' and i + 2 < len(tokens) and tokens[i + 2].norm.startswith('друг')
            governed = _wordlike(tokens[i]) and _tag(tokens[i].norm)[0] in ('PRTS', 'ADJS')
            links[i] = LINK_HEAD if reciprocal or governed else LINK_BEFORE_PREPOSITION
        else:
            links[i] = _phrase_link(tokens, i, heads)
    return links


# g27: the mark of an item of a list goes with its item: «Основные моменты: 1) | микропредприятиям», «во-вторых, | это федеральный налог»
_ITEM_WORDS = frozenset('во-первых во-вторых в-третьих в-четвёртых в-четвертых в-пятых в-шестых первое второе третье четвёртое четвертое пятое'.split())


def _item_marks(text, tokens):
    """True on the mark of a list item: «1)», «а)», «2.» at the start of a line, «во-первых,», «Второе —» opening its sentence or clause."""
    marks = []
    for i, t in enumerate(tokens):
        before = tokens[i - 1].gap if i else text[:t.start]
        opens = i == 0 or bool(re.search(r'[:;.!?\n]\s*$', before)) or bool(re.search(r'^\s*$', before) and i == 0)
        mark = bool((t.num and len(t.text) <= 2 or (len(t.text) == 1 and t.text.isalpha() and t.text.islower())) and re.match(r'\)\s', t.gap)
                    and (opens or re.search(r'[,(]\s*$', before)))
        mark = mark or bool(t.num and len(t.text) <= 2 and re.match(r'\.\s', t.gap) and (i == 0 or '\n' in before))
        mark = mark or bool(t.norm in _ITEM_WORDS and (opens or ',' in before) and re.match(r'\s*(?:[,:—–]|\s-)', t.gap) and i + 1 < len(tokens))
        marks.append(mark)
    return marks


def _sentence_marks(text, tokens):
    """True after the last token of every sentence ``razdel.sentenize`` finds («РФ. Она» is two, «т. е. масса», «А. С. Пушкин» and
    «70 тыс. человек» are one); the last token always ends one."""
    marks = [False] * len(tokens)
    if not tokens:
        return marks
    try:
        from razdel import sentenize
        stops = [sentence.stop for sentence in sentenize(text)]
    except Exception:                                    # no razdel: the punctuation alone (_break) says where a sentence ends
        stops = [t.end for t in tokens if t.brk == 3]
    j = 0
    for stop in stops:
        while j + 1 < len(tokens) and tokens[j + 1].start < stop:
            j += 1
        marks[j] = True
    marks[-1] = True
    return marks


def _meaning_marks(text, tokens, cfg, spans):
    """``(glue, heads, links, sentences)`` of the meaning planner. Glue - what is never cut - is the syllable planner's (function words,
    numbers, units, names, terms) and a number with the word it counts («988 году», «пять машин»); a sentence end is never glue."""
    func = _function_marks(tokens)
    number = [n or t or j for n, t, j in zip(_number_marks(tokens), _term_marks(tokens, spans), _joint_marks(tokens))]
    names = _name_marks(tokens, cfg)
    items = _item_marks(text, tokens)
    glue = [f or m or u or p or c or k for f, m, u, p, c, k in
            zip(func, number, _unit_marks(tokens, rates=True), names, _counted_marks(tokens), items)]
    sentences = _sentence_marks(text, tokens)
    for i, k in enumerate(items):
        if k and sentences[i] and i + 1 < len(tokens):
            sentences[i] = False                      # «Виды документов:\n1. Первичные»: razdel ends a sentence at «1.»; it ends before it
            if i:
                sentences[i - 1] = True
    glue = [g and not s for g, s in zip(glue, sentences)]
    heads = _head_marks(tokens, chains=True)         # R21-06: only the call profile keeps two adjectives of one noun together
    return glue, heads, _meaning_links(tokens, heads), sentences


def _zone_cost(syllables, cfg):
    low, high = cfg['target_syllables'] - MEANING_ZONE, cfg['target_syllables'] + MEANING_ZONE
    return (low - syllables) ** 2 if syllables < low else (syllables - high) ** 2 if syllables > high else 0


def _short_cost(words, whole, cfg, predicate=True):
    """A portion cut out of a longer sentence: one word never (unless nothing else fits), fewer than min_words words at a price; g27: fewer
    than MEANING_MIN_WORDS words without a predicate at a price too, in a profile whose portions may hold twice that many («Пассивный счёт —
    это счёт источников: | остаток по кредиту.», «Различие в том, | где …»; «Она перечисляет, например,» says something and stays)."""
    if whole:
        return 0
    if words == 1:
        return MIN_WORDS_PENALTY
    cost = SHORT_PENALTY * max(0, cfg['min_words'] - words)
    if not predicate and cfg['max_words'] >= 2 * MEANING_MIN_WORDS:
        cost += SHORT_NO_PREDICATE * max(0, MEANING_MIN_WORDS - max(words, cfg['min_words']))
    return cost


def _predicates(tokens):
    """g27: running count of the tokens that are a predicate (a verb, a short adjective or participle, «нужно»)."""
    counts = [0]
    for t in tokens:
        counts.append(counts[-1] + bool(_wordlike(t) and (_tag(t.norm)[0] in _PREDICATES or t.norm in MODALS or t.norm in COPULAS)
                                        or _dash_only(t.gap)))
    return counts


def _plan_meaning(tokens, cfg, glue, links, sentences):
    """Token indexes where meaning portions start and end: the cheapest plan of every sentence on its own."""
    n = len(tokens)
    max_syl, max_words = cfg['max_syllables'], cfg['max_words']
    extra = MEANING_WHOLE_EXTRA_SYLLABLES
    # (end token index + 1, syllables, words, last token index, starts a sentence)
    units, i = [], 0
    while i < n:
        j = i
        while j < n - 1 and glue[j]:
            j += 1
        units.append((j + 1, sum(t.syl for t in tokens[i:j + 1]), j + 1 - i, j, i == 0 or sentences[i - 1]))
        i = j + 1
    u = len(units)
    predicates = _predicates(tokens)
    best = [float('inf')] * (u + 1)
    best[0] = 0
    back = [0] * (u + 1)
    for a in range(u):
        syl = words = 0
        for b in range(a, u):
            syl += units[b][1]
            words += units[b][2]
            last = units[b][3]
            if b > a and (syl > max_syl + extra or words > max_words):
                break                                       # a single indivisible unit may overrun; two units may not
            if b > a and syl > max_syl and not (units[a][4] and sentences[last]):
                if sentences[last]:
                    break
                continue                                    # g27: only a whole sentence of max_words words may run over max_syllables
            first = units[a - 1][0] if a else 0
            cost = MEANING_PORTION_COST + _zone_cost(syl, cfg) + _short_cost(words, units[a][4] and sentences[last], cfg,
                                                                             predicates[last + 1] > predicates[first])
            if not sentences[last]:
                cost += links[last] - CLAUSE_BONUS[_meaning_break(tokens[last])]
            if best[a] + cost < best[b + 1]:
                best[b + 1], back[b + 1] = best[a] + cost, a
            if sentences[last]:
                break                                       # never across a sentence end
    ends, k = [], u
    while k > 0:
        ends.append(units[k - 1][0])
        k = back[k]
    return [0] + ends[::-1]


def _begins(text, tokens):
    """Where each token's portion would begin: an opening quote, bracket or sign travels with the NEXT word, and so does a dash between
    words (g27: no portion ends on «—», «Статья 59 Налогового кодекса —» left the listener hanging: the dash opens what follows it)."""
    begins = [0]
    for i in range(1, len(tokens)):
        gap = tokens[i - 1].gap
        opening = _OPENING.search(gap)
        if opening and _closes_a_number(tokens[i - 1], gap, opening):
            opening = None
        dash = _GAP_DASH.search(gap)
        start = min(x for x in (dash and dash.start(), opening and opening.start()) if x is not None) if dash or opening else None
        begins.append(tokens[i].start - (len(gap) - start) if start is not None else tokens[i].start)
    begins.append(len(text))
    return begins


def _closes_a_number(previous, gap, opening):
    """«500 ₽ за»: a currency sign that follows a number (and is followed by a space) belongs to that number,
    unlike «$100» or «№ 5», which belong to what comes next."""
    sign = gap[opening.start():opening.end()]
    return (sign.strip() in _CURRENCY_AFTER and sign != sign.strip()
            and (previous.num or previous.norm in SCALE_WORDS))


def _slice(text, tokens, cuts):
    begins = _begins(text, tokens)
    result = []
    for a, b in zip(cuts, cuts[1:]):
        piece = ' '.join(text[begins[a]:begins[b]].split())
        if piece:
            result.append(piece)
    return result


def _spans(text, tokens, cuts):
    """``(start, end)`` of every portion IN ``text`` itself (the portion strings have their whitespace collapsed, so
    they cannot be searched for in a text that holds a no-break space, a double space or a line break)."""
    begins = _begins(text, tokens)
    result = []
    for a, b in zip(cuts, cuts[1:]):
        raw = text[begins[a]:begins[b]]
        if raw.split():
            result.append((begins[a], begins[a] + len(raw.rstrip())))
    return result


def _avoid_phone_commands(text, tokens, cuts):
    """Merge every portion that equals (or essentially is) a phrase the phone handles locally (Stop/End) with a neighbour.

    The neighbour across the weaker punctuation wins, so sentence ends survive. Returns ``None`` when
    the whole answer is such a phrase: there is nothing to merge with and it must not be spoken.
    """
    cuts = list(cuts)
    while True:
        pieces = _slice(text, tokens, cuts)
        bad = next((k for k, piece in enumerate(pieces) if is_phone_phrase(piece)), None)
        if bad is None:
            return cuts
        if len(pieces) == 1:
            return None
        if bad == 0:
            drop = 1
        elif bad == len(pieces) - 1:
            drop = bad
        else:
            before, after = tokens[cuts[bad] - 1].brk, tokens[cuts[bad + 1] - 1].brk
            drop = bad if before < after else bad + 1
        del cuts[drop]


# --- abbreviations ---------------------------------------------------------------

def _term_marks(tokens, spans):
    """True where a token and the next one belong to the same expanded term: a term is never cut in half."""
    marks = [False] * len(tokens)
    for a, b in spans:
        inside = [i for i, t in enumerate(tokens) if a <= t.start and t.end <= b]
        for i, j in zip(inside, inside[1:]):
            marks[i] = j == i + 1
    return marks


def _term_spans(text, table):
    """Where the full terms of the abbreviation table already stand in ``text`` (a text that is already spoken)."""
    spans = []
    for full in table.values():
        words = full.split()
        if words:
            pattern = r'(?<![\w-])' + r'\s+'.join(re.escape(word) for word in words) + r'(?![\w-])'
            spans += [(m.start(), m.end()) for m in re.finditer(pattern, text, re.I)]
    return spans


def _plan(answer, cfg, *, spoken=False):
    """``(text, tokens, cuts)``: the answer after abbreviation expansion, its tokens, and the token indexes where portions
    begin and end. ``cuts`` is empty when the answer has no words or is nothing but a phrase the phone handles itself.
    ``spoken``: the text is already what is spoken (the producer expanded the abbreviations once, for the whole answer):
    it is not expanded again, but a term that stands in it is still never cut."""
    source = '' if answer is None else str(answer)
    text = source if spoken else expand_abbreviations(source, cfg['abbreviations'])
    spans = _term_spans(text, cfg['abbreviations'])
    tokens = _tokenize(text)
    if not tokens:
        return text, tokens, []
    if cfg['portion_mode'] == 'meaning':
        glue, _, links, sentences = _meaning_marks(text, tokens, cfg, spans)
        return text, tokens, _avoid_phone_commands(text, tokens, _plan_meaning(tokens, cfg, glue, links, sentences)) or []
    func = _function_marks(tokens)
    number = [n or t or j for n, t, j in zip(_number_marks(tokens), _term_marks(tokens, spans), _joint_marks(tokens))]
    if cfg['portion_mode'] == 'syllables':
        glue = [f or m or g or p for f, m, g, p in zip(func, number, _unit_marks(tokens), _name_marks(tokens, cfg))]
        # the planner's half of the shared predicate: no portion ends on a word that needs its head, and none is a bare number cut
        # from the word it counts (the cue's glue, _counted_marks: «12 | важных показателей» must not buy «важных показателей»)
        # - where the bounds allow another cut
        cuts = _plan_syllables(tokens, glue, cfg, _head_marks(tokens), _counted_marks(tokens))
    else:
        # the fixed-size mode is the legacy one: plain text gives exactly the old 3-word chunks (test_portioner_properties)
        cuts = _plan_words(tokens, func, number, cfg['words_per_portion'])
    return text, tokens, _avoid_phone_commands(text, tokens, cuts) or []


def portions(answer, settings=None, *, spoken=False):
    """The spoken portions of ``answer`` (a list of strings; empty when the answer has no words)."""
    text, tokens, cuts = _plan(answer, resolve(settings), spoken=spoken)
    return _slice(text, tokens, cuts) if cuts else []


def stable_prefix(text, settings=None, *, committed='', eager=False, starving=False):
    """One complete planned portion plus lexical lookahead, NOT fact checking.

    ``eager`` (meaning portions only): the listener waits at the frontier for the next portion - an open sentence that already plans
    two portions lets its first one go rather than leave the listener in silence until the sentence ends. ``starving`` (meaning
    portions only): the listener has waited there as long as an idle segment takes to be flushed while the text still trickles in -
    every complete word that arrived goes.

    The last unfinished word and last planned portion are retained. Existing
    committed characters are immutable; abbreviation expansion requires its
    separate source-to-spoken mapping and therefore waits for full text here.
    None rejects a producer rewrite. The caller must still establish that the
    content belongs to the current question and is sufficiently grounded.
    """
    cfg = resolve(settings)
    text = str(text).lstrip()
    if not text.startswith(committed):
        return None
    if cfg['abbreviations']:
        return committed
    tail = text[len(committed):]
    matches = list(WORDS.finditer(tail))
    if not matches:
        return committed
    # A delta ending in letters/digits may still be the middle of a word; so may a number before a final mark in a meaning plan (the
    # decimal point or comma of «ГОСТ 2.105», «2,5»: the first is never the end of a portion).
    if tail[-1].isalnum() or (cfg['portion_mode'] == 'meaning' and re.search(r'\d[.,]$', tail)):
        tail = tail[:matches[-1].start()]
    if starving and cfg['portion_mode'] == 'meaning':
        return committed + tail[:_open_end(tail, len(tail.rstrip()))]
    text_, tokens, cuts = _plan(tail, cfg)
    spans = _spans(text_, tokens, cuts) if cuts else []
    if cfg['portion_mode'] == 'meaning':
        end = _meaning_stable_end(text_, tokens, cuts, spans, eager, cfg)
        return committed + tail[:_open_end(text_, end)]
    # The syllable planner balances a whole chain of portions, so where its FIRST cut falls depends on where the partial text
    # happens to end (DEF-SEG-17: with one portion behind it the stream left one-word portions the plan of the whole text
    # avoids). With three behind it the stream and the plan of the whole text agree on all 208 answers of the S6 corpus.
    if len(spans) < STREAM_LOOKAHEAD[cfg['portion_mode']]:
        return committed
    # The first portion ends where the TEXT says: its string has its whitespace collapsed, so searching for it in a tail
    # that holds a no-break space, a double space or a line break finds nothing and cuts the word in half.
    return committed + tail[:spans[0][1]]


_HANGING = re.compile(r'(?:\s*(?:[—–]|\s-|(?:^|(?<=\s))[«“„(\[]))+\s*$')


def _open_end(text, end):
    """g27: ``end`` moved back so that what a stream lets go of ``text[:end]`` before the rest has arrived never ends on what needs the
    rest: a dash («Налог на прибыль —», «из статей 13–»: a number before it may be the start of a range), a function word, a copula, a
    correlative before its comma, the mark of a list item. 0 when nothing is left; a closed sentence stays as it is."""
    while end > 0:
        piece = text[:end]
        if re.search(r'[.!?…]["»)]*\s*$', piece) and not re.search(r'\d[.]\s*$', piece):
            return end
        hanging = _HANGING.search(piece)
        if hanging:
            end = hanging.start()
            if re.search(r'\d$', text[:end]) and not text[end:end + 1].isspace():
                end = len(text[:end].rstrip('0123456789,.'))     # «13–»: a range may follow
            end = len(text[:end].rstrip())
            continue
        words = list(WORDS.finditer(piece))
        if not words:
            return 0
        last = words[-1]
        norm, gap = normalize(last.group()), piece[last.end():]
        marked = re.match(r'\)\s*$', gap) and (last.group().isdigit() and len(last.group()) <= 2 or len(last.group()) == 1)
        if (norm in FUNCTION_WORDS or norm in COPULAS or marked or norm in _ITEM_WORDS
                or (norm in _CORRELATIVES and ',' in gap) or (norm == 'же' and len(words) > 1 and normalize(words[-2].group()) in _CORRELATIVES)):
            end = len(text[:last.start()].rstrip())
            continue
        return end
    return 0


def _meaning_stable_end(text, tokens, cuts, spans, eager=False, cfg=None):
    """Where the meaning plan of an arriving ``text`` can no longer change (an offset in it; 0: nowhere yet). A sentence is planned on
    its own, so every portion up to a sentence end that has arrived is final; the first portion of a sentence that is still open is
    final once that sentence already plans STREAM_LOOKAHEAD['meaning'] portions (a long sentence must not hold the listener). ``eager``:
    the listener waits for the next portion - see stable_prefix."""
    if not spans:
        return 0
    sentences = _sentence_marks(text, tokens)
    sentences[-1] = _sentence_closed(tokens[-1])          # the end of the arrived text ends a sentence only when it is closed
    ends = [b - 1 for b in cuts[1:]]                      # the last token of every planned portion
    stable = 0
    for k, last in enumerate(ends):
        if sentences[last]:
            stable = k + 1
    # A long sentence still arriving: its first portion goes once it ends at clause punctuation and the sentence already plans
    # STREAM_LOOKAHEAD['meaning'] portions.
    if len(ends) - stable >= STREAM_LOOKAHEAD['meaning'] and _meaning_break(tokens[ends[stable]]):
        stable += 1
    elif eager and len(ends) - stable >= 2:
        stable += 1                                   # the listener waits for it: the portion is as good as the text allows now
    elif eager and cfg is not None and len(ends) - stable == 1:
        # one open portion of MEANING_EARLY_WORDS words or more that the listener waits for while the text trickles in: it goes up to its
        # cheapest inner cut (never a torn phrase), so that its last words - which the next one may still join - stay behind
        first, last = (cuts[stable], ends[stable])
        gap = tokens[last].gap                            # an abbreviation's period is no clause end (_sentence_closed)
        if (_sentence_closed(tokens[last]) or any(c in gap for c in ',;:—–') or ' - ' in gap) and last - first + 1 >= cfg['min_words']:
            return spans[stable][1]                   # its clause punctuation has arrived: the whole clause is a portion
        if last - first + 1 >= MEANING_EARLY_WORDS:
            glue, _, links, _ = _meaning_marks(text, tokens, cfg, [])
            inner = [(links[i] - CLAUSE_BONUS[_meaning_break(tokens[i])], -i) for i in range(first + cfg['min_words'] - 1, last)
                     if not glue[i] and links[i] < LINK_HEAD]
            if inner:
                cut = -min(inner)[1]
                return len(text[:_begins(text, tokens)[cut + 1]].rstrip())
    return spans[stable - 1][1] if stable else 0


# --- the first cue (L2) ----------------------------------------------------------------------------------------------------
# What the listener must repeat FIRST is decided from the first few words alone, while the text is still arriving:
# 2-4 words (a 5th only when the 4th and 5th belong together: a term, a number with its unit, «не» + word), about 5
# syllables, never torn from the unit it is part of, and available as soon as the word AFTER it is known (no waiting for
# a comma, a full stop, or a second portion). first_useful.first_cue chooses among these places.
CUE_MIN_WORDS = 2
CUE_MAX_WORDS = 4
CUE_TARGET_SYLLABLES = 5
REMAINDER_PENALTY = 20      # a cue that leaves ONE word before the end of its sentence costs this much more
CUE_SYLLABLE_SLACK = 6      # a first cue may be this many syllables over max_syllables: two long words beat one fragment

CUE_MIN_SYLLABLES = 3       # a cue needs enough sound to be worth saying: «Нет, звук» (2 syllables) waits for «Нет, звук распространяется»
CUE_LONG_WORD = 5           # one word alone may be a cue from this many syllables on if a comma or a stronger mark follows it
                            # («Сублимация,»); without a mark the planner's own limit applies (6)
CUE_HEAD_SLACK = 4          # W1F-A: a cue lengthened to take a head along (or to reach punctuation) stays within max_syllables + 4:
                            # 12 in the call's profile, the load an issued portion may have (T-class N14)

# ``dangling``: the cut ends on a word that needs its head (_head_marks) and the cue can hold that head: glue in the cue, a place to end
# only when nothing else fits. ``closure``: a cut after the LAST arrived word, whose following word is not known yet: 'punct' when clause
# or sentence punctuation has already arrived after it, 'head' when it is the head a dangling word waited for. ``brk``: the punctuation
# after the cut (_break). ``heavy``: more syllables than a lengthened cue may have (CUE_HEAD_SLACK).
Cut = collections.namedtuple('Cut', 'end words syllables cost ready fragment dangling closure brk heavy')
_CLAUSE_MARKS = ',;:—–'
_CLOSING = re.compile(r'(?:\s*[,;:—–.!?…)\]»”])*')


def _sentence_closed(token):
    """True when what follows the LAST arrived word already ends the sentence (an abbreviation period does not)."""
    gap = token.gap
    if any(c in gap for c in '!?…'):
        return True
    # a period right after a number, an initial or an abbreviation may be its own («2.105», «А.», «т.»); after a symbol it ends the
    # sentence («0,5 %.», «500 ₽.»)
    return '.' in gap and not (gap.startswith('.') and (token.initial or token.num or len(token.text) == 1
                                                         or token.norm in ABBREVIATIONS))


def _trailing_break(token):
    """``_break`` for the last arrived word, which has no following word to look at."""
    gap = token.gap
    if _sentence_closed(token):
        return 3
    if any(c in gap for c in ';:—–)»”') or ' - ' in gap:
        return 2
    return 1 if ',' in gap else 0


def _plain(token):
    """A whole word after which a cut cannot depend on the word that follows: lower-case letters only (no number, name, initial or
    abbreviation), not a function word, not a word that needs a head itself, not an adjective or participle (it may agree with a noun
    that follows), not the noun of «в течение»."""
    norm = token.norm
    if not (token.text.isalpha() and token.text.islower()):
        return False
    if norm in FUNCTION_WORDS or norm in _DETERMINERS or norm in NEEDS_HEAD or norm in NUMBER_WORDS or norm in SCALE_WORDS:
        return False
    return norm not in LOCUTION_TAILS and not is_label(norm) and not _forms(norm)[0]


def _settled(tokens, cfg):
    """Can no word still to come be glued to the LAST arrived word? Clause punctuation after it (``_punct_closes``), or a plain word."""
    last = tokens[-1]
    return _punct_closes(tokens) or (not last.gap.strip() and _plain(last) and not cfg['abbreviations'])


def _last_word_closure(tokens, held, cfg):
    """May a first cue end after the LAST arrived word, whose following word has not arrived? Only when the word is provably whole and
    no following word can change the verdict (W1F-A, zero delay):

    * ``'head'``: the word before it needed it as its head and the cue can hold it («из-за плотной | атмосферы »): the cue that keeps
      them together stands in for the one that would have ended on the dangling word, at the same moment;
    * ``'punct'``: clause punctuation has already arrived after it (``_punct_closes``): a place the chosen cue may be lengthened to.
    """
    if len(tokens) > 1 and held[-2] and _settled(tokens, cfg):
        return 'head'
    return 'punct' if _punct_closes(tokens) else None


def _held_heads(tokens, glue, heads, keeps, cap, budget, settled):
    """True where a word that needs its head (``heads``) is glue in the first cue: the next place a cue could end after it - past its
    head and anything glued to that - is already known (``settled``: the last arrived word cannot be glued to a word still to come) and
    still fits the cue (``cap`` words, a 5th one when ``keeps`` allows it, at most ``budget`` syllables). Elsewhere the place after the
    word stays an ordinary cut, released exactly as before W1F-A: the head is never waited for («Номинал привилегированной» is not
    lengthened to the 13 syllables of «… акции»; «Сапсан — самый» is not held while «быстрый» may still agree with a noun to come)."""
    n = len(tokens)
    prefix, total = [], 0
    for token in tokens:
        total += token.syl
        prefix.append(total)
    reach, held = list(range(n)), [False] * n          # reach[i]: the token after which the next cut at or after i falls
    for i in range(n - 2, -1, -1):
        if glue[i]:
            reach[i] = reach[i + 1]
        elif heads[i]:
            end = reach[i + 1]
            if ((end < n - 1 or settled) and (end + 1 <= cap or (end + 1 == cap + 1 and keeps[cap - 1]))
                    and prefix[end] <= budget):
                held[i], reach[i] = True, end
    return held


def _punct_closes(tokens):
    """Clause punctuation (, ; : — –) has already arrived after the LAST word, and nothing can still glue that word to the next: it
    is no number (6,5 · 10:15 · 1941–1945 go on), no function word, no copula («это,» still needs its predicate) and no «в течение»."""
    last = tokens[-1]
    if not any(c in last.gap for c in _CLAUSE_MARKS):
        return False
    if last.num or last.roman or last.norm in FUNCTION_WORDS or last.norm in _DETERMINERS:
        return False
    if _copula(tokens, len(tokens) - 1) and not any(c in last.gap for c in ':;'):
        return False
    if (_dash_only(last.gap) or (last.norm in _CORRELATIVES and ',' in last.gap) or last.norm in COPULAS):
        return False                                   # g27: «травматизм —» waits for what it is, «те,» for its clause, «это,» for its predicate
    return not (last.norm in LOCUTION_TAILS and len(tokens) > 1 and tokens[-2].norm in PREPOSITIONS)


def _counted_marks(tokens):
    """True where a number (digits or words) is followed by the plain word it counts: «8 планет», «пять машин». Only the
    first cue uses it: a cue that ends on «В Солнечной системе 8» leaves the listener with half a statement."""
    marks = [False] * len(tokens)
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        # C7-A: a number with its case ending counts too: «988-ым годом», «1856-го года» («988-ым» | «годом» tore the year from its noun)
        if ((a.num or a.norm in NUMBER_WORDS or _SUFFIXED_NUMBER.fullmatch(a.text)) and not _PUNCTUATION.search(a.gap) and '.' not in a.gap
                and b.text.isalpha() and b.text.islower() and b.norm not in FUNCTION_WORDS):
            marks[i] = True
    return marks


def cue_cuts(text, settings, *, final, max_words=CUE_MAX_WORDS):
    """``(text, cuts, complete, closed)``: where the first cue of ``text`` may end.

    ``text`` is what has arrived, without a last word that may still be growing (unless ``final``). ``cuts`` lists, shortest
    first, every place that tears no unit - no function word, number with its unit, name, initials, abbreviation or term
    in two - after 2-4 words (5 when the 4th and 5th are glued), with the word after the cut already known (or the sentence
    closed, or ``final``): ``Cut(end, words, syllables, cost, ready, fragment, dangling, closure, brk, heavy)``, ``end`` an offset in
    ``text``, ``cost`` the planner's own (distance from the target length, bonus for punctuation), ``ready``: shaped well enough to be
    released at once, ``fragment``: a lone short word, spoken only when nothing else exists and the text is over; the W1F-A fields are
    described at ``Cut``.
    ``complete``: every place inside the word budget has been judged, so no further word can add a better short cue.
    ``closed``: the sentence that fills the text is over, so none of ITS words can add one.
    """
    cfg = resolve(settings)
    text = str(text or '')
    terms = _term_spans(text, cfg['abbreviations'])     # seen on the whole arrived text: a term whose last word is still growing
    if not final:
        matches = list(WORDS.finditer(text))
        if matches and (text[-1].isalnum() or text[-1] in "-’'"):
            text = text[:matches[-1].start()]          # the last word may still be growing
    tokens = _tokenize(text)
    n = len(tokens)
    if not n:
        return text, [], False, False
    settled = final or _sentence_closed(tokens[-1]) or _settled(tokens, cfg)
    slack, cap, budget, glue, heads, held, keeps, needed = _cue_marks(tokens, cfg, terms, max_words, settled)
    smallest = min(CUE_MIN_WORDS, cap)
    begins = _begins(text, tokens)
    cuts, syllables_so_far = [], 0
    for i, token in enumerate(tokens):
        syllables_so_far += token.syl
        words = i + 1
        single = all(glue[:i])                              # the cue so far is ONE indivisible unit
        straddle = words == cap + 1 and keeps[cap - 1]      # the 4th and 5th word belong together
        if words > cap and not straddle:
            if single and not cuts:
                pass                                        # one unit longer than a cue: it is the cue, there is no other
            elif words > cap + 1 or cuts:
                break
            else:
                continue
        closure = None
        if i < n - 1:
            if glue[i]:
                continue
        elif not (final or _sentence_closed(token)):
            closure = _last_word_closure(tokens, held, cfg)
            if closure is None:
                continue
        if not (single or straddle) and words > 1 and syllables_so_far > slack:
            continue
        brk = token.brk if i < n - 1 else _trailing_break(token)
        cost = (0 if (single or straddle) else (syllables_so_far - CUE_TARGET_SYLLABLES) ** 2) - BREAK_BONUS[brk]
        long_word = words == 1 and (syllables_so_far >= cfg['long_word_syllables']
                                    or (syllables_so_far >= CUE_LONG_WORD and brk >= 1))
        fragment = words < smallest and not (long_word or (words == 1 and i == n - 1 and final))
        if fragment:
            cost += MIN_WORDS_PENALTY * (smallest - words)
        # One word left alone at the end of the sentence is a portion of its own: take it along when the sentence is known to end.
        lone_tail = i + 1 < n and brk < 3 and (final or _sentence_closed(tokens[i + 1]) if i + 1 == n - 1
                                               else tokens[i + 1].brk == 3)
        if lone_tail:
            cost += REMAINDER_PENALTY
        ready = not lone_tail and (long_word or (words >= smallest and (syllables_so_far >= CUE_MIN_SYLLABLES or single)))
        # a closure ends at the punctuation that arrived, never on an opening quote that already belongs to the next word
        end = token.end + len(_CLOSING.match(token.gap).group()) if closure else len(text[:begins[i + 1]].rstrip())
        cuts.append(Cut(end, words, syllables_so_far, cost, bool(ready), fragment, i < n - 1 and held[i], closure, brk,
                        syllables_so_far > budget))
    closed = _sentence_closed(tokens[-1]) and n <= cap + 1        # the sentence is over: nothing in it can still improve the cue
    return text, cuts, bool(final or n >= needed), closed


def _cue_marks(tokens, cfg, terms, max_words, settled):
    """What ``cue_cuts`` decides by: ``(slack, cap, budget, glue, heads, held, keeps, needed)`` - the syllable slack of a cue, its word
    cap, the budget of a lengthened cue, the hard glue (function words and units), the words that need their head and those of them
    the cue can hold, where a 5th word may join the 4th, and how many words make the cue window complete."""
    n = len(tokens)
    slack = cfg['max_syllables'] + CUE_SYLLABLE_SLACK
    func = _function_marks(tokens)
    number = [a or b or c for a, b, c in zip(_number_marks(tokens), _joint_marks(tokens), _term_marks(tokens, terms))]
    names = _name_marks(tokens, {'max_words': CUE_MAX_WORDS + 1, 'max_syllables': slack})
    counted = _counted_marks(tokens)
    units = [m or g or p or c for m, g, p, c in zip(number, _unit_marks(tokens), names, counted)]
    glue = [f or u for f, u in zip(func, units)]
    # A 5th word is allowed to keep a number with its unit (and the «около» before it), a term, a name, a negation or a word that
    # needs its head together («почти нет атмосферы», «есть магнитная стрелка») - not a preposition with its noun.
    keeps = [u or (f and (t.norm in ('не', 'ни') or (i + 1 < n and (tokens[i + 1].num or tokens[i + 1].norm in NUMBER_WORDS))))
             for i, (f, u, t) in enumerate(zip(func, units, tokens))]
    cap = max(1, min(max_words, cfg['max_words']) if cfg['portion_mode'] == 'syllables' else max_words)
    budget = cfg['max_syllables'] + CUE_HEAD_SLACK
    heads = _head_marks(tokens)
    held = _held_heads(tokens, glue, heads, [k or h for k, h in zip(keeps, heads)], cap, budget, settled)
    keeps = [k or h for k, h in zip(keeps, held)]
    needed = cap + 1 + (1 if n > cap and keeps[cap - 1] else 0)
    return slack, cap, budget, glue, heads, held, keeps, needed


def first_clause(text, settings, *, max_words=CUE_MAX_WORDS):
    """``(clause, needed)``: the first clause of ``text`` through the punctuation attached to its last word (, ; : or the end of the
    sentence), once it has arrived, and the number of words its first-cue window needs (``cue_cuts``: ``complete``). ``(None, 0)``
    while it has not ended. A clause never changes once it has ended: what is decided on it stays decided however the text goes on
    (W1F-A, first_useful.elide_restated_head)."""
    cfg = resolve(settings)
    text = str(text or '')
    matches = list(WORDS.finditer(text))
    if matches and (text[-1].isalnum() or text[-1] in "-’'"):
        text = text[:matches[-1].start()]              # the last word may still be growing
    tokens = _tokenize(text)
    for i, token in enumerate(tokens):
        gap = token.gap
        attached = gap[:1] in tuple(',;:!?…')
        ended = token.brk == 3 if i < len(tokens) - 1 else _sentence_closed(token)
        if (attached or (gap[:1] == '.' and ended)) and not (token.num and gap[:1] in ',:'):
            clause = text[:token.end] + _CLOSING.match(gap).group()
            words = _tokenize(clause)
            return clause, _cue_marks(words, cfg, _term_spans(clause, cfg['abbreviations']), max_words, True)[-1]
    return None, 0


# --- the first meaning portion of a call (F1) ------------------------------------------------------------------------------------------
# ``end``: an offset in the text; ``words``, ``syllables``; ``cost``: the planner's own (_plan_meaning) for that portion, plus what the
# rest of its sentence would cost when that rest is known to be too short to stand alone; ``brk``: the punctuation after it (_break);
# ``sentence``: it ends its sentence (one that has arrived); ``torn``: it tears what must never be torn (a word from its head, a noun
# from its genitive, a pronoun from its verb: LINK_HEAD); ``verb``: it holds a predicate (a verb, a short adjective, «нельзя»), so a dash
# after it is no dash between a subject and its predicate («звук распространяется только в среде —», not «сумма углов —»).
MeaningCut = collections.namedtuple('MeaningCut', 'end words syllables cost brk sentence torn verb')


def portion_size(text):
    """``(words, syllables)`` of ``text`` as the planner counts a portion (``_tokenize``): the measure ``meaning_cuts`` compares with
    ``first_window``, so that a caller lengthening a portion of its own (first_useful.G15) weighs it on the very same scale."""
    tokens = _tokenize(str(text or ''))
    return len(tokens), sum(t.syl for t in tokens)


def first_window(settings, *, number=False):
    """``(words, syllables)``: the window of the first meaning portion - MEANING_FIRST_MAX_WORDS words (or max_words, if smaller) and
    max_syllables; for a question that asks for a number (C7-A) MEANING_NUMBER_FIRST_MAX_WORDS words and MEANING_NUMBER_EXTRA_SYLLABLES
    more, unless the profile asks for portions shorter than a first portion."""
    cfg = resolve(settings)
    if number and cfg['max_words'] >= MEANING_FIRST_MAX_WORDS:
        return MEANING_NUMBER_FIRST_MAX_WORDS, cfg['max_syllables'] + MEANING_NUMBER_EXTRA_SYLLABLES
    return min(MEANING_FIRST_MAX_WORDS, cfg['max_words']), cfg['max_syllables']


def meaning_cuts(text, settings, *, final, number=False):
    """``(text, cuts, complete)``: where the FIRST meaning portion of an arriving ``text`` may end.

    ``text`` is what has arrived, without a last word that may still be growing (unless ``final``). ``cuts`` lists, shortest first,
    every place inside the first sentence and inside the first window (``first_window``; ``number``: the question asks for a number)
    that tears no phrase unit (glue of _meaning_marks) and whose following word or punctuation is known. ``complete``: no further word
    can add a place (the first sentence has ended, or a word past the window has arrived, or the text is final). first_useful.first_cue
    chooses.
    """
    cfg = resolve(settings)
    text = str(text or '')
    if not final:
        matches = list(WORDS.finditer(text))
        if matches and (text[-1].isalnum() or text[-1] in "-’'"):
            text = text[:matches[-1].start()]          # the last word may still be growing
    tokens = _tokenize(text)
    n = len(tokens)
    if not n:
        return text, [], False
    glue, _, links, sentences = _meaning_marks(text, tokens, cfg, _term_spans(text, cfg['abbreviations']))
    closed = final or _sentence_closed(tokens[-1])
    sentences[-1] = closed
    first_end = next((i for i in range(n) if sentences[i]), None)       # the first sentence's last token, once it has arrived
    begins = _begins(text, tokens)
    cap, max_syl = first_window(settings, number=number)
    cuts, words, syl, complete, verb = [], 0, 0, final, False
    for i, token in enumerate(tokens):
        words += 1
        syl += token.syl
        verb = verb or (_wordlike(token) and _tag(token.norm)[0] in ('VERB', 'PRTS', 'ADJS', 'PRED'))
        single = all(glue[:i])                          # the portion so far is ONE indivisible unit
        if (words > cap or syl > max_syl) and not (single and not cuts):
            complete = True
            break
        if i < n - 1:
            if glue[i]:
                continue
            brk, link = _meaning_break(token), (0 if sentences[i] else links[i])
            end = len(text[:begins[i + 1]].rstrip())
        elif closed or (_punct_closes(tokens) and not (',' in token.gap and _negated_clause(tokens, i))):
            brk, link = (3 if closed else _trailing_break(token)), 0
            # a closed sentence takes everything after its last word: the mark and a symbol before it («0,5 %.», «100 °C.»)
            end = len(text.rstrip()) if closed else token.end + len(_CLOSING.match(token.gap).group())
        else:
            break                                       # the word after it decides how it ends: not known yet
        whole = sentences[i]                            # it ends the sentence it starts (the first one)
        if whole and is_phone_phrase(text[:end]):
            # a sentence the phone handles itself («До свидания.», «Стоп, стоп.») is never a portion alone: the plan joins it to the
            # next sentence (_avoid_phone_commands), and so does the first cue - the window runs on to that sentence's end
            first_end = next((k for k in range(i + 1, n) if sentences[k]), None)
            cuts.append(MeaningCut(end, words, syl, MEANING_PORTION_COST, brk, False, False, verb))
            continue
        cost = MEANING_PORTION_COST + _zone_cost(syl, cfg) + _short_cost(words, whole, cfg, verb)
        if not whole:
            cost += link - CLAUSE_BONUS[brk]
            if first_end is not None:                   # the rest of the sentence is known: is it long enough to stand alone?
                cost += _short_cost(first_end - i, False, cfg)
        cuts.append(MeaningCut(end, words, syl, cost, brk, whole, not whole and link >= LINK_HEAD, verb))
        if whole:
            complete = True
            break
    return text, cuts, complete


# --- w2-portion: the length of the portions not yet said follows the listener ------------------------------------------------------
# Three levels, all existing presets: 0 = the call's own 'meaning', 1 = 'semantic_short', 2 = 'pronunciation_short'. The adapter only decides;
# the controller feeds it one record per CONFIRMED portion and, on a decision, calls EchoEngine.adapt_rest (never inside a portion, a cue, a pause).
ADAPT_LEVELS = ('meaning', 'semantic_short', 'pronunciation_short')
ADAPT_WINDOW = 6          # portions remembered
ADAPT_DOWN_OF = 4         # of the last 4 ...
ADAPT_DOWN_BAD = 2        # ... at least 2 needed a tail, a repeat or a stumble: one level shorter
ADAPT_UP_RUN = 5          # 5 in a row confirmed at the first try and in time: one level longer (never above the starting level)
ADAPT_HOLD = 3            # a change at most once per 3 portions
_PORTION_KEYS = ('preset', 'portion_mode', 'words_per_portion', 'target_syllables', 'max_syllables', 'max_words', 'min_words', 'long_word_syllables')


def level_settings(base, level):
    """``base`` (raw settings) with its portion keys replaced by the preset of ``level`` (clamped to the levels)."""
    level = min(max(int(level), 0), len(ADAPT_LEVELS) - 1)
    out = {k: v for k, v in dict(base or {}).items() if k not in _PORTION_KEYS}
    out['preset'] = ADAPT_LEVELS[level]
    assert out['preset'] in PRESETS
    return out


class PortionAdapter:
    """The rule of the level. ``record`` once per confirmed portion; returns None or the change ``{'level','from','reason','n'}`` (also kept in ``trace``)."""

    def __init__(self, level=0, floor=0):
        self.level, self.floor = min(max(int(level), 0), len(ADAPT_LEVELS) - 1), floor     # floor: never longer than the profile's own level
        self.window, self.trace, self.n, self.since = [], [], 0, ADAPT_HOLD

    def record(self, *, first_try, fast, stumbled=False, repeat_asked=False):
        """first_try: confirmed with no tail and no repeat; fast: within the cue plus 1.5 s; stumbled / repeat_asked: the signals of the listener."""
        bad = bool(stumbled or repeat_asked or not first_try)
        self.window = (self.window + [(bad, bool(fast) and not bad)])[-ADAPT_WINDOW:]
        self.n += 1
        self.since += 1
        if self.since < ADAPT_HOLD:
            return None
        last = self.window[-ADAPT_DOWN_OF:]
        if sum(b for b, _ in last) >= ADAPT_DOWN_BAD and self.level < len(ADAPT_LEVELS) - 1:
            return self._move(self.level + 1, f'{sum(b for b, _ in last)} of the last {len(last)} portions needed a tail, a repeat or a stumble')
        run = self.window[-ADAPT_UP_RUN:]
        if len(run) == ADAPT_UP_RUN and all(ok for _, ok in run) and self.level > self.floor:
            return self._move(self.level - 1, f'{ADAPT_UP_RUN} portions in a row confirmed at the first try in time')
        return None

    def _move(self, level, reason):
        change = {'level': level, 'from': self.level, 'reason': reason, 'n': self.n}
        self.level, self.since, self.window = level, 0, []
        self.trace.append(change)
        return change


adapt_to_listener = PortionAdapter      # T08 (w2-t-check): the adaptation of the portion's length to the listener's signals; ``portion_adapt`` = "off" by default, the controller does not feed it yet (w3-integ.md)
