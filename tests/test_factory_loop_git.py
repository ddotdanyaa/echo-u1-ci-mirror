"""factory_loop: promote, index.lock, mirror, base sha (git group)."""
import json
import os
import subprocess
import sys
import time

import pytest

from tools import agent_factory as F
from tools import factory_loop as L
from test_factory_loop import Env, _stale_index_lock, Clock, git, task_row, env, empty_env, BRANCH, PY  # noqa: <id>


# ---- PROMOTE ----------------------------------------------------------------------------

def head(env):
    return git(env.repo, "rev-parse", BRANCH)


def test_promote_success_commits_and_marks(env):
    base = head(env)
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": base})
    env.loop().step()
    st = env.state()
    assert st["tasks"]["T1"]["status"] == "PROMOTED"
    assert st["tasks"]["T1"]["commit"] == head(env)
    assert head(env) != base
    assert (env.repo / "tools" / "x1.py").read_text(encoding="utf-8") == "a = 2\n"
    assert "factory(T1)" in git(env.repo, "log", "-1", "--format=%s")
    assert env.runs() == 0
    assert any(x["span"] == "promote" and x["status"] == "promoted" for x in env.events())


def test_promote_head_moved_with_conflict_requeues(env):
    base = head(env)
    (env.repo / "tools" / "x1.py").write_text("a = 99\n", encoding="utf-8")
    git(env.repo, "commit", "-qam", "someone else")
    env.set_row("T1", status="REVIEW", attempts=1)
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": base})
    before = head(env)
    env.loop().step()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "READY"
    assert F.strikes_for(env.state(), "B1") == 0
    assert head(env) == before
    assert not (env.state_dir / "stage" / "for-review" / "T1").exists()
    assert env.state()["infra_streak"] == 0


def test_promote_head_moved_unrelated_files_merges(env):
    base = head(env)
    (env.repo / "tools" / "other.py").write_text("b = 2\n", encoding="utf-8")
    git(env.repo, "commit", "-qam", "unrelated")
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": base})
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "PROMOTED"
    assert (env.repo / "tools" / "other.py").read_text(encoding="utf-8") == "b = 2\n"


def test_promote_git_error_is_infra_and_task_stays_review(env):
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": head(env)})
    (env.repo / "tools" / "other.py").write_text("dirty\n", encoding="utf-8")  # dirty worktree
    before = head(env)
    env.loop().step()
    st = env.state()
    assert st["tasks"]["T1"]["status"] == "REVIEW"
    assert st["infra_streak"] == 1
    assert head(env) == before
    assert any(x["span"] == "infra" for x in env.events())


# ---- critic round 2: recovery, idempotency, scope, missing base ---------------------------

def clean(env):
    return git(env.repo, "status", "--porcelain") == ""


def test_commit_done_but_state_not_saved_is_idempotent(env):
    base = head(env)
    (env.repo / "tools" / "x1.py").write_text("a = 2\n", encoding="utf-8")
    git(env.repo, "commit", "-qam", "factory(T1): task 1")
    merged = head(env)
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": base})              # base differs from HEAD (own commit)
    env.loop().step()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "PROMOTED" and row["commit"] == merged
    assert head(env) == merged                          # no second commit


def test_package_outside_scope_is_refused(env):
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n", "tools/other.py": "evil = 1\n"})
    env.set_loop_state(bases={"T1": head(env)})
    before = head(env)
    env.loop().step()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "BLOCKED" and head(env) == before and clean(env)
    assert any(x["span"] == "promote" and x["status"] == "refused" for x in env.events())
    assert env.state()["infra_streak"] == 0


@pytest.mark.parametrize("bad", [".git/hooks/pre-commit", "tests/conftest.py",
                                 "tools/factory_gate.py"])
def test_forbidden_paths_are_refused(env, bad):
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    pkg = env.state_dir / "stage" / "for-review" / "T1"
    target = pkg / bad
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n", encoding="utf-8")
    env.set_loop_state(bases={"T1": head(env)})
    before = head(env)
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "BLOCKED"
    assert head(env) == before


def test_missing_base_record_requeues(env):
    env.set_row("T1", status="REVIEW", attempts=1)
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    before = head(env)
    env.loop().step()
    assert env.state()["tasks"]["T1"]["status"] == "READY"
    assert head(env) == before
    assert F.strikes_for(env.state(), "B1") == 0


# ---- critic round 3 -------------------------------------------------------------------------

def test_unit_test_kind_task_promotes_a_tests_file(tmp_path, monkeypatch):
    row = task_row(2, kind="unit_test", touch_files=["tests/test_x2.py"],
                   tests=["tests/test_x2.py"])
    e = Env(tmp_path, monkeypatch, tasks=[row])
    e.set_row("T%d" % 2, status="REVIEW")
    e.package("T%d" % 2, {"tests/test_x2.py": "def test_a():\n    assert 1\n"})
    e.set_loop_state(bases={"T%d" % 2: head(e)})
    e.loop().step()
    assert e.state()["tasks"]["T%d" % 2]["status"] == "PROMOTED"
    assert (e.repo / "tests" / "test_x2.py").exists()


def test_empty_diff_blocks_with_event_and_no_foreign_sha(env):
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 1\n"})        # identical to HEAD
    env.set_loop_state(bases={"T1": head(env)})
    before = head(env)
    env.loop().step()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "BLOCKED" and row["blocked_reason"] == "no_diff"
    assert "commit" not in row and head(env) == before
    assert any(x["span"] == "promote" and x["status"] == "no_diff" and x["reason"] == "no_diff" for x in env.events())


def test_idempotency_looks_at_the_subject_only(env):
    base = head(env)
    (env.repo / "tools" / "other.py").write_text("b = 7\n", encoding="utf-8")
    git(env.repo, "commit", "-qam", "unrelated\n\nmentions factory(T1): in the body only")
    env.set_row("T1", status="REVIEW")
    env.package("T1", {"tools/x1.py": "a = 2\n"})
    env.set_loop_state(bases={"T1": base})
    env.loop().step()
    row = env.state()["tasks"]["T1"]
    assert row["status"] == "PROMOTED" and row["commit"] == head(env)
    assert "factory(T1)" in git(env.repo, "log", "-1", "--format=%s")
