"""Q1 / B8: a plain sum, difference, product, quotient or percent, answered by code: exact, no model, no network, a few microseconds.

``answer(text)`` recognises an utterance that is nothing but one expression of two numbers - «пять на пять», «сколько будет семь умножить на восемь», «10% от 200 000», «двести разделить на четыре»,
«двадцать плюс двадцать два» - and returns the result as one spoken sentence («Двадцать пять.»), in the shape of a hit of the reference base (``reference_kb.lookup``), so that the controller takes it the
way it takes that: at the cloud's final, and on the ear's text before the final (H4, ``ControlledMedia._ear_first``) with no route of its own, except that a figure from the ear waits for the cloud's open turn to
give the same figure (``ControlledMedia._ear_sum``). Anything else returns ``None`` and the model answers.

The test is a whitelist, as the reference base's: after the two numbers and the operator between them only filler and question words may be left («ну», «сколько будет», «это сколько»). One word that is not on
the list (a unit, a thing, «не», «нет», «почему», «в квадрате», «счёт», «с ... ноября»), one number more or less than two, a run of number words that is no number (a phone number), a number that stands for a
year, a result that is not whole or short («100 : 3»), a division by nothing, a number too big to say: it is not arithmetic. So is one mark the reader cannot see through: a sign glued to a number, a root, a
power, a currency, a thousands separator that reads as a point, a comma between two number words («двадцать, пять на два» is not 25). The bare «на» («пять на пять», and the sign 5×5, the way a recognizer writes a
size) is a product only between whole numbers below a thousand: over that it is more likely a size or a date than a sum, and the verb has to be said. Asked for in words («сколько будет», «посчитай») that is all
it needs. Said alone it needs more: nothing around it but «а», «ну», «и», «пожалуйста» («пять на шесть, да?», «значит пять на шесть» are remarks), no 0 or 1 («один на один»), a number of one digit in it, the
multiplication table («пятьдесят на пятьдесят», «сто на сто»: a figure of speech; «шестьдесят на девяносто», «двадцать один на тридцать», «пятьдесят один на шестьдесят»: accounts, a size), not «двадцать четыре на
семь». In any doubt the answer is ``None``: a missed hit costs the seconds of the model, a wrong one a wrong cue.

Numbers are read with ``ru_numbers`` (the reader of the acknowledgement matcher and of the reference base): words and digits, «200 тысяч», «2,5», «две целых пять десятых»; the case forms the operands are said in
(accusative after «на», genitive after «от») come from the tables below. Nothing here is imported but the standard library and ``ru_numbers``; ``answer`` never raises.
"""
from __future__ import annotations

import re
from decimal import Decimal
from fractions import Fraction
from typing import Optional

from . import ru_numbers as numbers

_MAX_CHARS = 210
_MAX_TOKENS = 40          # h30: a sum read from a sheet is long: «одна тысяча семьсот пятьдесят восемь целых девять сотых разделить на…»
_MAX_AROUND = 14             # the words that are no number: long numbers may be long, what stands around them not
_OPERAND = 10 ** 12          # each operand is below it
_RESULT = 10 ** 15           # so is the result: the words for it come from the scales below
_DECIMALS = 3                # a result with more digits behind the point is not said
_BARE_LIMIT = 1000           # the bare «на» multiplies whole numbers below it only

# -- the words the operands are said in ----------------------------------------------------------------------------------------

_LEX = {}
for _value, _forms in (
        (0, 'ноль нуль нуля'), (1, 'один одна одну одно одного одной'), (2, 'два две двух'), (3, 'три трех'), (4, 'четыре четырех'), (5, 'пять пяти'), (6, 'шесть шести'), (7, 'семь семи'),
        (8, 'восемь восьми'), (9, 'девять девяти'), (10, 'десять десяти'), (11, 'одиннадцать одиннадцати'), (12, 'двенадцать двенадцати'), (13, 'тринадцать тринадцати'),
        (14, 'четырнадцать четырнадцати'), (15, 'пятнадцать пятнадцати'), (16, 'шестнадцать шестнадцати'), (17, 'семнадцать семнадцати'), (18, 'восемнадцать восемнадцати'),
        (19, 'девятнадцать девятнадцати'), (20, 'двадцать двадцати'), (30, 'тридцать тридцати'), (40, 'сорок сорока'), (50, 'пятьдесят пятидесяти'), (60, 'шестьдесят шестидесяти'),
        (70, 'семьдесят семидесяти'), (80, 'восемьдесят восьмидесяти'), (90, 'девяносто девяноста'), (100, 'сто ста'), (200, 'двести двухсот'), (300, 'триста трехсот'),
        (400, 'четыреста четырехсот'), (500, 'пятьсот пятисот'), (600, 'шестьсот шестисот'), (700, 'семьсот семисот'), (800, 'восемьсот восьмисот'), (900, 'девятьсот девятисот')):
    for _form in _forms.split():
        _LEX[_form] = _value
# After a number: every form of a scale word. Alone (right after «от», at the start): the singular ones only - «от тысячи», «миллион разделить на четыре».
_SCALES_AFTER = {'тысяча': 10 ** 3, 'тысячу': 10 ** 3, 'тысячи': 10 ** 3, 'тысяч': 10 ** 3, 'тыс': 10 ** 3, 'миллион': 10 ** 6, 'миллиона': 10 ** 6, 'миллионов': 10 ** 6, 'млн': 10 ** 6,
                 'миллиард': 10 ** 9, 'миллиарда': 10 ** 9, 'миллиардов': 10 ** 9, 'млрд': 10 ** 9, 'триллион': 10 ** 12, 'триллиона': 10 ** 12, 'триллионов': 10 ** 12, 'трлн': 10 ** 12}
_SCALES_ALONE = frozenset('тысяча тысячу тысячи миллион миллиона миллиард миллиарда триллион триллиона'.split())
_SCALES_GENITIVE = frozenset('тысячи миллиона миллиарда триллиона'.split())       # one thousand only right after «от»: «тысячи плюс сто» says no count, «тысячи пять» is the inverted order of about-so-many, near 5000
_DIGITS = re.compile(r'(?:0|[1-9]\d*)(?:[.,]\d{1,%d})?' % _DECIMALS)
_NUMBER_WORDS = frozenset(_LEX) | frozenset(_SCALES_AFTER)

# -- the words around them ----------------------------------------------------------------------------------------------------

_ASKING = 'сколько будет получится получается'
_FILLER = 'ну так а и да вот хорошо ладно итак значит окей ага угу эм э мм ммм хм ой слушай слушайте скажи скажите подскажи подскажите давай давайте пожалуйста теперь дальше еще кстати тогда же ли'
_LEAD = frozenset((_FILLER + ' посчитай посчитайте подсчитай вычисли составляет составит ' + _ASKING).split())
_TAIL = frozenset(('ну так да вот хорошо ладно пожалуйста же ли это равно равняется ' + _ASKING + ' сколько').split())
_ASKED = frozenset('сколько посчитай посчитайте подсчитай вычисли равно равняется скажи скажите подскажи подскажите'.split())     # a bare «на» with one of these is a sum asked for
_BARE_AROUND = frozenset('а ну и пожалуйста'.split())       # all that may stand around a bare «на» that nobody asked to work out
_BARE_PHRASES = frozenset({(24, 7), (7, 24)})               # «двадцать четыре на семь»: round the clock
_MULTIPLY = frozenset('умножить помножить'.split())
_DIVIDE = frozenset('разделить поделить делить'.split())
_PERCENT = frozenset('процент процента процентов'.split())
_INFIX = {('плюс',): '+', ('минус',): '-', ('умножить', 'на'): '*', ('помножить', 'на'): '*', ('разделить', 'на'): '/', ('поделить', 'на'): '/', ('делить', 'на'): '/',
          ('процент', 'от'): '%', ('процента', 'от'): '%', ('процентов', 'от'): '%', ('на',): 'на'}

_HINT = re.compile(r'\bна\b|плюс|минус|умнож|помнож|раздел|подел|делить|процент|%|\+|×|\*|÷|\d\s*[xх]\s*\d')
# The cross is the bare «на» as a recognizer writes it, a size as often as a product (1920x1080).
_SIGNS = ((re.compile(r'(?<=\d)\s*%'), ' процентов '), (re.compile(r'(?<=\d)\s*\+\s*(?=\d)'), ' плюс '), (re.compile(r'(?<=\d)\s*[×*xх]\s*(?=\d)'), ' на '),
          (re.compile(r'(?<=\d)\s*÷\s*(?=\d)'), ' разделить на '))
_TOKEN = re.compile(r'\d+(?:[.,]\d+)?|[a-zа-я]+')
# What ``_TOKEN`` would drop and the figure depends on: a mark that is on no list (√, ², ½, №, €, °, $, ‰), a sign glued to a number, a separator that may be a point («10,000», «12.30»).
_UNREADABLE = re.compile(r'[^a-zа-я0-9\s,.?!;:…«»"\'=+×*÷%—–−-]|[-−–—]\s*\d|(?<!\w)[-−–—](?=\w)|(?<![\d.,])(?:[1-9]\d*,\d{3}|\d+\.\d{2,3})(?!\d)')
_SIGN_LEFT = re.compile(r'[+×*÷%]')
_MARK_BETWEEN = re.compile(r'([а-я]+)\s*[-,.;:!?…—–]+\s*(?=([а-я]+))')      # two words with a pause or a dash written between them: two number words are two numbers then, never one


def _items(tokens):
    items = []
    for token in tokens:
        previous = items[-1].kind if items else None
        if _DIGITS.fullmatch(token):
            items.append(numbers.Item('digits', Decimal(token.replace(',', '.')), token))
        elif token in _LEX:
            items.append(numbers.Item('card', _LEX[token], token))
        elif token in _SCALES_AFTER and (previous in ('card', 'digits') or token in _SCALES_ALONE):
            items.append(numbers.Item('scale', _SCALES_AFTER[token], token))
        elif token in numbers.FRACTIONS:
            items.append(numbers.Item('frac', numbers.FRACTIONS[token], token))
        else:
            items.append(numbers.Item('word', token, token))
    return items


def _half_of_a_scale(words):
    """«пять тысяч с половиной» is 5500; ``ru_numbers`` adds a half of one to it. «пять с половиной тысяч» it reads right."""
    return 'с' in words and words[words.index('с') - 1] in _SCALES_AFTER


def _bare_is_a_sum(a, b, around):
    """Is «a на b», said with these words ``around`` it, a product? Asked for in words it is. Said alone it may be a size, a figure of speech, a remark: see the head of the module."""
    if any(word in _ASKED for word in around):
        return True
    return all(word in _BARE_AROUND for word in around) and 2 <= min(a, b) < 10 and (a, b) not in _BARE_PHRASES


def _mentions(tokens):
    """``[(start, end, Decimal)]`` of the numbers in ``tokens``; ``None`` when a run of number words is no number, or a number stands for a year, a date, an ordinal."""
    items, found, i = _items(tokens), [], 0
    while i < len(items):
        read = numbers.read_number(items, i)
        if isinstance(read, numbers.Read):
            if read.atom.startswith('#ord:') or (tokens[i] in _SCALES_GENITIVE and (read.end > i + 1 or tokens[i - 1:i] != ['от'])) or _half_of_a_scale(tokens[i:read.end]):
                return None
            found.append((i, read.end, Decimal(read.atom[1:])))
            i = read.end
        elif isinstance(read, numbers.Fail):
            return None
        else:
            i += 1
    return found


def _expression(tokens):
    """``(operator, a, b)`` when the utterance is one expression of two numbers and filler, else ``None``."""
    found = _mentions(tokens)
    if not found or len(found) != 2:
        return None
    (start, end, a), (start2, end2, b) = found
    before, between, after = tokens[:start], tuple(tokens[end:start2]), tokens[end2:]
    operator = _INFIX.get(between)
    if operator is None:
        return None
    if operator == 'на':                       # «пять на пять»: a product; «разделить двести на четыре»: the verb stands in front of the first number
        verb = before[-1] if before else None
        if verb in _MULTIPLY or verb in _DIVIDE:
            operator, before = '*' if verb in _MULTIPLY else '/', before[:-1]
        elif not all(0 <= x < _BARE_LIMIT and x == x.to_integral_value() for x in (a, b)) or not _bare_is_a_sum(a, b, before + after):
            return None
        else:
            operator = '*'
    if not all(word in _LEAD for word in before) or not all(word in _TAIL for word in after):
        return None
    if not all(0 <= x < _OPERAND and -x.as_tuple().exponent <= _DECIMALS for x in (a, b)):
        return None
    return operator, a, b


_FRACTION_WORDS = {'десятых': 10, 'десятая': 10, 'десятую': 10, 'сотых': 100, 'сотая': 100, 'сотую': 100}


def _one_number(words):
    """The value of ``words`` when all of them are one whole number, else ``None``."""
    if not words:
        return None
    items = _items(list(words))
    read = numbers.read_number(items, 0)
    if isinstance(read, numbers.Read) and read.end == len(words) and not read.atom.startswith('#ord:'):
        return Decimal(read.atom[1:])
    return None


def _said_point(tokens):
    """h30, the call of 07.11: read from a sheet «целых» falls out («тысяча семьсот пятьдесят восемь девять сотых»). h31 (F17): «целых» goes back in only when the words allow ONE reading:
    the run of number words in front of the fraction word can be split into a whole and a numerator below the denominator at one place only, and it is no complete number by itself
    («сто двадцать пять сотых» is 1,25 or 100,25; «тысяча семьсот пятьдесят девять сотых» is 17,59 or 1700,59). More than one reading: ``None``, the model answers. After «целых» there is nothing to guess."""
    out = list(tokens)
    for at in range(len(out) - 1, 0, -1):
        limit = _FRACTION_WORDS.get(out[at])
        if limit is None:
            continue
        start = at
        while start > 0 and out[start - 1] in _NUMBER_WORDS:
            start -= 1
        run = out[start:at]
        if len(run) < 2 or (start > 0 and out[start - 1] == 'целых'):
            continue
        readings = [k for k in range(1, len(run)) if _one_number(run[:k]) is not None and 0 < (_one_number(run[k:]) or 0) < limit]
        whole = _one_number(run) is not None
        if len(readings) + whole > 1:
            return None
        if readings:
            out.insert(start + readings[0], 'целых')
    return out


def _chain(tokens):
    """h30: three numbers, the share of a table: «A разделить на B и умножить на сто»: ``(a, op, b, op, c)``, the same whitelist around them as one expression."""
    found = _mentions(tokens)
    if not found or len(found) != 3:
        return None
    (start, end, a), (start2, end2, b), (start3, end3, c) = found
    first = _INFIX.get(tuple(tokens[end:start2]))
    second = tuple(tokens[end2:start3])
    second = _INFIX.get(second[1:] if second[:1] == ('и',) else second)
    if first not in ('*', '/') or second not in ('*', '/'):       # left to right holds for these alone; a sum and a product is a question of order, the model's
        return None
    if not all(word in _LEAD for word in tokens[:start]) or not all(word in _TAIL for word in tokens[end3:]):
        return None
    if not all(0 <= x < _OPERAND and -x.as_tuple().exponent <= _DECIMALS for x in (a, b, c)):
        return None
    return a, first, b, second, c


def _exact(operator, a, b):
    if operator == '+':
        return a + b
    if operator == '-':
        return a - b
    if operator == '*':
        return a * b
    return a / b if b else None


def _rounded(value):
    """h30: a share of a table is said to two places, as it is written down. Only what has a fraction in it or gives a percent comes here: «100 : 3» stays unsaid."""
    if value is None or abs(value) >= _RESULT or (value and abs(value) < Fraction(1, 10)):       # h31: below 0,1 two places leave one digit or none: the model answers, never a confident «Ноль.»
        return None
    scaled = int(value * 100 + Fraction(1, 2))
    return Decimal(scaled).scaleb(-2) if scaled % 100 else scaled // 100


def _fits(value):
    """The value as it is when it is exact and short (up to ``_DECIMALS`` places), else ``None``."""
    if value is None or abs(value) >= _RESULT:
        return None
    for digits in range(_DECIMALS + 1):        # exact and short, or not said
        scaled = value * 10 ** digits
        if scaled.denominator == 1:
            return Decimal(int(scaled)).scaleb(-digits) if digits else int(scaled)
    return None


def _chain_result(a, first, b, second, c):
    value = _exact(first, Fraction(a), Fraction(b))
    value = _exact(second, value, Fraction(c)) if value is not None else None
    fit = _fits(value)
    return fit if fit is not None else _rounded(value)


def _result(operator, a, b):
    a, b = Fraction(a), Fraction(b)
    if operator == '+':
        value = a + b
    elif operator == '-':
        value = a - b
    elif operator == '*':
        value = a * b
    elif operator == '%':
        value = a * b / 100
    else:
        if b == 0:
            return None
        value = a / b
    fit = _fits(value)
    if fit is None and operator == '/' and (a.denominator != 1 or b.denominator != 1):       # h30: 1758,09 : 6100,34, said to two places once the exact form does not fit (h31: after it, not before)
        return _rounded(value)
    return fit


# -- the spoken number --------------------------------------------------------------------------------------------------------

_UNITS = 'ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать'.split()
_TENS = 'двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split()
_HUNDREDS = 'сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот'.split()
_SCALE_NAMES = (('тысяча', 'тысячи', 'тысяч', True), ('миллион', 'миллиона', 'миллионов', False), ('миллиард', 'миллиарда', 'миллиардов', False), ('триллион', 'триллиона', 'триллионов', False))
_FRACTION_NAMES = (('десятая', 'десятых'), ('сотая', 'сотых'), ('тысячная', 'тысячных'))


def _plural(n, one, few, many):
    if 11 <= n % 100 <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def _below_thousand(n, feminine):
    words, hundreds, rest = [], n // 100, n % 100
    if hundreds:
        words.append(_HUNDREDS[hundreds - 1])
    if rest >= 20:
        words.append(_TENS[rest // 10 - 2])
        rest %= 10
    if rest:
        words.append({1: 'одна', 2: 'две'}[rest] if feminine and rest in (1, 2) else _UNITS[rest])
    return words


def _whole(n, feminine=False):
    if n == 0:
        return 'ноль'
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    words = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            continue
        if index == 0:
            words += _below_thousand(group, feminine)
        else:
            one, few, many, scale_feminine = _SCALE_NAMES[index - 1]
            words += _below_thousand(group, scale_feminine) + [_plural(group, one, few, many)]
    return ' '.join(words)


def spell(value):
    """A whole number or a decimal as words (nominative): 21000 -> «двадцать одна тысяча», 3.5 -> «три целых пять десятых», -3 -> «минус три»."""
    sign = 'минус ' if value < 0 else ''
    text = format(abs(Decimal(value)), 'f')
    whole, _, fraction = text.partition('.')
    fraction = fraction.rstrip('0')
    if not fraction:
        return sign + _whole(int(whole))
    number = int(fraction)
    one, many = _FRACTION_NAMES[len(fraction) - 1]
    integer = int(whole)
    return '%s%s %s %s %s' % (sign, _whole(integer, True), 'целая' if integer % 10 == 1 and integer % 100 != 11 else 'целых', _whole(number, True),
                              one if number % 10 == 1 and number % 100 != 11 else many)


# -- the answer ---------------------------------------------------------------------------------------------------------------

def _answer(text):
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or len(text) > _MAX_CHARS:
        return None
    low = numbers.merge_digit_groups(text.lower().replace('ё', 'е'))
    if not _HINT.search(low) or _UNREADABLE.search(low):
        return None
    if any(left in _NUMBER_WORDS and right in _NUMBER_WORDS for left, right in _MARK_BETWEEN.findall(low)):
        return None
    for pattern, sign in _SIGNS:
        low = pattern.sub(sign, low)
    if _SIGN_LEFT.search(low):                 # a sign that stands between no two numbers: «5 + 5 +» goes on, «+5» is no sum
        return None
    tokens = _TOKEN.findall(low)
    if not tokens or len(tokens) > _MAX_TOKENS:
        return None
    if sum(token not in _NUMBER_WORDS and not _DIGITS.fullmatch(token) and token not in _FRACTION_WORDS and token != 'целых' for token in tokens) > _MAX_AROUND:
        return None
    tokens = _said_point(tokens)
    if tokens is None:
        return None
    expression = _expression(tokens)
    chain = _chain(tokens) if expression is None else None
    value = _result(*expression) if expression else _chain_result(*chain) if chain else None
    if value is None:
        return None
    words = spell(value)
    return words[0].upper() + words[1:] + '.'


_OPERATOR_WORDS = {'+': 'плюс', '-': 'минус', '*': 'на', '/': 'разделить на'}


def _stated(text):
    low = numbers.merge_digit_groups(text.strip().lower().replace('ё', 'е'))
    for pattern, sign in _SIGNS:
        low = pattern.sub(sign, low)
    tokens = _said_point(_TOKEN.findall(low))
    expression = _expression(tokens) if tokens else None
    chain = _chain(tokens) if tokens and expression is None else None
    spoken = answer(text)
    if spoken is None or not (expression or chain):
        return None
    if chain:
        a, first, b, second, c = chain
        said = '%s %s %s %s %s' % (spell(a), _OPERATOR_WORDS[first], spell(b), _OPERATOR_WORDS[second], spell(c))
    elif expression[0] == '%':
        said = '%s%% от %s' % (numbers.decimal_text(expression[1]), numbers.decimal_text(expression[2]))
    else:
        said = '%s %s %s' % (spell(expression[1]), _OPERATOR_WORDS[expression[0]], spell(expression[2]))
    return said[0].upper() + said[1:] + ' — ' + spoken[0].lower() + spoken[1:]


def stated(text: str) -> Optional[str]:
    """U43 (a): ``answer`` with its operands named, «пять на тридцать — сто пятьдесят.»: said when the ear and the cloud heard different numbers, so that a wrong operand is caught by ear. ``None`` when ``answer`` is. Never raises."""
    try:
        return _stated(text)
    except Exception:
        return None


def asked(text: str) -> bool:
    """Does ``text`` ask for the sum in words («сколько», «посчитай», «равно»)? Said with no such word a sum may be the end of something else."""
    return bool(_ASKED.intersection(_TOKEN.findall(str(text).lower().replace('ё', 'е'))))


def answer(text: str) -> Optional[str]:
    """The spoken result of a plain expression of two numbers («пять на пять» -> «Двадцать пять.»), else ``None``. Never raises."""
    try:
        return _answer(text)
    except Exception:
        return None
