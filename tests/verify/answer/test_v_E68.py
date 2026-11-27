"""V3 E68: R7: the refusal «—» of the job on the route of the sources / without a source does not lose the question silently: something is heard (the model's other answer, or the honest phrase) by the bound.
R6 (the answer of the base without the rule of the end of an utterance) is not here: the backlog says «сначала решение, какое правило сильнее»: that is a decision of the family K/A, not a test to write blind.

Real ControlledMedia and wire (rig of test_h1_fast_text). Red = a card for A. Not run on the laptop."""
import helpers_s6_state as S
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS
from test_h1_fast_text import VERIFY, rig      # noqa: F401 - rig is the fixture


def test_a_dash_on_the_route_of_sources_is_not_a_lost_question(rig):
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', VERIFY))
    rig.pump()
    assert rig.w.lookup_calls, 'precondition: the route of sources'
    rig.say(0, '—')
    rig.fake.run(0).finish()
    rig.pump(ANSWER_WAIT_SECONDS + 2.0)
    assert rig.w.cues, 'R7: the question was lost without a sound'


def test_a_dash_without_a_source_is_not_a_lost_question(rig, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', VERIFY))
    rig.pump()
    rig.say(0, '—')
    rig.fake.run(0).finish()
    rig.pump(ANSWER_WAIT_SECONDS + 2.0)
    assert rig.w.cues, 'R7: the question was lost without a sound'
