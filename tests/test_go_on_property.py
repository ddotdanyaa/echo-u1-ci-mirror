"""g17-go-on: the owner's call after the phone (06.11): part of the answer or his own words, the last words of the cue at the end, and the next portion did not go. The rule of the laptop
(``most_said``, ``ends_like``, ``_try_went``, ``go_on`` in controlled_media) as a property over 3000 portions of the bank: what the owner says back goes on, what he says of his own does not, a changed number or
«не» does not, a question of another answer does not. The ear's errors are the rates of ``tools/rehearsal/ear_n2.json``. No model, no network: the rule is pure text."""
import glob
import json
import random
import re
from pathlib import Path

import pytest

from echo_sync.classifier import QUESTION, QUESTION_WORDS, analyze, strip_fillers
from echo_sync.fast_text import _atoms, _said_words, ends_like, most_said
from echo_sync.portioner import portions
from echo_sync.settings import CALL_SETTINGS
from echo_sync.textutil import norm_words

ROOT = Path(__file__).resolve().parents[1]
EAR = json.loads((ROOT / 'tools/rehearsal/ear_n2.json').read_text(encoding='utf-8'))
N = 3000
WORD = re.compile(r'\d{1,3}(?:\u00a0| )\d{3}(?!\d)|\d+(?:[.,:/–-]\d+)*[\w-]*|[\w-]+', re.U)      # «250 000», «50.01», «55-1», «17.09.2020», «204н» are one word
NUMBER = re.compile(r'^\d+$')
MULTIPLIER = re.compile(r'^(?:тысяч|миллион|миллиард|трлн|млн|млрд|тыс)', re.I)      # «50 тысяч» without «тысяч» is another number
OWN = ['ну значит', 'своими словами', 'короче говоря', 'то есть', 'в общем', 'ну это про то что']


def _bank():
    found = []
    for name in sorted(glob.glob(str(ROOT / 'cloud_context/bank/merged/*.json'))):
        for entry in json.loads(Path(name).read_text(encoding='utf-8')):
            found += [(entry['q'], portion) for portion in portions(entry['answer'], CALL_SETTINGS)]
    return found


BANK = _bank()
_rng = random.Random(17)
SAMPLE = _rng.sample(BANK, N) if len(BANK) > N else BANK
QUESTIONS = sorted({q for q, _ in BANK})


def go_on(heard, portion):
    """What one try of the owner does on the laptop's rule: the next portion, or the same one said again (``ControlledMedia._try_went`` with one try). A question is no try: the cloud's final
    goes on only on what the classifier keeps quiet or takes for a replay, and the ear's try is no question either (``_tempo_said``)."""
    said = strip_fillers(heard, CALL_SETTINGS)
    state = {'chunks': ['Первая часть ответа.', portion], 'chunk_index': 1, 'revision': 1}
    return analyze(heard, state, [], CALL_SETTINGS).kind != QUESTION and (most_said(said, portion) or ends_like(said, portion))


# --- what the owner says ----------------------------------------------------------------------------------------------------------
_UNITS = 'ноль один два три четыре пять шесть семь восемь девять'.split()
_TEENS = 'десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать'.split()
_TENS = ' десять двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split(' ')
_HUNDREDS = ' сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот'.split(' ')


def spoken(n):
    """A number as the owner says it, nominative («сорок восемь»; «одна тысяча» is said «тысяча»)."""
    if n == 0:
        return 'ноль'
    out = []
    if n >= 1000:
        k, n = divmod(n, 1000)
        out += ([] if k == 1 else [spoken(k).replace('один', 'одна').replace('два', 'две') if k % 10 in (1, 2) and k % 100 not in (11, 12) else spoken(k)]) + [
            'тысяча' if k % 10 == 1 and k % 100 != 11 else 'тысячи' if k % 10 in (2, 3, 4) and k % 100 not in (12, 13, 14) else 'тысяч']
    if n >= 100:
        out.append(_HUNDREDS[n // 100]); n %= 100
    if 10 <= n < 20:
        out.append(_TEENS[n - 10]); n = 0
    elif n >= 20:
        out.append(_TENS[n // 10]); n %= 10
    if n:
        out.append(_UNITS[n])
    return ' '.join(out)


def words(text):
    return list(WORD.finditer(text))


def put(portion, ms, changes=None, start=0):
    """``portion`` from its word ``start`` on, as it is written (its commas and dashes: «35 — 700» is no «35 700»), with the words ``changes`` names said otherwise (None: lost)."""
    out, at = [], ms[start].start() if ms else 0
    for j, m in enumerate(ms[start:], start):
        if j in (changes or {}):
            out.append(portion[at:m.start()] + (changes[j] or ''))
            at = m.end()
    return re.sub(r'\s+', ' ', ''.join(out) + portion[at:]).strip()


def content(word):
    """A content word as the rule counts it (``fast_text._said_words``), no part of a number («D7», «тысяч», «двух целых»)."""
    return not number(word) and not MULTIPLIER.match(word) and bool(_said_words(_atoms(word)))


def number(word):
    return bool(re.search(r'\d', word)) or bool(re.match(r'(?:цел|десят|сот|тысячн)ы[хм]', word.lower())) or any(atom.kind == 'n' or atom.atom.startswith(('#', '!spoken:')) for atom in _atoms(word))


def in_words(portion, ms):
    return put(portion, ms, {j: spoken(int(m.group())) for j, m in enumerate(ms) if NUMBER.match(m.group()) and len(m.group()) <= 6})


def in_pairs(portion, ms):
    """A number of four digits read in pairs: «тридцать два десять» for 3210."""
    return put(portion, ms, {j: f'{spoken(int(w[:2]))} {spoken(int(w[2:]))}' for j, w in enumerate(m.group() for m in ms) if NUMBER.match(w) and len(w) == 4 and w[0] != '0' and w[2] != '0'})


def ear(portion, ms, rng):
    """The local ear's errors at the rates it was measured with: a word lost, a word of its own put in, a word heard as another (never a number or a «не»: those are the cases of their own; an ear
    that loses the «не» the owner put in has heard the portion as it is, and the controller cannot know better until the cloud's final, which comes after the next portion: a risk named in the report)."""
    subs = [w for heard in EAR['subs'].values() for w in heard]
    changes = {}
    for j, m in enumerate(ms):
        roll, w = rng.random(), m.group()
        if w.lower() in ('не', 'ни') or number(w):      # the ear's errors on a number: its veto (``local_ear_number_veto``) keeps the portion for a second try, by design
            continue
        if roll < EAR['del']:
            changes[j] = None
        elif roll < EAR['del'] + EAR['sub'] and not number(w):
            changes[j] = rng.choice(subs)
        if rng.random() < EAR['ins']:
            changes[j] = (changes.get(j, w) or '') + ' ' + rng.choice(subs)
    return put(portion, ms, changes)


# --- the property --------------------------------------------------------------------------------------------------------------------
def _cases():
    rng = random.Random(1706)
    for q, portion in SAMPLE:
        yield from _cases_of(portion, q, rng)


def _cases_of(portion, q, rng):
    """What the owner may say to ``portion`` of the answer to ``q``: (what it should do, the kind, the text)."""
    if True:
        ms = words(portion)
        ws = [m.group() for m in ms]
        rich = [j for j, w in enumerate(ws) if content(w)]
        numbers = [j for j, w in enumerate(ws) if NUMBER.match(w)]           # plain numbers: these are changed, read in words and in pairs
        items = sorted(rich + [j for j, w in enumerate(ws) if number(w)])
        if items:
            yield 'go', 'verbatim', portion, portion
        kept = [j for j in rich if not (j and ws[j - 1].lower() in ('не', 'ни')) and not (j and j + 1 < len(ws) and number(ws[j - 1]) and number(ws[j + 1]))]      # the word of a «не» is no word lost:
        # «не 25-го числа» for «не позднее 25-го числа» is another meaning; nor the word between two numbers: «пункт 1 217» is 1217
        if kept and len(rich) >= 2 and len(items) >= 4:
            yield 'go', 'a word lost', put(portion, ms, {rng.choice(kept): None}), portion
        heads = [j for j in items if not (number(ws[j]) and j - 1 in items and number(ws[j - 1]))]       # «2,4 миллиона» is one number
        if len(heads) >= 2 and rich:
            start = heads[-2]
            while start and (number(ws[start - 1]) or ws[start - 1].lower() in ('не', 'ни')):      # a number or «не» is said with its word
                start -= 1
            if ws[start].lower() not in QUESTION_WORDS:      # «своими словами какой применяет»: the classifier hears a question in it (walk 2420): when to cue is g5's, not this rule's
                yield 'go', 'own words, its end', f'{rng.choice(OWN)} {put(portion, ms, start=start)}', portion
        if numbers and any(len(ws[j]) <= 6 for j in numbers):
            yield 'go', 'numbers in words', in_words(portion, ms), portion
        if any(len(ws[j]) == 4 for j in numbers):
            yield 'go', 'a number in pairs', in_pairs(portion, ms), portion
        if len(items) >= 4:
            cut = ms[items[len(items) // 2 - 1]].end()
            yield 'go', 'two parts', portion[:cut] + ' | ' + portion[cut:].lstrip(' ,:;—-'), portion
        if len(rich) >= 4 and len(items) >= 6:
            yield 'stay', 'a part and a pause', portion[:ms[items[1]].end()], portion        # two of six or more: a start, its help is from the word it stopped at
        other = rng.choice(QUESTIONS)
        if other != q:
            yield 'stay', 'another question', other, portion
        if numbers:
            j = rng.choice(numbers)
            changed = str(int(ws[j]) + rng.choice([1, 2, 5, 10]))
            yield 'stay', 'a number changed', put(portion, ms, {j: changed}), portion
            yield 'stay', 'a number changed, in words', put(portion, ms, {j: spoken(int(changed))}) if len(changed) <= 6 else portion + ' 999', portion
        if rich:
            nots = {j: None for j, w in enumerate(ws) if w.lower() == 'не'}
            if nots:
                yield 'stay', '«не» lost', put(portion, ms, nots), portion
            else:
                j = rng.choice(rich)
                yield 'stay', '«не» put in', put(portion, ms, {j: 'не ' + ws[j]}), portion
        heard = ear(portion, ms, rng)
        if heard != put(portion, ms):
            yield 'ear', 'the ear', heard, portion


CASES = list(_cases())


def test_the_bank_gives_the_portions():
    assert len(SAMPLE) == N and len(CASES) > 4 * N


@pytest.mark.parametrize('kind', ['verbatim', 'a word lost', 'own words, its end', 'numbers in words', 'a number in pairs'])
def test_what_is_said_back_goes_on(kind):
    cases = [(h, p) for want, k, h, p in CASES if k == kind]
    missed = [(h, p) for h, p in cases if not go_on(h, p)]
    assert cases and not missed, f'{kind}: {len(missed)} of {len(cases)} stay, e.g. {missed[:5]}'


@pytest.mark.parametrize('kind', ['a part and a pause', 'another question', 'a number changed', 'a number changed, in words', '«не» lost', '«не» put in'])
def test_what_is_not_the_portion_stays(kind):
    cases = [(h, p) for want, k, h, p in CASES if k == kind]
    went = [(h, p) for h, p in cases if go_on(h, p)]
    assert cases and not went, f'{kind}: {len(went)} of {len(cases)} go on, e.g. {went[:5]}'


def test_the_ear_goes_on_at_the_first_try_mostly_and_never_past_a_lost_not():
    """The ear's errors (ear_n2: 5 % of words heard as another, 1.8 % lost, 1 % put in): a word of its own may be a word changed, that try is said again once and the second goes on
    (``_try_went``, the controller's test below). At the first try two of three go on now (608 of 919 at seed 1706); a «не» the ear lost never does."""
    cases = [(h, p) for want, k, h, p in CASES if k == 'the ear']
    went = [(h, p) for h, p in cases if go_on(h, p)]
    assert len(went) >= 0.6 * len(cases), f'{len(went)} of {len(cases)}'
    assert not [(h, p) for h, p in went if 'не' in p.lower().split() and 'не' not in h.lower().split()]


# --- the controller ----------------------------------------------------------------------------------------------------------------------
# The real NativeMediaSocket, ShadowEar and controller on the injected clock (``test_h3_tempo.Rig``), the job answers with an answer of the bank. The owner's words reach it twice, as on the phone: the ear's
# text and, a little later, the cloud's final of the same utterance. A final the job is asked about is declined («—»): it is no question.

import helpers_s6_state as S       # noqa: E402
from test_h3_tempo import TICK, Rig       # noqa: E402

ENTRIES = [entry for name in sorted(glob.glob(str(ROOT / 'cloud_context/bank/merged/*.json'))) for entry in json.loads(Path(name).read_text(encoding='utf-8'))]


class Owner:
    def __init__(self, monkeypatch, entry, ear_errors=None):
        """The question; the job answers it with the bank's answer, unless the reference base («статья 14 НК», «счёт 44») has answered first: then that is the plan walked."""
        self.rig = rig = Rig(monkeypatch, fast_text='on', max_auto_repeats=3)
        rig.w.feed(S.turn_created('u1', 'user', entry['q'].split()[0]))
        rig.w.feed(S.turn_done('u1', 'user', entry['q']))
        for _ in range(40):
            rig.pump(TICK)
            if rig.fake.runs or rig.cues():
                break
        self.job = 0
        if rig.fake.runs and not rig.cues():
            rig.job_says(0, entry['answer'])
            rig.job_ends(0)
            self.job = 1
        assert rig.cues() and rig.c.state(), 'precondition: the question was answered'
        self.turn, self.ear_errors = 2, ear_errors

    def says(self, text, heard=None):
        """One utterance: the ear's text (``heard``, with the ear's errors when ``ear_errors`` is a generator), then the cloud's final of it."""
        rig = self.rig
        rig.says(heard or (ear(text, words(text), self.ear_errors) if self.ear_errors else text), speech=1.0)
        rig.w.feed(S.turn_created(f'u{self.turn}', 'user', text.split()[0]))
        rig.w.feed(S.turn_done(f'u{self.turn}', 'user', text))
        self.turn += 1
        rig.pump(TICK)
        while len(rig.fake.runs) > self.job:
            if not (rig.fake.runs[self.job].cancelled.is_set() or rig.fake.runs[self.job].ended.is_set()):      # a job a newer final cancelled is no job to answer (an error of the stand)
                rig.job_says(self.job, '—')
                rig.job_ends(self.job)
            self.job += 1
        rig.pump(0.4)

    def plan(self):
        state = self.rig.c.state()
        return state['revision'], state['chunks'], state['chunk_index']


def _walk(monkeypatch, entry, rng, kinds=None, ear_errors=None):
    """The owner goes through the answer, one variant per portion; after one that is no try at it, the portion word for word. What went wrong, or None; ``steps``: how many were judged."""
    owner, steps = Owner(monkeypatch, entry, ear_errors), 0
    try:
        while True:
            revision, chunks, i = owner.plan()
            if i >= len(chunks) - 1:
                return None
            cases = [(want, kind, heard) for want, kind, heard, _ in _cases_of(chunks[i], entry['q'], rng) if kinds is None or kind in kinds]
            if not cases:
                return None
            want, kind, heard = rng.choice(cases)
            said, own = norm_words(heard), norm_words(chunks[i])
            # c23-final(B): the last word lost leaves a clean start of the portion that stopped: by default it is helped with the rest, as test_h3_tempo.test_a_start_with_its_neighbours
            # pins («общие условия установления налогов» → «и сборов.»); the owner's rule (repeat_rule, off by default, c22-repeat) takes it as said; the ear's own errors may make it a try.
            # Either is right: it goes on once, or it is helped and the portion waits (then said whole); never a false step or a double
            start = kind == 'a word lost' and 0 < len(said) < len(own) and own[:len(said)] == said
            if want == 'stay':
                found = _step(owner, 'stay', kind, heard, revision, chunks, i)
                if found or owner.plan()[0] != revision:
                    return found
                want, kind, heard = 'go', 'verbatim after it', chunks[i]
            found = _step(owner, want, kind, heard, revision, chunks, i)
            if found and start and owner.plan()[0] == revision and owner.plan()[2] == i and chunks[i + 1] not in found[3]:
                found = _step(owner, 'go', 'verbatim after it', chunks[i], revision, chunks, i)
            steps += 1
            if found or want == 'ear' and owner.plan()[2] == i:
                return found
    finally:
        _walk.steps = getattr(_walk, 'steps', 0) + steps
        owner.rig.close()


def _step(owner, want, kind, heard, revision, chunks, i):
    before = len(owner.rig.cues())
    owner.rig.pump(0.6)
    for said in heard.split(' | '):
        owner.says(said)
    owner.rig.pump(0.8)
    new = [cue.text for cue in owner.rig.cues()[before:]]
    now, after, j = owner.plan()
    went = now == revision and j == i + 1
    once = new.count(chunks[i + 1]) <= (2 if kind == 'two parts' else 1)      # the first breath may go on alone (three fifths), the timer says the next portion again while the owner ends the first
    if want == 'go' and not (went and once and chunks[i + 1] in new and (i + 2 >= len(chunks) or chunks[i + 2] not in new)):
        return kind, heard, chunks[i], new
    if want in ('stay', 'ear') and now == revision and (j > i + 1 or new.count(chunks[i + 1]) > 1 or want == 'stay' and (j != i or chunks[i + 1] in new)):
        return kind, heard, chunks[i], new
    return None


def test_a_question_the_ear_heard_is_no_try_at_the_portion(monkeypatch):
    """«Что такое налоговые органы?» asked over «банки и налоговые органы.»: the ear took it for a try (a word of the portion), it ended like the portion, and the next portion of the old answer
    went on top of the new question."""
    # integ-c17: g15 (the first portion ends on a finished thought) keeps «Отчётность видят собственники, банки и налоговые органы.» one portion: the portion that ends on «налоговые органы» is the second here
    owner = Owner(monkeypatch, {'q': 'Кто видит отчётность?', 'answer': 'Отчётность видят собственники. Её видят банки и налоговые органы. Её сдают в срок раз в год.'})
    try:
        owner.says('Отчётность видят собственники')
        assert owner.plan()[2] == 1, 'precondition: the second portion waits'
        owner.rig.pump(0.6)
        owner.rig.says('Что такое налоговые органы?', speech=1.0)
        owner.rig.pump(0.3)
        assert 'Её сдают в срок раз в год.' not in owner.rig.said()
    finally:
        owner.rig.close()


WALKS = 60


@pytest.mark.parametrize('seed', range(WALKS))
def test_the_owner_walks_through_an_answer(monkeypatch, seed):
    """A walk of the bank on the controller: every portion said back in one of the ways goes on once, a part, a changed number or «не», another question do not."""
    rng = random.Random(seed)
    found = _walk(monkeypatch, rng.choice(ENTRIES), rng)
    assert found is None, found


@pytest.mark.parametrize('seed', range(WALKS))
def test_the_owner_walks_through_an_answer_as_the_ear_hears_it(monkeypatch, seed):
    """The same with the ear's errors on the ear's text (ear_n2), the cloud's final as said: the two disagree as on the phone, and still one portion goes on per try."""
    rng = random.Random(10_000 + seed)
    found = _walk(monkeypatch, rng.choice(ENTRIES), rng, ear_errors=random.Random(seed))
    assert found is None, found


@pytest.mark.parametrize('q,answer,said', [
    # the ear's try went on; the cloud's final of the same words came then, judged against the new portion: a wrong repeat, and it was cued a second time
    ('Какие источники финансирования бывают?', 'Собственные и заёмные. Собственные: уставный капитал, прибыль, добавочный капитал. Заёмные — кредиты: долгосрочный на станки, краткосрочный на сырьё.',
     'своими словами Собственные и заёмные.'),
    # ... or it ended like the new portion too («календарный год»), and that one went on as well: two portions for one try
    ('Какой налоговый период по НДФЛ?', 'Календарный год. Налоговым периодом по НДФЛ признаётся календарный год.', 'ну значит Календарный год.'),
])
def test_the_clouds_final_of_a_try_that_went_on_is_that_try(monkeypatch, q, answer, said):
    owner = Owner(monkeypatch, {'q': q, 'answer': answer})
    try:
        revision, chunks, i = owner.plan()
        owner.rig.pump(0.6)
        owner.says(said)
        owner.rig.pump(0.8)
        assert owner.plan()[2] == 1 and owner.rig.said() == chunks[:2], owner.rig.said()
    finally:
        owner.rig.close()


def test_one_try_is_one_portion_when_the_next_says_the_same(monkeypatch):
    """Walk 1350: the answer says its first portion twice («Расчёты с поставщиками и подрядчиками.» and «...подрядчиками:»); the final of the try said the next one too, and two went on."""
    answer = 'Расчёты с поставщиками и подрядчиками. Расчёты с поставщиками и подрядчиками: что мы им должны и какие авансы им выдали.'
    owner = Owner(monkeypatch, {'q': 'Что учитывают на счёте 60?', 'answer': answer})
    try:
        revision, chunks, i = owner.plan()
        owner.rig.pump(0.6)
        owner.says('ну это про то что поставщиками и подрядчиками.')
        owner.rig.pump(0.8)
        assert owner.plan()[2] == 1 and owner.rig.said() == chunks[:2], owner.rig.said()
    finally:
        owner.rig.close()


def test_the_final_that_says_the_portion_before_is_that_try(monkeypatch):
    """Walk 5115 with the ear's errors: the ear lost a word and went on; the final said the portion word for word, and it said most of the next one too («законодательство субъектов Российской
    Федерации о налогах и сборах»): it went on once more."""
    answer = 'законодательство Российской Федерации о налогах и сборах, законодательство субъектов Российской Федерации о налогах и сборах, нормативные правовые акты представительных органов.'
    owner = Owner(monkeypatch, {'q': 'Что входит в законодательство о налогах?', 'answer': answer})
    try:
        revision, chunks, i = owner.plan()
        assert chunks[0].startswith('законодательство Российской') and chunks[1].startswith('законодательство субъектов'), chunks
        owner.rig.pump(0.6)
        owner.says(chunks[i], heard=chunks[i].replace('налогах', ''))
        owner.rig.pump(0.8)
        assert owner.plan()[2] == i + 1 and owner.rig.said()[-1] == chunks[i + 1], (chunks, owner.rig.said())
    finally:
        owner.rig.close()


def test_the_rest_of_a_portion_said_in_two_breaths_is_no_try_at_the_next(monkeypatch):
    """Walk 2648: «Главный бухгалтер» went on, «или бухгалтер и кассир.» (the rest of it) was counted as a first try at «При отсутствии главного бухгалтера», and the owner's next words, a «не» put in,
    were its second try: they went on whatever they said."""
    owner = Owner(monkeypatch, {'q': 'Кто подписывает кассовые документы?', 'answer': 'Главный бухгалтер или бухгалтер и кассир. При отсутствии главного бухгалтера и бухгалтера подписывает руководитель.'})
    try:
        revision, chunks, i = owner.plan()
        assert chunks[1] == 'При отсутствии главного бухгалтера', chunks
        owner.rig.pump(0.6)
        owner.says('Главный бухгалтер')
        owner.says('или бухгалтер и кассир.')
        owner.rig.pump(0.8)
        assert owner.plan()[2] == 1, owner.rig.said()
        owner.says('При отсутствии главного не бухгалтера')
        owner.rig.pump(0.8)
        assert owner.plan()[2] == 1 and chunks[2] not in owner.rig.said(), owner.rig.said()
    finally:
        owner.rig.close()


def test_a_try_at_the_next_portion_is_no_final_of_the_try_before(monkeypatch):
    """Walk 21011: «Внеоборотные и активы.» went on; «ну это про то что внеоборотные активы,», a try at «Первый раздел внеоборотные активы,», said only words of that try and was taken for its final."""
    owner = Owner(monkeypatch, {'q': 'Из каких разделов состоит актив баланса?', 'answer': 'Внеоборотные и оборотные активы. Первый раздел внеоборотные активы, второй раздел оборотные активы.'})
    try:
        revision, chunks, i = owner.plan()
        assert chunks[1] == 'Первый раздел внеоборотные активы,', chunks
        owner.rig.pump(0.6)
        owner.says('Внеоборотные и активы.')
        owner.rig.pump(0.8)
        assert owner.plan()[2] == 1, owner.rig.said()
        owner.says('ну это про то что внеоборотные активы,')
        owner.rig.pump(0.8)
        assert owner.rig.said() == chunks[:3], owner.rig.said()
    finally:
        owner.rig.close()


def test_a_new_breath_that_ends_like_the_waiting_portion_goes_on_when_the_one_before_ended_alike(monkeypatch):
    """Walk 30071: the answer says «Прочие доходы и расходы.» and then «Прочие доходы и расходы,»; the owner's try at the second was taken for the rest of the first, and nothing went on."""
    answer = 'Прочие доходы и расходы. Прочие доходы и расходы, не связанные с основной деятельностью: продажа активов, проценты, штрафы, курсовые разницы.'
    owner = Owner(monkeypatch, {'q': 'Что учитывают на счёте 91?', 'answer': answer})
    try:
        revision, chunks, i = owner.plan()
        assert chunks[:2] == ['Прочие доходы и расходы.', 'Прочие доходы и расходы,'], chunks
        owner.rig.pump(0.6)
        owner.says('то есть доходы и расходы.')
        owner.rig.pump(0.8)
        owner.says('короче говоря доходы и расходы,')
        owner.rig.pump(0.8)
        assert owner.rig.said() == chunks[:3], owner.rig.said()
    finally:
        owner.rig.close()
