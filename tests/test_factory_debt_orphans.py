"""fac-98: a debt row rel-base-<n> whose number the debt book no longer has is closed (unless its guard is red in the last
full build); the <id> sweep takes it out of every queue and says which case closed it."""
import json
import time

from test_factory_loop import Env, task_row, env  # noqa: <id>
from tools import factory_release as REL

BOOKS = ("to_slice", "slice_wait", "reslices", "quarantine", "holds", "hold_ver", "hold_hash", "rel_entry", "green_proof", "arch_decision")
G = "tests/test_g.py::test_g"


def _write(state_dir, name, data):
    rel = REL.release_dir(state_dir)
    rel.mkdir(parents=True, exist_ok=True)
    (rel / name).write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def _books(state_dir, debt, red=()):
    _write(state_dir, "regressions.json", {})
    _write(state_dir, "red_last.json", {"sha": "a" * 40, "at": 1, "red": list(red)})
    if debt is not None:
        _write(state_dir, REL.DEBT_FILE, debt)


def _rec(n, closed):
    return {"tests/test_x.py": {"tests": ["tests/test_x.py::t"], "n": n, "closed": closed}}


def test_a_debt_row_with_a_record_follows_its_record(tmp_path):
    _books(tmp_path, _rec(7, False))
    assert REL.rel_row_closed(tmp_path, "rel-base-7") is False
    _books(tmp_path, _rec(7, True))
    assert REL.rel_row_closed(tmp_path, "rel-base-7") is True


def test_a_debt_row_whose_number_is_gone_is_closed_unless_the_guard_is_red(tmp_path):
    _books(tmp_path, _rec(8, False))
    assert REL.rel_row_closed(tmp_path, "rel-base-7") is True
    assert REL.rel_row_closed(tmp_path, "rel-base-7", guard=G) is True
    _books(tmp_path, _rec(8, False), red=[G])
    assert REL.rel_row_closed(tmp_path, "rel-base-7", guard=G) is False
    assert REL.rel_row_closed(tmp_path, "rel-base-local") is False
    assert REL.rel_row_closed(tmp_path, "rel-base-abc123") is False


def test_a_missing_or_broken_debt_book_closes_nothing(tmp_path):
    _books(tmp_path, None)
    assert REL.closed_books(tmp_path) is None
    assert REL.rel_row_closed(tmp_path, "rel-base-7") is False
    _write(tmp_path, REL.DEBT_FILE, "{broken")
    assert REL.closed_books(tmp_path) is None
    assert REL.rel_row_closed(tmp_path, "rel-base-7") is False
    _books(tmp_path, {})
    _write(tmp_path, "regressions.json", "{broken")
    assert REL.closed_books(tmp_path) is None


def _loop(tmp_path, monkeypatch, cards):
    tmp_path.mkdir(parents=True, exist_ok=True)
    tasks = [task_row(i + 1, id="T%d_r1" % (i + 1), kind="code", backlog_id=b) for i, b in enumerate(cards)]
    e = Env(tmp_path, monkeypatch, tasks=tasks)
    return e, e.loop(triage_fn=lambda **k: {"tasks": [], "holds": [], "stale": [], "skipped": []})


def _put(loop, row, guard):
    ls = loop.ls()
    for key in BOOKS:
        ls.setdefault(key, {})[row] = {"guard": guard, "at": 1} if key == "rel_entry" else ("x" if key != "slice_wait" else time.time() + 99)
    ls.setdefault("to_slice", {})[row] = {"guard": guard, "at": 1}
    loop.save_ls(ls)


def test_the_sweep_closes_an_orphan_debt_row_and_leaves_the_others(tmp_path, monkeypatch):
    e, loop = _loop(tmp_path, monkeypatch, cards=("rel-base-9", "rel-base-8"))
    _books(e.state_dir, _rec(8, False), red=["tests/test_red.py::t"])
    _put(loop, "rel-base-9", G)
    _put(loop, "rel-base-8", G)
    _put(loop, "rel-base-10", "tests/test_red.py::t")
    loop._sweep_closed_rel(time.time())
    ls = loop.ls()
    for key in BOOKS:
        assert "rel-base-9" not in (ls.get(key) or {}), key
        assert "rel-base-8" in (ls.get(key) or {}), key
        assert "rel-base-10" in (ls.get(key) or {}), key
    _tasks, state = loop.load()
    assert state["tasks"]["T1_r1"]["status"] == "FAILED" and state["tasks"]["T1_r1"]["reason"] == "superseded:already_green"
    assert state["tasks"]["T2_r1"]["status"] == "READY"
    done = [x for x in e.events() if x.get("status") == "debt_closed"]
    assert [x["backlog_id"] for x in done] == ["rel-base-9"]
    assert "number gone" in done[0]["reason"]
