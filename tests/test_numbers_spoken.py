"""U43 (b)(c): a number said digit by digit («четыре два два», «four two two») or in English words is ONE number in ``_protected_atoms``; (a): a figure worked out while the ear and the cloud disagree names its operands.
U36 pins: the ear and the cloud may name one number in two ways, and then they agree."""
import pytest
from echo_sync.controlled_media import ControlledMedia as CM
from echo_sync import quick_math
from test_h1_fast_text import rig  # noqa: F401 - the fixture


@pytest.mark.parametrize('text,atoms,last', [
    ('четыре два два', {'#422'}, '#422'),
    ('статья четыре два два', {'#422'}, '#422'),
    ('номер четыре два два кодекса', {'#422'}, None),
    ('four two two', {'#422'}, '#422'),
    ('article four two two', {'#422'}, '#422'),
    ('two hundred twenty two', {'#222'}, '#222'),
    ('two hundred', {'#200'}, '#200'),
    ('one thousand five hundred', {'#1500'}, '#1500'),
    ('twenty two', {'#22'}, '#22'),
])
def test_digits_one_by_one_and_english_words_are_one_number(text, atoms, last):
    found, end = CM._protected_atoms(text)
    assert found == atoms and end == last


@pytest.mark.parametrize('text,atoms', [
    ('два раза', {'#2'}),
    ('один, два, три', {'#1', '#2', '#3'}),      # a list with its pauses
    ('один два три', {'#1', '#2', '#3'}),      # counting up
    ('три два один', {'#1', '#2', '#3'}),      # counting down
    ('пять шесть', {'#5', '#6'}),      # two numbers are never summed
    ('четыре, два, два', {'#4', '#2'}),
    ('сто сорок четыре ноль ноль ноль', {'#144000'}),      # the recognizer's thousands by groups
    ('двадцать четыре два два', {'#20', '#4', '#2'}),      # after a bigger number word: not a number of its own (the base's reading stays)
    ('one two three', set()),
    ('one of them, two times', set()),
    ('two apples', set()),
])
def test_what_is_no_one_number_stays_as_it_was(text, atoms):
    assert CM._protected_atoms(text)[0] == atoms


def test_one_number_two_ways_is_no_disagreement(rig, monkeypatch):
    c = rig.w.controller
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'есть статья четыре два два')
    assert c._number_witness('Статья 422 …', 'статья четыреста двадцать два', 'u1') == 'Статья 422 …' and c.number_asked is None
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'статья сто двадцать два')
    c._number_witness('X', 'статья четыре два два', 'u2')
    asked = c._number_witness('X', 'статья четыре два два', 'u3')
    assert '122' in asked and '422' in asked and '?' in asked, asked


def test_a_figure_names_its_operands_when_the_witnesses_differ(rig, monkeypatch):
    c = rig.w.controller
    cloud = 'сколько будет пять на тридцать'
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'сколько будет пять на тридцать пять')
    bare = quick_math.answer(cloud)
    assert bare == 'Сто пятьдесят.'
    said = c._number_witness(bare, cloud, 'u1')
    assert said == 'Пять на тридцать — сто пятьдесят.', said
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'сколько будет пять на тридцать')
    assert c._number_witness(bare, cloud, 'u2') == bare, 'the witnesses agree: the figure stands bare'
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'статья сто двадцать два')
    assert c._number_witness('Ответ.', 'статья триста двадцать два', 'u3') == 'Ответ.', 'what is no figure is left as it was'
