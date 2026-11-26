"""W-a4: the slicer picks the step of the ladder by the cohort's measured yield (first contract -> row merged in the end)."""
from types import SimpleNamespace

from tools import factory_architect as A
from tools import factory_loop as L

ALL = ("free", "free_main", "free_small", "paid", "agent")
# the audit of 26.11: contracts -> merged by engine (loop_state.contracts_by_engine)
TABLE = {"free_small": (322, 1), "free+free_main": (93, 0), "free": (378, 13), "free_main": (146, 7),
         "paid": (643, 42), "agent": (89, 7), "agent+solver": (159, 25)}
NOW = 10_000_000.0


def cohort(table=TABLE, at=NOW - A.YIELD_SETTLE_S - 1):
    out = {}
    for engine, (made, merged) in table.items():
        for i in range(made):
            out["%s-%d" % (engine, i)] = dict(engine=engine, at=at, merged=i < merged)
    return out


def test_the_measured_table_does_not_start_with_free_small():
    big = dict(TABLE)       # the window holds the latest YIELD_WINDOW rows: a scaled table keeps every engine in it
    small = {e: (max(1, m * A.YIELD_WINDOW // 1900), g * A.YIELD_WINDOW // 1900) for e, (m, g) in big.items()}
    small["free_small"] = (A.YIELD_MIN_ROWS + 50, 0)
    yields = A.engine_yield(cohort(small), NOW)
    assert yields["free_small"]["rows"] >= A.YIELD_MIN_ROWS
    for rung in (0, 1, 2):
        order = A.ladder(rung, rungs=ALL, yields=yields)
        assert order[0] != "free_small" and order[-1] == "free_small" and sorted(order) == sorted(ALL)
    full = A.engine_yield({k: v for k, v in cohort().items()}, NOW)      # the whole table, the window cuts to the latest rows
    assert A.ladder(0, rungs=ALL, yields=full)[0] != "free_small"


def test_the_yield_credits_the_first_engine_not_the_last_rung():
    rows = {"r1": dict(engine="free_small", at=0, merged=True), "r2": dict(engine="paid", at=0, merged=False)}
    rows.update({"s%d" % i: dict(engine="free_small", at=0, merged=True) for i in range(A.YIELD_MIN_ROWS)})
    rows.update({"p%d" % i: dict(engine="paid", at=0, merged=False) for i in range(A.YIELD_MIN_ROWS)})
    y = A.engine_yield(rows, NOW)
    assert y["free_small"]["yield"] == 1.0 and y["paid"]["yield"] == 0.0
    assert A.ladder(1, rungs=ALL, yields=y) == ["free_small", "agent", "free", "free_main", "paid"]
    young = {"y": dict(engine="agent", at=NOW, merged=False)}     # still young and unmerged: not counted yet
    assert A.engine_yield(young, NOW) == {}


def test_the_probe_share_is_kept():
    loop = SimpleNamespace(clock=lambda: NOW)
    ls = {"cohort": cohort()}
    leads = []
    for _ in range(100):
        yields, probe = L.Loop._yield_pick(loop, ls)
        leads.append(A.ladder(0, rungs=ALL, yields=yields, probe=probe)[0])
    worst = min((e for e in ALL if e in yields), key=lambda e: yields[e]["yield"])
    assert leads.count(worst) == 100 // A.PROBE_EVERY
    assert all(lead != worst for i, lead in enumerate(leads) if (i + 1) % A.PROBE_EVERY)


def test_no_data_keeps_the_old_ladder():
    for rung in (0, 1, 2):
        assert A.ladder(rung, rungs=ALL, yields={}) == A.ladder(rung, rungs=ALL)
        assert A.ladder(rung, rungs=ALL, yields=A.engine_yield({}, NOW), probe=True) == A.ladder(rung, rungs=ALL)
    few = {"x%d" % i: dict(engine="free_small", at=0, merged=False) for i in range(A.YIELD_MIN_ROWS - 1)}
    assert A.ladder(0, rungs=ALL, yields=A.engine_yield(few, NOW)) == A.ladder(0, rungs=ALL)     # not confirmed yet
    loop = SimpleNamespace(clock=lambda: NOW)
    assert L.Loop._yield_pick(loop, {}) == ({}, False)


def test_the_cohort_keeps_the_first_engine_only():
    loop = SimpleNamespace(clock=lambda: NOW)
    ls = {}
    L.Loop._cohort_first(loop, ls, "row-1", "free_small")
    L.Loop._cohort_first(loop, ls, "row-1", "paid")
    assert ls["cohort"]["row-1"]["engine"] == "free_small" and ls["cohort"]["row-1"]["merged"] is False
