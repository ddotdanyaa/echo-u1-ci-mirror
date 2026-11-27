"""<id> (owner: «пробовал и так, и так, оставлял лучшее»; A/B built into the conveyor for good). An
experiment has arms (e.g. tournament size 1 or 3); every task gets one arm by a stable hash, so a task always gets the
same arm; outcomes are counted per arm from the telemetry; the better arm is decided only with enough cases and a
clear margin, and the decision goes to the growth journal with its numbers."""
import json

from tools import factory_ab as A


def test_a_task_always_gets_the_same_arm_and_both_arms_are_used():
    arms = ('1', '3')
    seen = {A.assign('T%d' % i, 'tournament_size', arms) for i in range(40)}
    assert seen == {'1', '3'}
    assert all(A.assign('T7', 'tournament_size', arms) == A.assign('T7', 'tournament_size', arms) for _ in range(3))
    assert A.assign('T7', 'other_experiment', arms) in arms


def _run(task, arm, status):
    return {'span': 'loop', 'action': 'RUN', 'task_id': task, 'status': status,
            'experiments': {'tournament_size': arm}}


def test_outcomes_count_passes_and_successes_per_arm():
    rows = [_run('T1', '1', 'FAILED'), _run('T2a', '1', 'REVIEW'), _run('T3', '3', 'REVIEW'),
            _run('T4', '3', 'REVIEW'), {'span': 'loop', 'action': 'HOLD'}, _run('T5', '3', 'READY')]
    assert A.outcomes(rows, 'tournament_size') == {'1': {'n': 2, 'ok': 1, 's': 0.0}, '3': {'n': 3, 'ok': 2, 's': 0.0}}


def test_outcomes_sum_the_run_time_of_each_arm():
    rows = [dict(_run('T1', '1', 'REVIEW'), dur_s=100.5), dict(_run('T2a', '1', 'FAILED'), dur_s=50),
            dict(_run('T3', '3', 'REVIEW'), dur_s=True), dict(_run('T4', '3', 'READY'), dur_s='9')]
    assert A.outcomes(rows, 'tournament_size') == {'1': {'n': 2, 'ok': 1, 's': 150.5}, '3': {'n': 2, 'ok': 1, 's': 0.0}}


def test_per_hour_the_arm_that_only_costs_time_loses():
    """20.11: the same passes per run, but one arm's runs take 2.5 times as long: per run no decision, per hour
    the faster arm wins."""
    slow, fast = {'n': 20, 'ok': 4, 's': 5000.0}, {'n': 20, 'ok': 4, 's': 2000.0}
    assert A.decide({'on': slow, 'off': fast}) is None
    decision = A.decide({'on': slow, 'off': fast}, margin=0.25, per_hour=True)
    assert decision == {'winner': 'off', 'rates': {'on': 2.88, 'off': 7.2}, 'n': {'on': 20, 'off': 20}}


def test_an_arm_that_takes_longer_and_wins_nothing_loses_without_many_passes():
    """Live 20.11: a small model as a later tournament candidate, 74 runs of 182 s against 96 of 64 s, 0 and 1 passes to
    a review: the per-hour rule wanted three passes of the winner, so the experiment never ended and the arm kept
    eating the loop's time (1.35 h)."""
    live = {'on': {'n': 74, 'ok': 0, 's': 13475.0}, 'off': {'n': 96, 'ok': 1, 's': 6115.0}}
    decision = A.decide(live, margin=0.25, per_hour=True)
    assert decision['winner'] == 'off' and decision['why'] == 'cheaper' and decision['n'] == {'on': 74, 'off': 96}
    assert A.decide({'on': {'n': 20, 'ok': 1, 's': 900.0}, 'off': {'n': 20, 'ok': 1, 's': 100.0}},
                    per_hour=True)['winner'] == 'off'                        # as many passes, a ninth of the time
    # not when the slow arm has won more, the difference in time is small, an arm has no time or too few runs
    assert A.decide({'on': {'n': 20, 'ok': 2, 's': 900.0}, 'off': {'n': 20, 'ok': 0, 's': 100.0}}, per_hour=True) is None
    assert A.decide({'on': {'n': 20, 'ok': 0, 's': 1400.0}, 'off': {'n': 20, 'ok': 0, 's': 1000.0}}, per_hour=True) is None
    assert A.decide({'on': {'n': 20, 'ok': 0, 's': 0.0}, 'off': {'n': 20, 'ok': 0, 's': 1000.0}}, per_hour=True) is None
    assert A.decide({'on': {'n': 5, 'ok': 0, 's': 900.0}, 'off': {'n': 20, 'ok': 0, 's': 100.0}}, per_hour=True) is None


def test_per_hour_needs_enough_passes_and_a_clear_factor():
    assert A.decide({'on': {'n': 20, 'ok': 2, 's': 900.0}, 'off': {'n': 20, 'ok': 0, 's': 100.0}},
                    per_hour=True) is None                                   # two passes are no evidence
    assert A.decide({'on': {'n': 20, 'ok': 5, 's': 1100.0}, 'off': {'n': 20, 'ok': 5, 's': 1000.0}},
                    margin=0.25, per_hour=True) is None                      # 10 % faster is no clear margin
    assert A.decide({'on': {'n': 20, 'ok': 0, 's': 0.0}, 'off': {'n': 20, 'ok': 0, 's': 0.0}}, per_hour=True) is None


def test_no_decision_without_enough_cases_or_margin():
    assert A.decide({'1': {'n': 5, 'ok': 1}, '3': {'n': 5, 'ok': 4}}, min_n=10) is None
    assert A.decide({'1': {'n': 20, 'ok': 10}, '3': {'n': 20, 'ok': 11}}, min_n=10, margin=0.15) is None


def test_a_clear_winner_is_decided_with_its_rates():
    decision = A.decide({'1': {'n': 20, 'ok': 6}, '3': {'n': 20, 'ok': 14}}, min_n=10, margin=0.15)
    assert decision == {'winner': '3', 'rates': {'1': 0.3, '3': 0.7}, 'n': {'1': 20, '3': 20}}


def test_the_decision_goes_to_the_growth_journal(tmp_path):
    path = tmp_path / 'growth.jsonl'
    A.record(path, 'tournament_size', {'winner': '3', 'rates': {'1': 0.3, '3': 0.7}, 'n': {'1': 20, '3': 20}},
             when='2026-11-20T03:00:00+03:00')
    A.record(path, 'review_chain', None, when='2026-11-20T03:05:00+03:00')
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert rows[0] == {'when': '2026-11-20T03:00:00+03:00', 'experiment': 'tournament_size', 'winner': '3',
                       'rates': {'1': 0.3, '3': 0.7}, 'n': {'1': 20, '3': 20}}
    assert rows[1] == {'when': '2026-11-20T03:05:00+03:00', 'experiment': 'review_chain', 'winner': None}
