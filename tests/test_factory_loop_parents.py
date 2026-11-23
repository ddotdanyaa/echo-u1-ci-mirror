"""factory_loop: a row cut into parts is closed when all its code parts are done (parents group)."""
import json

from tools import agent_factory as F  # noqa: <id>
from tools import factory_loop as L  # noqa: <id>
from test_factory_loop import Env, git, task_row, env, empty_env, BRANCH, PY  # noqa: <id>

# The parent rig needs a public row, a private row and an unrelated row, without
# importing the answer command's private fixture corpus into this cloud suite.
REL_MD = ("## 4. Очередь\n### 4.1 P0\n| ID | Приоритет | Состояние | Формулировка |\n"
          "|---|---|---|---|\n| B3 | P1 | новая | parse the call recordings for tools/e.py |\n"
          "| B4 | P1 | новая | tools/e.py: он велел делать сразу, потому что так проще |\n"
          "| B1 | P1 | новая | строка про tools/x1.py |\n"
          "| BX | P1 | новая | строка про tools/x1.py |\n## 5. Конец\n")


def _rows():
    return [task_row(1, id="P_c1", backlog_id="B1#1", parent="B1", part=1, parts=2),
            task_row(2, id="P_c2", backlog_id="B1#2", parent="B1", part=2, parts=2)]


RECORD = {"backlog_id": "B1", "parts": 2, "children": ["B1#1", "B1#2"],
          "code_tasks": ["P_c1", "P_c2"], "test_tasks": []}


class Triage:
    def __init__(self, once=False):
        self.known, self.once = [], once

    def __call__(self, **kw):
        self.known.append(set(kw["known_backlog_ids"]))
        if self.once and len(self.known) > 1:
            return {"tasks": [], "holds": [], "stale": [], "skipped": [], "events": [], "deferred": [],
                    "profile_attempts": {}, "parents": []}
        return {"tasks": _rows(), "holds": [], "stale": [], "skipped": [], "events": [],
                "deferred": [], "profile_attempts": {}, "parents": [dict(RECORD)]}


def _ls(e):
    return json.loads((e.state_dir / "loop_state.json").read_text(encoding="utf-8"))


def _cut_row(empty_env, once=False):
    e = empty_env
    e.backlog.write_text(REL_MD, encoding="utf-8")
    tri = Triage(once)
    loop = e.loop(triage_fn=tri)
    assert loop.step().action == "TRIAGE"
    assert set(e.state()["tasks"]) == {"P_c1", "P_c2"}
    ls = loop.ls()
    ls["parents"] = {"B1": dict(RECORD)}
    loop.save_ls(ls)
    return e, loop, tri


def test_parent_stays_open_while_one_part_is_not_done(empty_env):
    e, loop, tri = _cut_row(empty_env)
    e.set_row("P_c1", status="DONE")
    e.set_row("P_c2", status="BLOCKED", blocked_reason="gate_failed")
    loop.step()
    ls = _ls(e)
    assert "B1" not in ls["closed"] and "B1" in ls["parents"]


def test_parent_closes_once_when_all_code_parts_are_done_or_promoted(empty_env):
    e, loop, tri = _cut_row(empty_env)
    e.set_row("P_c1", status="DONE")
    e.set_row("P_c2", status="PROMOTED")
    loop.step()
    ls = _ls(e)
    assert "B1" in ls["closed"] and "B1" not in ls.get("parents", {})
    loop.step()
    loop.step()
    closes = [x for x in e.events() if x["span"] == "answer" and "parent B1 closed" in x.get("reason", "")]
    assert len(closes) == 1


def test_retriage_of_a_cut_row_adds_nothing_and_knows_the_parent(empty_env):
    e, loop, tri = _cut_row(empty_env)
    tasks, state = loop.load()
    out = loop._triage(state, tasks, loop.ls(), e.clock.now())
    assert out.status == "empty"                                  # same rows: nothing appended
    assert set(e.state()["tasks"]) == {"P_c1", "P_c2"}
    assert {"B1#1", "B1#2", "B1"} <= tri.known[-1]               # the parent is known: no re-import


def test_parent_not_in_the_backlog_is_dropped_without_a_loop(empty_env):
    e, loop, tri = _cut_row(empty_env, once=True)
    e.backlog.write_text(REL_MD.replace("| B1 |", "| B7 |"), encoding="utf-8")
    e.set_row("P_c1", status="DONE")
    e.set_row("P_c2", status="DONE")
    loop.step()
    assert "B1" not in _ls(e).get("parents", {}) and "B1" not in _ls(e)["closed"]


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.


# Replaced by queue/generation coverage in test_factory_reslice.py and test_factory_decompose.py.
