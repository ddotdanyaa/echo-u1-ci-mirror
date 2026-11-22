"""<id>: a row that names no file gets candidate files (its ID in the code, commits that name it, its identifiers,
the project's own .md paragraphs that tie Russian words to a module) and becomes a hold the free head model answers;
a scope it picked comes back to the triage as ``scopes`` and the row becomes a normal task pair."""
import subprocess

import pytest

from tools import agent_factory_import as imp
from tools import factory_holds as H

HDR = "| ID | Формулировка | Origin | Приоритет: причина | Состояние | Зависит |\n|---|---|---|---|---|---|\n"
ROWS = [
    ("E60000", "Медленный путь надо ускорить без лишних задержек", "P1"),
    ("E62000", "Проверка `_fits` режет ответ слишком рано", "P0"),
    ("E63000", "Подключить базу законов к ответу ассистента", "P2"),
    ("E51000", "Без путей вообще", "P3"),
    ("E64000", "Ваши слова 14:36 (L29818000): «она молчит» про погоду", "P1"),
    ("E66000", "Ваши слова 14:36 (L29818000): «она молчит» опять", "P1"),
]


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.com", "PATH": __import__("os").environ.get("PATH", "")})


def _backlog(rows):
    return "## 4. Q\n### 4.2 P1\n" + HDR + "".join(
        "| %s | %s | x | %s | новая | — |\n" % r for r in rows) + "## 5. H\n"


@pytest.fixture
def ctree(tmp_path):
    root = tmp_path / "r"
    files = {
        "echo_sync/__init__.py": "# E60000\n", "tools/__init__.py": "",
        "echo_sync/x.py": "# E60000: the slow path guard\n# E66000 too\ndef slow():\n    return 1\n",
        "echo_sync/fit.py": "def _fits(a):\n    return a\n",
        "echo_sync/law_base.py": "def load():\n    return []\n",
        "echo_sync/other.py": "def other():\n    return 0\n",
        "tools/factory_zz.py": "# E60000\n",
        "tests/test_x.py": "# E60000\ndef test_a():\n    assert True\n",
        "docs/LAW.md": "Модуль `law_base.py` хранит базу законов для ответа ассистента.\n\n"
                       "Другой абзац про `other.py`: погода и облака.\n",
    }
    for rel, txt in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    b = tmp_path / "B.md"
    b.write_text(_backlog(ROWS), encoding="utf-8")
    return root, b


def _holds(r):
    return {h["backlog_id"]: h["question"] for h in r["holds"]}


def _skip(r):
    return {x["backlog_id"]: x["reason"] for x in r["skipped"]}


def test_id_in_a_comment_gives_a_candidate_hold_not_a_skip(ctree):
    root, b = ctree
    r = imp.triage_portion(b, root, set(), 50)
    q = _holds(r)["E60000"]
    assert H.kind_of(q) == "candidates" and "E60000" not in _skip(r)
    assert H.candidates(q)[0][0] == "echo_sync/x.py"
    assert "(P1)" in q and "Медленный" not in q               # paths and tags only, never the row text


def test_backticked_symbol_finds_the_defining_module(ctree):
    root, _ = ctree
    cands = [c[0] for c in imp.candidate_files(root, "E62000", "Проверка `_fits` режет ответ слишком рано")]
    assert cands[0] == "echo_sync/fit.py"


def test_docs_bridge_ties_russian_words_to_a_module(ctree):
    root, _ = ctree
    cands = imp.candidate_files(root, "E63000", "Подключить базу законов к ответу ассистента")
    assert cands and cands[0][0] == "echo_sync/law_base.py" and "doc" in cands[0][2]


def test_candidates_never_tests_protected_or_init(ctree):
    root, _ = ctree
    assert imp._protected("tools/factory_zz.py")
    cands = [c[0] for c in imp.candidate_files(root, "E60000", "Медленный путь")]
    assert "echo_sync/x.py" in cands
    assert not [c for c in cands if c.startswith("tests/") or c.endswith("__init__.py") or imp._protected(c)]


def test_no_candidates_stays_a_skip(ctree):
    root, b = ctree
    r = imp.triage_portion(b, root, set(), 50)
    assert "нет упомянутых" in _skip(r)["E51000"] and "кандидатов нет" in _skip(r)["E51000"]


def test_owner_words_row_needs_a_strong_signal_and_never_shows_its_text(ctree):
    root, b = ctree
    r = imp.triage_portion(b, root, set(), 50)
    assert "E64000" in _skip(r) and "E64000" not in _holds(r)       # only a docs word (погода): no hold
    q = _holds(r)["E66000"]                                      # its ID is in echo_sync/x.py
    assert H.kind_of(q) == "candidates" and "echo_sync/x.py" in q
    assert "молчит" not in q and "14:36" not in q


def test_holds_keep_backlog_priority_order(ctree):
    root, b = ctree
    r = imp.triage_portion(b, root, set(), 50)
    order = [h["backlog_id"] for h in r["holds"] if H.kind_of(h["question"]) == "candidates"]
    assert order.index("E62000") < order.index("E60000")


def test_a_public_row_with_only_word_matches_gets_no_hold(ctree):
    # <id> live 20.11: <id>/<id>/<id> (design, proxy watchdog, a work rule) were candidates holds by words alone; the free
    # head scoped them wrongly, the coordinator rejected all 5 promotions. Words rank files, they never make a hold.
    root, b = ctree
    cands = imp.candidate_files(root, "E63000", "Подключить базу законов к ответу ассистента")
    assert cands and cands[0][1] >= imp.CAND_MIN and all(c[2] == ["doc"] for c in cands)
    r = imp.triage_portion(b, root, set(), 50)
    assert "E63000" not in _holds(r) and "кандидаты слабые" in _skip(r)["E63000"]
    assert not imp.strong_candidates(cands)


def test_an_attribute_that_is_only_read_is_not_a_defined_name(tmp_path):
    root = tmp_path / "r"
    (root / "echo_sync").mkdir(parents=True)
    (root / "echo_sync" / "a.py").write_text("def f(o):\n    return o.held_reply\n", encoding="utf-8")
    (root / "echo_sync" / "b.py").write_text("class C():\n    def __init__(self):\n        self.own_reply = 1\n",
                                             encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    read = imp.candidate_files(root, "E70000", "флаг `held_reply` не читается")
    assert not any("sym" in c[2] for c in read)
    made = imp.candidate_files(root, "E71000", "флаг `own_reply` не читается")
    assert made and made[0][0] == "echo_sync/b.py" and "sym" in made[0][2]


def test_git_signal_is_a_commit_subject_naming_the_id_with_code_files(tmp_path):
    root = tmp_path / "r"
    (root / "echo_sync").mkdir(parents=True)
    (root / "echo_sync" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "echo_sync" / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    (root / "echo_sync" / "a.py").write_text("def f():\n    return 3\n", encoding="utf-8")
    _git(root, "commit", "-q", "-am", "E80000: f returns three")
    (root / "echo_sync" / "b.py").write_text("def g():\n    return 4\n", encoding="utf-8")
    _git(root, "commit", "-q", "-am", "tidy g", "-m", "also mentions E81000 and E80000 in the body")
    by_subject = imp.candidate_files(root, "E80000", "строка без имён")
    assert by_subject and by_subject[0][0] == "echo_sync/a.py" and "git" in by_subject[0][2]
    assert not any("git" in c[2] for c in imp.candidate_files(root, "E81000", "строка без имён"))


def test_weak_candidate_holds_names_rows_whose_candidates_are_words_only(ctree):
    root, b = ctree
    weak = imp.weak_candidate_holds(root, b, ["E60000", "E63000", "E64000", "E99000"])
    assert set(weak) == {"E63000", "E64000"} and all("кандидаты слабые" in w for w in weak.values())


def test_a_picked_scope_makes_the_normal_task_pair(ctree):
    root, b = ctree
    scopes = {"E60000": {"touch_files": ["echo_sync/x.py", "echo_sync/ghost.py", "tools/factory_zz.py"],
                      "note": "Speed up slow in x"}}
    r = imp.triage_portion(b, root, set(), 50, scopes=scopes)
    t = {x["id"]: x for x in r["tasks"]}
    assert t["bl_E60000_test"]["kind"] == "unit_test" and t["bl_E60000_test"]["touch_files"] == ["tests/test_factory_e60000.py"]
    main = t["bl_E60000"]
    assert main["touch_files"] == ["echo_sync/x.py"] and main["depends_on"] == ["bl_E60000_test"]
    assert "Speed up slow in x" in main["goal"] and main["privacy_safe"] is True
    assert "E60000" not in _holds(r)


def test_a_scope_of_only_missing_or_protected_files_is_ignored(ctree):
    root, b = ctree
    r = imp.triage_portion(b, root, set(), 50, scopes={"E60000": {"touch_files": ["tools/factory_zz.py"], "note": ""}})
    assert "bl_E60000" not in {x["id"] for x in r["tasks"]}


def test_an_id_as_a_code_label_or_a_name_is_no_id_signal(tmp_path):
    # <id> critic: backlog <id>/<id> met timer_policy's Relation('<id>', ..) labels; a name ``<id> = 1`` is code, not a row
    root = tmp_path / "r"
    (root / "echo_sync").mkdir(parents=True)
    (root / "echo_sync" / "a.py").write_text("R5000 = 1\nX = [Relation('R6000', True), u'U44000', 'E90000']\n", encoding="utf-8")
    (root / "echo_sync" / "b.py").write_text("# R5000: the tail guard\nY = 'U44000 (a): said with operands'\n",
                                             encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    ids = {b: [c[0] for c in imp.candidate_files(root, b, "строка") if "id" in c[2]] for b in ("R5000", "R6000", "U44000", "E90000")}
    assert ids == {"R5000": ["echo_sync/b.py"], "R6000": [], "U44000": ["echo_sync/b.py"], "E90000": []}


def test_a_plain_word_many_files_define_is_no_sym(tmp_path):
    # <id> critic: <id> (`sys.path` in a tests conftest row) became a hold by ``path``, assigned in many modules
    root = tmp_path / "r"
    (root / "echo_sync").mkdir(parents=True)
    for n in "abc":
        (root / "echo_sync" / (n + ".py")).write_text("path = 1\nhold_gap = 2\n" if n == "a" else "path = 1\n",
                                                      encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    assert not imp.strong_candidates(imp.candidate_files(root, "E91000", "conftest кладёт `x` в `sys.path`"))
    made = imp.candidate_files(root, "E92000", "`hold_gap` и `sys.path`")
    assert made[0][0] == "echo_sync/a.py" and "sym" in made[0][2] and imp.strong_candidates(made)
