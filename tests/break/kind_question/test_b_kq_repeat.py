"""BREAK kind_question 4: «повтори» said twice, between «дальше», over a stop, after the end. The marks come from the job as the call does it. Real ControlledMedia, not run on the laptop.
Class of problem: К6 (the repeat depends on a mode), К21 (modes and commands), К26 (a repeat into the void), A3/A5 of the stand (a step with no utterance, a portion said again in silence)."""
from break_kit import ACCOUNT, LIVE_RULES, MATERIALS, NOTICE, S, TICK, call, chunks_of, index_of, job_mark, plan, said_to_the_room    # noqa: F401 - call is the fixture


def test_b08_two_repeats_say_the_portion_twice_more_and_the_cursor_never_moves(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.c.max_auto_repeats = 0
    first = chunks_of(rig)[0]
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Повтори, пожалуйста')
    job_mark(rig, 1, '[повтори]')
    rig.pump(1.0)
    said_to_the_room(rig, 'u2', 'Ещё раз повтори')
    job_mark(rig, 2, '[повтори]')
    rig.pump(TICK * 3)
    assert rig.said() == [first, first, first], rig.said()
    assert index_of(rig) == 0


def test_b09_repeat_next_repeat_repeats_the_portion_the_listener_is_on(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.c.max_auto_repeats = 0
    first, second = chunks_of(rig)[:2]
    for n, (uid, text, mark) in enumerate([('u1', 'Повтори', '[повтори]'), ('u2', 'Так, а дальше что', '[дальше]'), ('u3', 'Повтори ещё раз', '[повтори]')], start=1):
        rig.pump(1.0)
        said_to_the_room(rig, uid, text)
        job_mark(rig, n, mark)
        rig.pump(TICK * 2)
    assert rig.said() == [first, first, second, second], rig.said()
    assert index_of(rig) == 1


def test_b10_repeats_after_the_end_of_the_answer_say_its_last_portion_each_time(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked='Что такое инерция', answer=NOTICE)
    rig.c.max_auto_repeats = 0
    rig.w.feed(S.turn_done('u1', 'user', NOTICE))
    rig.pump(TICK * 3)
    assert rig.c.state()['completed'] is True
    for n, uid in enumerate(['u2', 'u3'], start=1):
        said_to_the_room(rig, uid, 'Как ты сказала?')
        job_mark(rig, n, '[повтори]')
        rig.pump(1.0)
    assert rig.said() == [NOTICE, NOTICE, NOTICE], rig.said()


def test_b11_a_repeat_asked_inside_a_stop_says_the_portion_once_and_the_stop_holds(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    first = chunks_of(rig)[0]
    rig.pump(1.0)
    said_to_the_room(rig, 'u1', 'Стоп, подождите секунду')
    job_mark(rig, 1, '[стоп]')
    assert rig.c.state()['paused'] is True
    rig.pump(5.0)
    said_to_the_room(rig, 'u2', 'Повтори последнее')
    job_mark(rig, 2, '[повтори]')
    rig.pump(TICK * 2)
    assert rig.said() == [first, first], rig.said()
    rig.pump(70.0)
    assert rig.said() == [first, first], 'the stop did not hold after the repeat: the cycle went on by itself'
