"""fac-neighbors: the neighbour check ran all neighbour files in ONE pytest. Live 19.11 20:04 (fac-self trial 6): six
neighbours did not fit the 30 s limit, the whole check counted as skipped, and five broken tests of a fast neighbour
file passed the gate. Each neighbour file is measured in its own run: a slow one is skipped alone, the rest count."""
from pathlib import Path

from tools import factory_gate as G
from test_factory_runtime import Rig, _kilo_engine, gr  # noqa: <id>  (_kilo_engine: autouse, the rig fakes Kilo)


def test_a_slow_neighbour_does_not_hide_a_fast_one_that_breaks(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(rig.w, 'neighbor_tests', lambda root, task: ['tests/test_slow.py', 'tests/test_fast.py'])
    for name in ('tests/test_slow.py', 'tests/test_fast.py'):
        (rig.root / name).write_text('def test_n(): pass\n')

    def run(root, tests, timeout_s):
        fixed = 'a+b' in (Path(root) / 'calc.py').read_text()
        if 'tests/test_slow.py' in tests:          # a pytest that includes the slow file never ends in 30 s
            return G.GateResult(-1, 0, 0, 0, 0, 0, False, 'timeout after 30s (process tree killed)')
        if 'tests/test_fast.py' in tests:
            return gr(not fixed, diag='neighbour broke')
        return gr(fixed, diag='task test')
    rig.run_tests_fn = run
    result = rig.once()
    assert result['status'] == 'READY' and 'neighbo' in result['reason']
