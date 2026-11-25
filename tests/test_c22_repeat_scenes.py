"""c22-repeat: the stand of scenes (``tools/replay/repeat_scenes``) on the rule's flags: every move by the rule goes on at the first try, nothing lost, no loop, no false step, nothing cut
into the writing. Off, the last word alone is the portion again (the board before). Nothing here is a measurement of a call."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.replay import repeat_scenes as R      # noqa: E402

ON = {'dictation': 'on'}


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.mark.parametrize('name', ['last_word', 'most', 'stumble_silent', 'dictation', 'voice_dictation', 'mixed'])
def test_the_rule_on_the_stand(name):
    board = R.scene(ON, R.SCENES[name], answers=R.ANSWERS[:2], name=name)
    n = board.n
    assert n['ack_first'] == n['moves'] and not (n['lost'] or n['loops'] or n['false_steps'] or n['wrong_help'] or n['cut_in'] or n['lost_answer']), (n, board.episodes)
    assert n['silence_whole'] == n['silences'], board.episodes


def test_a_marathon_does_not_lose_its_way_after_the_third_or_the_fifteenth_answer():
    board = R.scene(ON, ['whole', 'last2', 'most'], rounds=4, name='marathon16')
    assert board.n['answers'] == 16 and board.n['lost_answer'] == 0 and board.n['ack_first'] == board.n['moves'], (board.n, board.episodes)


def test_off_the_last_word_alone_is_not_taken():
    board = R.scene({}, R.SCENES['last_word'], answers=R.ANSWERS[:1], name='last_word')
    assert board.n['ack_first'] == 0 and board.n['moves'] == 3, board.n

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
