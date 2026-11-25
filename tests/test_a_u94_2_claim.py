"""U94.2 on the call (goes to ``tests/`` WITH the two patches of this folder: the engine hands the generator the claim, ``ControlledMedia._generate`` compares the bound answer with it).

The real ControlledMedia, the real EchoEngine and the real NativeMediaSocket (rig ``call`` of test_h3_tempo, the profile of the working call): the question is asked, the cloud answers. The engine's generator is wrapped to
read what it is called with; the wrapper changes nothing, except in the last test, where it changes the CLAIM (as if the engine claimed another turn): the answer bound to the first turn must not be spoken for it.
Red before the patches (the request carries no claim; the other-claim test then speaks the answer), green after. Not run on the laptop."""
import pytest

from test_h3_tempo import TICK, call      # noqa: F401 - call is the fixture
from test_h5_live import LIVE, ACCOUNT, MATERIALS, asked, cloud


def spy(rig, change=None):
    """Wrap the generator the engine was built with; ``seen`` lists the request of each call, ``change`` (if any) may alter the claim."""
    engine = rig.c.engine
    original = engine.generate
    seen = []

    def generate(question, history, context, request, model):
        seen.append(request)
        if change is not None:
            request = change(request)
        return original(question, history, context, request, model)
    engine.generate = generate
    return seen


def test_the_engine_hands_the_generator_the_turn_and_the_revision_it_claimed(call):
    rig = call(**LIVE)
    seen = spy(rig)
    asked(rig, ACCOUNT)
    cloud(rig, 'a1', MATERIALS)
    rig.pump(TICK * 2)
    claims = [request.get('claim') for request in seen]
    assert claims and all(claim and claim['turn'] and isinstance(claim['revision'], int) for claim in claims), claims
    assert rig.said(), 'the answer of the question was spoken'


def test_an_answer_is_not_spoken_for_a_claim_of_another_turn(call):
    rig = call(**LIVE)
    seen = spy(rig, change=lambda request: {**request, 'claim': {**request['claim'], 'turn': 'another'}})
    asked(rig, ACCOUNT)
    cloud(rig, 'a1', MATERIALS)
    rig.pump(TICK * 2)
    assert seen, 'precondition: the engine asked the generator'
    assert rig.said() == [], 'U94.2: the answer bound to one turn was spoken for the claim of another'
