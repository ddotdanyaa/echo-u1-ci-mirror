"""fac-100: the yield floor is measured among the steps asked now, and a row that already waited gets the weak steps back."""
from test_factory_loop import Env
from tools import factory_architect as A

N = A.YIELD_MIN_ROWS
LIVE = {e: {"yield": v, "rows": N} for e, v in (("solver", 0.5484), ("free_main", 0.3016), ("free", 0.2308),
                                                 ("agent", 0.2195), ("free_small", 0.1852), ("paid", 0.0653))}


def test_a_step_outside_the_order_never_sets_the_bar():
    assert A.YIELD_FLOOR == 0.5
    assert A.weak_steps(("agent", "free", "free_main", "free_small"), LIVE) == set()


def test_a_really_weak_step_of_the_order_is_still_weak():
    assert A.weak_steps(("agent", "paid", "free_main"), LIVE) == {"paid"}


def test_one_measured_step_alone_is_never_weak():
    assert A.weak_steps(("free_small",), LIVE) == set()


def _slice_with(tmp_path, monkeypatch, waits):
    e = Env(tmp_path, monkeypatch)
    seen, events = [], []

    def architect(packet, **kw):
        seen.append(list(kw["asks"]))
        raise RuntimeError("stop")
    loop = e.loop(architect_rungs=("free", "free_main"), extra={"architect_fn": architect})
    steps = {"free": lambda *a, **k: "", "free_main": lambda *a, **k: ""}
    yields = {"free_main": {"yield": 0.4, "rows": N}, "free": {"yield": 0.1, "rows": N}}     # free is under half of free_main
    loop._asks = lambda root=None: dict(steps)
    loop._row_packet = lambda *a, **k: {}
    loop._snapshot = lambda sha: tmp_path
    loop._yield_pick = lambda ls: (yields, False)
    loop._wait_record = lambda ls, bid, create=False: {"waits": waits, "engines": {}}
    loop.ls = lambda: {"to_slice": {}, "architect_quotas": {}}
    loop.save_ls = lambda ls: None
    real = loop.event
    loop.event = lambda kind, **kw: (events.append((kind, kw)), real(kind, **kw))[1]
    tasks, state = loop.load()
    loop._slice("B1", "c", 0, "", gen=1, tasks=tasks, state=state, ls={"to_slice": {}}, now=0)
    for job in list(loop._slicers.values()):
        job.thread.join(5)
    return seen, [kw for k, kw in events if k == "slice" and kw.get("status") == "weak"]


def test_a_row_that_already_waited_keeps_the_weak_step(tmp_path, monkeypatch):
    seen, weak = _slice_with(tmp_path, monkeypatch, waits=1)
    assert seen == [["free", "free_main"]] and not weak


def test_a_row_that_has_not_waited_loses_the_weak_step(tmp_path, monkeypatch):
    seen, weak = _slice_with(tmp_path, monkeypatch, waits=0)
    assert seen == [["free_main"]]
    assert len(weak) == 1 and weak[0]["engine"] == "free"
