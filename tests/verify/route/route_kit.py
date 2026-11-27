"""V6 kit: what the verify tests of the family «road to the model, host, ear» share. Nothing here decides anything: the tests drive the REAL ControlledMedia through the REAL NativeMediaSocket of
``tests/helpers_s6_state.World`` (rig ``call`` of test_h3_tempo: the ear, the job's stream and the cloud's events are scripted; the controller and the wire are the product's) or the real
``controlled_host.serve`` (``helpers_s6_fault.HostRig``). The clock is the world's: no number here is a measurement of a call, a laptop or a phone."""
import helpers_s6_state as S
from echo_sync.textutil import normalize
from test_h3_tempo import GRID, TICK, call                                                  # noqa: F401 - call is the fixture
from test_h5_live import BAPTISM, LIVE, RIGHT, asked, cloud, fails                          # noqa: F401


def texts(rig):
    """What reached the earpiece as speech of the answer (a spoken diagnostic is not here)."""
    return [c.text for c in rig.cues()]


def bare(rig, word):
    return [t for t in texts(rig) if normalize(t) == normalize(word)]


def open_jobs(rig):
    """The jobs of the call that have not ended."""
    return [n for n, run in enumerate(rig.fake.runs) if not run.ended.is_set()]


def answer_with_job(rig, question, answer, uid):
    """A question whose job answers: the job asked for after the ask is the last one begun; its text and its end."""
    before = len(rig.fake.runs)
    asked(rig, question, uid=uid)
    rig.pump(TICK * 2)
    assert len(rig.fake.runs) > before, f'no job was asked for {question!r}'
    n = len(rig.fake.runs) - 1
    rig.job_says(n, answer)
    rig.job_ends(n)
    rig.pump(TICK * 3)
    return n
