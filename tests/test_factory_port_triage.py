"""Port rows in the triage (coordinator, 20.11): "реализовано на ветке ... `<sha>`" waited for a merge of an old branch
that never comes, so such rows waited for good while their guard tests are red on the head. With the commit named and
no other wait the row is open as a port: ONE code task (tests = the row's own guard test, files = the ones that define
the functions the commit changed, port_from = the commit). Never a test task: without a guard test it is a question."""
import ast
import subprocess

from tools import agent_factory_import as imp
from tools import factory_port

HDR = "| ID | Формулировка | Origin | Приоритет: причина | Состояние | Зависит |\n|---|---|---|---|---|---|\n"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def _write(root, files):
    for rel, txt in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(txt, encoding="utf-8")


def _head(tmp_path, guard=True):
    """Old layout -> the commit that built the behaviour -> the unified layout (the function moved to a family file)."""
    root = tmp_path / "head"
    _write(root, {"echo_sync/__init__.py": "", "echo_sync/host.py":
                  "class Host:\n    def _stop(self, word):\n        return word == 'stop'\n"})
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "old layout")
    _write(root, {"echo_sync/host.py": "class Host:\n    def _stop(self, word):\n        if not self.whole:\n"
                                       "            return False\n        return word == 'stop'\n"})
    _git(root, "commit", "-q", "-am", "commands only on whole speech")
    sha = _git(root, "rev-parse", "--short=7", "HEAD")
    (root / "echo_sync" / "host.py").unlink()
    files = {"echo_sync/cm_kind.py": "class KindMixin:\n    def _stop(self, word):\n        return word == 'stop'\n"}
    if guard:
        files["tests/verify/question/test_v_E35000.py"] = "def test_whole():\n    assert False\n"
    _write(root, files)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "unified layout")
    return root, sha


def _backlog(tmp_path, rows):
    b = tmp_path / "B.md"
    b.write_text("## 4. Q\n### 4.1 P0\n" + HDR + rows + "## 5. H\n", encoding="utf-8")
    return b


def test_a_row_built_on_an_old_branch_is_open_as_a_port_and_other_waits_still_wait():
    md = ("## 4. Q\n### 4.1 P0\n" + HDR +
          "| E35000 | **План** | A01000 | P0 | блокер · реализовано на ветке: H6 п.2 `781c924`, в `integ-c15000`; не выложено | E33000 |\n"
          "| E36000 | **Числа** | A01000 | P1 | улучшение · реализовано в ветке, коммит не назван | — |\n"
          "| E37000 | **Порции** | A01000 | P1 | блокер · реализовано на ветке `1234abc`; ждёт облака | — |\n"
          "| E38000 | **Повтор** | A01000 | P1 | блокер · реализовано на ветке `abc1234` | дубль E35000 |\n"
          "## 5. H\n")
    rows = {r["backlog_id"]: r for r in imp.parse_section4(md)}
    assert rows["E35000"]["open"] and rows["E35000"]["port_from"] == "781c924"
    for bid in ("E36000", "E37000", "E38000"):          # no commit / another wait / a duplicate: no port
        assert not rows[bid]["open"] and rows[bid]["port_from"] == ""


def test_a_port_row_with_its_guard_test_goes_to_the_slicer_with_the_guard(tmp_path):
    # replaces the one-code-task test: the mechanical slicer is gone, the architect finds the files
    root, sha = _head(tmp_path)
    b = _backlog(tmp_path, "| E35000 | **Команды только на целой речи** | A01000 | P0 | блокер · реализовано на ветке: "
                           "H6 п.5 `%s`, в `integ-c15000`; не выложено | E33000 |\n" % sha)
    r = imp.triage_portion(b, root, set(), 20)
    assert r["holds"] == [] and r["tasks"] == []
    # the guard id comes only from the sweep verdict (none given here); the row still reaches the slicer
    assert [x["backlog_id"] for x in r["to_slice"]] == ["E35000"]


def test_a_port_row_without_a_guard_test_still_reaches_the_slicer_and_makes_no_task(tmp_path):
    # replaces the question-hold test: the row is no longer parked, the slicer owns it (empty guard)
    root, sha = _head(tmp_path, guard=False)
    b = _backlog(tmp_path, "| E35000 | **Команды** | A01000 | P0 | блокер · реализовано на ветке: `%s` | E33000 |\n" % sha)
    r = imp.triage_portion(b, root, set(), 20)
    assert r["tasks"] == [] and r["holds"] == []
    assert [(x["backlog_id"], x["guard"]) for x in r["to_slice"]] == [("E35000", "")]


def test_the_definitions_of_the_tree_are_parsed_once_until_a_file_changes(tmp_path, monkeypatch):
    root, _sha = _head(tmp_path)
    factory_port.locate(root, ["_stop"])
    parsed = []
    real = ast.parse
    monkeypatch.setattr(factory_port.ast, "parse", lambda *a, **k: parsed.append(1) or real(*a, **k))
    assert factory_port.locate(root, ["_stop"]) == ["echo_sync/cm_kind.py"] and parsed == []
    (root / "echo_sync" / "cm_kind.py").write_text("class KindMixin:\n    def _go(self):\n        return 1\n",
                                                   encoding="utf-8")
    assert factory_port.locate(root, ["_stop"]) == [] and len(parsed) == 1
