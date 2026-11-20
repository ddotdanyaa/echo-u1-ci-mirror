"""Spectrum localisation (factory_gate.profile_tests / rank_modules) and its use in triage_portion."""
import math
import os
import subprocess
from pathlib import Path

import pytest

from tools import agent_factory_import as imp
from tools import factory_gate as G


def _write(root, files):
    for rel, txt in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")


def _snapshot(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in Path(root).rglob("*") if p.is_file() and ".git" not in p.parts}


SMALL = {
    "echo_sync/__init__.py": "",
    "echo_sync/m.py": "def good():\n    return 1\n\n\ndef bad():\n    return 2\n",
    "tests/test_p.py": ("from echo_sync.m import good, bad\n\n"
                        "def test_fails():\n    assert bad() == 3\n\n"
                        "def test_passes():\n    assert good() == 1\n"),
}

# the <id> shape: the test imports util for normalize(); the defect is in engine, reached through a fixture
E08000ISH = {
    "echo_sync/__init__.py": "",
    "echo_sync/util.py": "def normalize(s):\n    return s.strip().lower()\n",
    "echo_sync/engine.py": ("def decide(word):\n    return _route(word)\n\n\n"
                            "def _route(word):\n    if word == 'remark':\n        return _remark_branch(word)\n"
                            "    return 'ok'\n\n\ndef _remark_branch(word):\n    return 'sound'\n"),
    "tests/conftest.py": ("import pytest\nfrom echo_sync.engine import decide\n\n"
                          "@pytest.fixture\ndef call():\n    return decide\n"),
    "tests/test_v_E70000.py": ("from echo_sync.util import normalize\n\n"
                            "def test_remark_is_silent(call):\n    assert normalize(call('remark')) == 'ok'\n"),
    "tests/test_other.py": ("from echo_sync.util import normalize\n\n"
                            "def test_ok(call):\n    assert normalize(call('plain')) == 'ok'\n\n"
                            "def test_util():\n    assert normalize(' A ') == 'a'\n"),
}


def test_profile_records_called_functions_per_test_and_outcomes(tmp_path):
    _write(tmp_path, SMALL)
    r = G.profile_tests(tmp_path, ["tests/test_p.py"], 60, ("echo_sync/",))
    assert r.verdict == "ok" and r.fallback is False
    by = {k.split("::")[-1]: v for k, v in r.outcomes.items()}
    assert by == {"test_fails": "failed", "test_passes": "passed"}
    names = {k.split("::")[-1]: {q for _, q, _ in v} for k, v in r.calls.items()}
    assert names["test_fails"] == {"bad"} and names["test_passes"] == {"good"}
    assert all(rel == "echo_sync/m.py" for v in r.calls.values() for rel, _, _ in v)


def test_profile_does_not_write_into_the_source_tree(tmp_path):
    _write(tmp_path, SMALL)
    before = _snapshot(tmp_path)
    G.profile_tests(tmp_path, ["tests/test_p.py"], 60, ("echo_sync/",))
    assert _snapshot(tmp_path) == before


def test_profile_timeout_is_unknown(tmp_path):
    _write(tmp_path, dict(SMALL, **{"tests/test_slow.py": "import time\n\ndef test_s():\n    time.sleep(30)\n"}))
    r = G.profile_tests(tmp_path, ["tests/test_slow.py"], 3, ("echo_sync/",))
    assert r.verdict == "unknown" and "timeout" in r.diag


def test_ochiai_on_table_data():
    outcomes = {"t1": "failed", "t2": "passed", "t3": "passed"}
    f = lambda q, line=1: ("echo_sync/a.py", q, line)
    calls = {"t1": {f("bad"), f("both")}, "t2": {f("both"), f("good")}, "t3": {f("good")}}
    mods, leaders = G.rank_modules(outcomes, calls)
    assert [m for m, _, _ in mods] == ["echo_sync/a.py"]
    scores = {q: s for q, _, s in leaders["echo_sync/a.py"]}
    assert scores["bad"] == pytest.approx(1.0)
    assert scores["both"] == pytest.approx(1 / math.sqrt(1 * 2))
    assert "good" not in scores or scores["good"] == 0


def test_ochiai_module_score_is_max_and_ties_prefer_more_top_functions():
    outcomes = {"f": "failed", "p": "passed"}
    c = lambda mod, q: (mod, q, 1)
    calls = {"f": {c("a.py", "x"), c("b.py", "y"), c("b.py", "z"), c("c.py", "w")},
             "p": {c("c.py", "w")}}
    mods, _ = G.rank_modules(outcomes, calls)
    assert [m for m, _, _ in mods] == ["b.py", "a.py", "c.py"]       # b has two top functions; c is shared
    assert mods[0][1] == pytest.approx(1.0) and mods[2][1] < 1.0


def test_shape_leader_is_engine_not_util(tmp_path):
    _write(tmp_path, E08000ISH)
    r = G.profile_tests(tmp_path, ["tests/test_v_E70000.py", "tests/test_other.py"], 60, ("echo_sync/",))
    assert r.verdict == "ok"
    mods, leaders = G.rank_modules(r.outcomes, r.calls)
    assert mods[0][0] == "echo_sync/engine.py" and mods[0][1] == pytest.approx(1.0)
    assert next(s for m, s, _ in mods if m == "echo_sync/util.py") < 1.0
    assert leaders["echo_sync/engine.py"][0][0] == "_remark_branch"


def _repo(tmp_path, files, backlog_row):
    root = tmp_path / "head"
    _write(root, files)
    for a in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *a],
                       check=True, capture_output=True)
    b = tmp_path / "B.md"
    b.write_text("## 4. Q\n### 4.2 P1\n| ID | Формулировка | Origin | Приоритет: причина | Состояние | Зависит |\n"
                 "|---|---|---|---|---|---|\n" + backlog_row + "## 5. H\n", encoding="utf-8")
    return root, b


ROW = "| E70000 | Контроллер молчит на реплике соседа | x | P0 | новая | — |\n"


def test_triage_red_target_gets_the_spectrum_leader_as_scope(tmp_path):
    root, b = _repo(tmp_path, E08000ISH, ROW)
    r = imp.triage_portion(b, root, set(), 5)
    t = {x["id"]: x for x in r["tasks"]}["bl_E70000"]
    assert t["touch_files"] == ["echo_sync/engine.py"]
    assert t["tests"] == ["tests/test_v_E70000.py"]
    assert t["read_files"] == ["echo_sync/util.py"]
    assert t["context_targets"] == {"echo_sync/util.py": "normalize"}      # read_files only


def test_triage_green_target_is_a_question_not_a_task(tmp_path):
    files = dict(E08000ISH, **{"tests/test_v_E70000.py": "from echo_sync.util import normalize\n\ndef test_g():\n    assert normalize(' A ') == 'a'\n"})
    root, b = _repo(tmp_path, files, ROW)
    r = imp.triage_portion(b, root, set(), 5)
    assert not r["tasks"]
    q = {h["backlog_id"]: h["question"] for h in r["holds"]}["E70000"]
    assert "зелёный на HEAD" in q and "test_v_E70000.py" in q and "закрыть строку E70000" in q


def _unknown_fake(*a, **k):
    return G.ProfileResult("unknown", {}, {}, False, "timeout after 30s (process tree killed)")


def test_unknown_profile_defers_the_row_and_counts_the_attempt(tmp_path, monkeypatch):
    root, b = _repo(tmp_path, E08000ISH, ROW)
    monkeypatch.setattr(G, "profile_tests", _unknown_fake)
    r = imp.triage_portion(b, root, set(), 5)
    assert not r["tasks"] and not r["holds"]                   # NOT a task by imports
    assert [d["backlog_id"] for d in r["deferred"]] == ["E70000"] and "timeout after 30s" in r["deferred"][0]["reason"]
    assert not any(x["backlog_id"] == "E70000" for x in r["skipped"])
    assert r["profile_attempts"] == {"E70000": 1}
    assert any(e["backlog_id"] == "E70000" and e["event"] == "profile_unknown" for e in r["events"])


def test_third_failed_profile_is_a_hold_with_import_hints_not_a_scope(tmp_path, monkeypatch):
    root, b = _repo(tmp_path, E08000ISH, ROW)
    monkeypatch.setattr(G, "profile_tests", _unknown_fake)
    r = imp.triage_portion(b, root, set(), 5, profile_attempts={"E70000": 2})
    assert not r["tasks"] and not r["deferred"]
    q = {h["backlog_id"]: h["question"] for h in r["holds"]}["E70000"]
    assert q.startswith("профиль не удался (") and "timeout after 30s" in q and "дать область?" in q
    assert "echo_sync/util.py" in q and "не область" in q
    assert r["profile_attempts"] == {"E70000": 3}


def test_target_and_neighbours_are_profiled_in_two_runs_and_merged(tmp_path, monkeypatch):
    root, b = _repo(tmp_path, E08000ISH, ROW)
    seen = []
    tgt = "tests/test_v_E70000.py::test_remark_is_silent"
    other = "tests/test_other.py::test_util"
    def fake(r_, tests, timeout, *a, **k):
        seen.append((list(tests), timeout))
        if tests == ["tests/test_v_E70000.py"]:
            return G.ProfileResult("ok", {tgt: "failed"}, {tgt: {("echo_sync/engine.py", "_remark_branch", 1),
                                                                ("echo_sync/util.py", "normalize", 1)}}, False, "", {})
        return G.ProfileResult("ok", {other: "passed"}, {other: {("echo_sync/util.py", "normalize", 1)}}, False, "", {})
    monkeypatch.setattr(G, "profile_tests", fake)
    t = {x["id"]: x for x in imp.triage_portion(b, root, set(), 5)["tasks"]}["bl_E70000"]
    assert len(seen) == 2 and seen[0][0] == ["tests/test_v_E70000.py"] and "tests/test_other.py" in seen[1][0]
    assert all(timeout <= 30 for _, timeout in seen)
    assert t["touch_files"] == ["echo_sync/engine.py"]          # util is shared with a passing neighbour: lower score


def test_neighbours_run_failing_falls_back_to_the_target_alone_with_a_note(tmp_path, monkeypatch):
    root, b = _repo(tmp_path, E08000ISH, ROW)
    tgt = "tests/test_v_E70000.py::test_remark_is_silent"
    def fake(r_, tests, timeout, *a, **k):
        if tests == ["tests/test_v_E70000.py"]:
            return G.ProfileResult("ok", {tgt: "failed"}, {tgt: {("echo_sync/engine.py", "_remark_branch", 1)}}, False, "", {})
        return G.ProfileResult("unknown", {}, {}, False, "timeout after 30s", {})
    monkeypatch.setattr(G, "profile_tests", fake)
    r = imp.triage_portion(b, root, set(), 5)
    assert {x["id"]: x for x in r["tasks"]}["bl_E70000"]["touch_files"] == ["echo_sync/engine.py"]
    assert any(e["event"] == "profile_neighbours_unknown" for e in r["events"])


def test_triage_explicit_file_in_the_row_skips_profiling(tmp_path, monkeypatch):
    root, b = _repo(tmp_path, E08000ISH, "| E70000 | Правка `echo_sync/util.py` | x | P0 | новая | — |\n")
    def boom(*a, **k):
        raise AssertionError("profile must not run for a row that names a file")
    monkeypatch.setattr(G, "profile_tests", boom)
    t = {x["id"]: x for x in imp.triage_portion(b, root, set(), 5)["tasks"]}["bl_E70000"]
    assert t["touch_files"] == ["echo_sync/util.py"]


# ---- round 2: honest verdict, target-only failures, suspects in the goal, deadline, neighbours ----
T = "tests/test_v_E70000.py::test_remark_is_silent"


def _fake(outcomes, calls=None, reasons=None, fallback=False, verdict="ok"):
    return lambda *a, **k: G.ProfileResult(verdict, outcomes, calls or {}, fallback, "", reasons or {})


def _triage_with(tmp_path, monkeypatch, fake, row=ROW, limit=5):
    d = tmp_path / ("c%d" % len(list(tmp_path.glob("c*"))))
    d.mkdir()
    root, b = _repo(d, E08000ISH, row)
    monkeypatch.setattr(G, "profile_tests", fake)
    return imp.triage_portion(b, root, set(), limit)


def test_green_needs_a_passed_target_and_no_skipped(tmp_path, monkeypatch):
    r = _triage_with(tmp_path, monkeypatch, _fake({T: "passed"}))
    assert any("зелёный на HEAD" in h["question"] for h in r["holds"])
    r = _triage_with(tmp_path, monkeypatch, _fake({T: "skipped"}))
    assert not any("зелёный" in h["question"] for h in r["holds"])
    assert any(e["event"] == "profile_unknown" for e in r["events"])
    r = _triage_with(tmp_path, monkeypatch, _fake({T: "passed", T + "2": "skipped"}))
    assert not any("зелёный" in h["question"] for h in r["holds"])


def test_target_failing_for_the_environment_is_unknown(tmp_path, monkeypatch):
    f = _fake({T: "failed"}, {T: {("echo_sync/engine.py", "_remark_branch", 1)}},
              {T: "ModuleNotFoundError: No module named 'zzz_missing'"})
    r = _triage_with(tmp_path, monkeypatch, f)
    assert any(e["event"] == "profile_unknown" and "environment" in e["reason"] for e in r["events"])
    assert not any(h["backlog_id"] == "E70000" for h in r["holds"])


def test_a_red_neighbour_does_not_shift_the_ranking():
    outcomes = {"t.py::target": "failed", "n.py::red_neighbour": "failed", "n.py::ok": "passed"}
    calls = {"t.py::target": {("a.py", "dec", 1)}, "n.py::red_neighbour": {("b.py", "other", 1), ("a.py", "dec", 1)},
             "n.py::ok": {("c.py", "fine", 1)}}
    mods, _ = G.rank_modules(outcomes, calls, targets={"t.py"})
    assert [m for m, _, _ in mods] == ["a.py"]                 # b.py only fails in the neighbour: not a suspect
    assert [m for m, _, _ in G.rank_modules(outcomes, calls)[0]][0] == "a.py"


def test_suspect_functions_are_in_the_goal_and_context_targets_only_for_read_files(tmp_path):
    root, b = _repo(tmp_path, E08000ISH, ROW)
    t = {x["id"]: x for x in imp.triage_portion(b, root, set(), 5)["tasks"]}["bl_E70000"]
    assert "Подозреваемые функции (замер вызовов падающего теста): echo_sync/engine.py: _remark_branch" in t["goal"]
    assert t["context_targets"] == {"echo_sync/util.py": "normalize"}
    assert len(t["goal"]) <= 1500


def test_fallback_is_an_event(tmp_path, monkeypatch):
    f = _fake({T: "failed", "tests/test_other.py::test_util": "passed"},
              {T: {("echo_sync/engine.py", "_remark_branch", 1)}}, fallback=True)
    r = _triage_with(tmp_path, monkeypatch, f)
    assert any(e["event"] == "profile_fallback" for e in r["events"])
    assert {x["id"] for x in r["tasks"]} >= {"bl_E70000"}


def test_real_setprofile_fallback_gives_the_same_calls(tmp_path):
    _write(tmp_path, SMALL)
    r = G.profile_tests(tmp_path, ["tests/test_p.py"], 60, ("echo_sync/",), force_fallback=True)
    assert r.verdict == "ok" and r.fallback is True
    assert {q for k, v in r.calls.items() if k.endswith("test_fails") for _, q, _ in v} == {"bad"}


def test_profile_path_with_cyrillic_and_space(tmp_path):
    root = tmp_path / "папка с пробелом"
    _write(root, SMALL)
    r = G.profile_tests(root, ["tests/test_p.py"], 60, ("echo_sync/",))
    assert r.verdict == "ok" and any(q == "bad" for v in r.calls.values() for _, q, _ in v)


def test_timeout_leaves_no_copy_and_no_process(tmp_path, tmp_path_factory, monkeypatch):
    import tempfile
    # its own temp folder, outside the copied tree: in the shared one the live loop's profiles (and a parallel part of
    # the suite) made copies of their own between 'before' and 'after' (20.11: red twice in parallel runs, green alone)
    own = tmp_path_factory.mktemp("profile-temp")
    monkeypatch.setattr(tempfile, "tempdir", str(own))
    pattern = Path(tempfile.gettempdir())
    before = {p.name for p in pattern.glob("factory-profile-*")}
    _write(tmp_path, dict(SMALL, **{"tests/test_slow.py": "import time\n\ndef test_s():\n    time.sleep(30)\n"}))
    assert G.profile_tests(tmp_path, ["tests/test_slow.py"], 3, ("echo_sync/",)).verdict == "unknown"
    assert {p.name for p in pattern.glob("factory-profile-*")} - before == set()


def test_at_most_limit_rows_are_profiled(tmp_path, monkeypatch):
    rows = "".join("| E%d | Строка %d без путей | x | P0 | новая | — |\n" % (70 + i, i) for i in range(4))
    files = dict(E08000ISH)
    for i in range(1, 4):
        files["tests/test_v_E%d.py" % (70 + i)] = "def test_x():\n    assert True\n"
    root, b = _repo(tmp_path, files, rows)
    calls = []
    monkeypatch.setattr(G, "profile_tests", lambda *a, **k: (calls.append(1), G.ProfileResult("unknown", {}, {}, False, "x"))[1])
    imp.triage_portion(b, root, set(), 2)
    assert len(calls) <= 2


def test_more_than_three_tied_modules_is_a_hold(tmp_path, monkeypatch):
    calls = {T: {("echo_sync/m%d.py" % i, "f", 1) for i in range(4)}}
    r = _triage_with(tmp_path, monkeypatch, _fake({T: "failed"}, calls))
    q = {h["backlog_id"]: h["question"] for h in r["holds"]}["E70000"]
    assert q.startswith("локализация неоднозначна") and not r["tasks"]


def test_deadline_defers_the_remaining_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(imp, "PORTION_DEADLINE_S", -1)
    def boom(*a, **k):
        raise AssertionError("no profiling after the deadline")
    r = _triage_with(tmp_path, monkeypatch, boom)
    assert [x["backlog_id"] for x in r["deferred"]] == ["E70000"] and r["deferred"][0]["reason"].startswith("отложено")
    assert not any(x["backlog_id"] == "E70000" for x in r["skipped"])      # the loop marks skipped rows as seen


def test_neighbours_are_chosen_by_shared_imports_not_by_name(tmp_path):
    files = dict(E08000ISH, **{
        "tests/aaa_unrelated.py": "def test_a():\n    assert True\n",
        "tests/test_aaa.py": "def test_a():\n    assert True\n",
        "tests/test_zzz_shares.py": "from echo_sync.util import normalize\nfrom echo_sync.engine import decide\n\ndef test_z():\n    assert normalize('A') == 'a'\n",
    })
    _write(tmp_path, files)
    idx = imp._module_index(tmp_path)
    allt = sorted(p for v in idx.values() for p in v if p.startswith("tests/"))
    assert imp._neighbours(tmp_path, ["tests/test_v_E70000.py"], idx, allt)[0] in ("tests/test_zzz_shares.py", "tests/test_other.py")
    assert "tests/test_aaa.py" not in imp._neighbours(tmp_path, ["tests/test_v_E70000.py"], idx, allt)
