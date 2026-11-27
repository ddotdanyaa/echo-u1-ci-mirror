"""V1a U47: a story is torn by a «question» made of the narrator's own words (the call of 11 Nov 08:45: over the waiting portion «Нужны были мундиры, обувь,» said «что соответственно нужны были» -> ``question_word`` -> the plan
was thrown away, 70 s of chaos). Fixed on 11 Nov (``SAID_BACK_TAIL=2``), the remainder («ну что ж, а сейчас наступает моя часть»: the word «что» outside the portion) is the judge's rule ``doubt`` (commit e629e91d, U47/U59), and the
13 Nov regression (a question in one's own words taken for a said-back portion, ``search_hang`` U85) is held by the count of own content words.

These guards drive the REAL ControlledMedia (``helpers_s6_ack.Dictation``: built as the host builds it, the provider's events, the injected clock; the speaker is ``test_stable_partial_ack.Speaker``), over a waiting portion.
Not run on the laptop. The commit that fixed the class is named in the report; the tests below are its guard (a red here reproduces the class: a defect card for the family K).
"""
import logging

import pytest

from test_one_m1_kind import said_over_the_portion
from test_stable_partial_ack import PORTION, Speaker, dictation

ARMY = 'Армия готовилась к походу, нужны были мундиры, обувь, шинели и оружие. Всё это закупали по всей стране.'


def judged(lines):
    return [line for line in lines if 'kind=question' in line]


def held_portion(d, s, caplog, portion, index):
    state = d.controller.state()
    return state['chunk_index'] == index and state['chunks'][index] == portion and 'new_question' not in caplog.text and not {'route', 'cancel'} & {a['type'] for a in s.actions}


@pytest.mark.parametrize('text', ['что соответственно при ста градусах', 'ну так что соответственно ста градусах Цельсия', 'так что при ста градусах'])
def test_the_narrators_own_words_with_a_question_word_are_the_portion_not_a_question(tmp_path, caplog, text):
    """The class of the call of 11 Nov: the last two words of the utterance run on in the waiting portion."""
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    assert lines and not judged(lines), lines
    assert held_portion(d, s, caplog, PORTION, 1)


def test_the_call_of_11_nov_in_its_own_words_over_its_own_portion(tmp_path, caplog):
    """The recorded line (t=248402 of the journal 20261111-084102): over «Нужны были мундиры, обувь,» said «что соответственно нужны были». The portion is the plan's first portion that waits; the words are the first two of it."""
    caplog.set_level(logging.INFO)
    d = dictation(tmp_path / 'u47call', answer=ARMY, at=0)
    portion, at = d.current, d.index
    words = portion.replace(',', ' ').replace('.', ' ').split()
    assert len(words) >= 2, f'precondition: a portion of at least two words: {portion!r}'
    s = Speaker(d).start().words('что соответственно ' + ' '.join(words[:2]).lower())
    s.wait(0.8)
    caplog.clear()
    s.final()
    s.wait(1.0)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync judge ')]
    assert lines and not judged(lines), (portion, lines)
    assert held_portion(d, s, caplog, portion, at)


@pytest.mark.parametrize('text', ['ну что ж, а сейчас наступает моя часть', 'Что ж, начнём.'])
def test_the_discourse_what_zh_outside_the_portion_is_no_question(tmp_path, caplog, text):
    """The remainder named in the row: «что» of a discourse, said over the waiting portion."""
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    assert lines and not judged(lines), lines
    assert held_portion(d, s, caplog, PORTION, 1)


@pytest.mark.parametrize('text', ['а что такое температура кипения', 'что такое градус', 'почему вода закипает при ста градусах'])
def test_a_question_in_ones_own_words_is_still_a_question(tmp_path, caplog, text):
    """The regression of 13 Nov (``search_hang``): the lock must not turn a real question that shares a word with the portion into a said-back portion."""
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    assert lines and 'kind=question' in lines[-1], lines
