"""W5 instant (С10, С11, С12, Ст7): the answer lies ready, and the ear's partial text finds it. One index of the bank (``load_bank``: the owner's
questions, trust «Д»; pairs of the material, trust «М»), and at the ear's cut-off the code answers of the chart of accounts and the codes
(``reference_kb``), the laws (``law_base``) and the sums (``quick_math``). ``Instant.feed(text, t, final=False)`` is called on every partial text of
the ear, not waiting for the silence, and gives a ``Hit`` whose ``core`` (at most 6 words) may sound at once.

A hit is given only when all of it holds:
- one bank entry is matched in full: every significant word of one of its forms is heard, nothing significant is heard that is not in it
  (the frame words «скажите», «что такое», «пожалуйста» are neither), the numbers are equal by value and in order, «не» stands before the same
  word, the question words («когда», «где», «как», «почему» ...) are the same set; two entries with other answers matched in full: nothing;
- on a partial: the last word heard is no preposition, conjunction, «не» or number (the speech goes on), and no other entry holds every
  significant word heard as well (``отрыв``: «что такое НДС» waits while «что такое НДС при импорте» is in the bank). At ``final`` (the ear's
  cut-off) the speech has stopped and the full match alone decides;
- the ear's errors are forgiven in ordinary words only: the same lemma, the same snowball stem, the same phonetic key (``phonetic``), or for a
  word of 8 letters and more one phonetic letter off (at most one such word per question). Numbers and «не» have no tolerance at all;
- a question about what changes («сейчас», «курс», «действующий», ``_CHANGES``) is never in the bank and never matched.

After a hit the same utterance is followed: new significant words, another number or «не» set ``cut`` (the cue is cut by the transport's own
``_speech_began``, the question goes the usual way) and nothing more is given until ``reset`` or the next utterance. Adapters answer only at
``final``; when the bank and an adapter answer differently, there is no answer. Never raises; writes nothing, logs nothing of the words."""
from __future__ import annotations

import copy
import functools
import json
import math
import re
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import ru_alignment
from .fast_text import STOPWORDS, _atoms, _is_number

MAX_BANK = 20000
MAX_Q = 300
MAX_ANSWER = 2000
MAX_HEARD_WORDS = 40
CORE_WORDS = 6
FUZZY_MIN = 8                       # letters of a phonetic key that may be one letter off
QWORDS = frozenset({'когда', 'где', 'куда', 'откуда', 'почему', 'зачем', 'отчего', 'как', 'кто', 'сколько', 'какой', 'чей', 'каков'})
FRAME = frozenset({'такой', 'это', 'сказать', 'подсказать', 'пожалуйста', 'рассказать', 'объяснить', 'назвать', 'напомнить', 'вопрос', 'ну', 'вот', 'а',
                   'так', 'значит', 'слушать', 'можно', 'мне', 'давать', 'давай', 'давайте', 'ли', 'же', 'что', 'и', 'да', 'ага', 'угу', 'э', 'эм', 'м'})
DANGLING = frozenset({'в', 'во', 'на', 'для', 'и', 'или', 'а', 'но', 'при', 'по', 'с', 'со', 'к', 'ко', 'от', 'до', 'из', 'без', 'о', 'об', 'обо', 'за', 'под',
                      'над', 'если', 'чем', 'у', 'не', 'ни', 'про', 'через', 'между', 'перед', 'после', 'около', 'либо', 'то', 'чтобы', 'как', 'что', 'какой',
                      'какая', 'какие', 'каком', 'какого'})
TRUST = ('Д', 'М')
_WORD = re.compile(r'[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*|\d+(?:[.,]\d+)?')


# --- the phonetic key -----------------------------------------------------------------------------------------------------------------

_PHON = [('ё', 'е'), ('ъ', ''), ('ь', ''), ('тьс', 'ц'), ('тс', 'ц'), ('дс', 'ц'), ('сч', 'щ'), ('жч', 'щ'), ('зч', 'щ'), ('стн', 'сн'), ('здн', 'зн'),
         ('вств', 'ств'), ('лнц', 'нц')]
_DEVOICE = str.maketrans({'б': 'п', 'в': 'ф', 'г': 'к', 'д': 'т', 'ж': 'ш', 'з': 'с'})
_VOWEL = str.maketrans({'о': 'а', 'е': 'и', 'э': 'и', 'я': 'и', 'ы': 'и', 'ю': 'у', 'й': 'и'})


def phonetic(word):
    """A rough key of how a Russian word sounds: unstressed vowels folded (о→а, е/э/я/ы→и), consonants devoiced, ь/ъ dropped, doubled letters
    one, «тс»/«ться» as «ц». Two words with one key are the same word to an ear that heard it badly. Numbers never go through it."""
    w = str(word or '').casefold()
    for a, b in _PHON:
        w = w.replace(a, b)
    w = re.sub(r'([ое])го$', r'\1ва', w)             # «-ого», «-его» at the end sound «-ова»
    w = w.translate(_DEVOICE).translate(_VOWEL)
    return re.sub(r'(.)\1+', r'\1', w)


def _deletions(key):
    return {key[:i] + key[i + 1:] for i in range(len(key))}


def _near(a, b):
    """Phonetic keys one edit apart (a letter missing, added or changed), both long enough."""
    if a == b:
        return True
    if min(len(a), len(b)) < FUZZY_MIN or abs(len(a) - len(b)) > 1:
        return False
    return bool(({a} | _deletions(a)) & ({b} | _deletions(b)))


def _noted(component, error, what=''):
    from . import degradation           # noqa: PLC0415 - U78: a swallowed failure is journalled, never raised
    degradation.note(component, error, what=what)


def _stem(word):
    from .textutil import stem          # noqa: PLC0415 - snowball, may be missing: then the lemma and the key alone
    try:
        return stem(word)
    except Exception as error:         # noqa: BLE001
        _noted('instant.stem', error)
        return word


# --- one text, prepared -----------------------------------------------------------------------------------------------------------------

@dataclass
class Item:
    kind: str                           # 'w' a content word, 'n' a number, 'not', 'q' a question word, 'f' a frame or function word
    key: str                            # the lemma, '#value', 'не'/'ни', the question word
    keys: frozenset = frozenset()       # a content word: lemma, 's:stem', 'p:phonetic'
    phon: str = ''


@functools.lru_cache(maxsize=4096)
def _items(text):
    """The items of one text, analysed once: a match reads the same text as ``whole``, as ``heard`` and again at ``_same`` / ``_beyond_row`` (read-only: nothing edits an item list)."""
    out = []
    for atom in _atoms(text):
        a = atom.atom
        if _is_number(atom):
            out.append(Item('n', '#' + re.split(r'[:#]', a)[-1]))
        elif a in ('не', 'ни'):
            out.append(Item('not', a))
        elif a in QWORDS:
            out.append(Item('q', a))
        elif a in FRAME or a in STOPWORDS:
            out.append(Item('f', a))            # neither needed nor extra; it only says what stands after «не»
        else:
            surface = atom.surface.casefold().replace('ё', 'е')
            phon = phonetic(a)
            keys = {a, 's:' + _stem(surface), 's:' + _stem(a), 'p:' + phon}
            if atom.kind == 'w' and len(surface) >= 4:
                keys.add('p:' + phonetic(surface))
            out.append(Item('w', a, frozenset(keys), phon))
    return out


def _sig(items):
    return [i for i in items if i.kind == 'w']


def _numbers(items):
    return [i.key for i in items if i.kind == 'n']


def _nots(items):
    """«не» with the item after it: ('не', key of the next item or '')."""
    out = []
    for k, i in enumerate(items):
        if i.kind == 'not':
            nxt = items[k + 1] if k + 1 < len(items) else None
            out.append((i.key, nxt))
    return out


def _qwords(items):
    return frozenset(i.key for i in items if i.kind == 'q')


def _asked(form):
    """The question word a form opens with («что» too, which the forms do not count as one), '' when it says none."""
    return next((w for w in _WORD.findall(form.text.casefold()) if w in QWORDS or w == 'что'), '')


def _garbled(heard, row):
    """U30: the ear's question word is lost (``heard`` empty) or one letter off the row's («кто» for «что»); never another question word («когда» over «кто»)."""
    return not heard or bool(row) and len(heard) == len(row) and sum(a != b for a, b in zip(heard, row)) <= 1 or bool(row) and abs(len(heard) - len(row)) == 1 and (heard in row or row in heard)


def _word_match(h, f):
    """-> 0 no, 1 sure (lemma, stem, phonetic key), 2 fuzzy (a phonetic letter off)."""
    if h.keys & f.keys:
        return 1
    return 2 if _near(h.phon, f.phon) else 0


@dataclass
class Form:
    entry: int
    text: str
    items: list
    words: list = field(default_factory=list)
    numbers: list = field(default_factory=list)
    qwords: frozenset = frozenset()


def _form(entry, text):
    items = _items(text)
    return Form(entry, text, items, _sig(items), _numbers(items), _qwords(items))


def _align(heard, form):
    """Match the content words of ``heard`` onto those of ``form``. -> (pairs {heard index: form index}, missing form words, extra heard words, fuzzy count)"""
    pairs, used, fuzzy = {}, set(), 0
    for want in (1, 2):
        for hi, h in enumerate(heard.words):
            if hi in pairs:
                continue
            for fi, f in enumerate(form.words):
                if fi not in used and _word_match(h, f) == want:
                    pairs[hi] = fi
                    used.add(fi)
                    fuzzy += want == 2
                    break
    return pairs, len(form.words) - len(used), len(heard.words) - len(pairs), fuzzy


def _nots_agree(heard, form, pairs):
    hn, fn = _nots(heard.items), _nots(form.items)
    if len(hn) != len(fn):
        return False
    hw = {id(w): k for k, w in enumerate(heard.words)}
    for (hk, hnext), (fk, fnext) in zip(hn, fn):
        if hk != fk:
            return False
        if hnext is None or fnext is None:
            if hnext is not fnext:
                return False
            continue
        if hnext.kind != fnext.kind:
            return False
        if hnext.kind == 'w':
            fi = pairs.get(hw.get(id(hnext)))
            if fi is None or form.words[fi] is not fnext:
                return False
        elif hnext.key != fnext.key:
            return False
    return True


def full_match(heard, form):
    """Is ``heard`` the question ``form`` (the rules of the module's head)?"""
    if heard.numbers != form.numbers or heard.qwords != form.qwords or len(heard.words) != len(form.words):
        return False                    # W11: no word missing and none extra means as many words: the count first, the alignment only then
    pairs, missing, extra, fuzzy = _align(heard, form)
    if missing or extra or fuzzy > 1 or (fuzzy and len(form.words) < 2):
        return False
    return _nots_agree(heard, form, pairs)


def could_become(heard, form):
    """Could the speech still go on into ``form``: every significant thing heard is in it (the numbers as its head), and it holds more."""
    if form.numbers[:len(heard.numbers)] != heard.numbers or not heard.qwords <= form.qwords:
        return False
    if len(_nots(heard.items)) > len(_nots(form.items)) or len(heard.words) > len(form.words):
        return False
    pairs, missing, extra, fuzzy = _align(heard, form)
    return not extra and (missing or len(form.numbers) > len(heard.numbers) or len(form.qwords) > len(heard.qwords) or len(_nots(form.items)) > len(_nots(heard.items)))


# --- the bank ---------------------------------------------------------------------------------------------------------------------------

def _clean(value, limit):
    text = ' '.join(str(value or '').split())
    return text if 0 < len(text) <= limit else ''


def _is_num_word(word):
    return word.isdigit() or any(a.kind == 'n' for a in _atoms(word))


def core_of(answer, limit=CORE_WORDS):
    """The first portion of ``answer``: at most ``limit`` words, cut at a comma or a full stop within them, else after the last word that is no
    preposition or conjunction and does not split a number («к девятьсот восемьдесят восьмому году» stays whole or goes to the next portion)."""
    words = str(answer or '').split()
    if not words:
        return ''
    head = words[:limit]
    for k in range(len(head) - 1, -1, -1):
        if re.search(r'[,.;:!?—]$', head[k]):
            return ' '.join(head[:k + 1])
    if len(words) <= limit:
        return ' '.join(words)
    for k in range(len(head), 0, -1):
        last = re.sub(r'\W+$', '', head[k - 1]).casefold()
        nxt = words[k] if k < len(words) else ''
        if last in DANGLING or last in STOPWORDS:
            continue
        if _is_num_word(last) and nxt and _is_num_word(re.sub(r'\W+$', '', nxt)):
            continue
        if k < len(words) and _is_num_word(re.sub(r'\W+$', '', nxt)) and k >= 1 and last in DANGLING:
            continue
        return ' '.join(head[:k])
    return ' '.join(head)


# What changes with the day. Narrower than ``generator.needs_current_data`` on purpose: that one also takes every «ставка», and a rate the owner
# put in the bank with its source is the owner's answer to say; «сейчас», «на сегодня», «курс», «действующий» are never answered from the bank.
# «курс» is spelled out case by case, not as ``курс\w*``: a rate («курс доллара», «курсы валют») changes with the day, but «курсовая работа» is a paper
# whose title and chapters do not, and the owner's answer about it must be allowed to stand in the bank.
# c22-reviewfix (review 4a91807): a live price has wordings with no «курс» («Почём евро?», «Сколько рублей за доллар?», «Какая стоимость биткоина?»)
# and the adjective has a market sense («курсовая стоимость акции»); «курсовая разница» is an accounting term and stays answerable.
_LIVE_PRICE = r'(?:доллар\w*|евро|юан\w*|иен\w*|фунт\w*|франк\w*|биткоин\w*|bitcoin|криптовалют\w*|эфир\w*|акци\w*|нефт\w*|валют\w*)'
_CHANGES = re.compile(r'(?<!\w)(?:сейчас|сегодня\w*|нынешн\w*|текущ\w*|действующ\w*|актуальн\w*|последн\w*|свеж\w*'
                      r'|курс(?:ы|а|у|е|ов|ом|ам|ами|ах)?|курсов\w*\s+(?:стоимост|цен)\w*|погод\w*|новост\w*|котировк\w*|в этом году|на данный момент'
                      r'|(?:стои\w*|почем|цен[аеуы]\w*|стоимост\w*|дают\s+за|рубл\w*\s+за)\s+(?:\w+\s+){0,2}?' + _LIVE_PRICE + r')(?!\w)', re.I)


def _changes(text):
    return bool(_CHANGES.search(str(text or '').replace('ё', 'е')))


_COUNT_HEAD = re.compile(r'^(?:Два|Две|Три|Четыре|Пять|Шесть|Семь|Восемь|Девять|Десять)\s+[а-яё]+:\s+(\S)')


def _no_count_head(answer, question):
    """h30, the owner on the call: «он говорит шесть видов вместо того, чтобы просто перечислить»: the first words of a cue are the answer, not its count (unless the count was asked)."""
    if 'сколько' in str(question).casefold():
        return answer
    return _COUNT_HEAD.sub(lambda found: found.group(1).upper(), answer, count=1)


def clean_entry(row, trust='Д'):
    """One bank row ``{q, alt, core, answer, source, subject, trust}`` checked, or None: no question or answer, too long, or about what changes."""
    if not isinstance(row, dict):
        return None
    q, answer = _clean(row.get('q'), MAX_Q), _clean(row.get('answer', row.get('a')), MAX_ANSWER)
    if not q or not answer or _changes(q):
        return None
    alt = [a for a in (_clean(x, MAX_Q) for x in (row.get('alt') or []) if isinstance(x, str)) if a and not _changes(a)]
    core = _clean(row.get('core'), 200)
    core = core if core and len(core.split()) <= CORE_WORDS and answer.startswith(core.rstrip(',.;:')) else core_of(answer)
    t = row.get('trust') if row.get('trust') in TRUST else trust
    return {'id': str(row.get('id') or ''), 'q': q, 'alt': alt, 'core': core, 'answer': answer, 'source': _clean(row.get('source'), 200),
            'subject': _clean(row.get('subject'), 100), 'trust': t}


def load_bank(path, trust='Д'):
    """The bank file (a JSON list of rows, or ``{"bank": [...]}``) checked row by row; missing or broken: []."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        data = data.get('bank', []) if isinstance(data, dict) else data
        rows = [clean_entry(r, trust) for r in data[:MAX_BANK]] if isinstance(data, list) else []
        return [r for r in rows if r]
    except Exception as error:                         # noqa: BLE001
        _noted('instant.bank', error, 'банк')
        return []


def material_entries(material):
    """Pairs ``В:``/``О:`` written in the material, as bank rows of trust «М»."""
    try:
        from .prepared_answers import parse_pairs      # noqa: PLC0415
        rows = [clean_entry({'q': q, 'answer': a, 'source': 'материал'}, 'М') for q, a in parse_pairs(material or '')]
        return [r for r in rows if r]
    except Exception as error:                         # noqa: BLE001
        _noted('instant.material', error, 'пары из материала')
        return []


def vocab_terms(bank, limit=60):
    """The plain words of the bank's questions for the ear's bias (``ear_vocab``): never a number or «не»/«ни» (``ear_sherpa.material_terms``)."""
    from .ear_sherpa import material_terms             # noqa: PLC0415
    texts = []
    for row in bank or ():
        if isinstance(row, dict):
            texts.append(str(row.get('q', '')))
            texts.extend(str(a) for a in row.get('alt') or ())
    return material_terms(texts, limit=limit)


# --- W11: the ranked path ---------------------------------------------------------------------------------------------------------------
# The full match above is too strict for questions written blind: 20 of 200. The ranked path weighs the words (rare ones weigh more, IDF over
# the entries), looks for them in the entry's ``q``, ``alt`` and, at a lower weight, in its ``answer``, and gives the best entry only when it
# is far enough above the second best with another answer. What sinks a candidate: another kind of question («что такое» against «когда»),
# a number or «не» the entry does not hold, a word the bank never heard (another program, company, country: ``RANK_UNKNOWN``).

RANK_MIN = 0.70                     # the score of the best entry, 0..1 (``_score``), tuned on the dev half of gold.json (tools/bank_eval.py); F5: 0.60 gives dev 23/74 but a false accept in the W5 table of 500
RANK_PARTIAL_MIN = 0.9              # on a partial the speech may still go on («можно менять учётную политику … посреди года?»): a surer score
RANK_GAP = 0.15                     # the best above the second best entry with another answer
RANK_ANSWER_W = 0.6                 # a word found only in the answer weighs this much of a word of ``q``/``alt``
RANK_TOP = 60                       # candidates scored in full
RANK_ATOM_CAP = 200                 # U21-S4 (C1): besides them, the entries that name the question's number are scored too, this many at most
FITTED_RIVAL_W = 0.6               # U21-S6 (C2): the weight fitted on dev (grid 0, 0.2, 0.3, 0.45, 0.6 all equal there; the mildest kept): the value to put in bank_rival_weight; the default stays 1.0
REJOIN_MAX = 2                      # U21-S5 (C3): a heard word torn in two by the ear is joined back, this many joins at most per question
RANK_FORM_W = 0.5                   # how much the entry's own question must be heard: score = cover × (1 − w + w × form)
RANK_TYPE_MISS = 0.5                # a form of another kind of question: its score times this
RANK_TYPE_NEAR = 0.85               # a form of a kin kind («что такое» / «какие бывают») or of no kind said, while the question says one
RANK_FORM_MIN = 0.8                 # the share (by IDF) of the words of the entry's question form the question must hold
RANK_COVER_MIN = 0.6                # the share (by IDF) of the heard words the entry must hold, a word of its answer counted at RANK_ANSWER_W
RANK_RARE = 3.0                     # F5: the first heard word, this rare (IDF), unsaid by the entry's question side: another question («амортизация НМА» ≠ «НМА»)
RANK_MIN_MASS = 2.8                 # the question must say this much (the sum of the IDF of its words): «как там всё считали» says nothing
TALK = frozenset({'слушать', 'ну', 'вот', 'я', 'ты', 'вы', 'мы', 'мне', 'нам', 'тебе', 'вам', 'понять', 'помнить', 'запомнить', 'знать', 'забыть',
                  'сказать', 'подсказать', 'объяснить', 'напомнить', 'рассказать', 'пояснить', 'уточнить', 'вообще', 'просто', 'кстати', 'короче',
                  'типа', 'значит', 'то', 'есть', 'это', 'ли', 'же', 'пожалуйста', 'можно', 'вопрос', 'интересно', 'хотеть', 'постоянно', 'путаться',
                  'спутать', 'путать', 'всегда', 'опять', 'снова', 'еще', 'раз', 'там', 'тут', 'вроде', 'кажется', 'честно', 'слово', 'простой',
                  'по-простому', 'а', 'и', 'да', 'так', 'ага', 'угу', 'э', 'эм', 'м', 'нет', 'такой', 'что-то', 'как-то', 'что', 'нибудь', 'какой-то',
                  'точно', 'именно', 'всё', 'все', 'вспомнить', 'понимать', 'вообще-то', 'ой', 'блин', 'давать', 'давай', 'давайте', 'мочь', 'бы',
                  'говорить', 'сказано', 'надо', 'нужно', 'ведь', 'сам', 'самый', 'дело', 'ладно', 'хорошо', 'окей', 'понятно'})
_TALK_NOT = frozenset({'помнить', 'понять', 'понимать', 'знать', 'запомнить', 'путать', 'путаться', 'спутать', 'уверенный', 'уверен', 'ясно', 'понятно'})
# The kind of a question: what the answer is. Two kinds that differ never meet (a definition is no deadline).
_QTYPES = (('diff', re.compile(r'\bчем\b.{0,40}\bотлича|\bотлича\w*\b.{0,40}\bот\b|\bразниц|\bв чём отлич|\bчем\b.{0,25}\bот\b|одно и то же|\bили\b')),
           ('calc', re.compile(r'\bкак\b.{0,25}\b(?:счита|рассчит|вычисл|посчита|определя|найти|исчисл)|\bформул|\bкак\b.{0,15}\bсчита')),
           ('who', re.compile(r'\bкто\b|\bкому\b|\bкого\b')),
           ('where', re.compile(r'\bгде\b|\bкуда\b|\bв каком месте\b|\bна каком (?:слайде|листе|счете|счёте)\b')),
           ('when', re.compile(r'\bкогда\b|\bдо какого\b|\bв какой срок|\bсрок\w*\b|\bдата\b|\bкакого числа\b|\bпо каким дням\b')),
           ('count', re.compile(r'\bсколько\b|\bкаков\w* (?:размер|ставк|лимит|процент)|\bкакая ставка\b|\bкакой процент\b|\bв каком размере\b')),
           ('why', re.compile(r'\bзачем\b|\bпочему\b|\bдля чего\b|\bс какой целью\b|\bкакова цель\b|\bчто дает\b|\bчто даёт\b|\bв чем смысл\b|\bв чём смысл\b')),
           ('what', re.compile(r'\bчто так\w*\b|\bчто значит\b|\bчто означает\b|\bэто что\b|\bчто это\b|\bчто за\b|\bопределени|\bчто понимают\b|\bчто называ|\bчто подразумева|\bпонятие\b|\bзначение термина')),
           ('list', re.compile(r'\bкакие\b.{0,30}\b(?:бывают|есть|существуют|виды|типы|элементы|источник|способ|метод|функции|признаки)|\bвиды\b|\bперечисл|\bиз чего\b|\bчто входит\b|\bкакие\b')),
           ('how', re.compile(r'\bкак\b|\bкаким образом\b|\bчто делать\b|\bчто нужно сделать\b|\bпорядок\b')))
_COMPAT = {('how', 'calc'), ('calc', 'how'), ('count', 'calc'), ('calc', 'count'), ('how', 'list'), ('list', 'how'),
           ('what', 'why'), ('why', 'what'), ('how', 'why'), ('why', 'how')}


_PERSONAL = frozenset({'ты', 'вы', 'тебя', 'тебе', 'твой', 'твоя', 'твою', 'твое', 'твои', 'ваш', 'вашу', 'ваша', 'вам', 'вас'}) - {'вам', 'вас'}


def qtype(text):
    """The kind of question of ``text`` (``_QTYPES``), or '' when it says none."""
    low = ' ' + str(text or '').casefold().replace('ё', 'е') + ' '
    for name, rx in _QTYPES:
        if rx.search(low):
            return name
    return ''


def _kind_same(kind, row, kindof=None, compat=None):
    """F5: the question's kind is one the entry answers: the kinds of its ``q`` and ``alt`` («приведи примеры НМА», a form of no kind, still
    belongs to «какие бывают НМА», which is no answer to «что такое НМА»)."""
    kinds = {(kindof or qtype)(t) for t in [row['q']] + list(row['alt'])} - {''}
    return not kind or not kinds or any(_types_meet(kind, k, compat) for k in kinds)


def _types_meet(a, b, compat=None):
    return not a or not b or a == b or (a, b) in (_COMPAT if compat is None else compat)


_COMPAT2 = (_COMPAT - {('what', 'why'), ('why', 'what')}      # C24: a definition is not a cause (nor a cause a definition): «что такое X» never answers «почему X»
            | {('what', 'list'), ('list', 'what'), ('what', 'how'), ('how', 'what')})      # h28: the owner's own calls: «что такое функция денег» of «какие функции у денег», «как контрольная функция» of «в чём контрольная функция»: 26 of 35 real questions lost to the form; a row of the same kind still wins by RANK_TYPE_NEAR


_SENT = re.compile(r'(?<=[.?!…])\s+')
_JOIN = re.compile(r'(?:,\s*|\s+)(?:и|а|или)\s+(?=(?:чем|когда|как|сколько|зачем|почему|где|кто|какие|какой|какая|каким|что|до какого|в чем|в чём)\b)'
                   r'|\?\s*(?=\S)', re.I)


def question_text(text):
    return question_parts(text)[0]


_RETRACT = frozenset({'нет', 'точнее', 'вернее', 'стоп', 'ой'})


def _retracts(tokens):
    """U21-S3 (RC3): the speaker takes a word back in the middle of the talk («функция денег, нет, давай-ка знаешь что …»): a retraction word with words on both sides. Diagnosis only."""
    return any(w in _RETRACT and 0 < i < len(tokens) - 1 for i, w in enumerate(tokens))


def question_parts(text):
    """-> (the question, the second question joined to it by «и» or '').  What of ``text`` is the question: the first sentence with a question in it (a remark after it, «Я постоянно путаюсь», goes), the talk
    before it («Слушай,», «Не помню,») gone, and of two questions joined by «и» the first («что такое РСВ и когда сдаётся» → «что такое РСВ»)."""
    text = ' '.join(str(text or '').split())
    parts = [p for p in _SENT.split(text) if p.strip()]
    pick = next((p for p in parts if p.rstrip().endswith('?') or qtype(p)), parts[0] if parts else '')
    split, tail = _JOIN.split(pick, maxsplit=1), ''
    if len(split) > 1 and _content(split[0]):
        pick, tail = split[0], split[1]
    clauses = [c for c in re.split(r'\s*[,:;—–]\s*|\s+-\s+', pick) if c.strip()]
    while len(clauses) > 1 and not _content(clauses[0]) and not qtype(clauses[0]):
        clauses.pop(0)
    return ', '.join(clauses), tail.strip()


# --- C24: rank2, the ranked path reads a spoken question kindly ----------------------------------------------------------------------------
# What a speaker adds around a question («объясни как другу», «неужели из-за соли», «ну что ли», «закончилась-то») is no part of it; the why-words are one kind. The guards
# stay as they were: a number, «не», a role, the kind of question and the word the bank never heard (a noun, a name, a verb of the fact) still decide.

_R2_PARTICLE = re.compile(r'(?<=\w)-(?:то|ка|таки|нибудь|либо)(?=\W|$)', re.I)
_R2_PHRASE = re.compile(r'[,;]?\s*(?<!\w)(?:в двух словах|на пальцах|по[- ]простому|простыми словами|как другу|как мне|если можно|покороче|если коротко|коротко|своими словами'
                        r'|по[- ]человечески|без лишних слов|в общем|вкратце)(?!\w)', re.I)
_R2_CLAUSE = re.compile(r'(?:,|\s)\s*(?:неужели|правда ли|что ли|разве|да ну|он что|она что|они что|ты что|мы выиграли|мы хоть|я что)(?!\w).*$', re.I)
_R2_TAIL = re.compile(r'[,\s]+(?:неужели|что ли|хоть|правда|да ну|ну)\s*(?=[?.!…]*$)', re.I)       # not «же» («одно и то же»), not «а»
_R2_WHY = re.compile(r'\bиз-за чего\b|\bотчего\b|\bчего ради\b|\bпо какой причине\b|\bв чем причина\b|\bв чём причина\b|\bкак так вышло\b')
R2_FRAME = frozenset({'название', 'перечислить', 'написать', 'раскрыть', 'назвать', 'понадобиться', 'потребоваться', 'оказаться', 'получиться', 'хоть', 'реально', 'неужели', 'разве', 'вообще-то', 'вроде', 'правда', 'впервые', 'изначально'})      # c25-b: «где впервые возник …»
# c25-b case 5: «когда и где», «где и когда»: two question words joined ask two kinds; a form of either is of the kind asked
_R2_TWO = re.compile(r'^\W*(?:а\s+|ну\s+)?(где|когда|откуда|в каком году)\s+и\s+(где|когда|откуда|в каком году)\b(.*)$', re.I)


# h28: how the owner really opens and closes a question («так, значит», «привет», «надо написать», «прям название»): a frame, however many of its words, is no part of it
_R3_HEAD = re.compile(r'^\W*(?:(?:так|значит|ну|вот|хорошо|ладно|привет|слушай|смотри|нет|да|а|теперь|сейчас|ещ[её]|давай|давайте|скажи|скажите|подскажи|подскажите|напомни|надо|нужно|написать|ответить|'
                      r'то есть|короче|кстати)(?!\w)[\s,.:;…—–-]*)+', re.I)
_R3_TAIL = re.compile(r'[,\s]+(?:прям\w*(?:\s+название)?|пожалуйста|вот так|да)\s*[?.!…]*$', re.I)


def chatter_off(text):
    """-> ``text`` with the speaker's own frame around the question taken out (never a number, «не», a name or a term)."""
    t = _R2_PARTICLE.sub('', str(text or ''))
    for rx in (_R3_HEAD, _R3_TAIL):
        cut = rx.sub('', t).strip(' ,;')
        if _WORD.search(cut) and (_content(cut) or re.search(r'\d', cut)):
            t = cut
    for rx in (_R2_CLAUSE, _R2_PHRASE, _R2_TAIL):
        cut = rx.sub('', t).strip(' ,;')
        if _WORD.search(cut) and (_content(cut) or re.search(r'\d', cut)):
            t = cut + ('?' if t.rstrip().endswith('?') and not cut.endswith('?') else '')
    return t


_R2_WHOM = re.compile(r'\bкому\b|\bкого\b|\bкем\b|\bо ком\b|\bу кого\b|\bот кого\b|\bс кем\b')


def _alt_is_cause_of_date(q, alt):
    """C24 index hygiene: a «почему» alt on an entry whose own question asks a date, a number, a person or a place: its answer is no cause (b01474 «Почему началась Смута?» → «В 1598 году»)."""
    return qtype2(alt) == 'why' and qtype2(q) in ('when', 'count', 'who', 'whom', 'where')


def qtype2(text):
    """``qtype`` with «из-за чего», «отчего», «чего ради» and «как так вышло» one kind with «почему» (a why asked another way), and «кто» apart from
    «кому/кого/кем» (the payer is not the payee)."""
    kind = qtype(text)
    low = ' ' + str(text or '').casefold().replace('ё', 'е') + ' '
    if re.search(r'\bне похож|\bразличи|\bотличи|\bчем разн|между ними\b|\bсравни\b', low) and kind in ('when', 'count'):
        return 'diff'                                     # «срок окупаемости … чем разные»: the word «срок» in a term does not ask a date
    if re.search(r'(?<!не )\bпохож\w*|\bсходств\w*|\bобщего\b|\bодинаков\w*', low):
        return 'sim'                                      # «чем X похож на Y» is not «чем X отличается от Y» (nor a deadline: «срок» in «срок окупаемости»)
    if kind in ('', 'how', 'what') and re.search(r'\bоткуда\b', ' ' + str(text or '').casefold() + ' '):
        return 'origin'                                   # «откуда взялся X» is not «кто такой X»
    if kind == 'who' and _R2_WHOM.search(' ' + str(text or '').casefold() + ' ') and not re.search(r'\bкто\b', str(text or '').casefold()):
        return 'whom'
    if kind in ('', 'how', 'what') and _R2_WHY.search(' ' + str(text or '').casefold() + ' '):
        return 'why'
    return kind


def _content(text):
    return [a for a in _atoms(text) if not _is_number(a) and a.atom not in STOPWORDS and a.atom not in TALK and a.atom not in QWORDS and a.atom not in FRAME
            and a.atom not in ('не', 'ни')]


def _terms(text, frame=frozenset()):
    """-> (content lemmas, numbers by value, «не»+next lemma pairs) of a text (``frame``: lemmas that are the speaker's, not the question's: rank2)."""
    atoms = _atoms(text)
    words, nums, nots = [], [], set()
    for k, a in enumerate(atoms):
        if _is_number(a):
            nums.append('#' + re.split(r'[:#]', a.atom)[-1])
        elif a.atom in ('не', 'ни'):
            nxt = next((b.atom for b in atoms[k + 1:k + 2]), '')
            if nxt not in _TALK_NOT:                    # «не помню», «не понял» is talk; «не такое», «не платит» is the question
                nots.add(nxt)
        elif a.atom not in STOPWORDS and a.atom not in TALK and a.atom not in QWORDS and a.atom not in FRAME and a.atom not in frame and len(a.atom) > 1:
            words.append(a.atom)
    return words, nums, nots


_HARMLESS = FRAME | {'быть', 'это', 'этот'}


def _beyond_row(text, row, partial=True):
    """c23: the ear's partial says more than the entry: from the first word the entry knows, a word neither its question side (``q``, ``alt``)
    nor its answer says («Куликовская битва она вообще что-то …» on «Когда была Куликовская битва?»). Such a partial is a longer question on
    its way, not the entry's: the index on the whole phrase is silent, so the ear must not answer its head. Frame words and question words
    («ну», «была», «когда») and «не»/numbers (the rules of their own) are no extra. At the ear's cut-off (``partial`` False) only a function word
    counts («она», «или», «через»: the sentence goes on); a content word there («простыми словами») is the ranked path's to weigh."""
    items = _items(text)
    known = [i for t in [row['q']] + list(row['alt']) for i in _items(t)]
    keys = set().union(*(i.keys for i in known if i.kind == 'w')) if known else set()
    keys |= set().union(*(i.keys for i in _items(row['answer']) if i.kind == 'w'))
    phons = {i.phon for i in known if i.kind == 'w'}
    atoms = {i.key for i in known}

    def has(i):
        return i.kind == 'w' and (bool(i.keys & keys) or any(_near(i.phon, p) for p in phons))

    start = next((k for k, i in enumerate(items) if has(i)), None)
    if start is None:
        return False
    return any((partial and i.kind == 'w' and not has(i)) or (i.kind == 'f' and i.key not in atoms and i.key not in _HARMLESS) for i in items[start:])


class Ranker:
    """The bank weighed for the ranked path: per entry the lemmas of its question side and of its answer, the IDF of each lemma over entries."""

    def __init__(self, entries, rank2=False, atoms_first=False, rejoin=False, rival_w=1.0, cover_min=None):
        self.entries, self.rank2, self.atoms_first, self.rejoin = entries, rank2, atoms_first, rejoin
        self.cover_min = RANK_COVER_MIN if cover_min is None else cover_min                       # U21-S8 (C5): the share of the heard words the entry must hold; RANK_COVER_MIN as it was
        self.rival_w = rival_w                           # U21-S6 (C2): how much the second best entry weighs in the margin; 1.0: all of it, as it was
        self._kind = qtype2 if rank2 else qtype
        self._compat = _COMPAT2 if rank2 else _COMPAT
        self._frame = R2_FRAME if rank2 else frozenset()
        self.qside, self.aside, self.forms, self.post = [], [], [], {}
        df = {}
        for n, row in enumerate(entries):
            forms = [_terms(t, self._frame) for t in [row['q']] + list(row['alt'])]
            q = set().union(*(set(f[0]) for f in forms))
            a = set(_terms(row['answer'], self._frame)[0])
            self.qside.append(q)
            self.aside.append(a - q)
            self.forms.append([(frozenset(f[0]), self._kind(t), frozenset(f[1]), frozenset(f[2])) for f, t in zip(forms, [row['q']] + list(row['alt']))])
            if atoms_first:                                  # U21-S4 (C1): the number atoms of the entry's forms, by the set a question must name whole
                for f in forms:
                    if f[1]:
                        self.post.setdefault('n:' + ','.join(sorted(set(f[1]))), []).append(n)
            for w in q | a:
                df[w] = df.get(w, 0) + 1
                self.post.setdefault(w, []).append(n)
                self.post.setdefault('s:' + _stem(w), []).append(n)
        self.n = max(len(entries), 1)
        self.idf = {w: math.log(1 + self.n / c) for w, c in df.items()}
        # a form that says what another form of the same entry says (the same lemmas, kind, numbers and «не») weighs the same and is read once: the scores are maxima over forms, so a repeat changes nothing (a third of the bank's forms)
        self.forms = [list(dict.fromkeys((f, t, fn, fx, sum(self.idf.get(w, 0.0) for w in f)) for f, t, fn, fx in forms)) for forms in self.forms]
        self.stem_of = {}
        for w in df:
            self.stem_of.setdefault('s:' + _stem(w), set()).add(w)

    def _resolve(self, w):
        """The bank's lemma for a heard lemma: itself, or one of the same snowball stem; '' when the bank never heard it."""
        if w in self.idf:
            return w
        same = self.stem_of.get('s:' + _stem(w))
        return max(same, key=lambda x: self.idf[x]) if same else ''

    def _joined(self, text):
        """U21-S5 (C3): ``text`` with a word the ear tore in two («стимулиру ющая») put back together: a token the bank never heard plus its next one, when the two make a word it knows; REJOIN_MAX joins at most."""
        toks, out, joins, i = text.split(), [], 0, 0
        while i < len(toks):
            if joins < REJOIN_MAX and i + 1 < len(toks):
                pair = _terms(toks[i], self._frame)[0]
                if pair and not all(self._resolve(w) for w in pair):
                    both = _terms(toks[i] + toks[i + 1], self._frame)[0]
                    if both and all(self._resolve(w) for w in both):
                        out.append(toks[i] + toks[i + 1])
                        joins, i = joins + 1, i + 2
                        continue
            out.append(toks[i])
            i += 1
        return ' '.join(out) if joins else ''

    def rank(self, text):
        """-> (scored list [(score, entry index, score with no hard rule)] best first, the facts of the question) for the question part of ``text``.
        U21-S5 (rejoin): when it holds a word the bank never heard, the text with torn words joined (C3), then the part that stands after a self-correction (C4), are ranked instead if they leave none."""
        got = self._rank_text(text)
        if not self.rejoin or not got[1]['unknown']:
            return got
        from .classifier import self_corrected                          # lazy: the classifier is not needed when the flag is off
        joined = self._joined(text)
        tries = [joined] if joined else []
        for base in [text] + tries:
            fixed = self_corrected(base)
            if fixed and fixed[1]:
                tries.append(fixed[1])
        for alt in tries:
            more = self._rank_text(alt)
            if more[0] and not more[1]['unknown']:
                return more
        return got

    def _rank_text(self, text):
        part, tail = question_parts(chatter_off(text) if self.rank2 else text)
        words, nums, nots = _terms(part, self._frame)
        tail_words = [self._resolve(w) or w for w in _terms(tail, self._frame)[0]] if tail else []
        nots = frozenset(self._resolve(w) or w for w in nots)
        kind = self._kind(part)
        two = _R2_TWO.match(part) if self.rank2 else None
        kinds = {kind} | ({self._kind(two[1] + two[3]), self._kind(two[2] + two[3])} - {''} if two else set())
        resolved = [(w, self._resolve(w)) for w in dict.fromkeys(words)]
        unknown = [w for w, r in resolved if not r]
        terms = [r for w, r in resolved if r]
        facts = {'part': part, 'tail': tail, 'tail_words': tail_words, 'kind': kind, 'terms': terms, 'unknown': unknown, 'nums': nums, 'nots': nots}
        mass = sum(self.idf[t] for t in terms)
        if not terms or mass < RANK_MIN_MASS:
            return [], facts
        seen = {}
        for t in terms:
            for e in self.post.get(t, ()):
                seen[e] = seen.get(e, 0.0) + self.idf[t]
        cands = sorted(seen, key=seen.get, reverse=True)[:RANK_TOP]
        if self.atoms_first and nums:                       # U21-S4 (C1): the entries of exactly this number are eligible before the cut, however many say the same words
            held = set(cands)
            cands += sorted((e for e in dict.fromkeys(self.post.get('n:' + ','.join(sorted(set(nums))), ())) if e in seen and e not in held), key=seen.get, reverse=True)[:RANK_ATOM_CAP]
        tset, nums, out = set(terms), frozenset(nums), []
        idf = self.idf.__getitem__                           # the sums below are the same sums in the same order as before: only the generator frames, the repeated type test and the global lookups are gone (this loop is most of a lookup)
        answer_w, form_w, form_min, cover_min = RANK_ANSWER_W, RANK_FORM_W, RANK_FORM_MIN, self.cover_min
        same_of, qside, aside = {}, self.qside, self.aside   # the kind of a form against the kinds asked: once per kind, not per form
        for e in cands:
            near = qside[e] | aside[e]
            best = soft = 0.0
            for f, ftype, fnums, fnots, fm in self.forms[e]:     # each question form of the entry on its own
                if not fm:
                    continue
                inq = sum(map(idf, tset & f))
                cover = (inq + answer_w * sum(map(idf, filter(near.__contains__, tset - f)))) / mass
                same = same_of.get(ftype)
                if same is None:
                    same = same_of[ftype] = 1.0 if ftype in kinds or not kind else RANK_TYPE_NEAR if any(_types_meet(k, ftype, self._compat) for k in kinds) else RANK_TYPE_MISS
                score = cover * (1 - form_w + form_w * inq / fm) * same
                if score > soft:
                    soft = score                                 # what the entry would weigh with no hard rule: the rival of the margin
                if fnums != nums or fnots != nots:              # a number or «не» of another question: never
                    continue
                if inq / fm < form_min or cover < cover_min:
                    continue                                     # the entry's own question not heard, or a heard word it never says
                if score > best:
                    best = score
            out.append((round(best, 4), e, round(soft, 4)))
        out.sort(reverse=True)
        return out, facts

    def tail_ok(self, e, tail):
        """A second question after the first («что такое X и чем он отличается от Y»): the first is answered (W11), but only when the second
        says something; «что такое X и почему» is speech cut off, no instant answer."""
        return bool(_terms(tail, self._frame)[0])

    def _other_number(self, k, nums):
        """F5: an entry whose every form names another number than the question («статья 88» for «статья 80») is no rival: it can never be it."""
        return bool(nums) and all(fn and fn != nums for _, _, fn, _, _ in self.forms[k])

    def asks_ok(self, e, facts, *, partial=False):
        """F5: does entry ``e`` answer what was asked. A personal question to the listener («а ты какую тему выбрал») is no bank question; a rare
        heard word the entry's question never says makes another question; on a partial, another entry that holds every heard word and more
        may be where the speech goes («какие источники финансирования …» → «… инвестиций бывают»)."""
        words = set(facts['part'].casefold().replace('ё', 'е').split())
        if words & _PERSONAL or not _kind_same(facts['kind'], self.entries[e], self._kind, self._compat):
            return False
        head = facts['terms'][0] if facts['terms'] else ''
        if head and self.idf[head] >= RANK_RARE and head not in self.qside[e]:
            return False                                 # the head of the question («амортизация» of «амортизация НМА») unsaid by the entry
        if partial:
            heard, answer = set(facts['terms']), self.entries[e]['answer']
            if any(heard < q for k, q in enumerate(self.qside) if k != e and self.entries[k]['answer'] != answer):
                return False
        return True

    def best(self, text, *, min_score=None, gap=None, partial=False):
        """-> (entry index, score, margin) when the ranked path is sure, else None."""
        ranked, facts = self.rank(text)
        if not ranked or facts['unknown']:
            return None
        score, e, _ = ranked[0]
        if facts['tail'] and not self.tail_ok(e, facts['tail']):
            return None
        if not self.asks_ok(e, facts, partial=partial):
            return None
        answer, nums = self.entries[e]['answer'], frozenset(facts['nums'])
        second = self.rival_w * max((soft for _, k, soft in ranked[1:] if self.entries[k]['answer'] != answer and not self._other_number(k, nums)), default=0.0)
        if score < (RANK_MIN if min_score is None else min_score) or score - second < (RANK_GAP if gap is None else gap):
            return None
        return e, score, score - second

    def explain(self, text, *, min_score=None, gap=None, partial=False):
        """U21-S3: why ``best`` gives none, mirrored step for step; '' when it would give an entry. A reason: no_terms | unknown_word | tail | asks |
        number | nots | form_min | cover_min | low_score | rival."""
        ranked, facts = self.rank(text)
        if not ranked:
            return 'no_terms'
        if facts['unknown']:
            return 'unknown_word'
        score, e, _ = ranked[0]
        if score <= 0:
            return self._zero_why(max(ranked, key=lambda r: r[2])[1], facts)
        if facts['tail'] and not self.tail_ok(e, facts['tail']):
            return 'tail'
        if not self.asks_ok(e, facts, partial=partial):
            return 'asks'
        answer, nums = self.entries[e]['answer'], frozenset(facts['nums'])
        second = self.rival_w * max((soft for _, k, soft in ranked[1:] if self.entries[k]['answer'] != answer and not self._other_number(k, nums)), default=0.0)
        if score < (RANK_MIN if min_score is None else min_score):
            return 'low_score'
        return 'rival' if score - second < (RANK_GAP if gap is None else gap) else ''

    def _zero_why(self, e, facts):
        """The hard rule that zeroed entry ``e`` (the one that would weigh most with none): the gate of ``rank`` its best form met last."""
        tset, nums, why = set(facts['terms']), frozenset(facts['nums']), 'low_score'
        mass, near, top = sum(self.idf[t] for t in tset), self.qside[e] | self.aside[e], -1.0
        for f, ftype, fnums, fnots, fm in self.forms[e]:
            inq = sum(self.idf[t] for t in tset & f)
            cover = (inq + RANK_ANSWER_W * sum(self.idf[t] for t in tset - f if t in near)) / mass
            if fm and inq / fm + cover > top:
                top = inq / fm + cover
                why = 'number' if fnums != nums else 'nots' if fnots != facts['nots'] else 'form_min' if inq / fm < RANK_FORM_MIN else 'cover_min' if cover < self.cover_min else 'low_score'
        return why


# --- the index and the ear's side ---------------------------------------------------------------------------------------------------------

@dataclass
class Hit:
    id: str
    q: str
    core: str
    answer: str
    source: str
    subject: str
    trust: str
    kind: str                           # 'bank' | 'material' | 'reference_kb' | 'law_base' | 'quick_math'
    text: str                           # what the ear had
    t: float
    early: bool                         # given on a partial: before the ear's cut-off
    ms: float                           # the lookup itself


def _adapters():
    def math(text):
        from .quick_math import answer          # noqa: PLC0415
        return answer(text)

    def kb(text):
        from .reference_kb import lookup        # noqa: PLC0415
        return lookup(text)

    def law(text):
        from .law_base import lookup            # noqa: PLC0415
        return lookup(text)
    return (('quick_math', math), ('reference_kb', kb), ('law_base', law))


_EXAMPLES = r'(?:\s+и\s+привед(?:и|ите)\s+примеры)?$'
_PAPER = ((re.compile(r'^(?:напиши|напишите|дай|дайте|сформулируй|сформулируйте|запиши|запишите|приведи|приведите)\s+определение\s+(?:(?:понятию|понятия|термину|термина)\s+)?(.+?)' + _EXAMPLES), r'что такое \1'),
          (re.compile(r'^раскрой(?:те)?\s+(?:вид\s+страхования|понятие|термин)\s+(.+?)' + _EXAMPLES), r'что такое \1'),
          (re.compile(r'^напиши(?:те)?\s+((?:где|когда|кто|что|как|какие|какой|какая|почему|зачем|сколько)\b.*)$'), r'\1'))


def paper_form(text):
    """h25: a question read off a sheet is put as written work puts it: «Напишите определение понятию государственный бюджет», «Раскройте вид страхования – личное страхование и приведите
    примеры», «Напишите, где и когда возник термин финансы». The same question the bank knows in its spoken form; anything else comes back as it is."""
    low = ' '.join(re.sub(r'[«»"„“.,:;!?—–]+', ' ', str(text or '').casefold().replace('ё', 'е')).split())
    for pattern, form in _PAPER:
        if pattern.match(low):
            return pattern.sub(form, low) + '?'
    return text


class Instant:
    def __init__(self, bank=(), *, material=None, adapters=None, clock=None, rank=True, rank2=False, atoms_first=False, rejoin=False, rival_w=1.0, cover_min=None):
        self.clock = clock or time.perf_counter
        rows = [r for r in (clean_entry(x) for x in list(bank or ())[:MAX_BANK]) if r]
        rows += material_entries(material)
        self.dropped_alts = []
        if rank2:                                        # C24: the index of rank2 holds no cause-alt of a date entry; the bank file is untouched
            for r in rows:
                keep = [a for a in r['alt'] if not _alt_is_cause_of_date(r['q'], a)]
                self.dropped_alts += [(r['id'], a) for a in r['alt'] if a not in keep]
                r['alt'] = keep
        self.entries = rows
        self.adapters = _adapters() if adapters is None else tuple(adapters)
        self.rank2 = bool(rank and rank2)                # C24: the ranked path reads a spoken question kindly; off: the W11/F5 path as it was
        self.ranker = Ranker(rows, self.rank2, bool(atoms_first), bool(rejoin), rival_w, cover_min) if rank else None
        self._words = None                              # ``near``: the words of each entry, on its first use
        self.forms, self.postings = [], {}
        for n, row in enumerate(rows):
            for text in [row['q']] + list(row['alt']):
                form = _form(n, text)
                if not form.words and not form.numbers:
                    continue
                k = len(self.forms)
                self.forms.append(form)
                for w in form.words:
                    for key in w.keys | {'d:' + d for d in (_deletions(w.phon) if len(w.phon) >= FUZZY_MIN else ())} | ({'d:' + w.phon} if len(w.phon) >= FUZZY_MIN else set()):
                        self.postings.setdefault(key, set()).add(k)
                for num in form.numbers:
                    self.postings.setdefault(num, set()).add(k)
        self.reset()

    def __len__(self):
        return len(self.entries)

    def for_call(self):
        """The same index with its own utterance state: everything built in ``__init__`` is only read during a call."""
        twin = copy.copy(self)
        twin.reset()
        return twin

    def reset(self):
        """A new utterance."""
        self.hit, self.cut, self._form, self._closed, self._uid = None, False, None, False, None

    def _candidates(self, heard):
        """The forms that can still be ``heard``: every one of the heard words has a posting of it (a lemma, a stem, a phonetic key, or for a long word one phonetic letter off).
        ``full_match``, ``could_become`` and the garbled-question-word match all need EVERY heard word aligned to a word of the form, so a form that misses the posting of any
        heard word is none of them: on a long question the union of the postings was ~1500 forms of 6000, the intersection is a handful. In the order of the union (the order of the first match)."""
        found, each = set(), []
        for w in heard.words:
            own = set()
            for key in w.keys:
                own |= self.postings.get(key, set())
            if len(w.phon) >= FUZZY_MIN:
                for d in _deletions(w.phon) | {w.phon}:
                    own |= self.postings.get('d:' + d, set())
            found |= own
            each.append(own)
        if not heard.words:
            for num in heard.numbers:
                found |= self.postings.get(num, set())
            return found
        every = set.intersection(*each)
        return [k for k in found if k in every]

    def feed(self, text, t, final=False, *, uid=None):
        """The ear's text so far (``final``: at its cut-off). -> ``Hit`` once per utterance, else None. Never raises."""
        try:
            if self._closed or (uid is not None and uid != self._uid):
                self.reset()
            self._uid = uid
            got = self._feed(str(text or ''), t, bool(final))
            if final:
                self._closed = True
            return got
        except Exception:                               # noqa: BLE001 - not sure: nothing
            return None

    def _feed(self, text, t, final):
        text = ' '.join(text.split())
        if self.hit is not None:                       # follow the utterance that has a hit
            if not self.cut and _WORD.search(text) and not self._same(text):
                self.cut = True
            return None
        if self.cut:
            return None
        found = self._match(text, t, final, ear=True)
        if found:
            self.hit, self._form = found
            return self.hit
        return None

    def _same(self, text):
        """Is ``text`` still the question of the hit: the full match of its form, or for a ranked hit the same entry ranked sure again."""
        if isinstance(self._form, tuple):
            got = self.ranker.best(text) if self.ranker else None
            same, row = bool(got) and got[0] == self._form[1], self.entries[self._form[1]]
        else:
            same, row = full_match(_form(-1, text), self._form), self.entries[self._form.entry] if 0 <= self._form.entry < len(self.entries) else None
        part = question_text(text)                       # c23: «… битва» hit, then «… битва она»: a word beyond the entry, the speech goes on into another question: cut
        return same and not (row is not None and _beyond_row(part if _WORD.search(part) else text, row))

    def near(self, text, limit=3):
        """``answer_witness``: the entries on the most words of ``text``, the best first: ``[(its question and answer, 'bank' | 'material')]``. Evidence that tells two numbers apart, never an answer: no rule of a match. Never raises."""
        try:
            if self._words is None:
                self._words = [frozenset(_terms(f"{row['q']} {row['answer']}")[0]) for row in self.entries]
            want = frozenset(_terms(text)[0])
            scored = sorted(((-len(want & words), n) for n, words in enumerate(self._words) if len(want & words) >= 2))[:limit]
            return [(f"{self.entries[n]['q']}. {self.entries[n]['answer']}", 'material' if self.entries[n].get('trust') == 'М' else 'bank') for _, n in scored]
        except Exception:                               # noqa: BLE001
            return []

    def lookup(self, text, *, final=True, bank_only=False):
        """The same match with no utterance behind it (the controller's ``_reference``): a ``Hit`` or None. Never raises."""
        try:
            found = self._match(' '.join(str(text or '').split()), self.clock(), bool(final), adapters=not bank_only)
            return found[0] if found else None
        except Exception:                               # noqa: BLE001
            return None

    def explain(self, text):
        """U21-S3: why the ear's way (``bank_eval.feed``: the text with no punctuation, partials, then the cut-off) gave none for ``text``: a reason word, or ''
        when it gives one. The RC causes of the design: truncated (RC1: the part kept before the question was cut short of the atoms), unknown_word (RC2),
        self_correction (RC3), rival (RC4), cover_min / low_score (RC6); the rest is the ranker's own word. Never raises."""
        try:
            said = ' '.join(re.sub(r'[^\w\s-]', ' ', str(text or '').lower().replace('ё', 'е')).split())
            if self._match(said, self.clock(), True, adapters=False, ear=True) is not None:
                return ''
            if self.ranker is None:
                return 'no_ranker'
            if self.rank2:
                said = chatter_off(said)
            said = paper_form(said)
            tokens = _WORD.findall(said.casefold())
            if not tokens or len(tokens) > MAX_HEARD_WORDS:
                return 'too_long'
            if _retracts(tokens):
                return 'self_correction'
            why = self.ranker.explain(said)
            part = ' '.join(re.sub(r'[^\w\s-]', ' ', question_parts(text)[0].lower().replace('ё', 'е')).split())      # the punctuation of the final text still cuts the talk off: the ear's way (no punctuation) does not
            if part and part != said and _WORD.search(part) and why and self._match(part, self.clock(), True, adapters=False, ear=True) is not None:
                return 'truncated'
            return why or 'gate'      # the ranked path would answer: a gate before it (_no_ask, a correction, two forms) held it
        except Exception:                               # noqa: BLE001
            return 'error'

    def _match(self, text, t, final, adapters=True, ear=False):
        start = self.clock()
        if self.rank2:
            text = chatter_off(text)
        text = paper_form(text)
        tokens = _WORD.findall(text.casefold())
        if not tokens or len(tokens) > MAX_HEARD_WORDS:
            return None
        whole = _form(-1, text)
        if final and _no_ask(text, tokens, whole):       # h28, class «a scrap of talk answered»: see _no_ask
            return None
        part, tail = question_parts(text)   # W11: the talk before the question and a second question after it are no part of the match
        heard = _form(-1, part if _WORD.search(part) else text)
        last = _atoms(tokens[-1])
        if not final and (tokens[-1] in DANGLING or not last or _is_number(last[-1])):
            return None
        if final and tail and self.rank2:                # h28, class «the bank's own question unheard»: a two-part form of a row («что идёт по дебету, а что по кредиту») is one question; split, it was silence
            own = [self.forms[k] for k in self._candidates(whole) if full_match(whole, self.forms[k])]
            if own:
                heard, tail = whole, ''
                part = text
        if _changes(text) and not (final and self.rank2 and any(full_match(whole, self.forms[k]) for k in self._candidates(whole))):
            return None
        kindof = qtype2 if self.rank2 else qtype
        full, open_, kind = {}, False, kindof(part)
        cands = self._candidates(heard)                  # one set for both passes below (its order is the order of the first match)
        for k in cands:
            form = self.forms[k]
            if full_match(heard, form) and _kind_same(kind, self.entries[form.entry], kindof, _COMPAT2 if self.rank2 else None):  # F5: «что такое НМА» is not answered by «какие бывают НМА»
                full.setdefault(self.entries[form.entry]['answer'], (form, self.entries[form.entry]))
            elif not final and could_become(heard, form):
                open_ = True
        if not full and final:                           # U30: the ear lost or garbled the question word («кто такое плотность»): every other word, number and «не» is a row's, so the row is asked
            asked, bare = _asked(heard), replace(heard, qwords=frozenset())
            for k in cands:
                form = self.forms[k]
                # the numbers and the count of the words first (full_match's own first test): of ~1500 candidate forms of a long question hardly one passes it, and the other two steps cost a regex and a copy each
                if heard.qwords != form.qwords and len(form.words) > 1 and heard.numbers == form.numbers and len(heard.words) == len(form.words) and _garbled(asked, _asked(form)) and full_match(bare, replace(form, qwords=frozenset())):
                    full.setdefault(self.entries[form.entry]['answer'], (form, self.entries[form.entry]))
        if len(full) > 1 and final and self.rank2:       # h28: two rows of one form: either is an answer to what was asked, and silence is none (120 of 6906 of the bank's own forms went silent). The row asked in its own «q» first, then the bank's order
            said = _form(-1, text)
            full = dict(sorted(full.items(), key=lambda kv: not full_match(said, _form(-1, kv[1][1]['q'])))[:1])
        if len(full) > 1 or (full and open_):
            return None
        if full and tail and not (self.ranker and self.ranker.tail_ok(self.entries.index(next(iter(full.values()))[1]), tail)):
            return None
        answers = {}
        if full:
            form, row = next(iter(full.values()))
            answers[row['answer']] = ('material' if row['trust'] == 'М' and row['source'] == 'материал' else 'bank', row, form)
        elif self.ranker is not None and not open_:
            got = self.ranker.best(text, min_score=None if final else max(RANK_MIN, RANK_PARTIAL_MIN), partial=not final)   # W11: the same margin on a partial
            if got:
                row = self.entries[got[0]]
                answers[row['answer']] = ('material' if row['trust'] == 'М' and row['source'] == 'материал' else 'bank', row, ('rank', got[0]))
        if final and adapters:
            for name, fn in self.adapters:
                try:
                    said = fn(text)
                except Exception:                      # noqa: BLE001
                    said = None
                if isinstance(said, str) and said.strip() and not (full and same_fact(next(iter(full)), said)):       # the owner's call of 06.11: «счёт 58» in the bank and in the chart, two wordings of one fact: no silence over a wording
                    answers.setdefault(said.strip(), (name, None, None))
        if len(answers) != 1:
            return None
        answer, (kind, row, form) = next(iter(answers.items()))
        if (ear or not final) and row is not None and _beyond_row(part if _WORD.search(part) else text, row, not final):   # c23: the ear's part (its cut-off too) says more than the entry: the cloud's final decides
            return None
        row = row or {'id': kind, 'q': text, 'core': core_of(answer), 'answer': answer, 'source': kind, 'subject': '', 'trust': 'Д'}
        core = row['core']
        told = _no_count_head(answer, part if _WORD.search(part) else text)       # h31 (F19): the count is cut by what was ASKED, not by the row
        if told != answer:
            answer, core = told, core_of(told)
        return Hit(row['id'], row['q'], core, answer, row['source'], row['subject'], row['trust'], kind, text, t, not final,
                   round((self.clock() - start) * 1000, 3)), form or heard


_ASKING = frozenset({'что', 'или', 'чём', 'чем', 'чего', 'дай', 'дайте', 'приведи', 'приведите', 'пример', 'примеры', 'объясни', 'объясните', 'определение', 'расскажи', 'расскажите', 'скажи', 'скажите', 'напомни', 'напомните', 'подскажи', 'подскажите'})


def _no_ask(text, tokens, whole):
    """h28: speech that asks nothing and names nothing, whatever the bank holds (the calls of 7 Nov, garbage talk): no content word at all («к два», «второй вопрос» → М2),
    a lone word with no question word («организации», «налогов», «деньги»), a clause cut on a dangling word («Деньги для»), a definition being said («денежная масса это все деньги в экономике»)."""
    if whole.qwords or _ASKING & set(tokens) or text.rstrip().endswith('?'):
        return False
    if not whole.words:
        return True
    if len(whole.words) + len(whole.numbers) < 2:
        return True
    if tokens[-1] in DANGLING:
        return True
    at = text.casefold().find(' это ')
    return at > 0 and len(_form(-1, text[at + 5:]).words) >= 2


def same_fact(one, other):
    """Two wordings of one fact: the numbers and the «не» of the shorter are in the longer, and at least half of its words."""
    short, long = sorted((_terms(one), _terms(other)), key=lambda terms: len(terms[0]))
    return set(short[1]) <= set(long[1]) and set(short[2]) <= set(long[2]) and len(set(short[0]) & set(long[0])) * 2 >= len(set(short[0]))


_built, _built_lock = {}, threading.Lock()         # one index per bank and material: a build costs 9-19 s of Python on the laptop, a call must not pay it


def _bank_stamp(path):
    try:
        got = Path(path).stat()
        return path, got.st_mtime_ns, got.st_size
    except OSError:
        return path, None, None


def from_settings(settings, *, material=None):
    """The index of a call, or None when ``instant`` is off. Built once per bank file and material; each call gets its own state over it."""
    if (settings or {}).get('instant') != 'on':
        return None
    path = (settings or {}).get('instant_bank_file') or ''
    rank = (settings or {}).get('instant_rank') == 'on'       # off by default: the ranker alone said 4 wrong of 22 on the held-out half, a wrong answer is worse than a late one
    rank2 = rank and (settings or {}).get('instant_rank2') == 'on'      # C24: a way of reading for the ranked path, off by default
    atoms = rank and (settings or {}).get('bank_atoms_first') == 'on'      # U21-S4: the entries of the question's number are scored before the cut; off by default
    rejoin = rank and (settings or {}).get('bank_rejoin') == 'on'      # U21-S5: torn words joined, the part after a self-correction ranked; off by default
    rival = (settings or {}).get('bank_rival_weight', 1.0)
    rival = float(rival) if isinstance(rival, (int, float)) and not isinstance(rival, bool) and 0 <= rival <= 1 else 1.0      # U21-S6: the weight of the rival in the margin, 1.0 = all of it, as it was
    cover = (settings or {}).get('bank_cover_min', RANK_COVER_MIN)
    cover = float(cover) if isinstance(cover, (int, float)) and not isinstance(cover, bool) and 0 <= cover <= 1 else RANK_COVER_MIN      # U21-S8: the cover floor of the ranked path, 0.6 as it was
    key = (_bank_stamp(path) if path else '', hash(material or ''), rank2, atoms, rejoin, rival, cover, ru_alignment.RANGES, rank)      # RANGES changes how numbers are read in the index

    with _built_lock:                              # a second call waits for the build under way instead of building its own
        index = _built.get(key)
        if index is None:
            index = Instant(load_bank(path) if path else [], material=material, rank=rank, rank2=rank2, atoms_first=atoms, rejoin=rejoin, rival_w=rival, cover_min=cover)
            _built.clear()
            _built[key] = index
    return index.for_call()


PARTIAL_MS = 200                    # the ear gives its text so far every this many ms of speech while ``instant`` is on (ear_shadow ``partial_ms``)


def for_home(settings, home):
    """``from_settings`` with the material of the profile (``materials/context.md``): built off the loop at the call's open. None when off or broken."""
    try:
        if (settings or {}).get('instant') != 'on':
            return None
        path = Path(home) / 'materials' / 'context.md'
        material = path.read_text(encoding='utf-8') if path.is_file() else None
        return from_settings(settings, material=material)
    except Exception:                                  # noqa: BLE001
        return None
