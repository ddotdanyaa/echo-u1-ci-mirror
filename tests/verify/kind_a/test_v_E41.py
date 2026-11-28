"""V1a E41: how many remarks that are not the listener's reach the public search (``lookup_first 59`` without a close). The threshold of the backlog is 0.

On the real ControlledMedia and the real wire of ``test_h1_fast_text.rig`` (the lookup route is open there: the control row proves a question of the listener's own makes the search run). The strangers' rows say a thing to
a named person, to the room, and a verb of the search in the mouth of someone else («проверь»), each in the same words that make the control search. ``public_lookup_allowed`` is by the backlog blind to the addressee, so a red
row here is a P0 of privacy: a defect card for the family K (the judge decides before the search) and for A (the privacy gate), not a thing to soften.
Not run on the laptop: the verdict is the cloud's.
"""
import pytest

import helpers_s6_state as S
from test_h1_fast_text import rig      # noqa: F401 - rig is the fixture

OWN = 'Проверь, пожалуйста, что такое гидравлический удар.'
STRANGERS = [
    'Лена, проверь, пожалуйста, что такое гидравлический удар.',
    'Миша, ты не посмотришь, что такое гидравлический удар?',
    'Коллеги, кто-нибудь, проверьте, пожалуйста, что такое гидравлический удар.',
    'Да откуда я знаю, у Светы спроси, она недавно людей оформляла',
    'Слушай, а ты проверь, пожалуйста, сколько у нас сегодня отпускных, я не знаю.',
]


def said(rig, text, uid='u1'):
    rig.w.feed(S.turn_created(uid, 'user', text.split()[0]))
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(1.0)


def test_control_the_listeners_own_request_to_check_makes_the_search_run(rig):
    said(rig, OWN)
    assert rig.w.lookup_calls, 'the control: the lookup route is open in this rig'


@pytest.mark.parametrize('text', STRANGERS, ids=[f'stranger{n}' for n in range(len(STRANGERS))])
def test_a_remark_of_somebody_else_never_reaches_the_public_search(rig, text):
    said(rig, text)
    assert rig.w.lookup_calls == [], f'the search was asked for: {rig.w.lookup_calls}'


def test_the_count_over_a_talk_of_several_people_is_zero(rig):
    """The count of the backlog on a scene, not a phrase: five remarks of the others in a row, 0 public searches (the job declines what it is asked)."""
    for n, text in enumerate(STRANGERS):
        said(rig, text, uid=f'u{n}')
        for run in range(len(rig.fake.runs)):
            if not rig.fake.runs[run].ended.is_set():
                rig.fake.run(run).say('—')
                rig.fake.run(run).finish()
        rig.pump(1.0)
    assert len(rig.w.lookup_calls) == 0, rig.w.lookup_calls
