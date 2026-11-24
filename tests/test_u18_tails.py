"""U18: listening / recording mode, the replay of tails of speech (synthesized: no call journal here). While the owner talks by themselves (a long monologue not addressed to the system) or dictates
(writes the portions by hand, in their own tempo) the system gives no prompt that nobody asked for: false prompts = 0. The rig of ``test_h3_tempo`` on the injected clock, the ear scripted."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_h3_tempo import TICK, call      # noqa: E402,F401 - call is the fixture
from test_repeat_cases import ASK, P1, P2, P3, rig_of, utter      # noqa: E402,F401

MONOLOGUE = ['вчера мы с Колей ездили на дачу и там сломался насос',
             'пришлось звонить соседу чтобы он привёз ведро воды',
             'а потом выяснилось что дело вовсе не в насосе а в проводке',
             'так что в субботу придётся ехать туда снова с электриком',
             'и заодно забрать с чердака старые рамы которые обещали отдать',
             'в общем полдня потеряли зря но хотя бы погуляли по лесу']


def prompts_after_each(rig, texts, gap):
    """The owner speaks to nobody in particular: the portion that waits is not what they speak of. The cues the system said after each utterance (and its gap)."""
    out = []
    for text in texts:
        before = len(rig.cues())
        utter(rig, text, speech=3.0)
        rig.pump(gap)
        out.append(rig.said()[before:])
    return out


@pytest.mark.parametrize('gap', [1.0, 2.5, 4.0, 6.0, 9.0, 14.0])
def test_a_monologue_to_nobody_gets_no_prompt_once_it_is_one(call, gap):
    """One remark over a waiting portion is the portion's business (it may be said again after the quiet); the second utterance of other speech in a row is a monologue: false prompts from there = 0."""
    rig = rig_of(call, max_auto_repeats=3)
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    rig.pump(0.5)
    after = prompts_after_each(rig, MONOLOGUE, gap)
    assert [p for p in after[1:] if p] == [], after
