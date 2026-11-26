"""V4 U53: the last word of a repeat is heard wrong or cut by the ear («написывал» for «описывал», «воинский у» for «устав»): the portion was not counted and came again (3 repeats, about 25 s). Backlog: the last
word of an attempt counts as the word of the portion when it is its beginning (cut by the ear) after the matching word before it, or alike by 0.8 at length 5+; numbers and «не» stay strict.

Real ControlledMedia, ShadowEar, NativeMediaSocket (rig ``call``): the repeat is the ear's text and the cloud's final of it. Not run on the laptop. A red test is a defect card for the family K (the judge) or P.
"""
import pytest

from portion_kit import PORTION, call, index, moved, rig_of, utter      # noqa: F401 - call is the fixture

HEARD_OK = ['общие условия установления налогов и сбо', 'общие условия установления налогов и сборах', 'общие условия установления налогов и сбор']
HEARD_OTHER = ['общие условия установления налогов и сыров', 'общие условия установления налогов и мостов']


@pytest.mark.parametrize('heard', HEARD_OK, ids=['cut', 'other_form', 'cut_short'])
def test_a_last_word_cut_or_heard_in_another_form_still_counts_the_portion(call, heard):
    rig = rig_of(call)
    rig.second_portion()
    before = index(rig)
    rig.pump(0.5)
    utter(rig, heard, speech=2.0, turn='u3', final=heard)
    rig.pump(0.5)
    assert moved(rig, before), f'the portion was not counted: {rig.said()}'
    assert rig.said().count(PORTION) == 1, 'and it is not said again as if nothing had been heard'


@pytest.mark.parametrize('heard', HEARD_OTHER, ids=['other_word_1', 'other_word_2'])
def test_another_word_of_the_same_length_is_no_repeat(call, heard):
    rig = rig_of(call)
    rig.second_portion()
    before = index(rig)
    rig.pump(0.5)
    utter(rig, heard, speech=2.0, turn='u3', final=heard)
    rig.pump(0.5)
    assert not moved(rig, before), 'a different last word is no confirmation'
