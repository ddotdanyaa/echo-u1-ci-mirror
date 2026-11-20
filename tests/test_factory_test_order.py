"""Gate test order (fast before heavy, last red first) and the duration-balanced cloud shards."""
import json

from tools import agent_factory_runner as W
from tools import factory_gate as G
from tools import factory_mirror as fm


def _res(failed=0, errors=0, passed=1, env='', env_failed=(), ids=()):
    return G.GateResult(1 if failed or errors else 0, passed + failed + errors, passed, failed, errors, 0, True,
                        'diag', env, (), tuple(ids), (), (), tuple(env_failed))


def _tree(tmp_path, sizes, secs=None):
    (tmp_path / 'tests' / 'data').mkdir(parents=True)
    for name, n in sizes.items():
        (tmp_path / 'tests' / name).write_text('x' * n)
    if secs is not None:
        (tmp_path / W.DURATIONS_FILE).write_text(json.dumps(secs))
    return tmp_path


# ---------------------------------------------------------------------------------------------- order in the runner
def test_order_is_fast_before_heavy_by_size_without_a_record(tmp_path):
    root = _tree(tmp_path, {'test_big.py': 900, 'test_mid.py': 300, 'test_small.py': 10})
    names = ['tests/test_big.py', 'tests/test_mid.py', 'tests/test_small.py']
    assert W.gate_order(root, names) == ['tests/test_small.py', 'tests/test_mid.py', 'tests/test_big.py']


def test_order_uses_the_recorded_duration_before_the_size(tmp_path):
    root = _tree(tmp_path, {'test_big.py': 900, 'test_small.py': 10}, {'tests/test_big.py': 0.5, 'tests/test_small.py': 40.0})
    assert W.gate_order(root, ['tests/test_small.py', 'tests/test_big.py']) == ['tests/test_big.py', 'tests/test_small.py']


def test_an_unrecorded_file_is_estimated_on_the_scale_of_the_recorded_ones(tmp_path):
    root = _tree(tmp_path, {'test_a.py': 100, 'test_b.py': 100, 'test_new.py': 1000},
                 {'tests/test_a.py': 1.0, 'tests/test_b.py': 50.0})
    # the median record is 50 s per 100 bytes: the unknown 1000-byte file is the heaviest
    assert W.gate_order(root, ['tests/test_new.py', 'tests/test_b.py', 'tests/test_a.py'])[0] == 'tests/test_a.py'
    assert W.gate_order(root, ['tests/test_new.py', 'tests/test_b.py', 'tests/test_a.py'])[-1] == 'tests/test_new.py'


def test_what_failed_last_time_goes_first_and_nothing_is_lost(tmp_path):
    root = _tree(tmp_path, {'test_big.py': 900, 'test_small.py': 10}, {'bad': 'json-shape', 'tests/test_small.py': -1})
    names = ['tests/test_small.py', 'tests/test_big.py', 'tests/test_small.py']
    assert W.gate_order(root, names, ['tests/test_big.py']) == ['tests/test_big.py', 'tests/test_small.py']
    (root / W.DURATIONS_FILE).write_text('not json')
    assert W.gate_order(root, ['tests/test_big.py']) == ['tests/test_big.py']


def test_red_entries_maps_gate_ids_to_the_task_files():
    tests = ['tests/test_a.py', 'tests/test_b.py::test_one', 'tests/test_c.py']
    ids = ['tests.test_b.TestX::test_one', 'tests.test_c::test_two', 'other.thing::x']
    assert W.red_entries(ids, tests) == ['tests/test_b.py::test_one', 'tests/test_c.py']
    assert W.red_entries([], tests) == []


def test_a_rerun_runs_only_the_failed_file_and_stops_while_it_is_red(tmp_path):
    root = _tree(tmp_path, {'test_a.py': 10, 'test_b.py': 20})
    calls = []

    def run(part):
        calls.append(list(part))
        return _res(failed=1, ids=['tests.test_b::test_x'])
    got = W.staged_run(run, root, ['tests/test_a.py', 'tests/test_b.py'], ['tests/test_b.py'])
    assert calls == [['tests/test_b.py']] and got.failed == 1                # the rest never ran


def test_a_rerun_runs_the_rest_only_after_the_failed_file_passes_and_merges_the_counts(tmp_path):
    root = _tree(tmp_path, {'test_a.py': 10, 'test_b.py': 20})
    calls = []

    def run(part):
        calls.append(list(part))
        return _res(passed=2 if part == ['tests/test_b.py'] else 3)
    got = W.staged_run(run, root, ['tests/test_a.py', 'tests/test_b.py'], ['tests/test_b.py'])
    assert calls == [['tests/test_b.py'], ['tests/test_a.py']] and got.passed == 5 and got.collected == 5


def test_without_a_previous_red_there_is_one_run_in_fast_first_order(tmp_path):
    root = _tree(tmp_path, {'test_a.py': 500, 'test_b.py': 20})
    calls = []
    W.staged_run(lambda part: calls.append(list(part)) or _res(), root, ['tests/test_a.py', 'tests/test_b.py'])
    assert calls == [['tests/test_b.py', 'tests/test_a.py']]


def test_an_environment_failure_of_the_first_stage_is_the_answer(tmp_path):
    root = _tree(tmp_path, {'test_a.py': 10, 'test_b.py': 20})
    calls = []
    got = W.staged_run(lambda part: calls.append(list(part)) or _res(failed=1, env='no slot'), root,
                       ['tests/test_a.py', 'tests/test_b.py'], ['tests/test_b.py'])
    assert len(calls) == 1 and got.env_reason == 'no slot'


def test_the_runner_gate_uses_the_ordering_for_the_candidate_and_the_neighbours():
    text = (W.Path(W.__file__)).read_text(encoding='utf-8')
    assert 'staged_run(' in text and 'gate_order(root, neighbor_tests(' in text and "ctx.setdefault('neighbour_red'" in text


# ---------------------------------------------------------------------------------------------- shards in the mirror
def _spread(parts, dur):
    loads = [sum(dur[t] for t in p) for p in parts]
    return max(loads) / (sum(loads) / len(loads))


def test_without_durations_the_split_is_the_old_alphabetical_one():
    tests = ['tests/test_factory_%d.py' % i for i in range(10)]
    assert fm.shards(tests) == fm.shards(tests, durations={}) == fm.shards(tests, durations={'tests/other.py': 3.0})
    assert fm.shards(tests)[0] == sorted(tests)[:4] and len(fm.shards(tests)) == 3


def test_durations_balance_the_shards_within_one_and_a_half_of_the_mean():
    # the live skew: one 43 s file next to many sub-second ones (alphabetical chunks of four gave 3.9x the mean)
    dur = {'tests/test_factory_a%02d.py' % i: 0.3 for i in range(8)}
    dur.update({'tests/test_factory_b0.py': 43.0, 'tests/test_factory_b1.py': 25.0, 'tests/test_factory_b2.py': 22.0,
                'tests/test_factory_b3.py': 13.0, 'tests/test_factory_b4.py': 10.0, 'tests/test_factory_b5.py': 7.0,
                'tests/test_factory_b6.py': 6.0, 'tests/test_factory_b7.py': 5.0})
    tests = sorted(dur)
    old = fm.shards(tests)
    new = fm.shards(tests, durations=dur)
    assert _spread(old, dur) > 1.5 and _spread(new, dur) <= 1.5
    assert len(new) == len(old) and sorted(t for p in new for t in p) == tests


def test_an_unmeasured_file_counts_as_the_median_and_still_lands_in_a_shard():
    dur = {'tests/test_factory_a.py': 5.0, 'tests/test_factory_b.py': 1.0, 'tests/test_factory_c.py': 3.0}
    tests = sorted(dur) + ['tests/test_factory_new.py', 'tests/conftest.py']
    got = fm.shards(tests, size=2, durations=dur)
    assert sorted(t for p in got for t in p) == sorted(dur) + ['tests/test_factory_new.py']


def test_the_workflow_balances_on_the_durations_and_uploads_each_shard_junit():
    dur = {'tests/test_factory_a.py': 40.0, 'tests/test_factory_b.py': 1.0, 'tests/test_factory_c.py': 1.0,
           'tests/test_factory_d.py': 1.0, 'tests/test_factory_e.py': 1.0}
    text = fm.render_workflow(sorted(dur), durations=dur)
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith('files:')]
    assert "files: 'tests/test_factory_a.py'" in lines                       # the 40 s file runs alone
    assert '--junitxml=junit-${{ matrix.shard }}.xml' in text and 'shard-junit-${{ matrix.shard }}' in text
    assert not fm.scan_workflow(text, fm.WORKFLOW_PATH)


def test_durations_come_from_junit_files_and_a_bad_table_is_ignored():
    xml = ('<testsuites><testsuite><testcase classname="tests.test_factory_x.TestA" name="a" time="1.5"/>'
           '<testcase classname="tests.test_factory_x" name="b" time="0.5"/>'
           '<testcase classname="tests.test_factory_y" name="c" time="2"/></testsuite></testsuites>')
    got = fm.durations_from_junit([xml, 'not xml'], {'tests/test_factory_old.py': 9.0, 'tests/test_factory_y.py': 99.0})
    assert got == {'tests/test_factory_old.py': 9.0, 'tests/test_factory_x.py': 2.0, 'tests/test_factory_y.py': 2.0}
    assert fm.load_durations('[1]') == {} and fm.load_durations('{') == {} and fm.load_durations('') == {}
    assert fm.load_durations('{"a": 1, "b": "x", "c": -1, "d": true}') == {'a': 1.0}
