"""c24-c (§11.4 «переподключение»): the plan and the cursor of a session outlive a reconnect (SQLite); so must what the owner said of dictation («я буду записывать» / «хватит диктовать»)
and the tempo of writing learned from them: a new call of the same session starts where the old one was. Another session starts from its profile. Not a measurement of a call."""
import logging

import pytest

import helpers_s6_state as S


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def test_dictation_said_and_the_tempo_outlive_a_reconnect():
    world = S.World()
    try:
        c = world.controller
        assert not c.dictation
        c.dictating.heard('dictation_on', c.settings)
        c.dictating.pace.observe('один два три четыре', 12.0)
        c.dictating.keep()      # as ``_tempo_heard`` does after each portion it learns from
        per_word = c.dictating.pace.per_word
        world.reconnect()
        assert world.controller is not c and world.controller.dictation and world.controller.dictating.pace.per_word == per_word
        world.controller.dictating.heard('dictation_off', world.controller.settings)
        world.reconnect()
        assert not world.controller.dictation
    finally:
        world.close()


def test_another_session_starts_from_its_profile():
    one, two = S.World(), S.World()
    try:
        one.controller.dictating.heard('dictation_on', one.controller.settings)
        assert not two.controller.dictation or two.session_id == one.session_id
    finally:
        one.close()
        two.close()
