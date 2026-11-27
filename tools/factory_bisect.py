"""W-bisect: the deterministic proof of WHAT broke a red baseline test, found without a model.

The baseline debt (``rel-base-<n>`` rows) is red tests no model could fix because it did not know what broke them.  Here the
history of the working branch (first parents, from the live root to the base) is swept in the cloud at a few checkpoints and the
commit after which each test turned red is searched by halving.  Per test the result is one of
  regression  - green at ``green``, red at ``red`` (a single commit or a narrow segment), with the files and the diff between them;
  never_green - red at every checkpoint where it exists;
  moved       - the test appeared already red (absent at the earlier checkpoints).
The sweep, the git archive of a commit and the git reads are INJECTED (``sweep_fn`` = tools.echo_cloud.sweep, ``snapshot_fn``,
``diff_fn``): the module reads and writes only ``<state>/release/bisect.json`` and imports only the release module.
One ``step`` = one cloud run (one checkpoint for a batch of tests); the run in flight is written into bisect.json the moment it
exists, so a restart takes it up.  Marks per test and checkpoint: g green, r red, n absent (no file / no test there), u unknown.
"""
import json
import re
from pathlib import Path

from tools import factory_release as REL
from tools import red_ratchet

ROOT_SHA = "671d2fe"        # the live root of the product history
MID_POINTS = 10             # checkpoints between the root and the base
REFINE_STEPS = 4            # halvings per test (per segment) at most
DIFF_CHARS = 6000           # files + diff handed to the slicer
DIFF_RAW = 60000            # the raw diff kept in the book (the trace/contract ordering is made at the packet)
FILES_SHOWN = 30
RETRY_S = 300               # a step that failed is repeated after this long (the loop)
TRIES = 3                   # a checkpoint whose run fails this many times is given up (its marks are u)
BISECT_FILE = "bisect.json"
KINDS = ("regression", "never_green", "moved")
TAIL_RANK = {"regression": 0, "never_green": 2, "moved": 2}     # row order among the baseline debt: unclassified rows are 1


def bisect_path(state_dir) -> Path:
    return REL.release_dir(state_dir) / BISECT_FILE


def key_of(name) -> str:
    return red_ratchet.cut(red_ratchet.norm(str(name)))


def file_of(name) -> str:
    return key_of(name).split("::", 1)[0]


# ----------------------------------------------------------------------------------------------------------- history
def history(git, base, root=ROOT_SHA) -> list:
    """The first-parent chain, oldest first: the root, then every commit after it up to ``base`` (``git(*args) -> text``).
    A root the repository does not know: the whole first-parent history of ``base``."""
    base = str(base).strip()
    try:
        top = git("rev-parse", root + "^{commit}").strip()
    except Exception:       # noqa: BLE001  no such commit here
        top = ""
    if top:
        chain = git("rev-list", "--first-parent", "--reverse", top + ".." + base).split()
        return [top] + [c for c in chain if c != top]
    return git("rev-list", "--first-parent", "--reverse", base).split()


def plan(tests_by_file, commits, mid=MID_POINTS) -> dict:
    """The checkpoints: the root, the base and ``mid`` evenly spread commits between them (ordered oldest first, no repeats).
    -> {"points": [sha], "files": [file], "tests": n}.  One cloud run of ALL the files runs on each point."""
    n = len(commits)
    if not n:
        return {"points": [], "files": sorted(tests_by_file or {}), "tests": 0}
    at = {0, n - 1} | {round(k * (n - 1) / (mid + 1)) for k in range(1, mid + 1)}
    return {"points": [commits[i] for i in sorted(at)], "files": sorted(tests_by_file or {}),
            "tests": sum(len(v) for v in (tests_by_file or {}).values())}


# --------------------------------------------------------------------------------------------------------------- book
def load(state_dir) -> dict:
    book = REL._read_json(bisect_path(state_dir), {})
    for name, default in (("commits", []), ("points", []), ("tests", {}), ("marks", {}), ("steps", {}), ("result", {}),
                          ("diffs", {}), ("tries", {})):
        if not isinstance(book.get(name), type(default)):
            book[name] = default
    return book


_BOOK: dict = {}


def load_shared(state_dir) -> dict:
    """``load`` for readers only, parsed once per (mtime, size): row_key asks it for every debt row of a tick."""
    try:
        st = bisect_path(state_dir).stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        return load(state_dir)
    hit = _BOOK.get(str(state_dir))
    if hit is None or hit[0] != stamp:
        hit = _BOOK[str(state_dir)] = (stamp, load(state_dir))
    return hit[1]


def save(state_dir, book) -> None:
    REL._write_json(bisect_path(state_dir), book)


def _index(book) -> dict:
    return {sha: i for i, sha in enumerate(book["commits"])}


def _by_index(book) -> dict:
    """{commit index: {test: mark}} of the checkpoints run so far."""
    idx = _index(book)
    return {idx[sha]: marks for sha, marks in book["marks"].items() if sha in idx}


def _absorb_tests(book, tests_by_file) -> None:
    """The tests of the open debt: new ones join the book, ``active`` is the open set (a closed file's tests are not run again)."""
    active = []
    for file, names in (tests_by_file or {}).items():
        for name in names or ():
            key = key_of(name)
            book["tests"].setdefault(key, file_of(name) if "::" in str(name) else str(file))
            active.append(key)
    book["active"] = sorted(set(active))


def _active(book) -> list:
    keep = set(book.get("active") if isinstance(book.get("active"), list) else book["tests"])
    return sorted(t for t in book["tests"] if t in keep)


def _gap(by_index, g, r, group) -> list:
    """The commits strictly between g and r no test of ``group`` was marked at."""
    return [i for i in range(g + 1, r) if not any(t in by_index.get(i, {}) for t in group)]


def _segment(book, test, by_index=None):
    """(g, r): the last green checkpoint and the first red one after it; None when there is no such pair."""
    by_index = by_index if by_index is not None else _by_index(book)
    used = sorted((i, m[test]) for i, m in by_index.items() if test in m)
    greens = [i for i, mark in used if mark == "g"]
    if not greens:
        return None
    after = [i for i, mark in used if mark == "r" and i > max(greens)]
    return (max(greens), min(after)) if after else None


def classify(book, test, by_index=None):
    """The result of one test, or None while it is not settled (a checkpoint is not run, or the segment can still be halved).
    kind: regression / never_green / moved; "green" = not red at the last checkpoint (nothing to prove)."""
    by_index = by_index if by_index is not None else _by_index(book)
    if any(test not in book["marks"].get(sha, {}) for sha in book["points"]):
        return None
    used = sorted((i, m[test]) for i, m in by_index.items() if test in m)
    reds = [i for i, mark in used if mark == "r"]
    if not reds:
        return {"kind": "green"}
    if not any(mark == "g" for _i, mark in used):
        return {"kind": "moved" if any(mark == "n" and i < min(reds) for i, mark in used) else "never_green"}
    seg = _segment(book, test, by_index)
    if seg is None:
        return {"kind": "green"}
    g, r = seg
    if r - g > 1 and int(book["steps"].get(test) or 0) < REFINE_STEPS and _gap(by_index, g, r, [test]):
        return None
    return {"kind": "regression", "green": book["commits"][g], "red": book["commits"][r], "g": g, "r": r,
            "single": r - g == 1, "steps": int(book["steps"].get(test) or 0)}


def next_job(book):
    """The next cloud run: (sha, [tests], phase) or None.  First every checkpoint of the plan (the base, the root, then the rest) for
    the tests it still lacks; then one halving point for the tests of the busiest segment (one point per step for all of them)."""
    tests = _active(book)
    idx = _index(book)
    order = sorted(book["points"], key=lambda s: (s != book["commits"][-1], s != book["commits"][0], idx.get(s, 0)))
    for sha in order:
        lacking = [t for t in tests if t not in book["marks"].get(sha, {})]
        if lacking:
            return sha, lacking, "plan"
    by_index = _by_index(book)
    groups = {}
    for t in tests:
        seg = _segment(book, t, by_index)
        if seg and seg[1] - seg[0] > 1 and int(book["steps"].get(t) or 0) < REFINE_STEPS:
            groups.setdefault(seg, []).append(t)
    for seg, group in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        gap = _gap(by_index, seg[0], seg[1], group)
        if gap:
            mid = min(gap, key=lambda i: (abs(i - (seg[0] + seg[1]) / 2), i))
            return book["commits"][mid], group, "refine"
    return None


def pending(state_dir, tests_by_file) -> bool:
    """True when a cloud run is in flight or a checkpoint / halving point is still to run for ``tests_by_file`` (a book with no
    history yet has work when there are tests)."""
    book = load(state_dir)
    if isinstance(book.get("run"), dict):
        return True
    if not book["commits"]:
        return any(tests_by_file.values())
    _absorb_tests(book, tests_by_file)
    return next_job(book) is not None


def has_run(state_dir) -> bool:
    """A run is out there (a restarted loop takes it up: it holds its own cloud places)."""
    return isinstance(load(state_dir).get("run"), dict)


def counts(state_dir) -> dict:
    """stats: {done: tests with a result, regression, never_green, moved}."""
    book = load(state_dir)
    res = [r for r in book["result"].values() if isinstance(r, dict)]
    return {"done": len(res), **{k: sum(1 for r in res if r.get("kind") == k) for k in KINDS}}


# -------------------------------------------------------------------------------------------------------------- step
def _defined(path, test) -> bool:
    """The test function is in the file text (a test that is not there at this commit is absent, not green)."""
    parts = test.split("::")[1:]
    name = re.sub(r"\[.*$", "", parts[-1]) if parts else ""
    if not name or name.startswith("<"):
        return True
    try:
        return re.search(r"\bdef\s+" + re.escape(name) + r"\b", path.read_text(encoding="utf-8", errors="replace")) is not None
    except OSError:
        return False


def _prepare(book, snapshot, tests):
    """({test: "n"} for the tests with no file/function at this commit, the tests to run, their files)."""
    pre, live = {}, []
    for t in tests:
        path = Path(snapshot) / book["tests"][t]
        if path.is_file() and _defined(path, t):
            live.append(t)
        else:
            pre[t] = "n"
    return pre, live, sorted({book["tests"][t] for t in live})


def _record(book, run, results) -> None:
    marks = book["marks"].setdefault(run["sha"], {})
    marks.update(run.get("pre") or {})
    for t in run.get("live") or ():
        row = (results or {}).get(book["tests"][t])
        if not isinstance(row, dict) or row.get("missing"):
            marks[t] = "u"
            continue
        failed = {key_of(x) for x in row.get("failed_ids") or ()}
        collection = any(x.endswith("::<collection>") for x in failed)
        marks[t] = "r" if (t in failed or collection) else "g"
    if run.get("phase") == "refine":
        for t in run.get("tests") or ():
            book["steps"][t] = int(book["steps"].get(t) or 0) + 1
    book.pop("run", None)
    book["tries"].pop(run["sha"], None)


def _finalize(book, diff_fn) -> None:
    """Results of every settled test; the diff of a regression's segment is read once per segment."""
    by_index = _by_index(book)
    for t in _active(book):
        res = classify(book, t, by_index)
        if res is None:
            book["result"].pop(t, None)
            continue
        if res["kind"] == "regression":
            seg = "%s..%s" % (res["green"][:12], res["red"][:12])
            res["segment"] = seg
            if seg not in book["diffs"] and diff_fn is not None:
                try:
                    files, text = diff_fn(res["green"], res["red"])
                    book["diffs"][seg] = {"files": list(files or ())[:200], "diff": str(text or "")[:DIFF_RAW],
                                          "commits": book["commits"][res["g"] + 1:res["r"] + 1][:60]}
                except Exception:       # noqa: BLE001  a diff is an aid: the proof stands, the diff is read at the next step
                    pass
        book["result"][t] = res


def _free(free_fn, snap) -> None:
    if snap is not None and free_fn is not None:
        try:
            free_fn(snap)
        except Exception:       # noqa: BLE001  a leftover snapshot is cleaned at the next start
            pass


def step(*, state_dir, sweep_fn, snapshot_fn, free_fn=None, diff_fn=None, drop_fn=None, commits=None, tests_by_file=None,
         shards=4, on_run=None) -> dict:
    """One cloud run (or the end of the one in flight).  -> {"status": "point" | "done" | "idle", "sha", "phase", "more", "reason"}.
    ``commits`` (oldest first, from ``history``) starts a book that has none; the book keeps its own history after that (the
    plan does not move with the base).  ``tests_by_file`` adds tests.  An error of the run is raised AFTER it was counted: the
    caller repeats later; a checkpoint that fails TRIES times (or whose tree the scanner blocks) gets the mark u."""
    rel = REL.release_dir(state_dir)
    rel.mkdir(parents=True, exist_ok=True)
    book = load(state_dir)
    if not book["commits"]:
        if not commits:
            return {"status": "idle", "sha": "", "phase": "", "more": False, "reason": "no history"}
        book["commits"] = list(commits)
        book["points"] = plan(tests_by_file or {}, book["commits"])["points"]
    _absorb_tests(book, tests_by_file)
    dpath = str(rel / "durations.json")
    run = book.get("run") if isinstance(book.get("run"), dict) else None

    def note(info):
        book["run"]["info"] = dict(info)
        save(state_dir, book)
        if on_run:
            on_run(dict(info))

    if run is None:
        job = next_job(book)
        if job is None:
            _finalize(book, diff_fn)
            save(state_dir, book)
            return {"status": "done", "sha": "", "phase": "", "more": False, "reason": "every checkpoint is run"}
        sha, tests, phase = job
        snap = snapshot_fn(sha)
        try:
            pre, live, files = _prepare(book, snap, tests)
        except Exception:
            _free(free_fn, snap)
            raise
        if not files:
            _free(free_fn, snap)
            snap = None
        run = book["run"] = {"sha": sha, "phase": phase, "tests": tests, "pre": pre, "live": live, "files": files, "info": None,
                             "fails": 0}
        save(state_dir, book)
    else:
        sha, phase, files, snap = run["sha"], run.get("phase", ""), list(run.get("files") or ()), None
    try:
        if run.get("info"):                                 # the run is out there: wait for it, never publish again
            _p, results, _id = sweep_fn(src=None, resume=dict(run["info"]), wait_s=None, durations_path=dpath)
        elif files:
            _p, results, _id = sweep_fn(src=snap, files=files, shards=max(1, min(int(shards), len(files))), wait_s=None,
                                        label=REL.next_label(state_dir, sha, prefix="rel-bs"), durations_path=dpath, on_run=note)
        else:
            results = {}
    except Exception as exc:        # noqa: BLE001
        tries = int(book["tries"].get(sha) or 0) + 1
        book["tries"][sha] = tries
        blocked = type(exc).__name__ == "Blocked"
        if run.get("info"):
            run["fails"] = int(run.get("fails") or 0) + 1
        gone = bool(run.get("info")) and run["fails"] >= REL.RESUME_FAILS
        if blocked or tries >= TRIES:
            _record(book, dict(run, live=run["live"]), {})        # no result: u for every test of the point
            _finalize(book, diff_fn)
        elif gone or not run.get("info"):                    # nothing out there any more: the next try is a new run
            if gone and drop_fn is not None:
                try:
                    drop_fn(run["info"])
                except Exception:       # noqa: BLE001
                    pass
            book.pop("run", None)
        save(state_dir, book)
        if blocked:
            return {"status": "point", "sha": sha, "phase": phase, "more": next_job(book) is not None, "reason": "blocked"}
        raise
    finally:
        _free(free_fn, snap)
    _record(book, run, results)
    _finalize(book, diff_fn)
    save(state_dir, book)
    return {"status": "point", "sha": sha, "phase": phase, "more": next_job(book) is not None, "reason": ""}


# --------------------------------------------------------------------------------------------------- the loop's reading
_CACHE = {}


def row_kinds(state_dir) -> dict:
    """{rel-base-<n>: kind} for the debt rows with a settled result: the guard test (the first one) decides, else a regression of any
    test of the row, else the kind the guard has.  Cached while the two files do not change."""
    paths = [bisect_path(state_dir), REL.release_dir(state_dir) / REL.DEBT_FILE]
    stamp = []
    for p in paths:
        try:
            st = p.stat()
            stamp.append((st.st_mtime_ns, st.st_size))
        except OSError:
            stamp.append(None)
    hit = _CACHE.get(str(state_dir))
    if hit and hit[0] == stamp:
        return hit[1]
    out = {}
    if stamp[0] is not None:
        res = load(state_dir)["result"]
        for rec in REL.debt(state_dir).values():
            if rec.get("closed") or not rec.get("tests") or not rec.get("n"):
                continue
            kinds = [(key_of(t), (res.get(key_of(t)) or {}).get("kind")) for t in rec["tests"]]
            pick = next((k for t, k in kinds[:1] if k in KINDS), None) or next((k for _t, k in kinds if k == "regression"), None)
            if pick:
                out["rel-base-%d" % int(rec["n"])] = pick
    _CACHE[str(state_dir)] = (stamp, out)
    return out


def row_tests(state_dir, row) -> list:
    """The red tests of an open debt row ``rel-base-<n>`` (the guard test first), [] for any other row."""
    found = REL.DEBT_ROW.match(str(row))
    if not found:
        return []
    for rec in REL.debt(state_dir).values():
        if rec.get("n") == int(found.group(1)) and not rec.get("closed"):
            return [str(t) for t in rec.get("tests") or ()]
    return []


def row_key(state_dir, row):
    """The segment key of the regression the row's evidence carries ("<green>..<red>"), None when the row has none (yet)."""
    if row_kinds(state_dir).get(str(row)) != "regression":
        return None
    return (clue(state_dir, row_tests(state_dir, row)) or {}).get("key")


def culprit_of(state_dir, name) -> str:
    """The guilty segment "<green>..<red>" of the test, "" when there is no proof (fac-67).  Only a segment narrowed to ONE commit
    counts: a wide one would glue independent regressions of the same range into one row."""
    res = load_shared(state_dir)["result"].get(key_of(name))
    return str(res.get("segment") or "") if isinstance(res, dict) and res.get("kind") == "regression" and res.get("single") else ""


def culprit_groups(state_dir, names) -> list:
    """fac-67: ``names`` grouped by the guilty segment, first seen first: [(segment, [names])]; a test with no proof is a group of its
    own with the segment "" (the old one-row-per-test)."""
    groups, order = {}, []
    for name in names:
        seg = culprit_of(state_dir, name)
        key = seg or ("\0" + str(name))
        if key not in groups:
            groups[key] = (seg, [])
            order.append(key)
        groups[key][1].append(name)
    return [groups[k] for k in order]


def rank(state_dir, row) -> int:
    """Order among the debt rows: 0 a regression, 1 not (yet) classified, 2 never_green / moved."""
    return TAIL_RANK.get(row_kinds(state_dir).get(str(row)), 1)


def _symbols(contract_text) -> set:
    out = set()
    for text in contract_text if isinstance(contract_text, (list, tuple)) else [contract_text]:
        try:
            parts = (json.loads(text) or {}).get("parts") or []
        except (ValueError, AttributeError, TypeError):
            continue
        for part in parts if isinstance(parts, list) else ():
            if isinstance(part, dict):
                out.update(str(s).split(".")[-1] for s in part.get("symbols") or () if s)
    return out


def order_diff(raw, names, cap=DIFF_CHARS) -> str:
    """The raw diff cut to ``cap``: the hunks that touch a function of ``names`` (trace and contract) first, the hunks of the
    product next, the hunks of tests last; the file header stays with its first hunk."""
    names = {str(n).split(".")[-1] for n in names if n}
    files, head, hunk = [], [], None
    for line in str(raw).splitlines():
        if line.startswith("diff --git "):
            files.append({"head": [line], "hunks": []})
            hunk = None
        elif line.startswith("@@") and files:
            hunk = [line]
            files[-1]["hunks"].append(hunk)
        elif hunk is not None:
            hunk.append(line)
        elif files:
            files[-1]["head"].append(line)
    ranked = []
    for n, f in enumerate(files):
        path = f["head"][0].split(" b/")[-1]
        for k, h in enumerate(f["hunks"]):
            text = "\n".join(h)
            hit = bool(names) and any(re.search(r"\b" + re.escape(x) + r"\b", text) for x in names)
            ranked.append((0 if hit else 2 if path.startswith("tests/") else 1, n, k, f, h))
    ranked.sort(key=lambda x: x[:3])
    out, seen, total = [], set(), 0
    for _r, n, _k, f, h in ranked:
        piece = ([] if n in seen else f["head"]) + h
        text = "\n".join(piece) + "\n"
        if total + len(text) > cap:
            room = cap - total
            if room > 80:
                out.append(text[:room - 20].rstrip() + "\n[...cut]\n")
            elif total:
                out.append("[...cut]\n")
            break
        seen.add(n)
        out.append(text)
        total += len(text)
    return "".join(out)


def clue(state_dir, tests, *, trace=(), contracts=()):
    """The evidence of the row for the slicer: {"key": "<green>..<red>", "text": ...} for the first regression among ``tests``
    (a settled one), else None.  ``trace`` = the functions of the guard's trace ((file, name, line) or names), ``contracts`` = the
    contracts of the row's earlier cards: the hunks that touch their functions come first.  Files and diff together fit DIFF_CHARS."""
    book = load_shared(state_dir)
    for t in tests:
        res = book["result"].get(key_of(t))
        if not (isinstance(res, dict) and res.get("kind") == "regression"):
            continue
        rec = book["diffs"].get(res.get("segment") or "")
        if not rec or not str(rec.get("diff") or "").strip():
            continue
        names = {str(x[1] if isinstance(x, (list, tuple)) else x) for x in trace if x} | _symbols(list(contracts))
        files = ", ".join(rec.get("files", [])[:FILES_SHOWN])
        head = "Files changed: %s\n" % (files or "-")
        body = order_diff(rec["diff"], names, max(500, DIFF_CHARS - len(head)))
        green, red = res["green"], res["red"]
        if res.get("single"):
            when = "The test was green before commit %s (green at %s, red at %s)" % (red[:12], green[:12], red[:12])
        else:
            when = ("The test was green before one of the %d commits after %s (green at %s, red at %s; the segment is not narrowed "
                    "to one commit)" % (len(rec.get("commits") or ()) or (res["r"] - res["g"]), green[:12], green[:12], red[:12]))
        text = ("BISECT PROOF (found without a model, by running the test on the history): " + when +
                "; here is the diff after which it turned red; restore the earlier behaviour without breaking the new.\n"
                + head + "DIFF:\n" + body)
        return {"key": res["segment"], "test": key_of(t), "text": text}
    return None
