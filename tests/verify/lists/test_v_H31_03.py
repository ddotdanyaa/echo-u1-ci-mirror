"""V7 H31-03 (К14, BACKLOG 4.10: «тест целой сцены с разными вопросами подряд»; the owner: «принят не тот вопрос», «постоянно повторяет и даже не слышит меня»): four different questions in a row, each
asked while the answer to the one before is still being prompted. Each new question gets its own answer from its first portion; no cue of an older answer sounds after it; one job a question; the plan
at the end is the last answer's; the stand's world records no violation.

Real chain of the h3 rig (``tools.replay.repeat_scenes.make_rig``: ControlledMedia, NativeMediaSocket, ShadowEar, FastText; the cloud's turns, the job and the ear scripted), the candidate profile of the
stand. The questions and their answers are ``repeat_scenes.ANSWERS``. The part on the owner's phone (a person speaking in turn) stays with the owner. Not run on the laptop."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.replay import repeat_scenes as R      # noqa: E402


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.mark.parametrize('gap', [0.8, 0.0])
@pytest.mark.parametrize('flags', [{}], ids=['plain'])
def test_four_different_questions_in_a_row_each_get_their_own_answer_and_no_old_sound(flags, gap):
    rig = R.make_rig(flags)
    try:
        flat_answers = [R.flat(' '.join(portions)) for _, portions in R.ANSWERS]
        for n, (ask, portions) in enumerate(R.ANSWERS):
            mark, jobs = len(rig.cues()), len(rig.fake.runs)
            rig.asks(f'k{n}', ask, jobs, ' '.join(portions))
            new = [c.text for c in rig.cues()[mark:]]
            assert new, f'question {n}: nothing sounded for {ask!r}'
            assert R.flat(new[0]) and R.flat(new[0]) in flat_answers[n] and R.flat(new[0]) == R.flat(portions[0]), (n, ask, new)
            assert all(R.flat(text) in flat_answers[n] for text in new), f'question {n}: a cue of another answer: {new}'
            assert len(rig.fake.runs) == jobs + 1, f'question {n}: one job a question, got {len(rig.fake.runs) - jobs}'
            rig.pump(gap)
            later = [c.text for c in rig.cues()[mark + len(new):]]
            assert all(R.flat(text) in flat_answers[n] for text in later), f'question {n}: an older answer sounds after the new question: {later}'
        plan = R.flat(' '.join((rig.c.state() or {}).get('chunks') or ()))
        assert plan and plan in flat_answers[-1], f'the plan at the end is not the last answer: {plan!r}'
        assert rig.w.violations == [], rig.w.violations
    finally:
        rig.close()
        rig._mp.undo()
