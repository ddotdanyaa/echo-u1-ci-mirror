"""G23 (Р051-Р100, candidate flags, minutes cap 3): each case is one ``old_answer`` episode of the board, replayed on the stand: no answer of an older
question begins after the system had a newer one (A2)."""
import pytest

FLAGS = dict(kv.split(':') for kv in ('fast_text:on,local_ear:act,instant:on,material_pick:on,'
                                      'spare_helper:on,warm_start:on,open_overlap:on').split(','))


def old_answers(name, seed):
    from tools.rehearsal import score, sim
    spec = sim.Spec(name)
    spec.minutes = min(spec.minutes, 3)
    _, eps = score.board(sim.play(spec, seed, flags=FLAGS))
    return [e for e in eps if e['kind'] == 'old_answer']


OPEN = {
    # c24-a1: ('Р057', 1) closed: one final says one utterance (``_said_after``): the question said after the older one stays unjudged, the old first cue waits for it
    # c24-a1: ('Р069', 1) closed: the late final of an utterance ended before the question the ear opened retires nothing (``_older_final``)
    # c23: ('Р084', 0) closed: the first cue waits for the ear's question said past the old final (``_said_past``, c22-break P01)
    ('Р087', 0): 'the cloud never gave the final of question 2 and the ear job was refused (rule=numbers): silence, then the old plan is replayed by the ear tempo',
    # c24-a1: ('Р100', 1) green: a turn with no known start of speech is no older turn for ``_overtaken``
}


@pytest.mark.parametrize('name,seed', [pytest.param(n, s, marks=pytest.mark.xfail(strict=True, reason='OPEN (g23 report): ' + OPEN[n, s])) if (n, s) in OPEN else (n, s)
                                       for n, s in [('Р057', 1), ('Р059', 0), ('Р063', 0), ('Р066', 1), ('Р069', 1), ('Р076', 1), ('Р084', 0), ('Р087', 0), ('Р094', 1), ('Р100', 1)]])
def test_no_old_answer_after_a_newer_question(name, seed):
    assert old_answers(name, seed) == []


def test_a_question_the_ear_heard_is_no_try_of_the_portion():
    """Р087 seed 0: the friend's question shares words with the open portion; it and the next stranger's remark were two «tries» and the cursor went on (``a_try_counts``)."""
    from tools.rehearsal import score, sim
    spec = sim.Spec('Р087')
    spec.minutes = min(spec.minutes, 3)
    out = sim.play(spec, 0, flags=FLAGS)
    assert not [m for _, m in out.ctl if 'reason=a_try_counts' in m and ' 18.' in m] and score.board(out)[0]['false_step'] == 0

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
