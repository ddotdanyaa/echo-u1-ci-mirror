"""W-mem2: a live worker is sized by its CURRENT working set, not by the job's lifetime peak."""
import time
from types import SimpleNamespace

import pytest

from tools import factory_loop as L
from tools import factory_process as P

MB = 2 ** 20


@pytest.fixture(autouse=True)
def _no_outside_bookings(monkeypatch):
    monkeypatch.setattr(L, '_reserved_bytes', lambda: 0)


def _worker(peak, current):
    owned = SimpleNamespace(peak_bytes=lambda: peak, current_bytes=lambda: current)
    return SimpleNamespace(owned=owned, tid='T', t_start=0.0)


def _loop(workers, peaks=(274 * MB,) * 5):
    stub = SimpleNamespace(pool=SimpleNamespace(workers=dict(enumerate(workers))), _peaks=list(peaks),
                           err=lambda *a: None)
    stub._estimate = lambda: L.Loop._estimate(stub)
    return stub


def test_the_median_follows_the_current_size_not_the_lifetime_peak():
    loop = _loop([_worker(260 * MB, 95 * MB) for _ in range(8)])
    med, burst, short = L.Loop._mem_plan(loop)
    assert med == 95 * MB and short == 0


def test_one_worker_without_a_measure_is_the_default_and_does_not_drag_the_median():
    loop = _loop([_worker(260 * MB, 95 * MB) for _ in range(3)] + [_worker(260 * MB, None)])
    assert L.Loop._mem_plan(loop)[0] == 95 * MB
    alone = _loop([_worker(260 * MB, None)])
    assert L.Loop._mem_plan(alone)[0] == L.EST_MEDIAN_DEFAULT


def test_the_burst_share_is_counted_above_the_median():
    est = 274 * MB
    loop = _loop([_worker(0, 80 * MB) for _ in range(20)])
    med, burst, _ = L.Loop._mem_plan(loop)
    assert burst == int(L.BURST_SHARE * 20 * (est - med)) and burst > est


def test_the_burst_never_falls_below_the_estimated_peak():
    loop = _loop([_worker(0, 80 * MB)])
    assert L.Loop._mem_plan(loop)[1] == 274 * MB


def test_a_posix_or_closed_job_has_no_current_size():
    assert P.Owned(SimpleNamespace(pid=1), job=None).current_bytes() is None
