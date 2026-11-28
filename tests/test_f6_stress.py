"""F6: the heavy rehearsals Р101-Р104 (``tools/rehearsal/plan.py``). Each case is one episode of their board (default flags of the seed) replayed on the
stand: the product's error, not the stand's."""
import pytest


def episodes(name, seed, kind):
    from tools.rehearsal import score, sim
    _, eps = score.board(sim.play(sim.Spec(name), seed))
    return [e for e in eps if e['kind'] == kind]


@pytest.mark.parametrize('name,seed', [
    ('Р104', 4),    # «Нет, не 6, а 16.» over «24. Это 6 раз по 4.»: the ear heard a dispute of the figure, no final yet, the ear's tempo replayed the old answer
    ('Р104', 3),    # c23: was OPEN (the answer of q13 admitted at 100.5 s first sounded at 103.5 s, after the fix at 102.8 s): the first cue waits for speech said past the old final (``_said_past``, c22-break P01)
])
def test_no_old_answer_after_a_number_fix(name, seed):
    assert episodes(name, seed, 'old_answer') == []


@pytest.mark.parametrize('name,seed,kind', [
    ('Р104', 0, 'missed'),      # integ-c17: was OPEN (the fix «Нет, не 4, а 14.» admitted while the user spoke, its first cue never heard); passes with the wave's groups
    ('Р101', 2, 'missed'),      # was OPEN (job 1 timed out at the first-text bound of 4 s, its retry was cancelled by the user's chatter: the first question dropped with nobody asking it again); closed by the one road: no bound of 4 s, a slow job lives to the give-up and the question is the roads' until then
    pytest.param('Р103', 0, 'lost_place', marks=pytest.mark.xfail(strict=True, reason='OPEN (policy): the cloud\'s stable partial acked the exact repeat, the noisy ear\'s '
                                                                                      'number vetoed it after (local_ear_number_veto boundary=taken_back): the cursor goes back')),
])
def test_open_episodes_of_the_heavy_rehearsals(name, seed, kind):
    assert episodes(name, seed, kind) == []
