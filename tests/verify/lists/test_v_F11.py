"""V7 Ф11: the other clarifications of FOLLOWUP §11 (BACKLOG 4.8: «c24-c, c24-e», report c24-final). §11.4 names the scenes the stand must have; each is mapped here to the scene that runs it, and the
count the owner asked for is held on every one: no lost or doubled NEXT, no wrong place of the tail, no old sound, no cut-in while writing, no model job on a repeat, no TTS render for a repeat (§11.3).

Real chain of the h3 rig (``tools.replay.c24_lecture``, ``tools.replay.no_cloud``). Not mapped, with the reason: «одновременная речь» of two people through one channel is no scene of its own (§11.2 last row:
one signal does not tell the speaker); the stand has the stranger's words (connected) and the cue heard back (echo). The minutes of a phone and the comfort of a person are not measured here. Not run on the
laptop."""
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


# §11.4 item -> the scenes of the stand that run it
PAIR_SCENES = {
    'repeated ASR final': ('final_twice',),
    'repeated last word': ('last_word_alone', 'final_twice', 'last_written_is_last'),
    'the word before the last': ('after_word', 'from_last_word'),
    'a landmark in the middle': ('from_word', 'after_word', 'twin_first', 'twin_second'),
    'the next question read out': ('question_again', 'question_changed'),
    'the number corrected / wrong': ('number_wrong', 'number_right'),
    'the negation lost / kept': ('neg_dropped', 'neg_kept'),
    'noise': ('noise',),
    'long writing without speech': ('long_writing',),
    'STOP and back': ('stop_and_back',),
}


def test_every_item_of_the_list_has_scenes_that_exist():
    assert all(name in L.PAIRS for names in PAIR_SCENES.values() for name in names), sorted(n for names in PAIR_SCENES.values() for n in names if n not in L.PAIRS)


@pytest.mark.parametrize('item', sorted(PAIR_SCENES))
def test_the_item_of_the_list_holds_on_each_of_its_scenes(item):
    for name in PAIR_SCENES[item]:
        board = L.pair(name)
        assert board.n['steps'] >= 1 and not board.bad(), (item, name, board.n, board.episodes)


def test_the_confirmation_at_the_same_moment_as_the_timer_is_one_next():
    board = L.timer_and_ack()
    assert not board.bad(), (board.n, board.episodes)


def test_the_assistants_cue_heard_back_by_the_microphone_moves_nothing():
    board = L.echo()
    assert not board.bad(), (board.n, board.episodes)


def test_the_stranger_with_the_same_word_and_the_question_read_next_are_in_the_connected_talk():
    board = L.connected()
    assert board.n['steps'] == 19 and not board.bad(), (board.n, board.episodes)


def test_a_repeat_of_an_unchanged_portion_costs_no_model_job_and_no_tts_render_over_the_whole_set():
    """§11.3: the count over all scenes together: the portions repeated by the stand are served from the call's cache."""
    total = L.total(L.run_all())
    assert total.n['renders'] == 0 and total.n['extra_jobs'] == 0, (total.n, total.episodes)


def test_the_landmark_tail_after_the_owners_word_comes_at_once():
    for name in ('from_word', 'after_word', 'twin_first', 'twin_second'):
        board = L.pair(name)
        assert board.tail_s and max(board.tail_s) <= 0.6, (name, board.tail_s)


def test_cloud_gone_local_and_the_cloud_back_is_one_call_with_its_place_kept():
    """§11.4 «переподключение и cloud -> local -> cloud»: the g36 stand's rule NC6 (the cloud's return does not restart the call, the plan and its cursor kept) and NC7 (the outage told at most once)."""
    from tools.replay import no_cloud
    rec = no_cloud.run('refused', length=60.0)
    assert not rec.violations, rec.violations

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
