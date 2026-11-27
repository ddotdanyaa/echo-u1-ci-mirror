"""w5-material (E15, E40): which parts of the owner's material the cloud model is shown for THIS question.

``content_policy.excerpt_of`` shows the first 12,000 characters of the material to every call and the rest is lost: a material of four
subjects is 27,000 characters and the talk moves from subject to subject. Here the material is cut into parts once (headings, then paragraphs),
and for every question the parts that fit the question and the last exchanges are taken, in the same cap, in the order of the material.
Local, no model: stems of the project (``textutil.stem``), BM25 over the parts; numbers and terms of the question weigh more. Nothing fits:
the first characters, as before. Never raises into a call; the log line has sizes only. Switched on by the ``material_pick`` flag (off)."""
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

from . import content_policy
from .content_policy import CLOSING, DATA_NOTICE, MATERIAL_EXCERPT_CHARS, MATERIAL_HOW, CallContext, excerpt_of
from .materials import squeeze_blank_lines
from .textutil import STOPWORDS, stem

PART_CHARS = 1200                 # a part is at most this long (its heading is added: <= PART_CHARS + HEADING_CHARS)
HEADING_CHARS = 200
LINE_WEIGHT = 1.0                 # the best sentence of a part counts next to the part: a lone fact in a big part is found
PAIR_WEIGHT = 4.0                 # two words of the question next to each other in a part (a number after "счёт"): worth this share of the best score
SUBJECT_BOOST = 2.0               # the question names the subject of a part (words of its title): its parts weigh this much more
HISTORY_ROWS = 2                  # the last exchanges that tell what the talk is about now
HISTORY_WEIGHT = 0.35             # their words next to the question's; with no word of the question in the material they weigh 1
NUMBER_WEIGHT, TERM_WEIGHT = 3.0, 2.0
KEEP_RATIO = 0.2                  # a part with less than this share of the best score is not worth the characters
SEPARATOR = '\n\n'
JOB_MATERIAL_CHARS = 2500         # W13 item 7: the job's material (9 000 chars went whole into every request): the parts for the question, under 3 000

_HEADING = re.compile(r'^(#{1,6})[ \t]+(.+?)[ \t]*$', re.M)
_WORD = re.compile(r'[\w]+(?:[-’\'][\w]+)*', re.U)
_SENTENCE = re.compile(r'(?<=[.!?…])\s+')
_ASKING = frozenset('расскажи объясни скажи подскажи покажи назови опиши коротко подробнее вопрос вопросе кратко как какой какая какое какие каких какого сколько скольких когда кто почему зачем где куда откуда чем такое значит нужно можно нужны'.split())


# Spoken numbers: the ear writes "три тысячи", "шестому ноября"; the material has "3 000", "06.11". The question gets both forms.
_ORD_END = r'(?:ой|ый|ого|ому|ом|ым|ая|ую|ое|ые|ых|ыми|ий|ьего|ьему|ьем|ья|ье)'
_NUMS = {'ноль': 0, 'один': 1, 'одн': 1, 'дв': 2, 'три': 3, 'тр': 3, 'четыр': 4, 'пят': 5, 'шест': 6, 'сем': 7, 'восем': 8, 'девят': 9, 'десят': 10,
         'одиннадцат': 11, 'двенадцат': 12, 'тринадцат': 13, 'четырнадцат': 14, 'пятнадцат': 15, 'шестнадцат': 16, 'семнадцат': 17,
         'восемнадцат': 18, 'девятнадцат': 19, 'двадцат': 20, 'тридцат': 30, 'сорок': 40, 'пятидесят': 50, 'пятьдесят': 50, 'шестидесят': 60,
         'шестьдесят': 60, 'семидесят': 70, 'семьдесят': 70, 'восьмидесят': 80, 'восемьдесят': 80, 'девяност': 90, 'девяно': 90, 'сто': 100, 'ст': 100,
         'двест': 200, 'триста': 300, 'трист': 300, 'четыреста': 400, 'четырест': 400, 'пятьсот': 500, 'пятисот': 500, 'шестьсот': 600, 'шестисот': 600,
         'семьсот': 700, 'семисот': 700, 'восемьсот': 800, 'восьмисот': 800, 'девятьсот': 900, 'девятисот': 900}
_ORDINALS = {'перв': 1, 'втор': 2, 'трет': 3, 'четвёрт': 4, 'четверт': 4, 'пят': 5, 'шест': 6, 'седьм': 7, 'восьм': 8, 'девят': 9, 'десят': 10,
             'одиннадцат': 11, 'двенадцат': 12, 'тринадцат': 13, 'четырнадцат': 14, 'пятнадцат': 15, 'шестнадцат': 16, 'семнадцат': 17,
             'восемнадцат': 18, 'девятнадцат': 19, 'двадцат': 20, 'тридцат': 30}
_MONTHS = {m: i + 1 for i, m in enumerate('января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split())}
_MULT = (('тысяч', 1000), ('миллион', 1000000), ('миллиард', 1000000000))
_WHOLE_NUMS = frozenset(w for w in _NUMS if len(w) > 3) | {'три', 'сто', 'два', 'две', 'дву', 'двух', 'трёх', 'трех', 'один', 'одна', 'одну', 'одного', 'пять', 'пяти', 'шесть', 'шести', 'семь', 'семи', 'восемь', 'восьми', 'девять', 'девяти', 'десять', 'десяти'}
_NUMS_LONGEST_FIRST = tuple(sorted(_NUMS, key=len, reverse=True))      # built once: _numeral runs for every word of every question
_NUM_FORM = re.compile(r'(?:' + '|'.join(map(re.escape, _NUMS_LONGEST_FIRST)) + r')(?:ь|и|ью|а|ов|ей|ех|ум|ою|ью)?')


def _numeral(word):
    """``(value, kind)`` of a spoken number word (kind 'c' cardinal, 'o' ordinal, 'm' a multiplier, 'x' a month), or ``None``."""
    w = word.casefold().replace('ё', 'е')
    if w in _MONTHS:
        return _MONTHS[w], 'x'
    for stem_, mult in _MULT:
        if w.startswith(stem_):
            return mult, 'm'
    for key, value in _ORDINALS.items():
        key = key.replace('ё', 'е')
        if w.startswith(key) and re.fullmatch(_ORD_END, w[len(key):] or '-') and len(w) > len(key):
            return value, 'o'
    if w in _WHOLE_NUMS or w in ('два', 'две', 'двух', 'трех', 'пять', 'восемь') or _NUM_FORM.fullmatch(w) and len(w) > 2:
        for key in _NUMS_LONGEST_FIRST:
            if w.startswith(key.replace('ё', 'е')):
                return _NUMS[key], 'c'
    return None


def spoken_numbers(words):
    """``words`` with spoken numbers also given as digits: "три тысячи" -> ... "3" "000"; "шестому ноября" -> ... "06" "11"; the words stay."""
    out, i = [], 0
    while i < len(words):
        first = _numeral(words[i])
        if first is None or first[1] in ('m', 'x'):
            out.append(words[i])
            i += 1
            continue
        total = part = 0
        kind = 'c'
        j = i
        while j < len(words):
            n = _numeral(words[j])
            if n is None or n[1] == 'x':
                break
            if n[1] == 'm':
                total += (part or 1) * n[0]
                part = 0
            else:
                part += n[0]
                kind = n[1]
            j += 1
        value = total + part
        month = _numeral(words[j]) if j < len(words) else None
        out.extend(words[i:j])
        if kind == 'o' and month and month[1] == 'x' and 0 < value < 32:
            out.extend([f'{value:02d}', f'{month[0]:02d}'])
            j += 1
        elif value >= 1000:
            out.extend(f'{value:,}'.replace(',', ' ').split())
        else:
            out.append(str(value))
        i = max(j, i + 1)
    return out


def _cut(text, size):
    """``text`` in pieces of at most ``size``: by sentences, then by words, then hard."""
    pieces, row = [], ''
    for sentence in _SENTENCE.split(text):
        while len(sentence) > size:
            at = sentence.rfind(' ', 0, size)
            at = at if at > size // 2 else size
            if row:
                pieces.append(row)
                row = ''
            pieces.append(sentence[:at].strip())
            sentence = sentence[at:].strip()
        if row and len(row) + 1 + len(sentence) > size:
            pieces.append(row)
            row = ''
        row = f'{row} {sentence}'.strip()
    return pieces + ([row] if row else [])


def split_parts(body):
    """The parts of ``body``: sections by markdown headings, a section by paragraphs gathered up to ``PART_CHARS``; each part starts
    with its nearest heading. Nothing is dropped except blank lines."""
    text = squeeze_blank_lines(str(body or '')).strip()
    marks = list(_HEADING.finditer(text))
    sections = [('', text[:marks[0].start()] if marks else text)]
    for i, m in enumerate(marks):
        sections.append((m.group(0).strip()[:HEADING_CHARS], text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)]))
    parts = []
    for heading, chunk in sections:
        paragraphs = [p.strip() for p in re.split(r'\n[ \t]*\n', chunk) if p.strip()]
        head = (heading + '\n') if heading else ''
        row = ''
        for paragraph in (q for p in paragraphs for q in (_cut(p, PART_CHARS) if len(p) > PART_CHARS else [p])):
            if row and len(row) + 2 + len(paragraph) > PART_CHARS:
                parts.append(head + row)
                row = ''
            row = f'{row}\n\n{paragraph}'.strip()
        if row:
            parts.append(head + row)
        elif heading and not paragraphs:
            parts.append(heading)
    return parts


def _tokens(text):
    return [w.casefold().replace('ё', 'е') for w in _WORD.findall(str(text or ''))]


def _content_stems(text):
    return [stem(w) for w in _tokens(text) if (w not in STOPWORDS and w not in _ASKING and (len(w) > 2 or w.isdigit()))]


def _query(question, history):
    """``({stem: weight}, found_in_question)``: the question's stems; a number weighs ``NUMBER_WEIGHT``, a term (a capital letter inside the
    sentence, or letters with digits) ``TERM_WEIGHT``; the stems of the last exchanges with ``HISTORY_WEIGHT`` unless the question has its own."""
    weights = {}
    words = spoken_numbers(_WORD.findall(str(question or '')))
    for i, raw in enumerate(words):
        w = raw.casefold().replace('ё', 'е')
        if w in STOPWORDS or w in _ASKING or not (len(w) > 2 or w.isdigit()):
            continue
        weight = NUMBER_WEIGHT if w.isdigit() else TERM_WEIGHT if (any(c.isdigit() for c in w) or (i and raw[:1].isupper())) else 1.0
        weights[stem(w)] = max(weights.get(stem(w), 0), weight)
    rows = [e for e in (history or ()) if isinstance(e, dict)][-HISTORY_ROWS:]
    old = {}
    for entry in rows:
        for s in _content_stems(entry.get('question')):
            old[s] = 1.0
    return weights, old


@dataclass
class Pick:
    text: str = ''
    parts: int = 0               # parts the material has
    picked: int = 0              # parts shown
    total: int = 0               # characters of the whole material
    truncated: bool = False
    fallback: bool = False       # nothing fitted: the first characters as before

    def summary(self):
        """One line for the log of a call: sizes only, never a word of the material."""
        return f'material_pick parts={self.parts} picked={self.picked} chars={len(self.text)} of={self.total} truncated={self.truncated} fallback={self.fallback}'


class MaterialPicker:
    """Built once at the opening of a call from the whole text of the material; ``pick`` costs milliseconds."""

    def __init__(self, body, cap=MATERIAL_EXCERPT_CHARS):
        self.cap = cap
        self.body = squeeze_blank_lines(str(body or '')).strip()
        self.sha256 = hashlib.sha256(self.body.encode('utf-8')).hexdigest() if self.body else ''
        self.parts = split_parts(self.body) if self.body else []
        self._counts = [Counter(_content_stems(p) + _content_stems(p.split('\n', 1)[0] if p.startswith('#') else '') * 2) for p in self.parts]
        self._lengths = [max(1, sum(c.values())) for c in self._counts]
        self._pairs = [set(zip(seq, seq[1:])) for seq in (_content_stems(p) for p in self.parts)]
        self._subject = self._subjects()
        self._lines = [[Counter(_content_stems(x)) for x in _SENTENCE.split(p.replace('\n', ' ')) if x.strip()] for p in self.parts]
        self._line_sizes = [[max(1, sum(c.values())) for c in rows] for rows in self._lines]
        sizes = [sum(c.values()) for rows in self._lines for c in rows]
        self._line_avg = max(1.0, sum(sizes) / max(1, len(sizes)))
        self._avg = sum(self._lengths) / max(1, len(self._lengths))
        df = Counter(s for c in self._counts for s in c)
        n = len(self.parts)
        self._idf = {s: math.log(1 + (n - d + 0.5) / (d + 0.5)) for s, d in df.items()}

    def _subjects(self):
        """For every part the stems of the title of its subject (the last heading of level 1 before it), or ``None``; stems common to all subjects are dropped."""
        titles, out, current = [], [], None
        for m in _HEADING.finditer(self.body):
            if len(m.group(1)) == 1:
                titles.append((m.start(), frozenset(_content_stems(m.group(2)))))
        for part in self.parts:
            at = self.body.find(part.split('\n', 1)[-1][:80])
            current = None
            for start, stems_ in titles:
                if start <= at:
                    current = stems_
            out.append(current)
        common = frozenset.intersection(*[t for _s, t in titles]) if titles else frozenset()
        return [None if t is None else t - common for t in out]

    def _scores(self, weights, pairs=(), subject=None):
        out = []
        for counts, length in zip(self._counts, self._lengths):
            score = 0.0
            for s, w in weights.items():
                tf = counts.get(s)
                if tf:
                    score += w * self._idf[s] * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / self._avg))
            out.append(score)
        if LINE_WEIGHT and out:
            for i, rows in enumerate(self._lines):
                best = 0.0
                for counts, size in zip(rows, self._line_sizes[i]):
                    got = sum(w * self._idf[s] * counts[s] * 2.2 / (counts[s] + 1.2 * (0.25 + 0.75 * size / self._line_avg)) for s, w in weights.items() if counts.get(s))
                    best = max(best, got)
                out[i] += LINE_WEIGHT * best
        if pairs and out:
            top = max(out)
            for i, have in enumerate(self._pairs):
                out[i] += PAIR_WEIGHT * top / max(1, len(weights)) * len(have.intersection(pairs))
        if subject and out:
            for i, title in enumerate(self._subject):
                if title and title & subject:
                    out[i] *= SUBJECT_BOOST
        return out

    def rank(self, question, history=()):
        """Indices of the parts, the best first (parts that do not fit at all are last, in the order of the material)."""
        try:
            scores = self._pick_scores(question, history)
        except Exception:                                      # noqa: BLE001
            scores = [0.0] * len(self.parts)
        return sorted(range(len(self.parts)), key=lambda i: (-scores[i], i))

    def _pick_scores(self, question, history):
        weights, old = _query(question, history)
        seq = _content_stems(' '.join(spoken_numbers(_WORD.findall(str(question or '')))))
        pairs, subject = set(zip(seq, seq[1:])), frozenset(seq)
        scores = self._scores(weights, pairs, subject) if weights else [0.0] * len(self.parts)
        if max(scores, default=0) <= 0:                    # no word of the question: what the talk was about before
            scores = self._scores(old)
        elif old:
            merged = dict(weights)
            for s in old:
                merged.setdefault(s, HISTORY_WEIGHT)
            scores = self._scores(merged)
        return scores

    def pick(self, question, history=()):
        total = len(self.body)
        try:
            if not self.body:
                return Pick()
            if total <= self.cap:
                return Pick(self.body, len(self.parts), len(self.parts), total)
            scores = self._pick_scores(question, history)
            best = max(scores, default=0)
            if best <= 0:
                return self._first(total)
            order = sorted((i for i, s in enumerate(scores) if s >= best * KEEP_RATIO), key=lambda i: -scores[i])
            chosen, used = [], 0
            for i in order:
                cost = len(self.parts[i]) + (len(SEPARATOR) if chosen else 0)
                if used + cost <= self.cap:
                    chosen.append(i)
                    used += cost
            chosen.sort()
            text = SEPARATOR.join(self.parts[i] for i in chosen)
            return Pick(text, len(self.parts), len(chosen), total, truncated=len(text) < total)
        except Exception:                                      # noqa: BLE001 - the material is an addition, never a failed call
            return self._first(total)

    def _first(self, total):
        try:
            shown, truncated = excerpt_of(self.body, self.cap)
        except Exception:                                      # noqa: BLE001
            shown, truncated = self.body[:self.cap], True
        return Pick(shown, len(self.parts), 0, total, truncated=truncated, fallback=True)

    def instructions(self, question, history, context, policy):
        """``build_instructions`` for this question: the owner's lines, then the parts picked. The pick itself (for the log) comes from ``instructions_and_pick``."""
        return self.instructions_and_pick(question, history, context, policy)[0]

    def instructions_and_pick(self, question, history, context, policy):
        pick = self.pick(question, history)
        material = content_policy._plain(pick.text).strip()
        base = content_policy.build_instructions(CallContext(subject=context.subject, audience=context.audience, style=context.style), policy)
        if not material:
            return base, pick
        if base == policy:
            base = '\n'.join([policy, '', DATA_NOTICE])
        elif base.endswith(CLOSING):
            base = base[:-len(CLOSING)].rstrip('\n')
        ident = (self.sha256 or hashlib.sha256(material.encode('utf-8')).hexdigest())[:12]
        how = (f'подобраны части под вопрос и разговор: {len(material)} из {pick.total} знаков; полный текст сохранён, но сюда не вмещается'
               if pick.truncated and not pick.fallback else
               f'показано начало: {len(material)} из {pick.total} знаков; полный текст сохранён, но сюда не вмещается' if pick.truncated
               else f'показаны полностью (всего знаков: {len(material)})')
        return '\n'.join([base, f'⟦МАТЕРИАЛЫ {ident} — {how}. {MATERIAL_HOW}⟧', material, f'⟦КОНЕЦ МАТЕРИАЛОВ {ident}⟧', CLOSING]), pick


def for_job(body, cap=JOB_MATERIAL_CHARS):
    """W13 item 7: the picker of the job (fast_text): parts for the question whatever the size of the material, within ``cap``."""
    return MaterialPicker(body, cap=cap)


def load_whole(home):
    """The whole text of ``<home>/materials/context.md`` as the call is shown it (blank runs squeezed), or ``''``: nothing usable, unreadable, too large. Blocking: call it off the loop."""
    try:
        body, _digest, _note = content_policy._read_material(content_policy.Path(home) / 'materials' / 'context.md')
        return squeeze_blank_lines(body).strip() if body else ''
    except Exception:                                          # noqa: BLE001
        return ''
