"""W13 item 8 (1_#17, 3_#10): the ear's ACK of a repeat acted, and 2 s later the cloud's final of the same repeat opened a new question: the
portion sounded again. A text that says the portion just said is no question."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S
from test_h3_tempo import HEAD, PORTION, TICK, call       # noqa: F401 - call is the fixture
from test_h4_ear_first import speaks

REPEAT = 'статья семнадцать налогового кодекса'


@pytest.mark.parametrize('turn', ['u2', 'u3'], ids=['its_turn', 'another_turn'])
@pytest.mark.parametrize('said', ['Статья 17 Налогового кодекса.', 'Статья 17 Налогового кодекса?', 'Статья семнадцать Налогового кодекса'])
def test_the_clouds_final_of_the_repeat_the_ear_took_opens_nothing(call, turn, said, caplog):
    import logging
    caplog.set_level(logging.INFO, logger='echo-sync')
    rig = call(fast_text='on')
    rig.first_portion()
    rig.pump(1.0)
    speaks(rig, REPEAT, speech=1.5, turn='u2', announced=0.5)
    assert rig.said() == [HEAD, PORTION], 'precondition: the ear took the repeat'
    caplog.clear()
    rig.pump(0.8)      # within the tempo's wait: no replay of its own
    if turn != 'u2':
        rig.w.feed(S.turn_created(turn, 'user', ''))
    rig.w.feed(S.turn_done(turn, 'user', said))
    rig.pump(0.3)
    assert not [r.getMessage() for r in caplog.records if 'decision kind=question' in r.getMessage()]
    assert rig.said() == [HEAD, PORTION], rig.said()
    assert rig.c.question_id == 'u1'
