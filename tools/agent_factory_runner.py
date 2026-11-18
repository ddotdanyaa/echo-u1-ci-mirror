"""Opt-in Kilo queue executor; defaults to planning, never deploying.

IMPORTANT: a copied work directory and git worktree are NOT OS sandboxes.
The --execute flag requires an explicit risk acknowledgement and a separately
configured account/OS sandbox when privacy matters. No file from the source
project is written back automatically.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from .agent_factory import (InvalidPlan, Task, acquire, backoff, load_state,
                            read_plan, ready, receipt_digest, route, quarantine,
                            safe_path, safe_source, save_atomic, settle)

RATE_LIMIT = re.compile(r"\b429\b|resource[_ -]?exhausted|rate.?limit", re.I)
AUTH_FAILURE = re.compile(r"\b(?:401|403)\b|permission[_ -]?denied|invalid authentication|"
                          r"location is not supported", re.I)
SERVER_FAILURE = re.compile(r"\b50[0-9]\b|internal server error|service unavailable", re.I)
ENV_ALLOW = ("PATH", "PATHEXT", "SystemRoot", "WINDIR", "COMSPEC", "LANG")
POLICY_FILE = "kilo.jsonc"


def worker_policy(task: Task) -> dict:
    """Kilo 1.0 project permission syntax; policy is frozen in the staging snapshot.

    This is application-level enforcement, NOT an OS sandbox.
    """
    edit = {"*": "deny"}
    edit.update({name: "allow" for name in sorted(task.touch_files)})
    return {
        "$schema": "https://app.kilo.ai/config.json",
        "enabled_providers": ["google"],
        "provider": {"google": {"env": ["GOOGLE_GENERATIVE_AI_API_KEY"]}},
        "mcp": {},
        "formatter": False,
        "lsp": False,
        "permission": {
            "*": "deny",
            "read": {"*": "allow", "*.env": "deny", "**/*.env": "deny",
                     "*.env.*": "deny", "**/*.env.*": "deny"},
            "edit": edit,
            "glob": "allow",
            "grep": "allow",
            "external_directory": "deny",
            "bash": "deny",
            "task": "deny",
            "agent_manager": "deny",
            "websearch": "deny",
            "webfetch": "deny",
            "doom_loop": "deny",
            "skill": "deny",
        },
    }


def source_path(root: Path, name: str) -> Path:
    safe_path(name)
    parent = root.resolve()
    parts = name.split("/")
    # A harmless-looking alias to a hidden directory is still a privacy leak.
    for depth in range(1, len(parts) + 1):
        if root.joinpath(*parts[:depth]).is_symlink():
            raise InvalidPlan("symlink component in source path")
    path = root.joinpath(*parts)
    if not path.resolve().is_relative_to(parent):
        raise InvalidPlan("path escapes source root")
    return path


def prepare(root: Path, task: Task, workdir: Path) -> dict[str, bytes]:
    """Copy only explicitly approved files, never .git, .env or any symlink.

    Existing tests are immutable. Safe staged sources still require external
    OS sandboxing before calling autonomous Kilo against real private code.
    """
    root = root.resolve()
    workdir.mkdir(parents=True, exist_ok=False)
    names = set(task.read_files) | set(task.touch_files) | set(task.tests)
    if set(task.touch_files) & set(task.tests):
        raise InvalidPlan("existing acceptance tests are immutable")
    if not task.privacy_safe:
        raise InvalidPlan("private plan must not be staged for free-tier Google")
    if any(safe_path(name) != name for name in names):
        raise InvalidPlan("unsafe filename")
    if len(names) > 100:
        raise InvalidPlan("overbroad task scope")
    if len(task.title) > 240 or re.search(r"AIza[0-9A-Za-z_-]+|sk-[0-9A-Za-z_-]+", task.title):
        raise InvalidPlan("unsafe prompt")
    staged: dict[str, bytes] = {}
    for name in sorted(names):
        src = source_path(root, name)
        # Nonexistent touch-files are permitted only as explicit new outputs.
        if not src.exists() and name in task.touch_files and name not in task.read_files:
            continue
        if not src.exists():
            raise InvalidPlan("required input missing")
        data = safe_source(src)
        dest = workdir.joinpath(*name.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        staged[name] = data
    # The model may not create/replace its own permissions. The file is also
    # compared byte-for-byte after coding and after pytest.
    conf = (json.dumps(worker_policy(task), sort_keys=True, ensure_ascii=False,
                       indent=2) + "\n").encode("utf-8")
    (workdir / POLICY_FILE).write_bytes(conf)
    staged[POLICY_FILE] = conf
    return staged


def inspect_changes(task: Task, workdir: Path, staged: dict[str, bytes]) -> tuple[str, ...]:
    """Reject changed tests, other files, deletion and generated test weakening."""
    allowed = set(task.touch_files)
    unchanged = ((set(task.read_files) | set(task.tests)) - allowed) | {POLICY_FILE}
    found: dict[str, bytes] = {}
    for p in workdir.rglob("*"):
        if p.is_symlink():
            raise InvalidPlan("symlink created in working copy")
        if not p.is_file():
            continue
        rel = p.relative_to(workdir).as_posix()
        if rel != POLICY_FILE:
            safe_path(rel)
        if rel not in allowed | unchanged:
            raise InvalidPlan("unapproved file created")
        found[rel] = safe_source(p)
    if set(found) - set(staged) - allowed:
        raise InvalidPlan("unapproved output")
    for name in unchanged:
        if name not in found or staged.get(name) != found[name]:
            raise InvalidPlan("acceptance input/test changed")
    for name in set(staged) & allowed:
        if name not in found:
            raise InvalidPlan("worker deleted source")
    return tuple(sorted(n for n in allowed if found.get(n) != staged.get(n)))


def gates(task: Task, workdir: Path, staged: dict[str, bytes],
          *, timeout: int = 120) -> tuple[bool, str, tuple[str, ...]]:
    """Compile, execute real pytest, validate JUnit and recheck immutable files.

    A zero-exit test suite with every case skipped is NOT passing evidence.
    """
    try:
        changed = inspect_changes(task, workdir, staged)
        if not changed:
            raise InvalidPlan("no approved output produced")
        for name in changed:
            if name.endswith(".py"):
                source = workdir.joinpath(*name.split("/")).read_text(encoding="utf-8")
                compile(source, name, "exec")
        if not task.tests:
            raise InvalidPlan("no immutable acceptance tests supplied")
        env = {k: v for k, v in os.environ.items() if k in ENV_ALLOW}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                   PYTHONDONTWRITEBYTECODE="1")
        with tempfile.TemporaryDirectory(prefix="factory-junit-") as d:
            xml = Path(d) / "result.xml"
            args = [sys.executable, "-m", "pytest", "-q", "--tb=short",
                    "-p", "no:cacheprovider", "--junitxml=" + str(xml), *task.tests]
            run = subprocess.run(args, cwd=workdir, env=env,
                                 capture_output=True, timeout=timeout)
            cases = list(ET.parse(xml).getroot().iter("testcase")) if xml.is_file() else []
            passed = sum(1 for case in cases
                         if not any(child.tag in ("skipped", "error", "failure")
                                    for child in case))
        # pytest executes untrusted code. A successful return cannot grant
        # permission to alter test files or the project policy during the run.
        same_changes = inspect_changes(task, workdir, staged) == changed
        accepted = run.returncode == 0 and passed > 0 and same_changes
        return accepted, receipt_digest(run.stdout, run.stderr, run.returncode), changed
    except (InvalidPlan, OSError, SyntaxError, UnicodeError,
            subprocess.TimeoutExpired, ET.ParseError) as error:
        return False, sha256(type(error).__name__.encode()).hexdigest(), ()


def model_attempt(task: Task, workdir: Path, model: str, timeout: int) -> tuple[int, bytes, bytes]:
    """Invoke Kilo with a frozen project policy and a temporary clean profile.

    The explicitly selected Google auth key is the only provider credential
    forwarded. No secret is placed in argv, model prompt or kilo.jsonc.
    """
    prompt = ("Implement ONLY task " + task.id + ": " + task.title +
              ". Change only: " + ", ".join(task.touch_files) +
              ". Read-only tests: " + ", ".join(task.tests) +
              ". Do not modify tests, execute deployment, read parent folders, "
              "or use network tools other than the configured model.")
    binary = shutil.which("kilo") or "kilo"
    if os.name == "nt" and binary.lower().endswith((".cmd", ".bat")):
        # Windows npm command shims are batch scripts and can receive shell
        # metacharacters in user-provided prompts. Require native kilo.exe.
        return 125, b"", b"native-kilo-exe-required"
    with tempfile.TemporaryDirectory(prefix="factory-kilo-home-") as home:
        base = Path(home)
        dirs = {name: base / name for name in
                ("config", "cache", "data", "appdata", "localappdata", "npm-cache")}
        for dest in dirs.values():
            dest.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k in ENV_ALLOW}
        env.update(HOME=home, USERPROFILE=home,
                   XDG_CONFIG_HOME=str(dirs["config"]),
                   XDG_CACHE_HOME=str(dirs["cache"]),
                   XDG_DATA_HOME=str(dirs["data"]),
                   APPDATA=str(dirs["appdata"]),
                   LOCALAPPDATA=str(dirs["localappdata"]),
                   NPM_CONFIG_CACHE=str(dirs["npm-cache"]),
                   TEMP=home, TMP=home, PYTHONUTF8="1",
                   PYTHONIOENCODING="utf-8")
        google = os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY", "")
        if google:
            env["GOOGLE_GENERATIVE_AI_API_KEY"] = google
        args = [binary, "run", "--auto", "--model", model, prompt]
        try:
            p = subprocess.run(args, cwd=workdir, env=env,
                               capture_output=True, timeout=timeout, shell=False)
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            # Python stops the direct process; it cannot prove all descendants
            # terminated on Windows. The caller must quarantine the task.
            return 124, b"", b"timeout-worker-descendants-unknown"



def once(*, root: Path, plan: Path, checkpoint: Path, staging: Path,
         small_model: str, large_model: str, execute: bool = False,
         acknowledge: bool = False) -> dict:
    tasks = read_plan(json.loads(plan.read_text(encoding="utf-8")))
    if staging.resolve().is_relative_to(root.resolve()):
        raise InvalidPlan("staging inside source project is forbidden")
    if checkpoint.resolve().is_relative_to(root.resolve()):
        raise InvalidPlan("checkpoint inside source project is forbidden")
    # The checkpoint is local. Exclusive directory creation is an atomic
    # single controller lock on supported filesystems, with no stale stealing.
    lock = checkpoint.with_suffix(checkpoint.suffix + ".lockdir")
    try:
        lock.mkdir(parents=True, exist_ok=False)
    except FileExistsError as e:
        raise InvalidPlan("another controller or stale lock owns state") from e
    try:
        state = load_state(checkpoint, tasks)
        candidates = ready(tasks, state)
        if not candidates:
            return {"status": "IDLE", "next": None, "deploy_blocked": state["deploy_blocked"]}
        tid = candidates[0]
        task = tasks[tid]
        model = route(task, small_model=small_model, large_model=large_model)
        if not execute:
            return {"status": "DRY_RUN", "next": tid, "model": model,
                    "deploy_blocked": state["deploy_blocked"]}
        if not acknowledge:
            raise InvalidPlan("autonomous Kilo is not OS isolated: explicit opt-in required")
        if not shutil.which("kilo"):
            raise InvalidPlan("kilo command unavailable")
        if not os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY"):
            raise InvalidPlan("Google API auth key must be set in the caller environment")
        token = acquire(tasks, state, tid)
        save_atomic(checkpoint, state)
        prefix = "task-" + tid + "-" + token[:8]
        workdir = staging / prefix
        logs = b""
        error = b""
        rc = 1
        try:
            baseline = prepare(root, task, workdir)
            stopped = None
            for attempt in range(2):  # at most two invocations, including a 429 fallback
                chosen = route(task, small_model=small_model, large_model=large_model,
                               fallback=bool(attempt))
                if attempt:
                    if state["model_calls"] >= state["max_model_calls"]:
                        stopped = "all_channels_throttled"
                        break
                    state["model_calls"] += 1
                    save_atomic(checkpoint, state)
                    time.sleep(backoff(attempt - 1))
                    # A failed worker may have written new files; never reuse it.
                    workdir = staging / (prefix + "-retry-" + str(attempt))
                    baseline = prepare(root, task, workdir)
                rc, logs, error = model_attempt(task, workdir, chosen, timeout=240)
                if rc == 0:
                    break
                detail = (logs + b"\n" + error)[:15000].decode("utf-8", errors="replace")
                if rc == 124:
                    stopped = "worker_timeout"
                    break
                if rc == 125:
                    stopped = "unsafe_windows_launcher"
                    break
                if AUTH_FAILURE.search(detail):
                    stopped = "provider_auth"
                    break
                is_throttled = bool(RATE_LIMIT.search(detail))
                retryable = is_throttled or bool(SERVER_FAILURE.search(detail))
                if not retryable:
                    break
                if attempt == 1:
                    stopped = "all_channels_throttled" if is_throttled else "provider_unavailable"
                    break
            if stopped:
                quarantine(state, tid, token, reason=stopped)
                save_atomic(checkpoint, state)
                return {"status": "BLOCKED", "task": tid,
                        "blocked_reason": stopped,
                        "deploy_blocked": state["deploy_blocked"]}
            if rc == 0:
                ok, receipt, changed = gates(task, workdir, baseline)
            else:
                ok, changed = False, ()
                receipt = receipt_digest(logs, error, rc)
            if ok:
                # A verified candidate is for external human review. Never
                # overlay worktree or Conduit from inside this executor.
                reviewed = staging / "for-review" / tid
                if reviewed.exists():
                    raise InvalidPlan("previous review package exists")
                reviewed.mkdir(parents=True)
                for name in changed:
                    dst = reviewed.joinpath(*name.split("/"))
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(workdir.joinpath(*name.split("/")), dst)
            status = settle(state, tid, token, tests_ok=ok, evidence=receipt)
            save_atomic(checkpoint, state)
            return {"status": status, "task": tid, "changed": len(changed),
                    "receipt_sha256": receipt, "deploy_blocked": state["deploy_blocked"]}
        except Exception as error_obj:
            # A failed policy/IO check may mean the model still has a live
            # descendant. Do not automatically dispatch the same task again.
            quarantine(state, tid, token,
                       reason="scope_violation" if isinstance(error_obj, InvalidPlan)
                       else "worker_exception")
            save_atomic(checkpoint, state)
            return {"status": "BLOCKED", "task": tid,
                    "error_type": type(error_obj).__name__,
                    "blocked_reason": state["tasks"][tid]["blocked_reason"]}
    finally:
        lock.rmdir()


def main(argv=None):
    p = argparse.ArgumentParser(description="Fail-closed experimental Kilo task runner")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--staging", type=Path, required=True)
    p.add_argument("--small-model", required=True)
    p.add_argument("--large-model", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--ack-host-access-risk", action="store_true")
    p.add_argument("--max-tasks", type=int, default=1,
                   help="execute at most N sequential tasks; no implicit daemon")
    args = p.parse_args(argv)
    if not 1 <= args.max_tasks <= 10:
        p.error("--max-tasks must be in 1..10")
    if args.execute and args.staging.resolve().is_relative_to(args.root.resolve()):
        p.error("staging must not be within original repository")
    outcomes = []
    for _ in range(args.max_tasks if args.execute else 1):
        result = once(root=args.root, plan=args.plan, checkpoint=args.checkpoint,
                      staging=args.staging, small_model=args.small_model,
                      large_model=args.large_model, execute=args.execute,
                      acknowledge=args.ack_host_access_risk)
        outcomes.append(result)
        if result["status"] not in ("REVIEW", "READY"):
            break
    for result in outcomes:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if all(x["status"] in ("DRY_RUN", "REVIEW", "IDLE")
                    for x in outcomes) else 2


if __name__ == "__main__":
    sys.exit(main())
