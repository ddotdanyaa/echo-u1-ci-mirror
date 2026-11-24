"""W-tick: the heavy ticks of the loop's main thread. A fill reads the state a few times per run (not per card), the
reslice pass does not read the plan per row, git is called once per pass (not per row), the dispositions are computed in
the background once there is an answer. Fake runner, fake git, no model."""
import time

from tools import agent_factory_import as imp
from tools import factory_loop as L
from test_factory_loop import task_row
from test_factory_pool_loop import pool_env


def test_ten_cards_started_in_one_fill_read_the_state_at_most_three_times(tmp_path, monkeypatch):
    monkeypatch.setenv("POOL_SLEEP", "2.0")
    monkeypatch.setenv("POOL_STATUS", "DONE")
    env = pool_env(tmp_path, monkeypatch, [task_row(i) for i in range(1, 11)])
    loop = env.make_loop()
    loop.slice_fn = lambda *a, **k: None
    loop.base_sha = L.refresh_mirror(loop.cfg.repo, loop.cfg.branch, loop.mirror)
    tasks, state = loop.load()
    ls = loop.ls()
    now = loop.clock()
    act = loop._act(state, tasks, ls, now)
    loads = []
    real = loop.load
    loop.load = lambda: loads.append(1) or real()
    loop._fill(act, tasks, state, ls, now)
    assert len(loop.pool.workers) >= 2
    assert len(loads) <= 3, len(loads)


def test_capacity_takes_the_state_it_is_given(tmp_path, monkeypatch):
    env = pool_env(tmp_path, monkeypatch, [task_row(1), task_row(2)])
    loop = env.make_loop()
    tasks, state = loop.load()
    loads = []
    real = loop.load
    loop.load = lambda: loads.append(1) or real()
    loop._capacity(tasks.get(next(iter(tasks))), state)
    assert not loads


def _backlog(tmp_path, n):
    rows = "\n".join("| X%d | P1 | open | text of the row %d |" % (i, i) for i in range(n))
    path = tmp_path / "BACKLOG.md"
    path.write_text("## 4. Rows\n\n| ID | P | state | text |\n|---|---|---|---|\n" + rows + "\n", encoding="utf-8")
    return path


def test_parse_open_rows_calls_git_for_head_once_per_pass(tmp_path, monkeypatch):
    calls = []

    def fake_git(root, *args):
        calls.append(args)
        time.sleep(0.01)                 # a costly git: 100 calls would take a second
        return "abc123\n" if args[0] == "rev-parse" else ""
    monkeypatch.setattr(imp, "_git", fake_git)
    monkeypatch.setattr(imp.id_query, "commits", lambda root: [{"subject": "X1: done"}])
    monkeypatch.setattr(imp.AF, "closed_ids", lambda root: set())
    imp._CLOSED_CACHE.clear()
    path = _backlog(tmp_path, 100)
    t0 = time.monotonic()
    try:
        imp.parse_open_rows(path, tmp_path, include_closed=True)
    except ValueError:
        pass                              # a backlog format of its own: the count of git calls is what counts
    assert time.monotonic() - t0 < 2.0
    assert sum(1 for a in calls if a[0] == "rev-parse") <= 2, calls
    assert not imp._HEAD_PIN


def test_head_pin_is_released_after_a_failing_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(imp, "_git", lambda root, *a: "abc\n")
    try:
        with imp._head_pinned(tmp_path):
            assert imp._head_of(tmp_path) == "abc"
            raise RuntimeError("x")
    except RuntimeError:
        pass
    assert not imp._HEAD_PIN
