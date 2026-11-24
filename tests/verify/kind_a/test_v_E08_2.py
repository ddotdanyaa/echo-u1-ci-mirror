"""V1a E08.2: «a tracker of whom the last question was addressed to» is conditional (only if the pairs of E08.1 are separable by a feature; the backlog row is «отложено до результата E08.1»).

What can be verified now without building it: the short follow-ups of the others (the answer «Да, отправила.» to a question to a named person, a bare «Да.») are no question of the listener and sound nothing on their own, and
the family has no tracker to read (the grep below: nothing in echo_sync/ keeps «the addressee of the last question»). If the first test is red, the tracker stops being conditional: a defect card for the family K.
"""
import re
from pathlib import Path

import pytest

from kind_a_kit import LIVE_RULES, TERM_ANSWER, TERM_QUESTION, TICK, let_jobs_decline, mark, only_the_plan_sounds, plan, said_to_the_room
from test_h3_tempo import call      # noqa: F401 - the fixture

SRC = Path(__file__).resolve().parents[3] / 'echo_sync'


@pytest.mark.parametrize('follow', ['Да, отправила, вчера ещё.', 'Да.', 'Ага, сейчас посмотрю.'])
def test_a_follow_up_of_the_others_to_a_question_to_a_named_person_sounds_nothing(call, follow):
    rig = call(**LIVE_RULES)
    plan(rig, asked=TERM_QUESTION, answer=TERM_ANSWER)
    before = mark(rig)
    said_to_the_room(rig, 'e1', 'Лена, ты отчёт отправила?')
    rig.pump(0.8)
    said_to_the_room(rig, 'e2', follow)
    rig.pump(TICK)
    let_jobs_decline(rig, before['runs'])
    rig.pump(6.0)
    assert only_the_plan_sounds(rig, before) == [], only_the_plan_sounds(rig, before)
    assert mark(rig)['lookups'] == before['lookups']
    after = rig.w.snapshot()
    assert (after['revision'], after['index']) == (before['revision'], before['index'])


def test_no_addressee_tracker_exists_yet_so_the_conditional_row_is_still_conditional():
    """The row waits for E08.1. This is the guard that nobody built a half of it behind the owner's back: a new owner of «whom the last question was for» would have to be a row of the judge (``utterance_judge``), not a state of its own."""
    found = []
    for path in SRC.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        if re.search(r'(?i)(last_question_addressee|addressee_of_last|asked_whom|question_addressee)', text):
            found.append(path.name)
    assert found == [], found
