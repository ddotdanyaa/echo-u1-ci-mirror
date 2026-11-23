"""ONE place of the spoken abbreviations (speech: abbrev-expand; w9-map N136, E17.1). Three copies of the one rule lived in three files: the stock expander
of the portioner (the FIRST occurrence in EACH answer), the controller's once-per-call wrapper of it, and a table of how the question lead writes the codes
(``question_lead._ABBR``). All three are here now:

* ``expand_abbreviations``: the mechanism, the FIRST occurrence of every key of the profile's table replaced by its full term (unless the answer spelled
  it out before). The portioner's ``_plan`` asks it for an answer that is not spoken text yet (the engine's own reply of a plain answer).
* ``Abbreviations``: the policy of a CALL, one object of the controller: a call that talks about «НДС» for ten minutes hears «налог на добавленную
  стоимость» once; the answers after it keep the short form until the listener asks what it means (``asks_expansion``).
* ``SPELLING``: how a code is written in a lead that is said aloud («нк» -> «НК»).
"""
import re

from .textutil import normalize

_ASKS = re.compile(r'расшифр|что\s+так(?:ое|ой|ая|ие)|что\s+знач|что\s+означ|что\s+эт[оа]\b|что\s+за\b', re.I)

SPELLING = {'нк': 'НК', 'гк': 'ГК', 'тк': 'ТК', 'ук': 'УК', 'ск': 'СК', 'жк': 'ЖК', 'коап': 'КоАП', 'рф': 'РФ', 'ндс': 'НДС', 'ндфл': 'НДФЛ', 'ссср': 'СССР',
            'сша': 'США', 'оон': 'ООН', 'ввп': 'ВВП', 'цб': 'ЦБ', 'мрот': 'МРОТ', 'усн': 'УСН', 'ип': 'ИП', 'ооо': 'ООО', 'фнс': 'ФНС', 'пфр': 'ПФР', 'днк': 'ДНК'}


def _find(key, text):
    return re.search(r'(?<![\w-])' + r'\s+'.join(re.escape(part) for part in key.split()) + r'(?![\w-])', text)


def asks_expansion(question, key):
    """Does the listener ask what ``key`` means («расшифруй НДС», «что такое НДС»)? «Какая ставка НДС» does not."""
    return isinstance(question, str) and bool(_find(key, question)) and _ASKS.search(question) is not None


def expand_abbreviations(text, table):
    """Replace the FIRST occurrence of every key by its full term (later ones stay short); a term the answer spelled out before its abbreviation stays as it is."""
    if not table:
        return text
    found = []
    for key, full in table.items():
        match = _find(key, text)
        if not match:
            continue
        spoken = f' {normalize(full)} '
        if spoken.strip() and spoken in f' {normalize(text[:match.start()])} ':
            continue  # the answer already spelled the term out before using the abbreviation
        found.append((match.start(), match.end(), full))
    found.sort(key=lambda item: (item[0], item[0] - item[1]))
    pieces, cursor = [], 0
    for start, end, full in found:
        if start >= cursor:
            pieces += [text[cursor:start], full]
            cursor = end
    pieces.append(text[cursor:])
    return ''.join(pieces)


class Abbreviations:
    """The call's memory of what it spelled out: what the EARLIER answers introduced is ``known``, this answer's own is ``now`` (a stream is expanded again at
    every tick and must not change under what is planned, so the answer's own terms join ``known`` only when the next question begins)."""

    def __init__(self):
        self.known, self.now, self.qid = set(), set(), None

    def say(self, text, table, question_id, asked):
        """``text`` with the terms of ``table`` spelled out once PER CALL: a term of an earlier answer keeps the short form unless ``asked`` asks what it means."""
        if not table:
            return text
        if self.qid != question_id:
            self.known |= self.now
            self.now, self.qid = set(), question_id
        out = expand_abbreviations(text, {key: value for key, value in table.items() if key not in self.known or asks_expansion(asked or '', key)})
        self.now |= {key for key in table if _find(key, text)}
        return out
