"""G3 chaos (tools/replay/chaos.py): a chain of questions through the stand's real chain, one failure thrown in at one step of it.

After the failure the next question gets its own answer, the call lives, the old answer does not come back, no portion is stuck, the log names
the cause (C1-C5 of the module), and the stand's own invariants hold. A failure of an optional part (the ear, the journal, the cache, the
lookup) never takes the main one down. Nothing here is a measurement of time on a laptop or a phone.
"""
import pytest

from tools.replay import chaos
from tools.replay.chaos import FAULTS, HARD


def hard(out):
    return [v for v in out.violations if v[0] in HARD]


def test_a_seed_and_a_fault_are_one_conversation():
    """The same questions, the same faults, the same verdict. Not cue for cue: under load a cue may move by a tick of 0.1 s between two runs (the job's thread
    hands its text to the loop on its own time; more often with ``two_witnesses``; see the report)."""
    for profile in (dict(chaos.CANDIDATE),):
        first, second = chaos.run(3, 'model_cut', 2, profile=dict(profile)), chaos.run(3, 'model_cut', 2, profile=dict(profile))
        assert first.asked == second.asked and len(first.asked) == chaos.STEPS
        assert hard(first) == hard(second) == []
        assert [c[1] for c in first.cues if not c[6]][:2] == [c[1] for c in second.cues if not c[6]][:2]


def test_the_control_without_a_fault_is_clean():
    for seed in range(4):
        out = chaos.run(seed, 'none', 2)
        assert not hard(out), (seed, hard(out))


@pytest.mark.parametrize('fault', [f for f in FAULTS if f != 'none'])
@pytest.mark.parametrize('at', chaos.ATS)
def test_after_the_fault_the_next_question_is_answered_and_nothing_is_stuck(fault, at):
    for seed in range(3):
        out = chaos.run(seed, fault, at)
        assert len(out.asked) == chaos.STEPS, (seed, 'the chain stalled')
        assert not hard(out), (seed, hard(out)[:3])


def test_the_checks_fire_on_a_scene_built_to_break_them(monkeypatch):
    """C5 fires when nothing names the cause; C1 when the later questions get no answer (a model that never says a word to anything)."""
    monkeypatch.setitem(chaos.CAUSES, 'none', r'^this line is never logged$')
    assert [v for v in chaos.run(0, 'none', 2).violations if v[0] == 'C5']

    def mute(self, job, thread):
        self.runs[id(job.request)] = chaos.ST.Run(job, thread, self.now())
    monkeypatch.setattr(chaos.Chaos, '_born', mute)
    assert [v for v in chaos.run(0, 'none', 2).violations if v[0] == 'C1']


@pytest.mark.parametrize('fault', ('model_hang', 'model_cut'))
def test_a_question_the_ear_stood_for_whose_job_breaks_is_not_left_in_silence(fault):
    """Seed 13, the third question (seed 3 no longer makes this scene: its ear job is refused by the final's words and the final's own job answers, so no phrase is owed): the cloud's final is late, the ear stands in (``no_final_the_ear_stands_in``: one job, no retry), the job hangs
    (or breaks) and the candidate goes back to the cloud's evidence (``fast_text_candidate_handed_back``); the cloud says nothing for it. Before the fix
    nothing ever came: no answer, no phrase, the question was never the controller's and the watchdog had nothing to count. Now the honest phrase."""
    out = chaos.run(13, fault, 3)
    assert not hard(out), hard(out)[:3]
    assert any('candidate_unanswered' in line or 'fast_text refusal' in line for _, line in out.chaos_lines), 'the log names why the phrase was said (the controller\'s, or the roads\' own sentence at REFUSE_AFTER_S)'


@pytest.mark.parametrize('fault', ('model_hang', 'model_cut'))
def test_the_old_plan_is_not_repeated_over_a_new_question_whose_job_broke(fault):
    """Seed 6, the second question: the ear stands in for its final, its job hangs (or breaks), the candidate goes back to the cloud, and the silence repeat of the
    tempo said the portion of question 1 again (A2: an older answer after a newer question), as W14 forbids for a new question nobody answered."""
    out = chaos.run(6, fault, 2)
    assert not hard(out), hard(out)[:3]


def test_a_question_the_ear_stood_for_is_known_by_the_clouds_final_that_came_after():
    """Seed 12, the third question: the ear's words carry no question mark («нужно не увеличивать а уменьшать …»), the cloud's final with it came 0.3 s after the ear stood
    in (a turn of its own); the job hung. The phrase is owed: the candidate is a question by the cloud's words."""
    out = chaos.run(12, 'model_hang', 3)
    assert not [v for v in out.violations if v[0] in ('A5', 'C1')], hard(out)[:3]
    assert any('candidate_unanswered' in line or 'fast_text refusal' in line for _, line in out.chaos_lines)
