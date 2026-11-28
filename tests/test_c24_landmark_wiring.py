"""c24-c item 2 on the controller: a landmark said while dictating moves the help of the CURRENT portion (the one plan, the one cursor: ``tempo_start`` as a stumble's help), never the
cursor itself, but for «последнее записанное слово» of its last word (the rule's one NEXT). Through the real chain of the h3 rig (``tools/replay/repeat_scenes``). Not a measurement of a call."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.replay import repeat_scenes as R      # noqa: E402

ON = {'dictation': 'on'}
ASK, PORTIONS = R.ANSWERS[2]      # «Налоговый вычет уменьшает облагаемый доход гражданина.» …


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def rig():
    rig = R.make_rig(ON)
    rig.asks('q1', ASK, 0, ' '.join(PORTIONS))
    rig.pump(0.5)
    yield rig
    rig.close()
    rig._mp.undo()


def said_after(rig, text, within=4.0):
    mark = len(rig.cues())
    R.utter(rig, text)
    rig.pump(within)
    return [c.text for c in rig.cues()[mark:]]


def index(rig):
    return (rig.c.state() or {}).get('chunk_index')


def test_from_the_word_includes_it(rig):
    assert said_after(rig, 'повтори со слова облагаемый') == ['облагаемый доход гражданина.'] and index(rig) == 0


def test_after_the_last_written_word_goes_on_after_it(rig):
    assert said_after(rig, 'последнее записанное слово облагаемый') == ['доход гражданина.'] and index(rig) == 0


def test_the_last_word_of_the_portion_written_is_one_next(rig):
    assert said_after(rig, 'последнее записанное слово гражданина', within=3.0) == [PORTIONS[1]] and index(rig) == 1


def test_from_the_last_word_is_no_next(rig):
    assert said_after(rig, 'повтори со слова гражданина') == ['гражданина.'] and index(rig) == 0


def test_a_word_of_the_next_portion_jumps_over_nothing(rig):
    got = said_after(rig, 'я записал покупке', within=3.0)
    assert index(rig) == 0 and PORTIONS[1] not in got, got


NEG_ANSWER = 'Основная ставка налога на доходы составляет 13 процентов. Пособие по беременности не облагается налогом. Декларацию подают до 30 апреля.'


@pytest.fixture
def neg():
    rig = R.make_rig(ON)
    rig.asks('q1', 'Какая ставка налога на доходы физических лиц?', 0, NEG_ANSWER)
    rig.pump(0.5)
    R.utter(rig, 'основная ставка налога на доходы составляет 13 процентов')
    rig.pump(2.0)
    assert rig.said()[-1] == 'Пособие по беременности не облагается налогом.' and index(rig) == 1, rig.said()
    yield rig
    rig.close()
    rig._mp.undo()


def test_the_words_before_the_last_get_the_tail_after_the_pen_wait(neg):
    from echo_sync.repeat_rule import DICTATION_START_SECONDS
    mark = len(neg.cues())
    _, ended = R.utter(neg, 'не облагается')
    neg.pump(DICTATION_START_SECONDS + 1.5)
    got = neg.cues()[mark:]
    assert [c.text for c in got] == ['налогом.'] and index(neg) == 1, [c.text for c in got]
    assert said_after(neg, 'налогом', within=3.0) == ['Декларацию подают до 30 апреля.'] and index(neg) == 2      # then the last word: one NEXT


def test_the_last_word_said_within_the_pen_wait_is_one_next_and_no_tail(neg):
    R.utter(neg, 'не облагается')
    neg.pump(1.0)
    assert said_after(neg, 'налогом', within=6.0) == ['Декларацию подают до 30 апреля.'] and index(neg) == 2

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
