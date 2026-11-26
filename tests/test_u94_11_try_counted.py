"""U94.11 (group G): the owner's repeat of the waiting portion, heard by the ear with no final, is a try (counted), and no new repeat is armed over it. The decision of ``ControlledMedia._try_counted`` on the real controller of the h31 rig;
the scene of the call of 13.11 (two loops of 87 s) goes through the replay in the cloud. Not a measurement of a call."""
import pytest

from tools.replay import quantity as Q


@pytest.fixture
def rig():
    rig = Q.rig_of()
    yield rig
    rig.close()
    rig._mp.undo()


def test_the_words_of_the_portion_are_a_try_and_other_words_are_not(rig):
    Q.ear_only(rig, 'Что такое инфляция?')
    rig.pump(1.0)
    state = rig.c.state()
    portion = rig.c.engine.current(state)
    assert portion and rig.c._try_counted(portion, state), 'the portion said back whole'
    assert not rig.c._try_counted('рост цен это вообще про другое было вчера у них в городе', state)
