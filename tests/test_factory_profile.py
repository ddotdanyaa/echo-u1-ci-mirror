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


# The triage no longer profiles tests, scopes rows, asks green/unknown/tied-module questions or defers rows by a
# deadline: the architect owns file discovery and the slicer queue owns every row (<id>). The tests of that triage-side
# profiling (red target as scope, green target as a question, unknown/third failed profile, two-run neighbours,
# explicit file skips profiling, honest verdict, environment failure, suspects in the goal, fallback event, limit,
# tied modules, deadline) are replaced by the one below; the profiler itself (G.profile_tests, ranking) keeps its
# own tests in this file.
def test_triage_never_profiles_and_hands_the_row_to_the_slicer(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the triage must not profile tests any more")
    monkeypatch.setattr(G, "profile_tests", boom)
    root, b = _repo(tmp_path, E08000ISH, ROW)
    r = imp.triage_portion(b, root, set(), 5)
    assert [x["backlog_id"] for x in r["to_slice"]] == ["E70000"]
    assert r["tasks"] == [] and r["holds"] == [] and r["deferred"] == [] and r["profile_attempts"] == {}


def test_a_red_neighbour_does_not_shift_the_ranking():
    outcomes = {"t.py::target": "failed", "n.py::red_neighbour": "failed", "n.py::ok": "passed"}
    calls = {"t.py::target": {("a.py", "dec", 1)}, "n.py::red_neighbour": {("b.py", "other", 1), ("a.py", "dec", 1)},
             "n.py::ok": {("c.py", "fine", 1)}}
    mods, _ = G.rank_modules(outcomes, calls, targets={"t.py"})
    assert [m for m, _, _ in mods] == ["a.py"]                 # b.py only fails in the neighbour: not a suspect
    assert [m for m, _, _ in G.rank_modules(outcomes, calls)[0]][0] == "a.py"


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


def test_module_fixture_calls_are_recorded_for_every_test_of_the_module(tmp_path):
    _write(tmp_path, {
        "echo_sync/__init__.py": "",
        "echo_sync/m.py": "def build():\n    return 1\n\n\ndef bad():\n    return 2\n",
        "tests/test_mod.py": ("import pytest\nfrom echo_sync.m import build, bad\n\n"
                              "@pytest.fixture(scope='module')\ndef shared():\n    return build()\n\n"
                              "def test_a(shared):\n    assert shared == 1\n\n"
                              "def test_b(shared):\n    assert bad() == 3\n"),
    })
    r = G.profile_tests(tmp_path, ["tests/test_mod.py"], 60, ("echo_sync/",))
    names = {k.split("::")[-1]: {q for _, q, _ in v} for k, v in r.calls.items()}
    assert "build" in names["test_a"] and "build" in names["test_b"] and "bad" in names["test_b"]
