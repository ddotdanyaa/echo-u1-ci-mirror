"""<id>: one writer of the backlog's closures table («## Закрыто коммитами координатора ...», rows ``| ID | sha | note |``).

Atomic (temp file + replace), idempotent (an ID already in the table is never written twice), line endings kept.
Never raises: the result is a word - added / present / no_section / unreadable / error.
"""
import os
import re
from pathlib import Path

HEADING = "## Закрыто коммитами координатора"
SHA_LEN = 8


def _cell(text) -> str:
    return re.sub(r"\s+", " ", str(text).replace("|", "/")).strip()


def record_closure(backlog, bid, sha, note="") -> str:
    path = Path(backlog)
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return "unreadable"
    eol = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(eol)
    start = next((i for i, x in enumerate(lines) if x.startswith(HEADING)), None)
    if start is None:
        return "no_section"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    last = None
    for i in range(start + 1, end):
        if lines[i].lstrip().startswith("|"):
            last = i
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if cells and cells[0] == str(bid).strip():
                return "present"
    if last is None:
        return "no_section"
    row = "| %s | %s | %s |" % (_cell(bid), _cell(sha)[:SHA_LEN], _cell(note))
    lines.insert(last + 1, row)
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
    return "added"
