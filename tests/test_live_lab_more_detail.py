"""Live lab, level2-c of 06.11 (step 45): the listener says «Подробнее.» over a waiting portion of «Что такое юридическое лицо».  The job (the text channel) read it as a
request to go on and said the mark ``[продолжай]``; the controller took the mark for the listener's command (``_fast_command``: ``suspended_answer_resumed``,
``resume_continue:the_portion_again``) and said the waiting portion «Организация со своим имуществом и ответственностью.» AGAIN as the answer: no detail at all
(no_stale_audio FAIL).  «Подробнее» is a request for more of the answer (``MORE_DETAIL``, the owner's call of 06.11: the model answers it, with the material), never a
command to go on: a mark that the words do not say is no command, the portion that waits stays where it is."""
import logging

import pytest

from test_h3_tempo import TICK, call   # noqa: F401 - call is the fixture
from test_h5_live import LIVE, NOTICE, QUESTION, cloud, decisions, job_mark, plan, said_to_the_room


@pytest.fixture(autouse=True)
def info_log(caplog):
    caplog.set_level(logging.INFO)


@pytest.mark.parametrize('heard', ['Подробнее', 'Подробнее.', 'А можно поподробнее'])
@pytest.mark.parametrize('mark', ['[продолжай]', '[дальше]'])
def test_more_detail_is_no_go_on_whatever_mark_the_job_says(call, caplog, heard, mark):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    said_to_the_room(rig, 'u1', heard)
    job_mark(rig, 1, mark)
    rig.pump(TICK * 2)
    assert rig.said() == [NOTICE], ('the waiting portion was said again as the answer to a request for detail', rig.said())
    assert not decisions(caplog, 'suspended_answer_resumed') and not decisions(caplog, 'resume_continue'), 'the mark was carried out as a command'


DETAIL = 'Если подробнее: минимальный срок указан в законе, а соглашение сторон может его увеличить.'


def test_the_clouds_answer_to_a_request_for_detail_is_the_answer_after_the_mark(call):
    rig = call(**LIVE)
    plan(rig, asked=QUESTION, answer=NOTICE)
    said_to_the_room(rig, 'u1', 'Подробнее')
    job_mark(rig, 1, '[продолжай]')
    cloud(rig, 'a1', DETAIL)
    rig.pump(TICK * 4)
    assert rig.said()[0] == NOTICE and rig.said().count(NOTICE) == 1 and any(cue.startswith('Если подробнее') for cue in rig.said()), rig.said()
