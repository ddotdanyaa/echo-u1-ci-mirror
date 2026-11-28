"""fac-95 (<id>): the RAM gate of the agent step books a run's estimate only while the run is young.

Measured on the live loop 28.11: a run holds 239-253 MB and is already missing from the free memory; subtracting the estimate
for every run in flight counted it twice and refused (fault busy) at 3-4 runs with 4 GB free of 16.
"""
import pytest
from tools import factory_architect as A
from tools import factory_gate as G
from tools import factory_paid_critic as PK

NOW = 5000.0


@pytest.fixture
def gate(tmp_path, monkeypatch):
    key = tmp_path / "config.txt"
    key.write_text("ANTHROPIC_API_KEY=fake-test-value\n", encoding="utf-8")
    monkeypatch.setenv("FACTORY_PAID_ENV", str(key))
    monkeypatch.setenv("FACTORY_PAID_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("FACTORY_BUILDERS_SPEND", str(tmp_path / "absent.json"))
    monkeypatch.setenv("FACTORY_BUILDERS_WAITING", str(tmp_path / "absent_waiting"))
    monkeypatch.setattr(PK, "_today", lambda: "2026-11-22")
    monkeypatch.setattr(A, "_now", lambda: NOW)
    monkeypatch.setattr(A, "_agent_runs", [])
    return tmp_path


def _drive(tmp_path):
    def run(*a, **k):
        raise RuntimeError("past the gate")
    try:
        A.ask_agent("sys", "user", cwd=tmp_path, run=run, argv_fn=lambda: ["claude"])
    except Exception as exc:
        return str(exc)
    return ""


def test_old_runs_are_not_booked_twice(gate, monkeypatch):
    monkeypatch.setattr(A, "_agent_runs", [NOW - 300] * 4)
    monkeypatch.setattr(G, "_free_ram", lambda: G.MIN_FREE_RAM + 2 * A.EST_AGENT_BYTES)
    assert "busy" not in _drive(gate)


def test_young_runs_are_booked(gate, monkeypatch):
    monkeypatch.setattr(A, "_agent_runs", [NOW - 10] * 2)
    monkeypatch.setattr(G, "_free_ram", lambda: G.MIN_FREE_RAM + 2 * A.EST_AGENT_BYTES)
    assert "busy" in _drive(gate)


def test_one_estimate_short_is_busy(gate, monkeypatch):
    monkeypatch.setattr(G, "_free_ram", lambda: G.MIN_FREE_RAM + A.EST_AGENT_BYTES - 1)
    assert "busy" in _drive(gate)


def test_young_window_is_a_minute():
    assert A.AGENT_YOUNG_S == 60


def test_a_finished_run_leaves_the_record_once(gate, monkeypatch):
    monkeypatch.setattr(G, "_free_ram", lambda: 10 ** 12)
    monkeypatch.setattr(A, "_agent_runs", [NOW - 300])
    _drive(gate)                                    # any exception on the way out of the call
    assert A.agent_live() == 1 and len(A._agent_runs) == 1


def test_a_normal_return_leaves_the_record_once(gate, monkeypatch):
    import subprocess
    monkeypatch.setattr(G, "_free_ram", lambda: 10 ** 12)
    monkeypatch.setattr(A, "_agent_runs", [])
    seen = []

    def run(argv, **k):
        seen.append(len(A._agent_runs))             # booked while the run is in flight
        out = b'{"type":"result","subtype":"success","result":"x"}\n'
        return subprocess.CompletedProcess(argv, 0, out, b"")
    work = gate.parent / (gate.name + "_work")      # outside the state dir: settings must not sit inside the cwd
    work.mkdir()
    got = A.ask_agent("sys", "user", cwd=work, run=run, argv_fn=lambda: ["claude"])
    assert got == "x"
    assert seen == [1] and len(A._agent_runs) == 0
