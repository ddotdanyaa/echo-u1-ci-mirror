"""W-vgs 5: the telemetry of the pass (vgs in the run row) and the day's numbers (stats.json: vgs)."""
import json
import datetime as dt

from tools import factory_loop as L
from tools import factory_metrics as M
from test_factory_loop import env, Env, Clock, git, task_row, BRANCH, PY  # noqa: <id>


def _row(ts, vgs):
    return json.dumps({"span": "run", "ts": ts, "task_id": "alpha", "kind": "code", "vgs": vgs})


def test_vgs_report_numbers(tmp_path):
    now = dt.datetime(2026, 11, 24, 12, 0, tzinfo=dt.timezone.utc)
    ts = lambda hours: (now - dt.timedelta(hours=hours)).isoformat()
    rows = [_row(ts(1), dict(k=4, asked=4, answered=4, valid=2, unique=2, votes_top=1, gates=2, green_at=2)),
            _row(ts(2), dict(k=4, asked=5, answered=4, valid=1, unique=1, votes_top=1, gates=1)),
            _row(ts(30), dict(k=4, asked=4, answered=4, valid=4, unique=1, votes_top=4, gates=1, green_at=1))]   # older than a day
    (tmp_path / "telemetry.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = M.vgs_report(tmp_path, now=now.isoformat())
    assert report == {"cards": 2, "valid_pct": 37.5, "green_pct": 50.0, "p_hat": 33.3}


def test_vgs_report_of_nothing(tmp_path):
    assert M.vgs_report(tmp_path) == {"cards": 0, "valid_pct": None, "green_pct": None, "p_hat": None}


def test_vgs_of_the_report_reaches_the_run_event(env, monkeypatch):
    loop = env.loop()
    monkeypatch.setattr(loop, "_learn_from_run", lambda *a: None)
    loop._account(L.Worker(-1, "T1", None, "base"), res={
        "status": "READY", "task": "T1", "dur_s": 0, "calls": [], "kind": "code",
        "vgs": {"k": 4, "asked": 4, "answered": 4, "valid": 3, "unique": 2, "votes_top": 2, "gates": 2, "green_at": 2}})
    rows = [e for e in env.events() if e.get("span") == "run" and e.get("task_id") == "T1" and not e.get("role")]
    assert rows and rows[0]["vgs"]["valid"] == 3 and rows[0]["vgs"]["green_at"] == 2
