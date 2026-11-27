"""fac-58: the loop's own weight does not grow with the size of the journals, and a worker is booked at its measured
working set (not at the job's commit peak)."""
import json
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import factory_loop as L
from tools import factory_metrics as M
from tools import factory_router as RT

MB = 2 ** 20


def _journal(d: Path, rows=6000, pad=1500):
    d.mkdir(parents=True, exist_ok=True)
    with (d / "telemetry.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(rows):
            fh.write(json.dumps(dict(ts="2026-11-27T12:00:%02d+03:00" % (i % 60), span="run", task_id="T%d" % (i % 50),
                                     role="coder", model="m", status="ok", attempt=1, reason="r", pad="x" * pad)) + "\n")
    return d


def _peak_of(fn) -> int:
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_loop_telemetry_rows_streams(tmp_path):
    d = _journal(tmp_path)
    stub = SimpleNamespace(dir=d, tel_path=d / "telemetry.jsonl")

    def go():
        n = sum(1 for r in L.Loop._telemetry_rows(stub) if r.get("span") == "run")
        assert n == 6000
    assert _peak_of(go) < 4 * MB          # the file is ~10 MB; a whole read would cost several times that


def test_router_build_streams(tmp_path):
    d = _journal(tmp_path)
    assert _peak_of(lambda: RT.build(d, write=False)) < 4 * MB


def test_metrics_rows_stream(tmp_path):
    d = _journal(tmp_path)
    assert _peak_of(lambda: sum(1 for _ in M._rows(d))) < 4 * MB


def _stub(workers, peaks=(), ws=()):
    stub = SimpleNamespace(pool=SimpleNamespace(workers=dict(enumerate(workers))), _peaks=list(peaks), err=lambda *a: None)
    stub._estimate = lambda: L.Loop._estimate(stub)
    return stub


def test_mem_plan_remembers_the_working_set_peak_of_each_live_worker(monkeypatch):
    monkeypatch.setattr(L, "_reserved_bytes", lambda: 0)
    cur = [90 * MB]
    owned = SimpleNamespace(peak_bytes=lambda: 400 * MB, current_bytes=lambda: cur[0])
    w = SimpleNamespace(owned=owned, tid="T", t_start=0.0, ws_peak=0)
    stub = _stub([w])
    L.Loop._mem_plan(stub)
    cur[0] = 130 * MB
    L.Loop._mem_plan(stub)
    cur[0] = 60 * MB
    L.Loop._mem_plan(stub)
    assert w.ws_peak == 130 * MB


def test_a_finished_worker_enters_the_estimate_by_its_working_set_not_the_commit_peak():
    assert L.Loop._peak_for_estimate(SimpleNamespace(peak=400 * MB, ws_peak=130 * MB, ws_n=5)) == 130 * MB
    assert L.Loop._peak_for_estimate(SimpleNamespace(peak=400 * MB, ws_peak=0)) == 400 * MB      # no sample: the old way
    assert L.Loop._peak_for_estimate(SimpleNamespace(peak=None, ws_peak=0)) == 0


def test_a_thin_series_keeps_the_job_peak():
    thin = SimpleNamespace(peak=400 * MB, ws_peak=30 * MB, ws_n=1)
    assert L.Loop._peak_for_estimate(thin) == 400 * MB
    full = SimpleNamespace(peak=400 * MB, ws_peak=130 * MB, ws_n=L.WS_MIN_SAMPLES)
    assert L.Loop._peak_for_estimate(full) == 130 * MB


def test_reap_books_the_working_set_not_the_commit_peak(tmp_path):
    cur = [0]
    owned = SimpleNamespace(current_bytes=lambda: cur[0], peak_bytes=lambda: 400 * MB, kill=lambda: None,
                            close=lambda: None, proc=SimpleNamespace(returncode=0))
    w = SimpleNamespace(owned=owned, ws_peak=120 * MB, ws_n=L.WS_MIN_SAMPLES, peak=None, fhs=(), tid="T", slot=0,
                        out=tmp_path / "o", err=tmp_path / "e")
    stub = SimpleNamespace(pool=SimpleNamespace(remove=lambda x: None), _peaks=[])
    stub._peak_for_estimate = L.Loop._peak_for_estimate
    try:
        L.Loop._reap(stub, w, True)         # timed out: the result is NO_RESULT, the peaks are booked before
    except Exception:
        pass
    assert stub._peaks == [120 * MB]


def _cap_stub(free, peaks, monkeypatch):
    monkeypatch.setattr(L, "_reserved_bytes", lambda: 0)
    monkeypatch.setattr(L, "_cloud_up", lambda f: True)
    live = SimpleNamespace(owned=None, tid="L", t_start=0.0, ws_peak=0, ws_n=0)
    stub = SimpleNamespace(pool=SimpleNamespace(workers={0: live}), _peaks=list(peaks), err=lambda *a: None,
                           free_ram_fn=lambda: free, cloud_fn=object(), cfg=SimpleNamespace(once=False))
    stub._estimate = lambda: L.Loop._estimate(stub)
    stub._mem_plan = lambda live=None: L.Loop._mem_plan(stub, live)
    stub._ending = lambda: False
    stub._floor = lambda task: L.LIGHT_FLOOR      # fac-68: a light card's floor in the cloud route (was CLOUD_FLOOR 1.5 GB)
    stub._brake_due = None
    stub.ls = lambda: {}
    return stub


def test_capacity_admits_by_the_measured_working_set(monkeypatch):
    free = 1850 * MB
    commit = _cap_stub(free, [1200 * MB] * 6, monkeypatch)      # booked by the commit peak (fac-68: floor 768 MB + median burst): refused
    assert L.Loop._capacity(commit, None, {}) == "low_ram"
    ws = _cap_stub(free, [130 * MB] * 6, monkeypatch)           # booked by the working set: passes the RAM check
    assert L.Loop._capacity(ws, None, {}) != "low_ram"
