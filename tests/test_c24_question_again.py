"""c24-c item 4: the question read again while its answer is being written. The same words (numbers, «не», their roles: ``fast_text.same_question`` both ways): the portion in hand is said
again from its start, the place kept, no new job (no model call, no lookup). A number or a «не» changed, another question: a new question, as ever (no old answer, no old sound). Dictating only:
in talk a question asked again stays a question (g28). Through the real chain of the h3 rig. Not a measurement of a call."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.replay import repeat_scenes as R      # noqa: E402

ASK = 'Какая ставка налога на доходы физических лиц?'
ANSWER = 'Основная ставка налога на доходы составляет 13 процентов. Пособие по беременности не облагается налогом. Декларацию подают до 30 апреля.'
P1 = 'Пособие по беременности не облагается налогом.'


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def at_second(flags):
    rig = R.make_rig(flags)
    rig.asks('q1', ASK, 0, ANSWER)
    rig.pump(0.5)
    R.utter(rig, 'основная ставка налога на доходы составляет 13 процентов')
    rig.pump(2.0)
    assert rig.said()[-1] == P1, rig.said()
    return rig


@pytest.fixture
def dictating():
    rig = at_second({'dictation': 'on'})
    yield rig
    rig.close()
    rig._mp.undo()


def where(rig):
    s = rig.c.state() or {}
    return s.get('revision'), s.get('chunk_index')


def test_the_same_question_read_again_is_the_portion_again_and_no_job(dictating):
    rig = dictating
    from echo_sync import pcm_cache
    from test_c24_repeat_pcm import host_like
    memo = pcm_cache.PcmCache()
    renders = host_like(rig, memo)
    memo.remember(P1, 'v|None', 24000, b'\x00\x40' * 12000)      # the sound the call made when it said the portion
    before, runs, lookups, mark = where(rig), len(rig.fake.runs), len(rig.w.lookup_calls), len(rig.cues())
    R.utter(rig, ASK)
    rig.pump(3.0)
    assert [c.text for c in rig.cues()[mark:]] == [P1], [c.text for c in rig.cues()[mark:]]
    assert where(rig) == before and len(rig.fake.runs) == runs and len(rig.w.lookup_calls) == lookups, (where(rig), before, len(rig.fake.runs) - runs)
    assert renders == [] and memo.reused == 1      # and its sound is the one already made


@pytest.mark.parametrize('changed', ['Какая ставка налога на доходы физических лиц 15 процентов?', 'Какая ставка налога на доходы не резидентов?',
                                     'Что такое налоговый вычет?'])
def test_a_changed_question_is_a_new_question(dictating, changed):
    rig = dictating
    runs = len(rig.fake.runs)
    R.utter(rig, changed)
    rig.pump(3.0)
    assert len(rig.fake.runs) > runs, 'a new question goes to the job'
    assert P1 not in [c.text for c in rig.cues()[-1:]] or where(rig)[0] != 1


def test_in_talk_the_same_question_asked_again_stays_a_question():
    rig = at_second({})
    try:
        runs = len(rig.fake.runs)
        R.utter(rig, ASK)
        rig.pump(3.0)
        assert len(rig.fake.runs) > runs or where(rig)[0] != 1
    finally:
        rig.close()
        rig._mp.undo()
