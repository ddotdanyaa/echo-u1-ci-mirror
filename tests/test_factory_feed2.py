"""W-feed2: the token feed of the small tier and the start of cards. No network, no model."""
import json
import threading
import time
import types

from tools import factory_hypo as HY
from tools import factory_loop as L


def _pump(ask, **kw):
    return HY.Pump(ask, None, channels=('slow',), sleep=lambda s: time.sleep(0.001), **kw)


def test_a_busy_small_tier_does_not_stop_the_pump_while_the_minute_has_tokens():
    asked = []
    pump = _pump(lambda c, t, tmp: (asked.append(t) or ('ok', '', 1)), minute=HY.Minute(limit=1000))
    pump.submit([HY.Item((0, 0, 0), str(i), 'q%d' % i, 100, 0.2, 'x') for i in range(5)])
    assert pump.run(5) and len(asked) == 5


def test_a_spent_minute_makes_the_pump_wait():
    asked = []
    minute = HY.Minute(limit=1000)
    minute.charge('slow', 950)
    pump = _pump(lambda c, t, tmp: (asked.append(t) or ('ok', '', 1)), minute=minute)
    group = pump.submit([HY.Item((0, 0, 0), 'k', 'q', 100, 0.2, 'x')])
    assert pump.run(0.2, group) is False and asked == []


def test_four_requests_of_the_pump_run_at_once_on_a_channel():
    gate, running, peak, lock = threading.Event(), [0], [0], threading.Lock()

    def ask(chan, text, temp):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        gate.wait(5)
        with lock:
            running[0] -= 1
        return 'ok', '', 1
    pump = _pump(ask, minute=HY.Minute(limit=10 ** 6))
    group = pump.submit([HY.Item((0, 0, 0), str(i), 'q', 10, 0.2, 'x') for i in range(8)])
    runner = threading.Thread(target=pump.run, args=(10, group))
    runner.start()
    deadline = time.time() + 5
    while time.time() < deadline and peak[0] < HY.PER_CHANNEL:
        time.sleep(0.005)
    gate.set()
    runner.join(10)
    assert peak[0] == HY.PER_CHANNEL == 4


def test_the_minute_keeps_the_rpm_of_the_channel_and_a_charge_always_lands():
    minute = HY.Minute(limit=10 ** 6, rpms={'slow': 2}, limits={'fast-a': 100})
    assert minute.book('slow', 1) and minute.book('slow', 1) and not minute.book('slow', 1)
    assert not minute.book('fast-a', 101) and minute.book('fast-a', 100)
    minute.charge('fast-a', 5000)
    assert minute.used('fast-a') == 5100


def test_the_loop_minute_takes_tpm_rpm_from_channels_json_and_the_slicer_charges_it(tmp_path):
    path = tmp_path / 'channels.json'
    path.write_text(json.dumps({'channels': [
        {'id': 'k1-4b', 'name': 'a', 'model': 'gemma-3-4b', 'tier': 'small', 'tpm': 16000, 'rpm': 30, 'rpd': 100},
        {'id': 'k2-4b', 'name': 'a2', 'model': 'gemma-3-4b', 'tier': 'small', 'tpm': 16000, 'rpm': 30, 'rpd': 100},
        {'id': 'k1-27b', 'name': 'b', 'model': 'gemma-3-27b', 'tier': 'small', 'tpm': 15000, 'rpm': 20, 'rpd': 100}]}),
        encoding='utf-8')
    stub = types.SimpleNamespace(cfg=types.SimpleNamespace(channels=path), err=lambda *a: None, _hypo_lock=threading.RLock())
    stub._hypo_min = lambda: L.Loop._hypo_min(stub)
    stub._hypo_min_make = lambda HY_: L.Loop._hypo_min_make(stub, HY_)
    stub._hypo_channels = lambda: L.Loop._hypo_channels(stub)
    minute = L.Loop._hypo_min(stub)       # the windows are the REAL channels (model + key), not made-up names
    assert minute.limits == {'k1-4b': 16000, 'k2-4b': 16000, 'k1-27b': 15000} and minute.rpms['k1-27b'] == 20
    L.Loop._hypo_charge(stub, 'gemma-3-27b', 'x' * 300)
    assert minute.used('k1-27b') == HY.est_tokens('x' * 300) and minute.used('k1-4b') == 0
    L.Loop._hypo_charge(stub, 'gemma-3-4b', 'x' * 300)
    assert minute.used('k1-4b') + minute.used('k2-4b') == HY.est_tokens('x' * 300)


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
    assert L.Loop.HYPO_PARALLEL == 6


def test_the_slicer_no_longer_owns_the_search():
    import inspect
    assert '_hypo_row' not in inspect.getsource(L.Loop._slice)       # one owner: the feeder tick of the loop
    assert not hasattr(L.Loop, '_hypo_row') and not hasattr(HY.Pump(None, None), 'live')      # no second path, no dead yield flag


def _tree(tmp_path):
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / 'calc.py').write_text('def add(a, b):\n    return a - b\n', encoding='utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_calc.py').write_text(
        'from pkg.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n', encoding='utf-8')
    return tmp_path


def _env(root, failure=''):
    return HY.Ctx(root=root, ask=lambda c, t, tmp: ('ok', 'CANNOT', 0), cloud=lambda *a: {}, failure_text=lambda ids: failure,
                  stats=HY.Stats(), timeout_s=5.0, sleep=lambda s: time.sleep(0.001))


def test_none_status_says_why(tmp_path):
    root = _tree(tmp_path)
    assert HY.search('E1', [], _env(root))['why'] == 'no ids'
    (root / 'tests' / 'test_empty.py').write_text('def test_x():\n    assert 1\n', encoding='utf-8')
    out = HY.search('E1', ['tests/test_empty.py::test_x'], _env(root))
    assert out['status'] == 'none' and out['why'] == 'no failure'
    out = HY.search('E1', ['tests/test_empty.py::test_x'], _env(root, failure='E assert 0'))
    assert out['status'] == 'none' and out['why'] == 'no functions'


def test_the_functions_the_test_imports_are_the_last_resort(tmp_path):
    root = _tree(tmp_path)
    assert HY.test_functions(root, 'tests/test_calc.py::test_add') == [('pkg/calc.py', 'add')]
    out = HY.search('E1', ['tests/test_calc.py::test_add'], _env(root, failure='E assert -1 == 3'))
    assert out['status'] == 'red' and out['tried'] and out['tried'][0]['symbol'] == 'add'
