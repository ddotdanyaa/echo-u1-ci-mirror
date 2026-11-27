"""W14: the board of w13's head with the candidate's flags had 17 ``old_answer``. Each case here is one episode of that board (rehearsal, seed, the
minutes cap 3 of the board) replayed on the stand: no answer of an older question may begin after the system had a newer one (A2)."""
import pytest

FLAGS = dict(kv.split(':') for kv in ('fast_text:on,local_ear:act,prompt_tempo:ear,ear_release:on,two_witnesses:on,gate_text:on,ear_command_early:on,'
                                      'prepare_wide:on,material_pick:on,brain_short:on').split(','))


def old_answers(name, seed):
    from tools.rehearsal import score, sim
    spec = sim.Spec(name)
    spec.minutes = min(spec.minutes, 3)
    _, eps = score.board(sim.play(spec, seed, flags=FLAGS))
    return [e for e in eps if e['kind'] == 'old_answer']


@pytest.mark.parametrize('name,seed', [
    ('Р004', 0),      # c24-a1: green (was OPEN: the job on «себестоимость» answered the ear's admission of «рентабельность»)
    ('Р052', 2),    # ear heard the new question, the cloud's turn went another way (silent: no_final_the_ear_is_contradicted), the ear's tempo replayed the old plan
])
def test_no_old_answer_after_a_newer_question(name, seed):
    assert old_answers(name, seed) == []
