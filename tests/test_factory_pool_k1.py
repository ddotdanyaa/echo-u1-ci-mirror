"""<id> layer C: with RAM for one worker the pool loop behaves exactly as the serial loop did (K=1), and the lock
test: no state write in the loop or the runner goes around the fenced transactions.

The golden file tests/data/pool_k1_golden.json was recorded with the serial loop (HEAD 238a85e2, before layer C): the
same scripted runner outcomes, the same scenario code (POOL_K1_RECORD=<file> makes this module write it)."""
import json
import os
import random
import re
import time
from pathlib import Path

import pytest

from tools import factory_loop as L
from test_factory_loop import Env, git, task_row, BRANCH  # noqa: <id>

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "data" / "pool_k1_golden.json"


def _head(env):
    return git(env.repo, "rev-parse", BRANCH)


def _rows(env):
    st = env.state()
    return {t: [r["status"], r["attempts"], r.get("blocked_reason")] for t, r in sorted(st["tasks"].items())}


def _events(env):
    out = []
    for e in env.events():
        if e["span"] in ("loop", "run", "promote") and e.get("status") != "ok" or e["span"] == "loop":
            if e["span"] == "run" and ("stage" in e or e.get("role")):
                continue
            out.append([e["span"], e.get("action"), e.get("reason") if e["span"] != "infra" else None,
                        e.get("status"), e.get("task_id")])
        elif e["span"] == "infra":
            out.append(["infra", None, str(e.get("reason"))[:30], e.get("status"), None])
    return out


def _snap(env, loop, out):
    st = env.state()
    return {"out": [out.action, out.reason, out.status, round(out.sleep), out.proof, out.code],
            "rows": _rows(env), "infra_streak": st["infra_streak"]}


def scenario_review_promote(env, loop):
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": []})
    steps = [_snap(env, loop, loop.step())]
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    steps.append(_snap(env, loop, loop.step()))
    steps.append(_snap(env, loop, loop.step()))
    return steps


def scenario_ready_defer(env, loop):
    env.runner_says({"status": "READY", "task": "T1", "reason": "transient", "wait_s": 30, "calls": []})
    return [_snap(env, loop, loop.step()) for _ in range(3)]


def scenario_no_result(env, loop):
    env.mp.setenv("FAKE_RC", "1")
    env.out.write_text("", encoding="utf-8")
    return [_snap(env, loop, loop.step()) for _ in range(3)]


def scenario_budget_wait(env, loop):
    env.runner_says({"status": "WAITING_CHANNEL", "task": "T1", "reason": "budget_exhausted", "wait_s": 120})
    return [_snap(env, loop, loop.step()) for _ in range(3)]


def scenario_blocked(env, loop):
    env.runner_says({"status": "BLOCKED", "task": "T1", "reason": "scope_violation", "calls": []})
    return [_snap(env, loop, loop.step()) for _ in range(2)]


def scenario_temporary_429(env, loop):
    env.runner_says({"status": "READY", "task": "T1", "reason": "rate_limited", "http_status": 429, "calls": []})
    return [_snap(env, loop, loop.step()) for _ in range(3)]


def scenario_low_ram(env, loop):
    env.free[0] = 512 * 2 ** 20      # below the light floor (768 MB)
    steps = [_snap(env, loop, loop.step())]
    env.free[0] = 8 * 2 ** 30
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    steps.append(_snap(env, loop, loop.step()))
    return steps


def scenario_locked_state(env, loop):
    (env.state_dir / "state.json.lockdir").mkdir()
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    return [_snap(env, loop, loop.step())]


SCENARIOS = {name[len("scenario_"):]: fn for name, fn in sorted(globals().items()) if name.startswith("scenario_")}


def record(name, tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch, tasks=[task_row(1)])
    env.free = [8 * 2 ** 30]
    monkeypatch.setattr(L.Loop, "TXN_WAIT_S", 0.3, raising=False)
    monkeypatch.setattr(L.Loop, "CLAIM_WAIT_S", 0.3, raising=False)
    loop = env.loop(rng=random.Random(7), extra={"free_ram_fn": lambda: env.free[0]})
    steps = SCENARIOS[name](env, loop)
    return {"steps": steps, "events": _events(env)}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_k1_matches_the_serial_loop(name, tmp_path, monkeypatch):
    got = record(name, tmp_path, monkeypatch)
    target = os.environ.get("POOL_K1_RECORD")
    if target:
        data = json.loads(Path(target).read_text(encoding="utf-8")) if Path(target).exists() else {}
        data[name] = got
        Path(target).write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))[name]
    assert json.loads(json.dumps(got)) == want


# ---- the lock test -------------------------------------------------------------------------------------------

def _src(name):
    return (ROOT / "tools" / name).read_text(encoding="utf-8")


def test_no_unlocked_state_writes():
    loop, runner = _src("factory_loop.py"), _src("agent_factory_runner.py")
    assert "save_atomic(checkpoint" not in runner
    assert "F.save_atomic(self.ckpt" not in loop and "def save(" not in loop
    assert not re.search(r"self\.save\(", loop)
    assert "--max-tasks" not in loop                      # the loop hands over the task and its lease
    assert "run_owned(" not in loop                       # workers are started and watched, not waited for in a call


def test_every_state_mutation_in_the_loop_sits_inside_a_txn():
    """Each `self.txn()` block is the only place the loop's tools mutate a state; reading goes through snapshot."""
    loop = _src("factory_loop.py")
    assert "self.txn()" in loop and "F.snapshot(" in loop
    assert not re.search(r"F\.save_atomic\(self\.ckpt", loop)
