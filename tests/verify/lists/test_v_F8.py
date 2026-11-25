"""V7 Ф8: presentation -> a question of the hall -> a question read aloud off the sheet -> the answer written by hand -> back to the place (BACKLOG 4.8, c24-c).

The stand is the real chain of the h3 rig (ControlledMedia, NativeMediaSocket, ShadowEar, FastText on the injected clock; the ear, the cloud and the job scripted), ``tools.replay.c24_lecture``. The fix
that stands behind it is h25 `299939dd` (c24-c taken). ``tests/test_c24_lecture.py`` already runs the same scenes and counts only the totals; this file says the ORDER of the stages and what sounded in
each, so a red names the stage. Seconds are the rig's, not a phone's: the iPhone part of Ф8 stays with the owner. Not run on the laptop."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.replay import c24_lecture as L      # noqa: E402


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def log(monkeypatch):
    """Every step of the stand: (label, the cues that sounded in it)."""
    seen = []
    original = L.Talk.step

    def step(self, label, act, **kw):
        texts = original(self, label, act, **kw)
        seen.append((label, tuple(texts)))
        return texts
    monkeypatch.setattr(L.Talk, 'step', step)
    return seen


def test_the_talk_goes_through_the_stages_in_their_order_and_each_says_what_it_owes(log):
    board = L.connected()
    assert not board.bad(), (board.n, board.episodes)
    said = dict(log)
    labels = [label for label, _ in log]
    order = ['intro', 'talk', 'hall question', 'answer aloud', 'back to the talk', 'dictation on', 'sheet question', 'silence writing', 'last word', 'question corrected', 'stop']
    assert [label for label in labels if label in order] == order, labels
    assert said['intro'] == () and said['talk'] == (), 'the talk itself is no question: nothing sounds over it'
    assert said['hall question'] == (L.A[0],), 'the question of the hall: its answer begins at once'
    assert said['answer aloud'] == (L.A[1],), 'the hall answer is said aloud: its next portion follows by the last word'
    assert said['back to the talk'] == (), 'back to the talk: the old answer does not come back by itself'
    assert said['sheet question'] == (L.B[0],), 'the question read off the sheet: the answer to be written begins'
    assert said['silence writing'] == (), 'the owner writes in silence: no cue cuts in'
    assert said['last word'] == (L.B[1],), 'the last word written: the next portion'
    assert said['question corrected'] == (L.C[0],), 'the corrected question: the new answer, from its first portion'
    assert said['stop'] == (), 'stop: nothing sounds'


def test_the_hall_question_while_writing_and_the_return_by_the_owners_word_to_the_place_being_written(log):
    for back in ('вернёмся к прошлому ответу', 'продолжай'):
        log.clear()
        board = L.hall_and_back(back=back)
        assert board.n['steps'] == 6 and not board.bad(), (back, board.n, board.episodes)
        said = dict(log)
        assert said['hall question'] == (L.A[0],) and said['A said'] == (L.A[1],), said
        assert said['no return by itself'] == (), 'the old plan stays quiet 25 s: it waits for the owner'
        assert said['back by intent'] == (L.B[1],), f'{back!r}: the portion being written, not its start and not past it'

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
