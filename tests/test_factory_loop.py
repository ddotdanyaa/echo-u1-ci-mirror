"""tools/factory_loop.py: the single continuous loop (pack D). No models, no sleep, no network.

The runner is a tiny python script that prints a JSON line; time and sleep are fakes; promote
works on a throw-away git repository.
"""
import json
import os
import shutil
import subprocess
import tempfile
import sys
import time
from pathlib import Path

import pytest

from tools import agent_factory as F
from tools import factory_loop as L

PY = sys.executable
BRANCH = "factory/test"

FAKE_RUNNER = """\
import os, sys
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + " KEY=" + os.environ.get("GEMINI_FAKE", "") + "\\n")
if os.environ.get("FAKE_SLEEP"):
    import time; time.sleep(float(os.environ["FAKE_SLEEP"]))
out = os.environ.get("FAKE_OUT", "")
if out:
    print(open(out, encoding="utf-8").read().strip())
sys.exit(int(os.environ.get("FAKE_RC", "0")))
"""


class Clock:
    def __init__(self):
        self.t = time.time()
        self.sleeps = []
        self.on_sleep = None

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s
        if self.on_sleep:
            self.on_sleep(s)


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout.strip()


_TEMPLATE = []


def template_repo() -> Path:
    """One git init + commit per test process; every test gets a cheap copy."""
    if not _TEMPLATE:
        root = Path(tempfile.mkdtemp(prefix="factory_loop_tpl_")) / "repo"
        root.mkdir()
        git(root, "init", "-q", "-b", BRANCH)
        git(root, "config", "user.name", "t")
        git(root, "config", "user.email", "t@example.com")   # an RFC 2606 name: the public mirror publishes it
        (root / "tools").mkdir()
        (root / "tools" / "x1.py").write_text("a = 1\n", encoding="utf-8")
        (root / "tools" / "other.py").write_text("b = 1\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        _TEMPLATE.append(root)
    return _TEMPLATE[0]


def task_row(i, **kw):
    row = {"id": "T%d" % i, "title": "task %d" % i, "touch_files": ["tools/x%d.py" % i],
           "tests": ["tests/test_x%d.py" % i], "privacy_safe": True, "estimated_tokens": 100,
           "backlog_id": "B%d" % i}
    row.update(kw)
    return row


class Env:
    def __init__(self, tmp_path, monkeypatch, tasks=()):
        self.tmp = tmp_path
        self.state_dir = tmp_path / "state"
        self.state_dir.mkdir()
        self.repo = tmp_path / "repo"
        shutil.copytree(template_repo(), self.repo)
        self.backlog = tmp_path / "BACKLOG.md"
        self.backlog.write_text("# backlog\n", encoding="utf-8")
        (self.state_dir / "plan.json").write_text(json.dumps({"tasks": list(tasks)}),
                                                  encoding="utf-8")
        self.script = tmp_path / "fake_runner.py"
        self.script.write_text(FAKE_RUNNER, encoding="utf-8")
        self.log = tmp_path / "runner.log"
        self.out = tmp_path / "out.json"
        monkeypatch.setenv("FAKE_LOG", str(self.log))
        monkeypatch.setenv("FAKE_OUT", str(self.out))
        monkeypatch.delenv("FAKE_RC", raising=False)
        monkeypatch.delenv("FAKE_SLEEP", raising=False)
        self.clock = Clock()
        self.mp = monkeypatch

    def runner_says(self, obj):
        self.out.write_text(json.dumps(obj), encoding="utf-8")

    def loop(self, triage_fn=None, extra=None, rng=None, **over):
        extra = dict(extra or {})
        if rng is not None:
            extra["rng"] = rng
        cfg = L.Config(state_dir=self.state_dir, repo=self.repo, branch=BRANCH,
                       worktree=self.repo, backlog=self.backlog,
                       channels=self.tmp / "channels.json", **over)
        self.power = []
        kw = dict(triage_fn=triage_fn, runner_cmd=[PY, "-S", str(self.script)],
                  clock=self.clock.now, sleep=self.clock.sleep,
                  power_fn=self.power.append, free_ram_fn=lambda: 8 * 2 ** 30)
        kw.update(extra)
        return L.Loop(cfg, **kw)

    def runs(self):
        return len(self.log.read_text(encoding="utf-8").splitlines()) if self.log.exists() else 0

    def events(self):
        path = self.state_dir / "telemetry.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]

    def loop_events(self):
        return [e for e in self.events() if e["span"] == "loop"
                and e.get("action") not in ("START", "EXIT")]

    def state(self):
        data = json.loads((self.state_dir / "plan.json").read_text(encoding="utf-8"))
        tasks = F.read_plan(data)
        return F.load_state(self.state_dir / "state.json", tasks)

    def set_row(self, tid, **row):
        data = json.loads((self.state_dir / "plan.json").read_text(encoding="utf-8"))
        st = F.load_state(self.state_dir / "state.json", F.read_plan(data))
        st["tasks"][tid].update(row)
        F.save_atomic(self.state_dir / "state.json", st)

    def package(self, tid, files):
        for name, text in files.items():
            dst = self.state_dir / "stage" / "for-review" / tid / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")

    def set_loop_state(self, **kw):
        (self.state_dir / "loop_state.json").write_text(json.dumps(kw), encoding="utf-8")


def _stale_index_lock(env, age):
    lock = env.repo / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - age
    os.utime(lock, (old, old))
    return lock


def two_tasks(tmp_path, monkeypatch, n=2):
    return Env(tmp_path, monkeypatch, tasks=[task_row(i) for i in range(1, n + 1)])


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch, tasks=[task_row(1)])


@pytest.fixture
def empty_env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch, tasks=[])


# ---- triage instead of IDLE -------------------------------------------------------------

def test_empty_queue_with_backlog_triages_not_idles(empty_env):
    e = empty_env
    calls = []

    def triage(backlog_path, head_root, known_backlog_ids, limit):
        calls.append((Path(backlog_path), Path(head_root), set(known_backlog_ids), limit))
        return {"tasks": [task_row(7)], "holds": [{"backlog_id": "B9", "question": "split it?"}],
                "stale": [], "skipped": []}

    loop = e.loop(triage_fn=triage)
    assert loop.step().code is None
    assert calls == [(e.backlog, e.repo, set(), 5)]
    plan = json.loads((e.state_dir / "plan.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in plan["tasks"]] == ["T7"]
    assert "B9" in (e.state_dir / "opus_questions.md").read_text(encoding="utf-8")
    acts = [x["action"] for x in e.loop_events()]
    assert "TRIAGE" in acts and "DONE" not in acts


def test_empty_portion_stops_triage_until_backlog_changes(empty_env):
    e = empty_env
    n = []

    def triage(**kw):
        n.append(1)
        return {"tasks": [], "holds": [], "stale": [], "skipped": []}

    loop = e.loop(triage_fn=triage)
    loop.step()
    loop.step()
    assert len(n) == 1
    assert [x["action"] for x in e.loop_events()] == ["TRIAGE", "DONE"]
    # backlog changes -> triage again
    time.sleep(0.02)
    e.backlog.write_text("# backlog\nnew\n", encoding="utf-8")
    os.utime(e.backlog, (time.time() + 5, time.time() + 5))
    loop.step()
    assert len(n) == 2


def test_triage_stub_not_implemented_means_no_more(empty_env):
    e = empty_env

    def triage(**kw):
        raise NotImplementedError("stub")

    loop = e.loop(triage_fn=triage)
    out = loop.step()
    assert out.code is None
    ev = [x for x in e.events() if x["span"] == "triage"]
    assert ev and "not_implemented" in ev[-1]["reason"]
    loop.step()
    assert e.loop_events()[-1]["action"] == "DONE"
    assert e.state()["infra_streak"] == 0


def test_known_backlog_ids_come_from_state(env):
    got = []

    def triage(backlog_path, head_root, known_backlog_ids, limit):
        got.append(set(known_backlog_ids))
        return {"tasks": [], "holds": [], "stale": [], "skipped": []}

    env.set_row("T1", status="DONE")
    env.loop(triage_fn=triage).step()
    assert got == [{"B1"}]


# ---- RUN / channel ----------------------------------------------------------------------

def test_run_calls_runner_and_records_tokens(env):
    env.runner_says({"status": "READY", "task": "T1", "calls": [
        {"model": "m/x", "input_tokens": 10, "output_tokens": 3, "elapsed_seconds": 2.0}]})
    loop = env.loop()
    loop.step()
    assert env.runs() == 1
    args = env.log.read_text(encoding="utf-8")
    assert "--execute" in args and "--max-tasks 1" in args
    run = [x for x in env.events() if x["span"] == "run"][-1]
    assert run["task_id"] == "T1" and run["backlog_id"] == "B1"
    assert run["tokens_in"] == 10 and run["tokens_out"] == 3 and run["model"] == "m/x"
    stats = json.loads((env.state_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["tokens_in"] == 10 and stats["tokens_out"] == 3


def test_waiting_channel_leads_to_wait_not_infra(env):
    env.runner_says({"status": "WAITING_CHANNEL", "task": "T1"})
    loop = env.loop()
    loop.step()
    out = loop.step()
    assert env.runs() == 1
    assert env.loop_events()[-1]["action"] == "WAIT"
    assert 0 < out.sleep <= 60
    assert env.state()["infra_streak"] == 0


# ---- brake ------------------------------------------------------------------------------

def test_brake_file_blocks_start_until_cleared(env):
    (env.state_dir / "BRAKE").write_text("brake: test\n", encoding="utf-8")
    assert env.loop().run() == 3
    assert env.runs() == 0
    assert any(x.get("reason") == "brake_active" for x in env.events())


# ---- STOP / until / once ----------------------------------------------------------------

def test_stop_file_exits_zero_without_work(env):
    (env.state_dir / "STOP").write_text("x", encoding="utf-8")
    assert env.loop().run() == 0
    assert env.runs() == 0


def test_until_deadline_exits_zero(env):
    import datetime as dt
    until = dt.datetime.fromtimestamp(env.clock.t - 5)
    assert env.loop(until=until).run() == 0
    assert env.runs() == 0


def test_once_runs_one_iteration(env):
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    assert env.loop(once=True).run() == 0
    assert env.runs() == 1
    assert len(env.loop_events()) == 1
    assert not (env.state_dir / "loop.pid").exists()


# ---- single instance --------------------------------------------------------------------

def test_second_instance_refuses(env):
    (env.state_dir / "loop.pid").write_text(str(os.getpid()), encoding="utf-8")
    assert env.loop(once=True).run() == 4
    assert env.runs() == 0
    assert (env.state_dir / "loop.pid").read_text(encoding="utf-8") == str(os.getpid())


def test_dead_pid_is_removed_and_loop_starts(env):
    p = subprocess.Popen([PY, "-c", "pass"])
    p.wait()
    (env.state_dir / "loop.pid").write_text(str(p.pid), encoding="utf-8")
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    assert env.loop(once=True).run() == 0
    assert env.runs() == 1
    assert any(x["span"] == "infra" and x.get("reason") == "stale_pid" for x in env.events())


def test_pid_alive_helper():
    p = subprocess.Popen([PY, "-c", "pass"])
    p.wait()
    assert L.pid_alive(os.getpid()) is True
    assert L.pid_alive(p.pid) is False


def test_stale_runner_lockdir_is_removed_at_start(env):
    lock = env.state_dir / "state.json.lockdir"
    lock.mkdir()
    old = time.time() - 99999
    os.utime(lock, (old, old))
    env.runner_says({"status": "READY", "task": "T1", "calls": []})
    env.loop(once=True).run()
    assert not lock.exists()
    assert any(x.get("reason") == "stale_lockdir" for x in env.events())


# ---- telemetry --------------------------------------------------------------------------
