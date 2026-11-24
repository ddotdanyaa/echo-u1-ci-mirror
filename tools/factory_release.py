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
import time
import uuid
from pathlib import Path

from tools import red_ratchet

SWEEP_SHARDS = (4, 10)      # a sweep takes 4..10 shards: only the places the task cards do not need; fewer than 4 free: it waits
RETRY_S = 120               # an unfinished sweep (a shard did not end) is repeated after this long
RUN_FILE = "run.json"       # the build in flight (run id, shards, results read so far): the loop may be restarted, the run is picked up
FILL_ROUNDS = 2             # files with no result are run again alone at most this many times
RESUME_FAILS = 2            # a run that cannot be waited for this many times is given up (counted only here, in run.json; run() reports "gave_up")
GUARD = re.compile(r"(?:^|/)test_v_([A-Za-z0-9]+)(?:_[^/]*)?\.py(?:::|$)")


def release_dir(state_dir) -> Path:
    return Path(state_dir) / "release"


def due(loop_state, now) -> bool:
    """True while the loop state holds no ``release`` record (the first sweep writes the baseline) and whenever a product row was merged
    after the last sweep (``promoted_total`` grew).  One sweep at a time: the loop starts the next one when the last one has ended."""
    if now < float((loop_state or {}).get("release_retry_at") or 0):
        return False
    if resumable(loop_state):                       # a run is out there (the loop was restarted): it is taken up, whatever else is due
        return True
    last = (loop_state or {}).get("release")
    if not isinstance(last, dict) or not last:
        return True
    seen = max(int(last.get("promoted_total") or 0), int(loop_state.get("release_skip_total") or 0))     # a skipped tick counts as seen
    return int(loop_state.get("promoted_total") or 0) > seen


def resumable(loop_state):
    """The info of the run a build left in flight (``release_run.run``, set while it sweeps, closed with the verdict), else None."""
    rr = (loop_state or {}).get("release_run")
    info = rr.get("run") if isinstance(rr, dict) and not rr.get("closed") else None
    return info if isinstance(info, dict) and info.get("run_id") else None


def worth_a_run(loop_state, sha, tree, n_rows) -> bool:
    """False when there is nothing to accept (``n_rows`` = 0) and the tree of ``sha`` was already swept (the last verdict, any status)
    or is being swept now (a run in flight: the loop's own ``_rel``, or ``resumable``, never reaches here): a second sweep of the same
    code tells nothing new.  The last verdict counts whatever its status; a build that gave none (sweep_incomplete, failed) does not.
    No baseline is needed for that: a first sweep of an unseen tree still runs (it writes the baseline)."""
    if n_rows:
        return True
    last = (loop_state or {}).get("release")
    if not isinstance(last, dict) or not last:
        return True
    return not ((sha and last.get("sha") == sha) or (tree and last.get("tree") == tree))


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


def _locked(path):
    """A lock file next to ``path`` (O_EXCL; a lock older than 30 s is taken over): two runs never read the same attempt number."""
    class _Lock:
        def __enter__(self):
            lock = Path(str(path) + ".lock")
            lock.parent.mkdir(parents=True, exist_ok=True)
            end = time.time() + 10
            while True:
                try:
                    os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                    break
                except FileExistsError:
                    try:
                        if time.time() - lock.stat().st_mtime > 30:
                            lock.unlink()
                            continue
                    except OSError:
                        pass
                    if time.time() > end:
                        break                       # a stuck lock must not stop the build: the random suffix still keeps the name unique
                    time.sleep(0.05)
            self.lock = lock
            return self

        def __exit__(self, *exc):
            try:
                self.lock.unlink()
            except OSError:
                pass
    return _Lock()


def next_label(state_dir, sha, prefix="rel") -> str:
    """``<prefix>-<sha8>-<n>-<rand>``: the mirror branch of a sweep is new for every attempt (a branch of an earlier attempt stays on
    the mirror, a push without force to its name is refused).  The attempt number per prefix and SHA is kept in
    ``<state>/release/attempts.json`` under a lock; the random suffix keeps the name new even when that state was reset.
    (A finished cloud run of the SHA is not reused: ``echo_cloud.sweep`` hands back a run id only together with its results,
    which ``run`` consumes at once, so no finished run is left to pick up, and the sweep module is not this task's to change.)"""
    key = "%s-%s" % (prefix, str(sha)[:8])
    path = release_dir(state_dir) / "attempts.json"
    with _locked(path):
        book = _read_json(path, {})
        n = int(book.get(key) or 0) + 1
        book[key] = n
        _write_json(path, book)
    return "%s-%d-%s" % (key, n, uuid.uuid4().hex[:6])


def _load_run(rel, sha, resume, drop=None) -> dict:
    """The record of the build of ``sha`` in flight (``release/run.json``): the run's info (``info``: run_id, branch, shards, ...), the
    results already read (``good``), the files still without a result (``missing``), the fill-in runs spent (``fills``) and the
    failed waits (``fails``).  A record of another SHA is dropped (its run info is handed to ``drop`` so the branch goes); ``resume``
    (the loop state's copy of the run info) stands in for a lost file, but not for a run whose results were already read."""
    rec = _read_json(rel / RUN_FILE, {})
    if rec.get("sha") != sha:
        if drop and isinstance(rec.get("info"), dict):
            _drop(drop, rec["info"])
        rec = {}
    if (not rec.get("info") and not rec.get("good") and not rec.get("missing") and not rec.get("fills")
            and isinstance(resume, dict) and resume.get("run_id")):
        rec = {**rec, "info": dict(resume), "runs": [dict(resume)]}     # its shards are then reported too
    rec["sha"] = sha
    for key, default in (("good", {}), ("missing", []), ("fills", 0), ("fails", 0), ("runs", [])):
        if not isinstance(rec.get(key), type(default)):
            rec[key] = default
    return rec


def _drop(drop, info) -> None:
    """Remove the mirror branch of a run that is given up (a run that did not end keeps its branch); a refusal is harmless."""
    try:
        if info.get("branch"):
            drop(info)
    except Exception:       # noqa: BLE001  a stale branch is harmless
        pass


def _shard_report(rec, results) -> dict:
    """{"shards": [files per shard], "longest_s": measured seconds of the slowest shard, "longest_shard": its number} of the first run
    (a run taken up from the loop state alone is entered into ``runs`` by ``_load_run``; with no run at all the lists are empty)."""
    runs = [r for r in rec.get("runs") or () if isinstance(r, dict) and r.get("parts")]
    if not runs:
        return {"shards": [], "longest_s": None, "longest_shard": None}
    parts = runs[0]["parts"]
    secs = [round(sum(float((results.get(f) or {}).get("seconds") or 0) for f in p), 1) for p in parts]
    longest = max(range(len(secs)), key=lambda i: secs[i]) if secs else None
    return {"shards": [len(p) for p in parts], "longest_s": secs[longest] if secs else None,
            "longest_shard": None if longest is None else longest + 1}


def run(*, sha, snapshot, state_dir, sweep_fn, known=(), open_ids=(), open_tests=(), recheck_fn=None, shards=SWEEP_SHARDS[1],
        known_path=red_ratchet.DEFAULT_KNOWN, env_path=red_ratchet.DEFAULT_ENV, resume=None, on_run=None, drop_fn=None) -> dict:
    """One full sweep of ``snapshot`` and its verdict.
    -> {"sha", "sweep": {"red", "new_red", "flaky", "run_id"}, "status", "reason", "debt_rows": [], "shards", "longest_s", "runs"}.
    status: baseline (first sweep: the reds are written as the baseline), green, new_red, sweep_incomplete (a shard did not end:
    no verdict, no acceptance, no baseline).  ``known`` = extra known names (the lists of tools/data and the baseline are read here).
    The run is kept in ``release/run.json`` (and handed to ``on_run``) the moment it exists: a call that finds a record of the same
    SHA (or gets ``resume``) takes that run up instead of starting another.  Files with no result (a shard that did not end) are
    run again alone, up to FILL_ROUNDS times, and added to the results already read.
    A run that could not be waited for RESUME_FAILS times is given up HERE (the only counter): run.json goes, ``drop_fn(info)`` removes
    its mirror branch, and the result is sweep_incomplete with ``gave_up`` true (the loop forgets the run)."""
    rel = release_dir(state_dir)
    rel.mkdir(parents=True, exist_ok=True)
    shards = max(SWEEP_SHARDS[0], min(SWEEP_SHARDS[1], int(shards)))
    dpath = str(rel / "durations.json")
    rec = _load_run(rel, sha, resume, drop_fn)

    def note(info):
        rec["info"] = dict(info)
        rec["runs"].append(dict(info))
        _write_json(rel / RUN_FILE, rec)
        if on_run:
            on_run(dict(info))

    def absorb(res):
        for f, r in (res or {}).items():
            if isinstance(r, dict) and r.get("missing"):
                if f not in rec["good"] and f not in rec["missing"]:
                    rec["missing"].append(f)
            else:
                rec["good"][f] = r
                if f in rec["missing"]:
                    rec["missing"].remove(f)
        rec["info"] = None
        _write_json(rel / RUN_FILE, rec)

    run_id = (rec.get("info") or {}).get("run_id")
    if rec.get("info"):                                         # a run of this SHA is out there: wait for it, never publish again
        try:
            _p, res, rid = sweep_fn(src=snapshot, resume=dict(rec["info"]), wait_s=None, durations_path=dpath)
        except Exception:
            rec["fails"] += 1
            if rec["fails"] >= RESUME_FAILS:                    # the run is gone (deleted, expired): the next call builds a new one
                (rel / RUN_FILE).unlink(missing_ok=True)
                _drop(drop_fn, rec["info"])
                return {"sha": sha, "sweep": {"red": 0, "new_red": [], "flaky": [], "run_id": run_id}, "status": "sweep_incomplete",
                        "reason": "run %s could not be waited for %d times: given up" % (run_id, rec["fails"]), "debt_rows": [],
                        "gave_up": True, "runs": [r.get("run_id") for r in rec["runs"] if r.get("run_id")],
                        **_shard_report(rec, {})}
            _write_json(rel / RUN_FILE, rec)
            raise
        absorb(res)
        run_id = rid or run_id
    elif not rec["good"] and not rec["missing"]:
        _p, res, rid = sweep_fn(src=snapshot, files=None, shards=shards, label=next_label(state_dir, sha), wait_s=None,
                                durations_path=dpath, on_run=note)
        absorb(res)
        run_id = rid
    reason_tail = ""
    while rec["missing"] and rec["fills"] < FILL_ROUNDS:
        if snapshot is None or not Path(snapshot).is_dir():
            reason_tail = " (the tree of this SHA is gone: no run of the missing files)"
            break
        rec["fills"] += 1
        _write_json(rel / RUN_FILE, rec)
        files = sorted(rec["missing"])
        _p, res, _rid = sweep_fn(src=snapshot, files=files, shards=min(len(files), shards), wait_s=None, durations_path=dpath,
                                 label=next_label(state_dir, sha, prefix="rel-fill"), on_run=note)
        absorb(res)
    results = dict(rec["good"])
    out = {"sha": sha, "sweep": {"red": 0, "new_red": [], "flaky": [], "run_id": run_id}, "status": "", "reason": "", "debt_rows": [],
           "closed_rows": [], "runs": [r.get("run_id") for r in rec["runs"] if r.get("run_id")], **_shard_report(rec, results)}
    missing = sorted(rec["missing"])
    if missing:
        (rel / RUN_FILE).unlink(missing_ok=True)                # the budget is spent: the next try is a new run
        out["status"] = "sweep_incomplete"
        out["reason"] = "no result of %d file(s) after %d fill-in run(s): %s%s" % (len(missing), rec["fills"], ", ".join(missing[:5]), reason_tail)
        return out
    (rel / RUN_FILE).unlink(missing_ok=True)
    names = []
    for f in sorted(results or {}):
        for n in (results[f] or {}).get("failed_ids") or ():
            if n not in names:
                names.append(n)
    out["sweep"]["red"] = len(names)
    try:                                # the failure text of each red test: a convenience, the verdict never waits for it
        keep_failures(state_dir, results, names, sha)
    except OSError:
        pass
    last_red = keep_red_last(rel, sha, names)           # W-part 1: the full verdict is the evidence of two builds
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
    try:                                # the debt is a convenience of the build: it never takes the verdict away
        out["debt_rows"] = _debt_step(rel, names, baseline, results, known_path, env_path, set(known), set(open_ids),
                                      set(open_tests), green=out["status"] == "green", closed_out=out["closed_rows"])
    except OSError:
        out["debt_rows"] = []
    try:
        out["closed_rows"] += close_regressions(rel, last_red)
    except OSError:
        pass
    return out


FAILURES_FILE = "failures.json"     # {test name: {"text": failure text (<= FAILURE_CHARS), "sha": base sha, "at": time}}
FAILURE_CHARS = 1500
FAILURES_KEEP = 400                 # entries kept (the newest by time)


def failures(state_dir) -> dict:
    """The failure texts the builds kept: ``{test name: {"text", "sha", "at"}}``."""
    return _read_json(release_dir(state_dir) / FAILURES_FILE, {})


def keep_failures(state_dir, results, names, sha) -> int:
    """Writes the failure text of every red test of this sweep (``results[file]["failures"][name]``, cut to FAILURE_CHARS) into
    ``<state>/release/failures.json``; a red test with no text in the results keeps the text of an earlier build.  Returns the number
    of texts written."""
    book = failures(state_dir)
    now, written = time.time(), 0
    for name in names:
        row = results.get(_file_of(name)) or results.get(str(name).split("::", 1)[0]) or {}
        text = (row.get("failures") or {}).get(name) if isinstance(row, dict) else None
        if isinstance(text, str) and text.strip():
            book[str(name)] = {"text": text.strip()[-FAILURE_CHARS:], "sha": str(sha), "at": now}
            written += 1
    if written:
        if len(book) > FAILURES_KEEP:
            book = dict(sorted(book.items(), key=lambda kv: float((kv[1] or {}).get("at") or 0))[-FAILURES_KEEP:])
        _write_json(release_dir(state_dir) / FAILURES_FILE, book)
    return written


def failure_of(state_dir, name, book=None):
    """The kept failure text of a test (an exact name, else the same test name in the same file), or ''.
    ``book``: the already read failures book (a grouping reads the file once)."""
    if book is None:
        book = failures(state_dir)
    rec = book.get(str(name))
    if rec is None:
        key = red_ratchet.cut(red_ratchet.norm(name))
        rec = next((r for n, r in book.items() if red_ratchet.cut(red_ratchet.norm(n)) == key), None)
    return str((rec or {}).get("text") or "") if isinstance(rec, dict) else ""


DEBT_FILE = "baseline_debt.json"        # {file: {"tests": [...], "queued": bool, "n": int, "closed": bool}}
DEBT_SEQ = "baseline_debt_seq.json"     # {"next": n}: the number of a file's row is never used twice
DEBT_ROW = re.compile(r"^rel-base-(\d+)$")


def debt(state_dir) -> dict:
    """The baseline debt: ``{test file: {"tests": [red test names], "queued": bool, "n": row number, "closed": bool}}``."""
    book = _read_json(release_dir(state_dir) / DEBT_FILE, {})
    return {f: dict(r) for f, r in book.items() if isinstance(r, dict)}


def holds_deploy(row_id) -> bool:
    """True for a row that holds the deploy back: a regression row ``rel-<sha8>-<n>``; the debt rows ``rel-base-<n>`` never do."""
    row = str(row_id or "")
    return row.startswith("rel-") and not row.startswith("rel-base-")


def close_debt(state_dir, row_id) -> bool:
    """A merged and accepted ``rel-base-<n>`` takes its file out of the debt (the entry stays, closed, until the tests are green
    and leave the baseline).  True when an entry was closed."""
    found = DEBT_ROW.match(str(row_id or ""))
    if not found:
        return False
    path = release_dir(state_dir) / DEBT_FILE
    book = _read_json(path, {})
    for rec in book.values():
        if isinstance(rec, dict) and rec.get("n") == int(found.group(1)) and not rec.get("closed"):
            rec["closed"] = True
            _write_json(path, book)
            return True
    return False


def _next_n(rel, book) -> int:
    seq = _read_json(rel / DEBT_SEQ, {})
    n = max(int(seq.get("next") or 1), 1 + max([int(r.get("n") or 0) for r in book.values() if isinstance(r, dict)] or [0]))
    _write_json(rel / DEBT_SEQ, {"next": n + 1})
    return n


RED_LAST = "red_last.json"      # {"sha", "at", "red": [names]}: the red tests of the last full verdict
RED_PREV = "red_prev.json"      # the same of the full verdict before it


def _key(name) -> str:
    return red_ratchet.cut(red_ratchet.norm(name))


def keep_red_last(rel, sha, names) -> dict:
    """Writes release/red_last.json (atomic) for a full verdict; the record it replaces (of another SHA) becomes red_prev.json.
    -> {"last": {keys}, "prev": {keys} or None}."""
    rel = Path(rel)
    old = _read_json(rel / RED_LAST, {})
    if old and str(old.get("sha")) != str(sha):
        _write_json(rel / RED_PREV, old)
    _write_json(rel / RED_LAST, {"sha": str(sha), "at": time.time(), "red": sorted(str(n) for n in names)})
    return red_pair(rel)


def red_pair(rel) -> dict:
    prev = _read_json(Path(rel) / RED_PREV, {})
    last = _read_json(Path(rel) / RED_LAST, {})
    return {"last": {_key(n) for n in last.get("red") or ()},
            "prev": {_key(n) for n in prev.get("red") or ()} if prev.get("red") is not None and prev else None}


def red_last(state_dir) -> dict:
    """The last full verdict's record ``{"sha", "at", "red"}`` ({} when none)."""
    return _read_json(release_dir(state_dir) / RED_LAST, {})


def _green_twice(tests, pair) -> bool:
    return bool(tests) and pair["prev"] is not None and not any(_key(t) in pair["last"] or _key(t) in pair["prev"] for t in tests)


def close_regressions(rel, pair) -> list:
    """The regression rows (rel-<sha>-<n>) whose tests are red in neither of the two last full builds leave regressions.json.
    -> the row ids closed."""
    rel = Path(rel)
    book = _read_json(rel / "regressions.json", {})
    out = []
    for name, rec in list(book.items()):
        if _green_twice([name], pair):
            out.append(str((rec or {}).get("row") or ""))
            del book[name]
    if out:
        _write_json(rel / "regressions.json", book)
    return [r for r in out if r]


def _debt_step(rel, names, baseline, results, known_path, env_path, known, open_ids, open_tests, *, green, closed_out=None) -> list:
    """Builds the debt of the red baseline from this full sweep and hands out the files not yet queued (once each).
    A debt test is red NOW (a test green on the last full run is no debt), in the baseline, on no known / cloud-env list (nor
    the 'no module in the cloud' auto label) and is not the guard of an open row or a test of an unfinished task.  On a green
    build the tests of a closed file that are green leave baseline_red.json (it only shrinks)."""
    book = debt(rel.parent)
    pair = red_pair(rel)
    for f, rec in book.items():             # W-part 1: no test of the file red in the two last full builds: the row is done
        if not rec.get("closed") and f in results and _green_twice(rec.get("tests"), pair):
            rec["closed"] = True
            if closed_out is not None and rec.get("n"):
                closed_out.append("rel-base-%d" % int(rec["n"]))
    red_now = {}
    for n in names:
        key = red_ratchet.cut(red_ratchet.norm(n))
        if key in baseline:
            red_now.setdefault(key, n)
    got = red_ratchet.compare(list(red_now.values()), known_path, env_path, extra_known=known)
    cand = [n for n in got["new"] if not _queued_work(n, open_ids, open_tests)]
    by_file = {}
    for n in sorted(cand):
        by_file.setdefault(_file_of(n), []).append(n)
    base_file = rel / "baseline_red.json"
    if green:                           # ratchet: a closed file's tests that are green now leave the baseline
        gone = set()
        for f, rec in book.items():
            if rec.get("closed") and f in results:
                gone |= {t for t in rec.get("tests") or () if t in baseline and t not in red_now}
        if gone:
            _write_json(base_file, sorted(baseline - gone))
    out, new_book = [], {}
    for f, tests in by_file.items():
        old = book.get(f) or {}
        if old and old.get("closed"):               # accepted, yet still red: a new row with a new number
            old = {}
        rec = {"tests": tests, "queued": bool(old.get("queued")), "n": int(old.get("n") or 0), "closed": False}
        if not rec["n"]:
            rec["n"] = _next_n(rel, {**book, **new_book})
        new_book[f] = rec
    for f, rec in book.items():
        if rec.get("closed") and f not in by_file:
            if f in results:
                continue                            # the file ran and none of its tests is a debt now: the entry is done
            new_book[f] = rec                       # the file did not run: stays closed
    for f, rec in book.items():
        if f in new_book or f in by_file or not rec.get("queued") or rec.get("closed"):
            continue
        pending_green = f in results and not any(_key(t) in pair["last"] for t in rec.get("tests") or ())    # waits for the 2nd green build
        if any(_queued_work(t, open_ids, open_tests) for t in rec.get("tests") or ()) or f not in results or pending_green:
            new_book[f] = rec                       # queued and in work (or not run): the entry stays, or its row is lost
    for f in sorted(new_book, key=lambda k: new_book[k]["n"]):
        rec = new_book[f]
        if not rec["queued"] and not rec["closed"]:
            rec["queued"] = True
            out.append({"file": f, "n": rec["n"], "key": "rel-base-%d" % rec["n"], "guard": rec["tests"][0],
                        "tests": list(rec["tests"])})
    _write_json(rel / DEBT_FILE, new_book)
    return out
