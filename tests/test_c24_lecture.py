"""c24-c: the owner's connected talk (FOLLOWUP §8) and the paired scenes of §11.4 on the stand (``tools/replay/c24_lecture``). Every step's cues, index and NEXT are written before it runs.
Nothing lost, nothing skipped, no wrong place, no old sound, nothing cut into the writing, no job on a repeat or a landmark, no TTS render for a repeat. Not a measurement of a call or a person."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.replay import c24_lecture as L      # noqa: E402


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def test_the_connected_talk():
    board = L.connected()
    assert board.n['steps'] == 19 and not board.bad(), (board.n, board.episodes)


def test_the_last_word_said_as_the_timer_comes_due_is_one_next():
    board = L.timer_and_ack()
    assert not board.bad(), (board.n, board.episodes)


@pytest.mark.parametrize('name', sorted(L.PAIRS))
def test_the_pairs(name):
    board = L.pair(name)
    assert board.n['steps'] >= 1 and not board.bad(), (board.n, board.episodes)


def test_a_landmark_tail_comes_at_once():
    for name in ('from_word', 'after_word', 'twin_first', 'twin_second'):
        board = L.pair(name)
        assert board.tail_s and max(board.tail_s) <= 0.6, (name, board.tail_s)


UNITS = ('рубл', 'тысяч', 'миллион', 'процент', 'апрел', 'мая', 'год', 'лет', 'месяц', 'дн')


def test_the_plan_of_a_call_cuts_no_number_from_its_unit_no_not_from_its_word_no_term():
    """The portions the call plans (the stand's chain, the profile's cutter): a number stays with its unit or date, «не» with its word, «Налоговым кодексом» whole. 5 words is no rule."""
    import re
    from tools.replay import repeat_scenes as R
    rig = R.make_rig({'dictation': 'on'})
    try:
        rig.asks('q', 'Какие бывают налоговые вычеты?', 0, 'Вычет на лечение составляет до 150 тысяч рублей в год на одного человека с учётом расходов на лекарства. '
                 'Пособие по беременности и родам в соответствии с Налоговым кодексом Российской Федерации не облагается налогом на доходы физических лиц. '
                 'Стандартный вычет на первого ребёнка составляет 1400 рублей в месяц, а на третьего ребёнка уже 6000 рублей. Декларацию подают до 30 апреля.')
        plan = list(rig.c.state()['chunks'])
    finally:
        rig.close()
        rig._mp.undo()
    for left, right in zip(plan, plan[1:]):
        assert not (re.search(r'\d\W*$', left) and right.lower().startswith(UNITS)), (left, right)
        assert not re.search(r'(?:^|\s)не\W*$', left.lower()), (left, right)
        assert not (left.endswith('Налоговым') and right.startswith('кодекс')), (left, right)


def test_a_question_of_the_hall_while_writing_and_back_by_intent():
    for back in ('вернёмся к прошлому ответу', 'продолжай'):
        board = L.hall_and_back(back=back)
        assert board.n['steps'] == 6 and not board.bad(), (back, board.n, board.episodes)


def test_the_cue_heard_back_while_it_plays_is_no_next_while_dictating():
    board = L.echo()
    assert not board.bad(), (board.n, board.episodes)


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
