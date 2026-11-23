"""Live 20.11 07:20: a pass of a task with slow scene tests took 1000 s and ended 'junit not ok: ... (+9 more): timeout
after 30s: the split budget was spent, not run'. Ten tests of the task never ran on the candidate, nothing that ran was
red, and the pass still counted it as a failed candidate and asked two more models, each spending the gate budget
again; since midnight three such tasks took 1.4 h of the loop's 4.8 h of passes. A test the budget left unrun is recorded apart
(``unrun``); a candidate whose only shortfall is such tests (no red that ran, every other cut test cut on the base too)
is undecided here: the pass releases the task without a strike and without another model, and the third such pass in
a row blocks it for a gate with more time. A test the candidate makes hang alone, while it ran on the base, is still
the candidate's failure."""
from tools import factory_gate as fg

SPENT = fg._failure(-1, fg.SPENT_DIAG % 30)
CUT = fg._failure(-1, fg.TIMEOUT_DIAG % 30)


def _green(n=1):
    return fg.GateResult(0, n, n, 0, 0, 0, True, '')


def _red(*ids):
    return fg.GateResult(1, len(ids), 0, len(ids), 0, 0, True, 'failure', failed_ids=tuple(ids))


def test_tests_the_budget_left_unrun_are_recorded_apart_from_a_test_cut_alone():
    merged = fg._merge([(('a::t1',), _green()), (('a::t2', 'a::t3'), SPENT), (('a::t4',), CUT)])
    assert merged.unrun == ('a::t2', 'a::t3')
    assert merged.timed_out == ('a::t2', 'a::t3', 'a::t4') and not merged.junit_ok


def test_a_candidate_short_only_of_unrun_tests_is_undecided():
    base = fg._merge([(('a::t1',), _red('a::t1')), (('a::t2',), _green())])
    cand = fg._merge([(('a::t1',), _green()), (('a::t2', 'a::t3'), SPENT)])
    assert not fg.accept(base, cand, True)[0]
    assert fg.undecided(base, cand)


def test_a_red_that_ran_decides_even_with_unrun_tests():
    base = fg._merge([(('a::t1',), _red('a::t1')), (('a::t2',), _green())])
    cand = fg._merge([(('a::t1',), _red('a::t1')), (('a::t2',), SPENT)])
    assert not fg.undecided(base, cand)


def test_a_test_the_candidate_makes_hang_while_it_ran_on_the_base_is_the_candidates_failure():
    base = fg._merge([(('a::t1',), _red('a::t1')), (('a::t2',), _green())])
    cand = fg._merge([(('a::t1',), _green()), (('a::t2',), CUT), (('a::t3',), SPENT)])
    assert not fg.undecided(base, cand)
    hung_on_base = fg._merge([(('a::t1',), _red('a::t1')), (('a::t2',), CUT)])
    assert fg.undecided(hung_on_base, cand)


def test_an_undecided_candidate_releases_the_task_without_a_strike_and_without_another_model(tmp_path, monkeypatch):
    import json
    from tests.test_factory_runtime import FIX_BLOCK, Rig
    rig = Rig(tmp_path, monkeypatch)
    test_id = 'tests/test_calc.py::test_add'
    runs = []

    def run(root, tests, timeout_s):
        runs.append(1)
        return fg._merge([((test_id,), _red(test_id))]) if len(runs) == 1 else fg._merge([((test_id,), SPENT)])
    rig.run_tests_fn = run
    sent = []

    def post(url, key, body, timeout):
        review = body['messages'][0]['content'] == rig.w.LIGHT_REVIEW_RULES
        sent.append('review' if review else 'coder')
        content = '{"approved": true, "reasons": []}' if review else FIX_BLOCK
        return 200, json.dumps(dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                                    usage=dict(prompt_tokens=900, completion_tokens=40))).encode()
    monkeypatch.setattr(rig.w, 'engine_for', lambda role, task: 'light')
    monkeypatch.setattr(rig.w, '_light_post', post)
    result = rig.once()
    assert result['status'] == 'READY' and result['reason'] == 'gate_unknown', result
    assert sent == ['coder']                         # no second model, no critic: the gate could not judge it here
    assert 'not run' in result.get('reason_detail', '')
    feedback = rig.state()['tasks']['T1'].get('feedback') or []
    assert not any('[attempt' in f.get('text', '') for f in feedback)        # no strike, no rejection note


def test_a_run_without_unrun_tests_is_never_undecided():
    base = fg._merge([(('a::t1',), _red('a::t1')), (('a::t2',), _green())])
    assert not fg.undecided(base, fg._merge([(('a::t1',), _green()), (('a::t2',), _green())]))
    assert not fg.undecided(base, fg._merge([(('a::t1',), _green()), (('a::t2',), CUT)]))
