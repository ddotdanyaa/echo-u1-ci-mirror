"""V4 Н5 (calls 11:40, 12:59, 16:15; h25, h26, h27 laid out): the repeat goes on from the place where he stopped. Backlog: confirm by a call; here: the stumble reader through the ear's text and the cloud's final
(a stop after a word, a filler, a garbled start of the breath, a number at the head). The words of a stop place that are not in the portion name no place. The confirmation by a call stays «нужен телефон».

Real ControlledMedia, NativeMediaSocket, ShadowEar (rig ``call`` with the rule of repeats on). Not run on the laptop. A red test is a defect card for the family P (``stumble_place``, ``ru_alignment``).
"""
import pytest

from portion_kit import GRID, P1, P2, RULE, after, call, walk      # noqa: F401 - call is the fixture

REST = 'на хлорофилл в листьях.'


@pytest.mark.parametrize('heard', ['свет попадает', 'свет попадает э-э', 'так свет попадает', 'эф свет попадает'], ids=['plain', 'filler', 'lead', 'garbled_start'])
def test_a_stop_after_the_first_words_goes_on_from_the_next_word(call, heard):
    rig = walk(call, **RULE)
    assert after(rig, heard, wait=1.8) == [REST], rig.said()


def test_a_stop_in_the_middle_goes_on_from_the_next_word(call):
    rig = walk(call, **RULE)
    assert after(rig, 'свет попадает на хлорофилл', wait=1.8) == ['в листьях.'], rig.said()


def test_words_that_are_not_in_the_portion_name_no_place(call):
    rig = walk(call, **RULE)
    after(rig, 'я думаю купи мне денег', wait=1.8)
    assert REST not in rig.said(), f'a place named by words that are not the portion: {rig.said()}'


def test_the_rest_said_to_the_end_gives_the_next_portion(call):
    rig = walk(call, **RULE)
    after(rig, 'свет попадает', wait=1.8)
    assert after(rig, 'на хлорофилл в листьях', wait=1.2) == [REST, P2]
