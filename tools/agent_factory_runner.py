"""Opt-in Kilo queue executor; defaults to planning, never deploying.

IMPORTANT: a copied work directory and git worktree are NOT OS sandboxes.
The --execute flag requires an explicit risk acknowledgement and a separately
configured account/OS sandbox when privacy matters. No file from the source
project is written back automatically.

One pass = one task: red-before on the base, ONE coder call, deterministic gates
(factory_gate), neighbour tests, an independent reviewer. A rejected candidate returns
its feedback and diff to the next pass; channel and provider faults are never strikes.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import replace

from .agent_factory import (BudgetExhausted, DEFER_REASONS, LEASE_LIFETIME_S, LOCK_OWNER, MODEL_ID, InvalidPlan, Task, acquire, add_feedback, charge_call,
                            defer, defer_streak, seconds_to_local_midnight,
                            load_state, read_plan, ready, redact,
                            route, quarantine, safe_path, safe_source, save_atomic, settle)
from .factory_context import (LARGE_FILE_CHARS, identifier_tokens, keywords_from, packet, render,
                              scrub_paths)
from .factory_process import kilo_argv, run_owned
from . import affected_tests
from . import factory_channels as channels
from . import factory_gate as gate
from . import factory_quota as quota_ledger

ENV_ALLOW = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "LANG")
POLICY_FILE = "kilo.jsonc"
PROVIDER_STEPS = 8   # coder: outline -> read by lines -> grep -> edit needs room (3 was too few)
REVIEW_STEPS = 4     # the reviewer only reads and answers


ENV_HOLD_AFTER = 10          # consecutive environment shortages before the long hold (the candidate is kept)
ENV_HOLD_S = 1800
ENV_OTHER_CEILING = 3         # a persistent non-slot environment failure (a missing package...) is parked after this many
RED_BEFORE_WAIT_S = 120      # the base run before the coder call waits for a slot at most this long (its own ceiling)
SLOT_BUDGET_S = 300         # ONE wait for a pytest slot / free RAM per runner pass, shared by every gate run
IDLE_SUSPECTS_ALLOWED = 2   # idle timeouts treated as a rate limit; the next one is a worker fault (infra)


def factory_env(state: dict) -> dict:
    """The runner's own counters (idle timeouts, environment shortages): a state key of their own, because a
    name inside channel_quotas would be read as a quota group."""
    table = state.get('factory_env')
    if not isinstance(table, dict):
        table = state['factory_env'] = {}
    for name in ('idle', 'shortages', 'other'):
        if not isinstance(table.get(name), dict):
            table[name] = {}
    return table


def _now() -> float:
    """The runner's clock for the slot budget (tests replace THIS, never the global time module)."""
    return time.monotonic()


def kilo_config(provider: str, auth_env: str, steps: int) -> dict:
    """The process-owned Kilo config: the key reference and ONE agent. No prompt/system until the canary proves it."""
    return {"provider": {provider: {"options": {"apiKey": '{env:' + auth_env + '}'}}},
            'enabled_providers': [provider],
            'agent': {'factory': {'description': 'Bounded task executor', 'mode': 'primary',
                                  'steps': steps or PROVIDER_STEPS}}}


def requests_for(steps: int) -> int:
    """Provider requests of one multi-step call: every step plus the final answer after the tool limit."""
    return steps + 1

GATE_TIMEOUT_S = 30                   # owner rule: pytest never longer than 30 s
MAX_NEIGHBORS = 6
INFRA_DEFER_S = 300
DIFF_LIMIT = 3000
REVIEW_DIFF_LIMIT = 6000
# infra=True (counts toward the loop brake) ONLY for a dead channel or no result from the process;
# a slow test, a prose answer, a 429 or a blocked task is the task's or the model's business
INFRA_DEFERS = frozenset(("key_invalid", "balance", "model_missing"))  # real infrastructure faults


ESCALATE = frozenset(("gate_unknown", "provider_error", "no_independent_reviewer", "reviewer_failed"))
ESCALATE_AFTER = 3          # the same postponement this many times in a row becomes BLOCKED
INFRA_CHANNEL_REASONS = frozenset(("dead", "no_key", "no_channels", "reservation_exceeds_tpm"))
REVIEW_HINT = ("The file is large: read the places you need with the read tool by line numbers from the "
               "outline. Do not edit anything: you only judge the diff.")
LIGHT_REVIEW_HINT = "The file is large: only its outline and the parts below are shown. You only judge the diff."
# The test author's most frequent defects, from the reviewers' rejections of the live series 19.11 17:53-18:38
# (a MagicMock as the code under test, assert False, a name-exists tautology, counts of the repository)
UNIT_TEST_RULES = ("The test must import the real functions or classes from the code files shown and call them, "
                   "then assert on what they return or do. Never test a MagicMock in place of that code, never "
                   "write assert False, a test that only checks that a name exists, or a hard-coded count of "
                   "files or markers in the repository. The project has no pytest-asyncio plugin: never write "
                   "async def test functions or @pytest.mark.asyncio; drive async code with asyncio.run(...) inside "
                   "a plain def test function.")
MARKER_PROBE = gate.GateResult(1, 1, 0, 1, 0, 0, True, '')   # a red result: only the marker can fail it
REVIEW_OVERHEAD = 1500      # reviewer instructions + verdict format on top of the files
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".env*", "SECRETS_LOCAL",
                                     "*.pem", "*.key")


class ChannelFault(Exception):
    """The channel or provider failed; the candidate is not to blame (no strike)."""

    def __init__(self, info: dict, wait_s: float = 0.0):
        super().__init__(info.get('kind', 'unknown'))
        self.info, self.wait_s = info, wait_s


class NoIndependentReviewer(Exception):
    """Only the coder's own model is available: the review waits (never a self-review)."""


class PromptTooLarge(Exception):
    """Prompt over the limit: not sent, no strike, the triage splits the task."""


class ReviewFault(Exception):
    """Reviewer call failed or answered with something that is not a verdict."""


def profile_names() -> tuple:
    """Names that identify the user: the home directory name and the login."""
    names = {Path.home().name, os.environ.get('USERNAME', ''), os.environ.get('USER', '')}
    return tuple(sorted(n for n in names if n))


def staging_reveals_profile(path) -> bool:
    """True when a WHOLE segment of the resolved path is the user's name (substrings of other words, such as
    'an' in 'agent-factory', are not a leak). 8.3 names are expanded by resolve()."""
    segments = {part.lower() for part in Path(path).resolve().parts}
    return any(name.lower() in segments for name in profile_names())


PROFILE_LEAK_MESSAGE = ("staging под профилем пользователя раскрывает имя модели: Kilo кладёт рабочий каталог "
                        "в системный промпт; задайте --state-dir вне профиля, например C:" + chr(92) + "agent-factory"
                        + chr(92) + "echo")


@contextlib.contextmanager
def scratch_redirect(staging):
    """Every temporary directory of a pass (base copies, gate trees, pytest basetemp) goes to <staging>/tmp:
    %TEMP% is under the profile and its paths would reach the model through test output."""
    tmp = Path(staging) / 'tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    saved = (tempfile.tempdir, os.environ.get('TEMP'), os.environ.get('TMP'))
    tempfile.tempdir = str(tmp.resolve())
    os.environ['TEMP'] = os.environ['TMP'] = tempfile.tempdir
    try:
        if staging_reveals_profile(tempfile.gettempdir()):
            raise InvalidPlan(PROFILE_LEAK_MESSAGE)
        yield tmp
    finally:
        tempfile.tempdir = saved[0]
        for key, value in zip(('TEMP', 'TMP'), saved[1:]):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def sweep_scratch(staging, max_age: float = 86400.0) -> list:
    """Orphans of killed passes (Kilo homes, review copies, tmp/*) older than a day, strictly inside staging.
    Returns the names it could not remove (a held file): the caller records them. Junctions are never followed."""
    staging = Path(staging)
    failed: list = []
    isjunction = getattr(os.path, 'isjunction', lambda _p: False)
    found = list(staging.glob('factory-kilo-home-*')) + list(staging.glob('factory-review-*'))
    found += list((staging / 'tmp').glob('*')) if (staging / 'tmp').is_dir() else []
    for item in found:
        try:
            if (item.is_symlink() or isjunction(item) or not inside_staging(item.resolve(), staging)
                    or time.time() - item.stat().st_mtime <= max_age):
                continue
            if item.is_dir():
                shutil.rmtree(item, onexc=lambda _f, _p, _e, name=item.name: failed.append(name))
            else:
                item.unlink()
        except OSError:
            failed.append(item.name)
    return failed


def worker_policy(task: Task, readable=()) -> dict:
    """Kilo 1.0 project permission syntax; policy is frozen in the staging snapshot.

    This is application-level enforcement, NOT an OS sandbox.

    NOTE: grep sees EVERYTHING in the work copy: the read deny rules do not apply to it (a grep for a
    secret would find it). Safety rests on safe_path / DENY_PARTS keeping .env, .git and secrets out of
    the copy in the first place; external_directory deny keeps every tool inside the copy.
    """
    edit = {"*": "deny"}
    # Kilo matches rules against the ABSOLUTE path; bare names never match.
    edit.update({"**/" + name: "allow" for name in sorted(task.touch_files)})
    read = {'*': 'deny', '*.env': 'deny', '**/*.env': 'deny',
            '*.env.*': 'deny', '**/*.env.*': 'deny'}
    read.update({'**/' + name: 'allow' for name in sorted(set(task.touch_files + task.tests))})
    # big read-only files are not in the prompt whole: the agent reads them by line numbers
    read.update({'**/' + name: 'allow' for name in sorted(readable)})
    return {
        "$schema": "https://app.kilo.ai/config.json",
        "enabled_providers": ["google"],
        "mcp": {},
        "formatter": False,
        "lsp": False,
        "permission": {
            "*": "deny",
            "read": read,
            "edit": edit,
            # search is allowed ONLY inside the work copy: it holds the task files and nothing else, and
            # external_directory stays deny. For a 100 KB file grep is the way to find a function.
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
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


def visible_targets(task: Task) -> dict:
    """context_targets of the files a prompt may show sliced: never writable files or tests."""
    return {n: s for n, s in task.context_targets if n not in task.touch_files + task.tests}


def inside_staging(path, staging) -> bool:
    """True only for a path STRICTLY inside staging (staging itself and anything outside are not)."""
    try:
        return Path(staging).resolve() in Path(path).resolve().parents
    except (OSError, ValueError, RuntimeError):
        return False


ATTEMPT_TAG = re.compile(r'^\[attempt (\d+)\] ')


def fresh_feedback(state: dict, tid: str) -> str | None:
    """Feedback for the coder: the LAST attempt's gate/review findings and Opus notes written after it.
    Infrastructure notes ([infra] ...) and older attempts never reach the coder. The runner tags its own
    entries: reject() writes "[attempt N] ...", block() writes "[infra] ..."; Opus notes are untagged."""
    items = [i for i in (state['tasks'][tid].get('feedback') or []) if isinstance(i, dict)]
    last_opus = max((i for i, item in enumerate(items) if item.get('source') == 'opus'), default=-1)
    tail = [(i, item) for i, item in enumerate(items)
            if i > last_opus and item.get('source') in ('gate', 'review')]
    last_n = None
    for _, item in tail:
        m = ATTEMPT_TAG.match(str(item.get('text', '')))
        if m:
            last_n = int(m.group(1))
    if last_n is not None:
        keep = {i for i, item in tail
                if (m := ATTEMPT_TAG.match(str(item.get('text', '')))) and int(m.group(1)) == last_n}
    else:   # an old state without attempt tags: the last plain gate/review entry (requeue notes included)
        plain = [i for i, item in tail if not (item.get('source') == 'gate'
                                               and str(item.get('text', '')).startswith('[infra] '))]
        keep = set(plain[-1:])
    out = []
    for i, item in enumerate(items):
        text, source = str(item.get('text', '')), item.get('source')
        if source == 'opus':                      # every Opus note is an instruction, whatever its age
            out.append('[opus] ' + text)
        elif i in keep:
            m = ATTEMPT_TAG.match(text)
            out.append('[%s] %s' % (source, text[m.end():] if m else text))
    return '\n'.join(out) or None


def large_names(task: Task, files: dict[str, bytes]) -> set[str]:
    """Writable/read-only source files too big to be pasted into a prompt whole."""
    scope = set(task.touch_files) | set(task.read_files)
    return {n for n, v in files.items() if n in scope and n not in task.tests and len(v) > LARGE_FILE_CHARS}


def prepare(root: Path, task: Task, workdir: Path) -> dict[str, bytes]:
    """Copy only explicitly approved files, never .git, .env or any symlink.

    Existing tests are immutable for a code task. A unit_test task touches exactly its
    tests and the file may not exist yet (the model creates it). Safe staged sources
    still require external OS sandboxing before calling autonomous Kilo against private code.
    """
    root = root.resolve()
    workdir.mkdir(parents=True, exist_ok=False)
    names = set(task.read_files) | set(task.touch_files) | set(task.tests)
    if task.kind != "unit_test" and set(task.touch_files) & set(task.tests):
        raise InvalidPlan("existing acceptance tests are immutable")
    if not task.privacy_safe:
        raise InvalidPlan("private plan must not be staged for free-tier Google")
    if any(safe_path(name) != name for name in names):
        raise InvalidPlan("unsafe filename")
    if len(names) > 100:
        raise InvalidPlan("overbroad task scope")
    if len(task.title) > 240:
        raise InvalidPlan("unsafe prompt: title too long")
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
    # Count all visible bytes, including writable files and tests, not just prompt.
    big = large_names(task, staged)
    targets = visible_targets(task)   # only dependency context is sliced; writable files and tests stay whole
    # Big files reach the model as outline + fragments (and are read by line numbers): not counted here.
    # The task's budget (default 8 000) never caps below the prompt itself: render() checks the exact room
    # (live 19.11 21:24: <id>_test, 11 662 bytes against a 28 000-character prompt, was refused here).
    packet({n: v for n, v in staged.items() if n not in big}, targets,
           max_tokens=max(task.context_budget, channels.PROMPT_LIMIT_CHARS))
    # The model may not create/replace its own permissions. The file is also
    # compared byte-for-byte after coding and after pytest.
    conf = (json.dumps(worker_policy(task, readable=sorted(big & set(task.read_files))), sort_keys=True, ensure_ascii=False,
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
            raise InvalidPlan("unapproved file created: " + rel)
        found[rel] = safe_source(p)
    if set(found) - set(staged) - allowed:
        raise InvalidPlan("unapproved output")
    for name in unchanged:
        if name not in found or staged.get(name) != found[name]:
            raise InvalidPlan("acceptance input/test changed: " + name)
    for name in set(staged) & allowed:
        if name not in found:
            raise InvalidPlan("worker deleted source: " + name)
    return tuple(sorted(n for n in allowed if found.get(n) != staged.get(n)))


def neighbor_tests(root: Path, task: Task) -> list[str]:
    """Tests one import hop from the touched files (risk register #35): at most MAX_NEIGHBORS,
    only files that exist in ``root``, never the task's own tests. The graph is built over ``root``
    (the mirror of HEAD), not over the tool's tree. Any failure RAISES: the caller records
    ``neighbors_unavailable`` instead of silently treating it as "no neighbours"."""
    graph = affected_tests.Graph(Path(root))
    found, _, _ = affected_tests.affected(list(task.touch_files), radius=1, g=graph)
    out: list[str] = []
    for name in found:
        if name in task.tests or name in task.touch_files or name in out:
            continue
        if (Path(root) / name).is_file():
            out.append(name)
    return out[:MAX_NEIGHBORS]


def candidate_tree(root: Path, workdir: Path, changed, into: Path) -> Path:
    """Full copy of the source tree with the candidate files laid over it: real tests import
    the whole package (conftest, sibling modules) that the model's narrow copy lacks."""
    tree = into / "tree"
    shutil.copytree(root, tree, ignore=COPY_IGNORE)
    for name in changed:
        dest = tree.joinpath(*name.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workdir.joinpath(*name.split("/")), dest)
    return tree


def _note_read(result: dict, part: dict, workdir: Path | None) -> None:
    """Names of files the model read with its read tool (inside the work copy only, at most 10).
    Raw tool arguments are never kept. Event shape (best effort, see tests): part.tool == "read" and the
    path under part.state.input / part.input as filePath | file_path | path."""
    if workdir is None or str(part.get('tool') or part.get('name') or '').lower() != 'read':
        return
    state = part.get('state') if isinstance(part.get('state'), dict) else {}
    args = state.get('input') if isinstance(state.get('input'), dict) else part.get('input')
    if not isinstance(args, dict):
        return
    raw = next((args[k] for k in ('filePath', 'file_path', 'path') if isinstance(args.get(k), str)), None)
    if not raw:
        return
    if raw[:2] in ('//', chr(92) * 2) or (raw[1:2] == ':' and raw[2:3] not in ('/', chr(92))):
        return   # UNC (resolve() could wait on the network) and drive-relative "C:x" are never work-copy files
    try:
        base = Path(workdir).resolve()
        # an absolute raw replaces ``base``; ".." anywhere is resolved before the containment test
        name = (base / raw).resolve().relative_to(base).as_posix()
    except (OSError, ValueError, RuntimeError):
        return
    if name == '.' or name in result['files_read'] or len(result['files_read']) >= 10:
        return
    result['files_read'].append(name)


def event_summary(stdout: bytes, workdir: Path | None = None) -> dict:
    """Only allowlisted metadata; never persist raw prompts/tool arguments."""
    result = {'input_tokens': None, 'output_tokens': None, 'reasoning_tokens': None,
              'cache_read_tokens': None, 'cache_write_tokens': None, 'finish_reason': None,
              'tool_events': 0, 'provider_error': False, 'error_class': None,
              'http_status': None, 'text': '', 'steps': 0, 'files_read': [], 'last_step_tools': 0}
    since_step = 0
    for line in stdout.decode('utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get('part', {})
        if not isinstance(part, dict):
            continue
        if event.get('type') == 'error':
            result['provider_error'] = True
            error = event.get('error', {})
            if isinstance(error, dict):
                result['error_class'] = str(error.get('name', 'unknown'))[:80]
                data = error.get('data', {})
                if isinstance(data, dict) and type(data.get('statusCode')) is int:
                    result['http_status'] = data['statusCode']
        if event.get('type') == 'tool_use':
            result['tool_events'] += 1
            since_step += 1
            _note_read(result, part, workdir)
        if event.get('type') == 'text':
            result['text'] += str(part.get('text', ''))
        if event.get('type') == 'step_finish':
            result['steps'] += 1
            result['last_step_tools'], since_step = since_step, 0
            tokens = part.get('tokens', {})
            if isinstance(tokens, dict):
                # Kilo/OpenCode: part.tokens of step_finish is the usage of THAT step (one LLM call), not a running
                # total (opencode noninteractive.ts maps session.step.ended tokens 1:1), so the steps are summed.
                cache = tokens.get('cache') if isinstance(tokens.get('cache'), dict) else {}
                for field, value in (('input_tokens', tokens.get('input')), ('output_tokens', tokens.get('output')),
                                     ('reasoning_tokens', tokens.get('reasoning')),
                                     ('cache_read_tokens', cache.get('read')),
                                     ('cache_write_tokens', cache.get('write'))):
                    if type(value) is int and value >= 0:
                        result[field] = (result[field] or 0) + value
            result['finish_reason'] = part.get('reason')
    return result


def unified_diff(baseline: dict[str, bytes], workdir: Path, names, limit: int) -> str:
    """Redacted, truncated unified diff of the candidate against the baseline."""
    chunks = []
    for name in sorted(names):
        path = workdir.joinpath(*name.split("/"))
        if not path.is_file():
            continue
        old = baseline.get(name, b'').decode('utf-8', 'replace').splitlines(keepends=True)
        new = path.read_bytes().decode('utf-8', 'replace').splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(old, new, 'a/' + name, 'b/' + name, n=2))
    text = redact(''.join(chunks))
    return text if len(text) <= limit else text[:limit] + '\n[diff truncated]\n'


REVIEW_CHECKS = (
    'Check ALL of: (1) the behaviour is really fixed, no lost behaviour, no stubs, no incomplete '
    'error handling; (2) NO hard-coding: the candidate must not fit data or expectations to the '
    'test (special-casing test inputs, copying expected values) instead of fixing the behaviour; '
    '(3) NO scope creep: nothing outside the task and the listed files. A legitimate pass '
    'statement is not itself a defect.')
# A unit_test task writes ONLY the test; its code task comes after it. Live 19.11 19:14-19:16: with the checks of a
# fix the reviewer rejected good tests "the patch only adds a test case but does not implement the fix".
REVIEW_CHECKS_TEST = (
    'This task writes ONLY a test: the fix is a separate later task, so the code under test stays unchanged and '
    'the new test is expected to FAIL on it now. Never reject it because the code is not fixed. Check ALL of: '
    '(1) the test imports the real code and calls it, and asserts the behaviour the task describes; (2) it fails '
    'on the current code because of the described defect and would pass once the defect is fixed; (3) NO stub: no '
    'MagicMock in place of the code under test, no assert False, no test that only checks that a name exists, no '
    'hard-coded counts of files or markers in the repository; (4) nothing outside the test file.')
# Owner: «турнир нескольких кандидатов с последовательной цепочкой критиков». A pass of the light engine
# asks up to TOURNAMENT_SIZE coders, each a different model, and every next one is told why the previous one failed;
# the first candidate that passes the mechanical checks (it changes the files, compiles, weakens no check) goes to the
# gate. Then REVIEW_CHAIN critics of different models review it one after another, each with its own lens; the
# first rejection ends the chain (the owner's cap is 4 rounds). A missing further model shortens the tournament or
# the chain, never fails the pass.
TOURNAMENT_SIZE = 3
TOURNAMENT_NOTE = ('\nAnother model already tried this task in this pass and its answer could not be used: %s. Do not '
                   'repeat that mistake: copy every SEARCH line exactly from the code shown above.\n')
# <id>: a candidate that fails the test gate for real (not the environment, not an unknown neighbour) does not end the
# pass while the tournament has room: the next model sees the failing output and the diff of the previous one.
TOURNAMENT_GATE_NOTE = ('\nAnother model already tried this task in this pass; its change was applied and the tests '
                        'failed. Do not repeat that mistake.\nFailing test output:\n%s\n')
TOURNAMENT_DIFF_NOTE = '\nIts diff (do not repeat it):\n%s\n'
TOURNAMENT_OUTPUT_LIMIT = 1500


class _GateRetry:
    """A real test failure of one candidate: the arguments of the ONE rejection that settles the pass if no other
    model can try, the failing output for the next prompt and the names of the files the candidate changed."""
    def __init__(self, reject_args: tuple, diag: str, changed):
        self.reject_args, self.diag, self.changed = reject_args, diag, list(changed)


REVIEW_CHAIN = 2
REVIEW_LENSES = (
    '',
    'You are the SECOND critic: an earlier critic approved this candidate. Look only for what it may have missed: '
    'an expected result of the task\'s own examples that the change or the test does not pin exactly (a check that '
    'only says a value changed accepts any wrong change), a case the task names that is not handled, a change the '
    'task did not ask for. Approve when none of these is there.',
    'You are the THIRD critic: two critics approved. Check that nothing the task asks for is missing and that the '
    'change cannot break the code around it (callers, error paths, other inputs of the same function).',
    'You are the LAST critic: three critics approved. Reject only a concrete defect you can name with its line.')


def review_candidate(task: Task, workdir: Path, model: str, invoke, *,
                     baseline: dict[str, bytes] | None = None,
                     scratch: Path | None = None, lens: str = '', prior: tuple = ()) -> tuple[bool, list[str]]:
    """A separate call sees an immutable copy and returns ``(approved, reasons)``.

    Its opinion never grants DONE. A failed call or an unreadable answer raises ReviewFault
    (the reviewer's fault is not the candidate's strike)."""
    reviewer = replace(task, touch_files=(),
                       read_files=tuple(sorted(set(task.touch_files + task.read_files))))
    with tempfile.TemporaryDirectory(prefix='factory-review-', dir=scratch, ignore_cleanup_errors=True) as directory:
        review_root = Path(directory) / 'input'
        snapshot = prepare(workdir, reviewer, review_root)
        files_for_hint = [n for n in snapshot if n != POLICY_FILE]
        light = engine_for('review', reviewer) == 'light'   # no tools: no read/grep words (critic 19.11 18:5x)
        checks = (REVIEW_CHECKS_TEST if task.kind == 'unit_test' else REVIEW_CHECKS) + (' ' + lens if lens else '')
        # <id> (owner): the next critic sees the remarks of all earlier critics of this candidate
        earlier = ('Earlier critics of this same candidate said:\n' +
                   ''.join('- ' + redact(str(p))[:600] + '\n' for p in prior) +
                   'Find what they missed or got wrong; do not repeat their remarks.\n') if prior else ''
        head = ('Review this patch task: ' + redact(task.title) + '.\n' + checks +
                (' The task files are below: small files whole, a large file as its outline and the parts that '
                 'matter. Judge the candidate by its diff and the code shown; never reject it only because some '
                 'code is not shown.\n' if light else
                 ' Read only the explicitly supplied files (relative paths in your working directory: '
                 + ', '.join(sorted(files_for_hint)) + '); grep inside it is allowed, nothing outside it.\n') +
                earlier + 'Return exactly JSON {"approved":true|false,"reasons":["each concrete defect"]}.\n')
        files = {n: v for n, v in snapshot.items() if n != POLICY_FILE}
        full_diff = unified_diff(baseline, workdir, task.touch_files, REVIEW_DIFF_LIMIT) if baseline is not None else ''
        priority = frozenset(keywords_from(task.title, strict=False)
                             | identifier_tokens(getattr(task, 'goal', '') or ''))
        words = priority | keywords_from(full_diff)
        big = {n for n, v in files.items() if n in (set(task.touch_files) | set(task.read_files))
               and n not in task.tests and len(v) > LARGE_FILE_CHARS}
        targets = visible_targets(task)
        review_budget = (channels.PROMPT_LIMIT_CHARS - len(head) - 250 -
                         (REVIEW_DIFF_LIMIT if baseline is not None else 0))
        body = render(files, targets, large=big, keywords=words, budget_chars=review_budget,
                      small_tokens=max(task.context_budget, review_budget),
                      priority=priority, hint=LIGHT_REVIEW_HINT if light else REVIEW_HINT, tools=not light)
        room = channels.PROMPT_LIMIT_CHARS - len(head) - len(body) - 250  # the diff takes only what is left
        diff = ''
        if baseline is not None and room > 300:
            diff = unified_diff(baseline, workdir, task.touch_files, min(REVIEW_DIFF_LIMIT, room))
        prompt = head + ('Candidate diff:\n' + diff + '\n' if diff else '') + body
        rc, stdout, _ = invoke(reviewer, review_root, model, prompt_override=prompt)
        if rc != 0 or inspect_changes(reviewer, review_root, snapshot):
            raise ReviewFault('reviewer call failed rc=%s' % rc)
        summary = event_summary(stdout)
        if summary['provider_error'] or summary['finish_reason'] in ('length', 'max_tokens'):
            raise ReviewFault('reviewer provider error or truncated answer')
        text = summary['text'].strip()
        try:   # the first JSON object of the answer: free models wrap it in prose or a ```json fence
            answer, _ = json.JSONDecoder().raw_decode(text[text.index('{'):])
        except ValueError as error:
            raise ReviewFault('reviewer answer is not JSON') from error
        if not isinstance(answer, dict) or type(answer.get('approved')) is not bool:
            raise ReviewFault('reviewer answer has no verdict')
        reasons = answer.get('reasons', answer.get('reason', []))
        if isinstance(reasons, str):
            reasons = [reasons]
        reasons = [str(r)[:400] for r in reasons if str(r).strip()] if isinstance(reasons, list) else []
        if answer['approved']:
            return True, reasons          # an approving critic keeps its remarks: the next critic sees them
        return False, reasons or ['rejected without a stated reason']


def build_coder_prompt(task: Task, visible: dict[str, bytes], feedback: str | None = None,
                       prev_diff: str = '', *, goal: str | None = None, failing: str = '',
                       light: bool = False) -> str:
    """The ONE builder of the coder prompt (used by the pass and by model_attempt's default). ``light``: the
    prompt of the light engine, which has no tools: no read/grep instructions (live 19.11 17:48-17:50:
    with them the model answered "CANNOT: requires access outside the provided files")."""
    targets = visible_targets(task)
    if task.kind == 'unit_test':
        # its own test file is the one file it writes: never "read-only" or "do not modify tests" (critic 19.11)
        core = ("Write ONLY the test of task " + task.id + ": " + redact(task.title) +
                ". Create or change only the test file: " + ", ".join(task.touch_files) +
                ". The code it tests is read-only. Do not execute deployment, read parent folders, "
                "or use network tools other than the configured model.\n" + UNIT_TEST_RULES)
    else:
        core = ("Implement ONLY task " + task.id + ": " + redact(task.title) +
                ". Change only: " + ", ".join(task.touch_files) +
                ". Read-only tests: " + ", ".join(task.tests) +
                ". Do not modify tests, execute deployment, read parent folders, "
                "or use network tools other than the configured model.")
    if light:
        core += ("\nThe task files are below: small files whole, a large file as its outline and the parts "
                 "that matter for the task.")
    else:
        core += ("\nAll task files are in your working directory under these relative paths: " +
                 ", ".join(sorted(set(task.touch_files) | set(task.read_files) | set(task.tests))) +
                 ". Read a file with the read tool by its exact relative path (use offset/limit for a line "
                 "range); find a function by name with grep inside this directory; never look for files "
                 "outside the working directory.")
    goal = getattr(task, 'goal', '') if goal is None else goal
    if goal:
        core += "\nTask text:\n" + redact(scrub_paths(goal))[:1500]
    if failing and task.kind != 'unit_test':
        core += "\nFailing on the base now (must pass after your change):\n" + redact(failing)[:1500]
    if task.kind == 'unit_test':
        core += (" Write the test so that it FAILS on the current code because of the described "
                 "defect and would pass once the defect is fixed.")
        if task.backlog_id:
            core += " The FIRST line of the test file must be exactly: # factory-backlog-id: " + task.backlog_id
    if feedback:
        core += "\nThe previous candidate was rejected. Feedback:\n" + redact(feedback)
    tests_text = ' '.join(visible[n].decode('utf-8', 'replace') for n in task.tests if n in visible)
    priority = frozenset(keywords_from(task.title, strict=False) | identifier_tokens(feedback or '')
                         | identifier_tokens(goal or ''))
    words = priority | keywords_from(tests_text, prev_diff, feedback)
    budget = channels.PROMPT_LIMIT_CHARS - REVIEW_OVERHEAD - len(core) - (2500 if prev_diff else 0) - 60
    core += '\n' + render(visible, targets, large=large_names(task, visible), keywords=words,
                          budget_chars=budget, small_tokens=max(task.context_budget, budget), priority=priority,
                          **({'hint': LIGHT_HINT, 'tools': False} if light else {}))
    room = channels.PROMPT_LIMIT_CHARS - len(core) - 200
    if prev_diff and room > 300:
        core += "\nDiff of the rejected candidate (do not repeat its mistake):\n" + prev_diff[:room]
    return core


def _default_prompt(task: Task, workdir: Path, light: bool = False) -> str:
    """The coder prompt of a direct call without a prepared prompt (both engines build it the same way)."""
    visible = {name: safe_source(workdir / name) for name in
               sorted(set(task.touch_files + task.read_files + task.tests))
               if (workdir / name).exists()}
    return build_coder_prompt(task, visible, light=light)


def model_attempt(task: Task, workdir: Path, model: str, timeout: int,
                  *, prompt_override: str | None = None, steps: int | None = None,
                  key_env: str = 'GOOGLE_GENERATIVE_AI_API_KEY') -> tuple[int, bytes, bytes]:
    """Invoke Kilo with a frozen project policy and a temporary clean profile.

    The explicitly selected Google auth key is the only provider credential
    forwarded. No secret is placed in argv, model prompt or kilo.jsonc.
    The prompt travels in argv (Kilo takes the message as an argument; its stdin mode is not
    documented, so it is not assumed): the 28 000-character limit keeps it far below the OS limit.
    """
    if task.only_opus:
        return 125, b'', b'opus-only-task'
    prompt = prompt_override if prompt_override is not None else _default_prompt(task, workdir)
    if len(prompt) > channels.PROMPT_LIMIT_CHARS:
        return 125, b'', b'context-too-large'
    try:
        command = kilo_argv()
    except FileNotFoundError:
        # Preserve direct callers' executable lookup. CLI preflights availability.
        command = ['kilo']
    except (ValueError, OSError):
        return 125, b'', b'invalid-kilo-entrypoint'
    # Kilo puts its working directory into the system prompt of EVERY call: nothing under %TEMP%/the profile
    with tempfile.TemporaryDirectory(prefix="factory-kilo-home-", dir=workdir.parent, ignore_cleanup_errors=True) as home:
        base = Path(home)
        dirs = {name: base / name for name in
                ("config", "cache", "data", "appdata", "localappdata", "npm-cache")}
        for dest in dirs.values():
            dest.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k.upper() in ENV_ALLOW}
        env.update(HOME=home, USERPROFILE=home,
                   XDG_CONFIG_HOME=str(dirs["config"]),
                   XDG_CACHE_HOME=str(dirs["cache"]),
                   XDG_DATA_HOME=str(dirs["data"]),
                   APPDATA=str(dirs["appdata"]),
                   LOCALAPPDATA=str(dirs["localappdata"]),
                   NPM_CONFIG_CACHE=str(dirs["npm-cache"]),
                   TEMP=home, TMP=home, PYTHONUTF8="1",
                   PYTHONIOENCODING="utf-8")
        provider = model.split('/')[0]
        auth_env = 'OPENROUTER_API_KEY' if provider == 'openrouter' else 'GOOGLE_GENERATIVE_AI_API_KEY'
        credential = os.environ.get(key_env, '')
        if credential:
            env[auth_env] = credential
        # Kilo deliberately ignores {env:VAR} in untrusted project configs.
        # Supply the reference in a trusted PROCESS-OWNED config, while the
        # project kilo.jsonc remains the immutable deny-first permissions file.
        env["KILO_CONFIG_CONTENT"] = json.dumps(kilo_config(provider, auth_env, steps))
        args = [*command, "run", "--pure", "--auto", '--agent', 'factory',
                "--format", "json", "--model", model, prompt]
        try:
            if os.environ.get('FACTORY_KILO_ENTRY') or shutil.which('kilo'):
                p = run_owned(args, cwd=workdir, env=env, timeout=timeout)
            else:
                p = subprocess.run(args, cwd=workdir, env=env,
                                   capture_output=True, timeout=timeout, shell=False)
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return 124, b"", b"worker-timeout"


# ---- The light engine (owner: small edits and reviews through fast calls, Kilo only for multi-file
# edits). ONE REST request instead of a Kilo agent loop. The coder prompt already carries the files (render():
# small files whole, keyword slices of large ones), so the model answers at once with SEARCH/REPLACE blocks and the
# runner applies them to the approved files only: the triage localises, one edit, the deterministic gate decides
# (the Agentless scheme). The answer comes back as a Kilo-shaped event stream, so event_summary(), classify(),
# reconcile() and the telemetry stay ONE path for both engines. Live evidence 19.11 17:04-17:13: three Kilo runs
# of a one-file task spent all 8 steps reading files that were already in the prompt and made no edit.
LIGHT_MAX_FILES = 2              # a coder task that changes more files is a multi-file edit: Kilo
LIGHT_OVERHEAD_TOKENS = 600      # the rules below and the chat wrapper (Kilo: 5 300-7 300)
LIGHT_TIMEOUT_S = 180
LIGHT_MAX_OUTPUT = 8192
LIGHT_REASONING_TOKENS = 2048
LIGHT_ENDPOINTS = {'google': 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
                   'openrouter': 'https://openrouter.ai/api/v1/chat/completions'}
LIGHT_EDIT_RULES = (
    "You are a precise code editor. This call has NO tools: everything you may use is in the message. Change "
    "only the allowed files. Answer ONLY with edit blocks, no analysis before them. A block is: the file path on "
    "its own line; a line <<<<<<< SEARCH; lines copied EXACTLY from the shown file (enough to be unique, never "
    "line numbers or omission markers); a line =======; the new lines; a line >>>>>>> REPLACE. An empty SEARCH "
    "part creates a new file (or fills an empty one) with the new lines. Several blocks are allowed. If the "
    "code you must change is not shown, answer one line: CANNOT: and the name of the function you need.")
LIGHT_HINT = ("The file is large: only its outline and the parts below are shown. Copy SEARCH lines from the "
              "shown parts; if the code to change is not shown, answer CANNOT: and the function name.")
LIGHT_REVIEW_RULES = ("You review a code patch. This call has NO tools: everything you may use is in the message. "
                      "Answer with the JSON verdict only.")
_LIGHT_NAME = re.compile(r'[\w./\\-]+\.[A-Za-z0-9]+')
# Gemma 4 on the OpenAI-compatible endpoint puts its reasoning before the answer (<thought>...</thought>, live 19.11);
# other free models use <think>. A draft edit inside it must never be applied, and the verdict JSON follows it.
# Only a LEADING block: the same tags inside a REPLACE (code that strips them) are the edit itself (critic 19.11).
_LIGHT_THOUGHT = re.compile(r'^\s*<(thought|think)>.*?(?:</\1>|\Z)\s*', re.S | re.I)


def light_rules(task: Task) -> str:
    """The coder's system text with the task's real file paths (live 19.11: a placeholder path in the format
    example was copied literally and became 'a block for a file outside the task')."""
    first = task.touch_files[0]
    return (LIGHT_EDIT_RULES + "\nAllowed files: " + ", ".join(task.touch_files) + ".\nThe shape of a block:\n"
            + first + "\n<<<<<<< SEARCH\n(old lines)\n=======\n(new lines)\n>>>>>>> REPLACE")


def engine_for(role: str, task: Task) -> str:
    """'light' for every review and for a coder task of at most LIGHT_MAX_FILES files, else 'kilo'."""
    return 'light' if role == 'review' or len(task.touch_files) <= LIGHT_MAX_FILES else 'kilo'


def _light_target(line: str, allowed: tuple) -> str | None:
    """The allowed file a file-name line names; '' for a file outside the task; None when it is no file name."""
    name = line.strip().strip('`*#:').strip().replace(chr(92), '/')
    while name.startswith('./'):
        name = name[2:]
    if not _LIGHT_NAME.fullmatch(name):
        return None
    if name in allowed:
        return name
    hits = [a for a in allowed if a.endswith('/' + name) or name.endswith('/' + a)]
    return hits[0] if len(hits) == 1 else ''


def parse_edit_blocks(text: str, allowed: tuple) -> tuple[list, int]:
    """``([(file, search, replace)], blocks for a file outside the task)``. The file of a block is the last
    file-name line before it; a block without one belongs to the only allowed file. An unterminated block is
    never applied."""
    lines = text.replace('\r\n', '\n').split('\n')
    blocks, outside, current, i = [], 0, None, 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith('<<<<<<<') and 'SEARCH' in s:
            # the separator and the end are whole lines: a longer ===== underline inside SEARCH is text
            j = i + 1
            while j < len(lines) and lines[j].strip() != '=======':
                j += 1
            k = j + 1
            while k < len(lines) and lines[k].strip() != '>>>>>>> REPLACE':
                k += 1
            if k >= len(lines):
                break
            name = current if current is not None else (allowed[0] if len(allowed) == 1 else '')
            if name:
                blocks.append((name, '\n'.join(lines[i + 1:j]), '\n'.join(lines[j + 1:k])))
            else:
                outside += 1
            i = k + 1
            continue
        if s and not s.startswith('```'):
            hit = _light_target(s, allowed)
            if hit is not None:
                current = hit
        i += 1
    return blocks, outside


def _line_hits(text: str, search: str) -> list[int]:
    """Starts of the exact occurrences of ``search`` that begin and end on line boundaries (a SEARCH that is the
    head of a longer line, '    return x' in '    return x_list', is no occurrence: critic 19.11)."""
    hits, start = [], 0
    while True:
        i = text.find(search, start)
        if i < 0:
            return hits
        end = i + len(search)
        if (i == 0 or text[i - 1] == '\n') and (end == len(text) or text[end] == '\n' or search.endswith('\n')):
            hits.append(i)
        start = i + 1


def _replace_once(text: str, search: str, replace: str) -> str | None:
    """``text`` with the ONE occurrence of ``search`` replaced; trailing spaces of lines are ignored when the
    exact text is absent. None when it is absent or ambiguous."""
    hits = _line_hits(text, search)
    if len(hits) == 1:
        return text[:hits[0]] + replace + text[hits[0] + len(search):]
    if len(hits) > 1:
        return None
    lines = text.split('\n')
    want = [line.rstrip() for line in search.split('\n')]
    while want and not want[-1]:
        want.pop()
    while want and not want[0]:
        want.pop(0)
    if not want:
        return None
    n = len(want)
    hits = [i for i in range(len(lines) - n + 1) if [line.rstrip() for line in lines[i:i + n]] == want]
    if len(hits) == 1:
        return '\n'.join(lines[:hits[0]] + replace.split('\n') + lines[hits[0] + n:])
    if hits:
        return None
    shifted = _replace_shifted(lines, want, replace)
    if shifted is not None:
        return shifted
    from .factory_patterns import repair     # ERROR_PATTERNS: a view line or a reflowed line, one place only
    return repair(text, search, replace)


def _replace_shifted(lines: list, want: list, replace: str) -> str | None:
    """aider's leading-whitespace rule (fac-light-indent, live 19.11: 11 of 32 coder answers missed their SEARCH):
    the SEARCH lines equal ONE place of the file but for one and the same prefix of spaces and tabs, and the REPLACE
    lines get that prefix. A prefix with anything but spaces/tabs is no shift ('return x' is never the tail of
    'foo_return x': coordinator's acceptance). None when there is no such place or more than one."""
    rep = [line.rstrip() for line in replace.split('\n')]
    lead = [len(x) - len(x.lstrip(' \t')) for x in want + rep if x.strip()]
    cut = min(lead) if lead else 0
    want = [x[cut:] if x.strip() else '' for x in want]
    rep = [x[cut:] if x.strip() else '' for x in rep]

    def prefix_at(i):
        found = None
        for k, wanted in enumerate(want):
            have = lines[i + k].rstrip()
            if not wanted:
                if have.strip():
                    return None
                continue
            if not have.endswith(wanted):
                return None
            prefix = have[:len(have) - len(wanted)]
            if prefix.strip(' \t') or (found is not None and prefix != found):
                return None
            found = prefix
        return found

    places = [(i, p) for i in range(len(lines) - len(want) + 1) for p in [prefix_at(i)] if p is not None]
    if len(places) != 1:
        return None
    i, prefix = places[0]
    return '\n'.join(lines[:i] + [prefix + x if x else '' for x in rep] + lines[i + len(want):])


def apply_edit_blocks(workdir: Path, blocks) -> tuple[list[str], dict]:
    """Apply the blocks inside ``workdir`` (the file names come from the task, never from the model):
    ``(changed files, {failure: count})``. All or nothing: when one block fails no file is written (half a
    candidate could pass weak tests; the failure note goes to the next attempt). A CRLF file stays CRLF."""
    failed, texts, crlf = {}, {}, {}

    def fail(why):
        failed[why] = failed.get(why, 0) + 1

    for name, search, replace_text in blocks:
        if name not in texts:
            path = Path(workdir).joinpath(*name.split('/'))
            try:
                raw = path.read_bytes().decode('utf-8') if path.is_file() else ''
            except (OSError, UnicodeDecodeError):
                fail('unreadable file')
                continue
            crlf[name] = '\r\n' in raw
            texts[name] = raw.replace('\r\n', '\n')
        text = texts[name]
        if not search.strip():
            if text.strip():
                fail('empty SEARCH on a file that is not empty')
                continue
            new = replace_text if replace_text.endswith('\n') else replace_text + '\n'
        else:
            new = _replace_once(text, search, replace_text)
            if new is None:
                fail('SEARCH not found exactly once')
                continue
        texts[name] = new
    payload = {}
    for name, text in texts.items():
        try:      # a lone surrogate from a JSON escape cannot be written: the model's answer, not a crash
            payload[name] = (text.replace('\n', '\r\n') if crlf[name] else text).encode('utf-8')
        except UnicodeError:
            fail('text that cannot be written as UTF-8')
    if failed:
        return [], failed
    applied = []
    for name, data in payload.items():
        path = Path(workdir).joinpath(*name.split('/'))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError:
            fail('unwritable file')
            continue
        applied.append(name)
    return applied, failed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is an error, never followed: urllib would resend the Authorization header to the new host (critic
    19.11), so the key could reach a third party."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_LIGHT_OPENER = urllib.request.build_opener(_NoRedirect)


def _light_post(url: str, key: str, body: dict, timeout: float) -> tuple[int | None, bytes]:
    """(HTTP status or None, body). The key travels only in the Authorization header, never in a log."""
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    try:
        with _LIGHT_OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        try:
            return error.code, error.read()
        except (OSError, http.client.HTTPException):
            return error.code, b''
    except (OSError, ValueError, http.client.HTTPException) as error:   # URLError, timeouts, resets
        return None, type(error).__name__.encode()


def _light_error(status: int | None, raw: bytes, name: str = 'APIError') -> bytes:
    """A Kilo-shaped error event: classify() reads the status and the provider body (quota ids, retryDelay).
    Gemini's OpenAI-compatible endpoint wraps the error object into a one-element list. ``name``:
    'NetworkError' (no HTTP answer at all) and 'UnreadableAnswer' (HTTP 200 that is no chat completion) have
    classes of their own (critic 19.11: both were 'transient' for ever, never the brake)."""
    text = (raw or b'')[:4000].decode('utf-8', 'replace')
    try:
        body = json.loads(text)
        if isinstance(body, list) and len(body) == 1 and isinstance(body[0], dict):
            text = json.dumps(body[0])
    except ValueError:
        pass
    data = {'message': text[:300]}
    if status is not None:
        data.update(statusCode=status, responseBody=text)
    return (json.dumps({'type': 'error', 'error': {'name': name, 'data': data}}) + '\n').encode('utf-8')


def _missing_blocks_note(workdir: Path, blocks) -> str:
    parts = []
    for i, (name, search, replace_text) in enumerate(blocks, 1):
        if not search.strip():
            continue
        try:
            path = Path(workdir).joinpath(*name.split('/'))
            raw = path.read_bytes().decode('utf-8') if path.is_file() else ''
            text = raw.replace('\r\n', '\n')
        except (OSError, UnicodeDecodeError):
            continue
        if _replace_once(text, search, replace_text) is not None:
            continue
        where = 'in the file more than once' if len(_line_hits(text, search)) > 1 else 'not in the file'
        have = {x.strip() for x in text.split('\n')}
        wanted = [x.strip() for x in search.split('\n') if x.strip()]
        first = next((x for x in wanted if x not in have), wanted[0] if wanted else '')[:80]
        parts.append("block %d (%s) SEARCH is %s: '%s'" % (i, name, where, first))
        if len(parts) >= 2:
            break
    return ''.join('; ' + p for p in parts)


def _light_note(total: int, applied: list, failed: dict, outside: int, text: str) -> str:
    """One line for the next attempt's feedback: what happened to the edit blocks (no file text)."""
    if not total:
        answer = text.strip()
        if answer[:7].upper() == 'CANNOT:':
            return 'the model answered CANNOT: ' + redact(answer[7:].strip())[:150]   # reject() scrubs paths
        return 'the answer had no SEARCH/REPLACE edit block'
    parts = ['edit blocks %d, changed files %d' % (total, len(applied))]
    if outside:
        parts.append('%d block(s) for a file outside the task' % outside)
    parts.extend('%d: %s' % (n, why) for why, n in sorted(failed.items()))
    return '; '.join(parts)


LIGHT_ANSWERS_KEPT = 200

def _keep_answer(workdir: Path, text: str) -> None:
    try:
        folder = Path(workdir).parent / 'answers'
        folder.mkdir(exist_ok=True)
        (folder / (Path(workdir).name + '.txt')).write_text(text[:20000], encoding='utf-8')
        files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
        for old in files[:max(0, len(files) - LIGHT_ANSWERS_KEPT)]:
            old.unlink()
    except OSError:
        pass


def light_attempt(task: Task, workdir: Path, model: str, timeout: int = LIGHT_TIMEOUT_S,
                  *, prompt_override: str | None = None, steps: int | None = None,
                  key_env: str | None = None, post=None) -> tuple[int, bytes, bytes]:
    """The light engine with model_attempt's contract: ``(rc, Kilo-shaped events, note)``. A task without
    touch_files (the reviewer's copy) only answers; a coder task gets its edit blocks applied in ``workdir``.
    ``post`` replaces the HTTP call (tests never reach the network)."""
    if task.only_opus:
        return 125, b'', b'opus-only-task'
    provider, _, model_id = model.partition('/')
    url = LIGHT_ENDPOINTS.get(provider)
    if url is None or not model_id:
        return 125, b'', b'light: unsupported provider'
    if not MODEL_ID.fullmatch(model):      # 0 rubles: an OpenRouter model without ':free' never leaves the machine
        return 125, b'', b'light: model id refused (a paid or malformed model)'
    prompt = prompt_override if prompt_override is not None else _default_prompt(task, workdir, light=True)
    if len(prompt) > channels.PROMPT_LIMIT_CHARS:
        return 125, b'', b'context-too-large'
    key = os.environ.get(key_env or ('OPENROUTER_API_KEY' if provider == 'openrouter' else 'GOOGLE_GENERATIVE_AI_API_KEY'), '')
    if not key:
        return 1, _light_error(401, b'{"error": {"message": "no API key in the environment"}}'), b''
    review = not task.touch_files
    body = {'model': model_id, 'max_tokens': LIGHT_MAX_OUTPUT, 'temperature': 0 if review else 0.2,
            'messages': [{'role': 'system', 'content': LIGHT_REVIEW_RULES if review else light_rules(task)},
                         {'role': 'user', 'content': prompt}]}
    if provider == 'openrouter':
        body['reasoning'] = {'max_tokens': LIGHT_REASONING_TOKENS}
    status, raw = (post or _light_post)(url, key, body, max(10, min(int(timeout), LIGHT_TIMEOUT_S)))
    if status is None and raw == b'TimeoutError':
        # the request reached the provider, the answer did not come in time: Kilo's timeout contract (the idle
        # series, then the ceiling: reviewer_failed / worker_timeout), never an endless 'transient' (critic 19.11)
        return 124, b'', b'worker-timeout'
    if status is None:          # no connection at all (DNS, the proxy is down): the request never reached a provider
        return 1, _light_error(None, raw, 'NetworkError'), b''
    if status != 200:
        return 1, _light_error(status, raw), b''
    try:
        data = json.loads(raw.decode('utf-8'))
        error = data.get('error') if isinstance(data, dict) and 'choices' not in data else None
        if isinstance(error, dict) and type(error.get('code')) is int:
            # OpenRouter: an error during generation comes with HTTP 200 and an error object (its own code)
            return 1, _light_error(error['code'], raw), b''
        choice = data['choices'][0]
        content = choice['message'].get('content') or ''
        if isinstance(content, list):   # some OpenAI-compatible providers answer with text parts
            content = ''.join(str(p.get('text', '')) for p in content if isinstance(p, dict))
        text = _LIGHT_THOUGHT.sub('', str(content)).strip()
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return 1, _light_error(None, b'unreadable answer', 'UnreadableAnswer'), b''
    usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
    given = usage.get('prompt_tokens_details') if isinstance(usage.get('prompt_tokens_details'), dict) else {}
    made = usage.get('completion_tokens_details') if isinstance(usage.get('completion_tokens_details'), dict) else {}
    cached = given.get('cached_tokens') if type(given.get('cached_tokens')) is int else None
    tokens = {}
    if type(usage.get('prompt_tokens')) is int:
        tokens['input'] = max(0, usage['prompt_tokens'] - (cached or 0))   # prompt_tokens include the cached part
    # completion_tokens already include the reasoning (OpenAI usage schema); the Kilo shape keeps them apart, so the
    # reasoning is counted once (live 19.11 19:44: Nemotron booked 5 515 + 8 192 + 8 192 for 13 707 real tokens)
    reasoning = made.get('reasoning_tokens') if type(made.get('reasoning_tokens')) is int else None
    if type(usage.get('completion_tokens')) is int:
        tokens['output'] = max(0, usage['completion_tokens'] - (reasoning or 0))
    if reasoning is not None:
        tokens['reasoning'] = reasoning
    if cached is not None:
        tokens['cache'] = {'read': cached, 'write': 0}
    events, note = [], ''
    if not review:
        blocks, outside = parse_edit_blocks(text, tuple(task.touch_files))
        applied, failed = apply_edit_blocks(Path(workdir), blocks)
        events.extend({'type': 'tool_use', 'part': {'tool': 'edit', 'state': {'input': {'filePath': n}}}}
                      for n in applied)
        note = _light_note(len(blocks) + outside, applied, failed, outside, text)
        if failed.get('SEARCH not found exactly once'):
            note += _missing_blocks_note(Path(workdir), blocks)
            from .factory_patterns import hints as pattern_hints
            note += ''.join('; ' + h for h in pattern_hints(blocks))
        if not applied:
            _keep_answer(Path(workdir), text)
    events.append({'type': 'text', 'part': {'text': text}})
    events.append({'type': 'step_finish', 'part': {'reason': choice.get('finish_reason') or 'stop', 'tokens': tokens}})
    return 0, ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events).encode('utf-8'), note.encode('utf-8')


def _digest(*parts) -> str:
    return sha256('|'.join(str(p) for p in parts).encode('utf-8', 'replace')).hexdigest()


def _counts(result) -> dict | None:
    if result is None:
        return None
    return dict(collected=result.collected, passed=result.passed,
                failed=result.failed + result.errors, skipped=result.skipped)


def once(*, root: Path, plan: Path, checkpoint: Path, staging: Path,
         small_model: str, large_model: str, execute: bool = False,
         acknowledge: bool = False, review_model: str | None = None,
         channel_config: Path | None = None, max_attempts: int = 2,
         max_model_calls: int | None = None, base_sha: str | None = None) -> dict:
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
    owner = lock / LOCK_OWNER
    with contextlib.suppress(OSError):   # the holder's pid: the loop clears the lock of a dead holder at once
        owner.write_text(str(os.getpid()), encoding='ascii')
    try:
        state = load_state(checkpoint, tasks)
        if max_model_calls is not None:
            # Explicit operator budget for this checkpoint, never an implicit raise.
            state["max_model_calls"] = max_model_calls
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
        if not shutil.which("kilo") and not os.environ.get('FACTORY_KILO_ENTRY'):
            raise InvalidPlan("kilo command unavailable")
        configured = []
        if channel_config is not None:
            configured = json.loads(channel_config.read_text(encoding='utf-8'))['channels']
            channels.validate(configured)
            if not configured or any(c.get('verified') is not True for c in configured):
                raise InvalidPlan('channels require actual verified model/tool availability')
        if not configured and not os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY"):
            raise InvalidPlan("Google API auth key must be set in the caller environment")
        if not review_model:
            raise InvalidPlan("review_model is required: no candidate may skip the independent review")
        if staging_reveals_profile(staging):
            raise InvalidPlan(PROFILE_LEAK_MESSAGE)
        try:
            staging.mkdir(parents=True, exist_ok=True)
            swept_failed = sweep_scratch(staging)
        except OSError as error:   # antivirus, a locked folder: the machine, not the task (nothing was acquired yet)
            return {'status': 'READY', 'reason': 'os_error', 'task_id': tid, 'task': tid,
                    'backlog_id': task.backlog_id, 'base_sha': base_sha, 'calls': [], 'stages': {},
                    'events': [], 'tests': None, 'infra': True, 'wait_s': 60.0,
                    'error_type': type(error).__name__,
                    'reason_detail': scrub_paths(redact(str(error))[:200], [root, staging]),
                    'deploy_blocked': state['deploy_blocked']}
        return _pass(tasks, task, state, checkpoint=checkpoint, root=root, staging=staging,
                     small_model=small_model, large_model=large_model, review_model=review_model,
                     configured=configured, max_attempts=max_attempts, swept_failed=swept_failed,
                     base_sha=base_sha or os.environ.get('FACTORY_BASE_SHA'),
                     ledger=(channel_config.resolve().parent / 'quota') if channel_config is not None else None)
    finally:
        with contextlib.suppress(OSError):    # a lock left behind is cleared by the loop; the pass result stands
            owner.unlink(missing_ok=True)
            lock.rmdir()


def _pass(tasks, task: Task, state: dict, **kwargs) -> dict:
    with scratch_redirect(kwargs['staging']):
        return _pass_inner(tasks, task, state, **kwargs)


def _pass_inner(tasks, task: Task, state: dict, *, checkpoint: Path, root: Path, staging: Path,
          small_model: str, large_model: str, review_model: str, configured: list,
          max_attempts: int, base_sha: str | None, swept_failed=(), ledger: Path | None = None) -> dict:
    tid = task.id
    staging.mkdir(parents=True, exist_ok=True)
    try:
        token = acquire(tasks, state, tid, charge=False)  # calls are charged when they are made
    except BudgetExhausted:
        return {'status': 'WAITING_CHANNEL', 'reason': 'budget_exhausted', 'task_id': tid, 'task': tid,
                'backlog_id': task.backlog_id, 'base_sha': base_sha, 'calls': [], 'stages': {}, 'events': [],
                'tests': None, 'infra': False, 'wait_s': round(seconds_to_local_midnight(), 1),
                'deploy_blocked': state['deploy_blocked']}
    save_atomic(checkpoint, state)
    prefix = "task-" + tid + "-" + token[:8]
    row = state['tasks'][tid]
    attempt = row['attempts']
    calls: list[dict] = []
    stages: dict[str, float] = {}
    events: list[str] = ['sweep_failed'] if swept_failed else []
    ctx = {'workdir': staging / prefix, 'baseline': {}, 'coder_model': None, 'counts': None, 'role': 'code',
           'read_chars': 0, 'last_tokens': 0, 'last_text': '', 'roots': [root, staging]}
    scrub = lambda text: scrub_paths(text, ctx['roots'] + [ctx['workdir']])  # noqa: <id>
    report = {'task_id': tid, 'task': tid, 'backlog_id': task.backlog_id, 'base_sha': base_sha,
              'attempt': attempt, 'kind': task.kind, 'calls': calls, 'stages': stages,
              'events': events, 'reason': None, 'tests': None, 'wait_s': 0.0, 'infra': False,
              'deploy_blocked': state['deploy_blocked']}
    started_pass = time.monotonic()
    prev_diff_file = staging / 'prev-diff' / (tid + '.diff')

    def finish(status: str, **extra) -> dict:
        report.update(extra)
        if status not in ('READY', 'WAITING_CHANNEL'):      # settled, blocked or quarantined: every series is over
            table = factory_env(state)
            for key in ('task:%s:code' % tid, 'task:%s:review' % tid):
                table['idle'].pop(key, None)
            table['shortages'].pop(tid, None)
            table['other'].pop(tid, None)
        report['status'] = status
        report['tests'] = _counts(ctx['counts'])
        report['dur_s'] = round(time.monotonic() - started_pass, 3)
        save_atomic(checkpoint, state)
        return report

    def timed(name: str, fn):
        t0 = time.monotonic()
        try:
            return fn()
        finally:
            stages[name] = round(stages.get(name, 0.0) + time.monotonic() - t0, 3)

    def release(reason: str, seconds: float, infra: bool | None = None) -> dict:
        """No strike, attempt not spent: back to READY, postponed. ``infra`` only for real faults."""
        status = defer(state, tid, token, reason, seconds)
        return finish(status, reason=reason, wait_s=round(float(seconds), 1),
                      infra=(reason in INFRA_DEFERS) if infra is None else infra,
                      deploy_blocked=state['deploy_blocked'])

    def block(reason: str, detail: str = '', *, infra: bool = False, keep: bool = False) -> dict:
        """BLOCKED without a strike (also drops a stale pending review: agent_factory.quarantine)."""
        detail = scrub(redact(detail))[:400]
        old = row.get('pending_review')
        if not keep and isinstance(old, dict) and isinstance(old.get('workdir'), str) and inside_staging(old['workdir'], staging):
            shutil.rmtree(old['workdir'], ignore_errors=True)   # the candidate is void with the block
        quarantine(state, tid, token, reason=reason)
        if detail:
            add_feedback(state, tid, 'gate', '[infra] ' + reason + ': ' + detail)
        return finish('BLOCKED', reason=reason, reason_detail=detail, infra=infra,
                      blocked_reason=row.get('blocked_reason'))

    def release_or_block(reason: str, seconds: float) -> dict:
        """The same postponement three times in a row is not a wait any more: BLOCKED for Opus."""
        if reason in ESCALATE and defer_streak(state, tid, reason) + 1 >= ESCALATE_AFTER:
            return block(reason, 'postponed %d times in a row' % ESCALATE_AFTER, infra=reason in INFRA_DEFERS)
        return release(reason, seconds)

    def reject(source: str, reason: str, text: str, names=()) -> dict:
        """A candidate failed a gate or the reviewer: feedback + previous diff + a strike."""
        reason = scrub(redact(reason))[:300]
        text = scrub(text)
        add_feedback(state, tid, source, '[attempt %d] %s' % (attempt, text))
        # NOTE: the previous diff below is deliberately NOT scrubbed: it is the user's own code under
        # relative a/ b/ names, and rewriting it would corrupt the diff the model must not repeat.
        if source == 'review' or reason in ('gate:no_changes', 'gate:steps_exhausted'):
            # the model's own final text: the REVIEWER's text on a review rejection, the CODER's on no_changes
            report['model_note'] = redact(ctx['last_text'])[:300]   # never raw tool arguments or the prompt
        if names:
            prev_diff_file.parent.mkdir(parents=True, exist_ok=True)
            prev_diff_file.write_text(unified_diff(ctx['baseline'], ctx['workdir'], names, DIFF_LIMIT),
                                      encoding='utf-8')
        else:
            prev_diff_file.unlink(missing_ok=True)  # never hand the next attempt another cycle's diff
        status = settle(state, tid, token, tests_ok=False, evidence=_digest(reason, text),
                        max_attempts=max_attempts)
        row.pop('pending_review', None)
        return finish(status, reason=reason, reason_detail=redact(text)[:400])

    def call(role: str, call_task: Task, directory_for, preferred: str, prompt: str,
             *, exclude_model: str | None = None) -> tuple[int, bytes, bytes]:
        """One real model call with reservation, charging, classification, one transient retry."""
        ctx['role'] = role
        if len(prompt) > channels.PROMPT_LIMIT_CHARS:
            raise PromptTooLarge(str(len(prompt)))
        light = ctx['light'] = engine_for(role, call_task) == 'light'    # one request, the files travel in the prompt
        base_tokens = channels.estimate_tokens(len(prompt), 0 if light else ctx['read_chars'],
                                               overhead=LIGHT_OVERHEAD_TOKENS if light else None)
        steps = 1 if light else (REVIEW_STEPS if role == 'review' else PROVIDER_STEPS)
        booked = 1 if light else requests_for(steps)   # the whole run: what choose() checks and reserve() books; reconcile() writes the fact
        for retry in (0, 1):
            selected, at, chosen, kwargs = None, None, preferred, {}
            if configured:
                route = 'review' if role == 'review' else 'code'
                order = channels.route_order(configured, route, attempt, base_tokens, preferred=preferred,
                                             exclude_model=exclude_model)
                if not order and route == 'code':     # no escalation/main channel at all: any channel is better than none
                    order = channels.route_order(configured, route, 1, 0, preferred=preferred,
                                                 exclude_model=exclude_model)   # never a model the tournament tried
                if not order:
                    raise NoIndependentReviewer()
                quota = state.setdefault('channel_quotas', {})
                seen = (quota_ledger.view(quota, quota_ledger.others(ledger, str(checkpoint)))
                        if ledger is not None else quota)    # <id>: the other states' bookings of the same keys
                live = channels.usable(order, seen, os.environ) or order   # a dead or keyless channel sets no ceiling
                tokens = min(base_tokens, max(c['tpm'] for c in live))  # a huge file may not make every channel "too small"
                if tokens < base_tokens and 'reservation_capped' not in events:
                    events.append('reservation_capped')
                selected = channels.choose(order, seen, tokens, os.environ,
                                           requests=booked)   # a multi-step call needs room
                charge_call(state, tid)   # BEFORE booking: an exhausted budget must leave no reservation behind
                at = channels.reserve(quota, selected, tokens, requests=booked)   # exactly what choose() checked
                if ledger is not None:
                    quota_ledger.publish(ledger, str(checkpoint), quota)
                chosen, kwargs['key_env'] = selected['model'], selected['key_env']
            elif chosen in channels.excluded_models(exclude_model):
                raise NoIndependentReviewer()
            else:
                tokens = base_tokens
                charge_call(state, tid)
            ctx['last_tokens'] = tokens
            save_atomic(checkpoint, state)
            directory = directory_for(retry)
            began = time.monotonic()
            engine = light_attempt if light else model_attempt
            code, stdout, stderr = engine(call_task, directory, chosen, timeout=240,
                                          prompt_override=prompt, steps=steps, **kwargs)
            ctx['light_note'] = stderr.decode('utf-8', 'replace')[:300] if light and code == 0 else ''
            elapsed = round(time.monotonic() - began, 3)
            summary = event_summary(stdout, directory)
            idle = code == 124 and summary['steps'] == 0 and summary['tool_events'] == 0
            counters = factory_env(state)['idle']
            task_key = 'task:%s:%s' % (tid, 'review' if role == 'review' else 'code')
            keys = (task_key, 'channel:' + str(selected['id'] if selected else chosen))
            prior = counters.get(task_key) if type(counters.get(task_key)) is int else 0    # only the TASK's own series blocks it
            ceiling = idle and prior >= IDLE_SUSPECTS_ALLOWED      # a broken launch must trip the brake, not cool forever
            info = channels.classify(stdout, stderr, code, idle=idle and not ceiling)
            if ceiling:
                info['ceiling'] = True
                if selected is not None:       # the NEXT task on this channel must not meet the same wall at once
                    channels.cool(state['channel_quotas'], selected, seconds=channels.RATE_SUSPECT_COOL_S)
                counters.pop(keys[1], None)
            if idle and not ceiling:
                for k in keys:
                    counters[k] = (counters.get(k) if type(counters.get(k)) is int else 0) + 1
            elif summary['steps'] > 0 or summary['tool_events'] > 0 or info['kind'] == 'ok':
                for k in keys:
                    counters.pop(k, None)               # real work was seen: the series is over
            if info.get('suspect') and 'rate_limited_suspect' not in events:
                events.append('rate_limited_suspect')
            kinds = ('input_tokens', 'cache_read_tokens', 'cache_write_tokens')
            actual_input = (sum(summary[k] or 0 for k in kinds) if any(summary[k] is not None for k in kinds)
                            else None)       # None = Kilo reported no usage: unknown, never 0
            actual = (None if actual_input is None and summary['output_tokens'] is None
                      else (actual_input or 0) + (summary['output_tokens'] or 0) + (summary['reasoning_tokens'] or 0))
            if selected is not None:
                # no usage reported: the fact is unknown, so the token booking stays whole
                charged = actual_input if actual_input is not None else tokens
                # Kilo retries inside a failed call and the retries spend quota the stream never shows: after a
                # failure, or when nothing was reported, the booking stays whole; only a clean call is trued up
                unknown = summary['steps'] == 0 and actual_input is None
                failed = code != 0 or info['kind'] != 'ok' or summary['provider_error']
                fact = max(booked, summary['steps']) if (failed or unknown) else max(1, summary['steps'])
                if info['kind'] == 'network':
                    fact = 0         # no HTTP answer: the request never reached the provider's quota
                channels.reconcile(state['channel_quotas'], selected, at, tokens, charged,
                                   requests=booked, actual_requests=fact)
            calls.append({'role': role, 'attempt': attempt, 'channel': selected['id'] if selected else None,
                          'model': chosen, 'reserved_tokens': tokens, 'actual_tokens': actual,
                          'actual_input_tokens': actual_input,
                          'input_tokens': summary['input_tokens'], 'output_tokens': summary['output_tokens'],
                          'reasoning_tokens': summary['reasoning_tokens'],
                          'cache_read_tokens': summary['cache_read_tokens'],
                          'cache_write_tokens': summary['cache_write_tokens'],
                          'candidate': ctx.get('candidate', 0) if role != 'review' else None,
                          'dur_s': elapsed, 'error_class': None if info['kind'] == 'ok' else info['kind'],
                          'http_status': info.get('status'), 'returncode': code,
                          'tool_events': summary['tool_events'], 'steps': summary['steps'],
                          'last_step_tools': summary['last_step_tools'],
                          'finish_reason': summary['finish_reason'], 'files_read': summary['files_read'],
                          'provider_error': info['kind'] not in ('ok', 'unknown') or summary['provider_error']})
            ctx['last_text'] = summary['text']
            if ledger is not None and selected is not None:
                quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
            save_atomic(checkpoint, state)
            kind = info['kind']
            if kind == 'ok' or (kind == 'unknown' and code == 0):
                return code, stdout, stderr
            if kind in ('timeout', 'launcher'):
                raise ChannelFault(info)
            if selected is not None:
                done = channels.apply_failure(state['channel_quotas'], selected, info, env=os.environ)
                if ledger is not None:
                    quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
            else:
                done = {'cool_s': info.get('retry_after_s') or 0}
            if kind in ('transient', 'network') and retry == 0:
                time.sleep(channels.TRANSIENT_RETRY_S)
                continue
            raise ChannelFault(info, done.get('cool_s') or 0)
        raise ChannelFault({'kind': 'transient'})  # unreachable guard

    def soonest(default: float) -> float:
        """Wait of the channel that can actually serve the NEXT step (coder, or a reviewer of another model)."""
        if not configured:
            return default
        pool = [c for c in configured if not (ctx['role'] == 'review' and c['model'] == ctx['coder_model'])]
        quota = state.get('channel_quotas', {})
        seen = quota_ledger.view(quota, quota_ledger.others(ledger, str(checkpoint))) if ledger is not None else quota
        wait = channels.next_wait(pool, seen, ctx['last_tokens'], os.environ,
                                  requests=1 if ctx.get('light') else
                                  requests_for(REVIEW_STEPS if ctx['role'] == 'review' else PROVIDER_STEPS))
        return default if wait is None else max(5.0, wait)

    def fault(error: ChannelFault) -> dict:
        kind = error.info['kind']
        report['reason_detail'] = scrub(redact(error.info.get('message', '')))[:300]
        if ctx['role'] == 'review' and kind == 'timeout' and error.info.get('ceiling'):
            return block('reviewer_failed', 'idle reviewer timeout %d times in a row.%s'
                         % (IDLE_SUSPECTS_ALLOWED + 1, park_candidate()), keep=True)
        if ctx['role'] == 'review' and kind in ('timeout', 'launcher'):
            return release_or_block('reviewer_failed', INFRA_DEFER_S)  # the candidate stays pending
        if kind in ('rate_minute', 'rate_day'):
            return release(kind, soonest(error.wait_s or error.info.get('retry_after_s') or channels.DEFAULT_COOL_S))
        if kind == 'region':
            return release(kind, soonest(60))
        if kind in ('key_invalid', 'model_missing'):
            return release(kind, soonest(60))
        if kind == 'too_big':      # the task does not fit the provider budget: the task's problem, not the channel's
            return block('context_too_large', error.info.get('message', ''))
        if kind == 'balance':
            return release('balance', soonest(error.wait_s or channels.BALANCE_COOL_S))
        if kind == 'transient':
            return release('transient', 60)
        if kind == 'network':
            # the machine has no network: every channel fails the same way, so the loop brake decides (a series
            # of these stops the factory instead of spending the daily call budget on passes that cannot work)
            return release('network', 60, infra=True)
        if kind == 'timeout':
            return block('worker_timeout', infra=True)
        if kind == 'launcher':
            return block('unsafe_windows_launcher', error.info.get('message', ''), infra=True)
        return release_or_block('provider_error', INFRA_DEFER_S)

    base_holder = None
    gate_tmp = staging / 'tmp'     # pytest's own temp (--basetemp) stays inside staging, never under the profile
    slot = {'deadline': None}      # armed at the FIRST gate run: the coder call must not eat the wait

    def gate_run(tree, tests):
        """gate.run_tests with the pass-wide slot budget (what is left of it, never a fresh one per call)."""
        if slot['deadline'] is None:
            slot['deadline'] = _now() + SLOT_BUDGET_S
        return gate.run_tests(tree, tests, GATE_TIMEOUT_S, workdir=gate_tmp,
                              wait_s=max(0.0, slot['deadline'] - _now()))

    def park_candidate() -> str:
        """Save the diff of a paid candidate outside every sweep (staging/parked) and name it for Opus."""
        parked = staging / 'parked' / (tid + '.diff')
        parked.parent.mkdir(parents=True, exist_ok=True)
        parked.write_text(unified_diff(ctx['baseline'], ctx['workdir'], list(task.touch_files), 10 * DIFF_LIMIT),
                          encoding='utf-8')
        return ' The candidate diff is kept in parked/%s.diff.' % tid

    def env_release(why_text: str, candidate: bool = True) -> dict:
        """The environment failed, not the candidate: no strike, no feedback to the model, and a block ONLY for a
        persistent reason. The gate may hand the reason over as an ``env:`` verdict: the prefix is not part of it.
        'pytest slot:' (no slot / no RAM) is a passing shortage: release_transient with a long hold after many in a
        row, never a block. Any other reason (a missing package) has its own small ceiling, then parks the task
        for Opus with the candidate saved. (A dedicated defer reason waits for <id>; 'transient' is whitelisted.)"""
        reason = why_text[4:].lstrip() if why_text.startswith('env:') else why_text
        report['reason_detail'] = scrub(redact(reason))[:300]
        events.append('env_shortage')
        table = factory_env(state)
        if not reason.startswith('pytest slot:'):
            seen = (table['other'].get(tid) if type(table['other'].get(tid)) is int else 0) + 1
            table['other'][tid] = seen
            if seen >= ENV_OTHER_CEILING:
                table['other'].pop(tid, None)
                saved = park_candidate() if candidate else ''
                return block('gate_unknown', "ENV: %s (%d passes in a row; not the candidate fault).%s"
                             % (reason, seen, saved), keep=True)
        if candidate:      # (the red_before check runs before any candidate exists; a pending one stays as it is)
            row['pending_review'] = dict(workdir=str(ctx['workdir']), baseline_digest=baseline_digest,
                                         coder_model=ctx['coder_model'])
        report['pending_review'] = bool(row.get('pending_review'))
        count = (table['shortages'].get(tid) if type(table['shortages'].get(tid)) is int else 0) + 1
        if reason.startswith('pytest slot:'):
            table['shortages'][tid] = count
        return release('transient', ENV_HOLD_S if count >= ENV_HOLD_AFTER else INFRA_DEFER_S)

    def base_root() -> Path:
        """Scratch copy of the source tree: the base runs execute untrusted tests, never in the live tree."""
        tree = Path(base_holder) / 'tree'
        if not tree.exists():
            shutil.copytree(root, tree, ignore=COPY_IGNORE)
            ctx['roots'].append(tree)
        return tree

    baseline_dir = None
    owned, live, parsed = set(), set(), True
    for other_tid, other in state['tasks'].items():
        held = other.get('pending_review')
        if held is not None:
            if isinstance(held, dict) and isinstance(held.get('workdir'), str):
                try:
                    owned.add(Path(held['workdir']).resolve())
                except (OSError, ValueError, RuntimeError):
                    parsed = False
            else:
                parsed = False     # a record we cannot read may own a copy: collect nothing this pass
        if other.get('status') == 'RUNNING' and isinstance(other.get('lease'), str):
            live.add('task-%s-%s' % (other_tid, other['lease'][:8]))
    if not parsed:
        events.append('cleanup_skipped_unparsed_pending')
    for stale in (staging.glob('task-*') if parsed else ()):   # copies of passes that no task owns any more
        try:
            if (stale.is_symlink() or not stale.is_dir() or not inside_staging(stale.resolve(), staging)
                    or stale.resolve() in owned
                    or any(stale.name == p or stale.name.startswith(p + '-') for p in live)):
                continue
            # younger than two leases: an expired-lease writer may still be writing into it
            if time.time() - stale.stat().st_mtime > 2 * LEASE_LIFETIME_S:
                shutil.rmtree(stale)
        except FileNotFoundError:
            pass
        except OSError:
            events.append('stale_baseline_kept' if stale.name.endswith('-baseline') else 'pending_copy_kept')
    try:
        base_holder = tempfile.mkdtemp(prefix='factory-base-')   # inside the try: an OSError here is a released pass
        pending = row.get('pending_review')
        if pending is not None and not (isinstance(pending, dict) and isinstance(pending.get('workdir'), str)
                                        and isinstance(pending.get('baseline_digest'), str)):
            row.pop('pending_review', None)  # corrupt record: treat as absent
            events.append('pending_dropped')
            pending = None
        baseline_dir = ctx['workdir'] if not pending else staging / (prefix + '-baseline')
        ctx['baseline'] = prepare(root, task, baseline_dir)
        ctx['read_chars'] = sum(len(v) for n, v in ctx['baseline'].items()
                                if n in (set(task.touch_files) | set(task.read_files)) and len(v) > LARGE_FILE_CHARS)
        baseline_digest = sha256(b''.join(n.encode() + sha256(v).digest()
                                          for n, v in sorted(ctx['baseline'].items()))).hexdigest()
        if pending:
            old = Path(pending['workdir'])
            inside = inside_staging(old, staging)
            if pending.get('baseline_digest') != baseline_digest or not old.is_dir() or not inside:
                # HEAD moved (or the work copy is gone): the old candidate is void. Start fresh, no strike.
                row.pop('pending_review', None)
                events.append('pending_dropped')
                if inside and old.is_dir():
                    shutil.rmtree(old, ignore_errors=True)
                ctx['workdir'] = baseline_dir
                pending = None
            else:
                ctx['workdir'] = old.resolve()
                ctx['coder_model'] = pending.get('coder_model')

        # 1. Base verdict before any model call: green = already done, unknown = infrastructure.
        verdict, base = timed('red_before_s', lambda: gate.red_before(
            base_root() if task.kind != 'unit_test' else root, task.tests, GATE_TIMEOUT_S, task.kind,
            wait_s=(min(RED_BEFORE_WAIT_S, max(0.0, slot['deadline'] - _now())) if slot['deadline'] is not None
                    else RED_BEFORE_WAIT_S),
            workdir=gate_tmp))
        ctx['counts'] = base
        if verdict == 'green':
            return block('already_green', 'the task tests already pass on the base')
        if verdict == 'unknown' and base.env_reason:
            return env_release(base.env_reason, candidate=False)    # the machine, not the task: never a block
        if verdict == 'unknown':
            report['reason_detail'] = scrub(redact(base.diag))[:300]
            return release_or_block('gate_unknown', INFRA_DEFER_S)

        # 3. Deterministic gates (factory_gate only). A decision, not a settlement: a dict ends the pass; a
        # _GateRetry is a real test failure the tournament may answer with another model; (changed, receipt) goes on.
        def run_gates():
            changed = inspect_changes(task, ctx['workdir'], ctx['baseline'])
            if not changed:
                last = calls[-1] if calls else {}
                if last.get('steps', 0) >= PROVIDER_STEPS and not last.get('last_step_tools'):
                    events.append('steps_exhausted')    # the model ran out of steps and answered in text only
                    return reject('gate', 'gate:steps_exhausted',
                                  'the step limit ended the call without an edit (last step had no tool use)', ())
                note = ctx.get('light_note') or ''
                return reject('gate', 'gate:no_changes', 'the model produced no change to the approved files'
                              + (' (' + note + ')' if note else ''), ())
            cand_files = {n: ctx['workdir'].joinpath(*n.split('/')).read_text(encoding='utf-8', errors='replace')
                          for n in changed}
            for name, source in cand_files.items():
                if name.endswith('.py'):
                    try:
                        compile(source, name, 'exec')
                    except (SyntaxError, ValueError) as error:
                        return reject('gate', 'gate: compile error in ' + name,
                                      'does not compile: %s' % error, changed)
            problems = gate.weakening_violations(root, cand_files, task.kind, task.touch_files)
            if problems:
                text = '; '.join(problems)
                return reject('gate', 'weakening: ' + text[:300], 'weakening of the checks: ' + text, changed)
            if task.kind == 'unit_test':
                if task.backlog_id:
                    first = next((n for n in changed if n in task.tests), task.tests[0])   # the first CHANGED test file
                    marker_ok, marker_why = gate.accept_unit_test(MARKER_PROBE, cand_files.get(first, ''), task.backlog_id)
                    if not marker_ok:   # cheaper than running pytest first
                        return reject('gate', 'gate: ' + marker_why[:300], marker_why, changed)
                else:
                    events.append('unit_test_marker_skipped')   # nothing to check against: never an unfixable rejection
            with tempfile.TemporaryDirectory(prefix='factory-gate-tree-', ignore_cleanup_errors=True) as d:
                tree = candidate_tree(root, ctx['workdir'], changed, Path(d))
                ctx['roots'].append(tree)
                # the gate decides whether a missing module is the environment or the candidate's own import (live
                # 19.11 18:06-18:08: written tests imported modules that do not exist and went round as 'environment')
                cand = gate.candidate_import(timed('gate_s', lambda: gate_run(tree, task.tests)), root, tree, changed)
                ctx['counts'] = cand
                if cand.env_reason:
                    return env_release(cand.env_reason)
                factory_env(state)['shortages'].pop(tid, None)   # measured: both environment series are over
                factory_env(state)['other'].pop(tid, None)
                # pytest executes untrusted code: it may not rewrite the frozen tests or inputs.
                for name in sorted((set(task.tests) | set(task.read_files)) - set(changed)):
                    original, after = root.joinpath(*name.split('/')), tree.joinpath(*name.split('/'))
                    if original.is_file() and (not after.is_file() or after.read_bytes() != original.read_bytes()):
                        return reject('gate', 'gate: immutable file changed during pytest',
                                      'pytest changed a frozen file: ' + name, changed)
                if task.kind == 'unit_test':
                    ok, why = gate.accept_unit_test(cand)
                else:
                    ok, why = gate.accept(base, cand, verdict == 'red')
                if not ok and why.startswith('env:'):
                    return env_release(why)
                if not ok:
                    return _GateRetry(('gate', 'gate: ' + why[:300], why + '\n' + cand.diag, changed), cand.diag or why,
                                      changed)
                if task.kind != 'unit_test':
                    try:
                        near = neighbor_tests(root, task)[:MAX_NEIGHBORS]
                    except Exception as error:  # noqa: BLE001 - "graph unavailable" is not "no neighbours"
                        events.append('neighbors_unavailable:' + redact(type(error).__name__))
                        near = []
                    if near:
                        def neighbours():
                            skipped_count = 0
                            last_result = None
                            for name in near:
                                mine = gate_run(tree, [name])
                                last_result = mine
                                if mine.env_reason:
                                    return 'env', mine
                                if not mine.junit_ok and not (mine.failed or mine.errors):
                                    skipped_count += 1
                                    continue
                                if mine.failed + mine.errors > 0:
                                    theirs = gate_run(base_root(), [name])
                                    last_result = theirs
                                    if theirs.env_reason:
                                        return 'env', theirs
                                    if not theirs.junit_ok and not (theirs.failed or theirs.errors):
                                        return 'unknown', mine
                                    if mine.failed_ids or theirs.failed_ids:
                                        fresh = set(mine.failed_ids) - set(theirs.failed_ids)
                                    else:
                                        fresh = {'count'} if mine.failed + mine.errors > theirs.failed + theirs.errors else set()
                                    if fresh:
                                        return 'regression', mine
                            if skipped_count == len(near):
                                return 'skipped', last_result
                            if skipped_count > 0:
                                events.append('neighbors_skipped')
                            return 'ok', last_result
                        outcome, mine = timed('neighbors_s', neighbours)
                        if outcome == 'env':
                            return env_release(mine.env_reason)
                        if outcome == 'skipped':
                            events.append('neighbors_skipped')
                        elif outcome == 'unknown':
                            report['reason_detail'] = 'neighbour tests of the base are not measured'
                            # keep the candidate: the next pass resumes at the gates and measures, no new coder call
                            row['pending_review'] = dict(workdir=str(ctx['workdir']), baseline_digest=baseline_digest,
                                                         coder_model=ctx['coder_model'])
                            report['pending_review'] = True
                            return release_or_block('gate_unknown', INFRA_DEFER_S)
                        elif outcome == 'regression':
                            return _GateRetry(('gate', 'gate:neighbors_regression',
                                               'new red among neighbour tests: ' + ', '.join(near) + '\n' + mine.diag,
                                               changed), mine.diag, changed)
            receipt = _digest(json.dumps(_counts(cand)), ','.join(changed))
            return changed, receipt

        # 2. The coder call(s) (a rejected candidate comes back next pass with feedback and its diff).
        decision = None
        if not pending:
            feedback = fresh_feedback(state, tid)
            feedback = scrub(feedback) if feedback else feedback
            prev_diff = prev_diff_file.read_text(encoding='utf-8') if prev_diff_file.is_file() else ''
            role = 'repair' if (feedback or attempt > 1) else 'code'
            visible = {name: safe_source(ctx['workdir'] / name) for name in
                       sorted(set(task.touch_files + task.read_files + task.tests))
                       if (ctx['workdir'] / name).exists()}
            # the reviewer sees the small files whole plus its instructions and a diff: refuse BEFORE the coder is paid for
            small_total = sum(len(v) for n, v in visible.items() if n not in large_names(task, visible))
            if small_total + REVIEW_DIFF_LIMIT + REVIEW_OVERHEAD > channels.PROMPT_LIMIT_CHARS:
                raise PromptTooLarge('coder+review prompts cannot both fit')
            failing = (', '.join(base.failed_ids) + '\n' + base.diag).strip() if task.kind == 'code' else ''
            prompt = build_coder_prompt(task, visible, feedback, prev_diff, failing=scrub(failing),
                                        light=engine_for(role, task) == 'light')   # the same rule call() applies
            chosen = route(task, small_model=small_model, large_model=large_model, fallback=attempt > 1)

            def dir_for(retry: int) -> Path:
                if retry:  # a failed worker may have written files; never reuse its directory
                    ctx['workdir'] = staging / (prefix + "-retry-" + str(retry))
                    ctx['baseline'] = prepare(root, task, ctx['workdir'])
                return ctx['workdir']

            def unusable() -> str:
                """Step 3's mechanical checks, without a strike: why this candidate cannot go to the gate ('' when it
                can). A candidate that fails them makes room for the tournament's next model."""
                now = inspect_changes(task, ctx['workdir'], ctx['baseline'])
                if not now:
                    return ctx.get('light_note') or 'its answer changed no file'
                texts = {n: ctx['workdir'].joinpath(*n.split('/')).read_text(encoding='utf-8', errors='replace')
                         for n in now}
                for name, source in texts.items():
                    if name.endswith('.py'):
                        try:
                            compile(source, name, 'exec')
                        except (SyntaxError, ValueError) as error:
                            return 'its edit of %s does not compile (%s)' % (name, error)
                if gate.weakening_violations(root, texts, task.kind, task.touch_files):
                    return 'its edit weakened a check'
                if task.kind == 'unit_test' and task.backlog_id:
                    first = next((n for n in now if n in task.tests), task.tests[0])
                    ok, why = gate.accept_unit_test(MARKER_PROBE, texts.get(first, ''), task.backlog_id)
                    return '' if ok else why
                return ''

            def gate_note(failure) -> str:
                """The note for the next coder after a real test failure: the failing output (scrubbed, redacted) and the
                diff of the candidate. Over PROMPT_LIMIT_CHARS the diff goes first, then the output is shortened."""
                output = scrub(redact(failure.diag))[:TOURNAMENT_OUTPUT_LIMIT]
                diff = unified_diff(ctx['baseline'], ctx['workdir'], failure.changed, DIFF_LIMIT)
                room = channels.PROMPT_LIMIT_CHARS - len(prompt)
                for part in (TOURNAMENT_DIFF_NOTE % diff if diff else '', ''):
                    note = TOURNAMENT_GATE_NOTE % output + part
                    if len(note) <= room:
                        return note
                fixed = len(TOURNAMENT_GATE_NOTE % '')
                return TOURNAMENT_GATE_NOTE % output[:max(0, room - fixed)] if room > fixed else ''

            size = TOURNAMENT_SIZE if configured and engine_for(role, task) == 'light' else 1
            tried, k_prompt, held, gate_failed, next_note = [], prompt, None, [], ''
            for k in range(size):
                if k:
                    held = (ctx['workdir'], ctx['baseline'])
                    tried.append(ctx['coder_model'])
                    k_prompt = prompt + next_note
                    if len(k_prompt) > channels.PROMPT_LIMIT_CHARS:
                        k_prompt = prompt
                    ctx['workdir'] = staging / ('%s-cand-%d' % (prefix, k))
                    shutil.rmtree(ctx['workdir'], ignore_errors=True)
                    ctx['baseline'] = prepare(root, task, ctx['workdir'])
                    events.append('tournament_candidate_%d' % (k + 1))
                ctx['candidate'] = k
                try:
                    rc, out, err = timed('code_s', lambda: call(role, task, dir_for, chosen, k_prompt,
                                                                exclude_model=tried or None))
                except (ChannelFault, channels.ChannelUnavailable, NoIndependentReviewer):
                    if not k:
                        raise
                    ctx['workdir'], ctx['baseline'] = held      # no further model now: the last candidate stands
                    events.append('tournament_short')
                    break
                decision = None          # the earlier candidate's failure is history now; this one is judged afresh
                ctx['coder_model'] = calls[-1]['model']
                if event_summary(out)['finish_reason'] in ('length', 'max_tokens'):
                    events.append('output_truncated')
                if k + 1 >= size:
                    break                            # the tournament is full: this candidate stands
                why = unusable()
                if why:                              # mechanically unusable: the next model hears why
                    next_note = TOURNAMENT_NOTE % scrub(redact(why))[:300]
                    continue
                decision = run_gates()               # usable: the deterministic gates decide
                if not isinstance(decision, _GateRetry):
                    break                            # passed, or a final result (environment, unknown neighbour, ...)
                gate_failed.append(ctx['coder_model'])
                events.append('tournament_gate_retry_%d' % (k + 1))
                next_note = gate_note(decision)
            if size > 1:
                report['tournament'] = dict(size=size, candidates=ctx['candidate'] + 1,
                                            models=tried + [ctx['coder_model']])
                if gate_failed:
                    report['tournament']['gate_failed'] = list(gate_failed)
        if decision is None:
            decision = run_gates()                   # the standing candidate (or the kept one of a pending review)
            if isinstance(decision, _GateRetry) and 'tournament' in report:
                report['tournament']['gate_failed'] = report['tournament'].get('gate_failed', []) + [ctx['coder_model']]
        if isinstance(decision, _GateRetry):
            return reject(*decision.reject_args)     # the pass ends on its last gate failure: ONE rejection
        if isinstance(decision, dict):
            return decision
        changed, receipt = decision


        # 4. Independent reviewer: another model, reasons go back as feedback.
        row['pending_review'] = dict(workdir=str(ctx['workdir']), baseline_digest=baseline_digest,
                                     coder_model=ctx['coder_model'])
        save_atomic(checkpoint, state)

        critics = []      # the models that reviewed this candidate: the next critic is none of them, nor the coder

        def invoke(call_task, directory, preferred, **kwargs):
            return call('review', call_task, lambda _retry: directory, preferred,
                        kwargs['prompt_override'], exclude_model=[ctx['coder_model']] + critics)
        try:
            approved, reasons = timed('review_s', lambda: review_candidate(
                task, ctx['workdir'], review_model, invoke, baseline=ctx['baseline'], scratch=staging))
            critics.append(calls[-1]['model'])
            said = ['critic 1 %s: %s' % ('approved' if approved else 'rejected', '; '.join(reasons) or 'no remarks')]
            for n in range(1, min(REVIEW_CHAIN, len(REVIEW_LENSES)) if approved else 0):
                try:     # the sequential chain: another model with its own lens; a missing one shortens it
                    approved, reasons = timed('review_s', lambda: review_candidate(
                        task, ctx['workdir'], review_model, invoke, baseline=ctx['baseline'], scratch=staging,
                        lens=REVIEW_LENSES[n], prior=tuple(said)))
                except (NoIndependentReviewer, channels.ChannelUnavailable, ReviewFault, ChannelFault):
                    events.append('review_chain_short')
                    approved = True          # the earlier critics approved; no further model now
                    break
                critics.append(calls[-1]['model'])
                events.append('review_chain_%d' % (n + 1))
                said.append('critic %d %s: %s' % (n + 1, 'approved' if approved else 'rejected',
                                                  '; '.join(reasons) or 'no remarks'))
                if not approved:
                    break
            report['critics'] = list(critics)
            report['critiques'] = list(said)
        except NoIndependentReviewer:
            report['pending_review'] = True
            return _wait(release_or_block, report, 'no_independent_reviewer', status='WAITING_CHANNEL')
        except channels.ChannelUnavailable as error:
            report['pending_review'] = True
            return _wait(release, report, 'channel_wait', error.wait_s, status='WAITING_CHANNEL',
                         channel_reason=error.reason)
        except ReviewFault as error:
            report['pending_review'] = True
            report['reason_detail'] = scrub(redact(str(error)))[:300]
            return release_or_block('reviewer_failed', INFRA_DEFER_S)
        if not approved:
            return reject('review', 'review: ' + '; '.join(reasons), '; '.join(reasons), changed)
        reviewed = staging / "for-review" / tid
        if reviewed.exists():
            shutil.rmtree(reviewed)  # left over from an earlier candidate of this task
        reviewed.mkdir(parents=True)
        for name in changed:
            dst = reviewed.joinpath(*name.split("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ctx['workdir'].joinpath(*name.split("/")), dst)
        status = settle(state, tid, token, tests_ok=True, evidence=receipt, max_attempts=max_attempts)
        row.pop('pending_review', None)
        prev_diff_file.unlink(missing_ok=True)
        return finish(status, changed=len(changed), receipt_sha256=receipt, cross_review=True)
    except ChannelFault as error:
        return fault(error)
    except BudgetExhausted:
        report['pending_review'] = bool(row.get('pending_review'))
        return release('budget_exhausted', seconds_to_local_midnight())
    except channels.ChannelUnavailable as error:
        report['pending_review'] = bool(row.get('pending_review'))
        return _wait(release, report, 'channel_wait', error.wait_s, status='WAITING_CHANNEL',
                     channel_reason=error.reason)
    except NoIndependentReviewer:
        report['pending_review'] = bool(row.get('pending_review'))
        return _wait(release_or_block, report, 'no_independent_reviewer', status='WAITING_CHANNEL')
    except PromptTooLarge as error:
        return block('context_too_large', 'prompt of %s characters exceeds %d' %
                     (error, channels.PROMPT_LIMIT_CHARS))
    except Exception as error_obj:  # noqa: BLE001 - fail closed, never retry an uncertain worker
        text = scrub(redact(str(error_obj)))[:300]
        if isinstance(error_obj, InvalidPlan) and 'budget' in text:  # prepare()/packet(): context over budget
            return block('context_too_large', text)
        if isinstance(error_obj, OSError):   # antivirus, a locked file, a full disk: the machine, not the task
            report['error_type'] = type(error_obj).__name__
            note = scrub(redact(str(error_obj)))[:200]
            report['reason_detail'] = note
            kind = 'os_error'   # whitelisted in agent_factory.DEFER_REASONS (seam test guards it)
            if defer_streak(state, tid, kind) + 1 >= ESCALATE_AFTER:
                # the same OS error on every pass is this task's problem (path clash, long path): block it,
                # and do not count it toward the brake of the whole factory
                return block('worker_exception', note, infra=False)
            return release(kind, 60, infra=True)
        reason = "scope_violation" if isinstance(error_obj, InvalidPlan) else "worker_exception"
        report['error_type'] = type(error_obj).__name__
        return block(reason, text)
    finally:
        if base_holder:
            shutil.rmtree(base_holder, ignore_errors=True)
        if baseline_dir is not None and baseline_dir.name.endswith('-baseline') and ctx['workdir'] != baseline_dir:
            shutil.rmtree(baseline_dir, ignore_errors=True)


def _wait(release, report: dict, reason: str, seconds: float = 60, *, status: str | None = None,
          channel_reason: str | None = None) -> dict:
    """Candidate kept (pending_review), no strike: the pass ends waiting for a channel/reviewer."""
    result = release(reason, max(1.0, seconds or 60))
    if status and result.get('status') != 'BLOCKED':
        result['status'] = status
    if channel_reason:
        result['channel_reason'] = channel_reason
        if channel_reason in INFRA_CHANNEL_REASONS:
            result['infra'] = True  # a dead key / no key / no channels must trip the loop brake
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Fail-closed experimental Kilo task runner")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--staging", type=Path, required=True)
    p.add_argument("--small-model", required=True)
    p.add_argument("--large-model", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument('--channels', type=Path, help='verified provider IDs, key environment names and actual quotas')
    p.add_argument('--review-model', help='independent reviewer (another model than the coder); defaults to large-model')
    p.add_argument('--base-sha', help='SHA of the integration branch the base was taken from (telemetry only)')
    p.add_argument("--ack-host-access-risk", action="store_true")
    p.add_argument("--max-tasks", type=int, default=1,
                   help="execute at most N sequential tasks; no implicit daemon")
    p.add_argument("--max-attempts", type=int, default=2,
                   help="strikes: a task becomes FAILED after N failed attempts")
    p.add_argument("--max-model-calls", type=int,
                   help="explicit model-call budget written into this checkpoint")
    args = p.parse_args(argv)
    if not 1 <= args.max_tasks <= 10:
        p.error("--max-tasks must be in 1..10")
    if not 1 <= args.max_attempts <= 5:
        p.error("--max-attempts must be in 1..5")
    if args.max_model_calls is not None and not 1 <= args.max_model_calls <= 2000:
        p.error("--max-model-calls must be in 1..2000")
    if args.execute and args.staging.resolve().is_relative_to(args.root.resolve()):
        p.error("staging must not be within original repository")
    outcomes = []
    for _ in range(args.max_tasks if args.execute else 1):
        options = {}
        if args.execute:
            options.update(review_model=args.review_model or args.large_model,
                           channel_config=args.channels, base_sha=args.base_sha)
        result = once(root=args.root, plan=args.plan, checkpoint=args.checkpoint,
                      staging=args.staging, small_model=args.small_model,
                      large_model=args.large_model, execute=args.execute,
                      acknowledge=args.ack_host_access_risk,
                      max_attempts=args.max_attempts,
                      max_model_calls=args.max_model_calls, **options)
        outcomes.append(result)
        if result["status"] not in ("REVIEW", "READY"):
            break
    for result in outcomes:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if all(x["status"] in ("DRY_RUN", "REVIEW", "IDLE")
                    for x in outcomes) else 2


if __name__ == "__main__":
    sys.exit(main())
