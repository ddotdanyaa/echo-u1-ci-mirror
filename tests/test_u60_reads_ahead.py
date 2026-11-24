"""U60 (one-input, partly): the prepared text is a support: when the listener reads beyond the waiting portion into the next ones, the cursor (``EchoEngine._next`` through the controller) goes there: nothing is cued of what was read. The real controller, the ear and the wire on the injected clock (``test_h3_tempo``). Nothing here is a measurement of a call."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_h3_tempo import call       # noqa: F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of, utter

P4 = 'Побочным продуктом выделяется кислород.'
P5 = 'Так растения кормят себя и других.'


def talk(call):
    rig = rig_of(call)
    rig.asks('u1', ASK, 0, ' '.join((P1, P2, P3, P4, P5)))
    assert rig.said() == [P1]
    rig.pump(0.5)
    return rig


def read(rig, *portions, speech=6.0):
    heard = ' '.join(p.rstrip('.').lower() for p in portions)
    utter(rig, heard, speech=speech, turn='u2', final=heard + '.')
    rig.pump(1.0)


def test_reading_two_portions_beyond_the_cued_one_cues_the_next_unread(call):
    rig = talk(call)
    read(rig, P1, P2, P3)
    assert rig.said() == [P1, P4], rig.said()
    assert rig.c.state()['chunk_index'] == 3


def test_reading_three_portions_beyond_the_cued_one_cues_the_last(call):
    rig = talk(call)
    read(rig, P1, P2, P3, P4, speech=8.0)
    assert rig.said() == [P1, P5], rig.said()


def test_a_portion_of_its_own_in_the_reading_stops_the_jump(call):
    rig = talk(call)
    read(rig, P1, P2, 'А тут я скажу от себя совсем другое', speech=5.0)
    assert P4 not in rig.said() and P5 not in rig.said(), rig.said()
