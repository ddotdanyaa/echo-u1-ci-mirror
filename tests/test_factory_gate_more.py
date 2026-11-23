"""Gate K-C, fourth pass: TDD base, forbidden globs, ast weakening, sandbox env, repo-local FileNotFound."""
from __future__ import annotations

import pytest

from tools import factory_gate as fg


def result(**kw):
    base = dict(rc=0, collected=3, passed=3, failed=0, errors=0, skipped=0, junit_ok=True, diag="")
    base.update(kw)
    return fg.GateResult(**base)


TDD_TEST = "from echo_sync.newmod import f\n\ndef test_f():\n    assert f() == 1\n"
SKIPPED = "import pytest\n\n" "@pytest.mark.skip(reason='no')\ndef test_s():\n    assert True\n"
ENV_PROBE = (
    "import os\n\ndef test_env():\n"
    "    keys = ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP')\n"
    "    assert all(os.environ[k] == os.environ['TEMP'] for k in keys)\n"
    "    assert os.environ['USERPROFILE'] != @REAL@\n"
)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    import os

    def make(name, files):
        root = tmp_path_factory.mktemp(name)
        for fname, text in files.items():
            path = root / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    base_root = make("tdd_base", {"echo_sync/__init__.py": "", "test_a.py": TDD_TEST})
    cand_root = make("tdd_cand", {"echo_sync/__init__.py": "", "echo_sync/newmod.py": "def f():\n    return 1\n",
                                  "test_a.py": TDD_TEST})
    probe = make("probe", {"test_a.py": ENV_PROBE.replace("@REAL@", repr(os.environ.get("USERPROFILE", "")))})
    skip_root = make("allskip", {"test_a.py": SKIPPED})
    jobs = {
        "tdd_base": lambda: fg.red_before(base_root, ["test_a.py"], 20),
        "tdd_cand": lambda: fg.run_tests(cand_root, ["test_a.py"], 20),
        "node_base": lambda: fg.red_before(base_root, ["test_a.py::test_f"], 20),
        "node_cand": lambda: fg.run_tests(cand_root, ["test_a.py::test_f"], 20),
        "probe": lambda: fg.run_tests(probe, ["test_a.py"], 20),
        "allskip": lambda: fg.red_before(skip_root, ["test_a.py"], 20),
    }
    class Lazy:                       # one real pytest run per key, on first use, one at a time (owner's rule: <= 2 pytest in
        def __init__(self):           # parallel and <= 30 s per group: a test pays only for the runs it reads)
            self.done = {}

        def __getitem__(self, key):
            if key not in self.done:
                self.done[key] = jobs[key]()
            return self.done[key]

    return Lazy()


# 1. TDD: the task test imports a not-yet-existing repo module -> collection error on base
def test_tdd_base_is_red_and_accept_takes_green_candidate(runs):
    verdict, base = runs["tdd_base"]
    cand = runs["tdd_cand"]
    assert verdict == "red" and base.errors >= 1 and base.env_reason == "" and base.junit_ok is False
    assert cand.junit_ok and cand.passed == 1
    assert fg.accept(base, cand, verdict == "red") == (True, "ok")


def test_accept_base_collection_error_still_needs_good_candidate(runs):
    _, base = runs["tdd_base"]
    ok, _ = fg.accept(base, result(collected=1, passed=0, skipped=1), True)
    assert not ok
    ok, _ = fg.accept(base, result(rc=1, failed=1, passed=0, collected=1), True)
    assert not ok
    assert not fg.accept(base, result(), False)[0]


def test_accept_base_collection_error_by_environment_is_env_not_strike():
    base = result(rc=2, collected=1, passed=0, errors=1, junit_ok=False, env_reason="ModuleNotFoundError")
    ok, reason = fg.accept(base, result(), True)        # round 7: an environment base is never a strike: 'env:' prefix
    assert not ok and reason == "env:ModuleNotFoundError"


# 3. all skipped on base is not green
def test_red_before_all_skipped_is_unknown(runs):
    verdict, r = runs["allskip"]
    assert verdict == "unknown" and r.skipped == 1 and r.passed == 0


# 6. privacy: the candidate's tests see a sandbox instead of the real profile
def test_sandboxed_env_in_real_run(runs):
    r = runs["probe"]
    assert r.passed == 1 and r.junit_ok is True, r.diag


def test_env_points_to_sandbox(tmp_path):
    env = fg._env(tmp_path)
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        assert env[key].startswith(str(tmp_path)), key


# 2. forbidden factory modules by glob
@pytest.mark.parametrize("path", ["tools/factory_new_thing.py", "tools/agent_factory.py",
                                  "tools/agent_factory_runner.py", "Tools/Factory_Loop.py",
                                  "tools/red_ratchet.py", "tools/push_guard.py"])
def test_factory_modules_forbidden(tmp_path, path):
    assert fg.weakening_violations(tmp_path, {path: "x = 1\n"}, "unit_test")


def test_other_tools_allowed(tmp_path):
    assert fg.weakening_violations(tmp_path, {"tools/other.py": "x = 1\n"}, "bugfix") == []


# 4. test-path arguments cannot smuggle pytest options
@pytest.mark.parametrize("bad", ["-x", "--co", "a/-b.py", "a:b.py", "./../x.py", "a/..\\x.py", "a/%s" % "-k"])
def test_run_tests_rejects_option_like_paths(tmp_path, bad):
    r = fg.run_tests(tmp_path, [bad], 5)
    assert r.rc == -1 and r.junit_ok is False and "path" in r.diag


# 5. ast-based weakening
def add(tmp_path, text, kind="bugfix"):
    (tmp_path / "echo_sync").mkdir(exist_ok=True)
    (tmp_path / "echo_sync" / "m.py").write_text("a = 1\n", encoding="utf-8")
    return fg.weakening_violations(tmp_path, {"echo_sync/m.py": "a = 1\n" + text}, kind)


@pytest.mark.parametrize("text", [
    "from pytest import (\n    raises,\n    skip,\n)\n",
    "from pytest import (\n    raises,\n    xfail as xf,\n)\n",
    "from unittest import skipIf\n",
    "from unittest import skip\n",
    "import pytest as p\n\np.skip('x')\n",
    "import pytest as p\n\n" "@p.mark.skip\ndef f(): pass\n",
    "import pytest as p\n\np.importorskip('x')\n",
    "import unittest\n\n" "@unittest.expectedFailure\ndef f(): pass\n",
    "from unittest import expectedFailure\n",
])
def test_ast_weakening_forms(tmp_path, text):
    assert add(tmp_path, text)


@pytest.mark.parametrize("text", [
    "from pytest import (\n    raises,\n    fixture,\n)\n",
    "import pytest as p\n\np.raises(ValueError)\n",
    "from unittest import mock\n",
])
def test_ast_legit_imports_not_flagged(tmp_path, text):
    assert add(tmp_path, text) == []


# 7. FileNotFoundError is environment only when the path is outside the repository
def test_filenotfound_inside_repo_is_task_red(tmp_path):
    inside = str(tmp_path / "data" / "x.json")
    assert fg._env_reason(f"FileNotFoundError: [Errno 2] No such file or directory: {inside!r}", tmp_path) == ""
    assert fg._env_reason("FileNotFoundError: [Errno 2] No such file or directory: 'data/x.json'", tmp_path) == ""


def test_filenotfound_outside_repo_is_environment(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = str(tmp_path / "elsewhere" / "x.json")
    assert fg._env_reason(f"FileNotFoundError: [Errno 2] No such file or directory: {outside!r}", root) \
        == "FileNotFoundError"


# 8. unparsable base test file is reported, not silent
def test_unparsable_base_is_noted(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_a(:\n", encoding="utf-8")
    violations, notes = fg.weakening_check(tmp_path, {"tests/test_x.py": "def test_a():\n    assert 1\n"}, "unit_test")
    assert violations == []
    assert notes and "base" in notes[0]
    assert fg.weakening_violations(tmp_path, {"tests/test_x.py": "def test_a():\n    assert 1\n"}, "unit_test") == []


def test_tdd_with_node_id_is_red_and_accepted(runs):
    verdict, base = runs["node_base"]
    cand = runs["node_cand"]
    assert verdict == "red", base.diag
    assert cand.junit_ok and cand.passed == 1
    assert fg.accept(base, cand, True) == (True, "ok")


def test_accept_red_collection_base_allows_equal_skips():
    base = result(rc=2, collected=1, passed=0, errors=1, skipped=1, junit_ok=False)
    assert fg.accept(base, result(collected=3, passed=2, skipped=1), True) == (True, "ok")
    ok, reason = fg.accept(base, result(collected=3, passed=1, skipped=2), True)
    assert not ok and "skip" in reason


def test_env_reason_path_problem_is_noted(tmp_path, monkeypatch):
    import os
    notes = []
    monkeypatch.setattr(os.path, "abspath", lambda p: (_ for _ in ()).throw(ValueError("boom")))
    assert fg._env_reason("FileNotFoundError: x: 'a/b.json'", tmp_path, notes) == "FileNotFoundError"
    assert notes and "path" in notes[0]


def test_failed_ids_name_the_red_testcases(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def test_good():\n    assert True\n\ndef test_bad():\n    assert False\n\ndef test_worse():\n    assert 1 == 2\n")
    got = fg.run_tests(tmp_path, ["tests/test_x.py"], 30)
    assert got.failed == 2
    assert got.failed_ids == ("tests.test_x::test_bad", "tests.test_x::test_worse")
    clean = fg.run_tests(tmp_path, ["tests/test_x.py::test_good"], 30)
    assert clean.failed_ids == ()
