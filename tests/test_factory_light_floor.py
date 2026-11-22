"""Admission floors of the loop: a light worker (one HTTP call, peak 40-120 MB) is admitted on a 3 GB machine, a Kilo
worker keeps the gate's 2 GB floor; the triage takes up to 12 tasks per pass."""
from types import SimpleNamespace

from tools import factory_gate as G
from tools import factory_loop as L

MB = 2 ** 20
LIGHT = {'touch_files': ['calc.py']}
KILO = {'touch_files': ['a.py', 'b.py', 'c.py', 'd.py', 'e.py', 'f.py']}      # over LIGHT_MAX_FILES (5)


def _loop(free, live=0, peaks=(), headroom=99):
    stub = SimpleNamespace(
        free_ram_fn=lambda: free,
        pool=SimpleNamespace(workers={i: SimpleNamespace(owned=None, tid='T%d' % i) for i in range(live)}),
        _ending=lambda: False, _brake_due=None, cfg=SimpleNamespace(once=False),
        ls=lambda: {}, _peaks=list(peaks), err=lambda *a: None,
        load=lambda: (None, {'tasks': {}}), _headroom=lambda task, state: headroom, _headroom_seen=None)
    stub._estimate = lambda: L.Loop._estimate(stub)
    stub._floor = L.Loop._floor
    return stub


def capacity(task, **kw):
    stub = _loop(**kw)
    return L.Loop._capacity(stub, task)


def test_the_light_floor_is_below_the_gate_floor_and_triage_takes_twelve():
    assert L.LIGHT_FLOOR == 768 * MB < G.MIN_FREE_RAM
    assert L.Config.triage_limit == 12


def test_a_light_worker_starts_with_one_and_a_half_gb_free_and_a_kilo_worker_does_not():
    assert capacity(LIGHT, free=1536 * MB) == ''
    assert capacity(KILO, free=1536 * MB) == 'low_ram'
    assert capacity(KILO, free=2100 * MB) == ''             # the old floor still admits Kilo above 2 GB


def test_below_the_light_floor_nothing_starts():
    assert capacity(LIGHT, free=700 * MB) == 'low_ram'


def test_light_workers_are_admitted_up_to_the_measured_estimate():
    peaks = [100 * MB] * 5                                   # measured: a worker needs about 100 MB
    free = 1536 * MB
    admitted = 0
    for live in range(1, 12):
        if capacity(LIGHT, free=free, live=live, peaks=peaks) == '':
            admitted = live
        else:
            break
    # the floor (768) plus one estimate (100) plus what the live workers have not used yet (100 each)
    assert admitted == 6
    assert capacity(LIGHT, free=free, live=7, peaks=peaks) == 'low_ram'


def test_with_the_unmeasured_default_estimate_one_and_a_half_gb_holds_two_light_workers():
    assert capacity(LIGHT, free=1536 * MB, live=1) == ''
    assert capacity(LIGHT, free=1536 * MB, live=2) == 'low_ram'


def test_a_kilo_second_worker_keeps_the_old_rule_and_an_unknown_task_the_light_floor():
    assert capacity(KILO, free=2400 * MB, live=1) == 'low_ram'          # 2400 - 300 < 2048 + 300
    assert capacity(None, free=1536 * MB) == ''
    assert capacity({'title': 'no files listed'}, free=1536 * MB) == 'low_ram'
