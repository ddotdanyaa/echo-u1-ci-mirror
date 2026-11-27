"""G6 (WAVE16): a stumble - the listener said a part of the portion and stopped: the cue begins with the very word they stopped before.

Property over 2000 portions of the bank's answers (the portioner's portions and whole sentences, for the long ones), every point of the stop, with the ear's
errors of N2 (``tools/rehearsal/ear_n2.json``: the substitutions seen, the rates) and the ones a speaker makes: another case, numbers in words, a word swallowed,
a word said twice, a stutter, a word of their own. The place is missed by one word at most. A retelling in the listener's own words never loses the place
nor sends it back. A number or a «не» said otherwise is no start of the portion: the whole portion again (a wrong figure is worse than a late cue).
``resume_word(heard, portion)``: ``(the rest of the portion, whether words were said twice)`` or None, the contract of ``ControlledMedia._said_of``."""
import difflib
import glob
import json
import random
import re
from pathlib import Path

import pytest

from echo_sync.portioner import portions
from echo_sync.ru_alignment import _canonical, resume_word

ROOT = Path(__file__).resolve().parents[1]
EAR = json.loads((ROOT / 'tools' / 'rehearsal' / 'ear_n2.json').read_text(encoding='utf-8'))
KINDS = ('clean', 'ear', 'case', 'digits', 'swallow', 'twice', 'stutter', 'own', 'filler', 'garble')
OWN = ('штука', 'вещь', 'короче', 'типа', 'собственно', 'вообще', 'конкретно', 'именно', 'просто', 'реально')
_SMALL = 'ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать'.split()
_TENS = 'двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split()
_HUNDREDS = 'сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот'.split()
NUMBER_WORDS = frozenset(_SMALL + _TENS + _HUNDREDS + ['тысяча', 'тысячи', 'тысяч', 'миллион', 'миллиона', 'миллионов'])
_THOUSANDS = {1: 'тысяча', 2: 'две тысячи', 3: 'три тысячи', 4: 'четыре тысячи'}


def spoken(n):
    """A cardinal in words, nominative (the ear writes them so)."""
    if n < 20:return _SMALL[n]
    out = []
    if n >= 1000:
        k, n = divmod(n, 1000)
        out.append(_THOUSANDS.get(k) or spoken(k) + ' тысяч')
    if n >= 100:out.append(_HUNDREDS[n // 100 - 1]);n %= 100
    if n >= 20:out.append(_TENS[n // 10 - 2]);n %= 10
    if n or not out:out.append(_SMALL[n]) if n else None
    return ' '.join(out)


KNOWN_GAPS = 4      # U42: the open gaps of the aligner on the ear's noise («доллар A1», a lost «на», an own «короче» among the words): at most this many of ~2500 scenes, the same budget as test_resume_last_word. The sample of portions moves with every change of the portioner, so a lucky zero is no bound


def corpus():
    """The portions of every answer of the bank, then the sentences of 5-14 words: 2000, the same every run."""
    short, long_ = [], []
    for name in sorted(glob.glob(str(ROOT / 'cloud_context' / 'bank' / 'merged' / '*.json'))):
        for row in json.loads(Path(name).read_text(encoding='utf-8')):
            short += [p.lstrip('—– ') for p in portions(row['answer']) if len(p.lstrip('—– ').split()) >= 2]      # U144: a portion may begin on the dash that joined it to the one before: the dash is no word, nobody says it
            long_ += [s for s in re.split(r'(?<=[.!?])\s+', row['answer']) if 5 <= len(s.split()) <= 14]
    rng = random.Random(16)
    short, long_ = sorted(set(short)), sorted(set(long_))
    return rng.sample(short, 1400) + rng.sample(long_, 600)


def word(token):
    return re.sub(r'^[^\w]+|[^\w]+$', '', token.lower().replace('ё', 'е'))


def cuts(tokens):
    """The points of a stop: after token k, never inside a number («300 | 000», «20 | %»), never before a bare mark."""
    for k in range(1, len(tokens)):
        a, b = tokens[k - 1], tokens[k]
        if not re.search(r'\w', b) or (re.search(r'\d', a) and (re.match(r'\d', b) or not re.search(r'[а-яё]{3}', b.lower()))):continue
        yield k


def ending(rng, w):
    if len(w) > 3 and w[-1] in 'аеиыяоуюй':return w[:-1] + rng.choice([v for v in 'аеиыяу' if v != w[-1]])
    return w + rng.choice(('а', 'у', 'ом', 'е'))


def say(rng, tokens, k, kind):
    """What the ear writes of the first ``k`` tokens said with ``kind``; and whether the place may be missed by one word more (a last word swallowed: nobody can know it was said)."""
    said = [word(t) for t in tokens[:k]]
    said = [w for w in said if w]
    slack = 0
    if kind == 'ear':
        out, lost = [], 0
        for w in said:
            roll = rng.random()
            if roll < EAR['del'] * 3:
                lost = lost + 1 if out and lost else 1;slack = max(slack, lost if lost > 1 else int(w is said[-1]))      # two and more lost in a row: nobody can know they were said
                continue
            lost = 0
            if roll < (EAR['del'] + EAR['sub']) * 3 and not re.search(r'\d', w) and w not in ('не', 'ни'):
                seen = EAR['subs'].get(w);w = rng.choices(list(seen), list(seen.values()))[0] if seen else ending(rng, w)
            out.append(w)
            if rng.random() < EAR['ins'] * 3:out.append(rng.choice(('э', 'а', 'ну', 'и')))
        if len(out) >= 2 and len(out[-1]) == 1 and len(said) >= 2 and out[-2] != said[-2] and said[-2] not in out[-3:]:slack = max(slack, 1)      # a word lost before the last «к»: the cue goes back, not past it
        said = out
    elif kind == 'case':
        at = [i for i, w in enumerate(said) if len(w) > 3 and not re.search(r'\d', w) and w not in ('не', 'ни') and not any(a.kind == 'n' for a in _canonical(w, (), True))]      # a number word misheard is the number's error: 'ear'
        if at:i = rng.choice(at);said[i] = ending(rng, said[i])
    elif kind == 'digits':
        group = lambda i: (i and said[i - 1].isdigit()) or (i + 1 < len(said) and said[i + 1].isdigit())      # «500 000» is said whole or not at all
        said = [spoken(int(w)) if w.isdigit() and int(w) < 10000 and not w.startswith('0') and not group(i) else w for i, w in enumerate(said)]
    elif kind == 'swallow' and len(said) >= 3:
        i = rng.randrange(1, len(said) - 1);said = said[:i] + said[i + 1:]
        slack = int(i == len(said) - 1 and len(said[-1]) == 1)      # «полный в» of «Полный перечень в»: the ear's added «в» looks the same; the cue goes back, never past a word not said
    elif kind == 'twice':
        i = rng.choice([i for i in range(len(said)) if not (i and said[i].isdigit() and said[i - 1].isdigit())])      # «300 000 000» is another number for anybody;said = said[:i + 1] + said[i:]
    elif kind == 'stutter':
        i = rng.randrange(len(said));w = said[i]
        if w.isdigit():return ' '.join(said), slack      # the ear writes digits: nobody stutters a digit
        head = re.match(r'[^аеиоуыэюя]*[аеиоуыэюя]?', w).group() or w[:1]
        said = said[:i] + [head + '-' + head, w] + said[i + 1:] if rng.random() < .5 else said[:i] + [head, w] + said[i + 1:]
    elif kind == 'own' and len(said) >= 3:
        i = rng.randrange(1, len(said) - 1)
        if not re.search(r'\d', said[i]) and said[i] not in ('не', 'ни'):said[i] = rng.choice(OWN)
    elif kind == 'filler':
        at = [i for i in range(len(said) + 1) if not (0 < i < len(said) and said[i - 1].isdigit() and said[i].isdigit())]      # not inside «200 000»
        fillers = [f for f in ('э', 'ну', 'вот', 'это', 'э-э') if f not in {word(t) for t in tokens}]      # a filler the portion says is the portion's word
        i = rng.choice(at);said = said[:i] + [rng.choice(fillers)] + said[i:]
    elif kind == 'garble':
        at = [i for i, w in enumerate(said) if len(w) >= 7 and not re.search(r'\d', w) and not any(a.kind == 'n' for a in _canonical(w, (), True))]
        if at:i = rng.choice(at);said[i] = said[i][2:]
    return ' '.join(said), slack


def protected_changed(tokens, k, heard):
    """The first of the said tokens whose number or «не»/«ни» what was heard does not say as written (left out, another value, one too many), or None.
    The cue has to begin there or before: a wrong figure is never passed over."""
    own = [word(t) for t in tokens[:k]]
    words = heard.split()
    said = [w for i, w in enumerate(words) if (not i or w != words[i - 1]) and not (i + 1 < len(words) and len(w) < len(words[i + 1]) and words[i + 1].startswith(w))]      # a word said twice is said once, a stutter is no word
    number = lambda w: bool(re.search(r'\d', w)) or w in NUMBER_WORDS or bool(re.match(r'(?:процент(?:ов|а|ы|ам|ах|ом|ами)?$|рубл(?:ь|я|ей|ю|ям|ях|ем|ями)$|доллар\w{0,3}$|евро$|копе\w{2,4}$|плюс$|минус$|[%₽$€])', w)) or any(atom.kind == 'n' for atom in _canonical(w, (), True))
    for at, w in enumerate(own):
        if (w in ('не', 'ни') and said.count(w) < own[:at + 1].count(w)) or (number(w) and w not in said and not (w.isdigit() and spoken(int(w)) in heard)
                                                                         and not (w.isalpha() and len(w) >= 4 and any(h.startswith(w[:max(4, len(w) - 2)]) for h in said))):return at      # a unit's word in another ending is the unit said
    extra = [w for w in said if (w in ('не', 'ни') and said.count(w) > own.count(w)) or (number(w) and w not in own and not any(o.startswith(w[:5]) for o in own if len(w) >= 5) and not any(o.isdigit() and w in spoken(int(o)).split() for o in own))]
    if not extra:return None
    spots = [b1 for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, said, own, autojunk=False).get_opcodes() for x in range(a1, a2) if said[x] in extra]
    return min(min(spots, default=0), k)


def words_in(tokens, k):
    """The words among the first ``k`` tokens: a dash is no word to miss."""
    return sum(1 for t in tokens[:k] if re.search(r'\w', t))


def place(portion, rest):
    """The token the rest begins with."""
    return len(portion[:len(portion) - len(rest)].split())


def scenes(seed=0):
    rng = random.Random(seed)
    for portion in corpus():
        tokens = portion.split()
        for k in cuts(tokens):
            kind = rng.choice(KINDS)
            heard, slack = say(rng, tokens, k, kind)
            yield portion, tokens, k, kind, heard, slack


def test_the_corpus_is_2000_portions_with_every_point_of_a_stop():
    rows = list(scenes())
    assert len(corpus()) == 2000 and len({r[0] for r in rows}) >= 1950 and len(rows) >= 4000


def test_a_stop_is_cued_from_the_word_it_stopped_before():
    """Every scene: the cue begins at the word after the last one said, one word off at most (two when the ear lost the last word said); a changed number or «не»: the whole portion."""
    misses = []
    for portion, tokens, k, kind, heard, slack in scenes():
        found = resume_word(heard, portion)
        wrong = protected_changed(tokens, k, heard)
        if wrong is not None:
            if found is not None and place(portion, found[0]) > wrong:misses.append((kind, heard, portion, k, 'protected', wrong, found))
            continue
        at = place(portion, found[0]) if found else 0
        if abs(words_in(tokens, at) - words_in(tokens, k)) > 1 + slack:misses.append((kind, heard, portion, k, at, found and found[0]))
    assert len(misses) <= KNOWN_GAPS, f'{len(misses)} misses, the first: ' + '\n'.join(map(repr, misses[:12]))


@pytest.mark.parametrize('heard,portion,rest', [
    ('общие', 'Общие условия установления налогов и сборов.', 'условия установления налогов и сборов.'),
    ('общие условия', 'Общие условия установления налогов и сборов.', 'установления налогов и сборов.'),
    ('общая условий', 'Общие условия установления налогов и сборов.', 'установления налогов и сборов.'),        # case
    ('об-об общие условия', 'Общие условия установления налогов и сборов.', 'установления налогов и сборов.'),  # stutter
    ('общие общие условия э', 'Общие условия установления налогов и сборов.', 'установления налогов и сборов.'),
    ('общие условия установ', 'Общие условия установления налогов и сборов.', 'установления налогов и сборов.'),  # a word cut off is the word they are on
    ('ставка двадцать процентов с', 'Ставка 20 % с 1 января.', '1 января.'),                                    # numbers in words, a unit
    ('в девятьсот', 'В 988 году крестили Русь.', '988 году крестили Русь.'),                                     # a number not finished: cued whole
    ('статья семнадцать', 'Статья 17 Налогового кодекса.', 'Налогового кодекса.'),
])
def test_examples(heard, portion, rest):
    assert resume_word(heard, portion)[0] == rest


@pytest.mark.parametrize('heard,portion,rest', [
    ('ставка восемнадцать процентов', 'Ставка 20 % с 1 января.', '20 % с 1 января.'),             # another number: the cue says the right one
    ('налог уплачивается', 'Налог не уплачивается до 15 числа.', 'не уплачивается до 15 числа.'),  # the «не» left out: the cue says it
])
def test_a_wrong_number_or_not_is_where_the_cue_begins(heard, portion, rest):
    assert resume_word(heard, portion)[0] == rest


@pytest.mark.parametrize('heard,portion', [
    ('что такое налог', 'Налог не уплачивается до 15 числа.'),                # a question, no start
    ('общие условия установления налогов и сборов', 'Общие условия установления налогов и сборов.'),   # the whole portion: no stumble
    ('', 'Общие условия.'),
])
def test_no_start(heard, portion):
    found = resume_word(heard, portion)
    assert found is None or place(portion, found[0]) == 0


@pytest.mark.parametrize('heard,portion,least', [
    # a retelling: the listener said it their own way, then a word of the portion: the place is at that word or after it, never before
    ('ну в общем условия установления', 'Общие условия установления налогов и сборов.', 3),
    ('программа чтобы работать с электронными', 'Программа для работы с электронными таблицами.', 5),
    ('короче хранят упорядочивают', 'В ней хранят, упорядочивают и анализируют данные.', 4),
])
def test_a_retelling_keeps_the_place(heard, portion, least):
    found = resume_word(heard, portion)
    assert found is not None and least <= place(portion, found[0]) <= least + 1


def retold(rng, tokens, k):
    """The first ``k`` tokens in the listener's words: a quarter of them their own (another word or a word left out), the last two the portion's."""
    said = [w for w in (word(t) for t in tokens[:k]) if w]
    out = []
    for i, w in enumerate(said):
        if i < len(said) - 2 and not re.search(r'\d', w) and w not in ('не', 'ни') and not any(a.kind in ('n', 'u') for a in _canonical(w, (), True)) and rng.random() < 1 / 4:
            out += rng.choice(([rng.choice(OWN)], []))
        else:out.append(w)
    return ' '.join(out)


def test_a_retelling_never_loses_the_place_nor_sends_it_back():
    """The 600 long sentences, every stop after the fourth word: retold, the cue begins at the stop, one word off: never lost, never sent back."""
    rng = random.Random(6)
    misses, rows = [], 0
    for portion in corpus()[1400:]:
        tokens = portion.split()
        for k in [k for k in cuts(tokens) if k >= 4]:
            heard = retold(rng, tokens, k);rows += 1
            if protected_changed(tokens, k, heard) is not None:continue
            found = resume_word(heard, portion)
            if found is None or abs(words_in(tokens, place(portion, found[0])) - words_in(tokens, k)) > 1:misses.append((heard, portion, k, found and found[0]))
    assert rows > 2000 and len(misses) <= KNOWN_GAPS, f'{len(misses)} of {rows}: ' + '\n'.join(map(repr, misses[:12]))


def test_a_whole_try_with_a_wrong_number_is_no_start_when_asked():
    """``wrong=False`` (the controller's whole try): a number said otherwise is no place to cue from but a wrong repeat; a stop before a number is a place as ever."""
    assert resume_word('ставка восемнадцать процентов с первого', 'Ставка 20 % с 1 января.', wrong=False) is None
    assert resume_word('о-о организации счет', 'организации, счёт 51', wrong=False)[0] == '51'


NOISE = ('clean', 'case', 'digits', 'twice', 'stutter', 'filler', 'garble')


def test_strict_forgives_the_noise_of_the_ear_and_of_a_stall():
    """R07's way (``strict``, what the controller asks when its own reading finds no clean start): another ending, a garbled word, numbers in words, a word said twice,
    a stutter, a filler: the place one word off at most, or the whole portion; never past a word not said right."""
    misses = []
    for portion, tokens, k, kind, heard, slack in scenes():
        if kind not in NOISE or protected_changed(tokens, k, heard) is not None:continue
        found = resume_word(heard, portion, strict=True)
        at = place(portion, found[0]) if found else None
        if at is not None and abs(words_in(tokens, at) - words_in(tokens, k)) > 1:misses.append((kind, heard, portion, k, at, found[0]))
    assert not misses, f'{len(misses)}: ' + '\n'.join(map(repr, misses[:12]))


@pytest.mark.parametrize('heard,portion', [
    ('общие установления налогов', 'общие условия установления налогов и сборов.'),        # a word left out
    ('условия общие установления', 'общие условия установления налогов и сборов.'),        # two swapped
    ('с подписью оплата', 'Без подписи оплата не пройдёт.'),                                # the preposition turned round
    ('статья восемнадцать', 'Статья 17 Налогового кодекса.'),                               # another number
    ('купили станок', 'Купили материалы для цеха.'),                                       # a word of the portion and one of their own
])
def test_strict_no_start(heard, portion):
    assert resume_word(heard, portion, strict=True) is None


@pytest.mark.parametrize('heard,portion,rest', [
    ('по показывает состояние', 'показывает состояние имущества', 'имущества'),           # a stutter
    ('о-о организации счет', 'организации, счёт 51', '51'),
    ('общие э условия', 'общие условия установления налогов и сборов.', 'установления налогов и сборов.'),
    ('в росии', 'в России составляет 20 процентов.', 'России составляет 20 процентов.'),   # the last word heard otherwise is cued again
])
def test_strict_examples(heard, portion, rest):
    assert resume_word(heard, portion, strict=True)[0] == rest


def test_resume_word_is_wired_to_started_behind_its_flag_off_by_default():
    """integ-c17 (coordinator): ``_started`` reads by ``resume_word`` only with the flag on; the flag is off by default and reaches the controller from the profile."""
    from pathlib import Path
    from types import SimpleNamespace
    from echo_sync.controlled_media import ControlledMedia
    from echo_sync.settings import DEFAULTS
    assert DEFAULTS['resume_word'] == 'off'
    # u13: the tuple of profile flags the host copies into the controller grew (B1+); the wiring is that 'resume_word' is a key of that tuple, not that it is the last one
    import re
    host_source = (Path(__file__).parents[1] / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
    from echo_sync.settings import controller_settings, resolve      # ROOT-1: one builder, controller_settings(), at construction: a key the profile changed reaches the controller
    assert controller_settings(resolve({'resume_word': 'on'}))['resume_word'] == 'on' and 'settings=controller_settings(profile_settings)' in host_source
    portion = 'Статья 17 Налогового кодекса устанавливает общие условия.'
    rest = resume_word('статья семнадцать налогового', portion)
    assert rest is not None
    on = SimpleNamespace(settings={**DEFAULTS, 'resume_word': 'on'})
    assert ControlledMedia._started(on, 'статья семнадцать налогового', portion) == resume_word('статья семнадцать налогового', portion, strict=True)
