"""c22: classes of breakage the stand found in the PRODUCT (echo_sync), each as a seed of the stand that gives it today. ``xfail(strict=True)``: when the product is
fixed the test turns into an XPASS failure, and the mark must go. The minimal scenes (ddmin) are in ``cloud_context/reports/c22-break.json``.
Nothing here is a measurement of time on a laptop or a phone."""
import pytest

from tools.replay import chaos, fuzz, half_hour, stand

REASON = 'c22-break %s: see cloud_context/reports/c22-break.md'


def groups(seed, inv, **keywords):
    return [v for v in stand.run(seed, **keywords).violations if v[0] == inv]


# c23: fixed (``_said_past``: speech said past the old final is unjudged, the first cue waits); the scene of ddmin is tests/test_c23_grpC.py
def test_p01_a_job_of_the_older_question_is_not_the_answer_of_the_newer_one():
    assert groups(7, 'A2') == []


# c24-a1: green; the seed's conversation has no «стоп» any more, but the minimal scene of ddmin (c22-break.json, seed 259) is green too, red on the base: see c24-a1.md
def test_p02_stop_while_the_answer_is_still_coming_cancels_it():
    assert [v for v in groups(88, 'A2') if 'стоп' in v[2]] == []


# c24-a1: green; the minimal scene of ddmin (seed 163) is green too, red on the base: see c24-a1.md; c24-a2: fixed for seed 148 (``_asked_again_unheard``); c24-b: fixed too (``_said_to_the_plan``: the late final of a repeat is read on the last portion of the answer just over, the suspended plan is not taken back)
def test_p03_a_late_final_does_not_advance_the_cursor_after_a_resume():
    assert groups(148, 'A3') == []


# c23: fixed (``_split_after``: the ear's breath does not run into an utterance the cloud has a turn of its own for)
def test_p04_two_utterances_are_not_one_request():
    assert groups(6, 'A9') == []


# c23: green on seed 809 only because the P01 hold (``_said_past``) changes the course of the call from ~20 s; the base scene (a question only the ear heard, begun BEFORE the old
# final, offset before it) is not covered by that rule: the root is not proven fixed, see cloud_context/reports/c23-grpC.md
def test_p05_an_answer_does_not_contradict_the_question_it_is_given_to():
    assert groups(809, 'A7') == []


# c24: fixed (``_heard_since``: «дальше» said before the portion was heard, whose final comes after the portion has sounded, says nothing more)
def test_p06_a_portion_is_not_repeated_on_its_own_four_times():
    assert groups(953, 'A5') == []


# c24-a1: green with the same «Продолжай» at 39.74 in the scene (one final says one utterance, ``_said_after``); c24-a2: and ``_cue(unless_spoken_over)`` (the cue of «продолжай» whose final comes while the owner says the next utterance waits for the silence after it)
def test_p07_one_utterance_one_answer():
    assert groups(293, 'A1') == []


# P08 (the breaker of the fast channel never closes again, half_hour seed 24) was OPEN: closed by deleting the breaker (the one road: a failure costs its job, never the channel)
def test_p08_three_slow_jobs_do_not_end_the_answers_of_the_call():
    result = half_hour.one(24, minutes=6, questions=12)
    assert [e for e in result['events'] if e[0] == 'unanswered'] == []


# c23: fixed (``_ear_stood_short``: a final that says more than the ear's declined text is judged again; the portion waits for it)
def test_p09_a_declined_question_is_not_answered_with_the_old_plan():
    out = chaos.run(27, 'mid_portion', 1)
    assert chaos.first(out) is None, out.violations
