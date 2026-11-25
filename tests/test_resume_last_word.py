"""G39 (owner, 06.11): «на каком слове я сказал, это последнее слово, до которого я адекватно понял; а если молчу, значит надо повторять заново сначала».
One rule after a portion has sounded, property over the 2000 portions of the bank with the ear's errors of N2 (``tools/rehearsal/ear_n2.json``, the scenes of ``test_resume_word``):
(1) words of the portion said (less than half): the place is just after the last word said, the cue goes on from that word; (2) the end or most of the portion said: the next portion, once (``most_said``,
``ends_like``, no place); (3) silence: the portion whole, from its start (no place, no try); (4) a number changed or a «не» lost: never moved on, the cue says it (a place at it or before); words of their own, a question: no
place past what was said right. Dictation in pauses (a portion said in pieces) waits and goes on from the place, never from the start."""
import random
import re

import pytest

import helpers_s6_state as S
from echo_sync.fast_text import ends_like, most_said, said_share
from test_resume_word import KINDS, corpus, cuts, place, protected_changed, retold, say, words_in


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


@pytest.fixture(scope='module')
def c():
    w = S.World()
    yield w.controller
    w.close()


KNOWN_GAPS = 4      # U42: the open gaps of the aligner on the ear's noise (cloud_context/reports/g39-resume.md: a lost «плюс» or «процентов» is no change for fast_text.most_said; «доллар A1»; the ear's several errors in one word): at most this many of ~6600 scenes. The sample of portions moves with the portioner, so the bound is a count, not a list of texts


def judge(c, heard, portion):
    """What the rule does with what was heard after the cue: ('next', None) / ('place', rest) / ('again', None)."""
    found = c._started(heard, portion)
    if found is None and (most_said(heard, portion) or ends_like(heard, portion)):return 'next', None
    if found is not None:return 'place', found[0]
    return 'again', None


def test_the_rule_1_and_2_over_2000_portions(c):
    """A stop before the half of the portion is cued from its word (one off); more than half said or its end closed is the next portion; a changed number or a lost «не» is no advance."""
    rng = random.Random(39)
    misses, rows = [], 0
    for portion in corpus():
        tokens = portion.split()
        for k in cuts(tokens):
            kind = rng.choice(KINDS);heard, slack = say(rng, tokens, k, kind);rows += 1
            if kind == 'stutter' and re.search(r'\d', heard):continue      # nobody stutters a number («75-2-75-2» is the generator's, not a speaker's)
            what, rest = judge(c, heard, portion)
            wrong = protected_changed(tokens, k, heard)
            if wrong is not None:
                if what == 'next' or (rest is not None and place(portion, rest) > wrong):misses.append(('changed', kind, heard, portion, wrong, what, rest))
                continue
            if what == 'place' and kind in ('own', 'swallow', 'garble', 'ear'):      # R07: never a cue after a word not said right: the place goes back to it, never past what was said
                if words_in(tokens, place(portion, rest)) > words_in(tokens, k):misses.append(('past', kind, heard, portion, k, rest))
            elif what == 'place' and abs(words_in(tokens, place(portion, rest)) - words_in(tokens, k)) > 1 + slack:misses.append(('place', kind, heard, portion, k, rest))
            elif what == 'again' and k <= len(tokens) - 2 and (said_share(heard, portion) or 0) <= .5 and kind in ('clean', 'filler', 'twice', 'stutter'):misses.append(('lost', kind, heard, portion, k))
    assert rows > 4000 and len(misses) <= KNOWN_GAPS, f'{len(misses)} of {rows}: ' + '\n'.join(map(repr, misses[:10]))


def test_rule_3_silence_is_the_whole_portion_from_the_start(c):
    for portion in corpus()[:300]:
        for heard in ('', 'э', 'ну', 'эм э'):
            assert judge(c, heard, portion)[0] == 'again', (heard, portion)


def test_rule_4_other_words_or_a_question_are_no_place_no_repeat(c):
    for portion in corpus()[:300]:
        for heard in ('а сколько это стоит', 'подожди минутку', 'что такое налог и зачем он нужен'):
            assert judge(c, heard, portion)[0] == 'again', (heard, portion)


def pieces(rng, tokens, k):
    """A dictation: the first ``k`` words cut into 2-3 pieces at the pauses."""
    words = [w for w in (re.sub(r'^[^\w]+|[^\w]+$', '', t.lower().replace('ё', 'е')) for t in tokens[:k]) if w]
    n = min(len(words), rng.choice((2, 3)))
    cut = sorted(rng.sample(range(1, len(words)), n - 1)) if len(words) > 1 else []
    return [' '.join(p) for p in (words[a:b] for a, b in zip([0] + cut, cut + [len(words)])) if p]


def test_dictation_in_pauses_waits_and_goes_on_from_the_place(c):
    """The listener says the portion in pieces: after each piece the place is after the words said so far (never the start while some of it is said, never past it); the whole pieces together close it."""
    rng = random.Random(7)
    misses, rows = [], 0
    for portion in corpus():
        tokens = portion.split()
        for k in [k for k in cuts(tokens) if k >= 3][::2]:
            said = '';parts = pieces(rng, tokens, k)
            for i, part in enumerate(parts):
                said = (said + ' ' + part).strip();rows += 1
                if protected_changed(tokens, k, said) is not None:continue
                what, rest = judge(c, said, portion)
                n = len(said.split())
                if what == 'again' and (said_share(said, portion) or 0) <= .5 and n >= 2:misses.append(('start', said, portion, k))
                elif what == 'place' and place(portion, rest) > len(tokens[:k]) + 1:misses.append(('past', said, portion, k, rest))
    assert rows > 1500 and not misses, f'{len(misses)} of {rows}: ' + '\n'.join(map(repr, misses[:10]))
