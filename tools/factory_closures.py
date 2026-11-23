"""<id>: one writer of the backlog's closures table («## Закрыто коммитами координатора ...», rows ``| ID | sha | note |``).

Atomic (temp file + replace), idempotent (an ID already in the table is never written twice), line endings kept.
Never raises: the result is a word - added / present / no_section / unreadable / error.
"""
import contextlib
import os
import re
import threading
import time
from functools import wraps
from pathlib import Path

_LOCK = threading.RLock()     # read -> change -> replace of the backlog is one step: the loop's thread and the links job share it


def _thread_locked(fn):
    @wraps(fn)
    def run(*a, **k):
        with _LOCK:
            return fn(*a, **k)
    return run

HEADING = "## Закрыто коммитами координатора"
SHA_LEN = 8


def _eol(raw):
    return chr(13) + chr(10) if chr(13) + chr(10) in raw else chr(10)


def _cell(text) -> str:
    return re.sub(r"\s+", " ", str(text).replace("|", "/")).strip()


def _section(lines):
    start = next((i for i, x in enumerate(lines) if x.startswith(HEADING)), None)
    if start is None:
        return None, None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    return start, end


def _read(path):
    try:
        return Path(path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def table_ids(backlog) -> dict:
    """{ID: sha} of the closures table; an unreadable file or a missing table is empty."""
    raw = _read(backlog)
    if raw is None:
        return {}
    lines = raw.split(_eol(raw))
    start, end = _section(lines)
    out = {}
    for i in range(start + 1, end) if start is not None else ():
        if lines[i].lstrip().startswith("|"):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] and cells[0] not in ("ID", "N") and not set(cells[0]) <= set("-: "):
                out.setdefault(cells[0], cells[1])
    return out


def table_evidence(backlog) -> dict:
    """{ID: "commit <sha>: <note>"} of the closures table (what a closed row says it did); unreadable or no table is empty."""
    raw = _read(backlog)
    if raw is None:
        return {}
    lines = raw.split(_eol(raw))
    start, end = _section(lines)
    out = {}
    for i in range(start + 1, end) if start is not None else ():
        if lines[i].lstrip().startswith("|"):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] and cells[0] not in ("ID", "N") and not set(cells[0]) <= set("-: "):
                out.setdefault(cells[0], "commit %s: %s" % (cells[1], cells[2].split(AUDIT_MARK)[0] if len(cells) > 2 else ""))
    return out


LOCK_STALE_S = 30       # a lock folder older than this is a dead writer's
LOCK_WAIT_S = 10


@contextlib.contextmanager
def _locked(path):
    """8.1: two loop instances write this one file. The lock is a folder beside it (mkdir is atomic); a folder older than
    LOCK_STALE_S is a dead writer's and is taken over. Not got within LOCK_WAIT_S: the write goes on (a late write beats none)."""
    lock = Path(str(path) + ".lock")
    held = False
    end = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            lock.mkdir()
            held = True
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    # a second waiter may have taken the dead lock over just now: look at the age once more right before
                    # the rmdir so a fresh lock is not removed (a window of microseconds is left; it needs a dead writer
                    # and two waiters in the same instant, and the cost is one lost closure that the loop writes again)
                    if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                        lock.rmdir()
                    continue
            except OSError:
                pass
        except PermissionError:
            pass                 # Windows: mkdir against a folder another waiter is removing right now; try again
        except OSError:
            break
        if time.monotonic() > end:
            break
        time.sleep(0.02)
    try:
        yield
    finally:
        if held:
            try:
                lock.rmdir()
            except OSError:
                pass


@_thread_locked
def record_closures(backlog, items) -> dict:
    """items: [(ID, sha, note)] -> {ID: added|present|no_section|unreadable|error}; ONE read and ONE atomic replace,
    under the lock folder."""
    with _locked(backlog):
        return _record_closures(backlog, items)


def _record_closures(backlog, items) -> dict:
    path = Path(backlog)
    raw = _read(path)
    items = [(str(b).strip(), s, n) for b, s, n in items]
    if raw is None:
        return {b: "unreadable" for b, _, _ in items}
    eol = _eol(raw)
    lines = raw.split(eol)
    start, end = _section(lines)
    last = None
    have = set()
    for i in range(start + 1, end) if start is not None else ():
        if lines[i].lstrip().startswith("|"):
            last = i
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if cells:
                have.add(cells[0])
    if last is None:
        return {b: "no_section" for b, _, _ in items}
    res, rows = {}, []
    for bid, sha, note in items:
        if bid in have:
            res.setdefault(bid, "present")
            continue
        have.add(bid)
        res[bid] = "added"
        rows.append("| %s | %s | %s |" % (_cell(bid), _cell(sha)[:SHA_LEN], _cell(note)))
    if not rows:
        return res
    lines[last + 1:last + 1] = rows
    tmp = path.with_name(path.name + ".closure.tmp")
    try:
        tmp.write_bytes(eol.join(lines).encode("utf-8"))
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return {b: ("error" if r == "added" else r) for b, r in res.items()}
    return res


def record_closure(backlog, bid, sha, note="") -> str:
    return record_closures(backlog, [(bid, sha, note)])[str(bid).strip()]


def _wanted(ids, sha_of):
    """[(ID, sha)] of the ECHO rows that a commit closed; no sha (closed by the coordinator, a duplicate) or fac-*: left out."""
    out, skipped = [], []
    for bid in dict.fromkeys(str(i).strip() for i in ids):
        if bid.lower().startswith("fac-"):
            continue
        sha = str((sha_of or {}).get(bid) or "").strip()
        (out if sha else skipped).append((bid, sha) if sha else bid)
    return out, skipped


def plan_stale(backlog, ids, sha_of) -> list:
    """Dry run of sync_stale: [(ID, sha)] that would be written now (nothing is written)."""
    have = table_ids(backlog)
    return [(b, s) for b, s in _wanted(ids, sha_of)[0] if b not in have]


def sync_stale(backlog, ids, sha_of, note="") -> dict:
    """Write the rows the triage proved closed by a commit (``sha_of``: {ID: sha}).  A row without a commit sha is
    reported in ``no_sha`` and never written.  -> {"added": [...], "present": [...], "no_sha": [...]}."""
    wanted, no_sha = _wanted(ids, sha_of)
    res = record_closures(backlog, [(b, s, note) for b, s in wanted]) if wanted else {}
    return {"added": [b for b, r in res.items() if r == "added"], "present": [b for b, r in res.items() if r == "present"],
            "no_sha": no_sha}


AUDIT_MARK = " · audit: "


@_thread_locked
def _edit_row(backlog, bid, change) -> str:
    """The closure row of ``bid``: ``change(cells)`` returns the new cells, or None to drop the row.  Atomic, line endings kept.
    -> done / absent / no_section / unreadable / error (never raises)."""
    with _locked(backlog):
        return _edit_row_unlocked(backlog, bid, change)


def _edit_row_unlocked(backlog, bid, change) -> str:
    path = Path(backlog)
    raw = _read(path)
    if raw is None:
        return "unreadable"
    eol = _eol(raw)
    lines = raw.split(eol)
    start, end = _section(lines)
    if start is None:
        return "no_section"
    at = next((i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")
               and lines[i].strip().strip("|").split("|")[0].strip() == str(bid).strip()), None)
    if at is None:
        return "absent"
    cells = [c.strip() for c in lines[at].strip().strip("|").split("|")]
    new = change(cells)
    if new is None:
        del lines[at]
    else:
        lines[at] = "| " + " | ".join(new) + " |"
    tmp = path.with_name(path.name + ".closure.tmp")
    try:
        tmp.write_bytes(eol.join(lines).encode("utf-8"))
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return "error"
    return "done"


def add_evidence(backlog, bid, text) -> str:
    """4.2 (<id>): the audit verdict goes into the evidence cell of the row's closure («... · audit: <text>»); a second call
    replaces the first verdict, never stacks.  -> updated / absent / no_section / unreadable / error."""
    def change(cells):
        while len(cells) < 3:
            cells.append("")
        cells[2] = cells[2].split(AUDIT_MARK)[0].rstrip() + AUDIT_MARK + _cell(text)
        return cells
    got = _edit_row(backlog, bid, change)
    return "updated" if got == "done" else got


def reopen(backlog, bid) -> str:
    """4.2 (<id>): the closure row of ``bid`` leaves the table, so the row is «new» again.  -> reopened / absent / no_section /
    unreadable / error."""
    got = _edit_row(backlog, bid, lambda cells: None)
    return "reopened" if got == "done" else got


PENDING = "merged by the loop (not yet taken)"


@_thread_locked
def update_note(backlog, bid, sha, note) -> str:
    """The closure row of ``bid`` (its commit starts with the first 8 characters of ``sha``) says «merged by the loop (not yet
    taken)»: that phrase becomes ``note``.  Atomic, line endings kept, every other line untouched.
    -> updated / absent / not_pending / mismatch / no_section / unreadable / error (never raises)."""
    with _locked(backlog):
        return _update_note(backlog, bid, sha, note)


def _update_note(backlog, bid, sha, note) -> str:
    path = Path(backlog)
    raw = _read(path)
    if raw is None:
        return "unreadable"
    eol = _eol(raw)
    lines = raw.split(eol)
    start, end = _section(lines)
    if start is None:
        return "no_section"
    verdict = "absent"
    for i in range(start + 1, end):
        if not lines[i].lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] != str(bid).strip():
            continue
        if sha and not cells[1].startswith(_cell(sha)[:SHA_LEN]):
            verdict = "mismatch"
            continue
        if PENDING not in cells[2]:
            verdict = "not_pending"
            continue
        cells[2] = cells[2].replace(PENDING, _cell(note))
        lines[i] = "| " + " | ".join(cells) + " |"
        verdict = "updated"
        break
    if verdict != "updated":
        return verdict
    tmp = path.with_name(path.name + ".closure.tmp")
    try:
        tmp.write_bytes(eol.join(lines).encode("utf-8"))
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return "error"
    return "updated"
