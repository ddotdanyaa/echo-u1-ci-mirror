"""w9-map (N133): the map of a compound question's parts. «Сколько стоит и когда привезут» is two asks: after the first is answered the second
must stay open (and be offered) rather than be forgotten silently. Pure: no clock, no I/O; the engine feeds it questions and answer texts.

``split_parts`` cuts a question into its asks, ``covers`` decides whether an answer text settles one ask (by the kind of the ask: a number
for «сколько», a time word for «когда», otherwise the stems of its content words), ``QuestionMap`` keeps per question the parts with
status open/closed."""
import re
from .timer_policy import CONVERSATION_GAP_S

_ASK = (r'(?:сколько|когда|где|как(?:ой|ая|ое|ие|ую|им|их|ого|ие)?|почему|зачем|что|чем|кто|куда|откуда|чей|чья|чьё|можно\s+ли|есть\s+ли|'
        r'будет\s+ли|над\s+как\w+|в\s+как\w+|на\s+как\w+|по\s+как\w+|с\s+как\w+)')
_JOIN = re.compile(r'(?:\s*,)?\s+(?:а\s+ещё|и\s+ещё|а\s+также|а\s+потом|и\s+потом|и)\s+(?=' + _ASK + r'\b)', re.I)
_ABOUT = re.compile(r'(?<!\w)про\s+', re.I)
_WORD = re.compile(r'\w+(?:-\w+)*', re.U)
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
_LEAD = re.compile(r'^(?:' + _ASK + r')\b', re.I)


def _asks_first(piece):
    """A compound question opens with its ask («Где вы учились и ...»); a preamble («Простите, что перебиваю, а что ...») or a story is not cut."""
    return _LEAD.match(piece) is not None


def _words(text):
    return [w.lower() for w in _WORD.findall(text if isinstance(text, str) else '')]


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
    if len(pieces) > 1 and all(2 <= len(_words(p)) <= _MAX_PART for p in pieces) and _asks_first(pieces[0]):
        return pieces
    return [_clean(text)]


def _kind(part):
    words = _words(part)
    for word in words[:4]:
        if word == 'сколько':
            return 'amount'
        if word == 'когда':
            return 'time'
    return 'stems'


def _stems(part):
    """Four-letter stems of the content words of an ask; a three-letter word counts only as a capitalised abbreviation («НДС», «УСН»)."""
    out = []
    for word in _WORD.findall(part):
        low = word.lower()
        if low not in _STOP and (len(low) >= 4 or (len(low) == 3 and word.isupper())):
            out.append(low[:_STEM])
    return out


def covers(part, answer):
    """Does the text ``answer`` settle the ask ``part``? A «сколько» ask wants a number (a date or a clock time does not count as one), a «когда» ask a
    time word, any other ask at least one stem (four letters) of its content words. A heuristic of the text, not of its truth."""
    if not isinstance(part, str) or not isinstance(answer, str) or not answer.strip():
        return False
    kind, words = _kind(part), _words(answer)
    if kind == 'amount':
        plain = _DATE_NUMBER.sub(' ', answer)
        return bool(re.search(r'\d', plain)) or any(w.startswith(_NUMBER) for w in _words(plain))
    if kind == 'time':
        return bool(_DATE_NUMBER.search(answer)) or any(w.startswith(_TIME) for w in words)
    stems = _stems(part)
    return bool(stems) and any(w.startswith(s) for s in stems for w in words)


class QuestionMap:
    """Per question: its parts {'text', 'status': 'open'|'closed'}. ``feed`` closes the parts a text settles; ``open_parts`` are the asks of the question nothing said has settled yet."""

    def __init__(self, window_s=CONVERSATION_GAP_S):
        self.window_s, self._next, self._entries = window_s, 1, {}

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
