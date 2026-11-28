"""R31-6: «повтори последние N слов» is a command of the one landmark place (``repeat_rule.landmark_command``): the last N words of the portion that waits are said again, by code, with no model, and the request is no «Угу» and no repeat of the
whole portion. Through the real chain of the h3 rig (``tools/replay/repeat_scenes``, the real ControlledMedia). Not a measurement of a call."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echo_sync.repeat_rule import last_words_command, landmark_command      # noqa: E402
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


def test_the_command_reads_digits_and_number_words_and_nothing_else():
    assert last_words_command('повтори последние три слова') == 3
    assert last_words_command('Повтори последние 20 слов') == 20
    assert last_words_command('скажи мне последних двадцать пять слов') == 25
    assert last_words_command('повтори последние слова') is None, 'no number'
    assert last_words_command('повтори последнее слово') is None, 'no number: the other command of the place'
    assert last_words_command('последнее слово налог') is None, 'no verb: the last word WRITTEN (``_AFTER``)'
    assert last_words_command('повтори последние сто слов') is None, 'a number a mouth does not ask for'
    assert landmark_command('повтори последние три слова') == ('last', ('3',))
    assert landmark_command('повтори со слова облагаемый')[0] == 'from', 'the other commands of the place are as they were'


def test_the_last_three_words_of_the_portion_are_said_again_not_the_whole_portion(rig):
    got = said_after(rig, 'повтори последние три слова')
    assert got == ['облагаемый доход гражданина.'], got
    assert (rig.c.state() or {}).get('chunk_index') == 0, 'the cursor stays on the portion'


def test_more_words_than_the_portion_has_say_the_portion_whole(rig):
    got = said_after(rig, 'повтори последние пятьдесят слов')
    assert got == [PORTIONS[0]], got
