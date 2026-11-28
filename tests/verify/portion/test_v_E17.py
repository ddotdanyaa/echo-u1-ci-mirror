"""V4 E17: the first portion carries the answer («Битва на реке Калке произошла», the year came 9 s later). Backlog: the decisive content is in the first portion; the first portion is no read-back of the question.

Real ControlledMedia, NativeMediaSocket and FastText (rig ``call``): the job's text is streamed to the real portioner. Not run on the laptop. A red test is a defect card for the family P (the first portion).
"""
import helpers_s6_state as S
from portion_kit import LIVE_RULES, TICK, call      # noqa: F401 - call is the fixture

ASKED = 'Когда была битва на реке Калке'
ANSWER = 'Битва на реке Калке произошла в 1223 году. После неё монголы пошли дальше.'


def ask(rig):
    rig.w.feed(S.turn_created('u1', 'user', 'Когда'))
    rig.w.feed(S.turn_done('u1', 'user', ASKED))
    rig.pump(TICK)


def test_the_first_portion_of_a_when_question_holds_the_year(call):
    rig = call(**LIVE_RULES)
    ask(rig)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    assert rig.said(), 'the first portion is said'
    assert '1223' in rig.said()[0], f'the year is the point of the answer: {rig.said()}'
    assert not rig.said()[0].lower().startswith('когда'), 'the question is not read back'


def test_a_stream_that_stopped_before_the_year_says_no_portion_without_it(call):
    rig = call(**LIVE_RULES)
    ask(rig)
    rig.job_says(0, 'Битва на реке Калке произошла')
    rig.pump(1.5)
    assert all('1223' in text for text in rig.said()), f'a portion without the decisive word: {rig.said()}'
    rig.job_says(0, ' в 1223 году.')
    rig.job_ends(0)
    rig.pump(0.5)
    assert rig.said() and '1223' in rig.said()[0], rig.said()
