"""V1a E81: «account for the answers of the other participants» - the backlog row is «отложено: только после D-4 и E08»; its one live clause is «чужие реплики не уходят в публичный поиск» and the others' answers keep the prompter quiet.

Verified on the real ControlledMedia (rig ``call``): after the listener's question another person ANSWERS it aloud (a number, a hedge, «по-моему»); this is the others' speech: no public search, no new plan, no cue that is not
a portion of the plan the listener already has, the cursor where it stood. The accounting itself («next time shorter») is not built and is not asserted: see the report (отказ: условно, ждёт D-4).
Not run on the laptop.
"""
import pytest

from kind_a_kit import LIVE_RULES, TICK, let_jobs_decline, mark, only_the_plan_sounds, plan, said_to_the_room, spoken_failures
from test_h3_tempo import call      # noqa: F401 - the fixture

ASKED = 'В каком году основали Петербург'
ANSWER = 'Петербург основан в тысяча семьсот третьем году. Основал его Пётр Первый.'
OTHERS = ['В тысяча семьсот третьем, по-моему, Пётр основал.', 'Да нет, в семьсот двенадцатом столицу перенесли, а основали раньше.', 'Ну мы в школе учили, что при Петре, я не помню.']


@pytest.mark.parametrize('said', OTHERS, ids=['hedged_answer', 'a_disputing_answer', 'a_vague_memory'])
def test_somebody_elses_answer_to_the_question_keeps_the_prompter_quiet_and_off_the_search(call, said):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ASKED, answer=ANSWER)
    before = mark(rig)
    said_to_the_room(rig, 'o1', said)
    rig.pump(TICK)
    let_jobs_decline(rig, before['runs'])
    rig.pump(6.0)
    assert not spoken_failures(rig)
    assert only_the_plan_sounds(rig, before) == [], only_the_plan_sounds(rig, before)
    assert mark(rig)['lookups'] == before['lookups'], 'the others\' answer went to the public search'
    after = rig.w.snapshot()
    assert (after['revision'], after['index']) == (before['revision'], before['index'])

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
