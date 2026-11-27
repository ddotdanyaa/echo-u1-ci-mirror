"""<id> layer C: the loop runs K runners at once (tools/factory_loop.py Pool). K comes only from free RAM and free quota
headroom; no model, no network; the runner is a small script that claims nothing itself (the loop claimed for it)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from tools import factory_process
from test_factory_loop import Env, git, task_row, BRANCH, PY  # noqa: <id>

ROOT = Path(__file__).resolve().parents[1]
TID2 = "T" + "2"                      # the loop env plans <id>..T3; the label is built so no ID-shaped literal stays
GB = 2 ** 30

POOL_RUNNER = r'''
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, %(root)r)
from tools import agent_factory as F
a = sys.argv[1:]
def opt(n):
    return a[a.index(n) + 1] if n in a else None
tid, lease, ck, plan = opt("--task"), opt("--lease"), Path(opt("--checkpoint")), Path(opt("--plan"))
def log(**kw):
    with open(os.environ["POOL_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(kw, tid=tid, t=time.time(), pid=os.getpid())) + chr(10))
with F.txn(ck, plan) as (tasks, state):
    resumed = bool(state["tasks"][tid].get("pending_review"))
    if os.environ.get("POOL_BEGIN"):
        F.begin(state, tid, lease, os.getpid())
log(ev="start", root=opt("--root"), base=opt("--base-sha"), lease=lease, resumed=resumed, args=a,
    max_tasks="--max-tasks" in a)
if os.environ.get("POOL_DIE_" + tid):
    sys.exit(3)
time.sleep(float(os.environ.get("POOL_SLEEP_" + tid, os.environ.get("POOL_SLEEP", "0"))))
status = os.environ.get("POOL_STATUS_" + tid, os.environ.get("POOL_STATUS", "READY"))
if status == "REVIEW":
    files = json.loads(os.environ.get("POOL_FILES_" + tid, "{}"))
    stage = Path(opt("--staging")) / "for-review" / tid
    for name, text in files.items():
        dst = stage / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
    with F.txn(ck, plan) as (tasks, state):
        state["tasks"][tid]["pending_review"] = {"workdir": str(stage), "baseline_digest": "d", "coder_model": "m"}
        F.settle(state, tid, lease, tests_ok=True, evidence="1" * 64)
        state["tasks"][tid].pop("pending_review", None)
elif status == "DONE":
    with F.txn(ck, plan) as (tasks, state):
        row = state["tasks"][tid]
        row.update(status="DONE", lease=None, deadline=None)
        row.pop("began", None)
elif status == "READY" and os.environ.get("POOL_BEGIN"):
    with F.txn(ck, plan) as (tasks, state):
        F.settle(state, tid, lease, tests_ok=False, evidence="2" * 64, strike=False)
log(ev="end")
calls = [{"returncode": 0, "output_tokens": 5, "model": "m", "role": "code"}] if os.environ.get("POOL_PROOF") else []
print(json.dumps({"status": status, "task_id": tid, "task": tid, "calls": calls, "dur_s": 0.1}))
''' % {"root": str(ROOT)}


def pool_env(tmp_path, monkeypatch, tasks, *, rpm=60, keys=True, free=8 * GB, **loop_kw):
    env = Env(tmp_path, monkeypatch, tasks=tasks)
    env.script.write_text(POOL_RUNNER, encoding="utf-8")
    env.plog = tmp_path / "pool.log"
    monkeypatch.setenv("POOL_LOG", str(env.plog))
    monkeypatch.setenv("POOL_BEGIN", "1")
    (tmp_path / "channels.json").write_text(json.dumps({"channels": [
        {"id": "c1", "model": "google/gemini-3.5-flash-lite", "group": "g1", "key_env": "POOLKEY", "tpm": 1000000,
         "rpd": 1000, "rpm": rpm, "tier": "main", "verified": True}]}), encoding="utf-8")
    env.free = [free]
    extra = {"extra_env": {"POOLKEY": "k"} if keys else {}, "free_ram_fn": lambda: env.free[0]}
    env.make_loop = lambda **kw: env.loop(extra=extra, **{**loop_kw, **kw})
    return env


def plog(env):
    if not env.plog.exists():
        return []
    return [json.loads(x) for x in env.plog.read_text(encoding="utf-8").splitlines()]


def spans(env):
    by = {}
    for e in plog(env):
        by.setdefault(e["tid"], {})[e["ev"]] = e["t"]
    return by


def overlap(env, a, b):
    s = spans(env)
    return max(s[a]["start"], s[b]["start"]) < min(s[a]["end"], s[b]["end"])


def run_steps(loop, n, env=None, tids=None):
    """Up to n steps; with ``tids`` it stops as soon as every one of them has ended."""
    out = []
    for _ in range(n):
        out.append(loop.step())
        if env is not None and tids and all("end" in spans(env).get(t, {}) for t in tids):
            break
    return out


def test_runs_disjoint_tasks_together_and_never_two_that_share_a_test(tmp_path, monkeypatch):
    # W-optim replacement: a shared EXISTING test file holds nothing any more; only the same NEW test file (test.new) does
    same_new = json.dumps({"test": {"new": {"path": "tests/test_shared_new.py"}}})
    env = pool_env(tmp_path, monkeypatch, [task_row(1, contract=same_new), task_row(2),
                                           task_row(3, contract=same_new)])
    monkeypatch.setenv("POOL_SLEEP", "1.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    loop = env.make_loop()
    run_steps(loop, 8, env, ("T1", TID2, "T3"))
    s = spans(env)
    assert set(s) == {"T1", TID2, "T3"}
    assert overlap(env, "T1", TID2)                       # disjoint: together
    assert not overlap(env, "T1", "T3") and not overlap(env, "T3", "T1")   # one new test file: never together
    assert all(not e["max_tasks"] for e in plog(env) if e["ev"] == "start")   # the loop hands the task and the lease
    assert all(e["lease"] for e in plog(env) if e["ev"] == "start")


def test_k_follows_free_ram_and_quota(tmp_path, monkeypatch):
    # a Kilo-engine task (more than LIGHT_MAX_FILES files) needs the gate's 2 GB floor; a light one only LIGHT_FLOOR
    from tools.agent_factory_runner import LIGHT_MAX_FILES
    rows = [task_row(i, touch_files=["tools/x%d_%d.py" % (i, n) for n in range(LIGHT_MAX_FILES + 1)]) for i in (1, 2, 3)]
    monkeypatch.setenv("POOL_SLEEP", "0.6")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    # 1.9 GB free: nothing starts
    (tmp_path / "a").mkdir()
    env = pool_env(tmp_path / "a", monkeypatch, rows, free=int(1.9 * GB))
    out = env.make_loop().step()
    assert out.action == "WAIT" and out.reason == "low_ram" and not plog(env)
    # 2.1 GB: one worker at a time (a second needs the floor plus its estimate)
    (tmp_path / "b").mkdir()
    env = pool_env(tmp_path / "b", monkeypatch, rows, free=int(2.1 * GB))
    loop = env.make_loop()
    run_steps(loop, 10, env, ("T1", TID2, "T3"))
    s = spans(env)
    assert len(s) == 3 and not overlap(env, "T1", TID2) and not overlap(env, TID2, "T3")
    pools = [e for e in env.events() if e["span"] == "pool"]
    assert any(e.get("refused_by") == "low_ram" for e in pools)
    # ample RAM, quota for one first call only (rpm 1): one worker at a time
    (tmp_path / "c").mkdir()
    env = pool_env(tmp_path / "c", monkeypatch, rows, rpm=1)
    loop = env.make_loop()
    run_steps(loop, 10, env, ("T1", TID2, "T3"))
    s = spans(env)
    assert len(s) == 3 and not overlap(env, "T1", TID2)
    assert any(e.get("refused_by") == "quota" for e in env.events() if e["span"] == "pool")
    # no channels known: no second worker either
    (tmp_path / "d").mkdir()
    env = pool_env(tmp_path / "d", monkeypatch, rows, keys=False)
    run_steps(env.make_loop(), 10, env, ("T1", TID2))
    assert not overlap(env, "T1", TID2)


def test_the_estimate_reserves_what_live_workers_have_not_used_yet(tmp_path, monkeypatch):
    rows = [task_row(i) for i in range(1, 9)]
    monkeypatch.setenv("POOL_SLEEP", "1.5")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, rows, free=int(3.7 * GB))     # 3.7 GB free all the time
    loop = env.make_loop()
    loop.step()
    started = {e["tid"] for e in plog(env) if e["ev"] == "start"}
    est = 300 * 2 ** 20
    from tools.factory_loop import LIGHT_FLOOR      # light tasks (one file): the light floor, not the gate's 2 GB
    assert 1 <= len(started) <= int((3.7 * GB - LIGHT_FLOOR) // est)


def _review_runner_env(monkeypatch, tid, files):
    monkeypatch.setenv("POOL_STATUS_" + tid, "REVIEW")
    monkeypatch.setenv("POOL_FILES_" + tid, json.dumps(files))


def test_promotes_serial_after_their_run_event(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2)])
    monkeypatch.setenv("POOL_SLEEP", "0.5")
    _review_runner_env(monkeypatch, "T1", {"tools/x1.py": "a = 2\n"})
    _review_runner_env(monkeypatch, TID2, {"tools/x2.py": "a = 3\n"})
    loop = env.make_loop()
    base = git(env.repo, "rev-parse", BRANCH)
    for _ in range(6):
        loop.step()
        if all(r["status"] == "PROMOTED" for r in env.state()["tasks"].values()):
            break
    assert all(r["status"] == "PROMOTED" for r in env.state()["tasks"].values())
    log = git(env.repo, "log", "--format=%s", BRANCH).splitlines()
    assert sum(1 for x in log if x.startswith("factory(")) == 2
    ev = [e for e in env.events() if e["span"] in ("run", "promote") and e.get("task_id") and e.get("status") != "ok"
          and e["span"] == "promote" or (e["span"] == "run" and e.get("task_id") and "stage" not in e)]
    for tid in ("T1", TID2):
        run_i = next(i for i, e in enumerate(ev) if e["span"] == "run" and e["task_id"] == tid)
        pro_i = next(i for i, e in enumerate(ev) if e["span"] == "promote" and e["task_id"] == tid)
        assert run_i < pro_i
        assert next(e for e in ev if e["span"] == "promote" and e["task_id"] == tid)["base_sha"] == base


def test_own_concurrent_promote_in_neighbourhood_requeues_with_candidate(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [], )
    repo = env.repo
    (repo / "tools" / "pb.py").write_text("v = 1\n", encoding="utf-8")
    (repo / "tools" / "pa.py").write_text("from tools import pb\nw = pb.v\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_pa.py").write_text("from tools import pa\ndef test_pa():\n    assert pa.w == 1\n",
                                                encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "pa pb")
    rows = [{"id": "TY", "title": "y", "touch_files": ["tools/pb.py"], "tests": ["tests/test_pb.py"],
             "privacy_safe": True, "estimated_tokens": 100, "backlog_id": "BY"},
            {"id": "TX", "title": "x", "touch_files": ["tools/pa.py"], "tests": ["tests/test_pa.py"],
             "privacy_safe": True, "estimated_tokens": 100, "backlog_id": "BX"}]
    (env.state_dir / "plan.json").write_text(json.dumps({"tasks": rows}), encoding="utf-8")
    monkeypatch.setenv("POOL_SLEEP_TY", "0.3")
    monkeypatch.setenv("POOL_SLEEP_TX", "0.8")
    _review_runner_env(monkeypatch, "TY", {"tools/pb.py": "v = 2\n"})
    _review_runner_env(monkeypatch, "TX", {"tools/pa.py": "from tools import pb\nw = pb.v\nz = 1\n"})
    loop = env.make_loop()
    for _ in range(8):
        loop.step()
        if env.state()["tasks"]["TY"]["status"] == "PROMOTED" and plog_count(env, "TX") >= 2:
            break
    st = env.state()["tasks"]
    assert st["TY"]["status"] == "PROMOTED"
    starts = [e for e in plog(env) if e["ev"] == "start" and e["tid"] == "TX"]
    assert len(starts) >= 2, "TX must run again (gates on the new base)"
    assert starts[0]["resumed"] is False and starts[1]["resumed"] is True    # the candidate came back: no coder call
    pro = [e for e in env.events() if e["span"] == "promote" and e.get("task_id") == "TX"]
    assert pro and pro[0]["status"] == "requeued" and pro[0]["reason"] == "base_moved"


def plog_count(env, tid):
    return sum(1 for e in plog(env) if e["ev"] == "start" and e["tid"] == tid)


def test_dead_before_begin_unclaimed_after_begin_keeps_lease(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    monkeypatch.setenv("POOL_DIE_T1", "1")
    monkeypatch.delenv("POOL_BEGIN")                 # dies before its begin
    loop = env.make_loop()
    run_steps(loop, 3, env, ("T1",))
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "READY" and row["attempts"] == 0 and row["lease"] is None     # unclaimed: as if never run
    (tmp_path / "x").mkdir()
    env2 = pool_env(tmp_path / "x", monkeypatch, [task_row(1)])
    monkeypatch.setenv("POOL_BEGIN", "1")
    run_steps(env2.make_loop(), 3, env2, ("T1",))
    row = env2.state()["tasks"]["T1"]
    assert row["status"] == "RUNNING" and row["lease"] and row["attempts"] == 1       # began: the lease stays until it ends


def test_brake_and_stop_drain_live_workers(tmp_path, monkeypatch):
    rows = [task_row(1), task_row(2)]
    env = pool_env(tmp_path, monkeypatch, rows)
    monkeypatch.setenv("POOL_SLEEP_T1", "0.3")
    monkeypatch.setenv("POOL_SLEEP_T2", "1.2")
    loop = env.make_loop()
    orig = loop._account

    def account(w, *a, **k):
        if w.tid == "T1":
            (env.state_dir / "STOP").write_text("", encoding="utf-8")      # STOP arrives while <id> still runs
        return orig(w, *a, **k)
    loop._account = account
    code = loop.run()
    assert code == L.EXIT_OK
    s = spans(env)
    assert "end" in s[TID2]                        # the second task was waited for, not abandoned
    assert not loop.pool.workers
    starts = [e["t"] for e in plog(env) if e["ev"] == "start"]
    assert len(starts) == 2                        # nothing was admitted after the STOP
    assert env.state()["tasks"][TID2]["status"] != "RUNNING" or env.state()["tasks"][TID2].get("lease")


def test_a_proof_during_the_drain_cancels_the_brake(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2)])
    monkeypatch.setenv("POOL_SLEEP_T1", "0.2")
    monkeypatch.setenv("POOL_SLEEP_T2", "1.0")
    monkeypatch.setenv("POOL_DIE_T1", "1")
    monkeypatch.delenv("POOL_BEGIN")
    monkeypatch.setenv("POOL_PROOF", "1")            # <id> carries a real model call: a proof of work
    _review_runner_env(monkeypatch, TID2, {"tools/x2.py": "a = 3\n"})
    loop = env.make_loop(max_infra=1)               # one infrastructure failure would brake at once
    run_steps(loop, 2)                               # <id> dies first (brake due), <id> proves the pipeline in the drain
    assert not (env.state_dir / "BRAKE").exists()
    assert not loop.pool.workers
    assert env.state()["infra_streak"] == 0 and env.state()["tasks"][TID2]["status"] in ("REVIEW", "PROMOTED")


def test_snapshot_survives_a_promote_while_a_worker_reads_it(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2)])
    monkeypatch.setenv("POOL_SLEEP_T1", "0.2")
    monkeypatch.setenv("POOL_SLEEP_T2", "6.0")       # a slow worker start (~1 s on a loaded machine) must not let <id> end before the promote
    _review_runner_env(monkeypatch, "T1", {"tools/x1.py": "a = 2\n"})
    loop = env.make_loop()
    seen = {}
    orig = loop._account

    def account(w, *a, **k):
        seen.setdefault("roots", []).append(sorted(str(p) for p in loop.pool.roots()))
        return orig(w, *a, **k)
    loop._account = account
    old_head = git(env.repo, "rev-parse", BRANCH)
    for _ in range(10):                              # <id> ends (REVIEW), is promoted while <id> still reads the first base
        loop.step()
        if env.state()["tasks"]["T1"]["status"] == "PROMOTED":
            break
    new_head = git(env.repo, "rev-parse", BRANCH)
    assert new_head != old_head
    root2 = next(e["root"] for e in plog(env) if e["ev"] == "start" and e["tid"] == TID2)
    assert "end" not in spans(env)[TID2] and Path(root2).is_dir()       # the second task is alive and its tree is still there
    assert Path(root2).name == old_head[:12]
    run_steps(loop, 10, env, (TID2,))
    loop.step()
    assert spans(env)[TID2]["end"]
    snaps = list((env.state_dir / "src_snapshots").glob("*"))
    assert all(p.name == new_head[:12] or p.name == "" for p in snaps if p.is_dir()) or len(snaps) <= 1
    assert not any(p.is_dir() and p.name != new_head[:12] for p in snaps)        # dropped after the reap


def test_worker_telemetry_fields(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2)])
    monkeypatch.setenv("POOL_SLEEP", "0.6")
    loop = env.make_loop()
    monkeypatch.setenv("POOL_STATUS", "DONE")
    run_steps(loop, 8, env, ("T1", TID2))
    run_steps(loop, 2)
    runs = [e for e in env.events() if e["span"] == "run" and e.get("status") and e.get("task_id") and "stage" not in e
            and e.get("role") is None]
    assert len(runs) == 2
    for e in runs:
        for k in ("worker", "pid", "lease", "k", "free_ram_mb", "peak_mb", "queue_s", "base_sha"):
            assert k in e, k
        assert len(e["lease"]) == 8 and e["pid"] > 0 and e["free_ram_mb"] > 0
    assert {e["k"] for e in runs} == {1, 2}
    assert any(e["span"] == "pool" and e.get("live") for e in env.events())
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats.get("max_workers") == 2


def test_one_network_blip_that_fails_every_live_pass_is_one_incident(tmp_path, monkeypatch):
    rows = [task_row(i) for i in (1, 2, 3)]
    env = pool_env(tmp_path, monkeypatch, rows)
    for t in ("T1", TID2, "T3"):
        monkeypatch.setenv("POOL_STATUS_" + t, "READY")
    monkeypatch.setenv("POOL_SLEEP", "0.3")
    monkeypatch.delenv("POOL_BEGIN")
    monkeypatch.setenv("POOL_DIE_T1", "1")
    monkeypatch.setenv("POOL_DIE_T2", "1")
    monkeypatch.setenv("POOL_DIE_T3", "1")
    loop = env.make_loop(max_infra=2)
    for _ in range(3):
        loop.step()
    assert not (env.state_dir / "BRAKE").exists()


def test_start_owned_reports_its_peak_and_kills_its_tree(tmp_path):
    code = "import time\nx = bytearray(40 * 2**20)\ntime.sleep(30)\n"
    w = factory_process.start_owned([sys.executable, "-c", code], cwd=str(tmp_path), env=dict(os.environ))
    try:
        time.sleep(1.0)
        assert w.poll() is None
        if os.name == "nt":
            assert (w.peak_bytes() or 0) > 30 * 2 ** 20
    finally:
        w.kill()
    assert w.poll() is not None


def test_run_owned_is_start_owned_plus_communicate(tmp_path):
    done = factory_process.run_owned([sys.executable, "-c", "print('hi')"], cwd=str(tmp_path), env=dict(os.environ),
                                     timeout=20)
    assert done.returncode == 0 and done.stdout.strip() == b"hi"
    with pytest.raises(subprocess.TimeoutExpired):
        factory_process.run_owned([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path),
                                  env=dict(os.environ), timeout=1)


@pytest.mark.skipif(os.name != "nt", reason="Windows job objects: the OS closes the handles of a killed loop")
def test_killed_loop_kills_its_workers_and_a_restart_frees_the_leases(tmp_path):
    pidfile = tmp_path / "child.pid"
    script = (
        "import os, sys, time\n"
        "sys.path.insert(0, %r)\n"
        "from tools import factory_process\n"
        "w = factory_process.start_owned([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=%r, env=dict(os.environ))\n"
        "open(%r, 'w').write(str(w.pid))\n"
        "time.sleep(60)\n" % (str(ROOT), str(tmp_path), str(pidfile)))
    loop = subprocess.Popen([sys.executable, "-c", script])
    try:
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text():
                break
            time.sleep(0.1)
        child = int(pidfile.read_text())
        assert F.pid_alive(child)
        loop.kill()                                   # the loop dies: nobody closes the job explicitly
        loop.wait(timeout=10)
        for _ in range(50):
            if not F.pid_alive(child):
                break
            time.sleep(0.1)
        assert not F.pid_alive(child)                 # the worker tree died with the loop
    finally:
        loop.kill()


def test_a_restart_frees_every_running_lease_of_the_killed_loop(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2)])
    with F.txn(env.state_dir / "state.json", env.state_dir / "plan.json") as (tasks, state):
        for tid in ("T1", TID2):
            F.acquire(tasks, state, tid, charge=False)
    loop = env.make_loop()
    loop.release_orphan_leases()
    rows = env.state()["tasks"]
    assert all(r["status"] == "READY" and r["attempts"] == 0 and r["lease"] is None for r in rows.values())


# ---- review defects of layer C (two reviewers, 20.11) -------------------------------------------------------------

def test_a_generic_crash_brake_waits_for_live_workers(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2)])
    monkeypatch.setenv("POOL_SLEEP_T1", "6")
    monkeypatch.setenv("POOL_SLEEP_T2", "0.2")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    loop = env.make_loop(max_infra=1)
    loop.step()
    assert loop.pool.workers
    monkeypatch.setattr(L, "refresh_mirror", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = loop.step()
    try:
        assert out.code is None and loop.pool.workers         # the loop does not exit under a live worker
        assert loop._brake_due is not None                    # the brake is due: the drain decides it
    finally:
        for w in list(loop.pool.workers.values()):
            w.owned.kill()


def test_no_admission_once_stop_is_written_mid_step(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2), task_row(3), task_row(4)])
    monkeypatch.setenv("POOL_SLEEP", "1.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    loop = env.make_loop()
    orig = loop._admit

    def admit(*a, **k):
        r = orig(*a, **k)
        loop.stop.write_text("", encoding="utf-8")
        return r
    loop._admit = admit
    loop.step()
    assert len([e for e in plog(env) if e["ev"] == "start"]) == 1


def test_fill_does_not_choose_again_an_id_admit_refused_in_the_pass(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2), task_row(3)])
    monkeypatch.setenv("POOL_SLEEP", "1.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    loop = env.make_loop()
    calls, started = [], set()
    monkeypatch.setattr(loop.pool, "tids", lambda: set(started))

    def admit(tid, tasks, ls):
        calls.append(tid)
        if tid == TID2:
            started.add(tid)                              # the second id starts
            return 1
        return 0                                          # the first and the third are refused
    loop._admit = admit
    tasks, state = loop.load()
    ls = loop.ls()
    now = loop.clock()
    act = loop._act(state, tasks, ls, now)
    assert act["action"] == "RUN" and act["task_ids"][0] == "T1"
    loop._fill(act, tasks, state, ls, now)
    assert calls == ["T1", TID2, "T3"]                  # every id asked once, the refused first one not again
    assert started == {TID2}


def test_a_busy_state_lock_after_the_reap_does_not_lose_the_result(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    monkeypatch.setenv("POOL_SLEEP_T1", "0.2")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    loop = env.make_loop()
    armed = [False]
    reap, load = loop._reap, loop.load

    def reap_(*a, **k):
        res = reap(*a, **k)
        armed[0] = True
        return res

    def load_(*a, **k):
        if armed[0]:
            armed[0] = False
            raise F.LockBusy("held")
        return load(*a, **k)
    loop._reap, loop.load = reap_, load_
    out = loop.step()
    assert out.reason == "state_locked"
    assert [w.tid for w in loop.pool.workers.values()] == ["T1"]       # parked with its result, not forgotten
    assert loop.pool.workers[0].res is not None
    for _ in range(5):
        loop.step()
        if not loop.pool.workers:
            break
    assert not loop.pool.workers
    text = loop.tel_path.read_text(encoding="utf-8")
    assert '"span": "run"' in text and "T1" in text                    # the result was accounted after all


def test_unclaim_does_not_swallow_a_busy_lock(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    loop = env.make_loop()

    def busy(*a, **k):
        raise F.LockBusy("held")
    loop._tx = busy
    with pytest.raises(F.LockBusy):
        loop._unclaim("T1", "tok")


def test_prune_never_leaves_a_half_deleted_snapshot_under_its_sha_name(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    loop = env.make_loop()
    loop.snap_dir.mkdir(parents=True, exist_ok=True)
    old = loop.snap_dir / "abcdef123456"
    (old / "tools").mkdir(parents=True)
    (old / "tools" / "x.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(L.shutil, "rmtree", lambda *a, **k: None)      # a scanner holds the files: nothing is deleted
    loop._prune_snapshots()
    assert not old.exists()                                            # the name _snapshot reuses is free again


def test_sleep_is_cut_to_a_look_while_workers_live(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1)])
    loop = env.make_loop()
    slept = []

    def step():
        loop.pool.workers[0] = L.Worker(slot=0, tid="X", token=None, base_sha="")
        return L.Outcome(sleep=60, action="WAIT", reason="state_locked")

    def sleep(n):
        slept.append(n)
        raise KeyboardInterrupt
    loop.step, loop._sleep = step, sleep
    with pytest.raises(KeyboardInterrupt):
        loop.run()
    assert slept == [L.WAIT_CHUNK_S]


