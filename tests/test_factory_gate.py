"""Deterministic QC gates (contract K-C). Nested runs use the real pytest in tiny tmp projects."""
from __future__ import annotations

import time

import pytest

from tools import factory_gate as fg

GREEN = "def test_ok():\n    assert 1 + 1 == 2\n"
RED = "def test_bad():\n    assert 1 == 2\n"
BROKEN = "import module_that_does_not_exist\n\ndef test_x():\n    assert True\n"
EMPTY = "x = 1\n"
SKIPPED = "import pytest\n\n" "@pytest.mark.skip(reason='no')\ndef test_s():\n    assert True\n"


def project(tmp_path, **files):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def result(**kw):
    base = dict(rc=0, collected=3, passed=3, failed=0, errors=0, skipped=0,
                junit_ok=True, diag="")
    base.update(kw)
    return fg.GateResult(**base)


# ---- run_tests / red_before: real pytest, all nested runs in parallel ------------

HANG_MARKER = "grandchild_alive.txt"
MIXED = "def test_x():\n    import module_nope_xyz\n\ndef test_y():\n    assert 1 == 2\n"
RAISES_FNF = (
    "import pytest\n\ndef test_ok():\n    with pytest.raises(FileNotFoundError):\n        open('nope_zz')\n"
    "\ndef test_bad():\n    assert 'FileNotFoundError' == 'x'\n"
)
ENV_TEST = "def test_x():\n    import module_nope_xyz\n"


def hang_source(marker):
    template = '''import subprocess, sys, time

def test_hang():
    code = "import time; time.sleep(4); open(r'@MARKER@', 'w').write('x')"
    subprocess.Popen([sys.executable, '-c', code])
    time.sleep(60)
'''
    return template.replace("@MARKER@", str(marker).replace("\\", "/"))


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Each scenario is a tiny project, run on first use (a nested pytest costs ~3 s)."""
    roots = {}

    def make(name, files):
        root = tmp_path_factory.mktemp(name)
        for fname, text in files.items():
            (root / fname).write_text(text, encoding="utf-8")
        roots[name] = root
        return root

    jobs = {
        "green": lambda: fg.run_tests(make("green", {"test_a.py": GREEN}), ["test_a.py"], 15),
        "red": lambda: fg.run_tests(make("red", {"test_a.py": RED}), ["test_a.py"], 15),
        "broken": lambda: fg.run_tests(make("broken", {"test_a.py": BROKEN}), ["test_a.py"], 15),
        "empty": lambda: fg.run_tests(make("empty", {"test_a.py": EMPTY}), ["test_a.py"], 15),
        "missing": lambda: fg.run_tests(
            make("missing", {"test_a.py": GREEN, "test_b.py": EMPTY}), ["test_a.py", "test_b.py"], 15),
        "skip": lambda: fg.run_tests(make("skip", {"test_a.py": SKIPPED}), ["test_a.py"], 15),
        "rb_red": lambda: fg.red_before(make("rb_red", {"test_a.py": RED}), ["test_a.py"], 15),
        "rb_green": lambda: fg.red_before(make("rb_green", {"test_a.py": GREEN}), ["test_a.py"], 15),
        "rb_unit": lambda: fg.red_before(make("rb_unit", {}), ["test_new.py"], 15, kind="unit_test"),
        "rb_missing": lambda: fg.red_before(make("rb_missing", {}), ["test_nothere.py"], 15),
        "rb_timeout": lambda: fg.red_before(
            make("rb_timeout", {"test_a.py": "import time\n\ndef test_slow():\n    time.sleep(30)\n"}),
            ["test_a.py"], 2),
        "rb_env": lambda: fg.red_before(
            make("rb_env", {"test_a.py": ENV_TEST}), ["test_a.py"], 15),
        "mixed": lambda: fg.red_before(make("mixed", {"test_a.py": MIXED}), ["test_a.py"], 15),
        "raises_fnf": lambda: fg.run_tests(make("rfnf", {"test_a.py": RAISES_FNF}), ["test_a.py"], 15),
        "rb_partial": lambda: fg.red_before(
            make("rb_partial", {"test_a.py": RED}), ["test_a.py", "test_none.py"], 15),
        "cyr": lambda: fg.run_tests(make("каталог", {"test_тест.py": GREEN}), ["./test_тест.py"], 15),
    }
    hang_root = tmp_path_factory.mktemp("hang")
    marker = hang_root / HANG_MARKER
    (hang_root / "test_a.py").write_text(hang_source(marker), encoding="utf-8")

    def hang():
        t0 = time.monotonic()
        r = fg.run_tests(hang_root, ["test_a.py"], 3)
        return r, time.monotonic() - t0

    jobs["hang"] = hang
    class Lazy:                       # one real pytest run per key, on first use, one at a time: a test pays only for the
        def __init__(self):           # runs it reads (owner's rule: <= 2 pytest in parallel, <= 30 s per group)
            self.done = {"marker": marker}

        def __getitem__(self, key):
            if key not in self.done:
                self.done[key] = jobs[key]()
            return self.done[key]

    return Lazy()


def test_green(runs):
    r = runs["green"]
    assert (r.rc, r.collected, r.passed, r.failed, r.errors, r.skipped) == (0, 1, 1, 0, 0, 0)
    assert r.junit_ok is True


def test_red(runs):
    r = runs["red"]
    assert r.rc != 0 and r.failed == 1 and r.passed == 0
    ok, _ = fg.accept(result(), r, True)
    assert not ok


def test_collection_error_is_failure(runs):
    r = runs["broken"]
    assert r.errors >= 1
    assert r.junit_ok is False
    assert r.diag


def test_empty_file_is_not_green(runs):
    r = runs["empty"]
    assert r.collected == 0 and r.passed == 0
    assert r.junit_ok is False


def test_missing_file_among_tests_is_not_ok(runs):
    assert runs["missing"].junit_ok is False


def test_skip_counted(runs):
    r = runs["skip"]
    assert r.skipped == 1 and r.passed == 0 and r.collected == 1
    assert r.junit_ok is True
    ok, reason = fg.accept(result(collected=1, passed=1, skipped=0), r, True)
    assert not ok and "skip" in reason


def test_timeout_kills_whole_tree(runs):
    r, elapsed = runs["hang"]
    assert elapsed < 12
    assert r.junit_ok is False and "timeout" in r.diag.lower()
    time.sleep(3)  # the grandchild (sleeps 4 s from its start) would have written the marker by now
    assert not runs["marker"].exists()


def test_red_before_red_when_base_red(runs):
    verdict, r = runs["rb_red"]
    assert verdict == "red" and r.failed == 1


def test_red_before_green_when_base_green(runs):
    assert runs["rb_green"][0] == "green"


def test_red_before_unit_test_is_red_without_running(runs):
    verdict, r = runs["rb_unit"]
    assert verdict == "red" and r.collected == 0 and r.junit_ok is True


def test_red_before_missing_file_is_unknown(runs):
    verdict, r = runs["rb_missing"]
    assert verdict == "unknown" and r.junit_ok is False


def test_red_before_timeout_is_unknown(runs):
    verdict, r = runs["rb_timeout"]
    assert verdict == "unknown" and "timeout" in r.diag.lower()


def test_cyrillic_dir_and_dot_slash_path(runs):
    r = runs["cyr"]
    assert r.passed == 1 and r.junit_ok is True


def test_covered_checks_node_name():
    import xml.etree.ElementTree as ET
    cases = [ET.Element("testcase", classname="tests.test_a", name="test_x[1]")]
    assert fg._covered(cases, "tests/test_a.py::test_x")
    assert not fg._covered(cases, "tests/test_a.py::test_y")
    assert fg._covered(cases, "tests/test_a.py")
    assert fg._covered(cases, "./tests/test_a.py")


# ---- weakening_violations ------------------------------------------------------

@pytest.mark.parametrize("path", [
    "conftest.py", "tests/conftest.py", "tests/sub/conftest.py", "pytest.ini", "setup.cfg",
    "pyproject.toml", "tools/red_ratchet.py", "tools/push_guard.py", "tools/factory_gate.py",
    "tools/known_cloud_env_red_x.txt", "tox.ini", ".pytest.ini", "pytest.toml",
    "sitecustomize.py", "usercustomize.py", "x/y.pth",
    "CONFTEST.PY", "PyProject.toml", "Tools/Factory_Gate.py", "tools//factory_gate.py",
    "tools/./factory_gate.py", "a/./conftest.py", "conftest.py.", "conftest.py ", "tools\\factory_gate.py",
])
def test_forbidden_paths(tmp_path, path):
    v = fg.weakening_violations(tmp_path, {path: "x = 1\n"}, "unit_test")
    assert v, path


@pytest.mark.parametrize("path", ["Tests/x.py", "tests//x.py", "./tests/x.py", "TESTS/тест.py", "tests/тест.py"])
def test_tests_dir_variants_forbidden_for_non_unit_test(tmp_path, path):
    assert fg.weakening_violations(tmp_path, {path: GREEN}, "bugfix")
    assert fg.weakening_violations(tmp_path, {path: GREEN}, "unit_test") == []


@pytest.mark.parametrize("path", ["a/../b.py", "../b.py", "/etc/b.py", "C:" "/b.py", "c:" "\\b.py", "a/.. /b.py"])
def test_escape_forms_rejected(tmp_path, path):
    assert fg.weakening_violations(tmp_path, {path: "x=1\n"}, "unit_test")


def test_tests_dir_forbidden_unless_unit_test(tmp_path):
    files = {"tests/test_new.py": GREEN}
    assert fg.weakening_violations(tmp_path, files, "bugfix")
    assert fg.weakening_violations(tmp_path, files, "unit_test") == []


SKIP_LINES = [
    "    pytest.skip('x')", "@pytest.mark.skip", "@pytest.mark.skipif(True, reason='r')",
    "@pytest.mark.xfail", "    if os.environ.get('PYTEST_CURRENT_TEST'): return",
    "    m = pytest.importorskip('numpy')", "    raise unittest.SkipTest()", "    self.skipTest('x')",
    "    pytest.exit('bye')", "from pytest import skip", "from pytest import raises, xfail",
    "@unittest.skip('x')", "@unittest.skipIf(1, 'x')", "@skipUnless(1, 'x')", "@skipIf(1, 'x')",
]

LEGIT_LINES = [
    "skip_chunks = 1", "# the file was skipped", "def skip_silence(a):\n    return a", "from pytest import raises",
    "x = 'skipped'", "@pytest.mark.SKIP",
]


@pytest.mark.parametrize("line", LEGIT_LINES)
def test_legit_skip_words_are_not_violations(tmp_path, line):
    (tmp_path / "echo_sync").mkdir()
    (tmp_path / "echo_sync" / "m.py").write_text("a = 1\n", encoding="utf-8")
    assert fg.weakening_violations(tmp_path, {"echo_sync/m.py": "a = 1\n" + line + "\n"}, "bugfix") == []


@pytest.mark.parametrize("line", SKIP_LINES)
def test_added_weakening_lines(tmp_path, line):
    (tmp_path / "echo_sync").mkdir()
    (tmp_path / "echo_sync" / "m.py").write_text("a = 1\n", encoding="utf-8")
    v = fg.weakening_violations(tmp_path, {"echo_sync/m.py": "a = 1\n" + line + "\n"}, "bugfix")
    assert v


def test_moved_or_reindented_skip_is_not_flagged(tmp_path):
    (tmp_path / "echo_sync").mkdir()
    old = "def f():\n    pytest.skip('x')\n    return 1\n"
    (tmp_path / "echo_sync" / "m.py").write_text(old, encoding="utf-8")
    moved = "x = 0\n\nclass C:" "\n    def f(self):\n        pytest.skip('x')\n        return 1\n"
    assert fg.weakening_violations(tmp_path, {"echo_sync/m.py": moved}, "bugfix") == []
    more = moved + "pytest.skip('y')\n"
    assert fg.weakening_violations(tmp_path, {"echo_sync/m.py": more}, "bugfix")


def write_test(tmp_path, text):
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_x.py").write_text(text, encoding="utf-8")


OLD = "def test_a():\n    assert 1\n    assert 2\n"


def check(tmp_path, new):
    return fg.weakening_violations(tmp_path, {"tests/test_x.py": new}, "unit_test")


def test_unit_test_assert_count_must_not_drop(tmp_path):
    write_test(tmp_path, OLD)
    assert check(tmp_path, "def test_a():\n    assert 1\n")
    assert check(tmp_path, OLD + "def test_b():\n    assert 3\n") == []


def test_assert_in_comment_or_string_does_not_compensate(tmp_path):
    write_test(tmp_path, OLD)
    assert check(tmp_path, "def test_a():\n    assert 1\n    # assert 2\n    x = 'assert 3'\n")


def test_unit_test_deleting_test_function_flagged(tmp_path):
    write_test(tmp_path, OLD + "def test_b():\n    assert 5\n")
    assert check(tmp_path, "def test_a():\n    assert 1\n    assert 2\n    assert 3\n")  # test_b gone


def test_raises_and_self_assert_count(tmp_path):
    write_test(tmp_path, "import pytest\n\ndef test_a():\n    with pytest.raises(ValueError):\n        int('x')\n")
    assert check(tmp_path, "def test_a():\n    pass\n")


def test_unit_test_syntax_error_is_violation(tmp_path):
    write_test(tmp_path, OLD)
    assert check(tmp_path, "def test_a(:\n")


def test_unit_test_deleting_existing_test_flagged(tmp_path):
    write_test(tmp_path, OLD)
    assert check(tmp_path, "")


def test_symlink_outside_root_is_not_read(tmp_path, monkeypatch):
    from pathlib import Path
    root = tmp_path / "root"
    (root / "echo_sync").mkdir(parents=True)
    (root / "echo_sync" / "m.py").write_text("a = 1\n", encoding="utf-8")
    real = Path.resolve

    def fake(self, *a, **k):  # as if echo_sync/m.py were a link to a file outside the root
        return Path(tmp_path / "elsewhere" / "m.py") if self.name == "m.py" else real(self, *a, **k)
    monkeypatch.setattr(Path, "resolve", fake)
    assert fg.weakening_violations(root, {"echo_sync/m.py": "a = 1\n"}, "bugfix")


@pytest.mark.parametrize("path", ["tools/agent_factory.py", "tools/factory_process.py", "x/a:stream.py",
                                  "tools/factory_gate.py::$DATA"])
def test_more_forbidden_and_ntfs_streams(tmp_path, path):
    assert fg.weakening_violations(tmp_path, {path: "x = 1\n"}, "unit_test")


# fac-self 19.11: the factory's own code opens only to the task that names it (CODEOWNERS); the rest stays closed
def test_factory_code_opens_only_to_the_task_that_names_it(tmp_path):
    runner = "tools/agent_factory_runner.py"
    assert fg.weakening_violations(tmp_path, {runner: "x = 1\n"}, "code")
    assert fg.weakening_violations(tmp_path, {runner: "x = 1\n"}, "code", (runner,)) == []
    assert fg.weakening_violations(tmp_path, {"Tools//Agent_Factory_Runner.py": "x = 1\n"}, "code", (runner,)) == []
    assert fg.weakening_violations(tmp_path, {runner: "x = 1\n"}, "code", ("tools/factory_gate.py",))
    assert fg.weakening_violations(tmp_path, {"tools/push_guard.py": "x = 1\n"}, "code", ("tools/push_guard.py",)) == []
    for closed in ("conftest.py", "tests/conftest.py", "x/y.pth", "tools/known_cloud_env_red_x.txt"):
        assert fg.is_forbidden(closed, "code", (closed,)), closed
    assert fg.is_forbidden("tests/test_a.py", "code", ("tests/test_a.py",))


def test_the_loop_never_merges_factory_code_even_when_the_task_names_it(tmp_path):
    from types import SimpleNamespace
    from tools import factory_loop as L
    runner = "tools/agent_factory_runner.py"
    src = tmp_path / "pkg"
    (src / "tools").mkdir(parents=True)
    (src / "tools" / "agent_factory_runner.py").write_text("x = 1\n", encoding="utf-8")
    task = SimpleNamespace(touch_files=(runner,), tests=("tests/test_a.py",), kind="code")
    why = L.Loop._refuse_reason(SimpleNamespace(mirror=tmp_path), [runner], src, task)
    assert "factory's own code" in why


def test_shape_errors_are_violations(tmp_path, monkeypatch):
    write_test(tmp_path, OLD)
    assert check(tmp_path, "def test_a():\n    assert 1\n" * 1 + "x = (" * 1)  # SyntaxError
    assert check(tmp_path, "def test_a():\n    assert 1\n    assert 2\n" + "\0")  # ValueError (null byte)


def test_run_tests_rejects_escaping_test_paths(tmp_path):
    for bad in ("../x.py", "/abs/x.py", "C:" "/x.py", "a/../../x.py"):
        r = fg.run_tests(tmp_path, [bad], 5)
        assert r.rc == -1 and r.junit_ok is False and "path" in r.diag


# ---- env_reason classification (pure) ---------------------------------------------

def test_env_reason_module_missing_outside_repo_is_env(tmp_path):
    # the module travels with the class: candidate_import() tells the candidate's own import from the environment
    assert fg._env_reason("ModuleNotFoundError: No module named 'numpy_x'", tmp_path) == "ModuleNotFoundError: numpy_x"
    assert fg._env_reason("FileNotFoundError: [Errno 2] no such file", tmp_path) == "FileNotFoundError"


def test_a_module_only_the_candidate_imports_is_its_defect_a_project_package_is_the_environment(tmp_path):
    """Critic 19.11: ONE owner of this decision (it had a second one in the runner, which struck project packages)."""
    from dataclasses import replace
    base, tree = tmp_path / "base", tmp_path / "tree"
    (base / "pkg").mkdir(parents=True)
    (base / "pkg/plot.py").write_text("import numpy as np\n", encoding="utf-8")
    (tree / "tests").mkdir(parents=True)
    (tree / "tests/test_new.py").write_text("import nope.sub\nimport numpy\n", encoding="utf-8")
    red = replace(result(rc=1, collected=1, passed=0, errors=1, junit_ok=False), diag="collection failure",
                  env_reason="ModuleNotFoundError: nope.sub")
    mine = fg.candidate_import(red, base, tree, ["tests/test_new.py"])
    assert mine.env_reason == "" and "not available: nope.sub" in mine.diag
    env = replace(red, env_reason="ModuleNotFoundError: numpy")
    assert fg.candidate_import(env, base, tree, ["tests/test_new.py"]) == env        # the project imports it too
    other = replace(red, env_reason="ModuleNotFoundError: yaml")
    assert fg.candidate_import(other, base, tree, ["tests/test_new.py"]) == other    # not the candidate's import
    slot = replace(red, env_reason="pytest slot: no RAM")
    assert fg.candidate_import(slot, base, tree, ["tests/test_new.py"]) == slot


def test_env_reason_repo_module_is_task_red(tmp_path):
    (tmp_path / "echo_sync").mkdir()
    assert fg._env_reason("ModuleNotFoundError: No module named 'echo_sync.new'", tmp_path) == ""
    assert fg._env_reason("ImportError: cannot import name 'f' from 'echo_sync.m'", tmp_path) == ""
    (tmp_path / "tools.py").write_text("", encoding="utf-8")
    assert fg._env_reason("ModuleNotFoundError: No module named 'tools'", tmp_path) == ""


def test_env_reason_ignores_other_messages(tmp_path):
    assert fg._env_reason("assert 1 == 2 FileNotFoundError", tmp_path) == ""
    assert fg._env_reason("collection failure", tmp_path) == ""


def test_mixed_reds_are_not_env(runs):
    verdict, r = runs["mixed"]
    assert r.failed == 2 and r.env_reason == ""
    assert verdict == "red"


def test_raises_filenotfound_is_not_env(runs):
    r = runs["raises_fnf"]
    assert r.failed == 1 and r.env_reason == ""


def test_covered_class_nodes():
    import xml.etree.ElementTree as ET
    cases = [ET.Element("testcase", classname="tests.test_a.TestC", name="test_m")]
    assert fg._covered(cases, "tests/test_a.py::TestC")
    assert fg._covered(cases, "tests/test_a.py::TestC::test_m")
    assert not fg._covered(cases, "tests/test_a.py::TestD")
    assert not fg._covered(cases, "tests/test_a.py::TestC::test_z")


# ---- accept ----------------------------------------------------------------------

def test_accept_ok():
    assert fg.accept(result(), result(collected=4, passed=4), True) == (True, "ok")


@pytest.mark.parametrize("cand_kw, red, word", [
    (dict(junit_ok=False), True, "junit"),
    (dict(failed=1, passed=2), True, "fail"),
    (dict(errors=1), True, "error"),
    (dict(collected=2, passed=2), True, "collected"),
    (dict(skipped=1, passed=2), True, "skip"),
    ({}, False, "red"),
    (dict(rc=5), True, "rc"),
    (dict(rc=2), True, "rc"),
])
def test_accept_rejections(cand_kw, red, word):
    ok, reason = fg.accept(result(), result(**cand_kw), red)
    assert not ok and word in reason.lower()


def test_accept_base_unknown():
    ok, reason = fg.accept(result(junit_ok=False, collected=0), result(), True)
    assert not ok and reason == "base_unknown"


def test_accept_unit_test_with_empty_base():
    assert fg.accept(fg.EMPTY_BASE, result(), True) == (True, "ok")


def test_red_by_environment_is_unknown(runs):
    verdict, r = runs["rb_env"]
    assert r.failed == 1
    assert verdict == "unknown"
    assert "ModuleNotFoundError" in r.env_reason


def test_red_before_partial_missing_is_unknown(runs):
    verdict, r = runs["rb_partial"]
    assert verdict == "unknown" and "test_none.py" in r.missing


def test_env_reason_found_on_collection_error(runs):
    assert runs["broken"].env_reason.split(":")[0] in ("ImportError", "ModuleNotFoundError")
    assert runs["green"].env_reason == ""


def test_accept_unit_test_red_on_old_code_ok():
    assert fg.accept_unit_test(result(rc=1, collected=1, passed=0, failed=1)) == (True, "ok")


def test_accept_unit_test_green_on_old_code_is_defect():
    ok, reason = fg.accept_unit_test(result(collected=1, passed=1))
    assert not ok and "не ловит дефект" in reason


def test_accept_unit_test_collection_error():
    ok, reason = fg.accept_unit_test(result(rc=2, collected=1, passed=0, errors=1, junit_ok=False))
    assert not ok and "не собирается" in reason


def test_accept_unit_test_nothing_collected():
    ok, reason = fg.accept_unit_test(result(rc=5, collected=0, passed=0, junit_ok=False))
    assert not ok


def test_accept_unit_test_needs_failure_and_junit():
    assert not fg.accept_unit_test(result(rc=1, collected=1, passed=0, failed=1, junit_ok=False))[0]
    assert not fg.accept_unit_test(result(collected=1, passed=0, skipped=1))[0]


def test_accept_unit_test_env_red_is_rejected():
    ok, reason = fg.accept_unit_test(result(rc=1, collected=1, passed=0, failed=1, env_reason="ModuleNotFoundError"))
    assert not ok and "по среде" in reason


def test_accept_requires_passed_at_least_one():
    ok, reason = fg.accept(result(), result(collected=3, passed=0, skipped=0), True)
    assert not ok and "passed" in reason


# ---- loosened checks (acceptance 20.11: <id> and <id>#2 passed the gate and every critic) ----------------------
WQX09_BASE = ("import re\n" +
            r"ID_RE = re.compile(r'(?m)^\|\s*([A-Za-zА-Яа-я]{1,3}\d+(?:[.\-]\d+)*)\s*\|')" + "\n" +
            r"LINK_RE = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')" + "\n")


def test_wQX09_replay_a_regex_that_drops_its_anchor_is_a_weakening(tmp_path):
    """The promoted <id> fix (1730f833) dropped ^ of ID_RE: the priority cell <id> then counts as an ID."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/link_check.py").write_text(WQX09_BASE, encoding="utf-8")
    cand = WQX09_BASE.replace(r"(?m)^\|", r"\|")
    v = fg.weakening_violations(tmp_path, {"tools/link_check.py": cand}, "code", ("tools/link_check.py",))
    assert len(v) == 1 and "ID_RE lost anchors 1 -> 0" in v[0]
    # the fix the coordinator named (allow only leading spaces) keeps the anchor and passes
    good = WQX09_BASE.replace(r"(?m)^\|", r"(?m)^\s*\|")
    assert fg.weakening_violations(tmp_path, {"tools/link_check.py": good}, "code", ("tools/link_check.py",)) == []


def test_anchor_count_ignores_escapes_and_character_classes():
    assert fg._anchors(r"(?m)^\|\s*x\s*\|") == 1
    assert fg._anchors(r"[^a$]\^\$x") == 0
    assert fg._anchors(r"\bword\b$") == 3 and fg._anchors(r"\Ax\Z") == 2


def test_r8_replay_an_error_path_that_flips_its_result_is_a_weakening(tmp_path):
    """The promoted <id>#2 fix (f8af3bda) turned the fail-closed except branch of _cancelled from True to False."""
    base = ("class G:" "\n    @staticmethod\n    def _cancelled(event, is_current=None):\n"
            "        if is_current is not None:\n            try:\n                return not is_current()\n"
            "            except Exception:\n                return True\n        return False\n")
    (tmp_path / "gen.py").write_text(base, encoding="utf-8")
    cand = base.replace("                return True\n", "                return False\n")
    v = fg.weakening_violations(tmp_path, {"gen.py": cand}, "code", ("gen.py",))
    assert len(v) == 1 and "error path of G._cancelled returns [False] instead of [True]" in v[0]
    # the normal path may change freely
    normal = base.replace("return not is_current()", "return is_current() is False")
    assert fg.weakening_violations(tmp_path, {"gen.py": normal}, "code", ("gen.py",)) == []


def test_a_regex_added_next_to_an_anchored_one_is_not_a_loosening():
    """Critic 20.11: keys by position (f#0) or a reused name (m) compared an added unanchored regex with the old one."""
    old = "import re\ndef f(s):\n    m = re.match(r'^a', s)\n    return re.search(r'^x', s) or m\n"
    new = ("import re\ndef f(s):\n    m = re.match(r'b', s)\n    if re.search(r'y', s):\n        return m\n"
           "    m = re.match(r'^a', s)\n    return re.search(r'^x', s) or m\n")
    assert fg.loosened_checks(old, new) == []
    assert fg.loosened_checks(old, old.replace("r'^x'", "r'x'")) != []
