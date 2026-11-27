"""V3 U152: the base of laws (E91) reaches the sound of a REAL call: «Что говорит статья 19 Конституции» is answered by the article verbatim in portions, the first portion within 1 s of the end of the question.
The listener says each portion back, as in a call: the ear and the cloud's final confirm it and the next portion goes (a silence only says the same portion again, never the next one).
Real ControlledMedia and wire (rig ``call``); the base is the fake page base of ``helpers_law``; the cloud gives no answer, the job is never fed. Not run on the laptop."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import helpers_law as H                         # noqa: E402
import helpers_s6_state as S                    # noqa: E402
from answer_kit import TICK, call               # noqa: E402,F401
from echo_sync import law_base as lb            # noqa: E402
from echo_sync.textutil import normalize        # noqa: E402
from test_repeat_cases import utter             # noqa: E402

CASES = ('Что говорит статья 19 Конституции', 'Статья 20 Конституции', 'Что говорит статья 71 Трудового кодекса')


@pytest.fixture
def base():
    with tempfile.TemporaryDirectory() as folder:
        H.build(os.path.join(folder, 'law.sqlite'))
        lb.use(os.path.join(folder, 'law.sqlite'))
        yield
        lb.use(None)


@pytest.mark.parametrize('question', CASES)
def test_the_article_is_said_verbatim_in_portions_and_the_first_portion_is_quick(call, base, question):
    expected = lb.lookup(question, ())
    assert expected, 'precondition: the base knows the article'
    rig = call(fast_text='on')
    rig.w.feed(S.turn_created('u1', 'user', question.split()[0]))
    rig.w.feed(S.turn_done('u1', 'user', question))
    began = rig.w.clock.t
    rig.pump(1.0)
    first = rig.cues()
    assert first, 'no portion of the article within 1 s of the end of the question'
    assert first[0].text and normalize(expected).startswith(normalize(first[0].text)[:40]), (first[0].text, expected)
    assert first[0].t - began <= 1.0, 'the first portion came %.2f s after the question' % (first[0].t - began)
    for n in range(40):
        said = rig.cues()[-1].text
        utter(rig, said, speech=max(0.4, 0.35 * len(said.split())), turn='u%d' % (n + 10), final=said + '.')
        if rig.next_cue(2.5) is None:
            break
    parts = [c.text for c in rig.cues()]
    heard = normalize(' '.join(t for i, t in enumerate(parts) if not i or t != parts[i - 1]))      # the same portion said again on its own is no new text
    assert normalize(expected)[:200] in heard, (heard[:300], expected[:200])
    assert rig.w.clock.t - began >= 1.0


@pytest.mark.parametrize('question', CASES)
def test_precondition_the_base_alone_answers_the_article(base, question):
    assert lb.lookup(question, ())
