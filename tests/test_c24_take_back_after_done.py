"""c24-b (rehearsals with the speed set, old answers): the late final of the listener's repeat of the answer just completed («12. Это 4 раз по 3.»)
took back the plan the new question had suspended («63. Это 9 раз по 7.»): the two share «Это … раз по …», and the check «a try at the answer that is
current» read nothing once that answer was over. Р102 seed 0 (old answer at 83.82), Р064 seed 0 (at 34.24)."""
import os

import pytest

CS = ('prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on,stop_in_flight=on,'
      'ear_job=on,turn_mark=on,cloud_form=on,ear_lookup=on')


@pytest.mark.parametrize('name, seed', [('Р102', 0), ('Р064', 0)])
def test_a_repeat_of_the_answer_just_over_never_takes_the_old_plan_back(monkeypatch, name, seed):
    monkeypatch.setenv('ECHO_REPLAY_FLAGS', CS)
    from tools.rehearsal import sim
    spec = sim.Spec(name)
    spec.minutes = min(spec.minutes, 6)
    out = sim.play(spec, seed, flags=dict(kv.split('=', 1) for kv in CS.split(',')))
    taken = [t for t, line in out.ctl if 'suspended_plan_taken_back' in line]
    old = [v for v in out.violations if v[0] == 'A2' and any(abs(v[1] - t) < 0.5 for t in taken)]
    assert old == [], old
