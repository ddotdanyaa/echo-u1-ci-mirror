"""W-bisect: the deterministic proof of what turned a baseline test red (checkpoints, halving, restart, kinds, the clue)."""
import json
import shutil

from tools import factory_bisect as BIS
from tools import factory_release as REL


def _shas(n):
    return ["%040x" % (i + 1) for i in range(n)]


class World:
    """A fake history and a fake cloud: ``tests`` = {name: (appears at index, red from index or None)}; one file per test."""

    def __init__(self, tmp_path, n, tests):
        self.n, self.shas, self.tests, self.tmp = n, _shas(n), tests, tmp_path
        self.calls, self.resumed, self.pending, self.crash_after = [], [], {}, None
        self.by_file = {self._file(t): [t] for t in tests}

    @staticmethod
    def _file(name):
        return name.split("::")[0]

    def snapshot(self, sha):
        i = self.shas.index(sha)
        root = self.tmp / "snaps" / sha
        for name, (appears, _red) in self.tests.items():
            if i >= appears:
                path = root / self._file(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("def %s():\n    pass\n" % name.split("::")[1], encoding="utf-8")
        root.mkdir(parents=True, exist_ok=True)
        (root / ".sha").write_text(sha, encoding="utf-8")
        return root

    def free(self, path):
        shutil.rmtree(path, ignore_errors=True)

    def _results(self, sha, files):
        i = self.shas.index(sha)
        out = {}
        for f in files:
            red = [t for t in self.by_file[f] if self.tests[t][1] is not None and i >= self.tests[t][1]]
            out[f] = {"passed": 1, "failed": len(red), "errors": 0, "failed_ids": red, "skipped": 0, "seconds": 1.0}
        return out

    def sweep(self, src=None, files=None, shards=1, label=None, wait_s=None, durations_path=None, on_run=None, resume=None):
        if resume:
            self.resumed.append(resume["run_id"])
            sha, files = self.pending.pop(resume["run_id"])
            return "r.json", self._results(sha, files), resume["run_id"]
        sha = (src / ".sha").read_text(encoding="utf-8")
        present = [f for f in files if (src / f).is_file()]
        assert present == list(files)                       # only the files the commit has are run
        self.calls.append((sha, list(files)))
        run_id = 1000 + len(self.calls)
        self.pending[run_id] = (sha, list(files))
        if on_run:
            on_run({"run_id": run_id, "branch": "b%d" % run_id, "shards": 1})
        if self.crash_after is not None and len(self.calls) >= self.crash_after:
            self.crash_after = None
            raise RuntimeError("the loop died")
        self.pending.pop(run_id)
        return "r.json", self._results(sha, files), run_id

    def diff(self, a, b):
        return ["tools/x.py"], "diff --git a/tools/x.py b/tools/x.py\n--- a/tools/x.py\n+++ b/tools/x.py\n@@ -1,2 +1,2 @@ def f():\n-old\n+new\n"

    def step(self, state_dir, **kw):
        return BIS.step(state_dir=state_dir, sweep_fn=self.sweep, snapshot_fn=self.snapshot, free_fn=self.free, diff_fn=self.diff,
                        commits=self.shas, tests_by_file=self.by_file, **kw)

    def run_all(self, state_dir, limit=80):
        for _ in range(limit):
            out = self.step(state_dir)
            if not out["more"]:
                return out
        raise AssertionError("does not end")


def test_plan_has_the_root_the_base_and_ten_even_points_between():
    commits = _shas(1211)
    points = BIS.plan({"tests/test_a.py": ["tests/test_a.py::test_one"]}, commits)["points"]
    assert len(points) == 12 and points[0] == commits[0] and points[-1] == commits[-1]
    assert points == sorted(points, key=commits.index) and len(set(points)) == 12
    gaps = [commits.index(b) - commits.index(a) for a, b in zip(points, points[1:])]
    assert max(gaps) - min(gaps) <= 1                         # even
    assert BIS.plan({}, _shas(5))["points"] == _shas(5)       # a short history: no repeats
    assert BIS.plan({}, _shas(1))["points"] == _shas(1) and BIS.plan({}, [])["points"] == []


def test_history_is_the_first_parent_chain_from_the_root():
    seen = []

    def git(*args):
        seen.append(args)
        if args[0] == "rev-parse":
            return "aaa\n"
        return "bbb\nccc\n"
    assert BIS.history(git, "ddd") == ["aaa", "bbb", "ccc"]
    assert seen[1] == ("rev-list", "--first-parent", "--reverse", "aaa..ddd")

    def lost(*args):
        if args[0] == "rev-parse":
            raise RuntimeError("unknown revision")
        return "x1\nx2\n"
    assert BIS.history(lost, "ddd") == ["x1", "x2"]


def test_a_regression_is_narrowed_by_shared_halving_to_a_single_commit(tmp_path):
    w = World(tmp_path, 40, {"tests/test_a.py::test_one": (0, 23), "tests/test_b.py::test_two": (0, 24)})
    state = tmp_path / "state"
    w.run_all(state)
    res = BIS.load(state)["result"]
    a, b = res["tests/test_a.py::test_one"], res["tests/test_b.py::test_two"]
    assert a["kind"] == "regression" and a["single"] and a["red"] == w.shas[23] and a["green"] == w.shas[22]
    assert b["single"] and b["red"] == w.shas[24]
    plan_calls = [c for c in w.calls if len(c[1]) == 2]
    assert len(w.calls) <= 12 + 2 * BIS.REFINE_STEPS
    assert all(set(files) == {"tests/test_a.py", "tests/test_b.py"} for _sha, files in plan_calls)   # the whole batch on every point
    assert BIS.counts(state) == {"done": 2, "regression": 2, "never_green": 0, "moved": 0}


def test_one_point_per_step_serves_every_test_of_the_segment(tmp_path):
    w = World(tmp_path, 400, {"tests/test_a.py::test_one": (0, 301), "tests/test_b.py::test_two": (0, 305)})
    state = tmp_path / "state"
    w.run_all(state)
    points = BIS.load(state)["points"]
    refine = [c for c in w.calls if c[0] not in points]
    assert 1 <= len(refine) <= BIS.REFINE_STEPS + 1
    assert any(set(files) == {"tests/test_a.py", "tests/test_b.py"} for _sha, files in refine)     # one run, two tests
    res = BIS.load(state)["result"]
    for name, red in (("tests/test_a.py::test_one", 301), ("tests/test_b.py::test_two", 305)):
        r = res[name]
        assert r["kind"] == "regression" and r["g"] < red <= r["r"]                 # the real commit is inside the segment
        assert r["steps"] <= BIS.REFINE_STEPS


def test_never_green_and_moved_and_green_now(tmp_path):
    w = World(tmp_path, 40, {"tests/test_a.py::test_one": (0, 0),          # red since the first commit
                             "tests/test_b.py::test_two": (17, 17),        # appears already red
                             "tests/test_c.py::test_three": (0, None)})    # green everywhere
    state = tmp_path / "state"
    w.run_all(state)
    res = BIS.load(state)["result"]
    assert res["tests/test_a.py::test_one"]["kind"] == "never_green"
    assert res["tests/test_b.py::test_two"]["kind"] == "moved"
    assert res["tests/test_c.py::test_three"]["kind"] == "green"
    assert BIS.counts(state) == {"done": 3, "regression": 0, "never_green": 1, "moved": 1}


def test_a_test_with_no_file_at_a_commit_is_absent_not_green(tmp_path):
    w = World(tmp_path, 12, {"tests/test_a.py::test_one": (6, 9)})
    state = tmp_path / "state"
    w.run_all(state)
    marks = BIS.load(state)["marks"]
    assert marks[w.shas[0]]["tests/test_a.py::test_one"] == "n"
    assert all(files for _sha, files in w.calls)           # a point where nothing exists is not run at all


def test_a_restart_goes_on_from_the_book_and_waits_for_the_run_in_flight(tmp_path):
    w = World(tmp_path, 40, {"tests/test_a.py::test_one": (0, 23)})
    state = tmp_path / "state"
    w.step(state)
    w.step(state)
    done_before = len(w.calls)
    w.crash_after = done_before + 1
    try:
        w.step(state)
    except RuntimeError:
        pass
    book = json.loads((state / "release" / "bisect.json").read_text(encoding="utf-8"))
    assert book["run"]["info"]["run_id"] == 1000 + done_before + 1          # the run is written the moment it exists
    out = w.step(state)                                                     # a new process: picks the run up, publishes nothing
    assert w.resumed == [1000 + done_before + 1] and len(w.calls) == done_before + 1 and out["status"] == "point"
    w.run_all(state)
    seen = [sha for sha, _f in w.calls]
    assert len(seen) == len(set(seen))                                      # no point is run twice
    assert BIS.load(state)["result"]["tests/test_a.py::test_one"]["single"]


def test_a_blocked_or_failing_point_gets_the_mark_u_and_the_work_goes_on(tmp_path):
    w = World(tmp_path, 12, {"tests/test_a.py::test_one": (0, 5)})
    state = tmp_path / "state"

    class Blocked(Exception):
        pass
    real, first = w.sweep, []

    def sweep(src=None, **kw):
        if src is not None and not first:
            first.append(1)
            raise Blocked("secret")
        return real(src=src, **kw)
    out = BIS.step(state_dir=state, sweep_fn=sweep, snapshot_fn=w.snapshot, free_fn=w.free, diff_fn=w.diff, commits=w.shas,
                   tests_by_file=w.by_file)
    assert out["reason"] == "blocked" and out["more"]
    marks = BIS.load(state)["marks"]
    assert list(marks[w.shas[-1]].values()) == ["u"]
    w.run_all(state)
    assert BIS.counts(state)["done"] == 1


def test_a_failing_run_is_repeated_and_given_up_after_three_tries(tmp_path):
    w = World(tmp_path, 12, {"tests/test_a.py::test_one": (0, 5)})
    state = tmp_path / "state"

    def sweep(src=None, **kw):
        raise OSError("cloud down")
    for _ in range(BIS.TRIES - 1):
        try:
            BIS.step(state_dir=state, sweep_fn=sweep, snapshot_fn=w.snapshot, free_fn=w.free, commits=w.shas, tests_by_file=w.by_file)
        except OSError:
            pass
        assert not BIS.load(state)["marks"]
    try:
        BIS.step(state_dir=state, sweep_fn=sweep, snapshot_fn=w.snapshot, free_fn=w.free, commits=w.shas, tests_by_file=w.by_file)
    except OSError:
        pass
    assert list(BIS.load(state)["marks"][w.shas[-1]].values()) == ["u"]


DIFF = """diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1,2 +1,2 @@ def test_x():
-a
+b
diff --git a/tools/other.py b/tools/other.py
--- a/tools/other.py
+++ b/tools/other.py
@@ -1,2 +1,2 @@ def helper():
-old_helper
+new_helper
diff --git a/tools/core.py b/tools/core.py
--- a/tools/core.py
+++ b/tools/core.py
@@ -9,2 +9,2 @@ def traced_function(x):
-return x
+return x + 1
"""


def test_the_diff_puts_the_functions_of_the_trace_and_the_contract_first_and_fits_the_cap():
    text = BIS.order_diff(DIFF, {"traced_function"})
    assert text.index("traced_function") < text.index("helper") < text.index("test_x")
    assert text.count("diff --git") == 3 and "+++ b/tools/core.py" in text
    by_contract = BIS.order_diff(DIFF, BIS._symbols([json.dumps({"parts": [{"file": "tools/other.py", "symbols": ["helper"]}]})]))
    assert by_contract.index("helper") < by_contract.index("traced_function")
    big = DIFF + "".join("diff --git a/tools/f%d.py b/tools/f%d.py\n@@ -1 +1 @@\n-%s\n+%s\n" % (i, i, "x" * 300, "y" * 300) for i in range(60))
    cut = BIS.order_diff(big, {"traced_function"})
    assert len(cut) <= BIS.DIFF_CHARS and cut.index("traced_function") < 400 and "[...cut]" in cut


def test_the_clue_carries_the_proof_and_stays_within_the_cap(tmp_path):
    w = World(tmp_path, 40, {"tests/test_a.py::test_one": (0, 23), "tests/test_b.py::test_two": (0, None)})
    state = tmp_path / "state"
    w.run_all(state)
    got = BIS.clue(state, ["tests/test_b.py::test_two", "tests/test_a.py::test_one"], trace=[("tools/x.py", "f", 3)])
    assert got["test"] == "tests/test_a.py::test_one" and got["key"] == "%s..%s" % (w.shas[22][:12], w.shas[23][:12])
    assert "was green before commit %s" % w.shas[23][:12] in got["text"] and "restore the earlier behaviour without breaking the new" in got["text"]
    assert "Files changed: tools/x.py" in got["text"] and "+new" in got["text"] and len(got["text"]) < BIS.DIFF_CHARS + 600
    assert BIS.clue(state, ["tests/test_b.py::test_two"]) is None


def _debt(state, rows):
    REL._write_json(state / "release" / REL.DEBT_FILE, rows)


def test_row_kinds_and_rank_follow_the_guard_test(tmp_path):
    w = World(tmp_path, 40, {"tests/test_a.py::test_one": (0, 23), "tests/test_b.py::test_two": (0, 0),
                             "tests/test_c.py::test_three": (17, 17)})
    state = tmp_path / "state"
    w.run_all(state)
    _debt(state, {"tests/test_a.py": {"tests": ["tests/test_a.py::test_one"], "queued": True, "n": 1, "closed": False},
                  "tests/test_b.py": {"tests": ["tests/test_b.py::test_two"], "queued": True, "n": 2, "closed": False},
                  "tests/test_c.py": {"tests": ["tests/test_c.py::test_three"], "queued": True, "n": 3, "closed": False},
                  "tests/test_d.py": {"tests": ["tests/test_d.py::test_none"], "queued": True, "n": 4, "closed": False},
                  "tests/test_e.py": {"tests": ["tests/test_e.py::x", "tests/test_a.py::test_one"], "queued": True, "n": 5, "closed": True}})
    assert BIS.row_kinds(state) == {"rel-base-1": "regression", "rel-base-2": "never_green", "rel-base-3": "moved"}
    assert [BIS.rank(state, "rel-base-%d" % n) for n in (1, 2, 3, 4, 5)] == [0, 2, 2, 1, 1]
    assert BIS.rank(state, "B7") == 1
