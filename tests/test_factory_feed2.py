"""W-feed2: the token feed of the small tier and the start of cards. No network, no model."""
import json
import threading
import time
import types

from tools import factory_hypo as HY
from tools import factory_loop as L


def _card(row):
    return types.SimpleNamespace(backlog_id=row, only_opus=False, privacy_safe=True)


def test_feeder_candidates_come_in_the_order_echo_rel_base_and_leave_out_the_busy():
    stub = types.SimpleNamespace(_hypers={'E2': object()}, _slicers={'E3': object()}, _hypo_skip={'E4': ('b', 0.0)}, base_sha='b',
                                 HYPO_RETRY_S=L.Loop.HYPO_RETRY_S)
    tasks = {'rel-base-1_r1': _card('rel-base-1'), 'rel-ab12-1_r1': _card('rel-ab12-1'), 'E5_r1': _card('E5'), 'rel-base-2_r1': _card('rel-base-2')}
    state = {'tasks': {'rel-base-1_r1': {'status': 'READY'}, 'rel-ab12-1_r1': {'status': 'READY'}, 'E5_r1': {'status': 'READY'},
                       'rel-base-2_r1': {'status': 'RUNNING'}}}
    guard = {'guard': 'tests/t.py::test_a', 'at': 0}
    ls = {'to_slice': {'E1': guard, 'E2': guard, 'E3': guard, 'E4': guard, 'E6': {'at': 0}, 'rel-base-2': {'at': 0}}, 'slice_wait': {'E1': 10 ** 9}}
    got = L.Loop._hypo_candidates(stub, tasks, state, ls, 5.0)
    # <id>: waiting row still searched; <id> under a search, <id> under a slicer, <id> nothing to search, <id> no red test,
    # rel-base-2 has a card running, <id> is a READY card without a guard: not a red row
    assert got == ['E1', 'rel-ab12-1', 'rel-base-1']


def test_the_slicer_no_longer_owns_the_search():
    import inspect
    assert '_hypo_row' not in inspect.getsource(L.Loop._slice)       # one owner: the feeder tick of the loop
    assert not hasattr(L.Loop, '_hypo_row')      # no second path


def _tree(tmp_path):
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / 'calc.py').write_text('def add(a, b):\n    return a - b\n', encoding='utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_calc.py').write_text(
        'from pkg.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n', encoding='utf-8')
    return tmp_path


def test_the_functions_the_test_imports_are_the_last_resort(tmp_path):
    root = _tree(tmp_path)
    assert HY.test_functions(root, 'tests/test_calc.py::test_add') == [('pkg/calc.py', 'add')]
    funcs = HY.rank_functions(root, ranked=HY.test_functions(root, 'tests/test_calc.py::test_add'))
    assert [(f['file'], f['symbol']) for f in funcs] == [('pkg/calc.py', 'add')]
