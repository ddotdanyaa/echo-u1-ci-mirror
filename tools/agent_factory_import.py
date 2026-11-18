"""Import existing N01–N200 proof register into a *review-only* task inventory.

The register class DONE is not acceptance, and its evidence filenames are NOT
an authorization to edit those files or publish them to free models. This
adapter deliberately does not manufacture executable READY tasks.
"""
from __future__ import annotations

import argparse
import json
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


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    from tools.backlog_register import register
    result = suggestions(register())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tasks_needing_review": len(result["tasks"]),
                      "executable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
