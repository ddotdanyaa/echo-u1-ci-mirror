"""V5 / S2 (do not lose yourself in a half-hour talk): the stand of G18 (tools.replay.half_hour: the real chain ControlledMedia + NativeMediaSocket + ShadowEar + FastText, seconds of the stand's clock).
A longer call than the one of tests/test_half_hour.py (30 questions over 15 stand minutes): every question answered in place, no step of two portions, no portion given twice after a try that was owed the
next one. The confirmation of S2 is a call (phone): nothing here is one. A red seed is a defect card for the family P (portion) / K."""
import pytest

from tools.replay import half_hour as H


@pytest.mark.parametrize('seed', [2, 4])
def test_s2_thirty_questions_in_fifteen_minutes_are_answered_in_place(seed):
    r = H.one(seed, questions=30, minutes=15.0)
    assert r['asked'] == 30 and not r['crash'], r.get('crash')
    kinds = [e[0] for e in r['events']]
    assert 'unanswered' not in kinds and 'skipped' not in kinds, r['events']
