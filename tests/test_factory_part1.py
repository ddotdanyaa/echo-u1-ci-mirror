"""W-part 1: a debt / regression row whose tests are red in neither of the two last full builds is closed."""
import json

from tools import factory_release as REL


def _sweep(*failed, files=()):
    def fn(**kw):
        results = {f: {"failed_ids": []} for f in files}
        for tid in failed:
            results.setdefault(tid.split("::")[0], {"failed_ids": []})["failed_ids"].append(tid)
        return "results.json", results, 7
    return fn


def _run(tmp_path, sha, *failed, files=()):
    return REL.run(sha=sha, snapshot=tmp_path, state_dir=tmp_path, sweep_fn=_sweep(*failed, files=files),
                   known=set(), open_ids=set(), open_tests=set())


def test_red_last_is_written_and_rotated(tmp_path):
    _run(tmp_path, "aaaa1111", "tests/test_x.py::t_one")
    _run(tmp_path, "bbbb2222", "tests/test_x.py::t_two")
    last = REL.red_last(tmp_path)
    assert last["sha"] == "bbbb2222" and last["red"] == ["tests/test_x.py::t_two"]
    prev = json.loads((tmp_path / "release" / "red_prev.json").read_text(encoding="utf-8"))
    assert prev["sha"] == "aaaa1111"


def test_debt_files_green_in_two_builds_are_closed(tmp_path):
    reds = ["tests/test_x.py::t_one", "tests/test_x.py::t_two"]
    _run(tmp_path, "aaaa1111", *reds)                                    # baseline
    first = _run(tmp_path, "bbbb2222", *reds, files=["tests/test_x.py"])
    assert [r["file"] for r in first["debt_rows"]] == ["tests/test_x.py"]
    key = first["debt_rows"][0]["key"]
    one = _run(tmp_path, "cccc3333", files=["tests/test_x.py"])          # green once: not yet
    assert key not in one["closed_rows"]
    assert REL.debt(tmp_path)["tests/test_x.py"]["closed"] is False
    two = _run(tmp_path, "dddd4444", files=["tests/test_x.py"])          # green twice: closed
    assert two["closed_rows"] == [key]


def test_a_test_red_in_the_last_build_keeps_the_row(tmp_path):
    reds = ["tests/test_x.py::t_one", "tests/test_x.py::t_two"]
    _run(tmp_path, "aaaa1111", *reds)
    first = _run(tmp_path, "bbbb2222", *reds, files=["tests/test_x.py"])
    _run(tmp_path, "cccc3333", files=["tests/test_x.py"])
    again = _run(tmp_path, "dddd4444", "tests/test_x.py::t_two", files=["tests/test_x.py"])
    assert first["debt_rows"][0]["key"] not in again["closed_rows"]


def test_regression_rows_close_after_two_green_builds(tmp_path):
    _run(tmp_path, "aaaa1111")
    REL.record_regressions(tmp_path, ["tests/test_y.py::t_new"], {"tests/test_y.py::t_new": "rel-bbbb2222-1"}, 1.0)
    _run(tmp_path, "bbbb2222", "tests/test_y.py::t_new")
    assert _run(tmp_path, "cccc3333")["closed_rows"] == []
    assert _run(tmp_path, "dddd4444")["closed_rows"] == ["rel-bbbb2222-1"]
    assert REL.regressions(tmp_path) == {}
