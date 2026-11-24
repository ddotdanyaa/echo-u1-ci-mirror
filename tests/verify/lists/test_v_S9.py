"""V7 С9 (BACKLOG 4.9: «вопрос с листка, запись ответа, возврат к выступлению», via Ф8 and Ф9): the question read off the sheet, its answer written portion by portion by the owner's last words, then the owner
goes back to the talk: after the last portion nothing sounds, no model job is opened for the talk, and the silence of the talk is not cut into. Ф8 (the stages in order) is in ``test_v_F8.py``, Ф9 (the
cycle of dictation) is closed by h25 and ``tests/test_c24_lecture.py``.

Real chain of the h3 rig (``tools.replay.c24_lecture.Talk``). The steps up to the last portion are the ones ``connected`` already proves; the two after it are the new expectations of this file (nothing sounds after
the end of the written answer; the talk's own speech opens no more jobs than the arbiter's own, ``talk_jobs``). Not run on the laptop; the iPhone part stays with the owner."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.replay import c24_lecture as L      # noqa: E402
from tools.replay import repeat_scenes as R    # noqa: E402


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def test_the_sheet_question_is_written_to_its_end_and_the_owner_goes_back_to_the_talk_in_quiet():
    board = L.Board()
    t = L.Talk(L.DICTATING, board, 'sheet_and_back')
    try:
        t.step('talk', ('say', 'Налоги делятся на прямые и косвенные.'), talk=True)
        t.step('dictation on', ('say', 'я буду записывать'), wait=1.0)
        t.step('sheet question', ('say', L.B_ASK), cues=[L.B[0]], index=0, jobs=1, answer=' '.join(L.B), wait=1.0)
        t.step('last word 1', ('say', 'гражданина'), cues=[L.B[1]], index=1, nexts=1)
        t.step('last word 2', ('say', 'налогом'), cues=[L.B[2]], index=2, nexts=1)
        t.step('last word 3', ('say', 'рублей'), cues=[L.B[3]], index=3, nexts=1)
        mark = len(t.rig.cues())
        R.utter(t.rig, 'инспекцию')      # the last portion written: the end of the answer
        t.rig.pump(L.ANSWER_WAIT_S)
        assert [c.text for c in t.rig.cues()[mark:]] == [], 'nothing sounds after the last portion is written'
        t.step('back to the talk', ('say', 'Хорошо, вернёмся к презентации о налогах.'), talk=True, wait=L.ANSWER_WAIT_S + 0.5)
        t.step('the talk goes on', ('say', 'Итак, следующая тема: страховые взносы.'), talk=True, wait=3.0)
        t.step('quiet in the talk', ('silence', 20.0), writing=True)
    finally:
        t.close()
    assert not board.bad(), (board.n, board.episodes)
