"""V4 E13: the recovery after a wrong repeat and the stuck tail («105,8»: a stumble on the border of two portions). Backlog: «1-секундный replay и missing-tail проверены через начало воспроизведения»; the stumble
itself is deferred in the row.

Real ControlledMedia (Dictation and the rig ``call``). Not run on the laptop: the verdict is the cloud's. A red test is a defect card for the family P (the portion) or T (the terms).
"""
import pytest

from portion_kit import GRID, HEAD, PORTION, REST, TEMPO_START_SECONDS, dictation_of, call, utter, rig_of      # noqa: F401 - call is the fixture

PRICE = 'Цена составила 105,8 рубля за штуку. Скидка составила 12 процентов.'


def test_a_repeat_with_a_wrong_number_does_not_move_on_and_the_right_one_does(tmp_path):
    d = dictation_of(tmp_path, PRICE)
    portion = d.current
    assert '105,8' in portion, f'precondition: the number is in the first portion: {d.chunks}'
    wrong = portion.replace('105,8', '108,5')
    assert d.say(wrong, gap=4.0).after == 0, 'a wrong number is no repeat of the portion'
    right = d.say(portion, gap=4.0)
    assert right.after == 1 or right.completed, 'the right repeat after the wrong one still moves on (no stuck tail)'


def test_a_start_that_stopped_is_helped_with_the_tail_only_within_about_a_second(call):
    """«общие» and a stop: not the whole portion after seconds, the tail after TEMPO_START_SECONDS."""
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    ended = rig.says('общие')
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == REST and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)
    assert TEMPO_START_SECONDS <= 1.5


def test_a_tail_missing_in_the_middle_of_the_portion_comes_back_by_its_word(call):
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    ended = rig.says('общие условия установления налогов')
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == 'и сборов.' and cue.t - ended == pytest.approx(TEMPO_START_SECONDS, abs=GRID)
