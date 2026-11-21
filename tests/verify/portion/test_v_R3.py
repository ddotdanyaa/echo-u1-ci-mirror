"""V4 R3: a word repeated in another form does not move the portion on («века» for «...XIII-XV веках», «пятнадцатый» for «XV»). Backlog: the form of a word (a common stem) and a number (Roman, in words, in digits)
count as the same in the key; the threshold is not lowered; false moves from background speech = 0.

Real ControlledMedia, NativeMediaSocket, ShadowEar and FastText (rig ``call`` with ``repeat_rule`` on, the controller's settings as the host builds them). Not run on the laptop. A red test is a defect card for
the family K (the judge) or P (``repeat_rule``).
"""
import pytest

from portion_kit import call, index, moved, rig_of, state, utter      # noqa: F401 - call is the fixture

WHEN = 'Когда это было'


def answer_of(rig, text):
    rig.asks('u1', WHEN, 0, text)
    rig.pump(0.5)
    return index(rig)


def test_a_form_of_the_last_word_moves_on(call):
    rig = rig_of(call)
    before = answer_of(rig, 'Реформа прошла в XIII–XV веках. Потом всё изменилось.')
    assert state(rig)['chunks'][0].rstrip('.').endswith('веках'), f'precondition: the portion ends in the word: {state(rig)["chunks"]}'
    utter(rig, 'века', speech=0.6, turn='u2', final='века')
    rig.pump(0.5)
    assert moved(rig, before), f'«века» for «веках» did not move: {rig.said()}'


def test_a_number_said_in_words_moves_on(call):
    rig = rig_of(call)
    before = answer_of(rig, 'Реформа началась в XV. Потом всё изменилось.')
    assert state(rig)['chunks'][0].rstrip('.').endswith('XV'), f'precondition: the portion ends in the number: {state(rig)["chunks"]}'
    utter(rig, 'пятнадцатый', speech=0.6, turn='u2', final='пятнадцатый')
    rig.pump(0.5)
    assert moved(rig, before), f'«пятнадцатый» for «XV» did not move: {rig.said()}'


@pytest.mark.parametrize('noise', ['погода сегодня хорошая', 'да нет'], ids=['talk', 'short'])
def test_speech_that_is_not_the_portion_moves_nothing(call, noise):
    rig = rig_of(call)
    before = answer_of(rig, 'Реформа прошла в XIII–XV веках. Потом всё изменилось.')
    utter(rig, noise, speech=1.0, turn='u2', final=noise)
    rig.pump(0.5)
    assert not moved(rig, before), 'a false move from speech that is not a repeat'
