"""V1a E08.1 (file named with ``_``: a dot cannot be in a module name): the pairs «the same words, another addressee» through the real ControlledMedia.

The words are the same, the label (to the listener / to another) is not in the text; what is in the text is the vocative. So a pair here is (the words said to a named other person, the same words without the name): the first is
DISTINGUISHABLE and has to end in the limited action (no sound, the cursor where it stood, no job, no public search); the second is NOT distinguishable from a question to the listener, and the test only holds it to the bound
every undecided utterance has: no sound before a job answered, no public search of what is about the speaker («мою», «ты как»). The table «pair -> outcome -> distinguishable?» is the assertion message of the two tests (``got``).
Author's note, not a run: the verdicts of ``gate_text`` for the first rows are the cases N23/E08 of tests/test_gate_text.py (a remark to a person by name: TALK, ``to_person``, quiet without the model).
"""
import pytest

from kind_a_kit import LIVE_RULES, TERM_ANSWER, TERM_QUESTION, TICK, let_jobs_decline, mark, only_the_plan_sounds, plan, said_to_the_room
from test_h3_tempo import call      # noqa: F401 - the fixture

PAIRS = [
    ('Миша, ты зарядку мою не видел?', 'ты зарядку мою не видел?'),
    ('Лена, ты домашку сделала?', 'ты домашку сделала?'),
    ('Паша, а ты как к этому относишься?', 'а ты как к этому относишься?'),
    ('Света, скажи, во сколько завтра выезжаем?', 'скажи, во сколько завтра выезжаем?'),
    ('Коллеги, а вы во сколько завтра выезжаете?', 'а вы во сколько завтра выезжаете?'),
]


def outcome(call, text):
    """The plan waits; ``text`` is said by a voice that is not asked for; what the controller did with it (a job decides nothing here: it declines, so a sound can only be the controller's own)."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=TERM_QUESTION, answer=TERM_ANSWER)
    before = mark(rig)
    said_to_the_room(rig, 'p1', text)
    rig.pump(TICK)
    asked = len(rig.fake.runs) - before['runs']
    let_jobs_decline(rig, before['runs'])
    rig.pump(6.0)
    after = mark(rig)
    heard = only_the_plan_sounds(rig, before)
    return {'text': text, 'jobs': asked, 'new_sounds': heard, 'lookups': after['lookups'] - before['lookups'], 'moved': (after['revision'], after['index']) != (before['revision'], before['index'])}


@pytest.mark.parametrize('named, bare', PAIRS, ids=[p[0][:24] for p in PAIRS])
def test_the_words_to_a_named_other_person_end_in_the_limited_action(call, named, bare):
    got = outcome(call, named)
    assert got['jobs'] == 0 and not got['new_sounds'] and got['lookups'] == 0 and not got['moved'], got


@pytest.mark.parametrize('named, bare', PAIRS, ids=[p[0][:24] for p in PAIRS])
def test_the_same_words_without_the_name_are_held_to_the_bound_of_an_undecided_utterance(call, named, bare):
    got = outcome(call, bare)
    assert not got['new_sounds'] and got['lookups'] == 0 and not got['moved'], got

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
