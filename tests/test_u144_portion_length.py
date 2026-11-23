"""U144 (M4): the rules of the portions by sense are always on (no ``portion_sense`` key): no portion the listener is given ends on a dash, and no portion
but the tail of an answer is two words or fewer. Through the real ControlledMedia on the h3 stand: the answer is cut by the engine, the first cue is said."""
import pytest

from test_h3_tempo import call  # noqa: F401 - the fixture
from u144_texts import ANSWERS

DASHES = ('—', '–', ' -')


def profile():
    return dict(fast_text='on', preset='meaning', max_words=9)


@pytest.mark.parametrize('answer', ANSWERS)
def test_no_portion_ends_on_a_dash_and_none_is_short_but_the_tail(call, answer):
    rig = call(**profile())
    rig.asks('u1', 'Расскажи подробнее', 0, answer)
    chunks = rig.c.state()['chunks']
    assert chunks, 'precondition: the answer is cut'
    for chunk in chunks:
        assert not chunk.rstrip().endswith(DASHES), f'a portion hangs on a dash: {chunk!r}'
    for chunk in chunks[:-1]:
        assert len(chunk.split()) > 2, f'a short portion before the tail: {chunk!r} in {chunks}'
    assert not rig.said()[0].rstrip().endswith(DASHES), f'the first cue said hangs on a dash: {rig.said()[0]!r}'
