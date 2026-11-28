"""G15: the first portion ends on a finished thought. Owner's calls of 06.11: «Счёт 69 — расчёты», «ПКО КО-1 — приходный кассовый ордер,»,
«Указание Банка России 3210-У» (instead of «… о порядке ведения кассовых операций»), and the rest waited for a confirmation.
Rule: a first portion never stops 2-4 words (prepositions not counted) before the end of its sentence - those words go with it.
The sweep is over every answer of cloud_context/bank/merged, fed whole and word by word; the expectations are written here, not read from echo_sync."""
import glob
import json
import os
import re

import pytest
from razdel import sentenize

from echo_sync.first_useful import first_cue
from echo_sync.settings import CALL_SETTINGS as S

BANK = os.path.join(os.path.dirname(__file__), '..', 'cloud_context', 'bank', 'merged', '*.json')
ROWS = [(r['q'], r['answer']) for f in sorted(glob.glob(BANK)) for r in json.load(open(f, encoding='utf-8'))]
PREP = frozenset('в во на с со к ко по о об от из за для до при про над под перед между через без у около после среди'.split())
WORD = re.compile(r'\w[\w.\-]*', re.U)
COUNTED = re.compile(r"\d[\d\u00a0 ]*\d|[^\W_]+(?:[-’'][^\W_]+)*")
FIRST_MAX = 9      # fix-c20 (the coordinator): a first portion is at most 9 words; a thought that would run past them is not finished


def _tail(answer, cue):
    """Words (prepositions not counted) between the end of ``cue`` and the end of its sentence; 0 when the cue ends a sentence."""
    n = len(cue)
    for s in sentenize(answer):
        if s.start < n < s.stop:
            return len([w for w in WORD.findall(answer[n:s.stop]) if w.casefold() not in PREP])
    return 0


def _sentence_of(answer, cue):
    """The answer up to the end of the sentence ``cue`` stops in."""
    n = len(cue)
    return next((answer[:s.stop] for s in sentenize(answer) if s.start < n < s.stop), cue)


def _stream(answer, question):
    parts = answer.split(' ')
    for k in range(1, len(parts) + 1):
        cue = first_cue(' '.join(parts[:k]) + (' ' if k < len(parts) else ''), question, S, final=k == len(parts), last=k == len(parts))
        if cue:
            return cue
    return None


def _cues(question, answer):
    return {'whole': first_cue(answer, question, S, final=True, last=True), 'stream': _stream(answer, question)}


OWNER = [
    ('Что такое счёт 69?', 'Расчёты по социальному страхованию и обеспечению. Его используют для начислений.',
     'Расчёты по социальному страхованию и обеспечению.'),
    ('Что такое ПКО?', 'ПКО КО-1 — приходный кассовый ордер, по нему принимают наличные.',
     'ПКО КО-1 — приходный кассовый ордер, по нему принимают наличные.'),
    # c22-merge: the choice fix-c20 asked for is made by the server's c21/0003: the cap is counted on the planner's own scale
    # (portioner.portion_size), where «3210-У» is one word and the owner's phrase is 9 - inside the cap. No xfail any more.
    ('Что такое указание 3210-У?', 'Указание Банка России 3210-У о порядке ведения кассовых операций. Оно действует с 2012 года.',
     'Указание Банка России 3210-У о порядке ведения кассовых операций.'),
]


@pytest.mark.parametrize('question,answer,expected', OWNER)
def test_owner_phrases(question, answer, expected):
    assert _cues(question, answer) == {'whole': expected, 'stream': expected}


def test_bank_never_stops_short_of_the_end_of_a_thought():
    bad = []
    for question, answer in ROWS:
        for mode, cue in _cues(question, answer).items():
            if cue and answer.startswith(cue) and 1 <= _tail(answer, cue) <= 4 and len(COUNTED.findall(_sentence_of(answer, cue))) <= FIRST_MAX:
                bad.append((mode, question, cue, answer[len(cue):]))
    assert not bad, f'{len(bad)} of {len(ROWS) * 2}: {bad[:5]}'


def test_extension_only_adds_text_that_is_there():
    for question, answer in ROWS:
        for cue in _cues(question, answer).values():
            assert not cue or answer.startswith(cue)


# --------------------------------------------------------------------------------------------------------------------
# c20-first-cue (06.11 23:xx): G15 has a ceiling - the word cap of a portion (first_useful._portion_cap_holds). Without
# it the rule lengthened the first portion to the end of its sentence however long that sentence was: the live scene
# level2-c of 06.11 11:07 failed its NDS step on ``above_hard_cap`` with «22 процента — основная ставка НДС с 1 января
# 2026 года.» (10 words against 9), and tests/test_ear_number_veto.py lost its cut at the comma.
# The cap must not bring back what G15 was made for: a first cue that stops mid-thought («Статья 59 Налогового
# кодекса —», «Активный счёт учитывает имущество, пассивный —»: the owner's own complaints of the morning of 06.11).
# The caps are written here, not read from echo_sync: settings PRESETS['meaning']['max_words'] = 9, and the first
# portion of a question for a number or a date portioner.first_window(number=True) = 12.
CAP_WORDS, NUMBER_CAP_WORDS = 9, 12
DASHES = '—–'
# the conjunctions that leave a thought open at the end of a portion (echo_sync.textutil.CONJUNCTIONS, written out here)
CONJ = frozenset('и а но да или либо ни что чтобы чтоб как когда если хотя пока потому поскольку так также зато однако '
                 'причём притом будто словно чем нежели едва пусть пускай ибо'.split())

MID_THOUGHT = [
    ('Что такое статья 59 Налогового кодекса?',
     'Статья 59 Налогового кодекса — о признании недоимки безнадёжной к взысканию. Её применяют при ликвидации должника.',
     'Статья 59 Налогового кодекса —'),
    ('Чем отличается активный счёт от пассивного?',
     'Активный счёт учитывает имущество, пассивный — источники его образования. Это основа двойной записи.',
     'Активный счёт учитывает имущество, пассивный —'),
]
NDS = '22 процента — основная ставка НДС с 1 января 2026 года. Пониженная ставка 10 процентов осталась.'


def _words(text):
    return WORD.findall(str(text or ''))


def _open_end(cue):
    """What leaves the thought open at the end of ``cue``: a dash, a preposition or a conjunction - or '' when it is closed."""
    body = str(cue or '').rstrip().rstrip('.!?…,;:')
    if body[-1:] in DASHES:
        return 'dash'
    last = (_words(body) or [''])[-1].casefold().replace('ё', 'е')
    return 'preposition' if last in PREP else 'conjunction' if last in CONJ else ''


@pytest.mark.parametrize('question,answer,complained', MID_THOUGHT)
def test_the_cap_never_leaves_the_first_cue_mid_thought(question, answer, complained):
    """The owner's two phrases of 06.11: whatever the cap does to G15, the cue never ends on the dash he complained about."""
    for mode, cue in _cues(question, answer).items():
        assert cue, mode
        assert answer.startswith(cue), (mode, cue)
        assert not _open_end(cue), f'{mode}: {cue!r} ends on a {_open_end(cue)}'
        assert cue.rstrip() != complained.rstrip(), f'{mode}: the cue the owner complained about'
        assert len(_words(cue)) > len(_words(complained)), f'{mode}: {cue!r} is no more than the head he complained about'


def test_a_thought_that_fits_the_cap_is_still_finished_whole():
    """G15 itself: «Активный счёт учитывает имущество, пассивный — источники его образования.» is 8 words, inside the cap, so the
    first portion is the whole sentence - a definition with both its halves, never the half before the dash."""
    question, answer, _ = MID_THOUGHT[1]
    assert _cues(question, answer) == {'whole': answer.split('. ')[0] + '.', 'stream': answer.split('. ')[0] + '.'}


def test_the_first_cue_stays_inside_the_word_cap():
    """level2-c 11:07: the NDS sentence is 10 words. A question that asks for a number or a date may have it (the wider window,
    12 words); a question that does not must be cut inside 9 - G15 may not lengthen a portion past the cap for it."""
    plain = _cues('Что такое НДС и что меняется', NDS)
    counted = _cues('Какая основная ставка НДС с 2026 года?', NDS)
    for mode, cue in plain.items():
        assert cue and len(_words(cue)) <= CAP_WORDS, f'{mode}: {cue!r} is {len(_words(cue))} words'
        assert not _open_end(cue), f'{mode}: {cue!r} ends on a {_open_end(cue)}'
    for mode, cue in counted.items():
        assert cue and len(_words(cue)) <= NUMBER_CAP_WORDS, f'{mode}: {cue!r} is {len(_words(cue))} words'
        assert not _open_end(cue), f'{mode}: {cue!r} ends on a {_open_end(cue)}'


def test_the_cut_at_a_comma_is_not_swallowed_by_the_next_clause():
    """tests/test_ear_number_veto.py's precondition, as first_cue sees it: the sentence is 10 words, over the cap, so the first
    portion is the clause with the number - not the clause and the remark after it."""
    answer = 'Крещение Руси обычно датируют 988 годом, но точная дата спорна. Это было давно.'
    assert _cues('Расскажи подробнее', answer) == {'whole': 'Крещение Руси обычно датируют 988 годом,',
                                                   'stream': 'Крещение Руси обычно датируют 988 годом,'}
