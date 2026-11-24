"""BREAK kind_question 5: foreign speech beside the call: somebody else's question in the room, another language, a phone call, and the cloud that answers all of it. The plan in play must go on unchanged.
Class of problem: К7 (talk around took the hint away), К8 (a late answer replaced the hint), К28 (language of the utterance), A8 of the stand (chatter taken for an answer). Real ControlledMedia, not run on the laptop."""
import pytest

from break_kit import ACCOUNT, LIVE_RULES, MATERIALS, call, chunks_of, cloud, declined_if_asked, heard, index_of, plan, said_to_the_room    # noqa: F401 - call is the fixture

FOREIGN = ['Вася, ты во сколько вечером придёшь домой?', 'Okay, let us move on to the next slide, shall we?', 'Маша, закрой окно, там дует', 'Алло, да, слушаю, перезвони мне через час',
           'Тут вопрос по списку, кто следующий, ты или Петя?']


@pytest.mark.parametrize('remark', FOREIGN, ids=range(len(FOREIGN)))
def test_b12_a_remark_for_somebody_else_leaves_the_plan_where_it_was(call, remark):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    chunks, first = chunks_of(rig), chunks_of(rig)[0]
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', remark)
    declined_if_asked(rig, 1)
    rig.pump(12.0)
    assert chunks_of(rig) == chunks and index_of(rig) == 0, rig.c.state()
    assert set(rig.said()) == {first}, rig.said()


def test_b13_the_clouds_chatter_over_a_remark_is_not_said_as_the_answer(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    first = chunks_of(rig)[0]
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Вася, ты во сколько вечером придёшь домой?')
    cloud(rig, 'a1', 'Конечно, давайте продолжим, я с радостью отвечу на ваш вопрос.')
    declined_if_asked(rig, 1)
    rig.pump(12.0)
    assert set(rig.said()) == {first}, rig.said()
    assert not heard(rig, 'с радостью')
