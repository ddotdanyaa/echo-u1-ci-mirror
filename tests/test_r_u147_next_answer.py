"""U147 (the owner, 14.11: «при отказе одного звонок продолжает на другом»): the chaos stand (tools/replay/chaos.py, the real ControlledMedia chain with only its boundaries faked) throws ONE failure of the four kinds the owner named
into a chain of questions (the ear, the model, the search, the link of the cloud: the VPN), and the question that follows it is answered within ANSWER_NEXT_S of the moment the system had it. ``test_chaos`` bounds the same moment
by ``ANSWER_WAIT_SECONDS + 3.5`` s (it asks that an answer comes at all); the acceptance of U147 is the tighter number, 3 s, in 4 of 4 failures. The time is the stand's virtual clock, not a measurement on a laptop or a phone.
Written, not run on the laptop (cloud only): a cell that is red here is a finding of the road, not a reason to widen the number."""
import pytest

from tools.replay import chaos

ANSWER_NEXT_S = 3.0
FOUR = {'ear': 'ear_down', 'model_hang': 'model_hang', 'model_cut': 'model_cut', 'search': 'search_hang', 'link': 'cloud_flicker'}
LATE = []


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def measure(stand, out):
    """The first cue of the question after the fault: its delay after the moment the system had that question (the final of the cloud, or the ear's words, whichever came first as ``check_chaos`` knows it)."""
    found = {}
    cues = [c for c in out.cues if not c[6]]
    for i, u in enumerate(stand.asked):
        if i + 1 <= stand.at:
            continue
        t0 = u.final_at if u.final_at is not None else (u.ear_at if u.ear_at is not None else u.offset)
        nxt = stand.asked[i + 1].onset if i + 1 < len(stand.asked) else float('inf')
        heard = [c[0] for c in cues if u.onset <= c[0] < nxt and u.meaning[1].fits(' '.join(c[4]))]
        found[i + 1] = None if not heard else round(min(heard) - t0, 2)
    LATE.append((stand.fault, stand.at, found))


@pytest.fixture
def spy(monkeypatch):
    LATE.clear()
    real = chaos.check_chaos

    def watching(stand, out, lines):
        measure(stand, out)
        return real(stand, out, lines)
    monkeypatch.setattr(chaos, 'check_chaos', watching)
    return LATE


@pytest.mark.parametrize('name', sorted(FOUR))
@pytest.mark.parametrize('at', (2, 3))
def test_u147_after_one_failure_the_next_question_is_answered_within_three_seconds(spy, name, at):
    for seed in range(3):
        out = chaos.run(seed, FOUR[name], at)
        assert not [v for v in out.violations if v[0] in chaos.HARD], (name, seed, [v for v in out.violations if v[0] in chaos.HARD][:2])
        fault, step, found = spy[-1]
        assert fault == FOUR[name] and step == at
        nxt = found.get(at + 1)
        assert nxt is not None, f'{name} seed {seed}: the question after the failure got no answer of its own'
        assert nxt <= ANSWER_NEXT_S, f'{name} seed {seed}: the next question is answered {nxt} s after the system had it (more than {ANSWER_NEXT_S})'


def test_u147_the_control_without_a_failure_is_inside_the_same_bound(spy):
    """The bound is the stand's, not a loose one: with no fault the same question is answered inside it, so a red cell above is the failure's and not the stand's."""
    for seed in range(3):
        chaos.run(seed, 'none', 2)
        found = spy[-1][2]
        assert found.get(3) is not None and found[3] <= ANSWER_NEXT_S, (seed, found)


def test_u147_the_measure_fires_on_a_scene_built_to_break_it(spy, monkeypatch):
    """A model that never says a word to anything (as in test_chaos): the later questions get no answer, so the measure says None."""
    def mute(self, job, thread):
        self.runs[id(job.request)] = chaos.ST.Run(job, thread, self.now())
    monkeypatch.setattr(chaos.Chaos, '_born', mute)
    chaos.run(0, 'none', 2)
    assert spy[-1][2].get(3) is None
