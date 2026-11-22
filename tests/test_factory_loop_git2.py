"""factory_loop: index.lock, restore after failures, mirror, base sha (git2 group)."""
import json
import os
import subprocess
import sys
import time

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, _stale_index_lock, Clock, git, task_row, env, empty_env, BRANCH, PY  # noqa: <id>


def head(env):
    return git(env.repo, "rev-parse", BRANCH)


def clean(env):
    return git(env.repo, "status", "--porcelain") == ""


def test_b_stale_index_lock_removed_and_retried(env, monkeypatch):
    monkeypatch.setattr(L, "git_running", lambda: False)
    lock = _stale_index_lock(env, 600)
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": head(env)})
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "PROMOTED"
    assert not lock.exists()


def test_c_mirror_swap_is_atomic(env, monkeypatch):
    loop = env.loop()
    loop.step()
    mirror = env.state_dir / "src_mirror"
    assert (mirror / "tools" / "x1.py").exists() and (mirror / ".factory_mirror").exists()
    (mirror / "stale_marker.txt").write_text("old", encoding="utf-8")
    (env.state_dir / "src_mirror.new").mkdir()  # leftover of a killed run
    (env.repo / "tools" / "x1.py").write_text("a = 5\n", encoding="utf-8")
    git(env.repo, "commit", "-qam", "move")
    import tarfile

    def broken(*a, **k):
        raise OSError("killed mid-extract")
    monkeypatch.setattr(tarfile.TarFile, "extractall", broken)
    env.loop().step()
    assert (mirror / "stale_marker.txt").exists()  # old mirror intact
    monkeypatch.undo()
    env.mp.setenv("FAKE_LOG", str(env.log))
    env.loop().step()
    assert not (mirror / "stale_marker.txt").exists()
    assert (mirror / "tools" / "x1.py").read_text(encoding="utf-8") == "a = 5\n"
    assert not (env.state_dir / "src_mirror.new").exists()


def test_d_base_sha_in_telemetry_and_checked(env):
    env.runner_says({"status": "REVIEW", "task": "T1", "calls": []})
    env.loop().step()
    run = [x for x in env.events() if x["span"] == "run"][-1]
    assert run["base_sha"] == head(env)
    loop_ev = env.loop_events()[-1]
    assert loop_ev["base_sha"] == head(env)
    ls = json.loads((env.state_dir / "loop_state.json").read_text(encoding="utf-8"))
    assert ls["bases"]["T1"] == head(env)




def test_failed_add_leaves_clean_tree_and_retry_merges(env, monkeypatch):
    monkeypatch.setattr(L, "git_running", lambda: True)  # the lock is "live": cannot be removed
    lock = _stale_index_lock(env, 600)
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": head(env)})
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "REVIEW"
    assert env.state()["infra_streak"] == 1
    assert git(env.repo, 'status', '--porcelain') == ''  # nothing of the package is left behind
    assert (env.repo / "tools" / "x1.py").read_text(encoding="utf-8") == "a = 1\n"
    lock.unlink()
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "PROMOTED"
    assert (env.repo / "tools" / "x1.py").read_text(encoding="utf-8") == "a = 2\n"


def test_failed_commit_new_file_is_removed(env, monkeypatch):
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": head(env)})
    real = L.git_run

    def flaky(cwd, *args, **kw):
        if "commit" in args:
            raise subprocess.CalledProcessError(1, "git commit", "", "boom")
        return real(cwd, *args, **kw)
    monkeypatch.setattr(L, "git_run", flaky)
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "REVIEW" and clean(env)
    monkeypatch.setattr(L, "git_run", real)
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "PROMOTED"


def test_dirt_only_in_package_files_does_not_block(env):
    (env.repo / "tools" / "x1.py").write_text("half-copied\n", encoding="utf-8")
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": head(env)})
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "PROMOTED"




def test_review_without_package_is_requeued_with_event(env):
    env.set_row("T1", status="REVIEW", attempts=1)       # nothing in stage/for-review/<id>
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "READY"
    assert env.state()["infra_streak"] == 0
    assert any(x["span"] == "promote" and x["status"] == "requeued"
               and x["reason"] == "no_package" for x in env.events())


# ---- worktree lock on a Cyrillic path (a Russian Windows), atomic owner ---------------------------

def test_worktree_lock_works_for_a_cyrillic_linked_worktree(tmp_path, monkeypatch):
    base = tmp_path / "Рабочая папка"
    base.mkdir()
    e = Env(base, monkeypatch, tasks=[task_row(1)])
    linked = base / "связанное дерево"
    git(e.repo, "worktree", "add", "-q", "-b", "other-branch", str(linked))
    cfg = L.Config(state_dir=e.state_dir, repo=e.repo, branch=BRANCH, worktree=linked,
                   backlog=e.backlog, channels=base / "c.json")
    loop = L.Loop(cfg, clock=e.clock.now, sleep=e.clock.sleep, power_fn=lambda f: None,
                  free_ram_fn=lambda: 2 ** 40)
    assert loop.acquire()
    try:
        locks = list((e.repo / ".git" / "worktrees").glob("*/factory_loop.lockdir"))
        assert len(locks) == 1 and (locks[0] / "owner").exists()   # a real lock, not a silent no-op
        assert not any(x.get("status") == "error" for x in e.events())
    finally:
        loop.release()
    assert not list((e.repo / ".git" / "worktrees").glob("*/factory_loop.lockdir"))


def test_young_empty_owner_counts_as_alive(env, tmp_path):
    lock = env.repo / ".git" / "factory_loop.lockdir"
    lock.mkdir()                                  # a lock being created right now: owner not yet written
    other = env.loop()
    assert other._lock_worktree() is False
    old = time.time() - 600
    os.utime(lock, (old, old))                    # abandoned long ago: taken over
    assert other._lock_worktree() is True
    other.release()


# ---- a deterministic package failure parks the task, an environment failure is infra ------------

def _review(env, tid="T1"):
    env.set_row(tid, status="REVIEW", attempts=1)
    env.package(tid, {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={tid: head(env)})
