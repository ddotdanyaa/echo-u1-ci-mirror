"""U16-S8: the TTS century paradigm and range reading, the owner's rule, always on (no key, no switch)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from echo_sync import speech_text as S      # noqa: E402

CASES = ('в XV веках', 'в XIII–XV веках', 'в 13–15 веках', 'XV веков', 'в XV веке', 'в XX веке', 'Глава IV')


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def spoken(text):
    return S.speak(text)


def test_on_no_latin_letters_in_a_plural_century():
    for t in CASES:
        out = spoken(t)
        assert not re.search('[A-Za-z]', out) and 'икс' not in out and 'вэ' not in out, (t, out)
    assert 'пятнадцат' in spoken('в XV веках')
    assert spoken('в XV веках').endswith('веках')


def test_on_a_range_of_centuries_reads_both_ends_in_the_plural_paradigm():
    a, b = spoken('в XIII–XV веках'), spoken('в 13–15 веках')
    for out in (a, b):
        assert 'тринадцат' in out and 'пятнадцат' in out and out.endswith('веках'), out
    assert a == b


def test_on_leaves_the_singular_century_and_other_text_unchanged():
    for t in ('в XV веке', 'в XX веке', 'Глава IV', 'в 2020–2022 гг.', 'от 5 до 10'):
        assert not re.search('[A-Za-z0-9]', S.speak(t)), t
