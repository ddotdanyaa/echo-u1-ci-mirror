"""BREAK kind_question 1: the owner cuts himself off. A word broken in the middle, a question dropped half way and asked again whole. Real ControlledMedia (rig ``call``), not run on the laptop.
Class of problem: К5 (a scrap of speech taken for a question), К13 (the answer begins again), К2 (what is left of speech must not bury the next question)."""
import pytest

from break_kit import ACCOUNT, LIVE_RULES, MATERIALS, TICK, answered, asked, call, chunks_of, heard, index_of, job_text, partial, plan    # noqa: F401 - call is the fixture


@pytest.mark.parametrize('fragment', ['как отра', 'ну по', ''], ids=['how', 'well', 'nothing'])
def test_b01_a_word_cut_in_the_middle_opens_no_question_and_the_portion_stays(call, fragment):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    first = chunks_of(rig)[0]
    rig.pump(1.0)
    rig.says(fragment, speech=0.25, lag=0.15)
    rig.pump(2.0)
    assert not rig.fake.runs[1:], f'a broken word became a question: {[r.question for r in rig.fake.runs[1:]]}'
    assert index_of(rig) == 0
    rig.pump(12.0)
    assert set(rig.said()) == {first}, rig.said()


def test_b02_a_question_dropped_half_way_and_asked_whole_is_answered_once_with_its_own_words(call):
    rig = call(**LIVE_RULES)
    partial(rig, 'u1', 'Как отразить по')
    rig.pump(0.6)
    asked(rig, ACCOUNT, uid='u2')
    rig.pump(0.5)
    last = len(rig.fake.runs) - 1
    assert last >= 0, 'the whole question never reached a job'
    assert 'покупку материалов' in job_text(rig, last), job_text(rig, last)
    answered(rig, last, MATERIALS)
    rig.pump(1.0)
    assert heard(rig, 'Купили материалы')
    assert not any(text.startswith('Как отразить по') for text in rig.said())
