"""E72: a long remark with no question form that ends on a question is answered by a short fact (7 words, 3 words of the question), not dropped by ``_talk_no_question``.
A reply that carries fewer than 3 words of the remark stays talk (h29 / U35). Through the real ControlledMedia (the stand of test_h3_tempo)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_h3_tempo import call      # noqa: F401 - call is the fixture
from test_h5_live import asked
from test_h7 import CALL_1027, SAID_KALKA, job_answers


def run(call, said, reply):
    rig = call(**CALL_1027)
    asked(rig, said)
    rig.pump(0.4)
    job_answers(rig, 0, reply)
    rig.pump(0.2)
    return rig


def test_a_short_fact_of_seven_words_with_the_words_of_the_question_is_said(call):
    assert run(call, SAID_KALKA, 'Битва при Калке произошла в 1223 году.').said() == ['Битва при Калке произошла в 1223 году.']


@pytest.mark.parametrize('reply', ['Битва была давно, в тринадцатом веке, это известно.', 'Да, это интересная тема, давай обсудим её подробнее потом.'])
def test_a_reply_with_fewer_than_three_words_of_the_remark_stays_talk(call, reply):
    assert run(call, SAID_KALKA, reply).said() == []
