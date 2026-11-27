"""WAVE15 f3-reaction: the scenes of the run n1_01 (test_h5_live) with ``prompt_pace`` = "on". A stop inside a number is a reading pause («сто сорок четыре | ноль ноль
ноль рублей»): the help waits the top of the owner's window (1.2 s after the last word), the floor (0.7 s) cut into the second piece at 0.7 s."""
import test_h5_live as H
from test_h3_tempo import call  # noqa: F401 - the fixture


def test_n1_01_step_17_with_the_pace_on(call):
    real = call
    H.test_n1_01_step_17_with_the_ear_in_the_order_of_the_run(lambda **profile: real(**{**profile, 'prompt_pace': 'on'}))
