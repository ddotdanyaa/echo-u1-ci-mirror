"""W-rig: a "test rig" card (contract rig:true): the contract, the gate with the AST lock; no network."""
import json
import pytest
from tools import factory_architect as A
from tools import factory_gate as G

TEST_OLD = ("import pytest\n\n"
            "def helper(x):\n    return x\n\n"
            "def test_a():\n    v = helper(1)\n    assert v == 1\n\n"
            "def test_b():\n    with pytest.raises(ValueError):\n        raise ValueError()\n    assert True\n")


@pytest.fixture
def root(tmp_path):
    files = {"tests/test_rig_t1.py": TEST_OLD, "tests/helpers.py": "X = 1\n",
             "echo_sync/engine.py": "class Engine:\n    def go(self):\n        return 1\n"}
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def contract(**over):
    out = {"row": "B1", "decision": "fix", "rig": True, "why": "the stand of the test is broken",
           "test": {"use": "tests/test_rig_t1.py::test_a"},
           "parts": [{"file": "tests/test_rig_t1.py", "symbols": ["helper"], "code": "def helper(x):\n    return x + 0\n",
                      "instruction": "Replace the helper of the stand with the verified text."}]}
    out.update(over)
    return out


# ---- 1. the contract
def test_rig_contract_with_ready_code_is_valid(root):
    assert A.validate(contract(), root, bid="B1", engine="hypo") == []


def test_tests_dir_is_refused_without_rig(root):
    faults = A.validate(contract(rig=False), root, bid="B1")
    assert any("tests/**" in f for f in faults)


def test_rig_needs_ready_code_in_every_part(root):
    c = contract()
    c["parts"][0].pop("code")
    assert any("ready code" in f for f in A.validate(c, root, bid="B1"))


def test_rig_refuses_other_dirs_and_more_than_three_echo_files(root):
    c = contract()
    c["parts"].append({"file": "tools/x.py", "code": "x = 1\n", "instruction": "Replace the helper text here."})
    assert any("only tests/** and echo_sync/**" in f for f in A.validate(c, root, bid="B1"))
    assert G.rig_touch_faults(["tests/a.py"] + ["echo_sync/f%d.py" % n for n in range(4)])
    assert not G.rig_touch_faults(["tests/a.py"] + ["echo_sync/f%d.py" % n for n in range(3)])


def test_rig_only_for_strong_engines(root):
    assert any("only paid/agent" in f for f in A.validate(contract(), root, bid="B1", engine="banana"))   # W-path D (was "free"): the free steps may give a rig now
    for engine in ("paid", "agent", "hypo", "coordinator", "free", "free_main", "free_small"):
        assert A.validate(contract(), root, bid="B1", engine=engine) == []


def test_whole_file_patch_part(root):
    c = contract()
    c["parts"] = [{"file": "tests/helpers.py", "file_text": "X = 3\n", "instruction": "Replace the whole stand file with the verified text of the cloud run."}]
    assert A.validate(c, root, bid="B1", engine="paid") == []


# ---- 2. the gate
def test_is_forbidden_opens_named_tests_only_for_rig():
    named = ["tests/helpers.py"]
    assert G.is_forbidden("tests/helpers.py", "code", named=named)
    assert G.is_forbidden("tests/helpers.py", "code", named=named, rig=True) is None
    assert G.is_forbidden("tests/other.py", "code", named=named, rig=True)          # not named
    assert G.is_forbidden("tests/helpers.py", "code", named=named + ["tools/x.py"], rig=True)   # a foreign file in the card


def cand(text):
    return {"tests/test_rig_t1.py": text}


def violations(root, text):
    return G.weakening_violations(root, cand(text), "code", ["tests/test_rig_t1.py"], rig=True)


def test_lock_allows_changes_outside_test_functions_and_non_assert_lines(root):
    new = TEST_OLD.replace("return x", "return x + 0").replace("v = helper(1)", "v = helper(1)\n    w = 5")
    assert violations(root, new) == []


def test_lock_refuses_changed_assert_with_the_function(root):
    out = violations(root, TEST_OLD.replace("assert v == 1", "assert v == 2"))
    assert any(v.startswith("rig_weakens") and "test_a" in v for v in out)


def test_lock_refuses_dropped_assert_and_removed_test(root):
    out = violations(root, TEST_OLD.replace("    assert True\n", ""))
    assert any("test_b" in v for v in out)
    out = violations(root, TEST_OLD.split("def test_b")[0])
    assert any("test_b" in v for v in out)


def test_lock_refuses_changed_raises(root):
    out = violations(root, TEST_OLD.replace("pytest.raises(ValueError)", "pytest.raises(Exception)"))
    assert any("test_b" in v for v in out)


@pytest.mark.parametrize("mark", ["import time\n\ndef sl():\n    time.sleep(1)\n",
                                  "def sk():\n    pytest.skip('x')\n",
                                  "def mp(monkeypatch):\n    monkeypatch.setattr(1, 2)\n",
                                  "@pytest.mark.xfail\ndef xf():\n    pass\n"])
def test_lock_refuses_new_markers(root, mark):
    out = violations(root, TEST_OLD + "\n" + mark)
    assert any("rig_weakens" in v for v in out)


def test_lock_not_applied_without_rig(root):
    out = G.weakening_violations(root, cand(TEST_OLD.replace("== 1", "== 2")), "code", ["tests/test_rig_t1.py"])
    assert out and not any(v.startswith("rig_weakens") for v in out)


# ---- 3. acceptance
def _task(contract_obj):
    from tools.agent_factory import Task
    return Task(id="t1", title="t", goal="g", kind="code", touch_files=["tests/a.py"], tests=["tests/test_a.py"],
                depends_on=[], read_files=[], privacy_safe=True, estimated_tokens=0, contract=json.dumps(contract_obj))


def test_is_rig_task_reads_the_contract():
    assert G.is_rig_task(_task({"rig": True}))
    assert not G.is_rig_task(_task({"rig": False}))


def test_close_debt_ids_takes_ids_of_many_files_at_once(tmp_path):
    from tools import factory_release as REL
    rel = REL.release_dir(tmp_path)
    rel.mkdir(parents=True, exist_ok=True)
    book = {"tests/test_a.py": {"tests": ["tests/test_a.py::test_1", "tests/test_a.py::test_2"], "n": 1},
            "tests/test_b.py": {"tests": ["tests/test_b.py::test_1"], "n": 2},
            "tests/test_c.py": {"tests": ["tests/test_c.py::test_1"], "n": 3}}
    (rel / REL.DEBT_FILE).write_text(json.dumps(book), encoding="utf-8")
    assert REL.close_debt_ids(tmp_path, ["tests/test_a.py::test_1", "tests/test_b.py::test_1"]) == 2
    now = REL.debt(tmp_path)
    assert now["tests/test_a.py"]["tests"] == ["tests/test_a.py::test_2"] and not now["tests/test_a.py"].get("closed")
    assert now["tests/test_b.py"]["closed"] and not now["tests/test_c.py"].get("closed")
    assert REL.close_debt_ids(tmp_path, ["tests/test_b.py::test_1"]) == 0


# ---- 4. the submission
def test_rig_command_creates_one_card_idempotently(root, tmp_path):
    from tools import factory_loop as L
    cand = tmp_path / "cand"
    (cand / "tests").mkdir(parents=True)
    (cand / "tests" / "helpers.py").write_text("X = 5\n", encoding="utf-8")
    ids = tmp_path / "ids.txt"
    ids.write_text("tests/test_rig_t1.py::test_a\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    argv = ["--cand", str(cand), "--ids", str(ids), "--why", "stand of T1", "--state-dir", str(state), "--repo", str(root)]
    assert L.rig_main(argv) == 0
    assert L.rig_main(argv) == 0
    rows = json.loads((state / "plan.json").read_text(encoding="utf-8"))["tasks"]
    assert len(rows) == 1 and rows[0]["backlog_id"].startswith("rel-rig-") and rows[0]["priority"] == 0
    assert rows[0]["touch_files"] == ["tests/helpers.py"] and json.loads(rows[0]["contract"])["rig"] is True


def test_rig_command_refuses_foreign_paths(root, tmp_path):
    from tools import factory_loop as L
    cand = tmp_path / "cand"
    (cand / "tools").mkdir(parents=True)
    (cand / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
    ids = tmp_path / "ids.txt"
    ids.write_text("tests/test_rig_t1.py::test_a\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    with pytest.raises(SystemExit):
        L.rig_main(["--cand", str(cand), "--ids", str(ids), "--why", "w", "--state-dir", str(tmp_path / "state"), "--repo", str(root)])


# ---- fix1
def test_rig_without_engine_or_free_engine_is_refused(root):
    assert any("only paid/agent" in f for f in A.validate(contract(), root, bid="B1"))
    assert any("only paid/agent" in f for f in A.validate(contract(), root, bid="B1", engine="the_editor"))   # W-path D: free_small is no longer refused


def test_lock_refuses_new_assert_inside_old_test_function(root):     # stricter than the task: pinned
    out = violations(root, TEST_OLD.replace("assert v == 1", "assert v == 1\n    assert v"))
    assert any(v.startswith("rig_weakens") and "test_a" in v for v in out)


def test_rig_command_keeps_crlf_and_refuses_non_utf8(root, tmp_path):
    from tools import factory_loop as L
    cand = tmp_path / "cand"
    (cand / "tests").mkdir(parents=True)
    (cand / "tests" / "helpers.py").write_bytes(b"X = 5\r\nY = 6\r\n")
    ids = tmp_path / "ids.txt"
    ids.write_text("tests/test_rig_t1.py::test_a\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    argv = ["--cand", str(cand), "--ids", str(ids), "--why", "w", "--state-dir", str(state), "--repo", str(root)]
    assert L.rig_main(argv) == 0
    rows = json.loads((state / "plan.json").read_text(encoding="utf-8"))["tasks"]
    assert json.loads(rows[0]["contract"])["parts"][0]["file_text"] == "X = 5\r\nY = 6\r\n"
    (cand / "tests" / "data.bin").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SystemExit):
        L.rig_main(argv)


def test_a_rig_card_with_file_text_changes_the_file_in_the_work_copy(tmp_path):
    """W-rig fix2: the runner applies file_text as the whole file (CRLF kept), without asking a model."""
    from tools import agent_factory as F, agent_factory_runner as R
    from test_factory_loop import task_row
    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_x.py").write_bytes(b"def test_a():\r\n    assert 1\r\n")
    new = "def helper():\r\n    return 2\r\n\r\ndef test_a():\r\n    assert 1\r\n"
    part = {"file": "tests/test_x.py", "file_text": new, "instruction": "Replace the whole file.", "stage": 1}
    task = F.read_plan([task_row(1, touch_files=["tests/test_x.py"], contract=json.dumps({"row": "B1", "decision": "fix", "rig": True}))])["T1"]
    rc, _, err = R.edit_parts(task, [part], work, lambda *a: pytest.fail("a model was asked"), use_code=True)
    assert rc == 0, err
    assert (work / "tests" / "test_x.py").read_bytes() == new.encode("utf-8")


def test_a_rig_card_with_file_text_is_written_on_a_retry_too(tmp_path):
    """W-rig fix3: use_code False (a retry, feedback, a parallel candidate) does not hand the card to a model."""
    from tools import agent_factory as F, agent_factory_runner as R
    from test_factory_loop import task_row
    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_x.py").write_bytes(b"def test_a():\r\n    assert 1\r\n")
    new = "def test_a():\r\n    assert 1\r\n\r\ndef test_b():\r\n    assert 2\r\n"
    part = {"file": "tests/test_x.py", "file_text": new, "instruction": "Replace the whole file.", "stage": 1}
    task = F.read_plan([task_row(1, touch_files=["tests/test_x.py"], contract=json.dumps({"row": "B1", "decision": "fix", "rig": True}))])["T1"]
    rc, _, err = R.edit_parts(task, [part], work, lambda *a: pytest.fail("a model was asked"), use_code=False)
    assert rc == 0, err
    assert (work / "tests" / "test_x.py").read_bytes() == new.encode("utf-8")
