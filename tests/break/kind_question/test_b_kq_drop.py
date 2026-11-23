"""BREAK kind_question 6: the link drops on a question: with the question open, between its final and the answer, with an answer in play. A new call over the same file. Real ControlledMedia (rig ``call``), not run on the laptop.
Class of problem: К9 (network), К27 (the memory of the talk), A1/A2 of the stand (the old call's answer in the new call), one writer of the state."""
from break_kit import ACCOUNT, LIVE_RULES, MATERIALS, TICK, WIDE, answered, asked, call, chunks_of, heard, job_mark, late, partial, plan, rebuilt, said_to_the_room    # noqa: F401 - call is the fixture


def test_b15_a_question_open_when_the_line_dropped_is_asked_again_and_answered_once(call):
    rig = call(**WIDE)
    partial(rig, 'u1', ACCOUNT)
    rig.pump(0.6)
    rebuilt(rig)
    rig.pump(1.0)
    assert rig.said() == [], 'the dropped call said something after its line was gone'
    asked(rig, ACCOUNT, uid='u2')
    rig.pump(0.3)
    answered(rig, len(rig.fake.runs) - 1, MATERIALS)
    rig.pump(1.0)
    assert heard(rig, 'Купили материалы')
    assert not rig.w.errors, rig.w.errors


def test_b16_the_answer_of_the_job_of_the_dropped_call_is_never_said_in_the_new_one(call):
    rig = call(**LIVE_RULES)
    old = rig.fake
    asked(rig, ACCOUNT, uid='u1')
    run = old.run(0)
    rebuilt(rig)
    late(run, 'Ответ старого звонка, которого уже нет.')
    rig.pump(3.0)
    assert not heard(rig, 'старого звонка'), rig.said()
    asked(rig, ACCOUNT, uid='u2')
    answered(rig, 0, MATERIALS)
    rig.pump(1.0)
    assert heard(rig, 'Купили материалы') and not heard(rig, 'старого звонка')


def test_b17_after_the_drop_the_plan_is_the_files_and_a_repeat_says_its_portion(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    first = chunks_of(rig)[0]
    rig.pump(1.0)
    rebuilt(rig)
    rig.c.max_auto_repeats = 0
    rig.pump(3.0)
    said_to_the_room(rig, 'u1', 'Повтори, я не расслышал')
    job_mark(rig, 0, '[повтори]')
    rig.pump(TICK * 2)
    assert rig.said()[-1] == first, rig.said()
    assert rig.c.state()['chunk_index'] == 0
