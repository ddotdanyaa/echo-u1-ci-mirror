"""Promote is a 3-way merge, not a blind copy (owner barriers 49/50/63/64): independent candidates are kept without a
re-gate, an overlapping one goes back with the merge verdict as feedback, a known-good tag marks the pre-promote HEAD."""
import json

from tools import factory_loop as L
from test_factory_loop import git, BRANCH
from test_factory_pool_loop import pool_env, plog, _review_runner_env


def test_three_way_merges_different_lines_and_flags_the_same_line():
    base = "a = 1\nb = 2\nc = 3\n"
    assert L.three_way_merge(base, "a = 9\nb = 2\nc = 3\n", "a = 1\nb = 2\nc = 7\n") == ("a = 9\nb = 2\nc = 7\n", False)
    assert L.three_way_merge(base, base, "a = 5\nb = 2\nc = 3\n") == ("a = 5\nb = 2\nc = 3\n", False)
    text, conflict = L.three_way_merge(base, "a = 9\nb = 2\nc = 3\n", "a = 8\nb = 2\nc = 3\n")
    assert conflict is True


def _two_on_one_file(env, monkeypatch, ours_text, theirs_text):
    """Real Loop promote path; while the candidate waits for its promote a foreign commit edits the same file."""
    repo = env.repo
    (repo / "tools" / "shared.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "shared")
    rows = [{"id": "TX", "title": "x", "touch_files": ["tools/shared.py"], "tests": ["tests/test_x.py"],
             "privacy_safe": True, "estimated_tokens": 100, "backlog_id": "BTX"}]
    (env.state_dir / "plan.json").write_text(json.dumps({"tasks": rows}), encoding="utf-8")
    _review_runner_env(monkeypatch, "TX", {"tools/shared.py": theirs_text})
    loop = env.make_loop()
    orig = loop._promote

    def racing(tid, tasks, state, ls):
        if not git(repo, "log", "--format=%s", "-1").startswith("foreign"):
            (repo / "tools" / "shared.py").write_text(ours_text, encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "foreign edit")
        return orig(tid, tasks, state, ls)
    loop._promote = racing
    for _ in range(6):
        loop.step()
        if any(e["span"] == "promote" for e in env.events()):
            break
    allp = [e for e in env.events() if e["span"] == "promote"]
    pro = [e for e in allp if e["status"] == "requeued"]
    assert pro, [(e["task_id"], e["status"], e["reason"]) for e in allp]
    row = env.state()["tasks"]["TX"]
    return pro, " ".join(f["text"] for f in row.get("feedback", []))


def test_same_file_clean_merge_goes_back_to_the_gate_with_the_verdict(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [])
    pro, fb = _two_on_one_file(env, monkeypatch, "a = 9\nb = 2\nc = 3\n", "a = 1\nb = 2\nc = 7\n")
    assert pro[0]["status"] == "requeued" and pro[0]["reason"] == "base_moved"
    assert "3-way" in fb and "чисто" in fb


def test_same_file_conflict_goes_back_with_the_conflict_as_feedback(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [])
    pro, fb = _two_on_one_file(env, monkeypatch, "a = 9\nb = 2\nc = 3\n", "a = 8\nb = 2\nc = 3\n")
    assert pro[0]["status"] == "requeued"
    assert "3-way" in fb and "конфликт" in fb


def test_independent_files_are_kept_without_a_regate_and_known_good_tag_is_set(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [])
    repo = env.repo
    rows = [{"id": tid, "title": tid, "touch_files": ["tools/%s.py" % tid.lower()], "tests": ["tests/test_%s.py" % tid.lower()],
             "privacy_safe": True, "estimated_tokens": 100, "backlog_id": "B" + tid} for tid in ("TY", "TX")]
    (env.state_dir / "plan.json").write_text(json.dumps({"tasks": rows}), encoding="utf-8")
    monkeypatch.setenv("POOL_SLEEP_TY", "0.3")
    monkeypatch.setenv("POOL_SLEEP_TX", "0.8")
    _review_runner_env(monkeypatch, "TY", {"tools/ty.py": "v = 1\n"})
    _review_runner_env(monkeypatch, "TX", {"tools/tx.py": "w = 1\n"})
    loop = env.make_loop()
    for _ in range(8):
        loop.step()
        if all(r["status"] == "PROMOTED" for r in env.state()["tasks"].values()):
            break
    assert all(r["status"] == "PROMOTED" for r in env.state()["tasks"].values())
    assert len([e for e in plog(env) if e["ev"] == "start" and e["tid"] == "TX"]) == 1     # never re-gated
    subjects = git(repo, "log", "--format=%s", BRANCH).splitlines()
    last = git(repo, "rev-parse", BRANCH)
    assert git(repo, "rev-parse", "factory/known-good") == git(repo, "rev-parse", last + "~1")
    assert sum(1 for s in subjects if s.startswith("factory(")) == 2

