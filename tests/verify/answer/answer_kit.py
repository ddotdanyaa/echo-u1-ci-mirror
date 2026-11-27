"""V3 kit: what the verify tests of the family «answer» share. Nothing here decides anything: the tests drive the REAL ControlledMedia through the REAL NativeMediaSocket of ``tests/helpers_s6_state.World``
(rig ``call`` of test_h3_tempo: the ear, the job's stream and the cloud's events are scripted; the controller and the wire are the product's) or the rig ``rig`` of test_h1_fast_text (the lookup route is open there).
The clock is the world's: no number here is a measurement of a call, a laptop or a phone."""
import helpers_s6_state as S
from echo_sync.textutil import normalize
from test_h3_tempo import GRID, TICK, call                                                  # noqa: F401 - call is the fixture
from test_h5_live import (BAPTISM, LIVE, NO_NUMBER, RIGHT, WRONG_YEAR, asked, cloud, fails, plan, spoken_failures)   # noqa: F401
from test_h7 import CALL_1027, WIDE, job_answers, journal, lines, partial                   # noqa: F401


def heard_all(rig):
    """Every cue that reached the earpiece, a spoken diagnostic too (``rig.said()`` has the portions only)."""
    return [c for c in rig.w.cues]


def texts(rig):
    return [c.text for c in rig.cues()]


def bare(rig, word):
    """The cues that are only ``word`` (a bare «Да.»)."""
    return [t for t in texts(rig) if normalize(t) == normalize(word)]


def fail_open_jobs(rig, since=0, rounds=6):
    """Every job begun after ``since`` that is still open fails: the model's channel breaks on each ask (a retry is followed ``rounds`` times, never for ever)."""
    for _ in range(rounds):
        todo = [n for n in range(since, len(rig.fake.runs)) if not rig.fake.runs[n].ended.is_set()]
        if not todo:
            return
        for n in todo:
            fails(rig, n)


def say_question(rig, text, uid='u1'):
    rig.w.feed(S.turn_created(uid, 'user', text.split()[0]))
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK)
