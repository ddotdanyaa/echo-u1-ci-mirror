"""fac-99: a rel row the build's books closed is never given to the slicer because an old card of it failed."""
import json

from test_factory_loop import Env, task_row, env  # noqa: <id>
from tools import factory_release as REL

SHA = "ab12cd34"
OPEN, SHUT = "rel-%s-1" % SHA, "rel-%s-2" % SHA
G_OPEN, G_SHUT = "tests/test_a.py::test_open", "tests/test_b.py::test_shut"
EMPTY = {"tasks": [], "holds": [], "stale": [], "skipped": []}
GATE = "gate: rc=1 (0 required)"


def _write(state_dir, name, data):
    rel = REL.release_dir(state_dir)
    rel.mkdir(parents=True, exist_ok=True)
    (rel / name).write_text(json.dumps(data), encoding="utf-8")


def _books(state_dir, regr=None, red=()):
    _write(state_dir, "regressions.json", regr or {})
    _write(state_dir, "red_last.json", {"sha": "a" * 40, "at": 1, "red": list(red)})
    _write(state_dir, REL.DEBT_FILE, {})


def _setup(tmp_path, monkeypatch, row, status="FAILED", reason=GATE, regr=None, red=()):
    tmp_path.mkdir(parents=True, exist_ok=True)
    e = Env(tmp_path, monkeypatch, tasks=[task_row(1, id="T1_r1", kind="code", backlog_id=row)])
    seen = []
    loop = e.loop(triage_fn=lambda **k: EMPTY, extra={"slice_fn": lambda r, cause, *a, **kw: seen.append((r, cause))})
    _books(e.state_dir, regr=regr, red=red)
    e.set_row("T1_r1", status=status, reason=reason)
    return e, loop, seen


def _tick(loop, e):
    tasks, state = loop.load()
    loop._reslice_tick(tasks, state, loop.ls(), e.clock.t)


def _closed_events(e):
    return [x for x in e.events() if x.get("status") == "debt_closed"]


def test_a_closed_row_with_a_failed_card_is_not_sliced_and_closed_once(tmp_path, monkeypatch):
    e, loop, seen = _setup(tmp_path, monkeypatch, SHUT)
    _tick(loop, e)
    assert not [s for s in seen if s[0] == SHUT]
    assert e.state()["tasks"]["T1_r1"]["reason"] == "superseded:already_green"
    assert len(_closed_events(e)) == 1
    _tick(loop, e)
    assert not [s for s in seen if s[0] == SHUT]
    assert len(_closed_events(e)) == 1


def test_a_closed_row_with_a_red_guard_is_still_sliced(tmp_path, monkeypatch):
    e, loop, seen = _setup(tmp_path, monkeypatch, SHUT, red=[G_SHUT])
    ls = loop.ls()
    ls["rel_entry"] = {SHUT: {"guard": G_SHUT, "text": "t", "priority": 0}}
    loop.save_ls(ls)
    _tick(loop, e)
    assert [s for s in seen if s[0] == SHUT]
    assert not _closed_events(e)


def test_a_row_the_regressions_book_holds_is_sliced(tmp_path, monkeypatch):
    e, loop, seen = _setup(tmp_path, monkeypatch, OPEN, regr={G_OPEN: {"row": OPEN, "at": 1}}, red=[G_OPEN])
    _tick(loop, e)
    assert [s for s in seen if s[0] == OPEN]
    assert not _closed_events(e)


def test_a_running_card_of_a_closed_row_is_untouched(tmp_path, monkeypatch):
    e, loop, seen = _setup(tmp_path, monkeypatch, SHUT)
    e.set_row("T1_r1", status="RUNNING", reason=None, lease="a" * 32, deadline=e.clock.t + 999, attempts=1)
    loop._close_rel_rows(loop.ls(), {SHUT: "x"})
    assert e.state()["tasks"]["T1_r1"]["status"] == "RUNNING"
    _tick(loop, e)
    assert e.state()["tasks"]["T1_r1"]["status"] == "RUNNING"
    assert not [s for s in seen if s[0] == SHUT]


def test_rel_entry_back_gives_a_closed_row_nothing(tmp_path, monkeypatch):
    # the books hold only OPEN: SHUT is closed there, so _lost_rows (which asks _rel_entry_back) cannot give it back
    e, loop, seen = _setup(tmp_path, monkeypatch, SHUT, regr={G_OPEN: {"row": OPEN, "at": 1}}, red=[G_OPEN])
    ls = loop.ls()
    assert loop._rel_entry_back(ls, SHUT) is None
    ls["rel_entry"] = {SHUT: {"guard": G_SHUT, "text": "t", "priority": 0}}
    assert loop._rel_entry_back(ls, SHUT) is None
    back = loop._rel_entry_back(ls, OPEN)               # control: an open row of the books is given back
    assert back and back["guard"] == G_OPEN
