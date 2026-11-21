"""Break kit of the family «question» (U237): the owner's way of breaking the call, played through the REAL ControlledMedia / NativeMediaSocket / ShadowEar / FastText of the rig ``call``.

The speech detector, the recognizer's worker, the cloud's events and the job's stream are scripted; the clock is the world's. Nothing here decides anything and no number is a measurement of a call.
A red test of this directory is a found defect: it is never loosened, never xfail.
"""
import os
import sys

_TESTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _path in (_TESTS, os.path.join(_TESTS, 'verify', 'question')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from question_kit import (ACCOUNT, AMORT, AMORT_ANSWER, LIVE_RULES, LONG_ANSWER, LONG_ASKED, MATERIALS, TICK, WIDE, answered, call, entry_of, heard, history, job_input, job_text,   # noqa: E402,F401
                          plan, rebuilt, user_turn, asked, cloud, fails, partial, job_answers, said_to_the_room, spoken_failures)
from test_h5_live import INTEREST, NOTICE, TASK, job_mark, piece              # noqa: E402,F401
from test_h6 import INERTIA                                                     # noqa: E402,F401
from test_h4_ear_first import slow                                              # noqa: E402,F401
import helpers_s6_state as S                                                    # noqa: E402,F401


def chunks_of(rig):
    return list(rig.c.state()['chunks'])


def index_of(rig):
    return rig.c.state()['chunk_index']


def declined_if_asked(rig, n):
    """A remark of a neighbour may open a job (the classifier takes the form) or not: when it did, the job says «—»."""
    if len(rig.fake.runs) > n:
        job_mark(rig, n, '—')
        rig.pump(TICK * 2)


def late(run, text, end=True):
    """What a job the host has already dropped may still push: put on its script, never waited for (a cancelled run does not acknowledge)."""
    run.script.put(('delta', text))
    if end:
        run.script.put(('end', None))
