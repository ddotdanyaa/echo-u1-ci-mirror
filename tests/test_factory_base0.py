"""W-base0: the old baseline debt rel-base-<n> never spends paid money: the slicer ladder is free only, the paid control critic skips it."""
from types import SimpleNamespace

from tools import factory_architect as A
from tools import factory_paid_critic as PK

FULL = ("free", "free_main", "paid", "agent")


def test_base_debt_ladder_is_free_only_with_an_empty_echo_queue():
    for rung in (0, 1, 2, 3):
        for red in (False, True):
            for dry in (False, True):
                assert A.ladder(rung, rungs=FULL, red=red, dry=dry, base_debt=True) == ["free", "free_main"]


def test_fresh_regression_and_echo_row_ladders_are_as_before():
    assert A.ladder(0, rungs=FULL) == ["free", "free_main", "paid", "agent"]
    assert A.ladder(1, rungs=FULL) == ["paid", "agent", "free", "free_main"]
    assert A.ladder(0, rungs=FULL, red=True) == ["agent", "paid", "free", "free_main"]


def test_contract_for_a_debt_row_asks_only_free_steps_without_any_waiting_flag():
    asked = []

    def ask(name):
        def go(system, user):
            asked.append(name)
            raise A.ContractFault("no answer")
        return go
    asks = {k: ask(k) for k in FULL}
    try:
        A.contract_for({"bid": "rel-base-9", "red_given": True}, rung=2, root=".", asks=asks)
    except Exception:
        pass
    assert asked and set(asked) <= {"free", "free_main"}


def test_the_paid_control_critic_never_looks_at_a_debt_row(monkeypatch, tmp_path):
    key = tmp_path / "paid.cfg"
    key.write_text("ANTHROPIC_API_KEY=k\n", encoding="utf-8")
    monkeypatch.setenv("FACTORY_PAID_ENV", str(key))
    seen = []
    monkeypatch.setattr(PK, "credit_dead", lambda *a, **k: False)
    monkeypatch.setattr(PK, "_control", lambda task, *a, **k: seen.append(task.backlog_id) or {"verdict": "ok"})
    assert PK.control(SimpleNamespace(backlog_id="rel-base-9", id="t1"), "diff") is None
    assert not seen
    assert PK.control(SimpleNamespace(backlog_id="rel-1a2b3c4d-1", id="t2"), "diff") == {"verdict": "ok"}
    assert seen == ["rel-1a2b3c4d-1"]
