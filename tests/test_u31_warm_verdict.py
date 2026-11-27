"""U31: a step of the warm plan has a verdict (``alive``), a ``fallback`` and the ``phrase_key`` the call says when the part is dead in the end; the model source of the plan ('model_road') follows ``Roads.alive``."""
import pytest

from echo_sync import warm


# ---- U31: a warm step has a verdict, a fallback and a phrase ---------------------------------------------------------------------------------
def test_a_step_that_ran_and_left_a_dead_part_is_not_ok_and_names_the_phrase():
    done = warm.run_plan([warm.Step('model_road', lambda: None, alive=lambda: False, phrase_key='channel')])
    assert done[0]['ok'] is False and done[0]['reason'] == 'dead' and done[0]['alive'] is False and done[0]['phrase_key'] == 'channel'


def test_the_fallback_of_a_dead_step_runs_and_a_part_it_revives_is_alive():
    state = {'up': False}
    step = warm.Step('road', lambda: None, alive=lambda: state['up'], fallback=lambda: state.update(up=True), phrase_key='channel')
    done = warm.run_plan([step])[0]
    assert done['ok'] is True and done['alive'] is True and done['fallback'] == 'ok' and 'phrase_key' not in done


def test_a_failing_fallback_and_a_raising_check_end_in_the_phrase_and_nothing_raises():
    def boom():
        raise RuntimeError('x')
    done = warm.run_plan([warm.Step('a', lambda: None, alive=boom, fallback=boom, phrase_key='channel'), warm.Step('b', lambda: None)])
    assert done[0]['ok'] is False and done[0]['fallback'] == 'RuntimeError' and done[0]['phrase_key'] == 'channel'
    assert done[1] == {'name': 'b', 'ok': True, 'ms': done[1]['ms'], 'reason': None, 'over_budget': False}      # a step with no verdict keeps its record as it was


@pytest.mark.parametrize('alive', [True, False])
def test_the_model_road_step_follows_the_roads(alive):
    class Roads:
        def alive(self):
            return alive
    step = next(s for s in warm.default_steps('.', roads=lambda: Roads()) if s.name == 'model_road')
    done = warm.run_plan([step])[0]
    assert done['ok'] is alive and (done.get('phrase_key') == ('channel' if not alive else None))
    assert all(s.name != 'model_road' for s in warm.default_steps('.'))      # no roads given: the plan is as it was


def test_the_real_roads_of_the_process_are_asked_by_the_plan_of_the_server(monkeypatch):
    seen = []
    monkeypatch.setattr(warm, 'start_plan', lambda steps, **kw: seen.extend(s.name for s in steps))
    monkeypatch.setattr(warm.guard, 'start', lambda **kw: None)
    warm.start_server_warm('.', settings={'warm_start': 'on'})
    assert 'model_road' in seen
