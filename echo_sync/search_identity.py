"""a3-search / R10: which document and article a source row is about, and when a question is the same by meaning.

``identity(query, row)``: ``match`` (everything the question names - code or law, article - the row confirms), ``document`` / ``article`` (the row is about another code or law, or another
article: a Labour Code row with article 19 is no answer to the Tax Code's article 19, whatever stems it shares), ``repealed`` (the row says it has lost force), ``unknown`` (the row names neither).
``same_meaning(a, b)``: the early preparation of one question may serve another that says it differently («что в статье 19 НК РФ» / «что говорится в девятнадцатой статье Налогового кодекса»); numbers in
their order with the word after them, every «не» with the word it negates, and the content lemmas (synonym-free apart from the table below) must agree. No embeddings here: that step is the laptop's.
Pure functions, no network; every failure answers «not the same» / ``unknown``.
"""
from __future__ import annotations

import re

from . import reference_kb as rk
from . import ru_numbers as numbers

_CODES = (('nk', r'налогов\w*\s+кодекс|\bнк\b'), ('gk', r'гражданск\w*\s+кодекс|\bгк\b'), ('tk', r'трудов\w*\s+кодекс|\bтк\b'), ('uk', r'уголовн\w*\s+кодекс|\bук\b'),
          ('koap', r'коап|кодекс\w*\s+об\s+административн\w*\s+правонарушен\w*'), ('sk', r'семейн\w*\s+кодекс|\bск\b'), ('zhk', r'жилищн\w*\s+кодекс|\bжк\b'),
          ('zk', r'земельн\w*\s+кодекс|\bзк\b'), ('konst', r'конституци\w*'))
_LAW_NUMBER = re.compile(r'(?<!\d)(\d{1,4}(?:-\d)?)\s*-?\s*фз|фз\s*-?\s*(\d{1,4}(?:-\d)?)')
_LAW_TOPIC = re.compile(r'закон\w*\s+(?:рф\s+|российской\s+федерации\s+)?(?:о|об)\s+([а-я]+)(?:\s+([а-я]+))?(?:\s+([а-я]+))?')
_LAW_ALIASES = {'152': 'персональн', '2300-1': 'потребител', '38': 'реклам', '44': 'закупк', '115': 'легализац', '273': 'противодейств', '402': 'бухгалтерск', '127': 'несостоятельн'}
_LAW_SKIP = frozenset('защите защита защиту прав праве правах'.split())
_ABBREVIATIONS = (('нк рф', 'налоговый кодекс'), ('гк рф', 'гражданский кодекс'), ('тк рф', 'трудовой кодекс'), ('нк', 'налоговый кодекс'), ('гк', 'гражданский кодекс'), ('тк', 'трудовой кодекс'),
                  ('ук', 'уголовный кодекс'), ('ндс', 'налог на добавленную стоимость'), ('ндфл', 'налог на доходы физических лиц'))
_REPEALED = re.compile(r'утрати\w+\s+силу|не\s+действу\w+|исключен\w*\s+федеральным')
_IGNORABLE = frozenset('говориться быть являться значить такой сказать подсказать рассказать рассказывать объяснить пожалуйста слушать слушай скажи подскажи ну вот итак короче значит сейчас получаться выйти получиться'.split())
_SYNONYMS = {'истратить': 'потратить', 'израсходовать': 'потратить', 'остаться': 'остаться', 'получиться': 'быть', 'стоить': 'стоимость', 'цена': 'стоимость', 'размер': 'ставка'}
_NEGATIONS = frozenset({'не', 'нет', 'ни'})
_REFERENCE_WORDS = frozenset({'статья', 'пункт', 'глава', 'счет', 'часть', 'раздел'})   # «статья 19» and «19-я статья» are one reference
_FROM = frozenset({'из', 'от', 'с', 'со'})      # E87.1: the two ends of a road (the role a place has in the question): where from, where to
_TO = frozenset({'в', 'во', 'до', 'на', 'к', 'ко'})


def _low(text):
    return re.sub(r'\s+', ' ', str(text or '').lower().replace('ё', 'е'))


def documents(text):
    """The codes and laws a text names, as a frozenset of keys."""
    low, found = _low(text), set()
    for key, pattern in _CODES:
        if re.search(pattern, low):
            found.add(key)
    for match in _LAW_NUMBER.finditer(low):
        number = match.group(1) or match.group(2)
        found.add('law:' + _LAW_ALIASES.get(number, number))
    for match in _LAW_TOPIC.finditer(low):
        words = [w for w in match.groups() if w and w not in _LAW_SKIP]
        for word in words[:2]:
            found.add('law:' + word[:7 if word.startswith('персональн') else 9])
    return frozenset(found), []


def _docs(text):
    keys, _ = documents(text)
    return frozenset(_norm_law(k) for k in keys)


def _norm_law(key):
    for alias in _LAW_ALIASES.values():
        if key.startswith('law:') and alias.startswith(key[4:]) or key == 'law:' + alias:
            return 'law:' + alias
    return key


def articles(text):
    """The articles a text names («статья 19», «19-я статья», «ст. 105.1»), as a frozenset of keys."""
    try:
        low = _low(text)
        tokens = rk._TOKEN.findall(numbers.merge_digit_groups(low))[:400]
        out = set()
        for mention in rk._mentions(tokens):
            for keyword in rk._keywords(tokens):
                if keyword[0] == 'article' and rk._adjacent(tokens, mention, keyword) is not None:
                    out.add(str(mention.key))
        return frozenset(out)
    except Exception:  # noqa: BLE001
        return frozenset()


def _row_text(row):
    return ' '.join(str(row.get(key) or '') for key in ('title', 'text')) if isinstance(row, dict) else str(row or '')


def identity(query, row):
    try:
        asked_docs, asked_arts = _docs(query), articles(query)
        if not asked_docs and not asked_arts:
            return 'unknown'
        text = _row_text(row)
        docs, arts = _docs(text), articles(text)
        if asked_docs and docs and not asked_docs & docs:
            return 'document'
        if asked_arts and arts and not asked_arts & arts:
            return 'article'
        confirmed = (not asked_docs or bool(asked_docs & docs)) and (not asked_arts or bool(asked_arts & arts))
        if not confirmed:
            return 'unknown'
        if _REPEALED.search(_low(text)) and len(arts) <= 1:
            return 'repealed'
        return 'match'
    except Exception:  # noqa: BLE001
        return 'unknown'


# -- same meaning ------------------------------------------------------------------------------------------------

def _atoms(text):
    from .ru_alignment import _canonical, _lemma
    low = _low(text)
    for short, full in _ABBREVIATIONS:
        low = re.sub(r'(?<![\w-])' + short + r'(?![\w-])', full, low)
    low = re.sub(r'(?<![\w-])(?:рф|российской федерации|российский)(?![\w-])', ' ', low)
    return [a for a in _canonical(low, ()) if a], _lemma


def _content(text):
    from .textutil import FUNCTION_WORDS, STOPWORDS
    atoms, _ = _atoms(text)
    out = []
    for atom in atoms:
        if atom in _NEGATIONS or atom.startswith('#') or not atom.isalpha():
            out.append(atom)
        elif atom not in STOPWORDS and atom not in FUNCTION_WORDS and atom not in _IGNORABLE:
            out.append(_SYNONYMS.get(atom, atom))
    return out


def _protected(atoms):
    """Numbers and symbols in order with the word after each; every «не» with the word it negates."""
    key = []
    for i, atom in enumerate(atoms):
        following = next((a for a in atoms[i + 1:] if a not in _NEGATIONS and not a.startswith('#') and a.isalpha()), None)
        if atom.startswith('#'):
            near = [a for a in (atoms[i - 1] if i else None, atoms[i + 1] if i + 1 < len(atoms) else None) if a in _REFERENCE_WORDS]
            key.append((atom, near[0] if near else following))
        elif atom in _NEGATIONS:
            key.append(('не', following))
        elif not atom.isalpha():
            key.append((atom, None))
    return key


def _ends(text):
    """E87.1: the role of each word that stands after «из / от / с» ('from') or «в / до / на / к» ('to'): «из Москвы в Питер» and «из Питера в Москву» have the same words and are two questions.
    A word with no such preposition has no role (a paraphrase may drop it); only two roles that DIFFER for the same word refuse (``same_meaning``)."""
    roles, pending = {}, None
    for atom in _atoms(text)[0]:
        if atom in _FROM:
            pending = 'from'
        elif atom in _TO:
            pending = 'to'
        elif atom.isalpha():
            if pending:
                roles.setdefault(atom, pending)
            pending = None
    return roles


def _lcs(a, b):
    row = [0] * (len(b) + 1)
    for x in a:
        prev = 0
        for j, y in enumerate(b, 1):
            cur = row[j]
            row[j] = prev + 1 if x == y else max(row[j], row[j - 1])
            prev = cur
    return row[-1]


def _tenses(text):
    """Tense of every finite verb (a lemma alone erases it: «устанавливает» / «устанавливала» are two questions)."""
    from . import ru_alignment as ru
    out = []
    for word in re.findall(r'[а-я]+', _low(text)):
        ru._lemma(word)
        with ru._LOCK:
            tag = ru._MORPH.parse(word)[0].tag
        if tag.POS == 'VERB' and tag.tense and ru._lemma(word) not in _IGNORABLE:
            out.append(tag.tense)
    return sorted(out)


def same_meaning(a, b):
    try:
        if _tenses(a) != _tenses(b):
            return False
        left, right = _content(a), _content(b)
        if not left or not right or _protected(left) != _protected(right):
            return False
        words = lambda atoms: [x for x in atoms if x not in _NEGATIONS and not x.startswith('#') and x.isalpha()]
        wl, wr = words(left), words(right)
        if sorted(wl) != sorted(wr):
            return False
        ends_a, ends_b = _ends(a), _ends(b)
        if any(ends_a[w] != ends_b[w] for w in ends_a.keys() & ends_b.keys()):
            return False
        from .fast_text import same_roles      # noqa: PLC0415 - E87.1: persons, cases, modals, question words and «не»: the one table of E87 (A2) tells them, not a second rule here
        if not same_roles(a, b):
            return False
        return wl == wr or _lcs(wl, wr) >= len(wl) - 1
    except Exception:  # noqa: BLE001
        return False
