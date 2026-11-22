"""<id> wiring: A/B experiments in the loop (registry, arm per task, RUN event carries the arms, decision at START)."""
import json

from tests.test_factory_loop import Env, task_row
from tests.test_factory_loop_spec import CHANNEL, GOOD, fake_post
from tools import factory_ab as AB
from tools import factory_loop as L


def pick(experiment, arm, kind=None):
    """A task number whose stable hash gives `arm` in `experiment`."""
    arms = L.EXPERIMENTS[experiment]
    for i in range(1, 200):
        if AB.assign("T%d" % i, experiment, arms) == arm:
            return i
    raise AssertionError("no task id for %s=%s" % (experiment, arm))


def make(tmp_path, monkeypatch, i, **kw):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(i, **kw)])
    (tmp_path / "channels.json").write_text(json.dumps({"channels": [CHANNEL]}), encoding="utf-8")
    env.runner_says({"status": "NO_RESULT"})
    return env


def run_events(env):
    return [e for e in env.events() if e["span"] == "loop" and e.get("action") == "RUN"]


def runner_args(env):
    line = env.log.read_text(encoding="utf-8").splitlines()[-1].split(" KEY=")[0].split()
    return {a: line[k + 1] for k, a in enumerate(line) if a.startswith("--") and k + 1 < len(line)}


def tel(path, rows, raw_first=None):
    lines = ([raw_first] if raw_first else []) + [json.dumps(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rows(arm, status, n=12, exp="spec_pass"):
    return [{"span": "loop", "action": "RUN", "status": status, "experiments": {exp: arm}} for _ in range(n)]


def test_registry_has_the_experiments():
    assert L.EXPERIMENTS["spec_pass"] == ("on", "off")
    assert L.EXPERIMENTS["coder_model"] == ("google/gemini-3.5-flash-lite", "google/gemini-3.1-flash-lite")
    assert L.EXPERIMENTS["small_follow_up"] == ("on", "off")
    assert L.PER_HOUR_EXPERIMENTS == {"small_follow_up"}


def test_run_event_carries_the_experiments(tmp_path, monkeypatch):
    i = pick("coder_model", L.EXPERIMENTS["coder_model"][0])
    env = make(tmp_path, monkeypatch, i)
    env.loop().step()
    ev = run_events(env)
    assert len(ev) == 1
    # a plain code task is not in the spec_pass experiment
    assert ev[0]["experiments"] == {"coder_model": L.EXPERIMENTS["coder_model"][0],
                                    "small_follow_up": AB.assign("T%d" % i, "small_follow_up", ("on", "off"))}


def test_run_event_of_a_unit_test_task_has_all(tmp_path, monkeypatch):
    i = pick("spec_pass", "off")
    env = make(tmp_path, monkeypatch, i, kind="unit_test", touch_files=["tests/test_x%d.py" % i])
    env.loop().step()
    exps = run_events(env)[0]["experiments"]
    assert exps["spec_pass"] == "off" and set(exps) == {"spec_pass", "coder_model", "small_follow_up"}


def test_the_small_follow_up_arm_is_what_the_runner_gets(tmp_path, monkeypatch):
    for n, arm in enumerate(("on", "off")):
        sub = tmp_path / ("s%d" % n)
        sub.mkdir()
        env = make(sub, monkeypatch, pick("small_follow_up", arm))
        env.loop().step()
        assert runner_args(env)["--small-follow-up"] == arm


def test_start_decides_small_follow_up_per_hour(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    slow = [{"span": "loop", "action": "RUN", "status": "REVIEW" if k < 4 else "READY", "dur_s": 250.0,
             "experiments": {"small_follow_up": "on"}} for k in range(20)]
    fast = [dict(row, dur_s=100.0, experiments={"small_follow_up": "off"}) for row in slow]
    loop = env.loop()
    monkeypatch.setattr(loop, "_telemetry_rows", lambda: slow + fast)
    loop._decide_experiments()
    assert loop.ls()["experiments"]["small_follow_up"]["winner"] == "off"
    assert loop.arm("T%d" % 999, "small_follow_up") == "off"


def test_spec_pass_off_makes_no_spec_call(tmp_path, monkeypatch):
    i = pick("spec_pass", "off")
    env = make(tmp_path, monkeypatch, i, kind="unit_test", touch_files=["tests/test_x%d.py" % i],
               read_files=["tools/x1.py"], goal="Add must add two numbers properly.")
    calls = []
    monkeypatch.setattr(L, "_light_post", fake_post(calls, json.dumps(GOOD)))
    env.loop(extra={"extra_env": {"FAKE_KEY_ENV": "k"}}).step()
    assert calls == [] and env.runs() == 1
    assert "specs" not in env.loop().ls() or "T%d" % i not in env.loop().ls()["specs"]


def test_spec_pass_on_still_calls_the_model(tmp_path, monkeypatch):
    i = pick("spec_pass", "on")
    env = make(tmp_path, monkeypatch, i, kind="unit_test", touch_files=["tests/test_x%d.py" % i],
               read_files=["tools/x1.py"], goal="Add must add two numbers properly.")
    calls = []
    monkeypatch.setattr(L, "_light_post", fake_post(calls, json.dumps(GOOD)))
    env.loop(extra={"extra_env": {"FAKE_KEY_ENV": "k"}}).step()
    assert len(calls) == 1


def test_the_coder_arm_is_the_model_the_runner_gets(tmp_path, monkeypatch):
    a, b = L.EXPERIMENTS["coder_model"]
    for n, arm in enumerate((a, b)):
        sub = tmp_path / ("c%d" % n)
        sub.mkdir()
        env = make(sub, monkeypatch, pick("coder_model", arm))
        env.loop().step()
        args = runner_args(env)
        assert args["--small-model"] == arm and args["--large-model"] == arm
        assert args["--review-model"] != arm
        assert args["--review-model"] in (a, b)


def test_start_decides_a_winner_and_arm_returns_it(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    tel(env.state_dir / "telemetry.jsonl", rows("on", "REVIEW") + rows("off", "FAILED"))
    loop = env.loop(once=True)
    assert loop.run() == L.EXIT_OK
    win = loop.ls()["experiments"]["spec_pass"]
    assert win["winner"] == "on" and win["per_arm"]["off"]["n"] == 12 and win["at"]
    assert "coder_model" not in loop.ls().get("experiments", {})
    journal = [json.loads(x) for x in (env.state_dir / "growth.jsonl").read_text(encoding="utf-8").splitlines()]
    assert journal[0]["experiment"] == "spec_pass" and journal[0]["winner"] == "on"
    assert any(e["span"] == "experiment" and e["status"] == "decided" for e in env.events())
    for t in ("T%d" % 1, "T%d" % 2, "T%d" % pick("spec_pass", "off")):
        assert loop.arm(t, "spec_pass") == "on"
    assert loop.arm("T1", "coder_model") in L.EXPERIMENTS["coder_model"]


def test_a_decided_experiment_is_not_decided_twice(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    tel(env.state_dir / "telemetry.jsonl", rows("on", "REVIEW") + rows("off", "FAILED"))
    env.loop(once=True).run()
    env.loop(once=True).run()
    journal = (env.state_dir / "growth.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(journal) == 1


def test_a_broken_telemetry_line_stops_nothing(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    tel(env.state_dir / "telemetry.jsonl", rows("on", "REVIEW", 6), raw_first="{not json")
    tel(env.state_dir / "telemetry.jsonl.1", rows("on", "REVIEW", 6) + rows("off", "FAILED"), raw_first="\x00garbage")
    loop = env.loop(once=True)
    assert loop.run() == L.EXIT_OK
    assert loop.ls()["experiments"]["spec_pass"]["winner"] == "on"
    assert env.runs() == 1


def test_a_fault_in_the_decision_goes_to_err_and_the_loop_runs(tmp_path, monkeypatch):
    env = make(tmp_path, monkeypatch, 1)
    monkeypatch.setattr(AB, "outcomes", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    loop = env.loop(once=True)
    assert loop.run() == L.EXIT_OK
    assert env.runs() == 1
    assert any(e["span"] == "infra" and "boom" in str(e.get("reason")) for e in env.events())
