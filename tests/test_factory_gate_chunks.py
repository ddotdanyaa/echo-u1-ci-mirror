"""fac-gate-chunks (live 20.11 05:37-06:11): three tasks could never be accepted. Some of their test files do not
finish in 30 s under load (slow, not hung: one of them finished at 05:37 and not at 05:51), one test waits on a speech
process, and some tests fail on a package the gate's Python lacks. A pytest call is never longer than 30 s (owner rule), so a call cut at the limit goes on in smaller calls: a small progress plugin writes which tests were collected
and which one was running when the call was cut. That test runs alone (cut alone = it hangs here: timed out, not
measured); the others run in chunks of 60% of what the cut call finished, each in its own call. The continuation has a
budget (SPLIT_BUDGET_S); what is left when it is spent is not run (timed out). A candidate is judged on every test that
ran: tests cut on the base too, and tests red by the environment on both sides, are not measured on either side; any
other test cut, not run or red fails the candidate."""
from dataclasses import replace

from tools import factory_gate as fg

A, B = 'tests/test_a.py', 'tests/test_b.py'
CUT = fg.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout after 30s (process tree killed)')


def ids(path, n):
    return ['%s::t%d' % (path, i) for i in range(n)]


def _fake(monkeypatch, items, per_call=99, hang=(), red=()):
    """A fake pytest over ``items`` (collection order): a call runs its tests in order and is cut when it starts a test
    of ``hang`` or when it would start a test beyond ``per_call``; ``red`` tests fail. Every call is recorded."""
    calls = []

    def once(root, tests, timeout_s, workdir=None, wait_s=None, progress=None, deselect=()):
        chosen = [i for i in items if any(i == t or i.startswith(t + '::') for t in tests)
                  and not any(i == d or i.startswith(d + '::') for d in deselect)]
        calls.append(chosen)
        started = []
        for n, i in enumerate(chosen):
            started.append(i)
            if i in hang or n >= per_call:
                if progress is not None:
                    progress.update(items=list(chosen), started=list(started))
                return CUT
        bad = tuple(sorted(i for i in chosen if i in red))
        return fg.GateResult(1 if bad else 0, len(chosen), len(chosen) - len(bad), len(bad), 0, 0, True,
                             'failure ...' if bad else '', failed_ids=bad)
    monkeypatch.setattr(fg, '_run_once', once)
    return calls


def test_a_slow_file_is_measured_in_chunks_that_fit(monkeypatch, tmp_path):
    items = ids(A, 10)
    calls = _fake(monkeypatch, items, per_call=4)
    result = fg.run_tests(tmp_path, [A], 30)
    assert calls[0] == items                                   # one try: cut when the 5th test (t4) starts
    assert calls[1:] == [items[0:2], items[2:4], items[5:7], items[7:9], items[9:10], [items[4]]]
    assert (result.collected, result.passed, result.failed) == (10, 10, 0)
    assert result.junit_ok and not result.timed_out and not result.missing


def test_a_test_that_hangs_alone_is_timed_out_and_the_rest_is_measured(monkeypatch, tmp_path):
    items = ids(A, 6)
    calls = _fake(monkeypatch, items, hang={items[2]}, red={items[0]})
    result = fg.run_tests(tmp_path, [A], 30)
    assert calls[-1] == [items[2]]                             # the suspect last, alone
    assert result.timed_out == (items[2],) and items[2] in result.missing and not result.junit_ok
    assert (result.collected, result.passed, result.failed) == (5, 4, 1)
    monkeypatch.setattr(fg, 'run_tests', lambda *a, **k: result)
    assert fg.red_before(tmp_path, [A], 30)[0] == 'red'        # red where it ran; the hang is not a doubt about it


def test_the_continuation_stops_when_its_budget_is_spent(monkeypatch, tmp_path):
    items = ids(A, 10)
    calls = _fake(monkeypatch, items, per_call=4)
    result = fg.run_tests(tmp_path, [A], 30, budget_s=0)
    assert calls == [items]                                    # the first call always runs; nothing after it
    assert set(result.timed_out) == set(items) and not result.junit_ok
    assert 'budget' in result.diag
    monkeypatch.setattr(fg, 'run_tests', lambda *a, **k: result)
    assert fg.red_before(tmp_path, [A], 30)[0] == 'unknown'


def test_tests_that_hung_on_the_base_run_alone_and_are_left_out_of_their_file(monkeypatch, tmp_path):
    items = ids(A, 4) + ids(B, 2)
    calls = _fake(monkeypatch, items, hang={items[1]})
    result = fg.run_tests(tmp_path, [A, B], 30, hung=(items[1],))
    assert calls == [[items[0], items[2], items[3]], ids(B, 2), [items[1]]]   # no call is cut by the known hang first
    assert result.timed_out == (items[1],) and result.collected == 5


def test_a_whole_file_cut_on_the_base_starts_file_by_file(monkeypatch, tmp_path):
    items = ids(A, 3) + ids(B, 2)
    calls = _fake(monkeypatch, items)
    fg.run_tests(tmp_path, [A, B], 30, hung=(A,))
    assert calls == [ids(A, 3), ids(B, 2)]


def _base_with_hang():
    return fg.GateResult(-1, 5, 4, 1, 0, 0, False, 'x', missing=(A + '::t2',), failed_ids=(A + '::t0',),
                         timed_out=(A + '::t2',))


def test_a_candidate_is_judged_on_every_test_that_ran_when_only_the_base_hangs_are_left():
    cand = fg.GateResult(-1, 5, 5, 0, 0, 0, False, 'x', missing=(A + '::t2',), timed_out=(A + '::t2',))
    assert fg.accept(_base_with_hang(), cand, True) == (True, 'ok')
    file_level = fg.GateResult(-1, 4, 3, 1, 0, 0, False, 'x', missing=(A,), failed_ids=(B + '::t0',), timed_out=(A,))
    assert fg.accept(file_level, cand, True) == (True, 'ok')     # the base knew only the file: its test is inside it


def test_a_new_cut_or_a_call_without_a_result_fails_the_candidate():
    base = _base_with_hang()
    new_cut = fg.GateResult(-1, 4, 4, 0, 0, 0, False, 'x', missing=(A + '::t2', A + '::t3'),
                            timed_out=(A + '::t2', A + '::t3'))
    assert not fg.accept(base, new_cut, True)[0]
    no_result = fg.GateResult(-1, 4, 4, 0, 0, 0, False, 'x', missing=(A + '::t2', B + '::t0'),
                              timed_out=(A + '::t2',))
    ok, why = fg.accept(base, no_result, True)
    assert not ok and why.startswith('junit not ok')
    red = fg.GateResult(-1, 5, 4, 1, 0, 0, False, 'x', missing=(A + '::t2',), failed_ids=(A + '::t1',),
                        timed_out=(A + '::t2',))
    assert not fg.accept(base, red, True)[0]


def test_tests_red_by_the_environment_on_both_sides_are_not_measured_and_the_rest_decides():
    env = (B + '::t1', B + '::t2')
    base = fg.GateResult(1, 4, 1, 3, 0, 0, True, 'x', failed_ids=(A + '::t0',) + env, env_failed=env)
    cand = fg.GateResult(1, 4, 2, 2, 0, 0, True, 'x', failed_ids=env, env_failed=env)
    assert fg.accept(base, cand, True) == (True, 'ok') and fg.unmeasured(base, cand) == env
    broke = replace(cand, failed=3, failed_ids=env + (A + '::t3',), env_failed=env + (A + '::t3',))
    assert not fg.accept(base, broke, True)[0]          # the environment broke a test only on the candidate
    merits = replace(cand, env_failed=env[:1])
    assert not fg.accept(base, merits, True)[0]          # red on its merits on the candidate


def test_a_part_that_came_back_without_any_result_is_missing_in_the_merge():
    merged = fg._merge([((A + '::t0',), fg.GateResult(0, 1, 1, 0, 0, 0, True, '')),
                        ((A + '::t1', A + '::t2'), fg.GateResult(3, 0, 0, 0, 0, 0, False, 'no readable JUnit XML'))])
    assert set(merged.missing) == {A + '::t1', A + '::t2'} and not merged.timed_out and not merged.junit_ok


def test_a_real_cut_call_goes_on_by_tests_and_names_the_hanging_one(monkeypatch, tmp_path):
    """The real plugin through a real pytest: a 5 s limit, a test that sleeps 60 s, one red on its merits and one red
    by the environment (a package nobody has)."""
    monkeypatch.setattr(fg, 'SLOT_DIRS', [str(tmp_path / 'slot1'), str(tmp_path / 'slot2')])
    (tmp_path / 'src' / 'tests').mkdir(parents=True)
    (tmp_path / 'work').mkdir()
    body = ''.join('def test_%d():\n    assert %s\n' % (i, 'False' if i == 1 else 'True') for i in range(5))
    body += 'def test_env():\n    import factory_no_such_package_xyz\n'
    body += 'def test_sleeps():\n    import time\n    time.sleep(60)\n'
    body += 'def test_after():\n    assert True\n'
    (tmp_path / 'src' / 'tests' / 'test_x.py').write_text(body, encoding='utf-8')
    result = fg.run_tests(tmp_path / 'src', ['tests/test_x.py'], 5, workdir=tmp_path / 'work', budget_s=60)
    assert result.timed_out == ('tests/test_x.py::test_sleeps',), result
    assert (result.collected, result.passed, result.failed) == (7, 5, 2), result
    assert result.failed_ids == ('tests.test_x::test_1', 'tests.test_x::test_env')
    assert result.env_failed == ('tests.test_x::test_env',) and not result.env_reason
