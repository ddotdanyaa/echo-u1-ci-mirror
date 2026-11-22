"""Round 6, C: a row that is too big is cut into linked parts (unit_test -> code pairs) instead of a question."""
import subprocess
from pathlib import Path

import pytest

from tools import agent_factory as F
from tools import agent_factory_import as imp

HDR = "| ID | Формулировка | Origin | Приоритет: причина | Состояние | Зависит |\n|---|---|---|---|---|---|\n"
MODULES = ["a1", "a2", "a3", "a4", "a5", "a6", "b1"]


def _repo(tmp_path, row_text, extra_files=None, rows=None):
    root = tmp_path / "head"
    files = {"echo_sync/__init__.py": "", "tools/__init__.py": ""}
    for m in MODULES:
        files["echo_sync/%s.py" % m] = "def f_%s():\n    return 1\n" % m
    files["echo_sync/a2.py"] = "from echo_sync.a1 import f_a1\n\ndef f_a2():\n    return f_a1()\n"
    files.update(extra_files or {})
    for rel, txt in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(txt, encoding="utf-8")
    for a in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.test", *a], check=True, capture_output=True)
    b = tmp_path / "B.md"
    b.write_text("## 4. Q\n### 4.2 P1\n" + HDR + (rows or "| B1 | %s | x | P1 | новая | — |\n" % row_text) + "## 5. H\n", encoding="utf-8")
    return root, b


def _paths(names):
    return " ".join("`echo_sync/%s.py`" % n for n in names)


BIG = "Правим контроллер реплик по всем модулям сразу: " + _paths(MODULES[:6]) + ", все вместе при живом плане и тишине в канале"


def test_a_row_with_too_many_files_is_cut_into_pairs(tmp_path):
    root, b = _repo(tmp_path, BIG)
    r = imp.triage_portion(b, root, set(), 20)
    assert r["holds"] == [] and r["skipped"] == []
    tasks = {t["id"]: t for t in r["tasks"]}
    code = [t for t in r["tasks"] if t["kind"] == "code"]
    tests = [t for t in r["tasks"] if t["kind"] == "unit_test"]
    assert len(code) == 6 and len(tests) == 6                     # <id>: one-file parts
    assert all(len(t["touch_files"]) == 1 for t in code)
    assert sorted(f for t in code for f in t["touch_files"]) == sorted("echo_sync/%s.py" % m for m in MODULES[:6])
    for c in code:
        assert c["parent"] == "B1" and c["parts"] == 6 and c["part"] in range(1, 7)
        assert c["backlog_id"] == "B1#%d" % c["part"]
        (dep,) = c["depends_on"]
        assert tasks[dep]["kind"] == "unit_test" and tasks[dep]["touch_files"] == tasks[dep]["tests"] == c["tests"]
        assert tasks[dep]["backlog_id"] == c["backlog_id"] and tasks[dep]["parent"] == "B1"
        # live 19.11: the author of the test saw no code (read_files=[]) and imported invented modules
        assert tasks[dep]["read_files"] == c["touch_files"]
        assert all(f[:-3].replace("/", ".") in tasks[dep]["goal"] for f in c["touch_files"])
    F.read_plan(r["tasks"])                                      # the plan accepts them as they are


def test_import_related_files_are_still_separate_one_file_parts(tmp_path):
    root, b = _repo(tmp_path, BIG)
    code = [t for t in imp.triage_portion(b, root, set(), 20)["tasks"] if t["kind"] == "code"]
    parts = {f: t["part"] for t in code for f in t["touch_files"]}
    assert parts["echo_sync/a1.py"] != parts["echo_sync/a2.py"]  # <id>: a2 imports a1, but each file is its own part


def test_parent_record_tells_the_loop_when_the_row_is_done(tmp_path):
    root, b = _repo(tmp_path, BIG)
    r = imp.triage_portion(b, root, set(), 20)
    (rec,) = r["parents"]
    assert rec["backlog_id"] == "B1" and rec["parts"] == 6 and rec["children"] == ["B1#%d" % i for i in range(1, 7)]
    ids = {t["id"] for t in r["tasks"]}
    assert set(rec["code_tasks"]) | set(rec["test_tasks"]) == ids


def test_child_ids_are_stable_and_a_rerun_adds_nothing(tmp_path):
    root, b = _repo(tmp_path, BIG)
    first = imp.triage_portion(b, root, set(), 20)
    second = imp.triage_portion(b, root, set(), 20)
    assert [t["id"] for t in first["tasks"]] == [t["id"] for t in second["tasks"]]
    known = {t["backlog_id"] for t in first["tasks"]}             # what the loop knows after appending
    third = imp.triage_portion(b, root, known, 20)
    assert third["tasks"] == [] and any("уже известна" in x["reason"] for x in third["skipped"])


def test_parts_that_did_not_fit_come_in_the_next_portion(tmp_path):
    root, b = _repo(tmp_path, BIG)
    first = imp.triage_portion(b, root, set(), 2)                # room for one pair only
    assert len(first["tasks"]) == 2 and [d["backlog_id"] for d in first["deferred"]] == ["B1"]
    known = {t["backlog_id"] for t in first["tasks"]}
    second = imp.triage_portion(b, root, known, 2)
    assert {t["backlog_id"] for t in second["tasks"]} == {"B1#2"} and second["deferred"]
    assert not {t["id"] for t in first["tasks"]} & {t["id"] for t in second["tasks"]}


def test_a_limit_smaller_than_the_first_pair_is_a_question(tmp_path):
    root, b = _repo(tmp_path, BIG)
    r = imp.triage_portion(b, root, set(), 1)
    assert r["tasks"] == [] and "limit меньше первой части" in r["holds"][0]["question"]


def test_a_long_text_with_several_files_is_cut_by_file(tmp_path):
    long_row = "Описание " + "очень длинное слово " * 400 + _paths(["a3", "a4"])      # 8000 > MAX_TEXT (6000)
    root, b = _repo(tmp_path, long_row)
    r = imp.triage_portion(b, root, set(), 20)
    code = [t for t in r["tasks"] if t["kind"] == "code"]
    assert [t["touch_files"] for t in code] == [["echo_sync/a3.py"], ["echo_sync/a4.py"]]
    assert all(len(t["goal"]) <= imp.MAX_TEXT for t in r["tasks"])
    F.read_plan(r["tasks"])


def test_a_long_text_with_one_file_cannot_be_cut_honestly(tmp_path):
    long_row = "Описание " + "очень длинное слово " * 400 + _paths(["a3"])
    root, b = _repo(tmp_path, long_row)
    r = imp.triage_portion(b, root, set(), 20)
    assert r["tasks"] == [] and r["holds"][0]["question"].startswith("разбить на подзадачи")


def test_too_many_parts_stay_a_question(tmp_path):
    names = ["m%d" % i for i in range(61)]      # 13 parts of <= 5 files > MAX_PARTS (10)
    root, b = _repo(tmp_path, "Всё сразу " + _paths(names) + " при живом плане и тишине в канале сегодня",
                    extra_files={"echo_sync/%s.py" % n: "x = 1\n" for n in names})
    r = imp.triage_portion(b, root, set(), 140)
    assert r["tasks"] == [] and "частей получилось больше" in r["holds"][0]["question"]


def test_no_part_invents_a_file_or_a_test(tmp_path):
    root, b = _repo(tmp_path, BIG)
    r = imp.triage_portion(b, root, set(), 20)
    for t in r["tasks"]:
        if t["kind"] == "code":
            assert all((root / f).is_file() for f in t["touch_files"])
            assert not any((root / f).exists() for f in t["tests"])      # the test is made by its unit_test part
        else:
            assert t["touch_files"] == t["tests"] and t["touch_files"][0].startswith("tests/test_factory_")


def test_a_foreign_test_file_with_the_part_slug_blocks_the_row(tmp_path):
    root, b = _repo(tmp_path, BIG, extra_files={"tests/test_factory_b1_c1.py": "def test_x():\n    assert True\n"})
    r = imp.triage_portion(b, root, set(), 20)
    assert r["tasks"] == [] and "занят" in r["skipped"][0]["reason"]


def test_a_private_row_is_not_cut(tmp_path):
    root, b = _repo(tmp_path, "parse the call recordings " + _paths(MODULES[:6]) + " при живом плане и тишине в канале")
    r = imp.triage_portion(b, root, set(), 20)
    assert not [t for t in r["tasks"] if t.get("parent")]


def test_a_row_of_three_files_and_a_text_under_the_limit_is_one_task(tmp_path):
    """<id>: SLICE_FILES 3 (was MAX_TOUCH 5), MAX_TEXT 6000: this row (three files, 2500 characters) stays one task."""
    row = "Описание " + "довольно длинное слово " * 100 + _paths(MODULES[:3])
    assert 1500 < len(row) <= imp.MAX_TEXT
    root, b = _repo(tmp_path, row)
    r = imp.triage_portion(b, root, set(), 20)
    assert r["holds"] == [] and r["parents"] == []
    code = [t for t in r["tasks"] if t["kind"] == "code"]
    assert len(code) == 1 and sorted(code[0]["touch_files"]) == sorted("echo_sync/%s.py" % m for m in MODULES[:3])
    assert "parent" not in code[0]
