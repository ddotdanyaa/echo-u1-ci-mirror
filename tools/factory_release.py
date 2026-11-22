"""R-accept (5.1): the final build. A full cloud sweep of the whole product on an immutable snapshot, compared by test names with the red baseline.

``due`` says when a sweep is wanted (no baseline yet, or a product row was merged after the last one); ``run`` sweeps and judges.
The first sweep only WRITES the baseline (nothing is accepted, nothing blocks). Later a red test that is on no list is a regression:
it is rerun alone, and one that does not reproduce is flaky, not a regression. Two kinds of red are queued work, not breakage:
the guard test of an open backlog row (``test_v_<ID>``) and the tests of unfinished tasks (their test task merged first).
The module reads and writes only ``<state>/release/`` and imports nothing from ``tests/``.
"""
import json
import os
import re
from pathlib import Path

from tools import red_ratchet

SWEEP_SHARDS = (4, 10)      # a sweep takes 4..10 shards: only the places the task cards do not need; fewer than 4 free: it waits
RETRY_S = 120               # an unfinished sweep (a shard did not end) is repeated after this long
GUARD = re.compile(r"(?:^|/)test_v_([A-Za-z0-9]+)(?:_[^/]*)?\.py(?:::|$)")


def release_dir(state_dir) -> Path:
    return Path(state_dir) / "release"


def due(loop_state, now) -> bool:
    """True while the loop state holds no ``release`` record (the first sweep writes the baseline) and whenever a product row was merged
    after the last sweep (``promoted_total`` grew).  One sweep at a time: the loop starts the next one when the last one has ended."""
    if now < float((loop_state or {}).get("release_retry_at") or 0):
        return False
    last = (loop_state or {}).get("release")
    if not isinstance(last, dict) or not last:
        return True
    return int(loop_state.get("promoted_total") or 0) > int(last.get("promoted_total") or 0)


def shards_for(free_places) -> int:
    """How many shards a sweep takes with ``free_places`` places over what the cards need; 0 = too few, wait."""
    lo, hi = SWEEP_SHARDS
    return 0 if free_places < lo else min(hi, int(free_places))


def _read_json(path, default):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _file_of(name) -> str:
    return red_ratchet.cut(red_ratchet.norm(name)).split("::", 1)[0]


def _queued_work(name, open_ids, open_tests) -> bool:
    """A red that is the queue of work, not a breakage: the guard test of an open row, or a test of an unfinished task."""
    guard = GUARD.search(red_ratchet.cut(red_ratchet.norm(name)))
    if guard and guard.group(1) in open_ids:
        return True
    return _file_of(name) in open_tests


def regressions(state_dir) -> dict:
    """{test name: {"row": "rel-...", "at": ...}} - confirmed new reds whose ``rel-`` row is still open."""
    return _read_json(release_dir(state_dir) / "regressions.json", {})


def record_regressions(state_dir, names, row_of, at) -> None:
    book = regressions(state_dir)
    for name in names:
        book.setdefault(name, {"row": row_of.get(name, ""), "at": at})
    _write_json(release_dir(state_dir) / "regressions.json", book)


def run(*, sha, snapshot, state_dir, sweep_fn, known=(), open_ids=(), open_tests=(), recheck_fn=None, shards=SWEEP_SHARDS[1],
        known_path=red_ratchet.DEFAULT_KNOWN, env_path=red_ratchet.DEFAULT_ENV) -> dict:
    """One full sweep of ``snapshot`` and its verdict.
    -> {"sha", "sweep": {"red", "new_red", "flaky", "run_id"}, "status", "reason", "debt_rows": []}.
    status: baseline (first sweep: the reds are written as the baseline), green, new_red, sweep_incomplete (a shard did not end:
    no verdict, no acceptance, no baseline).  ``known`` = extra known names (the lists of tools/data and the baseline are read here)."""
    rel = release_dir(state_dir)
    rel.mkdir(parents=True, exist_ok=True)
    shards = max(SWEEP_SHARDS[0], min(SWEEP_SHARDS[1], int(shards)))
    _path, results, run_id = sweep_fn(src=snapshot, files=None, shards=shards, label="rel-" + str(sha)[:8],
                                      durations_path=str(rel / "durations.json"))
    out = {"sha": sha, "sweep": {"red": 0, "new_red": [], "flaky": [], "run_id": run_id}, "status": "", "reason": "", "debt_rows": []}
    missing = sorted(f for f, r in (results or {}).items() if isinstance(r, dict) and r.get("missing"))
    if missing:
        out["status"], out["reason"] = "sweep_incomplete", "no result of %d file(s): %s" % (len(missing), ", ".join(missing[:5]))
        return out
    names = []
    for f in sorted(results or {}):
        for n in (results[f] or {}).get("failed_ids") or ():
            if n not in names:
                names.append(n)
    out["sweep"]["red"] = len(names)
    base_file = rel / "baseline_red.json"
    if not base_file.is_file():
        _write_json(base_file, sorted({red_ratchet.cut(red_ratchet.norm(n)) for n in names}))
        out["status"], out["reason"] = "baseline", "the first sweep: %d red tests are the baseline" % len(names)
        return out
    baseline = set(_read_json(base_file, []))
    got = red_ratchet.compare(names, known_path, env_path, extra_known=set(known) | baseline)
    new = [n for n in got["new"] if not _queued_work(n, set(open_ids), set(open_tests))]
    if new and recheck_fn is not None:
        again = {red_ratchet.cut(red_ratchet.norm(n)) for n in (recheck_fn(list(new)) or ())}
        flaky = [n for n in new if n not in again]
        new = [n for n in new if n in again]
        if flaky:
            book = _read_json(rel / "flaky.json", [])
            _write_json(rel / "flaky.json", sorted(set(book) | set(flaky)))
            out["sweep"]["flaky"] = flaky
    out["sweep"]["new_red"] = new
    out["status"] = "new_red" if new else "green"
    out["reason"] = ("%d new red test(s)" % len(new)) if new else "no new red test"
    return out
