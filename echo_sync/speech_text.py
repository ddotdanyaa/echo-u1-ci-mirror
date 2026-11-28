"""The text before the voice (g8-speech): every digit, symbol and abbreviation brought to words the synthesizer reads right.

Pure, no I/O, no morphology library. ``speak(text)`` -> spoken text with no digits, brackets, quotes, dashes, «%», «₽», «№» or Latin letters left;
the case, gender and number of every numeral are chosen from the preposition before it and the noun after it («от 5% до 7%» -> «от пяти процентов до семи процентов»,
«в 2026 году» -> «в две тысячи двадцать шестом году», «2 тыс. руб.» -> «две тысячи рублей»). What cannot be said safely is left as the plain cardinal, never guessed.
``cardinal`` / ``ordinal`` decline a number; ``read_back`` / ``numbers_of`` are the round-trip check: the numbers of the text must equal the numbers
of the speech (a different reader than the writer: it reads words, not the tables' logic).
"""
from __future__ import annotations

import re
from decimal import Decimal

from .lang_hint import english_runs
from .ru_numbers import CENTURY_FORMS, CENTURY_PLURAL

# U16-S8: a plural century («в XV веках», «в XIII–XV веках») is read in its own paradigm: the owner's rule of the voice, always on (no key, no switch)


CASES = ('nom', 'gen', 'dat', 'acc', 'ins', 'prep')
_CI = {c: i for i, c in enumerate(CASES)}

# -- cardinals: forms by case (nom gen dat acc ins prep) ----------------------------------------------------------------------------------------------------
_W = lambda s: s.split()                                                                                                                  # noqa: E731
_ONE = {'m': _W('один одного одному один одним одном'), 'f': _W('одна одной одной одну одной одной'), 'n': _W('одно одного одному одно одним одном')}
_TWO = {'m': _W('два двух двум два двумя двух'), 'f': _W('две двух двум две двумя двух')}
_TWO['n'] = _TWO['m']
_UNITS = {0: _W('ноль нуля нулю ноль нулём нуле'), 3: _W('три трёх трём три тремя трёх'), 4: _W('четыре четырёх четырём четыре четырьмя четырёх'),
          5: _W('пять пяти пяти пять пятью пяти'), 6: _W('шесть шести шести шесть шестью шести'), 7: _W('семь семи семи семь семью семи'),
          8: _W('восемь восьми восьми восемь восемью восьми'), 9: _W('девять девяти девяти девять девятью девяти'),
          10: _W('десять десяти десяти десять десятью десяти')}
_TEENS = {11: 'одиннадцат', 12: 'двенадцат', 13: 'тринадцат', 14: 'четырнадцат', 15: 'пятнадцат', 16: 'шестнадцат', 17: 'семнадцат', 18: 'восемнадцат',
          19: 'девятнадцат'}
_TENS = {2: _W('двадцать двадцати двадцати двадцать двадцатью двадцати'), 3: _W('тридцать тридцати тридцати тридцать тридцатью тридцати'),
         4: _W('сорок сорока сорока сорок сорока сорока'), 5: _W('пятьдесят пятидесяти пятидесяти пятьдесят пятьюдесятью пятидесяти'),
         6: _W('шестьдесят шестидесяти шестидесяти шестьдесят шестьюдесятью шестидесяти'),
         7: _W('семьдесят семидесяти семидесяти семьдесят семьюдесятью семидесяти'),
         8: _W('восемьдесят восьмидесяти восьмидесяти восемьдесят восьмьюдесятью восьмидесяти'),
         9: _W('девяносто девяноста девяноста девяносто девяноста девяноста')}
_HUNDREDS = {1: _W('сто ста ста сто ста ста'), 2: _W('двести двухсот двумстам двести двумястами двухстах'),
             3: _W('триста трёхсот трёмстам триста тремястами трёхстах'), 4: _W('четыреста четырёхсот четырёмстам четыреста четырьмястами четырёхстах'),
             5: _W('пятьсот пятисот пятистам пятьсот пятьюстами пятистах'), 6: _W('шестьсот шестисот шестистам шестьсот шестьюстами шестистах'),
             7: _W('семьсот семисот семистам семьсот семьюстами семистах'), 8: _W('восемьсот восьмисот восьмистам восемьсот восьмьюстами восьмистах'),
             9: _W('девятьсот девятисот девятистам девятьсот девятьюстами девятистах')}
# scale nouns: (gender, singular by case, plural by case)
_SCALES = {1: ('f', _W('тысяча тысячи тысяче тысячу тысячей тысяче'), _W('тысячи тысяч тысячам тысячи тысячами тысячах')),
           2: ('m', _W('миллион миллиона миллиону миллион миллионом миллионе'), _W('миллионы миллионов миллионам миллионы миллионами миллионах')),
           3: ('m', _W('миллиард миллиарда миллиарду миллиард миллиардом миллиарде'), _W('миллиарды миллиардов миллиардам миллиарды миллиардами миллиардах')),
           4: ('m', _W('триллион триллиона триллиону триллион триллионом триллионе'), _W('триллионы триллионов триллионам триллионы триллионами триллионах'))}
_SCALE_ORD = {1: 'тысячн', 2: 'миллионн', 3: 'миллиардн', 4: 'триллионн'}


def _teen(n, ci):
    s = _TEENS[n]
    return (s + 'ь', s + 'и', s + 'и', s + 'ь', s + 'ью', s + 'и')[ci]


def _unit(u, ci, gender):
    return _ONE[gender][ci] if u == 1 else _TWO[gender][ci] if u == 2 else _UNITS[u][ci]


def _group(g, ci, gender):
    words, (h, r) = [], divmod(g, 100)
    if h:
        words.append(_HUNDREDS[h][ci])
    if r >= 20:
        words.append(_TENS[r // 10][ci])
        if r % 10:
            words.append(_unit(r % 10, ci, gender))
    elif r >= 11:
        words.append(_teen(r, ci))
    elif r:
        words.append(_unit(r, ci, gender))
    return words


def count_form(n, ci, sg, pl):
    """The noun form after the number ``n`` standing in case ``ci`` (sg / pl: six forms each): «21 рубль», «2 рубля», «5 рублей», «с пятью рублями»."""
    last, teen = n % 10, 10 < n % 100 < 20
    if last == 1 and not teen:
        return sg[ci]
    if ci in (0, 3):
        return sg[1] if 2 <= last <= 4 and not teen else pl[1]
    return pl[ci]


def cardinal(n, case='nom', gender='m'):
    """The number ``n`` >= 0 in words, in the case and gender given («пяти», «двадцать одной», «две тысячи двадцать шесть»)."""
    ci, n = _CI[case], int(n)
    if n == 0:
        return _UNITS[0][ci]
    parts = []
    while n:
        parts.append(n % 1000)
        n //= 1000
    words = []
    for s in range(len(parts) - 1, -1, -1):
        g = parts[s]
        if not g:
            continue
        if s == 0:
            words += _group(g, ci, gender)
            continue
        sg_gender, sg, pl = _SCALES[s]
        if not (g == 1 and s == 1):
            words += _group(g, ci, sg_gender)
        words.append(count_form(g, ci, sg, pl))
    return ' '.join(words)


# -- ordinals -----------------------------------------------------------------------------------------------------------------------------------------------
_ORD = {1: ('перв', 'ый'), 2: ('втор', 'ой'), 3: ('трет', 'ий'), 4: ('четвёрт', 'ый'), 5: ('пят', 'ый'), 6: ('шест', 'ой'), 7: ('седьм', 'ой'), 8: ('восьм', 'ой'),
        9: ('девят', 'ый'), 10: ('десят', 'ый'), 20: ('двадцат', 'ый'), 30: ('тридцат', 'ый'), 40: ('сороков', 'ой'), 50: ('пятидесят', 'ый'),
        60: ('шестидесят', 'ый'), 70: ('семидесят', 'ый'), 80: ('восьмидесят', 'ый'), 90: ('девяност', 'ый'), 100: ('сот', 'ый'), 200: ('двухсот', 'ый'),
        300: ('трёхсот', 'ый'), 400: ('четырёхсот', 'ый'), 500: ('пятисот', 'ый'), 600: ('шестисот', 'ый'), 700: ('семисот', 'ый'), 800: ('восьмисот', 'ый'),
        900: ('девятисот', 'ый')}
for _n, _s in _TEENS.items():
    _ORD[_n] = (_s, 'ый')
_ENDINGS = {'ый': {'m': _W('ый ого ому ый ым ом'), 'f': _W('ая ой ой ую ой ой'), 'n': _W('ое ого ому ое ым ом'), 'p': _W('ые ых ым ые ыми ых')},
            'ой': {'m': _W('ой ого ому ой ым ом'), 'f': _W('ая ой ой ую ой ой'), 'n': _W('ое ого ому ое ым ом'), 'p': _W('ые ых ым ые ыми ых')},
            'ий': {'m': _W('ий ьего ьему ий ьим ьем'), 'f': _W('ья ьей ьей ью ьей ьей'), 'n': _W('ье ьего ьему ье ьим ьем'), 'p': _W('ьи ьих ьим ьи ьими ьих')}}
_COMBINE = {n: ' '.join(_group(n, 1, 'm')).replace(' ', '') for n in range(1, 1000)}
_COMBINE[1], _COMBINE[40], _COMBINE[100] = 'одно', 'сорока', 'сто'
_COMBINE[90] = 'девяносто'


def _ord_word(n, ci, gender, plural):
    stem, kind = _ORD[n]
    return stem + _ENDINGS[kind]['p' if plural else gender][ci]


def ordinal(n, case='nom', gender='m', plural=False):
    """The ordinal ``n`` >= 1 («двадцать первый», «две тысячи двадцать шестого»): only the last word is declined, the rest is nominative."""
    ci, n = _CI[case], int(n)
    if n < 1:
        return cardinal(n, case, gender)
    low = next((s for s in range(4) if (n // 1000 ** s) % 1000), 0)
    if low:                                                   # ends in thousands / millions: «двухтысячный», «стотысячный»
        head, g = n - (n // 1000 ** low % 1000) * 1000 ** low, n // 1000 ** low % 1000
        word = ('' if g == 1 else _COMBINE[g]) + _SCALE_ORD[low]
        tail = word + _ENDINGS['ый']['p' if plural else gender][ci]
        return (cardinal(head) + ' ' if head else '') + tail
    high, last = divmod(n, 100)
    if last == 0:
        return (cardinal(n - 100 * (high % 10)) + ' ' if high >= 10 else '').replace('  ', ' ') + _ord_word(100 * (high % 10), ci, gender, plural)
    if last <= 20 or last % 10 == 0:
        return ((cardinal(n - last) + ' ') if n > last else '') + _ord_word(last, ci, gender, plural)
    return cardinal(n - last % 10) + ' ' + _ord_word(last % 10, ci, gender, plural)


# -- nouns that follow numbers ------------------------------------------------------------------------------------------------------------------------------
class Noun:
    def __init__(self, sg, pl, gender):
        self.sg, self.pl, self.gender = sg.split(), pl.split(), gender

    def count(self, n, ci):
        return count_form(n, ci, self.sg, self.pl)


def _m(stem, plgen=None):
    return Noun(f'{stem} {stem}а {stem}у {stem} {stem}ом {stem}е', f'{stem}ы {plgen or stem + "ов"} {stem}ам {stem}ы {stem}ами {stem}ах', 'm')


def _soft(stem, plgen=None):
    return Noun(f'{stem}ь {stem}я {stem}ю {stem}ь {stem}ём {stem}е', f'{stem}и {plgen or stem + "ей"} {stem}ям {stem}и {stem}ями {stem}ях', 'm')


def _f(stem, plgen):
    i = 'и' if stem[-1] in 'кгхжшщч' else 'ы'
    return Noun(f'{stem}а {stem}{i} {stem}е {stem}у {stem}ой {stem}е', f'{stem}{i} {plgen} {stem}ам {stem}{i} {stem}ами {stem}ах', 'f')


def _fya(stem, plgen):
    return Noun(f'{stem}я {stem}и {stem}е {stem}ю {stem}ей {stem}е', f'{stem}и {plgen} {stem}ям {stem}и {stem}ями {stem}ях', 'f')


NOUNS = {
    'рубль': _soft('рубл'), 'копейка': _f('копейк', 'копеек'), 'доллар': _m('доллар'), 'цент': _m('цент'), 'юань': Noun('юань юаня юаню юань юанем юане', 'юани юаней юаням юани юанями юанях', 'm'),
    'евро': Noun('евро евро евро евро евро евро', 'евро евро евро евро евро евро', 'n'), 'фунт': _m('фунт'),
    'процент': _m('процент'), 'год': Noun('год года году год годом годе', 'годы лет годам годы годами годах', 'm'),
    'месяц': Noun('месяц месяца месяцу месяц месяцем месяце', 'месяцы месяцев месяцам месяцы месяцами месяцах', 'm'),
    'неделя': _fya('недел', 'недель'), 'день': Noun('день дня дню день днём дне', 'дни дней дням дни днями днях', 'm'), 'час': _m('час'),
    'минута': _f('минут', 'минут'), 'секунда': _f('секунд', 'секунд'), 'квартал': _m('квартал'), 'век': Noun('век века веку век веком веке', 'века веков векам века веками веках', 'm'),
    'килограмм': _m('килограмм'), 'грамм': _m('грамм'), 'миллиграмм': _m('миллиграмм'), 'тонна': _f('тонн', 'тонн'), 'центнер': _m('центнер'),
    'километр': _m('километр'), 'метр': _m('метр'), 'сантиметр': _m('сантиметр'), 'миллиметр': _m('миллиметр'), 'дециметр': _m('дециметр'),
    'литр': _m('литр'), 'миллилитр': _m('миллилитр'), 'гектар': _m('гектар'), 'градус': _m('градус'), 'штука': _f('штук', 'штук'),
    'человек': Noun('человек человека человеку человека человеком человеке', 'люди человек людям людей людьми людях', 'm'),
    'раз': Noun('раз раза разу раз разом разе', 'разы раз разам разы разами разах', 'm'), 'страница': _f('страниц', 'страниц'),
    'экземпляр': _m('экземпляр'), 'единица': _f('единиц', 'единиц'), 'тысяча': Noun(' '.join(_SCALES[1][1]), ' '.join(_SCALES[1][2]), 'f'),
    'миллион': Noun(' '.join(_SCALES[2][1]), ' '.join(_SCALES[2][2]), 'm'), 'миллиард': Noun(' '.join(_SCALES[3][1]), ' '.join(_SCALES[3][2]), 'm'),
    'триллион': Noun(' '.join(_SCALES[4][1]), ' '.join(_SCALES[4][2]), 'm'), 'статья': _fya('стать', 'статей'), 'часть': Noun('часть части части часть частью части', 'части частей частям части частями частях', 'f'),
    'пункт': _m('пункт'), 'подпункт': _m('подпункт'), 'глава': _f('глав', 'глав'), 'раздел': _m('раздел'), 'абзац': _m('абзац'), 'приложение': Noun('приложение приложения приложению приложение приложением приложении', 'приложения приложений приложениям приложения приложениями приложениях', 'n'),
    'таблица': _f('таблиц', 'таблиц'), 'рисунок': Noun('рисунок рисунка рисунку рисунок рисунком рисунке', 'рисунки рисунков рисункам рисунки рисунками рисунках', 'm'),
    'форма': _f('форм', 'форм'), 'приказ': _m('приказ'), 'номер': Noun('номер номера номеру номер номером номере', 'номера номеров номерам номера номерами номерах', 'm'),
}
_ADJ = {'квадратный': ('ый', 'квадратн'), 'кубический': ('ий', 'кубическ')}
_SURFACES = {}
for _k, _n in NOUNS.items():
    for _num, _forms in ((0, _n.sg), (1, _n.pl)):
        for _i, _w in enumerate(_forms):
            _SURFACES.setdefault(_w, []).append((_k, _i, _num))


def noun_hint(word):
    """What the word after a number tells about the numeral's case: ``(case or None, gender or None)``."""
    w = word.lower()
    for key, ci, plural in _SURFACES.get(w, ()):
        n = NOUNS[key]
        if plural and ci in (2, 4, 5):
            return CASES[ci], n.gender
        if not plural and ci == 3 and w != n.sg[0] and n.gender == 'f':
            return 'acc', n.gender
        return None, n.gender
    for end, ci in (('ами', 4), ('ями', 4), ('ах', 5), ('ях', 5), ('ым', 2), ('им', 2), ('ыми', 4), ('ими', 4)):
        if w.endswith(end) and len(w) > len(end) + 2:
            return CASES[ci], None
    if w.endswith(('ам', 'ям')) and len(w) > 4:
        return 'dat', None
    return None, _guess_gender(w)


_FEM_SOFT = frozenset('ночь дочь мать связь цель роль область очередь жизнь власть дверь вещь помощь соль смерть пыль степень ступень осень'.split())


def _guess_gender(w):
    """From a singular nominative or a genitive: «недели» -> f, «рубля» -> m, «дело» -> n, «статья» -> f; unknown -> None."""
    if w in _FEM_SOFT or w.endswith(('ость', 'асть')):
        return 'f'
    if w.endswith(('а', 'я')) and not w.endswith(('ия', 'ья')) or w.endswith(('ия', 'ья')):
        return 'f'
    if w.endswith(('о', 'е')) and not w.endswith(('ое', 'ее')):
        return 'n'
    return None


def _word_gender(word, n, ci):
    """Gender of the noun after 1 / 2 (and 21, 22 ...) for the numeral forms that have one."""
    w = word.lower() if word else ''
    for key, c, plural in _SURFACES.get(w, ()):
        return NOUNS[key].gender
    if not w:
        return 'm'
    last = n % 10
    if last == 1:
        if ci in (0, 3):
            return {'а': 'f', 'я': 'f', 'у': 'f', 'ю': 'f', 'о': 'n'}.get(w[-1], 'm') if not (ci == 3 and w[-1] in 'ая') else 'f'
        if ci == 1:
            return 'f' if w.endswith(('ы', 'и')) and not w.endswith('ей') else 'm'
        return 'f' if w.endswith(('ой', 'ей', 'ью')) else 'm'
    if last == 2 and ci in (0, 3):
        return 'f' if w.endswith(('ы', 'и')) else 'm'
    return 'm'


# -- reading numbers back (the check) -----------------------------------------------------------------------------------------------------------------------
def _vocab():
    v = {}
    for ci in range(6):
        for g in 'mfn':
            for u in (1, 2):
                v[_unit(u, ci, g)] = ('u', u, 0)
        for u in range(0, 11):
            if u in _UNITS:
                v[_UNITS[u][ci]] = ('u' if u < 10 else 't1', u, 0)
        for n in _TEENS:
            v[_teen(n, ci)] = ('t1', n, 0)
        for t, forms in _TENS.items():
            v[forms[ci]] = ('t', t * 10, 0)
        for h, forms in _HUNDREDS.items():
            v[forms[ci]] = ('h', h * 100, 0)
        for s, (_, sg, pl) in _SCALES.items():
            v[sg[ci]] = ('s', 10 ** (3 * s), 0)
            v[pl[ci]] = ('s', 10 ** (3 * s), 0)
    for n, (stem, kind) in _ORD.items():
        for g in 'mfn':
            for ci in range(6):
                v[stem + _ENDINGS[kind][g][ci]] = ('u' if n < 10 else 't1' if n < 20 else 't' if n < 100 and n % 10 == 0 else 'h', n, 1)
        for ci in range(6):
            v[stem + _ENDINGS[kind]['p'][ci]] = ('u' if n < 10 else 't1' if n < 20 else 't' if n < 100 and n % 10 == 0 else 'h', n, 1)
    for s in range(1, 5):
        for g in range(1, 1000):
            for ci in range(6):
                for form in ('mfnp'):
                    w = ('' if g == 1 else _COMBINE[g]) + _SCALE_ORD[s] + _ENDINGS['ый'][form][ci]
                    v[w] = ('c', g * 1000 ** s, 1)
    return v


_VOCAB = None
_MONTHS = 'января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split()
_MONTH_NOM = 'январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь'.split()
_MONTH_VAL = {}
for _i, (_a, _b) in enumerate(zip(_MONTHS, _MONTH_NOM), 1):
    _MONTH_VAL[_a] = _MONTH_VAL[_b] = _i
_WHOLE = frozenset('целых целая целой целое целым целыми целую'.split())
_DEN = {}                                                         # «десятых», «сотой», «тысячными» -> exponent
_ZERO_WORDS = frozenset(_UNITS[0])
_BREAK = re.compile(r'[а-яё]+|\d+|[^\sа-яё\d]', re.I)


def _den_words():
    d = {}
    for k in range(1, 10):
        for ci in range(6):
            for g in 'fp':
                d[ordinal(10 ** k, CASES[ci], 'f', plural=(g == 'p')).split()[-1]] = k
    return d


def read_back(spoken):
    """The numbers said in ``spoken``, in order: cardinal and ordinal runs in any case, «N целых M десятых» as decimals, month names as 1..12, digits as they are."""
    global _VOCAB, _DEN
    if _VOCAB is None:
        _VOCAB, _DEN = _vocab(), _den_words()
    toks = [m.group(0).lower() for m in _BREAK.finditer(spoken)]
    return _runs(toks)


def _runs(toks):
    out, i, n = [], 0, len(toks)

    def number(i):
        """The longest valid spoken number at ``i``: ``(value, end)`` or None. Scales descend, a group is hundreds-tens-units, an ordinal ends it."""
        total, grp, last, top, j = 0, 0, None, 10 ** 30, i
        while j < n:
            e = _VOCAB.get(toks[j])
            if e is None:
                break
            kind, val, ordinal = e
            if kind == 'c':
                if last not in (None, 's'):
                    break
                return total + grp + val, j + 1
            if kind == 's':
                if val >= top:
                    break
                total, grp, last, top, j = total + (grp or 1) * val, 0, 's', val, j + 1
                continue
            before = None if last == 's' else last
            if kind == 'h':
                ok = before is None
            elif kind in ('t', 't1'):
                ok = before in (None, 'h')
            else:
                ok = before in (None, 'h', 't') and not (val == 0 and j > i)
            if not ok:
                break
            grp, last, j = grp + val, kind, j + 1
            if ordinal or val == 0:
                break
        return (total + grp, j) if j > i else None

    while i < n:
        t = toks[i]
        if t.isdigit():
            out.append(Decimal(t))
            i += 1
        elif t in _MONTH_VAL:
            out.append(Decimal(_MONTH_VAL[t]))
            i += 1
        elif t in _VOCAB:
            r = number(i)
            if r is None:
                i += 1
                continue
            value, i = r
            if i < n and toks[i] in _WHOLE:
                r2 = number(i + 1)
                if r2 and r2[1] < n and toks[r2[1]] in _DEN:
                    dec = Decimal(value) + Decimal(r2[0]) / Decimal(10) ** _DEN[toks[r2[1]]]
                    i = r2[1] + 1
                    if i < n and _VOCAB.get(toks[i], (0,))[0] == 's':          # «одна целая пять десятых миллиона»
                        dec, i = dec * _VOCAB[toks[i]][1], i + 1
                    out.append(dec)
                    continue
            out.append(Decimal(value))
        else:
            i += 1
    return out


# -- the text engine ----------------------------------------------------------------------------------------------------------------------------------------
_TOKEN = re.compile(r'(?P<num>\d+(?:[.,]\d+)*)|(?P<word>[A-Za-zА-Яа-яЁё]+(?:[-\'’][A-Za-zА-Яа-яЁё]+)*)|(?P<sp>\s+)|(?P<ch>.)', re.S)
_GROUPS = re.compile(r'(?<![\w.,])(\d{1,3}(?: \d{3})+)(?![\d]|[.,]\d{3})')
_SPACES = dict.fromkeys(map(ord, '      ​\t'), ' ')
_PHONE = re.compile(r'(?<![\w.,])(\+7|8|7)[\s-]*\(?(\d{3})\)?[\s-]*(\d{3})[\s-]*(\d{2})[\s-]*(\d{2})(?![\d])')
_SENTENCE_END = re.compile(r'\s*$|\s+[-–—]?\s*[А-ЯЁA-Z«"“]')
# prepositions: case(s) the numeral stands in after them
_PREP = {}
for _c, _ws in (('gen', 'от до из без для около после у кроме вокруг против возле помимо свыше ради среди внутри вместо сверх более менее порядка течение размере сумме пределах '
                        'позднее ранее истечении протяжении учётом учетом начиная окончании составе возрасте количестве объёме объеме'), ('dat', 'к согласно вопреки благодаря навстречу'),
                ('ins', 'над перед между'), ('prep', 'при'), ('acc', 'через про сквозь')):
    for _w in _ws.split():
        _PREP[_w] = (_c,)
_PREP.update({'в': ('acc', 'prep'), 'во': ('acc', 'prep'), 'на': ('acc', 'prep'), 'за': ('acc', 'ins'), 'по': ('acc', 'dat', 'prep'), 'о': ('prep', 'acc'),
              'об': ('prep', 'acc'), 'с': ('gen', 'ins', 'acc'), 'со': ('gen', 'ins', 'acc'), 'под': ('acc', 'ins'), 'из-за': ('gen',), 'около': ('gen',)})
_SKIP = frozenset('не примерно ровно почти где-то всего ещё еще уже только лишь целых'.split())
_MONTH_GEN = {m: i for i, m in enumerate(_MONTHS, 1)}
YEAR_WORDS = {'год': 'nom', 'года': 'gen', 'году': 'prep', 'годом': 'ins', 'годе': 'prep', 'годы': 'nom', 'годов': 'gen', 'годах': 'prep', 'годам': 'dat', 'годами': 'ins'}
_ACC_WORDS = frozenset('счёт счета счету счётом счетом счете счёте счетах счетов субсчёт субсчета субсчёту субсчете субсчетах дебет дебета дебету кредит кредита кредиту сч '
                       'субсчет субсчёта'.split())
_ID_WORDS = frozenset('инн кпп бик огрн огрнип снилс окпо октмо оквэд кбк'.split())
_ROMAN = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
# reference heads: surface -> (noun, case, plural)
_REF_ABBR = {'ст': 'статья', 'п': 'пункт', 'пп': 'подпункт', 'подп': 'подпункт', 'ч': 'часть', 'гл': 'глава', 'разд': 'раздел', 'абз': 'абзац', 'прил': 'приложение',
             'табл': 'таблица', 'рис': 'рисунок', 'стр': 'страница'}
_REF_SURFACE = {}
for _k in ('статья', 'пункт', 'подпункт', 'часть', 'глава', 'раздел', 'абзац', 'приложение', 'таблица', 'рисунок', 'страница', 'форма', 'приказ'):
    _n = NOUNS[_k]
    for _i in range(6):
        _REF_SURFACE.setdefault(_n.sg[_i], (_k, CASES[_i], False))
    for _i in range(6):
        _REF_SURFACE.setdefault(_n.pl[_i], (_k, CASES[_i], True))
_REF_SURFACE['статьей'] = ('статья', 'ins', False)
_REF_SURFACE['статью'] = ('статья', 'acc', False)
_ADJ_END = {'ый': _W('ый ого ому ый ым ом'), 'ой': _W('ой ого ому ой ым ом'), 'ий': _W('ий ого ому ий им ом')}
CODES = {'нк': ((('Налогов', 'ый'),), 0, 'кодекс'), 'тк': ((('Трудов', 'ой'),), 0, 'кодекс'), 'гк': ((('Гражданск', 'ий'),), 0, 'кодекс'),
         'ук': ((('Уголовн', 'ый'),), 0, 'кодекс'), 'бк': ((('Бюджетн', 'ый'),), 0, 'кодекс'), 'жк': ((('Жилищн', 'ый'),), 0, 'кодекс'), 'зк': ((('Земельн', 'ый'),), 0, 'кодекс'),
         'ск': ((('Семейн', 'ый'),), 0, 'кодекс'), 'апк': ((('Арбитражн', 'ый'), ('процессуальн', 'ый')), 0, 'кодекс'),
         'гпк': ((('Гражданск', 'ий'), ('процессуальн', 'ый')), 0, 'кодекс'), 'упк': ((('Уголовно-процессуальн', 'ый'),), 0, 'кодекс'), 'коап': ((), 0, 'кодекс')}
# letters
_CYR = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя', 'а бэ вэ гэ дэ е ё жэ зэ и и_краткое ка эль эм эн о пэ эр эс тэ у эф ха цэ чэ ша ща твёрдый_знак ы мягкий_знак э ю я'.split()))
_CYR['й'] = 'и краткое'
_CYR['ъ'], _CYR['ь'] = 'твёрдый знак', 'мягкий знак'
_LAT_RU = dict(zip('abcdefghijklmnopqrstuvwxyz', 'а бэ цэ дэ е эф гэ аш и йот ка эль эм эн о пэ ку эр эс тэ у вэ дубль-вэ икс игрек зэт'.split()))
_LAT_EN = dict(zip('abcdefghijklmnopqrstuvwxyz', 'эй би си ди и эф джи эйч ай джей кей эл эм эн оу пи кью ар эс ти ю ви дабл-ю икс уай зед'.split()))
LAT_WORDS = {'excel': 'эксель', 'word': 'ворд', 'powerpoint': 'пауэр пойнт', 'windows': 'виндовс', 'google': 'гугл', 'internet': 'интернет', 'online': 'онлайн', 'email': 'имейл',
             'e-mail': 'имейл', 'ok': 'окей', 'wifi': 'вай фай', 'wi-fi': 'вай фай', 'office': 'офис', 'zoom': 'зум', 'telegram': 'телеграм', 'whatsapp': 'вотсап', 'ctrl': 'контрол',
             'shift': 'шифт', 'alt': 'альт', 'enter': 'энтер', 'esc': 'эскейп', 'tab': 'таб', 'delete': 'делит', 'excel.': 'эксель', 'pdf': 'пи ди эф', 'sql': 'эс кью эль',
             'ai': 'эй ай', 'it': 'ай ти', 'ceo': 'си и о', 'usd': 'доллар', 'eur': 'евро', 'rub': 'рубль'}
_TR = [('shch', 'щ'), ('sch', 'ск'), ('sh', 'ш'), ('ch', 'ч'), ('th', 'т'), ('ph', 'ф'), ('ck', 'к'), ('kh', 'х'), ('zh', 'ж'), ('ee', 'и'), ('oo', 'у'), ('ea', 'и'),
       ('ou', 'ау'), ('ie', 'и'), ('qu', 'кв'), ('ya', 'я'), ('yu', 'ю'), ('yo', 'ё')]
_TR1 = dict(zip('abcdefghijklmnopqrstuvwxyz', 'абкдефгхижклмнопкрстувквксиз'))
_TR1['c'], _TR1['y'], _TR1['w'], _TR1['x'], _TR1['q'] = 'к', 'и', 'в', 'кс', 'к'
WORD_ACRONYMS = frozenset('ГОСТ МРОТ ОКВЭД СНИЛС ОГРН БИК СУММ СЧЁТ СЧЕТ ЕСЛИ МАКС МИН ИСТИНА ЛОЖЬ ИЛИ СРЗНАЧ СЧЁТЕСЛИ СЧЕТЕСЛИ СУММЕСЛИ СЧЁТЗ СЧЕТЗ ВПР ГПР НДС_'.split()) | frozenset({'НЕ', 'ИЛИ'})
ACRONYMS = {'ООО': 'о о о', 'ИП': 'и пэ', 'АО': 'а о', 'ПАО': 'пэ а о', 'ИНН': 'и эн эн', 'КПП': 'ка пэ пэ', 'РФ': 'Российской Федерации'}
UNITS = {'кг': 'килограмм', 'г': 'грамм', 'мг': 'миллиграмм', 'т': 'тонна', 'ц': 'центнер', 'км': 'километр', 'м': 'метр', 'см': 'сантиметр', 'мм': 'миллиметр', 'дм': 'дециметр',
         'л': 'литр', 'мл': 'миллилитр', 'га': 'гектар', 'ч': 'час', 'мин': 'минута', 'сек': 'секунда', 'дн': 'день', 'мес': 'месяц', 'нед': 'неделя', 'шт': 'штука',
         'чел': 'человек', 'экз': 'экземпляр', 'руб': 'рубль', 'коп': 'копейка', 'долл': 'доллар', 'евро': 'евро', 'лет': 'год', 'гг': 'год'}
SCALE_ABBR = {'тыс': 1, 'млн': 2, 'млрд': 3, 'трлн': 4}
SYMBOLS = {'+': 'плюс', '=': 'равно', '×': 'умножить на', '*': 'умножить на', '÷': 'разделить на', '>': 'больше', '<': 'меньше', '≥': 'больше или равно',
           '≤': 'меньше или равно', '≈': 'примерно', '±': 'плюс-минус', '&': 'и', '@': 'собака', '§': 'параграф', '°': 'градусов'}
_PER = {'ч': 'в час', 'час': 'в час', 'с': 'в секунду', 'сек': 'в секунду', 'мин': 'в минуту', 'мес': 'в месяц', 'год': 'в год', 'дн': 'в день', 'сут': 'в сутки'}
_SUFFIX = {'й': ('nom', 'm'), 'ый': ('nom', 'm'), 'ой': ('nom', 'm'), 'ий': ('nom', 'm'), 'я': ('nom', 'f'), 'ая': ('nom', 'f'), 'е': ('nom', 'n'), 'ое': ('nom', 'n'),
           'го': ('gen', 'm'), 'ого': ('gen', 'm'), 'его': ('gen', 'm'), 'му': ('dat', 'm'), 'ому': ('dat', 'm'), 'ему': ('dat', 'm'), 'ю': ('acc', 'f'), 'ую': ('acc', 'f'),
           'м': ('ins', 'm'), 'ым': ('ins', 'm'), 'им': ('ins', 'm'), 'ом': ('prep', 'm'), 'ем': ('prep', 'm'), 'х': ('gen', 'p'), 'ых': ('gen', 'p'), 'их': ('gen', 'p'),
           'ые': ('nom', 'p'), 'ие': ('nom', 'p'), 'ми': ('ins', 'p'), 'ыми': ('ins', 'p'), 'ими': ('ins', 'p')}


def _cyr_letter(ch):
    return _CYR.get(ch.lower(), ch)


def spell(word, lat=_LAT_EN):
    """Letter names of a word («НДС» -> «эн дэ эс», «PDF» -> «пи ди эф»)."""
    return ' '.join((lat.get(c.lower()) if c.isascii() else _cyr_letter(c)) or c for c in word if c.isalpha()).replace('_', ' ')


def _vowelish(word):
    low = word.lower()
    return any(c in 'аеёиоуыэюя' for c in low) and not re.search(r'[бвгджзйклмнпрстфхцчшщ]{3}', low)


def latin(word):
    low = word.lower()
    if low in LAT_WORDS:
        return LAT_WORDS[low]
    if word.isupper() or len(word) <= 2:
        return spell(word)
    out, i = '', 0
    while i < len(low):
        for a, b in _TR:
            if low.startswith(a, i):
                out, i = out + b, i + len(a)
                break
        else:
            out, i = out + _TR1.get(low[i], low[i]), i + 1
    return out


def _unabbrev(word):
    """An all-capitals word: acronym, spelled by letters, or a word read as it is."""
    if word in ACRONYMS:
        return ACRONYMS[word]
    if word.upper() in WORD_ACRONYMS or (len(word) >= 4 and _vowelish(word) and not word in ('ФСБУ', 'ЕСХН', 'НДФЛ')):
        return word.lower()
    return spell(word)


class _Speaker:
    def __init__(self, text):
        text = text.translate(_SPACES).replace('\r', ' ').replace('\n', ' ')
        text = _GROUPS.sub(lambda m: m.group(1).replace(' ', ''), text)
        self.toks = [(m.lastgroup, m.group(0)) for m in _TOKEN.finditer(text)]
        self.i, self.out, self.acc, self.prev_ref = 0, [], False, -10
        self.n = len(self.toks)

    # token helpers ----------------------------------------------------------------------------------------------------------------------------------------
    def kind(self, j):
        return self.toks[j][0] if 0 <= j < self.n else None

    def text(self, j):
        return self.toks[j][1] if 0 <= j < self.n else ''

    def low(self, j):
        return self.text(j).lower()

    def next_sig(self, j):
        """Index of the next non-space token after ``j`` (spaces only), or -1."""
        j += 1
        while j < self.n and self.kind(j) == 'sp':
            j += 1
        return j if j < self.n else -1

    def prev_words(self, j, k=2):
        """The ``k`` words before token ``j`` when only spaces lie between (a punctuation mark breaks it); skipped fillers do not count."""
        words, p = [], j - 1
        while p >= 0 and len(words) < k:
            if self.kind(p) == 'sp':
                p -= 1
            elif self.kind(p) == 'word':
                w = self.low(p)
                if w in _SKIP and words == []:
                    p -= 1
                    continue
                words.append(w)
                p -= 1
                if p >= 0 and self.kind(p) == 'ch' and self.text(p) == '.':
                    break
            else:
                break
        return words

    def prep_case(self, j):
        """The cases the preposition before token ``j`` asks for, or None."""
        words = self.prev_words(j, 2)
        if not words:
            return None
        if words[0] in _PREP:
            if words[0] in ('по', 'с', 'со') and len(words) > 1 and words[1] in ('не', 'ни'):
                pass
            return _PREP[words[0]]
        return None

    def sentence_dot(self, j):
        """After an abbreviation that ends at token ``j-1`` with a dot at ``j``: keep the dot when a sentence ends there."""
        return bool(_SENTENCE_END.match(''.join(t for _, t in self.toks[j + 1:j + 4])) or j + 1 >= self.n)

    def emit(self, s):
        self.out.append(s)

NOUNS.update({'число': Noun('число числа числу число числом числе', 'числа чисел числам числа числами числах', 'n'), 'класс': _m('класс'), 'курс': _m('курс'),
              'этаж': Noun('этаж этажа этажу этаж этажом этаже', 'этажи этажей этажам этажи этажами этажах', 'm')})
_SURFACES.clear()
for _k, _n in NOUNS.items():
    for _num, _forms in ((0, _n.sg), (1, _n.pl)):
        for _i, _w in enumerate(_forms):
            _SURFACES.setdefault(_w, []).append((_k, _i, _num))
_ORD_NOUNS = frozenset('квартал число класс курс этаж век'.split())
_PREP_ONE = {'в': 'prep', 'во': 'prep', 'на': 'prep', 'о': 'prep', 'об': 'prep', 'при': 'prep', 'по': 'dat', 'к': 'dat', 'согласно': 'dat', 'с': 'ins', 'со': 'ins',
             'за': 'acc', 'про': 'acc', 'через': 'acc', 'над': 'ins', 'перед': 'ins', 'между': 'ins', 'под': 'ins'}
_DASHES = '-–—−'
_QUOTES = '«»"“”„‘’`\''
_SOFT = '\x01'


def decimal_words(whole, digits, case='nom'):
    """«2,5» -> «две целых пять десятых» in the case given; more than nine decimals are read digit by digit."""
    ci = _CI[case]
    if len(digits) > 9:
        return cardinal(whole, case, 'f') + ' целых запятая ' + ' '.join(_UNITS[0][0] if d == '0' else _unit(int(d), 0, 'm') for d in digits)
    whole_word = cardinal(whole, case, 'f')
    last = whole % 10
    if last == 1 and whole % 100 != 11:
        tail = _W('целая целой целой целую целой целой')[ci]
    else:
        tail = _W('целые целых целым целые целыми целых')[ci] if ci not in (0, 3) else 'целых'
    num, den = int(digits), len(digits)
    k = num % 10
    numer = cardinal(num, case, 'f')
    if k == 1 and num % 100 != 11:
        d = ordinal(10 ** den, case, 'f')
    else:
        d = ordinal(10 ** den, 'gen' if ci in (0, 3) else case, 'f', plural=True)
    return f'{whole_word} {tail} {numer} {d}'


def _frac_words(a, b, case='nom'):
    ci = _CI[case]
    one = a % 10 == 1 and a % 100 != 11
    d = ordinal(b, case, 'f') if one else ordinal(b, 'gen' if ci in (0, 3) else case, 'f', plural=True)
    return f'{cardinal(a, case, "f")} {d}'


def digits_spoken(s):
    """A string of digits one by one («0310001» -> «ноль три один ноль ноль ноль один»), in groups of three when long."""
    words = [(_UNITS[0][0] if d == '0' else _unit(int(d), 0, 'm')) for d in s]
    if len(words) <= 4:
        return ' '.join(words)
    cut = list(range(0, len(words), 3))
    groups = [words[k:k + 3] for k in cut]
    if len(groups) > 1 and len(groups[-1]) == 1:
        tail = groups.pop()
        groups[-1] = groups[-1] + tail
    return ', '.join(' '.join(g) for g in groups)


_COURSE_CODES = frozenset('МДК ПМ ОП УП ПП ОГСЭ ЕН ПДП'.split())      # the codes of a course or a module in the journal and the plan of study


def _roman(word):
    if not word or any(c not in _ROMAN for c in word):
        return None
    total = sum(-_ROMAN[c] if k + 1 < len(word) and _ROMAN[word[k + 1]] > _ROMAN[c] else _ROMAN[c] for k, c in enumerate(word))
    spelled, rest = '', total
    for value, sym in ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        while rest >= value:
            spelled, rest = spelled + sym, rest - value
    return total if spelled == word and total else None


def s_prep(word):
    """«с» or «со» before the word («со второго», «с первого»)."""
    w = word.lower()
    v = 'аеёиоуыэюя'
    return 'со' if len(w) > 1 and ((w[0] in 'вфсзшщ' and w[1] not in v) or w[:2] in ('мн', 'рт', 'лб', 'лг', 'лж')) else 'с'


class _Engine(_Speaker):
    # -- the loop -----------------------------------------------------------------------------------------------------------------------------------------
    def run(self):
        while self.i < self.n:
            k, t = self.toks[self.i]
            start = self.i
            if k == 'num':
                self.number()
                self.end_dot(start)
            elif k == 'word':
                self.word()
                self.end_dot(start)
            elif k == 'sp':
                self.emit(t)
                self.i += 1
            else:
                self.char()
        return self.clean(''.join(self.out))

    def drop_prep(self):
        """Take the preposition just emitted back: «в 2020–2022 гг.» becomes «с … по … годы»."""
        if len(self.out) >= 2 and self.out[-1].isspace() and self.out[-2].lower() in ('в', 'во'):
            del self.out[-2:]
            return True
        return False

    def s_word(self, i, first):
        """The «с» of «с первого по пятое»: left out when a preposition already stands before the range."""
        return '' if self.prep_case(i) is not None else s_prep(first) + ' '

    def end_dot(self, start):
        """A handler that swallowed «руб.» / «гг.» at the end of a sentence gives the sentence its dot back."""
        j = self.i - 1
        if j > start and self.kind(j) == 'ch' and self.text(j) == '.' and self.sentence_dot(j) and not (self.out and self.out[-1].endswith('.')):
            self.emit('.')

    def adjacent(self, j, kind=None):
        """Token ``j`` exists (and is of ``kind``): used for «no space in between»."""
        return 0 <= j < self.n and (kind is None or self.kind(j) == kind)

    def case_of(self, j, n, noun=None):
        hint, _ = noun_hint(noun) if noun else (None, None)
        if hint:
            return hint
        p = self.prep_case(j)
        if p is None:
            return 'nom'
        if len(p) == 1:
            return p[0]
        low = (noun or '').lower()
        one = n % 10 == 1 and n % 100 != 11
        if 'ins' in p and p[0] == 'gen' and one and low.endswith(('ом', 'ем', 'ой', 'ей', 'ью')):
            return 'ins'
        if 'dat' in p and p[0] == 'acc' and one and low.endswith(('у', 'ю')):
            return 'dat'
        return p[0]

    def gender_of(self, n, case, noun=None):
        return _word_gender(noun, n, _CI[case]) if noun else 'm'

    def one_case(self, j):
        """The case a reference head or a code abbreviation stands in (a single case, from the preposition)."""
        words = self.prev_words(j, 1)
        if words and words[0] in _PREP_ONE:
            return _PREP_ONE[words[0]]
        if words and words[0] in _PREP:
            return _PREP[words[0]][0]
        return 'nom'

    # -- numbers ------------------------------------------------------------------------------------------------------------------------------------------
    def number(self):
        i, s = self.i, self.text(self.i)
        if self.fixed_digits(i, s):
            return
        acc, self.acc = self.acc, False
        if '.' in s and ',' not in s:
            return self.dotted(i, s, acc)
        if ',' in s:
            return self.commas(i, s)
        n = int(s)
        if acc and self.account(i, s):
            return
        if self.time(i, s) or self.fraction(i, s) or self.marker(i, n):
            return
        if self.spans_dash(i, n):
            return
        self.quantity(i, n, None)

    def fixed_digits(self, i, s):
        prev = self.prev_words(i, 1)
        if s.isdigit() and (len(s) >= 9 or (len(s) > 1 and s[0] == '0') or (prev and prev[0] in _ID_WORDS and len(s) >= 5)):
            if len(s) < 9 and (self.acc or (self.adjacent(i + 1, 'ch') and self.text(i + 1) in _DASHES and self.kind(i + 2) == 'num')):
                self.acc = True
                return False
            self.emit(digits_spoken(s))
            self.i = i + 1
            self.tail_letters(i + 1)
            return True
        return False

    def tail_letters(self, j):
        """Letters glued to a number: «157н» -> «сто пятьдесят семь эн», «402-ФЗ», «3210-У», «6-НДФЛ» (the number is already emitted)."""
        k = j
        if self.adjacent(k, 'ch') and self.text(k) == '-' and self.adjacent(k + 1, 'word'):
            k += 1
        if self.adjacent(k, 'word') and (k == j or self.low(k) not in _SUFFIX or not self.text(k).islower()):
            w = self.text(k)
            if w.lower() in UNITS or w.lower() in SCALE_ABBR:
                return False
            if len(w) <= 2 and w.isalpha() and w.isupper() == (len(w) > 0 and w.isupper()) or w.isupper() or (k == j and len(w) == 1):
                self.emit(' ' + (_unabbrev(w) if len(w) > 1 else _cyr_letter(w)))
                self.i = k + 1
                return True
        return False

    def course_code_before(self, i):
        """Is token ``i`` the number of a course or module code («МДК.03.01», «МДК 03.01»)? The upper-case letters of the code stand right before it, with a full stop or a space between."""
        p = i - 1
        while p >= 0 and (self.kind(p) == 'sp' or (self.kind(p) == 'ch' and self.text(p) == '.')):
            p -= 1
        return p >= 0 and self.kind(p) == 'word' and self.text(p) in _COURSE_CODES

    def dotted(self, i, s, acc=False):
        parts = s.split('.')
        if len(parts) == 2 and all(len(p) == 2 and p.isdigit() for p in parts) and self.course_code_before(i):
            self.emit(' точка '.join(digits_spoken(p) for p in parts))       # level2-c of 06.11 (bank 5, b01118): «МДК.03.01» was read as the date «третьего января»: a code is said digit by digit
            self.i = i + 1
            return
        if len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 2 and not acc and parts[0].isdigit() and parts[1].isdigit() and 1 <= int(parts[0]) <= 31 and 1 <= int(parts[1]) <= 12:
            j = i + 1                                              # «06.11», «08.09-16.09»: a day and a month
            second = None
            if self.adjacent(j, 'ch') and self.text(j) in '-–—−' and self.kind(j + 1) == 'num':
                q = self.text(j + 1).split('.')
                if len(q) == 2 and all(len(x) == 2 and x.isdigit() for x in q) and 1 <= int(q[0]) <= 31 and 1 <= int(q[1]) <= 12:
                    second = q
            if second:
                first = ordinal(int(parts[0]), "gen", "n")
                self.emit(f'{self.s_word(i, first)}{first} {_MONTHS[int(parts[1]) - 1]} по {ordinal(int(second[0]), "acc", "n")} {_MONTHS[int(second[1]) - 1]}')
                self.i = j + 2
            else:
                self.emit(f'{ordinal(int(parts[0]), self.date_case(i), "n")} {_MONTHS[int(parts[1]) - 1]}')
                self.i = i + 1
            return
        nxt = self.next_sig(i)
        if len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[2]) in (2, 4) and 1 <= int(parts[0]) <= 31 and 1 <= int(parts[1]) <= 12:
            year = int(parts[2]) + (2000 if len(parts[2]) == 2 else 0)
            self.emit(self.date_words(int(parts[0]), int(parts[1]), year, self.date_case(i)))
            self.i = i + 1
            return
        self.emit(' точка '.join(digits_spoken(p) if len(p) > 1 and p[0] == '0' else cardinal(int(p)) for p in parts))
        self.i = i + 1

    def commas(self, i, s):
        parts = s.split(',')
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return self.quantity(i, Decimal(s.replace(',', '.')), parts)
        self.emit(', '.join(cardinal(int(p)) if p.isdigit() else p for p in parts))
        self.i = i + 1

    def date_case(self, j):
        p = self.prev_words(j, 1)
        if p and p[0] in ('по', 'на', 'за', 'через', 'про'):
            return 'acc'
        if p and p[0] == 'к':
            return 'dat'
        return 'gen'

    def date_words(self, d, m, y, case='gen'):
        out = f'{ordinal(d, case, "n")} {_MONTHS[m - 1]}'
        if y:
            out += f' {ordinal(y, "gen")} года'
        return out

    def marker(self, i, n):
        """A list marker «1)» at the start of a sentence."""
        if self.adjacent(i + 1, 'ch') and self.text(i + 1) == ')':
            before = ''.join(self.out).rstrip()
            if not before or before[-1] in '.:;!?':
                self.emit(ordinal(n, 'nom', 'n') + ',')
                self.i = i + 2
                return True
        return False

    def time(self, i, s):
        if len(s) <= 2 and self.adjacent(i + 1, 'ch') and self.text(i + 1) == ':' and self.kind(i + 2) == 'num' and len(self.text(i + 2)) == 2 and self.text(i + 2).isdigit():
            h, mm = int(s), int(self.text(i + 2))
            if h <= 24 and mm < 60 and not (self.adjacent(i + 3, 'ch') and self.text(i + 3) == ':' and self.kind(i + 4) == 'num'):
                case = self.case_of(i, h)
                if mm == 0:
                    self.emit(f'{cardinal(h, case)} {NOUNS["час"].count(h, _CI[case])}')
                else:
                    self.emit(f'{cardinal(h, case)} {digits_spoken(self.text(i + 2)) if mm < 10 else cardinal(mm, case)}')
                self.i = i + 3
                return True
        return False

    def fraction(self, i, s):
        if self.adjacent(i + 1, 'ch') and self.text(i + 1) == '/' and self.kind(i + 2) == 'num' and self.text(i + 2).isdigit() and s.isdigit():
            a, b = int(s), int(self.text(i + 2))
            case = self.case_of(i, a)
            sa, sb = s, self.text(i + 2)
            if 2 <= b <= 1000 and 0 < a < b and sa[0] != '0' and sb[0] != '0':
                self.emit(_frac_words(a, b, case))
            else:
                word = lambda x: digits_spoken(x) if len(x) > 1 and x[0] == '0' else cardinal(int(x))      # noqa: E731
                self.emit(f'{word(sa)} дробь {word(sb)}')
            self.i = i + 3
            return True
        return False

    def account(self, i, s):
        """After «счёт», «дебет», «кредит»: accounts are said in the nominative, «73-1» as «семьдесят три точка один», «01-99» as a range."""
        def word(p):
            return digits_spoken(p) if len(p) > 1 and p[0] == '0' else cardinal(int(p))
        j = i + 1
        if len(s) > 3 or self.unit_at(j) is not None or self.adjacent(j, 'word'):
            return False
        if self.adjacent(j, 'ch') and self.text(j) in _DASHES and self.kind(j + 1) == 'num' and self.text(j + 1).isdigit():
            b = self.text(j + 1)
            if len(b) == len(s) and len(s) >= 2 and int(b) > int(s):
                self.emit(f'от {word(s)} до {word(b)}')
            else:
                self.emit(f'{word(s)} точка {word(b)}')
            j += 2
        else:
            self.emit(word(s))
        self.i = j
        nxt = self.next_sig(j - 1)
        self.acc = not (nxt >= 0 and self.kind(nxt) == 'word' and self.low(nxt) not in ('и', 'или', 'по'))
        return True

    def spans_dash(self, i, n):
        """A range «5–10», «2020–2022 гг.», «1–5 ноября» or a number glued to an acronym «402-ФЗ»."""
        j = i + 1
        sp = self.kind(j) == 'sp' and self.adjacent(j + 1, 'ch') and self.text(j + 1) in '–—−' and self.kind(j + 2) in ('sp', 'num')
        if sp:
            j += 1
        if not (self.adjacent(j, 'ch') and self.text(j) in _DASHES):
            return False
        k = j + 1
        if self.kind(k) == 'sp' and (sp or self.text(j) in '–—−'):
            k += 1
        if self.kind(k) == 'num' and self.text(k).isdigit() and (sp or self.kind(j - 1) == 'num'):
            m = int(self.text(k))
            if m > n:
                return self.range_(i, n, k, m)
            if self.kind(j - 1) == 'num' and not sp:
                self.emit(f'{cardinal(n)} тире {cardinal(m)}')
                self.i = k + 1
                return True
        return False

    def century_range(self, i, n, m, after):
        """«13–15 веках», «XIII–XV веках» (U16-S8): both ends are ordinals in the case of the plural noun, the noun after them."""
        case = CASES[_SURFACES[self.low(after)][0][1]]
        self.emit(f'{ordinal(n, case, "m", True)} {"и" if m == n + 1 else "по"} {ordinal(m, case, "m", True)} {self.text(after)}')
        self.i = after + 1
        return True

    def unit_at(self, j):
        """The unit that follows a number: ``(key, adj, end, scale, per)`` or None. ``end`` is the index after the unit (a dot included)."""
        k = self.next_sig(j - 1) if self.kind(j) == 'sp' else (j if j < self.n else -1)
        if k < 0 or k - j > 1:
            return None
        kind, t = self.kind(k), self.text(k)
        if kind == 'ch':
            sym = {'%': 'процент', '₽': 'рубль', '€': 'евро', '$': 'доллар', '£': 'фунт'}.get(t)
            if sym:
                return sym, None, k + 1, 0, None
            if t == '°':
                e = k + 1
                suffix = ''
                if self.adjacent(e, 'word') and self.text(e) in ('C', 'С', 'F'):
                    suffix, e = ' Цельсия' if self.text(e) != 'F' else ' Фаренгейта', e + 1
                return 'градус', None, e, 0, suffix
            return None
        if kind != 'word':
            return None
        w = t.lower()
        end = k + 1
        dot = self.adjacent(end, 'ch') and self.text(end) == '.'
        if w in SCALE_ABBR:
            end += 1 if dot else 0
            rest = self.unit_at(end) if self.kind(end) == 'sp' else None
            return (rest[0], rest[1], rest[2], SCALE_ABBR[w], rest[4]) if rest else (None, None, end, SCALE_ABBR[w], None)
        if w == 'кв' and dot:
            m = self.next_sig(end)
            if m >= 0 and self.kind(m) == 'word' and self.low(m) in ('м', 'км', 'см', 'мм'):
                return UNITS[self.low(m)], 'квадратный', m + 1 + (1 if self.adjacent(m + 1, 'ch') and self.text(m + 1) == '.' else 0), 0, None
        if w == 'куб' and dot:
            m = self.next_sig(end)
            if m >= 0 and self.kind(m) == 'word' and self.low(m) in ('м', 'км', 'см', 'мм'):
                return UNITS[self.low(m)], 'кубический', m + 1 + (1 if self.adjacent(m + 1, 'ch') and self.text(m + 1) == '.' else 0), 0, None
        if w in ('м', 'км', 'см', 'мм') and (self.text(end) in ('²', '³') if self.adjacent(end, 'ch') else (self.adjacent(end, 'num') and self.text(end) in ('2', '3'))):
            return UNITS[w], 'квадратный' if self.text(end) in ('²', '2') else 'кубический', end + 1, 0, None
        if w in UNITS and (w not in ('лет', 'гг', 'г') or w == 'г'):
            if w == 'г':
                return 'грамм', None, end + (1 if dot else 0), 0, None
            per = None
            if self.adjacent(end + (1 if dot else 0), 'ch') and self.text(end + (1 if dot else 0)) == '/' and self.kind(end + (2 if dot else 1)) == 'word' \
                    and self.low(end + (2 if dot else 1)) in _PER:
                per = ' ' + _PER[self.low(end + (2 if dot else 1))]
                e2 = end + (3 if dot else 2) + (1 if self.adjacent(end + (3 if dot else 2), 'ch') and self.text(end + (3 if dot else 2)) == '.' else 0)
                return UNITS[w], None, e2, 0, per
            if w in ('г', 'м', 'л', 'т', 'ч', 'ц') or dot or len(w) >= 2:
                return UNITS[w], None, end + (1 if dot else 0), 0, None
        if w in ('р', 'руб', 'рублей') and dot:
            return 'рубль', None, end + 1, 0, None
        return None

    def money_unit(self, key):
        return key in ('рубль', 'доллар', 'евро', 'фунт', 'юань', 'копейка', 'цент')

    def quantity(self, i, v, parts):
        """A number with what stands after it: unit, percent, money, scale, year, century, ordinal noun, or a bare count."""
        n_int = None if parts else v
        # glued ordinal suffix «25-го», «5-й», «90-х»
        if self.adjacent(i + 1, 'ch') and self.text(i + 1) == '-' and self.adjacent(i + 2, 'word') and not parts:
            suf = self.text(i + 2)
            if suf in _SUFFIX and suf.islower():
                return self.suffix_ordinal(i, v, suf)
            if 0 < v < 1000 and len(suf) > 3 and suf.islower() and suf.isalpha():
                self.emit(_COMBINE[int(v)] + suf)
                self.i = i + 3
                return
            if self.tail_letters_check(i + 1):
                self.emit(cardinal(v))
                self.i = i + 1
                self.tail_letters(i + 1)
                return
        nxt = self.next_sig(i)
        word = self.low(nxt) if nxt >= 0 and self.kind(nxt) == 'word' and nxt - i <= 2 else None
        # Roman century / date / year / ordinal nouns
        if word is not None and not parts:
            if word in _MONTH_GEN and 1 <= v <= 31:
                return self.date_phrase(i, int(v), nxt)
            hint = _SURFACES.get(word, ())
            key = hint[0][0] if hint else None
            if word in YEAR_WORDS and v >= 100:
                return self.year(i, int(v), nxt, YEAR_WORDS[word])
            if word in ('г', 'гг') and self.year_abbr(i, v, nxt, word):
                return
            if key in _ORD_NOUNS and ((key == 'век' and 1 <= v <= 40) or (key == 'квартал' and v <= 4) or (key == 'число' and 1 <= v <= 31) or key in ('класс', 'курс', 'этаж')) \
                    and hint[0][2] == 0:
                ci = hint[0][1]
                case = CASES[ci] if ci not in (0, 3) else self.case_of(i, int(v))
                self.emit(ordinal(int(v), case, NOUNS[key].gender))
                self.i = i + 1
                return
        unit = self.unit_at(i + 1) if not (word in YEAR_WORDS) else None
        ci_case = self.case_of(i, int(v) if parts is None else int(parts[0]), None if unit else (self.text(nxt) if word is not None and nxt >= 0 else None))
        if unit is None:
            return self.bare(i, v, parts, nxt, word, ci_case)
        key, adj, end, scale, per = unit
        if key == 'процент' and parts is None and 0 < v < 1000 and self.adjacent(end, 'ch') and self.text(end) == '-' and self.adjacent(end + 1, 'word') \
                and self.text(end + 1).islower() and self.text(end + 1).endswith(('ный', 'ная', 'ное', 'ные', 'ного', 'ной', 'ным', 'ных', 'ную')):
            self.emit(_COMBINE[int(v)] + 'процент' + self.text(end + 1))
            self.i = end + 2
            return
        self.i = end
        self.emit_quantity(i, v, parts, key, adj, scale, per, ci_case)

    def tail_letters_check(self, j):
        return self.adjacent(j + 1, 'word') and (self.text(j + 1).isupper() or len(self.text(j + 1)) == 1)

    def bare(self, i, v, parts, nxt, word, case):
        gender = _word_gender(self.text(nxt), int(v) if parts is None else 0, _CI[case]) if word is not None and parts is None else 'm'
        if parts is not None:
            self.emit(decimal_words(int(parts[0]), parts[1], case))
        else:
            self.emit(cardinal(int(v), case, gender))
        self.i = i + 1
        if parts is None:
            self.tail_letters(i + 1)

    def suffix_ordinal(self, i, v, suf):
        case, g = _SUFFIX[suf]
        nxt = self.next_sig(i + 2)
        noun = self.text(nxt) if nxt >= 0 and self.kind(nxt) == 'word' else None
        hint_c, hint_g = noun_hint(noun) if noun else (None, None)
        if suf in ('м', 'ым', 'им'):
            case = 'prep' if self.prep_case(i) and 'prep' in self.prep_case(i) else 'ins'
        if suf == 'ом':
            case = 'prep'
        plural = g == 'p'
        gender = g if g != 'p' else 'm'
        if suf == 'й' and hint_g == 'f':
            case, gender = (self.case_of(i, int(v)) if self.prep_case(i) else 'nom'), 'f'
        if suf in ('е', 'ое') and hint_g == 'p':
            plural = True
        if plural and hint_c:
            case = hint_c
        elif plural and suf == 'х':
            case = 'prep' if self.prep_case(i) and 'prep' in self.prep_case(i) else 'gen'
        self.emit(ordinal(int(v), case, gender, plural))
        self.i = i + 3

    def date_phrase(self, i, d, nxt):
        m = _MONTH_GEN[self.low(nxt)]
        case = self.date_case(i)
        out = f'{ordinal(d, case, "n")} {self.text(nxt)}'
        j = nxt + 1
        y = self.next_sig(nxt)
        if y >= 0 and self.kind(y) == 'num' and self.text(y).isdigit() and 1000 <= int(self.text(y)) <= 2999 and y - nxt <= 2:
            out += f' {ordinal(int(self.text(y)), "gen")}'
            j = y + 1
            g = self.next_sig(y)
            if g >= 0 and self.kind(g) == 'word' and self.low(g) in ('г', 'года', 'год'):
                e = g + 1
                dot = self.adjacent(e, 'ch') and self.text(e) == '.'
                out += ' года'
                j = e + (1 if dot else 0)
                if dot and self.sentence_dot(e):
                    out += '.'
        self.emit(out)
        self.i = j

    def year(self, i, v, nxt, case_word):
        word = self.low(nxt)
        pl = word in ('годы', 'годов', 'годах', 'годам', 'годами')
        self.emit(ordinal(v, case_word, 'm', pl))
        self.i = i + 1

    def year_abbr(self, i, v, nxt, word):
        e = nxt + 1
        dot = self.adjacent(e, 'ch') and self.text(e) == '.'
        if word == 'г' and not (dot and 1000 <= v <= 2200):
            return False
        if v < 100 or v != int(v):
            return False
        if word == 'г':
            nx = self.next_sig(e - 1 + (1 if dot else 0))
        p = self.prep_case(i)
        word_c = {'в': 'prep', 'во': 'prep', 'к': 'dat', 'с': 'gen', 'со': 'gen', 'до': 'gen', 'от': 'gen', 'из': 'gen', 'после': 'gen', 'для': 'gen', 'за': 'acc', 'на': 'acc',
                  'по': 'acc', 'через': 'acc', 'о': 'prep', 'при': 'prep'}
        pw = self.prev_words(i, 1)
        case = word_c.get(pw[0], 'gen' if p and p[0] == 'gen' else 'nom') if pw else 'nom'
        noun = {'nom': 'год', 'acc': 'год', 'gen': 'года', 'prep': 'году', 'dat': 'году', 'ins': 'годом'}[case]
        out = f'{ordinal(int(v), case, "m")} {noun}'
        self.i = e + (1 if dot else 0)
        if dot and self.sentence_dot(e):
            out += '.'
        self.emit(out)
        return True

    def range_(self, i, n, k, m):
        """«5–10», «2020–2022 гг.», «1–5 ноября»; ``k`` is the second number."""
        after = self.next_sig(k)
        w = self.low(after) if after >= 0 and self.kind(after) == 'word' and after - k <= 2 else None
        pc = self.prep_case(i)
        if w in _MONTH_GEN and 1 <= n < m <= 31:
            first = ordinal(n, "gen", "n")
            self.emit(f'{self.s_word(i, first)}{first} по {ordinal(m, "acc", "n")} {self.text(after)}')
            self.i = after + 1
            return True
        if w in ('гг', 'годы', 'годах', 'годов', 'г') and n >= 100:
            e = after + 1 + (1 if self.adjacent(after + 1, 'ch') and self.text(after + 1) == '.' else 0)
            if pc is not None and self.prev_words(i, 1) in (['в'], ['во']) and self.drop_prep():
                pc = None
            if pc is None:
                first = ordinal(n, "gen")
                self.emit(f'{s_prep(first)} {first} по {ordinal(m, "acc")} годы')
            else:
                case = self.one_case(i)
                noun = {'prep': 'годах', 'gen': 'годов', 'dat': 'годам', 'ins': 'годами'}.get(case, 'годы')
                self.emit(f'{ordinal(n, case, "m", True)} {"и" if m == n + 1 else "по"} {ordinal(m, case, "m", True)} {noun}')
            if self.adjacent(e - 1, 'ch') and self.text(e - 1) == '.' and self.sentence_dot(e - 1):
                self.emit('.')
            self.i = e
            return True
        if w in CENTURY_PLURAL and 1 <= n < m <= 40:
            return self.century_range(i, n, m, after)
        unit = self.unit_at(k + 1)
        sep = None
        if unit is None and w is not None and w not in ('и', 'или', 'до', 'по') and (after - k) <= 2:
            noun = self.text(after)
        else:
            noun = None
        if pc is None:
            case = 'gen'
            first = f'от {cardinal(n, case)} до {cardinal(m, case)}'
        else:
            case = self.case_of(i, n, noun)
            first = f'{cardinal(n, case)} {"или" if m == n + 1 else "по"} {cardinal(m, case)}'
        if unit:
            key, adj, end, scale, per = unit
            self.i = end
            noun_words = self.noun_phrase(key, adj, m, _CI[case], scale, per)
            self.emit(first + ' ' + noun_words)
        else:
            self.emit(first)
            self.i = k + 1
        return True

    def noun_phrase(self, key, adj, n, ci, scale, per, plural_gen=False):
        """The unit after a number ``n`` in case index ``ci``: «рублей», «квадратных метра», «тысячи рублей»."""
        out = []
        if scale:
            sg_gender, sg, pl = _SCALES[scale]
            out.append(count_form(n, ci, sg, pl))
            if key:
                nn = NOUNS[key]
                out.append(nn.pl[1])
        else:
            nn = NOUNS[key]
            if adj:
                form = ('mfnp')
                a = _ENDINGS['ий' if adj == 'кубический' else 'ый']
                stem = _ADJ[adj][1]
                last = n % 10
                if last == 1 and n % 100 != 11:
                    out.append(stem + a['m'][ci])
                    out.append(nn.sg[ci])
                elif ci in (0, 3):
                    out.append(stem + a['p'][1] if 2 <= last <= 4 and not 10 < n % 100 < 20 else stem + a['p'][1])
                    out.append(nn.count(n, ci))
                else:
                    out.append(stem + a['p'][ci])
                    out.append(nn.pl[ci])
            else:
                out.append(nn.count(n, ci))
        return ' '.join(out) + (per or '')

    def emit_quantity(self, i, v, parts, key, adj, scale, per, case):
        ci = _CI[case]
        if parts is not None:                                           # a decimal
            digits = parts[1]
            if key and self.money_unit(key) and not scale and key == 'рубль' and len(digits) <= 2 and case in ('nom', 'gen', 'acc', 'dat', 'ins', 'prep'):
                kop = int(digits.ljust(2, '0'))
                if kop == 0:
                    self.emit(f'{cardinal(int(parts[0]), case)} {NOUNS["рубль"].count(int(parts[0]), ci)}')
                    return
                self.emit(f'{cardinal(int(parts[0]), case)} {NOUNS["рубль"].count(int(parts[0]), ci)} {cardinal(kop, case, "f")} {NOUNS["копейка"].count(kop, ci)}')
                return
            words = decimal_words(int(parts[0]), digits, case)
            if scale:
                tail = _SCALES[scale][1][1] + (' ' + NOUNS[key].pl[1] if key else '')
            elif key:
                nn = NOUNS[key]
                tail = (((_ADJ[adj][1] + _ENDINGS['ый' if adj == 'квадратный' else 'ий']['m'][1]) + ' ') if adj else '') + nn.sg[1]
            else:
                tail = ''
            self.emit((words + ' ' + tail).strip() + (per or ''))
            return
        n = int(v)
        if scale and n >= 1000:                                           # «18 329 тыс. руб.»: said as the whole number, never «тысяч … тысяч»
            n, scale = n * 1000 ** scale, 0
            self.emit(cardinal(n, case, NOUNS[key].gender if key else 'm') + (f' {NOUNS[key].count(n, ci)}' if key else ''))
            return
        if scale:
            gender = _SCALES[scale][0]
            words = ('' if (n == 1 and scale == 1) else cardinal(n, case, gender) + ' ') + count_form(n, ci, _SCALES[scale][1], _SCALES[scale][2])
            if key:
                words += ' ' + NOUNS[key].pl[1]
            self.emit(words + (per or ''))
            return
        nn = NOUNS[key]
        gender = nn.gender
        if adj:
            gender = NOUNS[key].gender
        self.emit(f'{cardinal(n, case, gender)} {self.noun_phrase(key, adj, n, ci, 0, per)}')

    # -- words --------------------------------------------------------------------------------------------------------------------------------------------
    def dot_after(self, j):
        return self.adjacent(j, 'ch') and self.text(j) == '.'

    def finish_abbr(self, text, end):
        """Emit the expansion of an abbreviation that ends at token ``end-1``; a dot after it stays when a sentence ends there."""
        dot = self.dot_after(end)
        self.emit(text)
        self.i = end + (1 if dot else 0)
        if dot and self.sentence_dot(end):
            self.emit('.')

    def word(self):
        i, w = self.i, self.text(self.i)
        low = w.lower()
        nxt = self.next_sig(i)
        # т.е. т.д. т.п. т.к.
        if low == 'т' and self.dot_after(i + 1):
            k = i + 2
            if self.kind(k) == 'sp':
                k += 1
            if self.adjacent(k, 'word') and self.low(k) in ('е', 'д', 'п', 'к', 'н') and self.dot_after(k + 1):
                said = {'е': 'то есть', 'д': 'так далее', 'п': 'тому подобное', 'к': 'так как', 'н': 'так называемый'}[self.low(k)]
                return self.finish_abbr(said, k + 1)
        if low in ('и', 'а') and nxt >= 0 and self.low(nxt) in ('др', 'пр') and self.dot_after(nxt + 1):
            self.emit(w + ' ')
            self.finish_abbr('другие' if self.low(nxt) == 'др' else 'прочее', nxt + 1)
            return
        if low in _REF_ABBR and self.dot_after(i + 1) or (low in _REF_SURFACE and not w.islower() or low in _REF_SURFACE):
            if self.reference(i, low):
                return
        if low in CODES and w.isupper():
            return self.code(i, low)
        if low == 'рф' and w.isupper():
            self.emit('Российской Федерации')
            self.i = i + 1
            return
        if w.isascii():
            return self.latin_word(i, w)
        if w.isupper() and len(w) >= 2:
            self.emit(_unabbrev(w))
            self.i = i + 1
            return
        if low in _ABBR and self.dot_after(i + 1):
            self.acc = _ABBR[low] == 'счёт'
            return self.finish_abbr(_ABBR[low], i + 1)
        if low == 'г' and self.dot_after(i + 1) and nxt >= 0 and self.kind(nxt) == 'word' and self.text(nxt)[:1].isupper():
            return self.finish_abbr('город', i + 1)
        if low in ('км', 'м') and self.adjacent(i + 1, 'ch') and self.text(i + 1) == '/' and self.adjacent(i + 2, 'word') and self.low(i + 2) in ('ч', 'с'):
            self.emit({('км', 'ч'): 'километров в час', ('м', 'с'): 'метров в секунду'}.get((low, self.low(i + 2)), w))
            self.i = i + 3
            return
        if low in _ACC_WORDS:
            self.acc = True
        elif low not in ('и', 'или'):
            self.acc = False
        self.emit(w)
        self.i = i + 1

    def reference(self, i, low):
        """«ст. 15», «п. 2», «в статье 15»: the head noun in its case and the number as an ordinal that agrees with it."""
        abbr = low in _REF_ABBR and self.dot_after(i + 1)
        end = i + (2 if abbr else 1)
        k = self.next_sig(end - 1)
        if k < 0 or self.kind(k) != 'num' or k - end > 1:
            return False
        s = self.text(k)
        if self.adjacent(k + 1, 'word') or (self.adjacent(k + 1, 'ch') and self.text(k + 1) in '/:'):
            return False
        if abbr:
            lemma, plural = _REF_ABBR[low], False
            case = 'gen' if self.prev_ref >= 0 and i - self.prev_ref <= 1 else self.one_case(i)
        else:
            lemma, case, plural = _REF_SURFACE[low]
        items, j = [k], k                                    # a list «ст. 15 и 16», «пункты 2, 3»
        while s.isdigit():
            m = self.next_sig(j)
            if m < 0 or not ((self.kind(m) == 'ch' and self.text(m) == ',') or (self.kind(m) == 'word' and self.low(m) in ('и', 'или'))):
                break
            m2 = self.next_sig(m)
            if m2 < 0 or self.kind(m2) != 'num' or not self.text(m2).isdigit() or self.adjacent(m2 + 1, 'word') or (self.adjacent(m2 + 1, 'ch') and self.text(m2 + 1) in '-/:') or self.unit_at(m2 + 1) is not None:
                break
            items.append(m2)
            j = m2
        span = None                                           # «ст. 419–431»
        d = self.next_sig(j) if s.isdigit() and len(items) == 1 else -1
        if d >= 0 and self.kind(d) == 'ch' and self.text(d) in '-–—−':
            d2 = self.next_sig(d)
            if d2 >= 0 and self.kind(d2) == 'num' and self.text(d2).isdigit() and int(self.text(d2)) > int(s) and not self.adjacent(d2 + 1, 'word'):
                span = d2
        listing = len(items) > 1 or span is not None
        noun = NOUNS[lemma]
        if abbr:
            head = (noun.pl if listing else noun.sg)[_CI[case]]
            if self.text(i)[:1].isupper():
                head = head[:1].upper() + head[1:]
        else:
            head = self.text(i)
        if span is not None:
            a, b = int(s), int(self.text(span))
            first = ordinal(a, "gen", noun.gender) if lemma not in ('форма', 'приказ') else cardinal(a)
            body = f'{s_prep(first)} {first} по {ordinal(b, "acc", noun.gender) if lemma not in ("форма", "приказ") else cardinal(b)}'
            j = span
        elif listing:
            body = cardinal(int(self.text(items[0])))
            for prev, x in zip(items, items[1:]):
                gap = ''.join(t for _, t in self.toks[prev + 1:x]).lower()
                body += (' и ' if 'и' in gap and 'или' not in gap else ' или ' if 'или' in gap else ', ') + cardinal(int(self.text(x)))
        elif '.' in s or ',' in s:
            body = ' точка '.join(digits_spoken(p) if len(p) > 1 and p[0] == '0' else cardinal(int(p)) for p in re.split(r'[.,]', s))
        elif len(s) > 1 and s[0] == '0' or len(s) >= 9:
            body = digits_spoken(s)
        elif s == '0':
            body = 'ноль'
        elif lemma in ('форма', 'приказ'):
            body = cardinal(int(s))
        else:
            body = ordinal(int(s), case, noun.gender, plural)
        self.emit(head + ' ' + body)
        self.i = j + 1
        self.prev_ref = self.i
        return True

    def code(self, i, low):
        """«НК РФ» -> «Налоговый кодекс» in the case the sentence asks for (genitive right after «ст. 15»)."""
        adj, kind, noun = CODES[low]
        case = 'gen' if self.prev_ref >= 0 and i - self.prev_ref <= 1 else self.one_case(i)
        ci = _CI[case]
        k = self.next_sig(i)
        end = k + 1 if k >= 0 and self.kind(k) == 'word' and self.text(k) == 'РФ' else i + 1
        if low == 'коап':
            out = ('Кодекс', 'Кодекса', 'Кодексу', 'Кодекс', 'Кодексом', 'Кодексе')[ci] + ' об административных правонарушениях'
        else:
            out = ' '.join(a + _ADJ_END[kd][ci] for a, kd in adj) + ' ' + ('кодекс', 'кодекса', 'кодексу', 'кодекс', 'кодексом', 'кодексе')[ci]
        self.emit(out)
        self.i = end

    def latin_word(self, i, w):
        k = i + 1
        if len(w) <= 2 and self.adjacent(k, 'num') and self.text(k).isdigit():
            self.emit(' '.join(_LAT_RU.get(c.lower(), c) for c in w) + ' ' + cardinal(int(self.text(k))))
            self.i = k + 1
            return
        if w == 'N' and self.next_sig(i) >= 0 and self.kind(self.next_sig(i)) == 'num':
            self.emit('номер')
            self.i = i + 1
            return
        roman = _roman(w)
        if roman and self.roman_range(i, roman):
            return
        if roman and self.roman_context(i):
            return self.roman(i, roman)
        if len(w) == 1:
            self.emit(_LAT_RU.get(w.lower(), w))
            self.i = i + 1
            return
        self.emit(latin(w))
        self.i = i + 1

    def roman_range(self, i, first):
        """«XIII–XV веках»: two roman ends, a dash between, a plural century after (U16-S8)."""
        if not (self.adjacent(i + 1, 'ch') and self.text(i + 1) in _DASHES and self.kind(i + 2) == 'word' and self.text(i + 2).isascii()):
            return False
        last = _roman(self.text(i + 2))
        after = self.next_sig(i + 2)
        if not (last and 1 <= first < last <= 40 and after >= 0 and self.kind(after) == 'word' and self.low(after) in CENTURY_PLURAL):
            return False
        return self.century_range(i, first, last, after)

    def roman_context(self, i):
        nxt = self.next_sig(i)
        prev = self.prev_words(i, 1)
        century = CENTURY_FORMS      # U16-S8
        return (nxt >= 0 and self.kind(nxt) == 'word' and self.low(nxt) in (*century, 'в', 'квартал', 'квартала', 'квартале')) or \
            bool(prev and prev[0] in ('глава', 'главе', 'раздел', 'разделе', 'часть', 'части', 'этап', 'этапе', 'квартал', 'квартале', 'гл', 'разд', 'ч'))

    def roman(self, i, value):
        nxt = self.next_sig(i)
        w = self.low(nxt) if nxt >= 0 and self.kind(nxt) == 'word' else ''
        hint = _SURFACES.get(w, ())
        if w in CENTURY_PLURAL and hint:
            self.emit(ordinal(value, CASES[hint[0][1]], 'm', True))
            self.i = i + 1
            return
        if hint and hint[0][2] == 0:
            key, ci, _ = hint[0]
            self.emit(ordinal(value, CASES[ci], NOUNS[key].gender))
            self.i = i + 1
            return
        prev = self.prev_words(i, 1)
        ref = _REF_SURFACE.get(prev[0]) if prev else None
        gender = NOUNS[ref[0]].gender if ref else 'm'
        case = ref[1] if ref else 'nom'
        self.emit(ordinal(value, case, gender))
        self.i = i + 1
        if w == 'в' and self.dot_after(nxt + 1):
            self.i = i + 1

    # -- characters ---------------------------------------------------------------------------------------------------------------------------------------
    def char(self):
        i, c = self.i, self.text(self.i)
        self.i = i + 1
        nxt_num = self.kind(i + 1) == 'num'
        before = ''.join(self.out)
        at_start = not before.strip() or before[-1:] in ' \x01(«"' or before.rstrip()[-1:] in '(,:;'
        if c in _QUOTES:
            return
        if c in '([{':
            self.emit(_SOFT)
            return
        if c in ')]}':
            self.emit(_SOFT)
            return
        if c in '—–−-' or c == '‒':
            spaced_l = self.kind(i - 1) == 'sp' or i == 0
            if nxt_num and at_start and c in '-−–' and not (self.acc):
                self.emit('минус ')
                return
            if self.kind(i - 1) in ('word', 'num') and self.kind(i + 1) in ('word', 'num') and c == '-':
                self.emit(_SOFT if self.kind(i - 1) == 'num' and self.kind(i + 1) == 'num' else ' ')
                return
            self.emit(_SOFT)
            return
        if c == '…':
            self.emit('\x02')
            return
        if c == '.' and self.adjacent(i + 1, 'ch') and self.text(i + 1) == '.':
            j = i
            while self.adjacent(j, 'ch') and self.text(j) == '.':
                j += 1
            self.i = j
            self.emit('\x02' if j - i >= 3 else '.')
            return
        if c == '%':
            self.emit(' процент ')
            return
        if c in '₽€$£' and nxt_num and self.text(i + 1).isdigit():
            key = {'₽': 'рубль', '€': 'евро', '$': 'доллар', '£': 'фунт'}[c]
            n = int(self.text(i + 1))
            case = self.case_of(i, n)
            self.emit(f'{cardinal(n, case, NOUNS[key].gender)} {NOUNS[key].count(n, _CI[case])}')
            self.i = i + 2
            return
        if c in '₽€$£':
            self.emit(' ' + {'₽': 'рубль', '€': 'евро', '$': 'доллар', '£': 'фунт'}[c] + ' ')
            return
        if c in '№#':
            k = self.next_sig(i - 1)
            if k >= 0 and self.kind(k) == 'num':
                self.emit('номер ')
                return
            self.emit(' номер ' if c == '№' else ' решётка ')
            return
        if c == '/':
            if self.kind(i - 1) == 'word' and self.kind(i + 1) == 'word':
                self.emit(' или ' if not (self.low(i - 1) == 'и' and self.low(i + 1) == 'или') else ' ')
                return
            self.emit(' ')
            return
        if c == ':' and self.kind(i - 1) == 'num' and self.kind(i + 1) == 'word' and self.text(i + 1).isascii():
            self.emit(' двоеточие ')
            return
        if c == '^':
            self.emit(' в степени ')
            return
        if c == '~':
            self.emit(' около ' if nxt_num else ' ')
            return
        if c in SYMBOLS:
            if c == '+' and nxt_num and at_start and not before.rstrip()[-1:].isalnum():
                self.emit('плюс ')
            else:
                self.emit(' ' + SYMBOLS[c] + ' ')
            return
        if c in '.,;:!?':
            if c in '.:;!?':
                self.acc = False if c in ':;!?.' else self.acc
            self.emit(c)
            return
        if c in '²³':
            self.emit(' в квадрате ' if c == '²' else ' в кубе ')
            return
        if c in '|\\_*':
            self.emit(' ')
            return
        if c.isspace():
            self.emit(' ')
            return
        # anything else (emoji, control marks) is dropped, a plain word character is kept
        if c.isalnum():
            self.emit(c)

    # -- clean up -----------------------------------------------------------------------------------------------------------------------------------------
    def clean(self, text):
        text = re.sub(r'\x02\s*(?=[а-яёa-z])', '\x01', text)
        text = text.replace('\x02', '.')
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'(?:\s*\x01)+\s*', '\x01', text)
        text = re.sub(r'\x01+(?=\s*[.,;:!?])', '', text)
        text = re.sub(r'(?:\s*\x01)+\s*$', '', text)
        text = re.sub(r'\s*,(?:\s*,)+', ',', text)
        text = text.replace(_SOFT, ', ')
        text = re.sub(r'\s+([.,;:!?])', r'\1', text)
        text = re.sub(r',\s*([.;:!?])', r'\1', text)
        text = re.sub(r'([.,;:!?]){2,}', lambda m: m.group(0)[-1] if m.group(0)[-1] in '.!?' else m.group(0)[0], text)
        text = re.sub(r'^[\s,;:]+', '', text)
        text = re.sub(r'([.,;:!?])(?=[А-Яа-яЁёA-Za-z])', r'\1 ', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()


_ABBR = {'напр': 'например', 'см': 'смотри', 'рис': 'рисунок', 'табл': 'таблица', 'стр': 'страница', 'гл': 'глава', 'разд': 'раздел', 'абз': 'абзац', 'прим': 'примечание',
         'ред': 'редакция', 'вкл': 'включительно', 'руб': 'рублей', 'коп': 'копеек', 'тыс': 'тысяч', 'млн': 'миллионов', 'млрд': 'миллиардов', 'трлн': 'триллионов',
         'ул': 'улица', 'сч': 'счёт', 'обл': 'область', 'им': 'имени', 'гг': 'годы', 'пр': 'прочее', 'др': 'другие', 'ст': 'статья', 'п': 'пункт', 'ч': 'часть', 'подп': 'подпункт',
         'пп': 'подпункт', 'шт': 'штук', 'чел': 'человек', 'экз': 'экземпляров', 'проц': 'процентов', 'ф': 'фамилия', 'кв': 'квартира', 'д': 'дом', 'тел': 'телефон',
         'нач': 'начало', 'доп': 'дополнительно', 'орг': 'организация', 'сумм': 'сумма', 'мес': 'месяцев', 'дн': 'дней', 'гос': 'государственный', 'бух': 'бухгалтерский'}


def _phone_words(m):
    head = {'+7': 'плюс семь', '7': 'семь', '8': 'восемь'}[m.group(1)]
    return head + ', ' + ', '.join(digits_spoken(g) for g in m.groups()[1:]).replace(',  ', ', ')


# E89: SAPI reads a grouped number digit group by digit group: «40 000» is «сорок ноль ноль ноль» (WAV checked on the laptop, 5 Nov 17:15); «40000» is «сорок тысяч». The groups of one number
# (1-3 digits, then groups of exactly three after a space, a no-break or a thin space, as the portioner keeps them together) go to the synthesizer whole. The portion and its ACK keep the text as it was.
_GROUPED_NUMBER=re.compile(r'(?<![\d.,])(\d{1,3})((?:[    ]\d{3})+)(?![\d])')

_CENTURY=re.compile(r'(?<!\w)((?:(?i:в|с|по|до|к|от|из|на)\s+)?)([IVX]+)(?:\s*[-–—]\s*|\s+(?i:по|до)\s+)([IVX]+)\s+(?:век\w*|вв?\.)')

def _centuries(found):
    """h31 (F24): two centuries are a range, whatever the two: «в XIII-XV веках», «XIII-XV вв.», «с XIII по XV век» -> «с тринадцатого по пятнадцатый век». «в», «с», «от» before it are the range's own «с»."""
    head,first,last=found.group(1).strip(),found.group(2).upper(),found.group(3).upper()
    low=_speak_words(f'с {first} века').removeprefix('с ').removesuffix(' века')
    high=_speak_words(f'{last} век').removesuffix(' век')
    if low.split()[0]==first or high.split()[0]==last:       # a numeral the speech does not know: left as it was
        return found.group(0)
    kept=f'{head} ' if head and head.casefold() not in ('в','с','от') else ''
    text=f'{kept}с {low} по {high} век'
    return text[0].upper()+text[1:] if found.group(1)[:1].isupper() else text

def _whole_numbers(text):
    """E89: ``text`` with every grouped number written whole and a range of centuries in words, for the voice only (the first step of ``speak``). h29: a Roman century in words: the voice spelled «XIII-XV» letter by letter (the call of 20:29)."""
    text=_CENTURY.sub(_centuries,str(text))
    text=re.sub(r'(?<!\w)(?:(?:в|с|по|до|к|от|из|на)\s+)?[IVX]+\s+век\w*',lambda found:_speak_words(found.group(0)),text)
    return _GROUPED_NUMBER.sub(lambda found:found.group(1)+re.sub(r'\D','',found.group(2)),text)


_IMAGE_MARK = re.compile(r'\[(?:рисунок|формула)\]', re.I)      # law-speak: the base puts it where a picture or a formula was (the page's <img>); the voice says so, it does not read «рисунок»
IMAGE_SAID = 'здесь рисунок или формула, их нет в тексте'


def speak(text):
    """The ONE text for the voice (tts-render): every digit, symbol, abbreviation, grouped number and range of centuries brought to words. Idempotent: the result has nothing left to bring.

    The ONE decision of what is said in which language lives here: a run of English (``lang_hint.english_runs``) is the English voice's own and stays as written (the worker puts it inside its ``<voice>``); before this the text was brought to Russian letters first
    («What is the risk» -> «вхат ай эс те риск») and the English voice never got a word. A single Latin word inside Russian speech is part of the Russian run and is spoken in Russian letters as before."""
    if not text:
        return text or ''
    text = _IMAGE_MARK.sub(IMAGE_SAID, str(text))      # law-speak: the mark of a picture is said in words
    english = english_runs(text)
    if not english:
        return _speak_words(_whole_numbers(text))
    runs, pieces, pos = [], [], 0
    for start, end in english:      # each run leaves the Russian rules as one letters-only word that no rule touches and comes back as it was written
        pieces += [text[pos:start], f'ъъ{chr(ord("а") + len(runs) // 32)}{chr(ord("а") + len(runs) % 32)}ъъ']
        runs.append(text[start:end])
        pos = end
    said = _speak_words(_whole_numbers(''.join(pieces) + text[pos:]))
    return re.sub('ъъ([а-я])([а-я])ъъ', lambda m: runs[(ord(m.group(1)) - ord('а')) * 32 + ord(m.group(2)) - ord('а')], said)


def _speak_words(text):
    if not text:
        return text or ''
    text = re.sub(r'\.{3,}', '…', str(text)).translate(_SPACES)
    text = _PHONE.sub(lambda m: ' ' + _phone_words(m) + ' ', text)
    return _Engine(text).run()


# -- the check: the numbers of the text against the numbers of the speech -----------------------------------------------------------------------------------
_SCALE_WORDS = {'тыс': 10 ** 3, 'млн': 10 ** 6, 'млрд': 10 ** 9, 'трлн': 10 ** 12}
_SCALE_VALUES = {w: 10 ** (3 * s) for s, (_, sg, pl) in _SCALES.items() for w in sg + pl}
_NUMTOK = re.compile(r'\d+(?:[.,]\d+)*|[А-Яа-яЁёA-Za-z]+|[^\sА-Яа-яЁёA-Za-z\d]')


def numbers_of(text):
    """The numbers written or spoken in ``text``, in order: digits (grouped, decimal, dotted, scaled by «тыс.» / «тысяч»), number words, month names, Roman numerals of a century."""
    global _VOCAB, _DEN
    if _VOCAB is None:
        _VOCAB, _DEN = _vocab(), _den_words()
    text = text.translate(_SPACES)
    pieces, pos = [], 0
    for m in _PHONE.finditer(text):
        pieces += [text[pos:m.start()], [Decimal(c) for c in ''.join(m.groups()) if c.isdigit()]]
        pos = m.end()
    if pieces:
        pieces.append(text[pos:])
        out = []
        for piece in pieces:
            out.extend(piece if isinstance(piece, list) else numbers_of(piece))
        return out
    text = _GROUPS.sub(lambda m: m.group(1).replace(' ', ''), text)
    toks = _NUMTOK.findall(text)
    out, words, i, n = [], [], 0, len(toks)

    def flush():
        if words:
            out.extend(_runs([w.lower() for w in words]))
            words.clear()

    def digits(t, after):
        if t.isdigit():
            if len(t) >= 9 or (len(t) > 1 and t[0] == '0'):
                return [Decimal(c) for c in t]
            return [Decimal(t)]
        if '.' in t and ',' not in t:
            parts = t.split('.')
            if len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[2]) in (2, 4) and 1 <= int(parts[0]) <= 31 and 1 <= int(parts[1]) <= 12:
                return [Decimal(int(parts[0])), Decimal(int(parts[1])), Decimal(int(parts[2]) + (2000 if len(parts[2]) == 2 else 0))]
            return [x for p in parts for x in digits(p, '')]
        if t.count(',') == 1:
            a, b = t.split(',')
            if after and len(b) <= 2 and int(b) and after.lower() in ('руб', '₽', 'рублей', 'рубля', 'рубль', 'р'):
                return [Decimal(a), Decimal(b.ljust(2, '0'))]
            return [Decimal(a + '.' + b)]
        return [x for p in t.split(',') for x in digits(p, '')]
    while i < n:
        t = toks[i]
        if t[0].isdigit():
            flush()
            vals = digits(t, toks[i + 1] if i + 1 < n else '')
            j = i + 1
            if len(vals) == 1 and j < n:
                nxt = toks[j].lower()
                if nxt in _SCALE_WORDS or nxt in _SCALE_VALUES:
                    vals = [vals[0] * (_SCALE_WORDS.get(nxt) or _SCALE_VALUES[nxt])]
                    j += 1
                    if j < n and toks[j] == '.':
                        j += 1
                elif nxt == ':' and j + 1 < n and toks[j + 1] == '00' and not (j + 2 < n and toks[j + 2] == ':'):
                    j += 2
            out.extend(vals)
            i = j
        elif t.lower() in _MONTH_VAL:
            flush()
            out.append(Decimal(_MONTH_VAL[t.lower()]))
            i += 1
        elif t.isalpha():
            if t.isascii() and _roman(t) and i + 1 < n and toks[i + 1].lower() in ('век', 'века', 'веке', 'веку', 'веком'):
                flush()
                out.append(Decimal(_roman(t)))
            else:
                words.append(t)
            i += 1
        else:
            flush()
            i += 1
    flush()
    return out

# -- law-speak (tts-render): how the voice says an official title and an article number, and the «ё» of the table kb_yo ---------------------------------------------------
_YO_TABLE = []


def _yo_table():
    if not _YO_TABLE:
        try:
            from importlib import import_module
            _YO_TABLE.append(import_module('.kb_yo', __package__).YO)
        except Exception:
            _YO_TABLE.append({})
    return _YO_TABLE[0]


_PROPER = ('Росси', 'Евразийск', 'Москв', 'Санкт', 'Севастопол', 'Байконур')
_QUOTED = re.compile(r'"([^"]+)"')
_TRAILING_BRACKET = re.compile(r'\s*\(([^()]*)\)\s*$')
_BRACKET = re.compile(r'\s*\(([^()]*)\)')
_CYRILLIC_WORD = re.compile(r'[А-Яа-яЁё]+')


def put_yo(text):
    """«ё» where the table ``kb_yo`` has it (the voice stresses «всё» / «все» by it)."""
    table = _yo_table()

    def _put(match):
        word = match.group(0)
        fixed = table.get(word.lower())
        if fixed is None:
            return word
        return fixed[0].upper() + fixed[1:] if word[0].isupper() else fixed

    return _CYRILLIC_WORD.sub(_put, text)


def title_said(title):
    """The official title as part of a spoken sentence: «ё» restored, quotes and brackets spoken, no capital letter."""
    text = title.strip().rstrip('.').strip()
    text = _QUOTED.sub(lambda match: '«' + match.group(1) + '»', text)
    text = _TRAILING_BRACKET.sub(lambda match: ', ' + match.group(1), text)
    text = _BRACKET.sub(lambda match: ', ' + match.group(1) + ',', text)
    text = re.sub(r',\s*,', ',', text).replace(' ,', ',')
    text = put_yo(text)
    first = text.split(' ', 1)[0]
    if text and not (len(first) > 1 and first.isupper()) and not first.startswith(_PROPER):
        text = text[0].lower() + text[1:]
    return text


def article_said(key):
    """The number of an article for the voice: «15-1» is «15 дефис 1»."""
    return key.replace('-', ' дефис ')
