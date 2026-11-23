"""Shared pieces of tests/break/world. Test code only; nothing here decides what is correct.

Two stands, both through the REAL ControlledMedia:
- the dictation (helpers_s6_ack.Dictation: the controller as the host builds it, the clock and the provider events are the only fakes);
- the host (controlled_host.serve on a virtual loop, tests/helpers_always_answer.py via tests/break/answer_route/bk_common.py).
A red test here is a found defect: it is never loosened, never xfail.
"""
import helpers_s6_ack as H
from bps_common import SIDE_ANSWER, STORY, dictation, finish, silence, speaks, words_of     # noqa: F401  (the family «portion» kit, tests/break/portion_speech)

NEXT_AFTER = 'Дальше.'


def waiting(tmp_path, name='d', confirmed=1, **kwargs):
    """A dictation with ``confirmed`` portions already read back: the next one waits for the owner."""
    d = dictation(tmp_path, name=name, **kwargs)
    for _ in range(confirmed):
        d.say(d.current)
    assert d.current is not None and not d.completed, 'precondition: a portion waits'
    return d


def spoken_by_itself(d, seconds, step=2.0):
    """Silence of the room: what the controller says with nobody speaking."""
    return silence(d, seconds, step=step)
