"""Import existing N01–N200 proof register into a *review-only* task inventory.

The register class DONE is not acceptance, and its evidence filenames are NOT
an authorization to edit those files or publish them to free models. This
adapter deliberately does not manufacture executable READY tasks.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import re
from pathlib import Path


def suggestions(rows: list[dict]) -> dict:
    items = []
    seen = set()
    for row in rows:
        rid = row["id"]
        if rid in seen:
            raise ValueError("duplicate register ID")
        seen.add(rid)
        if row.get("accepted"):
            continue
        proof = row.get("files", [])
        impl = [f for f in proof if isinstance(f, str) and f.startswith("echo_sync/")]
        tests = [f for f in proof if isinstance(f, str) and f.startswith("tests/") and f.endswith(".py")]
        needs_owner = row.get("class") in ("OWNER", "LATER")
        items.append({
            "id": rid, "title": str(row.get("what", ""))[:240],
            "class": row.get("class"), "accepted": False,
            "status": "NEEDS_OWNER" if needs_owner else "NEEDS_SCOPE_REVIEW",
            "proof_sources": sorted(set(proof)),
            "proposed_touch_files": sorted(set(impl)),
            "proposed_tests": sorted(set(tests)),
            "privacy_safe": False,
            "depends_on": [],  # register has no guaranteed dependency DAG
            "review_required": [
                "which exact code files may change",
                "which immutable tests prove acceptance",
                "real DAG dependencies",
                "is source safe for a free third-party model",
                "what live/profile acceptance is still required",
            ],
        })
    return {"schema": "factory-review-v1", "origin": "tools.backlog_register.register",
            "not_executable": True, "tasks": items}


IDENT = re.compile(r"^(?:E|W|U|R|T)\d{1,3}(?:\.\d{1,2})?$")
ACTIVE_START = re.compile(r"^##\s+4\.\s")
ACTIVE_END = re.compile(r"^##\s+5\.\s")
N_SERIES = re.compile(r"^###\s+4\.6(?:\s|$)")


def active_backlog_review(markdown: str) -> dict:
    """Review-only index from the *current* BACKLOG_ECHO.md section 4.

    A row is indexed by its actual table ID; history, duplicate references
    and the N01-N200 section (owned by backlog_register) are not tasks.
    We do not parse untrusted prose into executable instructions, dependencies,
    claimed DONE status, or prompts to third-party models.
    """
    if not isinstance(markdown, str):
        raise TypeError("backlog is text")
    lines = markdown.splitlines()
    started = False
    ended = False
    section = ""
    skip_n = False
    found: dict[str, dict] = {}
    for line_no, line in enumerate(lines, 1):
        if not started:
            if ACTIVE_START.match(line):
                started = True
            continue
        if ACTIVE_END.match(line):
            ended = True
            break
        if line.startswith("### "):
            section = line.lstrip("# ").split(" ", 1)[0]
            skip_n = bool(N_SERIES.match(line))
            continue
        if skip_n or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or not IDENT.fullmatch(cells[0]):
            continue
        tid = cells[0]
        if tid not in found:
            found[tid] = {
                "id": tid, "title": "Review source item " + tid,
                "status": "NEEDS_TRIAGE",
                "accepted": False,
                "privacy_safe": False,
                "only_opus": False,
                "depends_on": [],  # dependencies in prose are NOT a trusted DAG
                "touch_files": [],
                "tests": [],
                "source": "BACKLOG_ECHO.md",
                "locations": [],
                "review_required": [
                    "verify current status from primary evidence",
                    "identify source/test paths and dependent tasks",
                    "resolve aliases/cycles by an authorized reviewer",
                    "approve privacy classification and model assignment",
                ],
            }
        found[tid]["locations"].append({"line": line_no, "section": section})
    if not started or not ended:
        raise ValueError("expected bounded authoritative section 4")
    missing = sorted({"U243", "U244"} - set(found))
    return {
        "schema": "factory-review-v1",
        "origin": "BACKLOG_ECHO.md section 4",
        "sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "not_executable": True,
        "missing_referenced_ids": missing,
        "tasks": [found[k] for k in sorted(found)],
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--source-backlog", type=Path,
                   default=Path(__file__).resolve().parents[1] / "BACKLOG_ECHO.md")
    args = p.parse_args(argv)
    from tools.backlog_register import register
    result = suggestions(register())
    backlog = active_backlog_review(args.source_backlog.read_text(encoding="utf-8"))
    common = {task["id"] for task in result["tasks"]}
    result["tasks"].extend(item for item in backlog["tasks"] if item["id"] not in common)
    result["backlog_sha256"] = backlog["sha256"]
    result["missing_referenced_ids"] = backlog["missing_referenced_ids"]
    result["not_executable"] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tasks_needing_review": len(result["tasks"]),
                      "missing_referenced_ids": result["missing_referenced_ids"],
                      "executable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
