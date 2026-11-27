"""fac-43 (was <id> A/B wiring): the loop has no A/B arms any more. The coder model of a call is the router's pick in the
runner (tools/factory_router.py); the loop hands the runner its configured models and builds the score table at START.
Replaced: the arm registry, the arm per task, the RUN event's arms and the START decision of an experiment ->
tests/test_factory_router_table.py (the table and the pick) and the tests below."""
import json

from tests.test_factory_loop import Env, task_row
from tools import factory_loop as L
from tools import factory_router as RT

CHANNEL = {"id": "g1", "model": "google/gemini-x", "group": "g", "key_env": "FAKE_KEY_ENV",
           "tpm": 100000, "rpm": 100, "rpd": 1000}


def make(tmp_path, monkeypatch, i, **kw):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(i, **kw)])
    (tmp_path / "channels.json").write_text(json.dumps({"channels": [CHANNEL]}), encoding="utf-8")
    env.runner_says({"status": "NO_RESULT"})
    return env


def runner_args(env):
    line = env.log.read_text(encoding="utf-8").splitlines()[-1].split(" KEY=")[0].split()
    return {a: line[k + 1] for k, a in enumerate(line) if a.startswith("--") and k + 1 < len(line)}


def tel(path, rows, raw_first=None):
    lines = ([raw_first] if raw_first else []) + [json.dumps(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_runner_gets_the_configured_models_and_no_arm(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    loop = env.loop()
    loop.step()
    args = runner_args(env)
    assert args["--small-model"] == loop.cfg.small_model and args["--large-model"] == loop.cfg.large_model
    assert args["--review-model"] == loop.cfg.review_model
    assert "--small-follow-up" not in args
    runs = [e for e in env.events() if e["span"] == "loop" and e.get("action") == "RUN"]
    assert runs and all("experiments" not in e for e in runs)


def test_start_builds_the_router_table_from_the_telemetry(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    tel(env.state_dir / "telemetry.jsonl", [
        {"span": "run", "task_id": "A", "role": "edit", "model": "google/x"},
        {"span": "accepted", "task_id": "A", "models": {"edit": {"google/x": 1}}}])
    loop = env.loop(once=True)
    assert loop.run() == L.EXIT_OK
    row = RT.load(env.state_dir)["rows"]["google/x|edit"]
    assert row["calls"] == 1 and row["accepted"] == 1.0


def test_a_broken_telemetry_line_stops_nothing(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    tel(env.state_dir / "telemetry.jsonl", [{"span": "run", "task_id": "A", "role": "code", "model": "google/x"}],
        raw_first="{not json")
    tel(env.state_dir / "telemetry.jsonl.1", [], raw_first="\x00garbage")
    loop = env.loop(once=True)
    assert loop.run() == L.EXIT_OK
    assert RT.load(env.state_dir)["rows"]["google/x|code"]["calls"] == 1
    assert env.runs() == 1


def test_a_fault_in_the_table_goes_to_err_and_the_loop_runs(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    monkeypatch.setattr(RT, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    loop = env.loop(once=True)
    assert loop.run() == L.EXIT_OK
    assert env.runs() == 1
    assert any(e["span"] == "infra" and "boom" in str(e.get("reason")) for e in env.events())
