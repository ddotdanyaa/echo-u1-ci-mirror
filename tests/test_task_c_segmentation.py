"""WAVE 2 / Task C-seg: portions the listener can repeat - a short first cue, whole numbers and units, no cut words,
no phrase the iPhone client intercepts as stop/end.

Every test here was written BEFORE the code it guards and watched to fail for the stated reason. The adversarial
module ``test_s6_segmentation.py`` is the independent acceptance test; this module adds what that one does not pin:
the exact behaviour of the new first-cue rule, the overlap rule for a tail that is a phone phrase, the stalling
phrases, and a replay of the nine real answers of the live corpus run 20261102-000520.
"""
from __future__ import annotations

import re

import pytest

from echo_sync.portioner import portions, stable_prefix
from echo_sync.textutil import WORDS, normalize

CONTROLLED = {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2, 'ack_match': 'ru_aligned', 'on_mismatch': 'silent'}


def squeeze(text):
    return ' '.join(str(text).split())


def cut_inside_a_word(text, prefix):
    return bool(prefix) and len(prefix) < len(text) and prefix[-1].isalnum() and text[len(prefix)].isalnum()


# =====================================================================================================
# DEF-SEG-12: stable_prefix must never cut a word, whatever separates the words
# =====================================================================================================

ODD = [' ', ' ', ' ', '  ', '   ', '\n', '\r\n', '\t', ' \n ', ' ']
PLAIN = 'Мама мыла раму папа пилил дрова дети ели кашу и потом все вместе пили сладкий чай с вареньем и мёдом '


@pytest.mark.parametrize('odd', ODD, ids=[repr(o) for o in ODD])
@pytest.mark.parametrize('nth', [0, 1, 2, 3])
def test_stable_prefix_commits_the_same_words_whatever_separates_them(odd, nth):
    """The whitespace inside the first planned portion may be anything: the commit still ends on a word end and
    holds exactly the words the plain-space text commits."""
    spaces = [m.start() for m in re.finditer(' ', PLAIN)]
    at = spaces[nth]
    text = PLAIN[:at] + odd + PLAIN[at + 1:]
    expected = stable_prefix(PLAIN, CONTROLLED, committed='')
    assert expected, 'the plain text must commit something, or this test proves nothing'
    got = stable_prefix(text, CONTROLLED, committed='')
    assert text.startswith(got) and not cut_inside_a_word(text, got), (text, got)
    assert got == got.rstrip(), 'the commit ends on the last letter of its last word'
    assert squeeze(got) == expected


@pytest.mark.parametrize('odd', ODD, ids=[repr(o) for o in ODD])
def test_stable_prefix_keeps_growing_when_the_committed_text_and_the_tail_hold_odd_whitespace(odd):
    words = 'Небо голубое потому что воздух рассеивает синий свет сильнее чем красный потому что короче волна '.split()
    text = odd.join(words) + odd
    committed, seen = '', []
    for end in range(1, len(words) + 1):
        arrived = odd.join(words[:end]) + (odd if end < len(words) else odd)
        nxt = stable_prefix(arrived, CONTROLLED, committed=committed)
        assert nxt is not None and nxt.startswith(committed), (end, committed, nxt)
        assert not cut_inside_a_word(arrived, nxt), (arrived, nxt)
        if nxt != committed:
            seen.append(nxt)
            committed = nxt
    assert seen, 'nothing was ever committed'
    assert text.startswith(seen[-1])


def test_stable_prefix_of_a_tail_that_starts_with_odd_whitespace():
    committed = 'Небо голубое'
    for odd in ODD:
        text = committed + odd + 'потому что воздух рассеивает синий свет сильнее чем красный потому что короче волна и выше частота '
        got = stable_prefix(text, CONTROLLED, committed=committed)
        assert got.startswith(committed) and text.startswith(got) and not cut_inside_a_word(text, got), (odd, got)
        assert len(got) > len(committed)
