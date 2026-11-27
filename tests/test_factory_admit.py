"""fac-68: with a live head the pool admits cards by memory and cloud only; the head alone paces Google calls. 'quota'
stays only when no channel of the route can take a ticket today (all closed by the day / no keys). Without a head the
ledger count holds as before."""
import json
import time
from types import SimpleNamespace

from tools import factory_channels as CH
from tools import factory_head as HD
from tools import factory_loop as L

MB = 2 ** 20
GB = 2 ** 30


def _channels(tmp_path):
    path = tmp_path / "channels.json"
    path.write_text(json.dumps({"channels": [
        {"id": "c1", "model": "google/gemini-3.5-flash-lite", "group": "g1", "key_env": "ADMKEY", "tpm": 1000000,
         "rpd": 500, "rpm": 15, "tier": "main", "verified": True}]}), encoding="utf-8")
    return path


def _stub(tmp_path, monkeypatch, *, head, cards=10, free=8 * GB, keys=True, calls_today=0, head_free=0):
    monkeypatch.setattr(L, "_reserved_bytes", lambda: 0)
    monkeypatch.setattr(L, "_cloud_up", lambda f: False)
    monkeypatch.setattr(HD, "alive", lambda f: head)
    monkeypatch.setattr(HD, "capacity", lambda *a, **k: head_free)
    monkeypatch.setattr(HD, "serves", lambda c: True)
    live = {i: SimpleNamespace(owned=None, tid="L%d" % i, t_start=0.0, ws_peak=0, ws_n=0) for i in range(cards)}
    now = time.time()
    state = {"tasks": {}, "channel_quotas": {"g1": {"request_times": [now - 5] * calls_today}}}
    stub = SimpleNamespace(pool=SimpleNamespace(workers=live), _peaks=[], err=lambda *a: None, free_ram_fn=lambda: free,
                           cloud_fn=None, cfg=SimpleNamespace(once=False, channels=str(_channels(tmp_path))),
                           extra_env={"ADMKEY": "k"} if keys else {}, clock=time.time, ckpt=tmp_path / "ck.json",
                           _headroom_seen=None)
    stub._estimate = lambda: L.Loop._estimate(stub)
    stub._mem_plan = lambda live=None: L.Loop._mem_plan(stub, live)
    stub._floor = lambda task: L.LIGHT_FLOOR
    stub._ending = lambda: False
    stub._brake_due = None
    stub.ls = lambda: {}
    stub._edit_dry = lambda: False
    stub._headroom = lambda task, st: L.Loop._headroom(stub, task, st)
    stub._head_gate = lambda task, st: L.Loop._head_gate(stub, task, st)
    return stub, state


def test_live_head_with_no_free_places_still_admits_by_memory(tmp_path, monkeypatch):
    # fac-68: the live fact: head alive, headroom 0, 10 live cards, enough RAM -> admitted (was "quota")
    stub, state = _stub(tmp_path, monkeypatch, head=True)
    assert L.Loop._capacity(stub, None, state) == ""


def test_live_head_still_refuses_by_memory(tmp_path, monkeypatch):
    stub, state = _stub(tmp_path, monkeypatch, head=True, free=int(0.2 * GB))
    assert L.Loop._capacity(stub, None, state) == "low_ram"


def test_live_head_refuses_quota_when_every_channel_of_the_route_is_closed_by_the_day(tmp_path, monkeypatch):
    stub, state = _stub(tmp_path, monkeypatch, head=True, calls_today=500)
    assert L.Loop._capacity(stub, None, state) == "quota"


def test_live_head_refuses_quota_when_no_key_is_set(tmp_path, monkeypatch):
    stub, state = _stub(tmp_path, monkeypatch, head=True, keys=False)
    assert L.Loop._capacity(stub, None, state) == "quota"


def test_without_a_head_the_ledger_count_holds(tmp_path, monkeypatch):
    stub, state = _stub(tmp_path, monkeypatch, head=False, cards=3, calls_today=0)
    state["channel_quotas"]["g1"]["request_times"] = []
    # rpm 15, 3 unbooked live cards, headroom <= unbooked -> quota (the old behaviour)
    monkeypatch.setattr(L, "_cloud_up", lambda f: False)
    stub._headroom = lambda task, st: 3
    assert L.Loop._capacity(stub, None, state) == "quota"
    stub._headroom = lambda task, st: 4
    assert L.Loop._capacity(stub, None, state) == ""


def test_route_open_today_reads_the_day_not_the_minute(tmp_path):
    ch = CH.validate(json.loads(_channels(tmp_path).read_text(encoding="utf-8"))["channels"])
    now = time.time()
    env = {"ADMKEY": "k"}
    assert CH.route_open_today(ch, {"g1": {"request_times": [now - 1] * 499}}, env, now=now)
    assert not CH.route_open_today(ch, {"g1": {"request_times": [now - 1] * 500}}, env, now=now)
    assert not CH.route_open_today(ch, {}, {}, now=now)
