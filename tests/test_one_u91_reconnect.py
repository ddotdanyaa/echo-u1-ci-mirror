"""one-input U91: «one final, one answer» across a reconnect (the line drops and the cloud sends the same final again over the new one), through the controller and the native socket;
the conversation of the memory goes on across a break shorter than CONVERSATION_GAP_S (test_m1_memory.py::test_e_*)."""
import logging

import pytest

import helpers_s6_state as S

QUESTION = 'Сколько будет сорок на два'


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def spoken(world):
    return [cue.text for cue in world.cues if not cue.diagnostic]


def ask_and_answer(world):
    world.feed(S.turn_created('u1', 'user', 'Сколько'))
    world.feed(S.turn_done('u1', 'user', QUESTION))
    world.feed(S.turn_done('a1', 'assistant', 'Восемьдесят.'))
    world.advance(6.0)


def test_a_final_repeated_after_a_reconnect_is_no_second_answer():
    world = S.World()
    try:
        ask_and_answer(world)
        said = spoken(world)
        assert said, 'precondition: the question was answered'
        world.advance(20.0)
        world.reconnect()
        world.feed(S.turn_done('u1', 'user', QUESTION))
        world.feed(S.turn_done('a1b', 'assistant', 'Восемьдесят.'))
        world.advance(8.0)
        assert spoken(world) == said, 'one final, one answer'
    finally:
        world.close()


def test_a_new_question_after_a_reconnect_is_answered():
    world = S.World()
    try:
        ask_and_answer(world)
        said = len(spoken(world))
        world.advance(20.0)
        world.reconnect()
        world.feed(S.turn_done('u2', 'user', 'Сколько будет пятьдесят на три'))
        world.feed(S.turn_done('a2', 'assistant', 'Сто пятьдесят.'))
        world.advance(8.0)
        assert len(spoken(world)) > said
    finally:
        world.close()
