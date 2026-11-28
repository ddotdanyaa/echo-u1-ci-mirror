"""fac-93 (<id>): a new CONTRACT_REV reopens a failed_gens quarantine at once; the agent RAM estimate is the measured one."""
import pytest
from tools import factory_architect as A
from tools import factory_gate as G
from tools import factory_loop as L
from tools import factory_paid_critic as PK


def _ls(rev, at, kind="failed_gens"):
    return {"quarantine": {"B1": {"kind": kind, "rev": rev, "at": at}}, "row_hist": {"B1": {"failed_gens": L.HARD_FAILED_GENS}}}


def test_other_rev_opens_a_failed_gens_quarantine_at_once():
    now = 1_000_000.0
    ls = _ls("0.0-old", now - 60)
    assert L.Loop._hard_reopen(None, ls, now) == {"B1"}
    assert "B1" not in ls["quarantine"]
    assert ls["row_hist"]["B1"]["failed_gens"] == L.HARD_FAILED_GENS - 1


@pytest.mark.parametrize("age", [0, 60, 86400 * 3])
def test_current_rev_never_opens_at_any_age(age):
    now = 1_000_000.0
    ls = _ls(str(A.CONTRACT_REV), now - age)
    assert L.Loop._hard_reopen(None, ls, now) == set()
    assert "B1" in ls["quarantine"] and ls["row_hist"]["B1"]["failed_gens"] == L.HARD_FAILED_GENS


def test_other_kinds_are_not_touched():
    now = 1_000_000.0
    ls = _ls("0.0-old", now - 10 ** 6, kind="stale")
    assert L.Loop._hard_reopen(None, ls, now) == set()
    assert "B1" in ls["quarantine"]


@pytest.fixture
def env_paid(tmp_path, monkeypatch):
    key = tmp_path / "config.txt"
    key.write_text("ANTHROPIC_API_KEY=fake-test-value\n", encoding="utf-8")
    monkeypatch.setenv("FACTORY_PAID_ENV", str(key))
    monkeypatch.setenv("FACTORY_PAID_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("FACTORY_BUILDERS_SPEND", str(tmp_path / "absent.json"))
    monkeypatch.setenv("FACTORY_BUILDERS_WAITING", str(tmp_path / "absent_waiting"))
    monkeypatch.setattr(PK, "_today", lambda: "2026-11-22")
    return tmp_path


def _drive(tmp_path):
    def run(*a, **k):
        raise RuntimeError("past the gate")
    try:
        A.ask_agent("sys", "user", cwd=tmp_path, run=run, argv_fn=lambda: ["claude"])
    except Exception as exc:
        return str(exc)
    return ""


def test_ram_gate_uses_the_measured_estimate(env_paid, tmp_path, monkeypatch):
    assert A.EST_AGENT_BYTES == 350 * 2**20
    monkeypatch.setattr(A, "_agent_count", 1)
    monkeypatch.setattr(G, "_free_ram", lambda: G.MIN_FREE_RAM + 2 * A.EST_AGENT_BYTES)
    assert "busy" not in _drive(tmp_path)
    monkeypatch.setattr(A, "_agent_count", 0)
    monkeypatch.setattr(G, "_free_ram", lambda: G.MIN_FREE_RAM + A.EST_AGENT_BYTES - 1)
    assert "busy" in _drive(tmp_path)
