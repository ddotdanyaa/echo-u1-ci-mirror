"""Russian number words and digits as ONE canonical value, for the acknowledgement matcher.

Pure and dependency-free (no morphology, no I/O): ``ru_alignment`` turns razdel tokens and pymorphy3 lemmas into
``Item`` tuples and asks ``read_number`` what number, if any, starts at a position. The same spoken number and the
same digits must give the same atom, for every magnitude («1945» = «тысяча девятьсот сорок пятый» in a year,
«2500» = «две тысячи пятьсот», «3,5» = «три целых пять десятых» = «три и пять десятых» = «три с половиной»), while two different numbers
never become one: a run that is not a valid Russian number is reported as a failure and is never summed up
(«пять шесть» is not 11).

Atoms: ``#N`` a cardinal or decimal number, ``#ord:N`` an ordinal. A cardinal never equals an ordinal («один» is not
«первый»), except where the digits themselves stand for an ordinal: a year, a century, a grade, a day of a month.
"""
from __future__ import annotations

import re
from collections import namedtuple
from decimal import Decimal

# kind: 'digits' (value Decimal), 'card' (int), 'ord' (int), 'scale' (int 10**k), 'half' (Decimal 1.5, «полтора»),
#       'frac' (int exponent: «десятых» 1, «сотых» 2, «тысячных» 3), 'roman' ((value, fallback lemma)), 'word' (lemma).
Item = namedtuple('Item', 'kind value surface')
Read = namedtuple('Read', 'atom end')
Fail = namedtuple('Fail', 'end')

SCALES = {'тысяча': 10 ** 3, 'миллион': 10 ** 6, 'миллиард': 10 ** 9, 'триллион': 10 ** 12}
# A scale word on its own is a number only in these (singular) forms: «тысяча человек», «около миллиона».
# «тысячи людей» / «миллионов» without a count stay words.
SINGULAR_SCALES = frozenset({'тысяча', 'тысячу', 'миллион', 'миллиона', 'миллиард', 'миллиарда', 'триллион', 'триллиона'})
SCALE_ABBREVIATIONS = {'тыс': 10 ** 3, 'млн': 10 ** 6, 'млрд': 10 ** 9, 'трлн': 10 ** 12}
FRACTIONS = {'десятых': 1, 'десятая': 1, 'десятые': 1, 'сотых': 2, 'сотая': 2, 'сотые': 2,
             'тысячных': 3, 'тысячная': 3, 'тысячные': 3}
WHOLE_WORDS = frozenset({'целых', 'целая', 'целое', 'целый', 'целой'})
AND_WORD = 'и'      # «три и пять десятых»: the whole part and its fraction, joined by «и» instead of «целых»
HALF_WORDS = frozenset({'половиной', 'половину', 'половина', 'половины'})
COMMA_WORDS = frozenset({'запятая'})

YEAR_WORDS = frozenset({'год', 'году', 'годом', 'годе'})      # «в 1945 году», «2026 год»; «года» only from 1000 («с 1945 года»)
# C7-B, G3 (live, W3 w3_02: «Обычно называют девятьсот восемьдесят восемь год» for «… 988 год —», five wasted repeats): a cloud ASR writes a year it
# heard as a cardinal («в одна тысяча восемьсот восемьдесят девять году» for «в 1889 году»). Any spelling of a number of 100 or more right before a
# form of «год» gets the atom the digits get there (``_ordinal_context``): one number, one atom. Below 100 it stays a count («двадцать один год»).
SPOKEN_YEAR_WORDS = YEAR_WORDS | {'года'}
CENTURY_WORDS = frozenset({'век', 'века', 'веке', 'веку', 'веком'})
CENTURY_PLURAL = frozenset({'веках', 'веков'})      # «в XIII–XV веках»: the END of a range only (``range_end_ordinal``); read_number does not use it
YEAR_PLURAL = frozenset({'годах', 'годов'})         # «в 1941–1945 годах»
CENTURY_FORMS = CENTURY_WORDS | CENTURY_PLURAL
GRADE_WORDS = frozenset({'класс', 'класса', 'классе', 'классу', 'классом'})
MONTH_WORDS = frozenset({'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября',
                         'ноября', 'декабря'})

_SPOKEN = ('card', 'ord', 'scale', 'half')
_ROMAN = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000}


def decimal_text(value):
    """The digits of a number as written: ``3.50`` stays ``3.50``, ``1E+3`` becomes ``1000`` (never an exponent)."""
    value = Decimal(value)
    return format(value, 'f') if value.as_tuple().exponent < 0 else str(int(value))


def roman_value(text):
    """The value of a well-formed Roman numeral, else ``None`` (only used for centuries: «XXI век»)."""
    text = text.lower()
    if not text or any(ch not in _ROMAN for ch in text):
        return None
    total = 0
    for i, ch in enumerate(text):
        v = _ROMAN[ch]
        total += -v if i + 1 < len(text) and _ROMAN[text[i + 1]] > v else v
    spelled = ''
    rest = total
    for value, symbol in ((1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'), (100, 'c'), (90, 'xc'), (50, 'l'), (40, 'xl'),
                          (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i')):
        while rest >= value:
            spelled += symbol
            rest -= value
    return total if spelled == text else None


# -- spoken integers -----------------------------------------------------------------------------------------------------

def _group(tokens, pos):
    """0..999 (hundreds, tens, units) at ``pos``: ``(value, new_pos, ends_in_ordinal)`` or ``None``."""
    n, start, value = len(tokens), pos, 0

    def number(k):
        return tokens[k] if k < n and tokens[k].kind in ('card', 'ord') else None

    t = number(pos)
    if t and 100 <= t.value <= 900 and t.value % 100 == 0:
        value += t.value
        pos += 1
        if t.kind == 'ord':
            return value, pos, True
    t = number(pos)
    if t and 20 <= t.value <= 90 and t.value % 10 == 0:
        value += t.value
        pos += 1
        if t.kind == 'ord':
            return value, pos, True
        u = number(pos)
        if u and 1 <= u.value <= 9:
            return value + u.value, pos + 1, u.kind == 'ord'
    elif t and 0 <= t.value < 20:
        if t.value == 0 and pos != start:
            return None                               # «сто ноль»
        value += t.value
        pos += 1
        return value, pos, t.kind == 'ord'
    if pos == start:
        return None
    return value, pos, False


def parse_integer(tokens):
    """A spoken integer from ``card`` / ``ord`` / ``scale`` items: ``(value, is_ordinal)`` or ``None``.

    Groups of up to three digits, each optionally followed by a scale word, scales strictly descending, only the very
    last word may be an ordinal («тысяча девятьсот сорок пятый»).
    """
    n, pos, total, last_scale = len(tokens), 0, 0, None
    while pos < n:
        t = tokens[pos]
        if t.kind == 'ord' and t.value >= 1000:          # «тысячный», «двухтысячный»: one word, nothing before or after
            return (t.value, True) if pos == n - 1 and total == 0 else None
        if t.kind == 'scale':                            # «тысяча девятьсот», «миллион»: an implicit one
            group, scale, pos = 1, t.value, pos + 1
        else:
            parsed = _group(tokens, pos)
            if parsed is None:
                return None
            group, pos, ordinal = parsed
            if pos < n and tokens[pos].kind == 'scale' and not ordinal:
                scale, pos = tokens[pos].value, pos + 1
            else:
                return (total + group, ordinal) if pos == n else None
        if last_scale is not None and scale >= last_scale:
            return None
        last_scale = scale
        total += group * scale
    return total, False


def _spoken(run):
    """The value of a maximal run of spoken number words: ``(Decimal, is_ordinal)`` or ``None``."""
    if any(t.kind == 'half' for t in run):               # «полтора», «полторы тысячи»
        if run[0].kind != 'half' or len(run) > 2 or (len(run) == 2 and run[1].kind != 'scale'):
            return None
        return run[0].value * (run[1].value if len(run) == 2 else 1), False
    parsed = parse_integer(run)
    return (Decimal(parsed[0]), parsed[1]) if parsed else None


def _is_integral(value):
    return value == value.to_integral_value()


def _cardinal_run(items, k):
    """A spoken cardinal or one integral digit token at ``k``: ``(int, end)`` or ``None``."""
    n = len(items)
    if k < n and items[k].kind == 'digits':
        return (int(items[k].value), k + 1) if _is_integral(items[k].value) else None
    end = k
    while end < n and items[end].kind in ('card', 'scale'):
        end += 1
    parsed = parse_integer(items[k:end]) if end > k else None
    return (parsed[0], end) if parsed and not parsed[1] else None


def _continuation(items, j, value):
    """What may follow an integral cardinal: «с половиной», «целых … десятых», «запятая …», «пять десятых»."""
    n = len(items)
    if j >= n:
        return None
    word = items[j]
    if word.kind == 'word' and word.surface == 'с' and j + 1 < n and items[j + 1].surface in HALF_WORDS:
        value, j = Decimal(f'{int(value)}.5'), j + 2
        if j < n and items[j].kind == 'scale':
            value, j = value * items[j].value, j + 1
        return value, j
    if word.kind == 'word' and (word.surface in WHOLE_WORDS or word.surface == AND_WORD):
        # «три целых пять десятых» and the way it is said, «три и пять десятых» (Task E2, ruling 5): both are 3.5. The «и» is a decimal only
        # when a fraction word closes the run («тридцать шесть и шесть десятых»); «пять и шесть» alone is two numbers and stays two.
        tail = _cardinal_run(items, j + 1)
        if tail and tail[1] < n and items[tail[1]].kind == 'frac':
            exponent = items[tail[1]].value
            if 0 <= tail[0] < 10 ** exponent:
                return Decimal(f'{int(value)}.{str(tail[0]).zfill(exponent)}'), tail[1] + 1
        return None
    if word.kind == 'word' and word.surface in COMMA_WORDS:
        k, zeros = j + 1, 0
        while k < n and items[k].kind == 'card' and items[k].value == 0:
            zeros, k = zeros + 1, k + 1
        tail = _cardinal_run(items, k)
        digits = '0' * zeros + (str(tail[0]) if tail else '')
        if not digits:
            return None
        return Decimal(f'{int(value)}.{digits}'), (tail[1] if tail else k)
    if word.kind == 'frac':
        if 0 <= value < 10 ** word.value:
            return Decimal(f'0.{str(int(value)).zfill(word.value)}'), j + 1
    return None


def _ordinal_context(value, nxt):
    """Digits that stand for an ordinal because of the word after them: «в 1945 году», «21 веке», «10 классе», «22 июня»."""
    if nxt is None or nxt.kind != 'word':
        return False
    s = nxt.surface
    if s in YEAR_WORDS:
        return value >= 100
    if s == 'года':
        return value >= 1000
    if s in CENTURY_WORDS:
        return 1 <= value <= 40
    if s in GRADE_WORDS:
        return 1 <= value <= 12
    if s in MONTH_WORDS:
        return 1 <= value <= 31
    return False


def range_end_ordinal(value, word):
    """True when ``value`` before the plural ``word`` is the end of a range of ordinals: «15 веках» (a century 1..40), «1945 годах» (from 100)."""
    if word in CENTURY_PLURAL:
        return 1 <= value <= 40
    if word in YEAR_PLURAL:
        return value >= 100
    return False


def read_number(items, i):
    """Read the number that starts at ``items[i]``.

    ``Read(atom, end)`` for a number, ``Fail(end)`` when ``items[i:end]`` is a run of number words that is not a valid
    number (the caller keeps the words as protected tokens), ``None`` when no number starts here.
    """
    n = len(items)
    it = items[i]
    ordinal = scaled = False
    if it.kind == 'digits':
        value, j = it.value, i + 1
        if j < n and items[j].kind == 'scale':
            value, j, scaled = value * items[j].value, j + 1, True
    elif it.kind == 'roman':
        number = it.value[0]
        if i + 1 < n and items[i + 1].kind == 'word' and items[i + 1].surface in CENTURY_WORDS and 1 <= number <= 39:
            return Read(f'#ord:{number}', i + 1)
        return None
    elif it.kind in _SPOKEN:
        j = i
        while j < n and items[j].kind in _SPOKEN:
            j += 1
        parsed = _spoken(items[i:j])
        if parsed is None:
            return Fail(j)
        value, ordinal = parsed
    else:
        return None
    changed = False
    if not ordinal and not scaled and _is_integral(value):
        more = _continuation(items, j, value)
        if more:
            value, j = more
            changed = True
    if it.kind == 'digits' and not scaled and not changed and _is_integral(value)             and _ordinal_context(int(value), items[j] if j < n else None):
        ordinal = True
    if (it.kind in ('card', 'scale', 'ord') and not changed and _is_integral(value) and value >= 100 and j < n
            and items[j].kind == 'word' and items[j].surface in SPOKEN_YEAR_WORDS):
        ordinal = _ordinal_context(int(value), items[j])          # «в тысяча восемьсот восемьдесят девять году»: the year 1889
    if ordinal:
        return Read(f'#ord:{int(value)}', j)
    if it.kind == 'digits' and not scaled and not changed:
        return Read('#' + it.surface.replace(',', '.'), j)      # as written: «25.10» is not «25.1»
    if _is_integral(value):
        return Read(f'#{int(value)}', j)                          # «1,5 миллиона» is 1500000, not 1500000.0
    return Read('#' + decimal_text(value), j)


# -- digit groups ("1 500", "300 000") ------------------------------------------------------------------------------------

_SPACES = '      	'      # F1: a tab between digit groups too («300<tab>000»: an ASR surface the ACK properties generate)
_GROUPED = re.compile(r'(?<![\w.,])(\d{1,3}(?:[' + _SPACES + r']\d{3})+)(?!\d)')
_STRIP_SPACES = re.compile('[' + _SPACES + ']')


def merge_digit_groups(text):
    """``1 500`` / ``1 500`` / ``300 000`` -> ``1500`` / ``300000``: one number written with a thousands separator."""
    return _GROUPED.sub(lambda match: _STRIP_SPACES.sub('', match.group(1)), text)


# -- numbers said as words that the matcher reads as separate words: «четыре два два», «four two two», «two hundred twenty two» ----------
# U43: ``digits_for_words`` writes them as the digits they are, before ``ru_alignment`` reads the text; what is no ONE number (a list with its
# pauses, counting «один два три», «два раза», «пять шесть») is left as it was.

_WORD = re.compile(r'[^\W\d_]+')
_RU_DIGITS = {'ноль': 0, 'один': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9}
_EN_DIGITS = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9}
_RU_BIG = frozenset('десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот тысяча тысячи тысяч миллион миллиона миллионов'.split())
_EN_TEENS = dict(zip('ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(), range(10, 20)))
_EN_TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))
_EN_SCALES = {'thousand': 10 ** 3, 'million': 10 ** 6, 'billion': 10 ** 9}
_EN_WORDS = frozenset(_EN_DIGITS) | frozenset(_EN_TEENS) | frozenset(_EN_TENS) | frozenset(_EN_SCALES) | {'hundred'}


def _one_by_one(values):
    """«4 2 2» -> ``'422'`` when three or more digits said one by one are a number: not when they count («1 2 3», «3 2 1»)."""
    steps = {b - a for a, b in zip(values, values[1:])}
    return ''.join(map(str, values)) if len(values) >= 3 and steps not in ({1}, {-1}) else None


def _english_integer(words):
    """A spoken English integer («two hundred twenty two», «one thousand five hundred»), else ``None``."""
    total = cur = 0
    last_scale = None
    for word in words:
        low = cur % 100
        if word == 'and':
            continue
        if word == 'hundred':
            if not 0 < cur < 10:
                return None
            cur *= 100
        elif word in _EN_SCALES:
            if not cur or (last_scale is not None and _EN_SCALES[word] >= last_scale):
                return None
            total, cur, last_scale = total + cur * _EN_SCALES[word], 0, _EN_SCALES[word]
        elif word in _EN_DIGITS and word != 'zero':
            if low and not (low >= 20 and low % 10 == 0):
                return None
            cur += _EN_DIGITS[word]
        elif word in _EN_TEENS or word in _EN_TENS:
            if low:
                return None
            cur += _EN_TEENS.get(word) or _EN_TENS[word]
        else:
            return None
    return total + cur


def digits_for_words(text):
    """``text`` with each run of digit words said one by one («четыре два два», «four two two») and each English number said in words («two hundred twenty two», «two hundred») written as digits. Runs only of words
    separated by blanks (a comma ends a run); a bare «one» or «two» is no number («two times»); a run next to a bigger number word («сто сорок четыре ноль ноль ноль») is that number's, not its own."""
    words = [(m.group().lower(), m.start(), m.end()) for m in _WORD.finditer(text)]
    edits, k = [], 0
    while k < len(words):
        start = k
        while k + 1 < len(words) and not text[words[k][2]:words[k + 1][1]].strip():
            k += 1
        group, k = words[start:k + 1], k + 1
        j = 0
        while j < len(group):
            ru, en = group[j][0] in _RU_DIGITS, group[j][0] in _EN_WORDS
            end = j + 1
            while end < len(group) and ((ru and group[end][0] in _RU_DIGITS) or (en and (group[end][0] in _EN_WORDS or (group[end][0] == 'and' and group[end - 1][0] in ('hundred', 'thousand') and end + 1 < len(group) and group[end + 1][0] in _EN_WORDS)))):
                end += 1
            run, value = [w for w, _, _ in group[j:end]], None
            if ru and not (j and group[j - 1][0] in _RU_BIG) and not (end < len(group) and group[end][0] in _RU_BIG):
                value = _one_by_one([_RU_DIGITS[w] for w in run])
            elif en:
                parsed = _english_integer(run)
                if parsed is not None and (len(run) > 1 or parsed >= 10):
                    value = str(parsed)
                elif all(w in _EN_DIGITS for w in run):
                    value = _one_by_one([_EN_DIGITS[w] for w in run])
            if value is not None:
                edits.append((group[j][1], group[end - 1][2], value))
            j = end
    for begin, stop, value in reversed(edits):
        text = text[:begin] + value + text[stop:]
    return text
