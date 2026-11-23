"""The second instance merges factory/ready-* into its own branch (three-way) at the start and hourly with nothing RUNNING;
a conflict is aborted and reported as one line, the work goes on."""
import subprocess

from tests.test_factory_loop import BRANCH, Env

READY = "factory/ready-sync"


def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo, branch, name, text):
    _git(repo, "checkout", "-q", branch)
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "change " + name)


def _two_branches(repo):
    """BRANCH stays checked out; READY forks from its current head."""
    _git(repo, "branch", READY, BRANCH)
    _git(repo, "checkout", "-q", BRANCH)


def _syncs(e):
    return [x for x in e.events() if x["span"] == "sync"]


def test_the_ready_branch_is_merged_three_way_at_the_start_and_not_again_within_the_hour(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    _two_branches(e.repo)
    _commit(e.repo, READY, "from_ready.txt", "ready\n")
    _commit(e.repo, BRANCH, "from_self.txt", "self\n")        # both moved: a real merge commit, not a fast-forward
    loop = e.loop(self_repo=True, sync_ref=READY)
    assert loop._sync_ready_tick(loop.clock()) == "merged"
    assert (e.repo / "from_ready.txt").is_file() and (e.repo / "from_self.txt").is_file()
    assert len(_git(e.repo, "log", "-1", "--format=%P").split()) == 2
    assert loop._sync_ready_tick(loop.clock()) == ""            # inside the hour: nothing
    e.clock.sleep(3601)
    assert loop._sync_ready_tick(loop.clock()) == "up_to_date"
    assert [x["status"] for x in _syncs(e)] == ["merged", "up_to_date"]


def test_a_conflict_is_aborted_and_becomes_one_line_the_tree_stays_clean(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    _two_branches(e.repo)
    _commit(e.repo, READY, "shared.txt", "ready side\n")
    _commit(e.repo, BRANCH, "shared.txt", "self side\n")
    head = _git(e.repo, "rev-parse", "HEAD")
    loop = e.loop(self_repo=True, sync_ref=READY)
    assert loop._sync_ready_tick(loop.clock()) == "conflict"
    assert _git(e.repo, "rev-parse", "HEAD") == head and _git(e.repo, "status", "--porcelain", "--untracked-files=no") == ""
    row = _syncs(e)[0]
    assert row["status"] == "conflict" and "shared.txt" in row["reason"] and READY in row["reason"]


def test_the_quarantine_of_the_second_instance_opens_by_itself_with_slicer_one_point_three(tmp_path, monkeypatch):
    from tools import agent_factory as F
    from tests.test_factory_loop import task_row
    from tools import factory_architect as A
    assert A.CONTRACT_REV == "1.3"
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1, backlog_id="fac-1"), task_row(3, backlog_id="fac-3")])
    e.set_row("T1", status="FAILED", reason="quarantine", q_ver="s0old")      # shelved by the slicer of before
    e.set_row("T3", status="FAILED", reason="quarantine", q_ver=F.slicer_version())     # shelved by this one: stays
    loop = e.loop(self_repo=True)
    ls = loop.ls()
    ls["quarantine"] = {"fac-5": {"version": "s0old", "at": 0.0, "why": "reslice budget exhausted"}}
    loop.save_ls(ls)
    assert loop._reenter_on_new_slicer() == 2                                # fac-1 by its task, fac-5 by its row record
    st = e.state()["tasks"]
    assert st["T1"]["reason"] == "reenter" and st["T3"]["reason"] == "quarantine"
    assert "fac-5" in loop.ls()["to_slice"] and "fac-5" not in loop.ls()["quarantine"]
    assert loop._reenter_on_new_slicer() == 0                                # nothing is given back twice


def test_a_running_task_a_missing_ref_and_the_product_instance_are_left_alone(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    loop = e.loop(self_repo=True, sync_ref="factory/no-such-branch")
    assert loop._sync_ready_tick(loop.clock()) == "skipped"
    assert _syncs(e)[-1]["status"] == "skipped"
    other = e.loop(self_repo=True, sync_ref="")
    assert other._sync_ready_tick(other.clock()) == ""
    assert e.loop().cfg.self_repo is False       # _step calls the tick only for the second instance
