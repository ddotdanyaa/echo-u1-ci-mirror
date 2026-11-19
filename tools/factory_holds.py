"""<id>/<id>: the free head model answers the mechanical holds (which file to change) so they become tasks without
Opus. Pure helpers: the kind of a hold question, the paths it names, the prompt, the strict parse of the answer
and the pick of the holds to ask. The loop wiring is Loop._head_holds."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

AMBIGUOUS = "локализация неоднозначна"
SCOPE = "уточнить область"
REPEAT_S = 24 * 3600
# A pick must fit the light engine (agent_factory_runner.LIGHT_MAX_FILES; the lock test ties the two): live 20.11
# 02:18-02:23 the head picked all three candidates of <id>, the task went to the Kilo engine and burned its three
# attempts in two minutes (steps exhausted; Kilo 0 of 4 that night). A change of more files is a skip for Opus.
MAX_FILES = 2
NOTE_MAX = 300
_PATH = re.compile(r"(?<![\w/.-])((?:echo_sync|tests)/[\w./-]*?\.py)(?![\w])")


def kind_of(question) -> str | None:
    text = str(question or "").strip().lower()
    if text.startswith(AMBIGUOUS):
        return "ambiguous"
    if text.startswith(SCOPE):
        return "scope"
    return None


def candidates(question) -> tuple[list, list]:
    """(echo_sync files, tests) named in the question, in order, without duplicates."""
    files, tests = [], []
    for path in _PATH.findall(str(question or "")):
        bucket = files if path.startswith("echo_sync/") else tests
        if path not in bucket:
            bucket.append(path)
    return files, tests


def row_test(bid, mirror) -> str | None:
    """The row's own verify test in the mirror: tests/verify/**/test_v_<id>.py, only when exactly one exists."""
    norm = re.sub(r"[.\-]", "_", str(bid or "")).lower()
    if not norm:
        return None
    root = Path(mirror) / "tests" / "verify"
    want = "test_v_%s.py" % norm
    try:
        found = sorted(p for p in root.rglob("*.py") if p.name.lower() == want)
    except OSError:
        return None
    if len(found) != 1:
        return None
    return found[0].relative_to(Path(mirror)).as_posix()


def prompt(bid, goal, question, files, tests, outlines) -> str:
    parts = [
        "You choose which source files a coding task must change. Answer with ONE JSON object only, no prose, "
        "no code fence.",
        'Either {"touch_files": [1 to %d paths chosen ONLY from the candidates below], "note": "<one technical '
        'sentence for the coder: what to change and where, no quotes>"}' % MAX_FILES,
        'or {"skip": "<why no candidate fits>"}.',
        "Task %s." % bid,
        "Goal: %s" % goal,
        "Question: %s" % question,
        "Candidates: %s" % ", ".join(files),
        "Tests that must pass: %s" % (", ".join(tests) or "(none)"),
    ]
    for path in files:
        parts.append("Outline of %s:\n%s" % (path, outlines.get(path, "(not available)")))
    return "\n\n".join(parts)


def _first_object(text):
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def parse(answer, files) -> dict | None:
    obj = _first_object(str(answer or ""))
    if obj is None:
        return None
    if "skip" in obj and "touch_files" not in obj:
        reason = obj.get("skip")
        return {"skip": " ".join(str(reason).split())[:200]} if isinstance(reason, str) else None
    chosen = obj.get("touch_files")
    if (not isinstance(chosen, list) or not chosen or len(chosen) > MAX_FILES
            or not all(isinstance(p, str) and p in files for p in chosen)):
        return None
    note = obj.get("note", "")
    if not isinstance(note, str):
        return None
    note = " ".join(re.sub(r"[\"'`«»“”„()\[\]{}<>]", "", note).split())
    if len(note) > NOTE_MAX:
        return None
    return {"touch_files": list(dict.fromkeys(chosen)), "note": note}


def _age_ok(entry, now) -> bool:
    if not isinstance(entry, dict):
        return True
    if entry.get("status") == "later":        # the head was not reached: ask again at once
        return True
    at = entry.get("at")
    try:
        stamp = float(at) if isinstance(at, (int, float)) else dt.datetime.fromisoformat(str(at)).timestamp()
    except (TypeError, ValueError):
        return True
    return now - stamp >= REPEAT_S


def select(holds, done, now, limit=3) -> list:
    out = []
    for bid in sorted(holds or {}):
        question = holds[bid]
        if not isinstance(question, str) or kind_of(question) is None:
            continue
        if bid in (done or {}) and not _age_ok(done[bid], now):
            continue
        out.append((bid, question))
        if len(out) >= limit:
            break
    return out
