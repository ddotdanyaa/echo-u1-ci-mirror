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
import ast
import concurrent.futures
import contextlib
import difflib
from hashlib import sha256
import http.client
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
try:
    import tomllib
except ImportError:      # Python < 3.11: a .toml answer is then only read as text
    tomllib = type('tomllib', (), {'loads': staticmethod(lambda text: None)})
import logging
import concurrent.futures
import urllib.error
import urllib.request
import dataclasses
from dataclasses import replace

from .agent_factory import (BudgetExhausted, DEFER_REASONS, LEASE_LIFETIME_S, MAX_ATTEMPTS, MODEL_ID, InputTooLarge,
                            InvalidPlan, Lease, LockBusy, StaleLease, Task, add_feedback, begin, charge_call, claim,
                            defer, defer_streak, fail_not_code, fail_row, failed_models_of, is_base_debt, is_unsafe_reject, seconds_to_local_midnight,
                            read_plan, ready, redact, REPEAT_MARK, route, quarantine, safe_path, safe_source, settle,
                            snapshot, startable, txn, unclaim)
from .agent_factory import TRACE_DIR, load_trace as agent_factory_load_trace, put_trace, save_atomic
from .factory_context import (LARGE_FILE_CHARS, asked_names, failing_names, identifier_tokens, keywords_from, packet,
                              render, scrub_paths)
from .factory_process import kilo_argv, run_owned
from . import affected_tests
from . import factory_channels as channels
from . import factory_gate as gate
from . import factory_cards as K
from . import factory_tree
from . import factory_quota as quota_ledger
from . import factory_paid_critic as paid_critic
from . import factory_ensemble as ENS
from . import factory_calls as FC
from . import factory_review_wait as RW
from . import factory_head
from . import factory_router
_log = logging.getLogger(__name__)
ENV_ALLOW = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "LANG")
POLICY_FILE = "kilo.jsonc"
PROVIDER_STEPS = 8   # coder: outline -> read by lines -> grep -> edit needs room (3 was too few)
REVIEW_STEPS = 4     # the reviewer only reads and answers
TRANSIENT_HOPS = 4   # an overloaded (503) model: up to this many other models at once in the same call, no wait


ENV_HOLD_AFTER = 10          # consecutive environment shortages before the long hold (the candidate is kept)
ENV_HOLD_S = 1800
ENV_OTHER_CEILING = 3         # a persistent non-slot environment failure (a missing package...) is parked after this many
SCAN_SAME_CAUSE_STRIKE = 2   # the second scan_excluded refusal with the same cause text is a red attempt with the cause as evidence
SCAN_REASK_CEILING = 3      # a card whose test the scanner keeps out of the cloud run is asked again this many times (no strike), then it is a red attempt
RED_BEFORE_WAIT_S = 120     # the base run before the coder call waits for a slot at most this long (its own ceiling)
SLOT_BUDGET_S = 300         # ONE wait for a pytest slot / free RAM per runner pass, shared by every gate run
IDLE_SUSPECTS_ALLOWED = 4   # 21.11 (was 2) idle timeouts treated as a rate limit; the next one is a worker fault (infra)


def factory_env(state: dict) -> dict:
    """The runner's own counters (idle timeouts, environment shortages): a state key of their own, because a
    name inside channel_quotas would be read as a quota group."""
    table = state.get('factory_env')
    if not isinstance(table, dict):
        table = state['factory_env'] = {}
    for name in ('idle', 'shortages', 'other', 'cloud_down', 'scan_excluded'):
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


def _kilo_fits(order: list, steps: int, events: list) -> list:
    """The channels a Kilo run of ``steps`` steps can use: Kilo sends its steps back to back, so a channel whose
    rpm is below them answers 429 inside the run and Kilo sleeps there until the idle ceiling (live 20.11 12:25-12:44:
    three 3.6 Flash calls at rpm 5, 180 s each, no step, a strong-model request of the day spent). Such channels go
    out of the order; when none is left the order stays whole (a slow channel is better than no channel)."""
    fit = [c for c in order if not (type(c.get('rpm')) is int and c['rpm'] < steps)]
    if fit and len(fit) < len(order) and 'low_rpm_skipped' not in events:
        events.append('low_rpm_skipped')
    return fit or order


def requests_for(steps: int) -> int:
    """Provider requests of one multi-step call: every step plus the final answer after the tool limit."""
    return steps + 1

GATE_TIMEOUT_S = 30                   # owner rule: pytest never longer than 30 s
MAX_NEIGHBORS = 6
INFRA_DEFER_S = 300
REVIEWER_WAIT_S = 30    # W-review 1: a standing candidate whose reviewers are all busy longer than this skips the gates
DIFF_LIMIT = 3000
REVIEW_DIFF_LIMIT = 6000
# infra=True (counts toward the loop brake) ONLY for a dead channel or no result from the process;
# a slow test, a prose answer, a 429 or a blocked task is the task's or the model's business
INFRA_DEFERS = frozenset(("key_invalid", "balance", "model_missing"))  # real infrastructure faults


ESCALATE = frozenset(("gate_unknown", "provider_error", "no_independent_reviewer", "reviewer_failed",
                      "review_chain_short"))
ESCALATE_AFTER = 3          # the same postponement this many times in a row becomes BLOCKED
DRY_REVIEW_TRIES = 6        # W-dry 2: attempts of one review call while the edit channels are dry ...
DRY_REVIEW_PAUSE_S = 10     # ... after 10, 20, 30 ... s
DRY_REVIEW_RETRY_KINDS = frozenset(('transient', 'rate_minute', 'rate_day', 'network', 'timeout'))
INFRA_CHANNEL_REASONS = frozenset(("dead", "no_key", "no_channels", "reservation_exceeds_tpm"))
HEAD_ETA_MAX_S = 1800.0     # W-bucket: the longest card wait taken from the head's ETA (a channel shut for the day: the lease's life)
REVIEW_HINT = ("The file is large: read the places you need with the read tool by line numbers from the "
               "outline. Do not edit anything: you only judge the diff.")
LIGHT_REVIEW_HINT = "The file is large: only its outline and the parts below are shown. You only judge the diff."
# The test author's most frequent defects, from the reviewers' rejections of the live series 19.11 17:53-18:38
# (a MagicMock as the code under test, assert False, a name-exists tautology, counts of the repository)
MARKER_SENTENCE = ("the marker line # factory-backlog-id: <ID> goes only into the REPLACE part (its first "
                   "line), never into SEARCH.")
UNIT_TEST_RULES = ("The test must import the real functions or classes from the code files shown and call them, "
                   "then assert on what they return or do. Never test a MagicMock in place of that code, never "
                   "write assert False, a test that only checks that a name exists, or a hard-coded count of "
                   "files or markers in the repository. The project has no pytest-asyncio plugin: never write "
                   "async def test functions or @pytest.mark.asyncio; drive async code with asyncio.run(...) inside "
                   "a plain def test function. A test file that does not exist yet is created with an EMPTY SEARCH "
                   "part; " + MARKER_SENTENCE + "\n" + gate.UNIT_TEST_RULES)   # one source: the gate's own rules


def unit_rules() -> str:
    """UNIT_TEST_RULES; the second instance's rules do not mention the marker line (it asks for none)."""
    if not gate.SELF_REPO:
        return UNIT_TEST_RULES
    return UNIT_TEST_RULES.replace('part; ' + MARKER_SENTENCE, 'part.')


MARKER_PROBE = gate.GateResult(1, 1, 0, 1, 0, 0, True, '')   # a red result: only the marker can fail it
REVIEW_NOTE_LIMIT = 400     # <id>: what the task's earlier candidates were rejected for, shown to its critics
REVIEW_OVERHEAD = 1500 + REVIEW_NOTE_LIMIT      # reviewer instructions + verdict format on top of the files
VIEW_ROOM = 3000            # the least room planned for one file shown as outline + parts (render's floor is lower)
# what the files of one prompt may take: the reviewer's room besides its diff and instructions, less the coder's text
FIT_ROOM = channels.PROMPT_LIMIT_CHARS - REVIEW_DIFF_LIMIT - REVIEW_OVERHEAD - 3000
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".env*", "SECRETS_LOCAL",
                                     "*.pem", "*.key")


class ChannelFault(Exception):
    """The channel or provider failed; the candidate is not to blame (no strike)."""

    def __init__(self, info: dict, wait_s: float = 0.0):
        super().__init__(info.get('kind', 'unknown'))
        self.info, self.wait_s = info, wait_s


_FIXTURE_PRIVATE = re.compile(r'FileNotFoundError[^\n]*fixtures[/\\]+harvest|no key and no call text')


def fixture_private(base) -> bool:
    """W-vgs3 4: the red base test fails on harvested call recordings (tests/fixtures/harvest, kept out of the mirror for privacy)
    or on «no key and no call text»: no code of the mirror can make it green."""
    return bool(_FIXTURE_PRIVATE.search(str(getattr(base, 'diag', '') or '')))


class NoIndependentReviewer(Exception):
    """Only the coder's own model is available: the review waits (never a self-review)."""


class PromptTooLarge(Exception):
    """Prompt over the limit: not sent, no strike, the triage splits the task."""


class ReviewFault(Exception):
    """Reviewer call failed or answered with something that is not a verdict."""


class RubricInvalid(ReviewFault):
    """The critic answered without a required field of the rubric or cited a line the test does not have: an invalid
    vote, not a rejection of the candidate. The panel asks the next model of the chain instead."""


class UnfoundedVote(ReviewFault):
    """VARIANTS_1426 step 4 (b): the critic cites a line that is in none of the texts it was shown (the test, the diff,
    the files): its voice is mechanically not counted and another critic is asked."""


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


PROMOTED_KEEP_S = 7 * 86400.0       # stage/promoted/<tid> packages are kept this long
SCRATCH_KEEP_S = 7200.0             # the folders of failed passes are kept 2 hours (they were 24), then swept


def sweep_scratch(staging, max_age: float = SCRATCH_KEEP_S) -> list:
    """Orphans of killed passes (Kilo homes, review copies, tmp/*) older than ``max_age`` (2 hours), and the promoted
    packages (stage/promoted/<tid>) older than a week, strictly inside staging.
    Returns the names it could not remove (a held file): the caller records them. Junctions are never followed."""
    staging = Path(staging)
    failed: list = []
    isjunction = getattr(os.path, 'isjunction', lambda _p: False)
    found = list(staging.glob('factory-kilo-home-*')) + list(staging.glob('factory-review-*'))
    found += list((staging / 'tmp').glob('*')) if (staging / 'tmp').is_dir() else []
    ages = {item: max_age for item in found}
    if (staging / 'promoted').is_dir():       # the packages of promoted tasks (stage/promoted/<tid>) only pile up: a week is enough
        ages.update({item: PROMOTED_KEEP_S for item in (staging / 'promoted').glob('*')})
    for item, keep in ages.items():
        try:
            if (item.is_symlink() or isjunction(item) or not inside_staging(item.resolve(), staging)
                    or time.time() - item.stat().st_mtime <= keep):
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


def pinned_targets(task: Task) -> dict:
    """file -> definition names the coordinator named in context_targets (a name selector, 'Class.method' gives the
    method), writable files included: the coder prompt shows each of them whole before anything else."""
    out: dict = {}
    for name, sel in task.context_targets:
        leaf = str(sel).rpartition('.')[2]
        if leaf.isidentifier():
            out.setdefault(name, set()).add(leaf)
    return {n: frozenset(v) for n, v in out.items()}


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
                                               and str(item.get('text', '')).startswith(('[infra] ', REPEAT_MARK)))]
        keep = set(plain[-1:])
    # <id>: the loop's lines about the last failure (its repeat line, its class with the remedy and past cases) are
    # untagged and written after it; they reach the coder until a newer attempt is recorded
    anchor = max(keep, default=last_opus)
    keep |= {i for i, item in tail if i > anchor and item.get('source') == 'gate'
             and str(item.get('text', '')).startswith(REPEAT_MARK)}
    out = []
    for i, item in enumerate(items):
        text, source = str(item.get('text', '')), item.get('source')
        if source == 'opus':                      # every Opus note is an instruction, whatever its age
            out.append('[opus] ' + text)
        elif i in keep:
            m = ATTEMPT_TAG.match(text)
            out.append('[%s] %s' % (source, text[m.end():] if m else text))
    return '\n'.join(out) or None


def rejected_for(state: dict, tid: str) -> str:
    """What the task's earlier candidates were rejected for, as its coder was told (fresh_feedback) without the
    requeue notes and the loop's repeat markers; the newest REVIEW_NOTE_LIMIT characters. <id> (skeptic 20.11): a redo
    of a rejected test kept the very lines the rejection named and two critics approved it, they never saw it."""
    lines = [ln for ln in (fresh_feedback(state, tid) or '').split('\n')
             if ln.strip() and not ln.startswith(('[opus] Retry on factory version', '[gate] ' + REPEAT_MARK))]
    return redact('\n'.join(lines))[-REVIEW_NOTE_LIMIT:]


def large_names(task: Task, files: dict[str, bytes]) -> set[str]:
    """The files of the task shown as outline + parts, not whole: each over LARGE_FILE_CHARS, tests too, then the
    largest of the rest until the whole ones and VIEW_ROOM per view fit FIT_ROOM. The ONE rule of the coder prompt,
    the reviewer prompt, prepare(), the pass's size check and the read budget (live 20.11 04:29: four tasks were
    refused before any model call, every time, because their tests were always shown whole: one test file was
    50 KB, another task had five test files of 68 KB together)."""
    scope = set(task.touch_files) | set(task.read_files) | set(task.tests)
    sized = sorted(((len(v), n) for n, v in files.items() if n in scope), reverse=True)
    big = {n for size, n in sized if size > LARGE_FILE_CHARS}
    rest = [(size, n) for size, n in sized if n not in big]
    whole = sum(size for size, _ in rest)
    while rest and whole + VIEW_ROOM * len(big) > FIT_ROOM:
        size, name = rest.pop(0)
        big.add(name)
        whole -= size
    return big


BASE_CACHE_S = 6 * 3600     # a measured red base is reused this long for the same commit, tests and files


def _base_key(base_sha, task: Task, baseline: dict) -> str | None:
    """The identity of a base measurement: the base commit, the kind, the task's tests and the bytes of every staged
    file (the worker policy aside); None without a base commit (an unpinned tree is never reused)."""
    if not base_sha:
        return None
    h = sha256(('%s\n%s\n%s' % (base_sha, task.kind, '\n'.join(sorted(task.tests)))).encode('utf-8'))
    for name, data in sorted(baseline.items()):
        if name != POLICY_FILE:
            h.update(name.encode('utf-8') + b'\0' + sha256(data).digest())
    return h.hexdigest()


def votes_of_diff(pend, diff_hash):
    """W-base 3: the critics' voices kept on a pending review count only for the very diff they judged (its hash);
    another diff (the merge changed the card's files) drops them."""
    if isinstance(pend, dict) and diff_hash and pend.get('votes_diff') == diff_hash:
        return pend.get('votes')
    return None


SHARED_BASE_DIR = 'shared_base'      # W-a3: the red bases of ALL executors live here, one file per core (atomic), beside traces/
SHARED_BASE_MAX = 256


def _base_core(root, task: Task, baseline: dict) -> str:
    """The identity of a base measurement WITHOUT the commit: the tree, the kind, the tests, the trace prefixes of the run
    (path_trace) and the bytes of the tests' own files. The commit is checked apart (same, or moved over files the red
    base does not depend on). The bytes of the card's other staged files are NOT part of it: on one commit they are the
    commit's and the measure runs only the tests (live 26.11: cards with the same tests and other touch files measured
    the same red base again, 3 x ~3 min in 3 h)."""
    h = sha256(('%s\n%s\n%s\n%s' % (Path(root).resolve(), task.kind, '\n'.join(sorted(task.tests)),
                                   '\n'.join(path_trace(task)))).encode('utf-8'))
    own = {str(t).split('::', 1)[0] for t in task.tests}
    for name, data in sorted(baseline.items()):
        if name != POLICY_FILE and name in own:
            h.update(name.encode('utf-8') + b'\0' + sha256(data).digest())
    return h.hexdigest()


def _base_deps(task: Task, result) -> set:
    """The files a red base depends on: the tests' files, the task's files and the files of the failing tests' path."""
    deps = {str(t).split('::', 1)[0] for t in task.tests} | set(task.touch_files) | set(task.read_files)
    for entry in getattr(result, 'path', ()) or ():
        try:
            name = str(entry[0]).replace('\\', '/')
        except (IndexError, TypeError):
            continue
        deps.add(name)
        if not name.endswith('.py'):
            deps.add(name.replace('.', '/') + '.py')
    return deps


def _changed_between(root, old: str, new: str):
    """The files that differ between two commits of the repo at ``root``, or None (a commit unknown here, git fails)."""
    try:
        done = subprocess.run(['git', '-C', str(root), 'diff', '--name-only', old, new], capture_output=True,
                              text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return {line.strip() for line in done.stdout.splitlines() if line.strip()}


def _carry_ok(root, old_sha, new_sha, carry, deps) -> bool:
    """ONE carry rule of a red base (disk store and card row): the same commit, or a moved commit whose move did not
    touch a file the base depends on (it needs the failing tests' trace, else only the same commit counts)."""
    if old_sha == new_sha:
        return True
    if not carry or not old_sha or not new_sha:
        return False
    changed = _changed_between(root, old_sha, new_sha)
    return changed is not None and not (changed & set(deps or ()))


def _gate_result(fields: dict):
    """A GateResult from its stored fields (lists back to tuples); TypeError/ValueError/AttributeError when damaged."""
    fields = {k: tuple(v) if isinstance(v, list) else v for k, v in fields.items()}
    if 'path' in fields:
        fields['path'] = tuple(tuple(p) for p in fields['path'])
    return gate.GateResult(**fields)


def _shared_base_file(state_dir, core: str) -> Path:
    return Path(state_dir) / SHARED_BASE_DIR / (core + '.json')


def _shared_base_get(core: str, base_sha: str | None, root, state_dir=None):
    """A red base measured earlier by ANY executor (this card or another with the same tests and file bytes), read from
    the state dir: on the same commit as it is; on a moved commit when the move did not touch a file the base depends
    on. Else None (absent, stale, damaged: a new measurement)."""
    if not core or not base_sha or state_dir is None:
        return None
    path = _shared_base_file(state_dir, core)
    try:
        rec = json.loads(path.read_text(encoding='utf-8'))
        if not 0 <= _now() - float(rec['at']) < BASE_CACHE_S:
            return None
        result = _gate_result(rec['result'])
        if not _carry_ok(root, rec['sha'], base_sha, rec.get('carry'), rec.get('deps')):
            return None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    if rec['sha'] != base_sha:
        try:
            save_atomic(path, dict(rec, sha=base_sha))
        except OSError:
            pass
    return result


def _shared_base_put(core: str, base_sha: str | None, task: Task, result, state_dir=None) -> None:
    if not core or not base_sha or state_dir is None:
        return
    try:
        folder = Path(state_dir) / SHARED_BASE_DIR
        folder.mkdir(parents=True, exist_ok=True)
        old = sorted((f for f in folder.glob('*.json')), key=lambda f: f.stat().st_mtime)
        for f in old[:max(0, len(old) - SHARED_BASE_MAX + 1)]:
            f.unlink(missing_ok=True)
        kept = dataclasses.asdict(result)
        kept['path'] = [list(c) for c in kept.get('path') or ()]
        save_atomic(_shared_base_file(state_dir, core),
                    {'sha': base_sha, 'at': _now(), 'result': kept, 'deps': sorted(_base_deps(task, result)),
                     'carry': bool(getattr(result, 'path', ()))})
    except (OSError, TypeError, ValueError):
        pass


def _held_base(row: dict, key: str | None, kind: str | None = None, state_dir: Path | None = None,
               core: str | None = None, base_sha: str | None = None, root=None):
    """The red base kept on the row while it is fresh; None when absent, stale, foreign or unreadable (a damaged
    record only costs a new measurement). It is the row's when the key matches, or when the core (tests and file
    bytes) matches and the commit moved over files the base does not depend on (the same carry rule as the shared
    store). A code task's record must carry the path of its failing tests (GateResult.path)."""
    held = row.get('base_red')
    if not isinstance(held, dict) or not key:
        return None
    try:
        if held.get('key') != key and not (core and base_sha and held.get('core') == core and _carry_ok(
                root, held.get('sha'), base_sha, held.get('carry'), held.get('deps'))):
            return None
        if not 0 <= _now() - float(held['at']) < BASE_CACHE_S:
            return None
        if kind == 'code' and 'path' not in held['result'] and 'path_file' not in held['result']:
            return None
        fields = dict(held['result'])
        if 'path_file' in fields:       # <id>: the trace lives in its own file beside the state; it is put back for the result
            name = Path(str(fields.pop('path_file'))).name
            if state_dir is None or not (Path(state_dir) / TRACE_DIR / name).is_file():
                return None             # the file is gone: measure once more
            trace = agent_factory_load_trace(state_dir, row)
            if trace is None:
                return None             # the file is there but unreadable (torn write, garbage): measure once more
            fields['path'] = [list(p) for p in trace]
        return _gate_result(fields)
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


def prepare(root: Path, task: Task, workdir: Path) -> dict[str, bytes]:
    """Copy only explicitly approved files, never .git, .env or any symlink.

    Existing tests are immutable for a code task. A unit_test task touches exactly its
    tests and the file may not exist yet (the model creates it). Safe staged sources
    still require external OS sandboxing before calling autonomous Kilo against private code.
    """
    root = root.resolve()
    workdir.mkdir(parents=True, exist_ok=False)
    names = set(task.read_files) | set(task.touch_files) | set(task.tests)
    if task.kind != "unit_test" and set(task.touch_files) & set(task.tests) and not gate.is_rig_task(task):      # a rig card repairs its own stand file; rig_weakens keeps its asserts
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
    contract = K.contract_of(task)
    if not (contract.get('parts') or (contract.get('test') or {}).get('new')):
        # a card of a contract is written from the contract (its regions are squeezed to the limit by factory_cards), not
        # from the whole files: their size is no reason to refuse it here (W-ctx 1)
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


NEIGHBORS_FILE = ".factory_neighbors.json"   # {file: [tests one import hop away]} of the snapshot's base, built once per base by the loop


def _map_tests(table: dict) -> list:
    """The test files of the base: the map has one key per .py file of the base tree (affected_tests.neighbors_map)."""
    out = []
    for rel in table:
        leaf = rel.rsplit('/', 1)[-1]
        if rel.startswith('tests/') and leaf.startswith('test_') and leaf.endswith('.py'):
            out.append(rel)
    return sorted(out)


def _unmapped_neighbors(root: Path, table: dict, name: str) -> list:
    """<id>: what affected_tests.affected(radius=1) answers for a file the map has no key for, read from the map and the
    test files alone (the graph of the product cost a card +107 MB, measured 26.11 on a 40 MB snapshot). A pytest config
    file: every test of the base. A .py file without a key is not in the base (new or deleted): the graph ignores it too.
    Any other file: the tests whose text names it (its leaf name or its path), the graph's one hop for a non-python file."""
    if name in affected_tests.ALL_TESTS_TRIGGERS:
        return _map_tests(table)
    if name.endswith('.py'):
        return []
    leaf = name.rsplit('/', 1)[-1]
    hits = []
    for rel in _map_tests(table):
        try:
            text = (Path(root) / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if leaf in text or name in text:
            hits.append(rel)
    return hits


def _mapped_neighbors(root: Path, task: Task):
    """The sorted neighbour tests of the task's touched files from the map file in ``root``, or None (no usable map
    file): the import graph is built only then. A touched file the map does not know is answered from the map itself
    (``_unmapped_neighbors``), never by the graph inside the card."""
    try:
        table = json.loads((Path(root) / NEIGHBORS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(table, dict):
        return None
    found: set = set()
    for name in task.touch_files:
        names = table.get(name)
        if names is None:
            names = _unmapped_neighbors(Path(root), table, name)
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            return None
        found.update(names)
    return sorted(found)


def neighbor_tests(root: Path, task: Task) -> list[str]:
    """Tests one import hop from the touched files (risk register #35): at most MAX_NEIGHBORS,
    only files that exist in ``root``, never the task's own tests. The graph is built over ``root``
    (the mirror of HEAD), not over the tool's tree. Any failure RAISES: the caller records
    ``neighbors_unavailable`` instead of silently treating it as "no neighbours"."""
    found = _mapped_neighbors(Path(root), task)
    if found is None:       # no map yet (the first run of a base) or a touched file missing in it: the graph, as before
        graph = affected_tests.Graph(Path(root))
        found, _, _ = affected_tests.affected(list(task.touch_files), radius=1, g=graph)
    out: list[str] = []
    rig = gate.is_rig_task(task)
    mine = [n for n in task.touch_files if rig and Path(n).name.startswith('test_') and n.endswith('.py') and n not in task.tests]   # W-rig: every id of a changed test file runs (the target file already runs as the target)
    for name in mine + list(found):
        if name in out:
            continue
        if name not in mine and (name in task.tests or name in task.touch_files):
            continue
        if (Path(root) / name).is_file():
            out.append(name)
    return out[:MAX_NEIGHBORS]


DURATIONS_FILE = "tests/data/factory_durations.json"    # measured seconds per test file of the previous cloud run


def _known_seconds(root: Path) -> dict:
    """The recorded duration table of ``root`` (flat ``{test path: seconds}``); missing or malformed is just empty."""
    try:
        raw = json.loads((Path(root) / DURATIONS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: float(v) for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0}


def gate_order(root: Path, names, first=()) -> list[str]:
    """Order of test runs: ``first`` (what failed last time) before everything else, then the fast before the heavy:
    by the recorded duration of the file, and for a file with none by its size scaled to the recorded ones (bytes
    when nothing is recorded at all). Stable, never drops or adds a name."""
    names = list(dict.fromkeys(names))
    head = set(first)
    secs = _known_seconds(root)

    def size(name: str) -> int:
        try:
            return (Path(root) / name.split("::", 1)[0]).stat().st_size
        except OSError:
            return 0
    ratios = sorted(secs[n.split("::", 1)[0]] / size(n) for n in names
                    if n.split("::", 1)[0] in secs and size(n) > 0)
    scale = ratios[len(ratios) // 2] if ratios else None

    def estimate(name: str) -> float:
        file = name.split("::", 1)[0]
        if file in secs:
            return secs[file]
        return size(name) * scale if scale else float(size(name))
    return ([n for n in names if n in head]
            + sorted((n for n in names if n not in head), key=lambda n: (estimate(n), n)))


def red_entries(ids, tests) -> list[str]:
    """The entries of ``tests`` (files or ``file::test``) that hold a test id of ``ids`` ('classname::name' as the
    gate records them: ``tests.test_x.Class::name``): what the last candidate was red on."""
    files = set()
    for one in ids:
        parts = str(one).split("::", 1)[0].split(".")
        for i, part in enumerate(parts):
            if part.startswith("test_"):
                files.add("/".join(parts[:i + 1]) + ".py")
                break
    return [t for t in tests if t.split("::", 1)[0] in files]


def staged_run(run, root: Path, tests, red=()):
    """One result for ``tests``: the entries that failed last time run ALONE first; still red (and not by the
    environment): that result is the answer, the rest never runs. Green or unclear: the rest runs and both are merged
    (a single run when there is nothing to split)."""
    tests = gate_order(root, tests, red)
    first = [t for t in tests if t in set(red)]
    if not first or len(first) == len(tests):
        return run(tests)
    one = run(first)
    if one.env_reason or (one.failed + one.errors > 0 and not one.env_failed):
        return one
    rest = [t for t in tests if t not in set(first)]
    return gate._merge([(tuple(first), one), (tuple(rest), run(rest))])


def candidate_tree(root: Path, workdir: Path, changed, into: Path) -> Path:
    """The source tree with the candidate files laid over it, as a SPARSE tree: only the changed files and a marker naming
    ``root`` (factory_tree). The cloud gate ships base + these files; the local gate fills the rest in right before pytest
    (real tests import the whole package, conftest and siblings that the model's narrow copy lacks), so a check that
    runs in the cloud copies nothing here."""
    return factory_tree.sparse_tree(root, into, {name: workdir.joinpath(*name.split("/")) for name in changed})


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


def unified_diff(baseline: dict[str, bytes], workdir: Path, names, limit: int, per_file: bool = False,
                 cut_note: str = '') -> str:
    """Redacted, truncated unified diff of the candidate against the baseline. ``per_file``: ``limit`` is the cut of
    EACH file's diff (a change by parts is shown part by part), not of the whole text."""
    chunks = []
    for name in sorted(names):
        path = workdir.joinpath(*name.split("/"))
        if not path.is_file():
            continue
        old = baseline.get(name, b'').decode('utf-8', 'replace').splitlines(keepends=True)
        new = path.read_bytes().decode('utf-8', 'replace').splitlines(keepends=True)
        piece = list(difflib.unified_diff(old, new, 'a/' + name, 'b/' + name, n=2))
        if per_file:
            text = redact(''.join(piece))
            chunks.append(text if len(text) <= limit else text[:limit] + (cut_note or DIFF_CUT) % limit)
        else:
            chunks.extend(piece)
    if per_file:
        return ''.join(chunks)
    text = redact(''.join(chunks))
    return text if len(text) <= limit else text[:limit] + (cut_note or DIFF_CUT) % limit



def paid_diff(baseline: dict[str, bytes], workdir: Path, names) -> str:
    """The paid critic's diff by parts too (step 4 (a)): each hunk cut at paid_critic.PART_LIMIT, all within its
    DIFF_LIMIT, never the whole diff cut at one limit."""
    return diff_parts(baseline, workdir, names, paid_critic.PART_LIMIT, paid_critic.DIFF_LIMIT)


def diff_parts(baseline: dict[str, bytes], workdir: Path, names, part_limit: int, total: int) -> str:
    """VARIANTS_1426 step 4 (a): the reviewer's diff by parts (one hunk of one file is a part). Each part is cut at its
    own ``part_limit``; the parts follow one another while ``total`` allows, and a part that no longer fits is named by
    its file and hunk header, never dropped in silence. The whole diff is never cut at one limit."""
    shown, left, unseen = [], max(0, total), []
    for name in sorted(names):
        path = workdir.joinpath(*name.split("/"))
        if not path.is_file():
            continue
        old = baseline.get(name, b'').decode('utf-8', 'replace').splitlines(keepends=True)
        new = path.read_bytes().decode('utf-8', 'replace').splitlines(keepends=True)
        lines = list(difflib.unified_diff(old, new, 'a/' + name, 'b/' + name, n=2))
        if not lines:
            continue
        head, hunks = ''.join(lines[:2]), []
        for line in lines[2:]:
            if line.startswith('@@') or not hunks:
                hunks.append([])
            hunks[-1].append(line)
        head_shown = False
        for hunk in hunks:
            text = redact(''.join(hunk))
            if len(text) > part_limit:
                text = text[:part_limit] + DIFF_CUT % part_limit
            piece = ('' if head_shown else redact(head)) + text
            if not unseen and len(piece) <= left:
                shown.append(piece)
                left -= len(piece)
                head_shown = True
            else:
                unseen.append('%s %s' % (name, hunk[0].strip()[:80]))
    if unseen:
        notes = ''
        for n, label in enumerate(unseen):
            note = '[part not shown, no room: %s]\n' % label
            rest = '[%d more parts not shown, no room]\n' % (len(unseen) - n)
            if len(note) + len(rest) > left - len(notes):
                notes += rest if len(rest) <= left - len(notes) else ''
                break
            notes += note
        shown.append(notes)
    return ''.join(shown)

# the cut of a diff named as a cut, not as the end of the change: live 20.11 07:48 a critic rejected a self-fix whose
# code had passed the gate as "truncated ... incomplete and syntactically invalid"
DIFF_CUT = '\n[the diff is cut here at %d characters; the rest of the change is not shown]\n'
REVIEW_FOCUS_LIMIT = 12000     # W-flow 1: the whole review prompt when the changed functions fit
REVIEW_DIFF_CUT = '\n[diff truncated at %d chars]\n'
_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def _defs_of(text: str) -> dict:
    """qualified name -> (node, source) of the functions of a Python text (methods as Class.name)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    lines = text.splitlines()
    found = {}
    for node in ast.walk(tree):
        scope = [(node.name + '.', n) for n in node.body if isinstance(n, _FUNC)] if isinstance(node, ast.ClassDef) else []
        if node is tree:
            scope = [('', n) for n in node.body if isinstance(n, _FUNC)]
        for prefix, fn in scope:
            start = min([fn.lineno] + [d.lineno for d in fn.decorator_list]) - 1
            found[prefix + fn.name] = (fn, '\n'.join(lines[start:fn.end_lineno]))
    return found


def _signature(fn) -> str:
    return '%sdef %s(%s)%s: ...' % ('async ' if isinstance(fn, ast.AsyncFunctionDef) else '', fn.name,
                                    ast.unparse(fn.args), ' -> ' + ast.unparse(fn.returns) if fn.returns else '')


def review_focus(baseline: dict, workdir: Path, names, files: dict, test_names=frozenset()) -> str:
    """W-flow 1: what a critic needs instead of whole files: the bodies of the functions the candidate changed (as
    they are after the edit), signatures of the functions they call, the bodies of the red tests. '' when no Python
    function changed (the caller then falls back to the file view)."""
    changed, called, all_defs = {}, set(), {}
    for name in sorted(names):
        path = workdir.joinpath(*name.split('/'))
        if not name.endswith('.py') or not path.is_file():
            continue
        new = _defs_of(path.read_bytes().decode('utf-8', 'replace'))
        old = _defs_of(baseline.get(name, b'').decode('utf-8', 'replace'))
        all_defs.update({(name, q): v for q, v in new.items()})
        for q, (fn, src) in new.items():
            if q not in old or old[q][1] != src:
                changed[(name, q)] = (fn, src)
    if not changed:
        return ''
    for fn, _ in changed.values():
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                f = node.func
                called.add(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else '')
    for name, data in files.items():          # the other files shown: signatures of what is called from there
        if name not in names and name.endswith('.py'):
            all_defs.update({(name, q): v for q, v in _defs_of(
                data.decode('utf-8', 'replace') if isinstance(data, bytes) else str(data)).items()})
    out = ['Changed functions after the edit:\n']
    for (name, q), (_, src) in changed.items():
        out.append('# %s :: %s\n%s\n\n' % (name, q, src))
    sigs = ['# %s\n%s\n' % (n, _signature(fn)) for (n, q), (fn, _) in sorted(all_defs.items())
            if (n, q) not in changed and q.split('.')[-1] in called][:60]
    if sigs:
        out.append('Signatures of what they call:\n' + ''.join(sigs) + '\n')
    tests = []
    for name, data in sorted(files.items()):
        low = name.replace('\\', '/').lower()
        if name in names or not (low.rsplit('/', 1)[-1].startswith('test_') or '/tests/' in '/' + low):
            continue
        for q, (fn, src) in _defs_of(data.decode('utf-8', 'replace') if isinstance(data, bytes) else str(data)).items():
            if fn.name in test_names or (not test_names and fn.name.startswith('test') and
                                         any(re.search(r'\b%s\b' % re.escape(c[1].split('.')[-1]), src)
                                             for c in changed)):
                tests.append('# %s :: %s\n%s\n\n' % (name, q, src))
    if tests:
        out.append('Red test:\n' + ''.join(tests))
    return redact(''.join(out))


GATE_PASSED = (' The candidate already compiles and passes the task tests (the gate ran them before you): never reject '
               'it for syntax, imports or the cut of the diff; judge what the change does.')


REVIEW_CHECKS = (
    'Check ALL of: (1) the behaviour is really fixed, no lost behaviour, no stubs, no incomplete '
    'error handling; (2) NO hard-coding: the candidate must not fit data or expectations to the '
    'test (special-casing test inputs, copying expected values) instead of fixing the behaviour; '
    '(3) NO scope creep: nothing outside the task and the listed files. A legitimate pass '
    'statement is not itself a defect. The task tests are the specification, fixed before the coder '
    'started: never reject a candidate by disputing what a test expects; judge only whether the code '
    'meets it honestly.')
# A code task's critics rejected a correct candidate three times by arguing with the guard test's expectation
# instead of the change (live 21.11): the tests are not theirs to judge.
# A unit_test task writes ONLY the test; its code task comes after it. Live 19.11 19:14-19:16: with the checks of a
# fix the reviewer rejected good tests "the patch only adds a test case but does not implement the fix".
REVIEW_CHECKS_TEST = (
    'This task writes ONLY a test: the fix is a separate later task, so the code under test stays unchanged and '
    'the new test is expected to FAIL on it now. Never reject it because the code is not fixed. Check ALL of: '
    '(1) the test imports the real code and calls it, and asserts the behaviour the task describes; (2) it fails '
    'on the current code because of the described defect and would pass once the defect is fixed; (3) NO stub: no '
    'MagicMock in place of the code under test, no assert False, no test that only checks that a name exists, no '
    'hard-coded counts of files or markers in the repository; (4) nothing outside the test file; (5) it does not '
    'replace (monkeypatch, fake) the function inside which the described behaviour happens, read its body and the '
    'comments at the call; (6) every function is called with the kind of arguments its signature and docstring take; '
    '(7) the defect it asserts is the one the task text names, on input of the kind the project really has: reject '
    'a test whose defect is the model\'s own guess ("might", "or has spaces/formatting") or whose input the task '
    'text and the code shown never produce.')
# (5) and (6), 20.11 02:55: two promoted tests could never be made green by a correct fix. <id> called
# diagnostics.reason_of(call marks) although it takes an exception or a token (unknown for anything else); <id> replaced
# controlled_host.say, inside which speech_text turns numbers into words, so the fake always saw digits.
# Owner: «турнир нескольких кандидатов с последовательной цепочкой критиков». A pass of the light engine
# asks up to TOURNAMENT_SIZE coders, each a different model, and every next one is told why the previous one failed;
# the first candidate that passes the mechanical checks (it changes the files, compiles, weakens no check) goes to the
# gate. Then up to REVIEW_PANEL critics of different models review it one after another, each with its own lens;
# the majority decides (the owner's cap is 4 rounds). A missing further model shortens the tournament, never
# fails the pass; a chain cut short never approves: the candidate stays pending for the next pass (review_chain_short,
# ESCALATE_AFTER in a row is BLOCKED).
TOURNAMENT_SIZE = 3
TOURNAMENT_NOTE = ('\nAnother model already tried this task in this pass and its answer could not be used: %s. Do not '
                   'repeat that mistake: copy every SEARCH line exactly from the code shown above, or give REPLACE FUNCTION '
                   'for a function shown whole.\n')
# <id>: a candidate that fails the test gate for real (not the environment, not an unknown neighbour) does not end the
# pass while the tournament has room: the next model sees the failing output and the diff of the previous one.
TOURNAMENT_GATE_NOTE = ('\nAnother model already tried this task in this pass; its change was applied and the tests '
                        'failed. Do not repeat that mistake.\nFailing test output:\n%s\n')
TOURNAMENT_DIFF_NOTE = '\nIts diff (do not repeat it):\n%s\n'
# live 20.11 03:18, one task: three candidates in a row answered CANNOT: _last_clause_question to the same view
TOURNAMENT_ASKED_NOTE = 'The code it asked for (%s) is shown above now: edit it.\n'
TOURNAMENT_OUTPUT_LIMIT = 1500
GATE_NOTE_ROOM = 5000    # a contract test card: the note of an earlier candidate (failing output, real signatures, diff) up to this
# live 21.11 (replay of 36 CANNOT runs): 27 asked for a function defined in the task's own files, 17 repeated the same
# CANNOT on the next attempt. What a model asked for is kept on the task row, so every later attempt shows it first.
ASKED_KEEP = 12


def remember_asked(row: dict, names) -> None:
    """Add ``names`` (the definitions a coder asked to see) to the task row's ``asked`` list: no duplicates, the
    newest ASKED_KEEP kept."""
    kept = [n for n in (row.get('asked') or []) if isinstance(n, str)]
    for name in (sorted(names) if isinstance(names, (set, frozenset)) else names):
        if name and name not in kept:
            kept.append(name)
    row['asked'] = kept[-ASKED_KEEP:]


def defined_names(task: Task, workdir: Path) -> frozenset:
    """Names of the functions and classes (nested too) defined in the python files the task may change."""
    found = set()
    for name in task.touch_files:
        if not name.endswith('.py'):
            continue
        try:
            tree = ast.parse(Path(workdir).joinpath(*name.split('/')).read_bytes().decode('utf-8', 'replace'))
        except (OSError, SyntaxError, ValueError):
            continue
        found |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    return frozenset(found)


class _GateRetry:
    """A real test failure of one candidate: the arguments of the ONE rejection that settles the pass if no other
    model can try, the failing output for the next prompt and the names of the files the candidate changed.
    ``no_effect``: the test failed exactly as on the base (same_failure): the change missed the checked path."""
    def __init__(self, reject_args: tuple, diag: str, changed, no_effect: bool = False):
        self.reject_args, self.diag, self.changed = reject_args, diag, list(changed)
        self.no_effect = no_effect


# <id> class "a change without effect" (live 20.11 10:35-10:43: 17 of 18 passes reached the gate with a real edit and
# every attempt of a task failed with the very output of the unchanged base: the models edited code off the path the
# guard test checks, e.g. cue timers for a test about the words of an objection)
NO_EFFECT_NOTE = ('\nThe previous change had NO effect on the failing test: it fails exactly as it did before the '
                  'change, so the code it edited is not on the path this test checks. Find where the asserted '
                  'behaviour is decided and change that place.')
# Path-checked scope (live 20.11 12:19 on: 11 of 20 passes no_effect, 0 promotions): the red-before run of a code task
# records the functions its failing tests ran (GateResult.path). Those in the task's files are shown first and whole
# (at most PATH_FOCUS_MAX names); those outside are named, and a CANNOT or an edit block naming one of them widens the
# task by its module (the loop amends touch_files); the NO_EFFECT_BLOCK_AFTER-th no-effect on one base blocks the task
# with that list for Opus instead of more passes.
OFF_PATH_NOTE = ('\nThe failing test also runs, outside the files you may change: %s. If the asserted behaviour is '
                 'decided there, answer CANNOT: <that name>.')
PATH_FOCUS_MAX = 12
OFF_PATH_SHORT = 8
FAILING_CHARS = 3000      # the red base's failure text a code card carries (was 1500: the failing line was cut off)
OFF_BODIES_NOTE = ('\nCode the failing test runs outside the files you may change (read-only, as it is now): the '
                   'asserted behaviour may be decided there; then answer CANNOT: <name> instead of editing around it.\n%s')


OFF_PATH_WAIT_S = 30
NO_EFFECT_BLOCK_AFTER = 4   # 21.11 (was 2)

# J4-cards (live 26-27.11, owner cards: 68 of 212 failed cards were a red gate and in 52 of them the second attempt failed with
# the SAME tests as the first): the card of a contract (edit_parts) carried only the red BASE's failure, so a repeat was the
# very same prompt as the first try. A repeat now also carries what the previous attempt did and why it was rejected.
RETRY_FEEDBACK_CHARS = 1500    # the head of the previous rejection (failing ids, first asserts / the critic's reason)
RETRY_HEAD = 'Your previous attempt on this task was applied and rejected. Do not repeat it. Why:\n'
RETRY_WHERE = '\nThe previous attempt changed %s of %s (%d lines); that was not enough.\n'
_HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')
_FAILING_ID = re.compile(r'failure (\S+?):(?=\s|$)')


def file_diff(diff: str, file: str) -> str:
    """The part of a unified ``diff`` that belongs to ``file`` ('' when it has none)."""
    out, keep = [], False
    for line in str(diff or '').splitlines(keepends=True):
        if line.startswith('--- '):
            keep = line[4:].strip() == 'a/' + file
        if keep:
            out.append(line)
    return ''.join(out)


def changed_ranges(diff: str) -> tuple:
    """(``lines 3-5 and 9``, number of changed lines) of the new file from the hunks of a unified ``diff`` of one file;
    ('', 0) when it has no hunk. A removal marks the place where the line was."""
    marked, number, count = [], 0, 0
    for line in str(diff or '').splitlines():
        head = _HUNK.match(line)
        if head:
            number = int(head.group(1))
        elif line.startswith('+') and not line.startswith('+++'):
            marked.append(number)
            number += 1
            count += 1
        elif line.startswith('-') and not line.startswith('---'):
            marked.append(number)
            count += 1
        elif number and not line.startswith('\\'):
            number += 1
    runs = []
    for value in sorted(set(marked)):
        if runs and value <= runs[-1][1] + 1:
            runs[-1][1] = value
        else:
            runs.append([value, value])
    if not runs:
        return '', 0
    spans = ['%d' % a if a == b else '%d-%d' % (a, b) for a, b in runs]
    return ('lines ' if len(spans) > 1 or runs[0][0] != runs[0][1] else 'line ') + ' and '.join(spans), count


def retry_evidence(feedback, prev_diff, file: str) -> str:
    """The note of a repeated attempt for the card of ``file``: the previous rejection (``feedback`` as fresh_feedback
    gives it; a change with no effect says so and where to look) and WHERE that attempt changed the file: the line
    ranges of the new file and the number of changed lines, never a line of its code (a model shown a failed answer
    repeats it, and the voices of the ensemble must stay different)."""
    feedback = str(feedback or '').strip()
    if not feedback:
        return ''
    out = RETRY_HEAD + feedback[:RETRY_FEEDBACK_CHARS]
    if '[no effect]' in feedback:
        out += NO_EFFECT_NOTE
    where, count = changed_ranges(file_diff(prev_diff, file))
    if where:
        out += RETRY_WHERE % (where, file, count)
    return out


def progressed(prior, now) -> bool:
    """True when the failing tests of ``now`` are a strict, non-empty subset of those of ``prior``: the last change
    got closer (fewer tests red), so that red does not count toward the row's reslice (settle's ``reslice_after``)."""
    before, after = set(_FAILING_ID.findall(str(prior or ''))), set(_FAILING_ID.findall(str(now or '')))
    return bool(before) and bool(after) and after < before
_ADDRESS = re.compile(r'0x[0-9A-Fa-f]{4,}')
_WORKDIR = re.compile(r'task-[\w.-]+')
_SECONDS = re.compile(r'\b\d+(?:\.\d+)?s\b')


def same_failure(base_diag: str, cand_diag: str) -> bool:
    """The candidate's failing output is the base's (object addresses, work folders and durations aside)."""
    def norm(text):
        return _SECONDS.sub('?s', _WORKDIR.sub('task', _ADDRESS.sub('0x?', text or ''))).strip()
    return bool(norm(cand_diag)) and norm(base_diag) == norm(cand_diag)


# Execution-ranked selection: the critics get the mechanical execution report and answer a fixed rubric; up to
# REVIEW_PANEL critics of different models vote and the majority decides (2 of 3). A split with no further model goes
# to the mechanical ranking. The owner's cap is 4 rounds.
REVIEW_PANEL = 3
REVIEW_LENSES = (
    '',
    'You are the SECOND critic: judge on your own, then look at what the earlier critic said. Look for what it may '
    'have missed: an expected result of the task\'s own examples that the change or the test does not pin exactly (a '
    'check that only says a value changed accepts any wrong change), a case the task names that is not handled, a '
    'change the task did not ask for.',
    'You are the THIRD critic: the earlier critics disagree or only partly checked. Check that nothing the task asks '
    'for is missing and that the change cannot break the code around it (callers, error paths, other inputs of the '
    'same function). Reject only a concrete defect you can name with its line.')
# fac-41: when no independent second model is free now, the first critic's model may look again, with
# the first answer in front of it; it never replaces an independent voice and the author never votes.
RECHECK_LENS = (
    'You are the SAME model as the first critic, asked again only because no other independent model is free now. Check '
    'BOTH the change AND the first critic\'s answer above: is every defect it named real, did it miss one? Agreement '
    'without your own reference to a line of the code or the test is not an answer: cite the line you checked.')
RUBRIC_ASK = (
    'Answer with exactly this JSON and nothing else: {"defect_assert_line": "<the exact line of the test, copied '
    'character for character, that observes the defect the task names>", "fix_changes_value": "<what a correct fix '
    'changes at that line: the value before and after>", "independent_asserts": ["<every assert line of the test '
    'that does not depend on the code under test, e.g. a literal compared with a literal; empty list when there is '
    'none>"], "approved": true|false, "reasons": ["each concrete defect"]}. The candidate is approved only when the '
    'line is really in the test and no independent assert is listed.\n')
EXEC_REPORT_LIMIT = 1500
EXEC_PATH_NAMES = 12


def red_evidence(diag) -> str:
    """The proof that a NEW test is red on the unchanged base: its failing assert line (``>`` line of the pytest trace) and the
    error line (``E`` lines) from the gate's run of the candidate on the base; '' when the text shows none of them."""
    lines = [ln.rstrip() for ln in str(diag or '').splitlines()]
    picked = [ln for ln in lines if ln.lstrip().startswith(('>', 'E ')) or 'AssertionError' in ln]
    return '\n'.join(picked[:6])[:500] if picked else ''


def execution_report(base, hollow=(), extra_names=(), red='') -> str:
    """The mechanical facts a critic gets beside the diff (measured by the gate, not an opinion): the output of the
    red-before run, the functions the failing tests ran, hollow findings, names the candidate adds beyond the task.
    ``red``: for a new test (there are no base tests to run) the failing assert of the test on the base, from the gate."""
    parts = []
    diag = redact(str(getattr(base, 'diag', '') or '')).strip()
    if red:
        parts.append('Red-before evidence (the NEW test fails on the unchanged base, so it is red before the fix):\n'
                     + redact(red)[-600:])
    elif diag:
        parts.append('Red-before output (the tests on the unchanged base):\n' + diag[-600:])
    path = tuple(getattr(base, 'path', ()) or ())
    if path:
        parts.append('Failing path (functions the failing tests ran): ' + ', '.join(
            '%s::%s' % (p[0], p[1]) if isinstance(p, (list, tuple)) and len(p) > 1 else str(p)
            for p in path[:EXEC_PATH_NAMES]))
    if hollow:
        parts.append('Hollow findings: ' + '; '.join(redact(str(h))[:120] for h in hollow))
    if extra_names:
        parts.append('Names the candidate adds beyond the task: ' + ', '.join(redact(str(n))[:60] for n in extra_names))
    return ('Mechanical execution report:\n' + '\n'.join(parts) + '\n')[:EXEC_REPORT_LIMIT] if parts else ''


def mechanically_ok(base, hollow=(), extra_names=()) -> bool:
    """The mechanical ranking of a candidate: the failing tests ran code (a failing path was measured) and nothing
    hollow or extra was found. It only breaks a tie between critics, never overrules a majority."""
    return bool(getattr(base, 'path', ())) and not hollow and not extra_names


def _squash(text: str) -> str:
    return ' '.join(str(text).split())


RUBRIC_INVALID_TAG = 'critic rubric:'
RUBRIC_INVALID_TRIES = 3     # invalid answers of different models one critic seat tolerates before the call is a reviewer fault


def rubric_problems(answer: dict, haystack: str) -> list[str]:
    """Why an answer of the critic is not an approval: the cited test line must literally be in the code shown, the fix
    must name the value it changes, and no assert independent of the code under test may be listed. A missing or
    malformed rubric is a problem, never an approval."""
    problems = []
    line = answer.get('defect_assert_line')
    if not isinstance(line, str) or len(_squash(line)) < 3:
        problems.append('critic rubric: defect_assert_line is missing')
    elif _squash(line) not in _squash(haystack):
        problems.append('critic rubric: the cited line is not in the test: ' + redact(_squash(line))[:120])
    fix = answer.get('fix_changes_value')
    if not isinstance(fix, str) or not fix.strip():
        problems.append('critic rubric: fix_changes_value is missing')
    asserts = answer.get('independent_asserts')
    if not isinstance(asserts, list):
        problems.append('critic rubric: independent_asserts is missing')
    elif [a for a in asserts if str(a).strip()]:
        problems.append('independent asserts that do not depend on the code under test: ' +
                        '; '.join(redact(_squash(a))[:100] for a in asserts if str(a).strip()))
    return problems


CITE_MIN = 6       # a quoted fragment shorter than this (without spaces) is a name, not a cited line
BARE_NAME = re.compile(r'[\w.:/\\-]+(\(\))?')     # `validate_input`, `check()`, `tests/x.py`: a name, not a line
COMMANDS = frozenset(('pytest', 'python', 'python3', 'py', 'git', 'bash', 'sh', 'pip', 'ruff', 'npm', 'uv'))


def _cited_line(fragment: str) -> bool:
    """A `quoted` fragment of a reason cites a line of code; a bare name (often of what is missing) or a command to
    run is no citation and is never checked against the text shown (review fix 2)."""
    text = fragment.strip()
    return bool(text) and not BARE_NAME.fullmatch(text) and text.split()[0] not in COMMANDS


def unfounded_citations(answer: dict, reasons: list, shown: str, rubric: bool = True) -> list[str]:
    """Step 4 (b): what a critic cites as a line (the rubric's defect_assert_line, a `quoted` fragment of a reason) and
    that is in none of the texts it was shown, compared without whitespace. An ellipsis splits a quote into pieces.
    ``rubric``: the cited line is read only when the rubric asked for it."""
    plain = re.sub(r'\s+', '', shown)
    cited = []
    line = answer.get('defect_assert_line') if rubric else None
    if isinstance(line, str):
        cited.append(line)
    for reason in reasons:
        cited.extend(q for q in re.findall(r'`([^`\n]+)`', str(reason)) if _cited_line(q))
    missing = []
    for quote in cited:
        for piece in re.split(r'\.\.\.|\u2026', quote):
            bare = re.sub(r'\s+', '', piece)
            if len(bare) >= CITE_MIN and bare not in plain:
                missing.append(' '.join(piece.split()))
    return missing


def panel_verdict(votes: list, final: bool, mechanical_ok: bool):
    """True / False when the majority of the panel (2 of REVIEW_PANEL) is reached; None while undecided. ``final``:
    no further critic can be asked; an even split then goes to the mechanical ranking, a single vote stays undecided
    (one critic never decides alone)."""
    need = REVIEW_PANEL // 2 + 1
    yes = sum(1 for v in votes if v)
    if yes >= need:
        return True
    if len(votes) - yes >= need:
        return False
    if final and len(votes) >= 2 and yes * 2 == len(votes):
        return bool(mechanical_ok)
    return None


def review_candidate(task: Task, workdir: Path, model: str, invoke, *,
                     baseline: dict[str, bytes] | None = None,
                     scratch: Path | None = None, lens: str = '', prior: tuple = (),
                     rejected: str = '', rubric: bool = False, execution: str = '') -> tuple[bool, list[str]]:
    """A separate call sees an immutable copy and returns ``(approved, reasons)``.

    ``rubric``: the critic answers the fixed rubric (RUBRIC_ASK) and an approval stands only when the cited test line is
    really in the code shown and no independent assert is listed; ``execution``: the mechanical report shown to it.

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
        told = ('Earlier candidates of this task were rejected for:\n' + rejected[-REVIEW_NOTE_LIMIT:] +
                '\nReject this candidate if it still has a defect named there.\n') if rejected else ''
        # acceptance 20.11 (<id> and six before): the critics saw only the title ("Тест для <id>") and judged "the
        # described defect" by the test's own comment. They get the task text the coder got (same redaction, same cap).
        lessons = paid_critic.lessons_for(task, rejected or '')   # owner: catches of the paid critic that free critics missed
        goal = getattr(task, 'goal', '') or ''
        said_goal = ('Task text (what the coder was asked):\n' + redact(scrub_paths(goal))[:1500] + '\n') if goal else ''
        restate = K.restate_note(task)
        rubric = rubric and not restate      # the cited line of the old test is gone on purpose
        said_goal += restate
        spec = K.test_spec(task)      # W-critic 1: a test card's critics get the contract the test must meet
        said_goal += ('Contract of the new test:\n' + redact(spec)[:1500] + '\n') if spec else ''
        head = ('Review this patch task: ' + redact(task.title) + '.\n' + said_goal + ('' if restate else checks) + GATE_PASSED + '\n' + told +
                (lessons + '\n' if lessons else '') +
                (' The task files are below: small files whole, a large file as its outline and the parts that '
                 'matter. Judge the candidate by its diff and the code shown; never reject it only because some '
                 'code is not shown.\n' if light else
                 ' Read only the explicitly supplied files (relative paths in your working directory: '
                 + ', '.join(sorted(files_for_hint)) + '); grep inside it is allowed, nothing outside it.\n') +
                earlier + (execution if rubric else '') +
                (RUBRIC_ASK if rubric else 'Return exactly JSON {"approved":true|false,"reasons":["each concrete defect"]}.\n'))
        files = {n: v for n, v in snapshot.items() if n != POLICY_FILE}
        by_parts = bool(K.contract_of(task).get('parts'))     # a change by parts is judged part by part
        focused = None       # W-flow 1: the whole diff + the changed functions, when they fit REVIEW_FOCUS_LIMIT
        if baseline is not None and not by_parts:
            whole = unified_diff(baseline, workdir, task.touch_files, REVIEW_FOCUS_LIMIT, cut_note=REVIEW_DIFF_CUT)
            test_names = (set(re.findall(r'::([A-Za-z_]\w*)', ' '.join(task.tests) + ' ' + (execution or ''))) |
                          set(asked_names(execution or '')))
            focus = review_focus(baseline, workdir, task.touch_files, files, frozenset(test_names))
            # no named red test and a large test file: "every test that calls the changed function" is hundreds of
            # bodies; the outline view of the file (failing test first) is the right picture then
            unnamed_big_test = not test_names and any(
                n.replace('\\', '/').rsplit('/', 1)[-1].startswith('test_') for n in large_names(task, files))
            if focus and whole and not unnamed_big_test:
                piece = head + 'Candidate diff:\n' + whole + '\n' + focus
                if len(piece) <= REVIEW_FOCUS_LIMIT and 'diff truncated' not in whole:
                    focused = piece
        # step 4 (a) of VARIANTS_1426: the diff by parts (each hunk cut at its own REVIEW_DIFF_LIMIT), not the whole
        # diff cut at 6000: the files shown give way to a longer diff, down to the room of one file view
        full_diff = (diff_parts(baseline, workdir, task.touch_files, REVIEW_DIFF_LIMIT, channels.PROMPT_LIMIT_CHARS)
                     if baseline is not None and focused is None else '')
        priority = frozenset(keywords_from(task.title, strict=False)
                             | identifier_tokens(getattr(task, 'goal', '') or ''))
        words = priority | keywords_from(full_diff)
        big = large_names(task, files)
        targets = visible_targets(task)
        diff_room = (max(REVIEW_DIFF_LIMIT, min(len(full_diff), channels.PROMPT_LIMIT_CHARS - len(head) - 250 - VIEW_ROOM))
                     if baseline is not None else 0)
        review_budget = channels.PROMPT_LIMIT_CHARS - len(head) - 250 - diff_room
        body = render(files, targets, large=big, keywords=words, budget_chars=review_budget,
                      small_tokens=max(task.context_budget, review_budget),
                      priority=priority, hint=LIGHT_REVIEW_HINT if light else REVIEW_HINT, tools=not light)
        room = channels.PROMPT_LIMIT_CHARS - len(head) - len(body) - 250  # the diff takes only what is left
        diff = ''
        if baseline is not None and room > 300:
            diff = diff_parts(baseline, workdir, task.touch_files, REVIEW_DIFF_LIMIT, room)
        prompt = head + ('Candidate diff:\n' + diff + '\n' if diff else '') + body
        if focused is not None:
            prompt, diff = focused, whole
        rc, stdout, _ = invoke(reviewer, review_root, model, prompt_override=prompt)
        if rc != 0 or inspect_changes(reviewer, review_root, snapshot):
            raise ReviewFault('reviewer call failed rc=%s' % rc)
        summary = event_summary(stdout)
        if summary['provider_error'] or summary['finish_reason'] in ('length', 'max_tokens'):
            raise ReviewFault('reviewer provider error or truncated answer')
        text = summary['text'].strip()
        answer = _last_json_object(text)   # the LAST JSON object: free models think aloud, wrap it in prose or a fence
        if answer is None:
            raise ReviewFault('reviewer answer is not JSON')
        if not isinstance(answer, dict) or type(answer.get('approved')) is not bool:
            raise ReviewFault('reviewer answer has no verdict')
        reasons = answer.get('reasons', answer.get('reason', []))
        if isinstance(reasons, str):
            reasons = [reasons]
        reasons = [str(r)[:400] for r in reasons if str(r).strip()] if isinstance(reasons, list) else []
        # what it was shown of the change: the diff, the files, the task text, the measured report, the earlier
        # rejections and lessons it was told to check (not the earlier critics' remarks: a quote copied from them proves
        # nothing)
        unfounded = unfounded_citations(answer, reasons, '\n'.join(
            [diff, goal, execution, told, lessons or ''] + [v.decode('utf-8', 'replace') if isinstance(v, bytes) else str(v)
                                      for v in files.values()]), rubric)
        if unfounded:
            raise UnfoundedVote('critic cites what is not shown: ' + '; '.join(redact(u)[:120] for u in unfounded[:3]))
        if rubric and answer['approved']:
            def _is_test(name):
                low = str(name).replace('\\', '/').lower()
                return '/tests/' in '/' + low or low.rsplit('/', 1)[-1].startswith('test_') or '_test.' in low
            tests_shown = {n: v for n, v in files.items() if _is_test(n)}
            # the cited line must be in a test file; with no test file shown the code and the diff are all there is
            shown = tests_shown or files
            seen = '\n'.join([v.decode('utf-8', 'replace') if isinstance(v, bytes) else str(v)
                              for v in shown.values()] + ([] if tests_shown else [diff]))
            problems = rubric_problems(answer, seen)
            invalid = [p for p in problems if p.startswith(RUBRIC_INVALID_TAG) and 'independent_asserts' not in p]
            if invalid:       # not a verdict of the candidate: the next model of the chain is asked in its place
                raise RubricInvalid('; '.join(invalid))
            if problems:
                return False, problems + reasons
        if answer['approved']:
            return True, reasons          # an approving critic keeps its remarks: the next critic sees them
        return False, reasons or ['rejected without a stated reason']


def _last_json_object(text: str):
    """The last top-level JSON object of ``text`` (a verdict repeated after drafts counts once, at its end), else None.
    Braces of prose are skipped; the verdict object is preferred when several objects stand in the answer."""
    decoder, found, i = json.JSONDecoder(), [], 0
    while True:
        i = text.find('{', i)
        if i < 0:
            break
        try:
            value, end = decoder.raw_decode(text[i:])
        except ValueError:
            i += 1
            continue
        if isinstance(value, dict):
            found.append(value)
        i += end
    verdicts = [v for v in found if 'approved' in v]
    return (verdicts or found or [None])[-1]


REFERENCE_MAX = 5000   # the old-branch diff of a port task in the coder prompt; the view of the files gets the rest


def port_reference(root: Path, task: Task) -> str:
    """The diff of the old-branch commit a port task names (factory_port.reference: code files only, never a test or
    a key), '' for any other task or on any fault: a missing reference costs the model its example, never the pass."""
    sha = getattr(task, 'port_from', '')
    if not sha or task.kind == 'unit_test':
        return ''
    try:
        from . import factory_port
        return factory_port.reference(root, sha, max_chars=REFERENCE_MAX)
    except Exception:  # noqa: BLE001
        return ''


PORT_FOCUS_MAX = 8     # how many of the functions the old commit changed the coder's view asks for first


def port_focus(repo: Path, task: Task) -> frozenset:
    """The functions the old-branch commit of a port task changed, as names the coder's view shows first (whole when the
    room allows): the model edits their present versions, not whatever a stale suspect list names (live 20.11 09:34: the
    view showed ``_continuation`` of another module while ``_fast_release``, the function the commit changed, was only in
    the outline). Identifier-like names only: ``tick`` or ``release`` would pull every method of that name, a dunder
    every constructor. Empty for any other task and on any fault."""
    sha = getattr(task, 'port_from', '')
    if not sha or task.kind == 'unit_test':
        return frozenset()
    try:
        from . import factory_port
        names = factory_port.changed_names(repo, sha)
    except Exception:  # noqa: BLE001
        return frozenset()
    own = [n for n in names if identifier_tokens(n) == {n} and not n.startswith('__')]
    return frozenset(own[:PORT_FOCUS_MAX])


def build_coder_prompt(task: Task, visible: dict[str, bytes], feedback: str | None = None,
                       prev_diff: str = '', *, goal: str | None = None, failing: str = '',
                       light: bool = False, asked: frozenset = frozenset(), reference: str = '',
                       focus: frozenset = frozenset(), off_path=(), off_bodies: str = '',
                       failing_chars: int = 1500) -> str:
    """The ONE builder of the coder prompt (used by the pass and by model_attempt's default). ``light``: the
    prompt of the light engine, which has no tools: no read/grep instructions (live 19.11 17:48-17:50:
    with them the model answered "CANNOT: requires access outside the provided files"). ``asked``: definitions
    a model of this pass asked to see; with the ones the feedback names (asked_names) they are shown first.
    ``off_path`` names functions outside the allowed files."""
    asked = frozenset(asked) | asked_names(feedback or '')
    targets = visible_targets(task)
    if task.kind == 'unit_test':
        # its own test file is the one file it writes: never "read-only" or "do not modify tests" (critic 19.11)
        core = ("Write ONLY the test of task " + task.id + ": " + redact(task.title) +
                ". Create or change only the test file: " + ", ".join(task.touch_files) +
                ". The code it tests is read-only. Do not execute deployment, read parent folders, "
                "or use network tools other than the configured model.\n" + unit_rules())
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
        core += ("\nFailing on the base now (must pass after your change):\n"
                 + redact(failing)[:failing_chars])
    if off_path and task.kind != 'unit_test':
        core += OFF_PATH_NOTE % ', '.join(off_path)
    if reference and task.kind != 'unit_test':
        # a port task: the behaviour was built before on an old branch, in the code's old layout (live 20.11: 35 open
        # rows say so, their guard tests are red on the head of the unified code)
        core += ("\nThis behaviour was built before on an old branch, in the old layout of the code (commit " +
                 str(getattr(task, 'port_from', '')) + "). Its diff below is a reference, not a patch: files, names "
                 "and lines differ here, so copy every SEARCH line from the current files shown further below, never "
                 "from this diff. Bring the same behaviour into the files you may change:\n" +
                 redact(scrub_paths(reference))[:REFERENCE_MAX])
    if task.kind == 'unit_test':
        core += (" Write the test so that it FAILS on the current code because of the described "
                 "defect and would pass once the defect is fixed.")
        if task.backlog_id and not gate.SELF_REPO:     # the second instance: the row is known from the task, no marker is asked
            core += (" The FIRST line of the test file must be exactly: # factory-backlog-id: " + task.backlog_id +
                     " (in a new file: an EMPTY SEARCH part and the marker as the first line of REPLACE only)")
    if feedback:
        core += "\nThe previous candidate was rejected. Feedback:\n" + redact(feedback)
    tests_text = ' '.join(visible[n].decode('utf-8', 'replace') for n in task.tests if n in visible)
    tests_shown = {n: visible[n] for n in task.tests if n in visible}
    priority = frozenset(keywords_from(task.title, strict=False) | identifier_tokens(feedback or '')
                         | identifier_tokens(goal or '') | asked | failing_names(failing, tests_shown)
                         | frozenset(focus))
    words = priority | keywords_from(tests_text, prev_diff, feedback)
    budget = channels.PROMPT_LIMIT_CHARS - REVIEW_OVERHEAD - len(core) - (2500 if prev_diff else 0) - 60
    core += '\n' + render(visible, targets, large=large_names(task, visible), keywords=words,
                          budget_chars=budget, small_tokens=max(task.context_budget, budget), priority=priority,
                          asked=asked, pinned=pinned_targets(task),
                          **({'hint': LIGHT_HINT, 'tools': False} if light else {}))
    limit = channels.PROMPT_LIMIT_CHARS
    room = limit - len(core) - 200
    if off_bodies and task.kind != 'unit_test':
        # after the task's own files (they come first and whole): only what the card has room for, half of it at most
        # when a rejected diff is to follow
        share = room // 2 if prev_diff else room
        if share > 600:
            core += (OFF_BODIES_NOTE % redact(off_bodies))[:share]
            room = limit - len(core) - 200
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
    if channels.prompt_too_big(prompt):
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
# a coder task that changes more files is a multi-file edit: Kilo. 3 since 20.11 (telemetry of the whole run: Kilo 0 of
# 14 passes ever reached a review, every one of the 17 promoted candidates came from the light engine; 08:44-08:46 a
# 3-file row burned its three passes on 'steps exhausted'); the triage's MAX_TOUCH is 3, so no triaged task goes to Kilo
LIGHT_MAX_FILES = 10   # 23.11: a contract of up to 10 parts (one stage) is edited by the light engine, one card per file
PART_RETRIES = 2      # a part whose answer cannot be applied is asked again this many times (no strike)
FEEDBACK_CARD_CHARS = 3000   # the feedback a contract test card carries (its newest end)
PART_WAIT_REST_S = 20    # fac-pace: was 60 (a window of a channel opens within a minute); # a pass that found no free channel for PART_WAIT_S rests at least this long (fresh cards go first meanwhile)
PART_WAIT_S = 30     # a call waits for the nearest free channel at most this long, then the pass is deferred
PART_RETRY_NOTE = ('\nYour previous answer for this file could not be used: %s\nAnswer again for this file only, '
                   'copying the SEARCH lines exactly from the code shown above.\n')
PACK_CHARS_MAX = 4500    # fac-pace: context pack of one edit card, characters (~1.3K tokens); 13% of cards over 4K tokens held 28% of the edit tokens
LIGHT_OVERHEAD_TOKENS = 300      # the rules below and the chat wrapper (Kilo: 5 300-7 300)
LIGHT_TIMEOUT_S = 180
LIGHT_MAX_OUTPUT = 8192
_ENS_LEFT = threading.local()     # fac-68: the calling ensemble branch's remaining term (seconds), read by vgs_ask
LIGHT_REASONING_TOKENS = 2048
LIGHT_ENDPOINTS = {'google': 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
                   'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
                   'groq': 'https://api.groq.com/openai/v1/chat/completions',
                   'cerebras': 'https://api.cerebras.ai/v1/chat/completions',
                   'cohere': 'https://api.cohere.com/compatibility/v1/chat/completions',
                   'huggingface': 'https://router.huggingface.co/v1/chat/completions'}
# The bound of an explicit day budget of model calls: above the capacity of every free key (~60 000 a day, 20.11);
# the loop passes the registry's capacity (factory_loop.Loop._call_budget), each channel's rpd stays its limit.
MAX_MODEL_CALLS = 100_000
# ERROR_PATTERNS 'inline-thought' (live 20.11): Gemma 4 writes its reasoning into the answer (<thought>...), cannot be
# told so by reasoning_effort 'none' ('Thinking budget is not supported for this model', 400; 'minimal' IS accepted,
# see factory_channels.MODEL_BODY) and ran to the 8192 cap in ~175 s on
# coder calls; with this line its answers came without the section (probe 2 of 2, 3 of 3 with it before). Every light
# call starts with it; a leading block that still comes is stripped (_LIGHT_THOUGHT).
NO_THOUGHT = "Answer at once: do not think aloud, write no <thought> or <think> section. "
LIGHT_EDIT_RULES = (
    NO_THOUGHT + "You are a precise code editor. This call has NO tools: everything you may use is in the message. Change "
    "only the allowed files. Answer ONLY with edit blocks, no analysis before them. A block is: the file path on "
    "its own line; a line <<<<<<< SEARCH; lines copied EXACTLY from the shown file (enough to be unique, never "
    "line numbers or omission markers); a line =======; the new lines; a line >>>>>>> REPLACE. An empty SEARCH "
    "part creates a new file (or fills an empty one) with the new lines. Several blocks are allowed. If the "
    "code you must change is not shown, answer one line: CANNOT: and the name of the function you need. To "
    "replace a whole function or method instead, write the line REPLACE FUNCTION <path> <name> (name: func or "
    "Class.method), then a ```python fence with the complete new definition, then a closing ``` line. Use it "
    "only for a function shown WHOLE in the message, never for one shown in part; write every line of it, "
    "never ... or a comment instead of code.")
LIGHT_HINT = ("The file is large: only its outline and the parts below are shown. Copy SEARCH lines from the "
              "shown parts; if the code to change is not shown, answer CANNOT: and the function name. REPLACE FUNCTION "
              "only for a function shown whole.")
LIGHT_REVIEW_RULES = (NO_THOUGHT + "You review a code patch. This call has NO tools: everything you may use is in "
                      "the message. Answer with the JSON verdict only.")
_LIGHT_NAME = re.compile(r'[\w./\\-]+\.[A-Za-z0-9]+')
# Gemma 4 on the OpenAI-compatible endpoint puts its reasoning before the answer (<thought>...</thought>, live 19.11);
# other free models use <think>. A draft edit inside it must never be applied, and the verdict JSON follows it.
# Only a LEADING block: the same tags inside a REPLACE (code that strips them) are the edit itself (critic 19.11).
_LIGHT_THOUGHT = re.compile(r'^\s*<(thought|thinking|think)>.*?</\1>\s*', re.S | re.I)
_LIGHT_THOUGHT_OPEN = re.compile(r'^\s*<(?:thought|thinking|think)>', re.I)
_WHY_LINE = re.compile(r'(?im)^[ \t]*#[ \t]*WHY:')
_CANNOT_LINE = re.compile(r'(?im)^[^\w\n]*CANNOT:')


def strip_thought(content: str, last=_WHY_LINE, first=_CANNOT_LINE) -> str:
    """The answer without the model's leading reasoning (the one stripper: light coder, architect). A closed
    <thought>/<thinking>/<think> block is dropped. An UNCLOSED one (the closing tag never came) hides a draft: the answer
    starts at the last ``last`` line (the card's '# WHY:'), else at the first ``first`` line (CANNOT:); with neither
    (or None for both: an answer with no such format), nothing of it is an answer (a draft is never applied)."""
    content = str(content or '')
    closed = _LIGHT_THOUGHT.match(content)
    if closed:
        return content[closed.end():].strip()
    if not _LIGHT_THOUGHT_OPEN.match(content):
        return content.strip()
    why = list(last.finditer(content)) if last is not None else []
    start = why[-1] if why else (first.search(content) if first is not None else None)
    return content[start.start():].strip() if start else ''


def _example_function(task: Task, workdir) -> str:
    """A function of the first touch file that the title or the goal names (``Class.method`` or a plain name), else
    the first one of the file; '' when the file is no readable Python."""
    import ast
    first = task.touch_files[0]
    try:
        tree = ast.parse((Path(workdir).joinpath(*first.split('/'))).read_bytes().decode('utf-8'))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError, RecursionError, MemoryError, TypeError):
        return ''
    names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for c in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        names.extend('%s.%s' % (c.name, m.name) for m in c.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
    said = re.findall(r'[^\W\d]\w*(?:\.[^\W\d]\w*)?', '%s %s' % (task.title, task.goal))
    for word in said:
        hit = [n for n in names if n == word] or [n for n in names if n.rpartition('.')[2] == word and '.' in n]
        if hit:
            return hit[0]
    return names[0] if names else ''


def light_rules(task: Task, workdir=None) -> str:
    """The coder's system text with the task's real file paths (live 19.11: a placeholder path in the format
    example was copied literally and became 'a block for a file outside the task'). The function in the example
    is a real one of the first file when ``workdir`` is given."""
    first = task.touch_files[0]
    name = (_example_function(task, workdir) if workdir is not None else '') or 'Class.method'
    leaf = name.rpartition('.')[2]
    return (LIGHT_EDIT_RULES + "\nAllowed files: " + ", ".join(task.touch_files) + ".\nThe shape of a block:\n"
            + first + "\n<<<<<<< SEARCH\n(old lines)\n=======\n(new lines)\n>>>>>>> REPLACE"
            + "\nor, for a whole function shown whole:\nREPLACE FUNCTION " + first + " " + name + "\n```python\n"
            "def " + leaf + "(...):\n    (the whole new definition, every line)\n```")


def path_trace(task: Task) -> tuple:
    """The source prefixes whose functions the red-before run records for a code task: the top folder of each touch
    file (a top-level file: itself); () for any other kind."""
    if task.kind != 'code':
        return ()
    return tuple(sorted({f.split('/', 1)[0] + '/' if '/' in f else f for f in task.touch_files}))


def cannot_names(payload: str) -> list:
    """The names a CANNOT answer gives: a lone word as it is (``CANNOT: provider``); in a sentence only the code-like
    words (with ``_``, ``.``, ``/`` or an inner capital), so prose (``requires access outside the files``) never
    matches a same-named function of the path by accident."""
    words = re.findall(r'[\w./-]+', payload or '')
    if len(words) <= 1:
        return words
    return [w for w in words if any(c in w for c in '_./') or any(c.isupper() for c in w[1:])]


_SCAN_SKIP = frozenset(('.git', 'node_modules', '__pycache__', 'venv', '.venv', 'site-packages', 'build', 'dist'))
_SCAN_MAX_FILES = 20000


def _repo_py_files(root) -> list:
    """Repo-relative paths (posix) of the ``.py`` files under ``root``: the one code map of a CANNOT answer."""
    out = []
    for cur, dirs, files in os.walk(str(root)):
        dirs[:] = [d for d in dirs if d not in _SCAN_SKIP and not d.startswith('.')]
        for f in files:
            if f.endswith('.py'):
                out.append(os.path.relpath(os.path.join(cur, f), str(root)).replace(os.sep, '/'))
        if len(out) > _SCAN_MAX_FILES:
            break
    return out


def repo_scope_target(root, name: str, touch=(), kind='code'):
    """The repo file a CANNOT name means when it lies outside ``touch``: an existing file (path, or a name found in
    exactly one place) or a function/class defined in exactly one file; None when absent, ambiguous, already in the
    task or forbidden (gate.is_forbidden: privacy, tests of other rows, the factory's own code). Never raises."""
    try:
        name = (name or '').strip().strip('`\'"*()[]:;,').replace(chr(92), '/')
        while name.startswith('./'):
            name = name[2:]
        if not name:
            return None
        have = {str(t).replace(chr(92), '/') for t in touch}

        def usable(rel):
            return rel not in have and not gate.is_forbidden(rel, kind, touch)
        direct = Path(root) / name
        if '/' in name or name.endswith('.py') or name.startswith('.'):
            if not name.endswith('.py'):
                return None           # code files only: .env, keys, data and configs are never a scope
            if direct.is_file() and '..' not in name.split('/'):
                return name if usable(name) else None
            hits = [f for f in _repo_py_files(root) if f.endswith('/' + name) and usable(f)]
            return hits[0] if len(hits) == 1 else None
        if not re.fullmatch(r'[A-Za-z_]\w*(\.[A-Za-z_]\w*)*', name):
            return None
        leaf = name.rpartition('.')[2]
        rx = re.compile(r'^[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+' + re.escape(leaf) + r'\b', re.M)
        hits = []
        for rel in _repo_py_files(root):
            if rel not in have and gate.is_forbidden(rel, kind, touch):
                continue
            try:
                p = Path(root) / rel
                if p.stat().st_size < 1_000_000 and rx.search(p.read_text(encoding='utf-8', errors='replace')):
                    if rel in have:
                        return None   # defined in the task's own files: the model must look there, not widen
                    hits.append(rel)
            except OSError:
                continue
        return hits[0] if len(hits) == 1 else None
    except Exception:  # noqa: BLE001 - a widening is an extra: without it the CANNOT is judged as before
        return None


def _cannot_key(text: str, clean=lambda s: s) -> str:
    """A CANNOT text as one comparable key: words only, folded, cut where the feedback line cuts it."""
    return re.sub(r'\W+', ' ', clean(redact(text or ''))[:150]).strip().casefold()


def cannot_repeats(feedback, payload: str, clean=lambda s: s) -> bool:
    """True when the newest gate remark of the task is a CANNOT with the same text as ``payload`` (twice in a row)."""
    key = _cannot_key(payload, clean)
    if not key:
        return False
    for item in reversed(list(feedback or [])):
        text = str(item.get('text', '')) if isinstance(item, dict) else ''
        if not isinstance(item, dict) or item.get('source') != 'gate' or text.startswith(('[infra] ', REPEAT_MARK)):
            continue
        said = re.search(r'CANNOT:\s*(.*)', text, re.S)
        return bool(said) and _cannot_key(said.group(1), clean) == key
    return False


def outside_names(text: str, allowed: tuple) -> list:
    """The file names an answer's edit blocks aimed at outside ``allowed`` (file-name lines, REPLACE FUNCTION paths)."""
    names = []
    for line in (text or '').replace('\r\n', '\n').split('\n'):
        s = line.strip()
        head = _FUNC_HEAD.fullmatch(_func_clean(s)) if _FUNC_START.match(_func_clean(s)) else None
        name = head.group(1) if head else s
        if name and not name.startswith('```') and _light_target(name, allowed) == '':
            names.append(name.strip('`*#:').strip().replace(chr(92), '/'))
    return names


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


class _FuncTarget(str):
    """The 'search' part of a function block: the name (func or Class.method) of the definition to replace."""


class _Blocks(list):
    """The parsed blocks; ``problems`` = {why: count} of function blocks that could not be read (never applied)."""
    problems: dict


_NAME = r'[^\W\d]\w*'
_FUNC_START = re.compile(r'REPLACE\s+FUNCTION\b', re.I)
_FUNC_HEAD = re.compile(r'REPLACE\s+FUNCTION\s+(\S+)\s+(%s(?:\.%s)?)(?:\s*\(\s*\))?' % (_NAME, _NAME), re.I)
_FENCE = re.compile(r'\s*(`{3,})')
FUNC_SHAPE = 'REPLACE FUNCTION <path> <name>, then a ```python fence, the whole definition, a closing ``` line'


def _func_clean(line: str) -> str:
    return re.sub(r'[`*]', '', line).strip('#: \t')


def _function_block(lines: list, i: int, allowed: tuple):
    """Read the function block whose header is ``lines[i]``: ``(next line, file or None, block or None, problem or
    None, outside)``. A blank line between the header and the fence is fine; the fence closes on a whole line of at
    least as many backticks as it opened with."""
    head = _FUNC_HEAD.fullmatch(_func_clean(lines[i]))
    if head is None:
        return i + 1, None, None, 'a REPLACE FUNCTION line gave no block; shape: ' + FUNC_SHAPE, 0
    name = _light_target(head.group(1), allowed)
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    fence = _FENCE.match(lines[j]) if j < len(lines) else None
    if fence is None:
        return i + 1, name or None, None, 'REPLACE FUNCTION block without a ``` fence; shape: ' + FUNC_SHAPE, 0
    closing = re.compile(r'\s*`{%d,}\s*' % len(fence.group(1)))
    k = j + 1
    while k < len(lines) and not closing.fullmatch(lines[k]):
        k += 1
    if k >= len(lines):
        return len(lines), name or None, None, 'REPLACE FUNCTION block without a closing ``` line', 0
    if not name:
        return k + 1, None, None, None, 1
    body = lines[j + 1:k]
    if any(x.strip().startswith('<<<<<<<') and 'SEARCH' in x for x in body):
        return k + 1, name, ('inner', parse_edit_blocks('\n'.join(body), (name,))), None, 0
    return k + 1, name, (name, _FuncTarget(head.group(2)), '\n'.join(body)), None, 0


def parse_edit_blocks(text: str, allowed: tuple) -> tuple[list, int]:
    """``([(file, search, replace)], blocks for a file outside the task)``. The file of a block is the last
    file-name line before it; a block without one belongs to the only allowed file. An unterminated block is
    never applied; a function block that cannot be read is named in ``blocks.problems``."""
    lines = text.replace('\r\n', '\n').split('\n')
    blocks, outside, current, i = _Blocks(), 0, None, 0
    blocks.problems = {}
    while i < len(lines):
        s = lines[i].strip()
        if _FUNC_START.match(_func_clean(s)):
            i, name, got, why, out = _function_block(lines, i, allowed)
            outside += out
            if name:
                current = name
            if why:
                blocks.problems[why] = blocks.problems.get(why, 0) + 1
            if got is not None and got[0] == 'inner':
                blocks.extend(got[1][0])
                outside += got[1][1]
                for w, n in got[1][0].problems.items():
                    blocks.problems[w] = blocks.problems.get(w, 0) + n
            elif got is not None:
                blocks.append(got)
            continue
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
    """``text`` with the ONE occurrence of ``search`` replaced; None when it is absent or ambiguous."""
    return _replace_once_how(text, search, replace)[0]


def _replace_once_how(text: str, search: str, replace: str) -> tuple[str | None, str]:
    """``(new text or None, matcher)``. Matchers in order: 'exact' (whole lines), 'rstrip' (trailing spaces of
    lines ignored), 'shifted' (one common indent prefix), 'squeezed' (whitespace inside a line ignored, one place
    only), 'repair' (factory_patterns: a view line, a reflowed line). Ambiguous at a matcher: None, no later
    matcher is tried (a second place is a second place)."""
    hits = _line_hits(text, search)
    if len(hits) == 1:
        return text[:hits[0]] + replace + text[hits[0] + len(search):], 'exact'
    if len(hits) > 1:
        return None, ''
    lines = text.split('\n')
    want = [line.rstrip() for line in search.split('\n')]
    while want and not want[-1]:
        want.pop()
    while want and not want[0]:
        want.pop(0)
    if not want:
        return None, ''
    n = len(want)
    hits = [i for i in range(len(lines) - n + 1) if [line.rstrip() for line in lines[i:i + n]] == want]
    if len(hits) == 1:
        return '\n'.join(lines[:hits[0]] + replace.split('\n') + lines[hits[0] + n:]), 'rstrip'
    if hits:
        return None, ''
    shifted = _replace_shifted(lines, want, replace)
    if shifted is not None:
        return shifted, 'shifted'
    squeezed = _replace_squeezed(lines, want, replace)
    if squeezed is not None:
        return squeezed, 'squeezed'
    from .factory_patterns import repair     # ERROR_PATTERNS: a view line or a reflowed line, one place only
    fixed = repair(text, search, replace)
    return fixed, ('repair' if fixed is not None else '')


_COMMENT = chr(0)      # marks where a comment starts inside _squeeze
_DEF_HEAD = re.compile(r'(?:async\s+def|def|class)\s')


def _squeeze(line: str) -> str:
    """The line with the whitespace OUTSIDE string literals removed, but for one space kept between two word
    characters ('not x', 'return x' stay two words); a comment is cut and a trailing ':' dropped on a def/class
    line only. The literals stay exact, so two different code lines never collapse into one key."""
    out, quote, i, n = [], '', 0, len(line)
    while i < n:
        c = line[i]
        if quote:
            out.append(c)
            if c == '\\' and i + 1 < n:
                out.append(line[i + 1])
                i += 1
            elif c == quote:
                quote = ''
        elif c in '"\'':
            quote = c
            out.append(c)
        elif c == '#':
            out.append(_COMMENT)            # a comment start: kept as a marker, cut below on a def line only
            out.append(line[i:])
            break
        elif c in ' \t':
            j = i
            while j < n and line[j] in ' \t':
                j += 1
            if out and j < n and (out[-1][-1:].isalnum() or out[-1][-1:] == '_') and \
                    (line[j].isalnum() or line[j] == '_'):
                out.append(' ')
            i = j - 1
        else:
            out.append(c)
        i += 1
    key = ''.join(out)
    head = _DEF_HEAD.match(line.lstrip()) is not None
    code, mark, comment = key.partition(_COMMENT)
    if head:
        key = code.rstrip()
        return key[:-1].rstrip() if key.endswith(':') else key
    return code + ('#' + comment[1:] if mark else '')


_LITERAL = re.compile(r'''"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*\'''')


def _bracket_depth(line: str) -> int:
    """Brackets a code line opens minus the ones it closes (string literals and the comment left out)."""
    code = _LITERAL.sub('', line).partition('#')[0]
    return sum(code.count(c) for c in '([{') - sum(code.count(c) for c in ')]}')


def _replace_squeezed(lines: list, want: list, replace: str) -> str | None:
    """The SEARCH lines equal ONE place of the file once the whitespace inside each line is ignored (the file may be
    written compactly, 'f(a,b)', the model in PEP8, 'f(a, b)'); line breaks must agree. The REPLACE lines stay as the
    model wrote them, moved by the one indent difference of the place. None when there is no such place or more than
    one."""
    keys = [_squeeze(x) for x in want]
    if not any(keys):
        return None
    n = len(want)

    def lead(x):
        return x[:len(x) - len(x.lstrip(' \t'))]

    def shift_at(i):
        """The one indent difference of every code line of the place, or None when the lines disagree."""
        found, depth = None, 0
        for got, wanted in zip(lines[i:i + n], want):
            if not wanted.strip():
                continue
            delta = len(lead(got)) - len(lead(wanted))
            # <id> (replay 21.11): a continuation line of an open bracket is aligned by the model by eye, a column
            # off ('def f(a,' / '      b):'); its words are equal (the keys), only a statement line is pinned
            if found is not None and delta != found and depth <= 0:
                return None
            found = delta if found is None else found
            depth += _bracket_depth(got)
        return found

    places = [i for i in range(len(lines) - n + 1)
              if [_squeeze(x) for x in lines[i:i + n]] == keys and shift_at(i) is not None]
    if len(places) != 1:
        return None
    i = places[0]
    delta = shift_at(i)
    unit = lead(lines[i + next(j for j, x in enumerate(want) if x.strip())])[:1] or ' '
    out = []
    for x in replace.split('\n'):
        x = x.rstrip()
        if not x.strip():
            out.append('')
            continue
        out.append(unit * max(0, len(lead(x)) + delta) + x.lstrip(' \t'))
    return '\n'.join(lines[:i] + out + lines[i + n:])


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


_PARSE_ERRORS = (SyntaxError, ValueError, RecursionError, MemoryError)
_ELIDED = re.compile(r'\.\.\.|…|existing code|rest of|unchanged|omitted|same as (?:before|above)', re.I)


def _scan_text(new: str):
    """``(lines inside a multi-line string, comments)`` of a piece of Python, or None when it does not tokenize."""
    import io
    import tokenize
    inside, comments, stack = set(), [], []
    fstart, fend = getattr(tokenize, 'FSTRING_START', -1), getattr(tokenize, 'FSTRING_END', -1)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(new).readline):
            if tok.type == tokenize.STRING and tok.end[0] > tok.start[0]:
                inside.update(range(tok.start[0] + 1, tok.end[0] + 1))
            elif tok.type == fstart:
                stack.append(tok.start[0])
            elif tok.type == fend and stack:
                inside.update(range(stack.pop() + 1, tok.end[0] + 1))
            elif tok.type == tokenize.COMMENT:
                comments.append(tok.string)
    except (tokenize.TokenError, *_PARSE_ERRORS):
        return None
    return inside, comments


def _shifted(new: str, inside: set, pad: str) -> str:
    """``new`` with the margin of its first code line replaced by ``pad``. A line inside a multi-line string is
    never touched (its text is the value of the string); a blank line elsewhere becomes empty."""
    lines = new.split('\n')
    margin = next((x[:len(x) - len(x.lstrip())] for x in lines if x.strip()), '')
    out = []
    for n, x in enumerate(lines, 1):
        if n in inside:
            out.append(x)
        elif not x.strip():
            out.append('')
        else:
            k = 0
            while k < len(margin) and k < len(x) and x[k] in ' \t':
                k += 1
            out.append(pad + x[k:])
    return '\n'.join(out)


def _is_stub(node) -> bool:
    import ast
    body = node.body[1:] if (node.body and isinstance(node.body[0], ast.Expr)
                             and isinstance(node.body[0].value, ast.Constant)
                             and isinstance(node.body[0].value.value, str)) else node.body
    return all(isinstance(n, ast.Pass) or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                           and n.value.value is Ellipsis) for n in body)


def _ellipses(node) -> int:
    import ast
    return sum(1 for n in ast.walk(node) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
               and n.value.value is Ellipsis)


def _function_nodes(tree, target: str) -> list:
    import ast
    cls, _, leaf = target.rpartition('.')
    scopes = [n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls] if cls else [tree.body]
    return [n for body in scopes for n in body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == leaf]


def _all_defs(tree) -> list:
    """``[(qualified name, node, nested)]`` for every def of the file; ``nested`` is False for a top-level function and a
    method of a top-level class (those `_function_nodes` finds)."""
    import ast
    out = []

    def walk(body, path, kinds, direct):
        # kinds: what encloses this body ('class' / 'func'); direct: the body is the module's or a top-level class's own
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                top = direct and kinds in ((), ('class',))
                out.append(('.'.join(path + [n.name]), n, not top))
                walk(n.body, path + [n.name], kinds + ('func',), False)
            elif isinstance(n, ast.ClassDef):
                walk(n.body, path + [n.name], kinds + ('class',), direct)
            else:
                inner = [getattr(n, f, None) for f in ('body', 'orelse', 'finalbody')]
                inner += [h.body for h in (getattr(n, 'handlers', None) or [])]
                for block in inner:
                    if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                        walk(block, path, kinds, False)

    walk(tree.body, [], (), True)
    return out


def _replace_function(text: str, target: str, new: str, shown: str | None = None,
                      symbols=()) -> tuple[str | None, str]:
    """``(text with the one top-level function or Class.method replaced, '')`` or ``(None, reason)``. The new
    definition is re-indented to the old one and must parse as exactly one function of the same name. ``shown``:
    the text the model saw; the old definition must stand in it whole (a function shown in part or only in the
    outline is not replaced: the model would delete code it never read). Decorators the new text omits stay.
    ``symbols``: the qualified symbols of the part's contract; a method named without its class is taken only when
    the one def of that name is among them."""
    import ast
    if '\r' in text or '\r' in new:
        return None, "function '%s': a lone carriage return in the text" % target
    try:
        tree = ast.parse(text)
    except _PARSE_ERRORS:
        return None, "function '%s': the file does not parse" % target
    leaf = target.rpartition('.')[2]
    found = _function_nodes(tree, target)
    nested = as_method = False
    if not found:
        every = _all_defs(tree)
        if '.' not in target and symbols:   # W-vgs3 3: a method named without its class: the one def of that name,
            # when its qualified name is a symbol of the part's contract (Class.name / func.inner), is it
            bare = [(q, n) for q, n, _ in every if q.rpartition('.')[2] == leaf]
            if len(bare) == 1 and bare[0][0] in set(symbols):
                found, as_method = [bare[0][1]], True
    if not found:
        same_name = [(q, n) for q, n, deep in every if deep and (q == target or q.rpartition('.')[2] == leaf
                                                                  and (q.endswith('.' + target) or '.' not in target))]
        if len(same_name) == 1:
            found, nested = [same_name[0][1]], True
        elif same_name:
            return None, ("function '%s' is nested and named %d times: %s; use SEARCH/REPLACE on the shown lines"
                          % (target, len(same_name), ', '.join('%s (line %d)' % (q, n.lineno) for q, n in same_name)))
        else:
            import difflib
            names = sorted({q for q, _, _ in every} | {q.rpartition('.')[2] for q, _, _ in every})
            close = difflib.get_close_matches(target, names, n=5, cutoff=0.4)
            return None, ("function '%s' not found in the file%s; use SEARCH/REPLACE on the shown lines"
                          % (target, ' (similar real names: %s)' % ', '.join(close) if close else ''))
    if len(found) > 1:
        return None, "function '%s' is defined more than once" % target
    node = found[0]
    lines = text.split('\n')
    deco_first = min([node.lineno] + [d.lineno for d in node.decorator_list])
    old_whole = '\n'.join(lines[deco_first - 1:node.end_lineno])
    if shown is not None and old_whole not in shown:
        return None, ("function '%s' was not shown whole: use SEARCH/REPLACE on the shown lines or answer CANNOT: %s"
                      % (target, target))
    new = new.strip('\n')
    scanned = _scan_text(new)
    if scanned is None:
        return None, "new text of function '%s' does not parse" % target
    inside, comments = scanned
    try:
        parsed = ast.parse(_shifted(new, inside, ''))
    except _PARSE_ERRORS:
        return None, "new text of function '%s' does not parse" % target
    if len(parsed.body) != 1 or not isinstance(parsed.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None, "new text of function '%s' must define exactly one function" % target
    fresh_node = parsed.body[0]
    if fresh_node.name != leaf:
        return None, "new text of function '%s' defines another name (%s), not the same name" % (
            target, fresh_node.name)
    if (_is_stub(fresh_node) and not _is_stub(node)) or _ellipses(fresh_node) > _ellipses(node):
        return None, "new text of function '%s' elides code (... or pass): write every line" % target
    bad = next((c for c in comments if _ELIDED.search(c) and c not in old_whole), None)
    if bad is not None:
        return None, "new text of function '%s' elides code (comment %r): write every line" % (target, bad[:30])
    first = node.lineno if (node.decorator_list and not fresh_node.decorator_list) else deco_first
    head_line = lines[node.lineno - 1]
    pad = head_line[:len(head_line) - len(head_line.lstrip())]
    fresh = _shifted(new, inside, pad).split('\n')
    done = '\n'.join(lines[:first - 1] + fresh + lines[node.end_lineno:])
    try:
        again = ast.parse(done)
    except _PARSE_ERRORS:
        return None, "function '%s': the file does not parse after the replacement" % target
    if as_method:
        placed = [n for q, n, _ in _all_defs(again) if q.rpartition('.')[2] == leaf]
    elif nested:
        placed = [n for q, n, deep in _all_defs(again) if deep and q.rpartition('.')[2] == leaf
                  and (q == target or q.endswith('.' + target) or '.' not in target)]
    else:
        placed = _function_nodes(again, target)
    same = lambda n: (ast.dump(n.args), [ast.dump(x) for x in n.body], ast.dump(n.returns) if n.returns else '')
    if len(placed) != 1 or same(placed[0]) != same(fresh_node):
        return None, "function '%s': the file does not parse after the replacement" % target
    return done, ''


_MARKER_LINE = re.compile(r'#\s*factory-backlog-id:\s*\S.*')


def _marker_only(search: str, replace_text: str) -> bool:
    """SEARCH is exactly one ``# factory-backlog-id: ...`` line and the first line of REPLACE is the same line."""
    lines = [ln.strip() for ln in search.strip().splitlines()]
    if len(lines) != 1 or not _MARKER_LINE.fullmatch(lines[0]):
        return False
    first = replace_text.lstrip('\r\n').splitlines()[:1]
    return bool(first) and first[0].strip() == lines[0]


def ensure_test_marker(task, workdir: Path, changed) -> list[str]:
    """The model forgot the first line of a new test: the runner writes ``# factory-backlog-id: <ID>`` itself (after
    a shebang, in the file's own line ending). Another row's marker is never replaced (the gate refuses it). Only
    the first changed test file of the task is touched; returns the names written."""
    if getattr(task, 'kind', '') != 'unit_test' or not getattr(task, 'backlog_id', '') or gate.SELF_REPO:
        return []
    name = next((n for n in changed if n in task.tests), '')
    if not name:
        return []
    path = Path(workdir).joinpath(*name.split('/'))
    try:
        raw = path.read_bytes().decode('utf-8')
    except (OSError, UnicodeDecodeError):
        return []
    bom, body = ('﻿', raw[1:]) if raw.startswith('﻿') else ('', raw)
    mark = '# factory-backlog-id: ' + task.backlog_id
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if lines and lines[0].startswith('#!'):
        lines = lines[1:]
    if lines and lines[0].startswith('# factory-backlog-id:'):
        return []                       # right already, or another row's marker: the gate decides
    eol = '\r\n' if '\r\n' in body else '\n'
    parts = body.splitlines(keepends=True)
    at = 1 if parts and parts[0].startswith('#!') else 0
    if at and not parts[0].endswith('\n'):
        parts[0] += eol
    parts.insert(at, mark + eol)
    try:
        path.write_bytes((bom + ''.join(parts)).encode('utf-8'))
    except OSError:
        return []
    return [name]


def apply_edit_blocks(workdir: Path, blocks, shown: str | None = None, symbols=None) -> tuple[list[str], dict]:
    """Apply the blocks inside ``workdir`` (the file names come from the task, never from the model):
    ``(changed files, {failure: count})``. All or nothing: when one block fails no file is written (half a
    candidate could pass weak tests; the failure note goes to the next attempt). A CRLF file stays CRLF. ``shown``:
    the prompt the model saw (LF); a function block is applied only to a definition that stands in it whole.
    ``symbols``: {file: [contract symbols]} for a method named without its class."""
    failed, texts, crlf, how, done, repeats = {}, {}, {}, [], set(), 0

    def fail(why):
        failed[why] = failed.get(why, 0) + 1

    for name, search, replace_text in blocks:
        key = (name, str(search), replace_text, isinstance(search, _FuncTarget))
        if key in done and name in texts and _repeat_is_done(texts[name], search, replace_text):
            repeats += 1        # the same block again (thought and answer, <id>): applied once, not twice, not a failure
            continue
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
        if isinstance(search, _FuncTarget):
            new, why = _replace_function(text, str(search), replace_text, shown, (symbols or {}).get(name) or ())
            if new is None:
                fail(why)
                continue
        elif not search.strip():
            if text.strip():
                fail('empty SEARCH on a file that is not empty')
                continue
            new = replace_text if replace_text.endswith('\n') else replace_text + '\n'
        elif not text.strip() and _marker_only(search, replace_text):
            # the file does not exist yet and the model repeated the marker line as SEARCH: that is a creation
            new = replace_text if replace_text.endswith('\n') else replace_text + '\n'
        else:
            new, matcher = _replace_once_how(text, search, replace_text)
            if new is None:
                fail('SEARCH not found exactly once')
                continue
            how.append(matcher)
        texts[name] = new
        done.add(key)
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
    applied = _Applied(applied)
    applied.matchers = how           # telemetry: which matcher placed each SEARCH/REPLACE block
    applied.repeats = repeats
    return applied, failed


def _repeat_is_done(text: str, search, replace: str) -> bool:
    """True when a block that was already applied once, met again, would only redo itself: its SEARCH is gone and its
    REPLACE stands in the file, or the one place its SEARCH is found lies inside the REPLACE already written (an
    anchor -> anchor + line block). A repeat whose SEARCH stands at another place is a second change and is applied."""
    if isinstance(search, _FuncTarget):     # the same whole definition again: done while it still stands in the file
        want = [line.strip() for line in replace.strip('\n').split('\n')]   # (indent-free: a method is re-indented)
        have = [line.strip() for line in text.split('\n')]
        return any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1))
    hits = _line_hits(text, search) if search.strip() else []
    if not hits:
        return not replace.strip() or bool(_line_hits(text, replace)) or replace in text
    at = replace.find(search)
    return at >= 0 and any(h >= at and text[h - at:h - at + len(replace)] == replace for h in hits)


class _Applied(list):
    """The changed files; ``matchers``: the matcher that placed each block (see _replace_once_how); ``repeats``: blocks
    met again after they were applied, skipped (see _repeat_is_done)."""
    matchers: list = []
    repeats: int = 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is an error, never followed: urllib would resend the Authorization header to the new host (critic
    19.11), so the key could reach a third party."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_LIGHT_OPENER = urllib.request.build_opener(_NoRedirect)


def _with_retry_after(raw: bytes, header) -> bytes:
    """<id>: the Retry-After header (seconds) of an error answer travels in the body as ``_retry_after``, where
    classify() reads it; a date or garbage is ignored, a body that is not JSON is wrapped."""
    try:
        seconds = float(str(header).strip())
    except (TypeError, ValueError):
        return raw
    if not 0 < seconds <= 3600:
        return raw
    try:
        body = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        body = None
    if isinstance(body, dict):
        body['_retry_after'] = seconds
    elif isinstance(body, list) and len(body) == 1 and isinstance(body[0], dict):
        body = dict(body[0], _retry_after=seconds)
    else:
        body = {'error': {'message': (raw or b'')[:300].decode('utf-8', 'replace')}, '_retry_after': seconds}
    return json.dumps(body).encode('utf-8')


def _light_post(url: str, key: str, body: dict, timeout: float) -> tuple[int | None, bytes]:
    """(HTTP status or None, body) within ``timeout`` seconds IN TOTAL: urllib's timeout is per socket operation
    (connect, each read), so a slow answer lived far longer than asked (live 23.11: 87 s and 180 s for a 30 s limit).
    The key travels only in the Authorization header, never in a log."""
    box = []
    worker = threading.Thread(target=lambda: box.append(_light_post_once(url, key, body, timeout)), daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive() or not box:
        return None, b'TimeoutError'       # the late answer, if it ever comes, is dropped
    return box[0]


def _light_post_once(url: str, key: str, body: dict, timeout: float) -> tuple[int | None, bytes]:
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    try:
        with _LIGHT_OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        try:
            return error.code, _with_retry_after(error.read(), error.headers.get('Retry-After') if error.headers else None)
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


def _missing_blocks_note(workdir: Path, blocks, shown: str | None = None) -> str:
    """Per failed block: where its SEARCH missed and the closest real line. First, right after the counts (the note
    is cut at 300 characters): every definition a failed block aimed at that ``shown`` (the prompt) did not show
    whole, in the form asked_names reads, so the next candidate and the next pass are shown it first and whole."""
    from .factory_patterns import aimed_definition
    parts, asks = [], []
    seen = {x.strip() for x in (shown or '').replace('\r\n', '\n').split('\n')} if shown is not None else None
    for i, (name, search, replace_text) in enumerate(blocks, 1):
        if not search.strip() or isinstance(search, _FuncTarget):
            continue
        try:
            path = Path(workdir).joinpath(*name.split('/'))
            raw = path.read_bytes().decode('utf-8') if path.is_file() else ''
            text = raw.replace('\r\n', '\n')
        except (OSError, UnicodeDecodeError):
            continue
        if _replace_once(text, search, replace_text) is not None:
            continue
        aim = aimed_definition(text, search) if seen is not None else None
        if aim and not all(x.strip() in seen for x in aim[1] if x.strip()) and aim[0] not in asks:
            asks.append(aim[0])
        if len(parts) >= 2:
            continue                       # two blocks are named; the aims of the others are still asked for
        where = 'in the file more than once' if len(_line_hits(text, search)) > 1 else 'not in the file'
        have = {x.strip() for x in text.split('\n')}
        wanted = [x.strip() for x in search.split('\n') if x.strip()]
        first = next((x for x in wanted if x not in have), wanted[0] if wanted else '')[:80]
        part = "block %d (%s) SEARCH is %s: '%s'" % (i, name, where, first)
        # a guessed line (14 of the 56 no-change passes of the night 19-20.11): the real line it most looks like, so
        # the next attempt copies that one instead of guessing again; only a close look-alike is named
        close = difflib.get_close_matches(first, [x for x in have if x], n=1, cutoff=0.75) if first and \
            where == 'not in the file' else []
        if close:
            part += ", the closest line there: '%s'" % close[0][:100]
        parts.append(part)
    return ''.join('; ' + p for p in ["function '%s' was not shown whole" % a for a in asks[:3]] + parts)


_NO_FILE_ANSWER = re.compile(r"^\W*(?:cannot|can't|could not|unable to)\s+find\s+the\s+file\b|"
                             r"^\W*(?:the\s+)?file\b[^\n]{0,80}\b(?:not provided|was not provided|is not provided)\b", re.I)


_FIRST_BLOCK = re.compile(r'(?m)^[ \t]*(?:<{5,}[ \t]*SEARCH|REPLACE FUNCTION\b)')


def answer_cannot(text: str) -> str | None:
    """What a CANNOT answer says, None for no CANNOT. A 'CANNOT:' line counts anywhere BEFORE the first edit block (the
    card format puts '# WHY: ...' first: 14 of 29 block-less answers 26-27.11 had CANNOT on the second line); a line
    "Cannot find the file ..." / "file not provided" there is a CANNOT too. A line inside a block is code, never a
    CANNOT (a cut answer whose REPLACE holds '# cannot: ...' stays a cut answer, <id>)."""
    text = text or ''
    first = _FIRST_BLOCK.search(text)
    head = text[:first.start()] if first else text
    said = _CANNOT_LINE.search(head)
    if said:
        return head[said.end():].strip()
    return next((line.strip() for line in head.splitlines() if _NO_FILE_ANSWER.match(line)), None)


def said_cannot(note: str, text: str) -> str | None:
    """The CANNOT text of the last coder attempt: from the light engine's note ('... CANNOT: x'), else the first line
    of the answer's own CANNOT (answer_cannot: the one parse of a model's CANNOT); None for no CANNOT."""
    said = re.search(r'CANNOT:\s*(.*)', note or '')
    if said:
        return said.group(1)
    found = answer_cannot(text)
    return None if found is None else (found.split('\n') or [''])[0]


def _light_note(total: int, applied: list, failed: dict, outside: int, text: str) -> str:
    """One line for the next attempt's feedback: what happened to the edit blocks (no file text)."""
    if not total:
        said = answer_cannot(text)
        if said is not None:
            return 'the model answered CANNOT: ' + redact(said)[:150]   # reject() scrubs paths
        return 'the answer had no SEARCH/REPLACE edit block (nor a REPLACE FUNCTION block)'
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


CANDIDATE_TEMPERATURES = (0.2, 0.5, 0.8)   # <id>: every tournament candidate samples differently, not the same answer again


def candidate_temperature(k: int) -> float:
    return CANDIDATE_TEMPERATURES[min(max(0, int(k)), len(CANDIDATE_TEMPERATURES) - 1)]


def light_attempt(task: Task, workdir: Path, model: str, timeout: int = LIGHT_TIMEOUT_S,
                  *, prompt_override: str | None = None, steps: int | None = None,
                  key_env: str | None = None, post=None, temperature: float = 0.2) -> tuple[int, bytes, bytes]:
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
    if channels.prompt_too_big(prompt):
        return 125, b'', b'context-too-large'
    key = os.environ.get(key_env or {'openrouter': 'OPENROUTER_API_KEY', 'google': 'GOOGLE_GENERATIVE_AI_API_KEY'}.get(provider, ''), '')
    if not key:
        return 1, _light_error(401, b'{"error": {"message": "no API key in the environment"}}'), b''
    review = not task.touch_files
    body = {'model': model_id, 'max_tokens': channels.max_output_for(model, LIGHT_MAX_OUTPUT),
            'temperature': 0 if review else temperature,
            'messages': [{'role': 'system', 'content': LIGHT_REVIEW_RULES if review else light_rules(task, workdir)},
                         {'role': 'user', 'content': prompt}]}
    if provider == 'openrouter' and channels.supports_reasoning(model):    # D #24: only where the model takes it
        body['reasoning'] = {'max_tokens': LIGHT_REASONING_TOKENS}
    status, raw, sent = channels.post_with_extra(post or _light_post, url, key, body,
                                                 max(10, min(int(timeout), LIGHT_TIMEOUT_S)), model)
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
        text = strip_thought(content)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return 1, _light_error(None, b'unreadable answer', 'UnreadableAnswer'), b''
    if choice.get('finish_reason') in ('length', 'max_tokens') and text and answer_cannot(text) is None:
        # <id>: an answer cut by the output limit is a half edit: never applied, never judged; the next candidate is told
        return 1, _light_error(None, b'the answer was cut by the output limit', 'TruncatedAnswer'), b''
    if not text and choice.get('finish_reason') in ('length', 'max_tokens'):
        # the whole output limit went into reasoning (Gemma 4, live 20.11: 13 of 16 coder calls since midnight, ~100 s
        # each; reasoning_effort 'none' is refused (400), 'minimal' is accepted: MODEL_BODY sends it): no answer from
        # this model now, another one is asked
        return 1, _light_error(None, b'the model used its whole output limit and gave no answer', 'EmptyAnswer'), b''
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
        problems = dict(getattr(blocks, 'problems', {}))
        if problems:      # a function block that could not be read is half a candidate: nothing is applied
            applied, failed = [], problems
        else:
            part_symbols = {}
            for part in K.contract_of(task).get('parts') or []:
                if isinstance(part, dict) and part.get('file'):
                    part_symbols.setdefault(part['file'], []).extend(part.get('symbols') or [])
            applied, failed = apply_edit_blocks(Path(workdir), blocks, prompt.replace('\r\n', '\n'), part_symbols)
        events.extend({'type': 'tool_use', 'part': {'tool': 'edit', 'state': {'input': {'filePath': n}}}}
                      for n in applied)
        note = _light_note(len(blocks) + outside + sum(problems.values()), applied, failed, outside, text)
        if 'squeezed' in getattr(applied, 'matchers', ()):
            note += '; matcher: whitespace-tolerant x%d' % applied.matchers.count('squeezed')
        if getattr(applied, 'repeats', 0):
            note += '; repeated block applied once x%d' % applied.repeats
        if failed.get('SEARCH not found exactly once'):
            note += _missing_blocks_note(Path(workdir), blocks, prompt)
            from .factory_patterns import hints as pattern_hints
            note += ''.join('; ' + h for h in pattern_hints(blocks))
        if not applied:
            _keep_answer(Path(workdir), text)
    events.append({'type': 'text', 'part': {'text': text}})
    finish = {'reason': choice.get('finish_reason') or 'stop', 'tokens': tokens}
    if sent.get('reasoning_effort'):
        finish['reasoning'] = sent['reasoning_effort']      # telemetry: the effort field went with the call
    events.append({'type': 'step_finish', 'part': finish})
    return 0, ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events).encode('utf-8'), note.encode('utf-8')


class _SerialLease:
    """The pass's lease for threads: the parts of one card call the router at once, and every transaction on the
    checkpoint (the booking of a channel, the account of a call) runs one at a time under the lock of the process,
    so two threads never spend the same free request."""

    def __init__(self, lease):
        self._lease, self._lock = lease, threading.RLock()

    def __getattr__(self, name):
        return getattr(self._lease, name)

    def commit(self, fn):
        with self._lock:
            return self._lease.commit(fn)

    def read(self):
        with self._lock:
            return self._lease.read()


_PART_FAILED = re.compile(r'; \d+: |block\(s\) for a file outside')


NO_CHANGE_NOTE = 'your edit did not change the file'
_APPLIED_NOTE = re.compile(r'changed files [1-9]')


def part_failure(note: str, changed: bool) -> str:
    """Why the answer for one part cannot be used ('' when it can): nothing changed, or a block of it did not apply.
    An answer that changed nothing always says so first (W-ctx 2): blocks that 'applied' with a REPLACE equal to the
    SEARCH (live 23.11: 'edit blocks 1, changed files 1' and an unchanged file) are the same code returned."""
    if not changed:
        if _APPLIED_NOTE.search(note or ''):
            return NO_CHANGE_NOTE + ': the REPLACE lines are the same as the SEARCH lines. Make the change the instruction asks for'
        return NO_CHANGE_NOTE + ((' (' + note + ')') if note else '')
    if _PART_FAILED.search(note or ''):
        return note
    return ''


OFF_CONTRACT_NOTE = ('your edit changed code the contract does not name: %s. For this file the contract allows only: %s. '
                     'Change only those and keep every other line as it is')


def part_off_contract(parts: list, file: str, old_text: str, new_text: str) -> str:
    """W-ctx 4: '' when the edit of ``file`` stays inside the contract (the functions of its parts; a new function where
    the contract says 'add after'), else the note for the part's next ask: what went outside and what is allowed."""
    if not file.endswith('.py'):
        return ''
    mine = [p for p in parts if p.get('file') == file]
    names = K.changed_symbols(old_text, new_text)
    if any(p.get('add_after') for p in mine):
        names -= K.defined(new_text) - K.defined(old_text)
    off = K.contract_conformance({file: names}, {'parts': mine})
    if not off:
        return ''
    allowed = sorted({s for p in mine for s in p.get('symbols') or []}) or ['(the whole file)']
    return OFF_CONTRACT_NOTE % (', '.join(o.partition(': ')[2] or o for o in off), ', '.join(allowed))


STALE_MARK = 'reslice:stale'
_CANNOT_NOT_THERE = re.compile(r'CANNOT:.*does not contain', re.S | re.I)


UNDEF_RETRIES = 1      # re-asks of one part for a new undefined name that cost no PART_RETRIES try (W-see 4)


def part_undefined(file: str, old_text: str, new_text: str, root=None) -> str:
    """W-see 4: '' when the edit of ``file`` brings no new undefined name (ruff, the undefined-name rules: names the base
    did not have; no ruff: no check), else the note for the part's next ask."""
    if not file.endswith('.py'):
        return ''
    names = K.new_undefined_names(old_text, new_text)
    if not names:      # W-true2 1: a NEW call no definition of its name accepts (the same re-ask path, no strike)
        bad = FC.new_bad_calls(file, old_text, new_text, root)     # the definitions of the tree the file belongs to (the product snapshot)
        return 'your edit has a call the project does not accept: ' + ' | '.join(bad[:4]) if bad else ''
    return K.UNDEFINED_NOTE % (file, ', '.join(names[:8]))


VGS_ON = True         # W-vgs: the ensemble of the small tier (tests of other features switch it off)
VGS_K_MAX = 6
EDIT_EST = 3000     # fac-pace: tokens one Gemma edit reserves (26.11 telemetry: median 2.4K, mean 3.0K, <id> 4.8K; was 8000)
VGS_ALTS = 2          # the unions after the first one that may still go to the gates in a pass (3 gates in all)


def vgs_input_key(task: Task) -> str:
    """W-a2: the fingerprint of the ensemble's input (the card's contract): a pass with no answer at all is deferred under
    it, and the same input that got no answer ESCALATE_AFTER - 1 times in a row is not asked of the ensemble again."""
    contract = json.dumps(K.contract_of(task), sort_keys=True, ensure_ascii=False, default=str)
    return 'vgs0:' + sha256((task.id + '|' + contract).encode('utf-8', 'replace')).hexdigest()[:16]


class VgsPlan:
    """W-vgs 3: what edit_parts needs for the ensemble: ``k``, the channel names, ``ask(part_task, folder, text, n,
    temperature, channel)`` -> ``(rc, out, err)`` (raises ENS.ChannelRefused for a refused channel), and the pass's
    telemetry (``stats``) with the alternates for the gates (``alts``: (file, bytes) pairs, best first)."""

    def __init__(self, k: int, ask, channel_names=None, capacity=None):
        self.k, self.ask, self.channels = int(k), ask, list(channel_names or [])
        self.capacity = capacity      # W-a2: the head's free small places (ENS.Ensemble ``capacity``), None: no head
        self.input_key = ''           # W-a2: vgs_input_key of the card: a pass with no answer is deferred under it
        self.stats = dict(k=0, asked=0, answered=0, valid=0, unique=0, votes_top=0, retries_503=0)
        self.alts: list = []          # (file, bytes, model) of the next unions, best first
        self.winners: set = set()     # the models that wrote the standing candidate's parts
        self.lock = threading.Lock()

    def record(self, stats: dict) -> None:
        with self.lock:
            for name in ('asked', 'answered', 'valid', 'unique', 'retries_503'):
                self.stats[name] += int(stats.get(name) or 0)
            self.stats['k'] = max(self.stats['k'], int(stats.get('k') or 0))
            self.stats['votes_top'] = max(self.stats['votes_top'], int(stats.get('votes_top') or 0))


DAY_HOPS = 8


def past_day_limit(ask):
    """``ask()``, again at once while a channel refuses with its DAY limit: the refusal closed that channel (its mark is set), so the
    next ask takes another one. A day limit of one channel is not the end of the review or of the edit."""
    for n in range(DAY_HOPS):
        try:
            return ask()
        except ChannelFault as error:
            if (error.info or {}).get('kind') != 'rate_day' or n + 1 >= DAY_HOPS:
                raise


def part_verifier(parts: list, file: str, root=None):
    """W-vgs 2: the code plugin of the ensemble: ``verify(answer)`` -> ``(ok, why, key)`` over the answer of one call
    (``rc``, ``note``, ``raw``/``new`` = the file after the blocks, ``old_raw``/``old`` = before). The blocks were parsed
    for the allowed file only and applied by the light engine; here: the part is applied, compiles, brings no new
    undefined name, stays inside the contract and changes something. The key is the fingerprint of the new file."""
    def verify(answer: dict):
        if answer.get('rc'):
            return False, 'the call failed', ''
        new, old = answer.get('new'), answer.get('old') or ''
        changed = new is not None and answer.get('raw') != answer.get('old_raw')
        why = part_failure(answer.get('note') or '', changed)
        if not why and file.endswith('.py'):
            try:
                compile(new, file, 'exec')
            except (SyntaxError, ValueError) as error:
                why = 'its edit of %s does not compile (%s)' % (file, error)
        if not why:
            try:
                why = part_off_contract(parts, file, old, new) or part_undefined(file, old, new, root)
            except (OSError, ValueError, SyntaxError):
                why = ''
        return (False, why, '') if why else (True, '', ENS.fingerprint(new, file))
    return verify


def vgs_alternates(per_part: dict) -> list:
    """W-vgs 3: the unions after the first one: the part with the fewest votes takes its next valid candidate, then the
    next one. ``per_part``: file -> candidates (best first), only for files of exactly one part. Up to VGS_ALTS (file, bytes)."""
    order = sorted((f for f, c in per_part.items() if len(c) > 1), key=lambda f: (per_part[f][0].votes, f))
    out: list = []
    for f in order:
        for cand in per_part[f][1:]:
            out.append((f, cand.payload['raw'], cand.payload.get('model')))
            if len(out) >= VGS_ALTS:
                return out
    return out


def edit_parts(task: Task, parts: list, workdir: Path, call, failing: str = '', use_code: bool = False,
               trace=(), fail_ids=(), info=None, on_event=None,
               who=None, vgs: VgsPlan | None = None, root=None, previous=None) -> tuple[int, str, str]:
    """Edit the parts of the contract in ``workdir``: one call per part (``call(part_task, directory, prompt)`` ->
    ``(rc, stdout, stderr)``), the parts of one stage at once (one thread and one HTTP call per part), the next stage
    when all parts of the previous one are applied. Each part works in its own copy ``<workdir>-p<i>-<try>``; its
    file goes into ``workdir`` when the answer applied. A part whose answer cannot be applied (no block, SEARCH not
    found, CANNOT) is asked again, only that part, up to PART_RETRIES times with the reason; the other parts of the
    stage neither wait nor repeat. ``(0, answers, '')`` when every part applied, else ``(1, answers, evidence)``:
    the CANNOT text or the SEARCH miss of the part that stayed unapplied. ``use_code`` (the first attempt of the
    executor, W-hard 3): a part that carries ``code`` (the whole new text of each named function, or a SEARCH/REPLACE
    block for a file that is not .py) is applied from it WITHOUT a model, under the same checks as a model's answer
    (it changes something, only what the contract names); a part whose code cannot be applied goes to the model with
    the exact reason. W-see: every card also carries a context pack (K.context_pack: the red test and what the code
    reads; ``trace`` = the failing path, ``fail_ids`` = the red test ids); ``info`` (a dict) gets ``context_chars`` and
    ``context_sections``; ``on_event(name)`` hears the re-ask for a new undefined name. J4-cards: ``previous`` =
    (feedback, diff) of the attempt rejected before this one; every card of a repeat carries it (retry_evidence)."""
    workdir = Path(workdir)
    answers: list[str] = []
    lock = threading.Lock()
    contract = K.contract_of(task)
    test_ids = [str((contract.get('test') or {}).get('use') or '')] + [str(i) for i in fail_ids or ()] + list(task.tests or ())
    test_ids = [t for t in test_ids if t]
    notify = on_event or (lambda name: None)

    def again(file):
        """The previous attempt's rejection and its diff of ``file`` (a repeat only)."""
        return retry_evidence(previous[0], previous[1], file) if previous else ''

    def with_context(file, part, header, region, sigs, base):
        """``base`` (the card with no pack) and the card with the pack of this part: the pack fills what is left up to
        SMALL_PROMPT_TOKENS for a card that fits it (a short card stays a Gemma card), else up to 6000 characters, always
        inside the prompt limit."""
        limit = channels.PROMPT_LIMIT_CHARS - len(PART_RETRY_NOTE % ('x' * 300))

        def tokens(n, text):
            return channels.estimate_tokens(n, 0, overhead=LIGHT_OVERHEAD_TOKENS, cyrillic=channels.cyrillic_share(text))
        if tokens(len(base), base) < channels.SMALL_PROMPT_TOKENS:
            budget = (channels.SMALL_PROMPT_TOKENS - tokens(len(base), base)) * 3
        else:
            budget = 6000
        budget = min(budget, PACK_CHARS_MAX, limit - len(base) - 2)     # fac-pace: the pack no longer grows to fill the window
        for _ in range(5):
            if budget < 300:
                return base, ''
            pack = K.context_pack(workdir, part, region, test_ids=test_ids, trace=trace, budget=budget,
                                  clean=lambda text: redact(text))
            if not pack:
                return base, ''
            card = K.part_prompt(file, part, header, region, failing=failing, signatures=sigs, limit=limit, context=pack,
                                 previous=again(file))
            if tokens(len(base), base) >= channels.SMALL_PROMPT_TOKENS or \
                    tokens(len(card), card) <= channels.SMALL_PROMPT_TOKENS:
                return card, pack
            budget = int(budget * 0.7)
        return base, ''

    def apply_code(index: int, part: dict) -> str:
        """'' when ``part['code']`` was applied to the file in ``workdir``; else the exact reason it was not."""
        file = part['file']
        folder = workdir.parent / ('%s-c%d' % (workdir.name, index))
        shutil.rmtree(folder, ignore_errors=True)
        with lock:
            shutil.copytree(workdir, folder)
        try:
            try:
                if gate.is_rig_task(task) and isinstance(part.get('file_text'), str):
                    # W-rig fix2: a rig card carries the whole verified file; it is written as it is (bytes: CRLF stays)
                    blocks = None
                elif file.endswith('.py') and '<<<<<<< SEARCH' not in part['code']:
                    # W-optim 3: a function that moved since the architect's read is not a refusal and not a reslice: the
                    # replacement is applied by name onto the fresh snapshot and the gates judge it
                    blocks = [(file, _FuncTarget(symbol), text)
                              for symbol, text in K.split_part_code(part['code'], part.get('symbols') or [])]
                else:
                    blocks, outside = parse_edit_blocks(part['code'], (file,))
                    if outside or not blocks or getattr(blocks, 'problems', None):
                        return 'the code block is not a SEARCH/REPLACE block of ' + file
            except (ValueError, OSError) as error:
                return str(error)
            if blocks is None:
                try:
                    (folder / file).parent.mkdir(parents=True, exist_ok=True)
                    (folder / file).write_bytes(part['file_text'].encode('utf-8'))
                except OSError as error:
                    return str(error)
            else:
                applied, failed = apply_edit_blocks(folder, blocks, None, {file: part.get('symbols') or []})
                if failed:
                    return '; '.join(sorted(failed))
            target, before = folder / file, workdir / file
            with lock:
                changed = target.is_file() and (not before.is_file() or target.read_bytes() != before.read_bytes())
            reason = part_failure('', changed)
            # fac-69: code PROVEN green in the cloud (the contract's proof) has the FILE of the part as its border (the only
            # file apply_code writes), not the list of symbols (live 27.11: 14 refusals of proven code); code without that
            # proof (an architect's own) keeps the symbol check
            if not reason and not proven_code(task):
                try:
                    reason = part_off_contract(parts, file, before.read_text(encoding='utf-8-sig', errors='replace')
                                               if before.is_file() else '',
                                               target.read_text(encoding='utf-8-sig', errors='replace'))
                except (OSError, ValueError):
                    reason = ''
            if not reason:
                try:
                    reason = part_undefined(file, before.read_text(encoding='utf-8-sig', errors='replace')
                                            if before.is_file() else '', target.read_text(encoding='utf-8-sig', errors='replace'), root)
                except (OSError, ValueError):
                    reason = ''
            if reason:
                return reason
            with lock:
                before.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, before)
            return ''
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def current_texts() -> dict:
        """The files of the parts as they are in ``workdir`` NOW: the parts of an earlier stage are already applied."""
        with lock:
            return {p['file']: (workdir / p['file']).read_text(encoding='utf-8-sig', errors='replace')
                    for p in parts if (workdir / p['file']).is_file()}

    per_part: dict = {}      # file -> the valid candidates of its ensemble (best first)

    def ensemble_part(index: int, part: dict, part_task, text: str) -> str:
        """W-vgs 3: k independent asks of one part at once, each checked by the code plugin before anything else; the
        best candidate is written into ``workdir``. '' when one stands, else the commonest reason the answers failed."""
        file = part['file']
        target_now = workdir / file
        with lock:
            old_raw = target_now.read_bytes() if target_now.is_file() else None
        old = old_raw.decode('utf-8-sig', 'replace') if old_raw is not None else ''
        ens_t0 = [time.monotonic()]

        def ask(n: int, temperature: float, channel, ens_t0=ens_t0):     # bound per part: a branch of an earlier part keeps its own start
            folder = workdir.parent / ('%s-p%d-e%d' % (workdir.name, index, n))
            shutil.rmtree(folder, ignore_errors=True)
            with lock:
                shutil.copytree(workdir, folder)
            try:
                # fac-68: a ticket not sent before the ensemble's term ends expires in the head unsent (no quota, no tokens spent
                # for an answer nobody reads): the head's wait is what is left of the ensemble's own term
                _ENS_LEFT.left = lambda t0=ens_t0: max(0.0, t0[0] + ENS.TOTAL_S - time.monotonic())
                rc, out, err, *rest = vgs.ask(part_task, folder, text, n, temperature, channel)
                made = folder / file
                raw = made.read_bytes() if made.is_file() else None
                with lock:
                    answers.append(event_summary(out)['text'] if rc == 0 and out else '')
                return dict(rc=rc, note=err.decode('utf-8', 'replace') if isinstance(err, bytes) else str(err or ''),
                            raw=raw, new=raw.decode('utf-8-sig', 'replace') if raw is not None else None,
                            old_raw=old_raw, old=old, model=rest[0] if rest else None)
            finally:
                shutil.rmtree(folder, ignore_errors=True)

        ens = ENS.Ensemble(vgs.k, ask, part_verifier(parts, file, root), channels=vgs.channels, capacity=vgs.capacity)
        ens_t0[0] = time.monotonic()
        found = ens.run()
        vgs.record(ens.stats)
        if not found and not ens.stats.get('answered') and not ens.rejected:
            # W-vgs3 1: not one answer of a model (channel refusals, the term): the channel's fault, not the part's
            raise ChannelFault({'kind': 'transient', 'ensemble_no_answer': True, 'input_key': vgs.input_key or vgs_input_key(task)})
        if not found:
            seen: dict = {}
            for why in ens.rejected:
                seen[why] = seen.get(why, 0) + 1
            return max(seen, key=seen.get) if seen else 'no answer'
        with lock:       # the payload of a candidate is its answer: ``raw`` = the bytes of the new file
            target_now.parent.mkdir(parents=True, exist_ok=True)
            target_now.write_bytes(found[0].payload['raw'])
            if found[0].payload.get('model'):
                vgs.winners.add(found[0].payload['model'])
            if sum(1 for p in parts if p.get('file') == file) == 1:
                per_part[file] = found
        return ''

    def one(index: int, part: dict):
        file = part['file']
        texts = current_texts()
        source = texts.get(file, '')
        # fac-69: ready code is applied BEFORE the part is shown to anyone: no region, no region cap, no model
        ready_file = gate.is_rig_task(task) and isinstance(part.get('file_text'), str)
        more = ''
        if ready_file or (use_code and isinstance(part.get('code'), str) and part['code'].strip()):
            why_not = apply_code(index, part)
            if not why_not:
                if info is not None:
                    with lock:
                        info['code_applied'] = info.get('code_applied', 0) + 1
                return ''
            if ready_file:
                return '%s: the ready file could not be written (%s)' % (file, why_not[:300])
            more = ('\nThe architect wrote code for this part; it could not be applied (%s). Make the change the '
                    'instruction asks for.\n' % why_not[:300])
        try:
            header, region = K.part_region(source, part.get('symbols') or [], part.get('anchor') or '')
        except (ValueError, SyntaxError) as error:     # the code is not what the contract describes
            return '%s: the part cannot be shown (%s)' % (file, error)
        said =' '.join(str(part.get(k, '')) for k in ('instruction', 'keep'))
        names = set(re.findall(r'[^\W\d]\w*', said))
        sigs = K.signatures({f: t for f, t in texts.items() if f != file}, names)
        part_task = replace(task, touch_files=(file,), read_files=tuple(
            n for n in task.read_files if n != file) + tuple(n for n in task.touch_files if n != file))
        prompt_limit = channels.PROMPT_LIMIT_CHARS - len(PART_RETRY_NOTE % ('x' * 300))
        base = K.part_prompt(file, part, header, region, failing=failing, signatures=sigs, limit=prompt_limit,
                             previous=again(file))
        try:
            base, pack = with_context(file, part, header, region, sigs, base)
        except Exception:       # noqa: BLE001 - an addition to the card: without it the card is as before
            pack = ''
        if pack and pack.split('\n', 1)[0] not in base:
            pack = ''
        if info is not None:
            with lock:
                info['context_chars'] = info.get('context_chars', 0) + len(pack)
                info['context_sections'] = sorted(set(info.get('context_sections', [])) | set(K.context_sections(pack)))
        reason = ''
        # a rig card with a ready file has ONE path (above): on a retry, with feedback or for a parallel candidate it is
        # applied too, and an unapplied one is refused (never handed to a model, which would invent the file)
        if vgs is not None and vgs.k:
            reason = ensemble_part(index, part, part_task, base + more)
            # an empty ensemble is the answer: its reason, no second round of calls beyond k (the old path is only for k == 0)
            return '%s: %s' % (file, reason) if reason else ''
        tries, spin, free_asks = 0, 0, UNDEF_RETRIES
        cannots: list = []      # the models that answered "CANNOT: the provided function ... does not contain" for this part
        if info is not None:
            with lock:
                info['model_asked'] = info.get('model_asked', 0) + 1
        while tries <= PART_RETRIES:
            attempt_no, spin = spin, spin + 1
            folder = workdir.parent / ('%s-p%d-%d' % (workdir.name, index, attempt_no))
            shutil.rmtree(folder, ignore_errors=True)
            with lock:          # a copy of the work directory is never read while another part writes its file into it
                shutil.copytree(workdir, folder)
            try:
                rc, out, err = call(part_task, folder, base + (PART_RETRY_NOTE % reason if reason else '') + more)
                note = err.decode('utf-8', 'replace') if isinstance(err, bytes) else str(err or '')
                target, before = folder / file, workdir / file
                with lock:
                    changed = target.is_file() and (not before.is_file() or target.read_bytes() != before.read_bytes())
                    answers.append(event_summary(out)['text'] if rc == 0 and out else '')
                reason = part_failure(note, changed)
                if rc == 0 and not reason:
                    try:      # an edit outside the contract is asked again with the allowed functions (never a block)
                        reason = part_off_contract(parts, file, before.read_text(encoding='utf-8-sig', errors='replace')
                                                   if before.is_file() else '',
                                                   target.read_text(encoding='utf-8-sig', errors='replace'))
                    except (OSError, ValueError):
                        reason = ''
                undefined = False
                if rc == 0 and not reason:      # a name the edit uses and nothing defines: the part is asked again, no strike
                    try:
                        reason = part_undefined(file, before.read_text(encoding='utf-8-sig', errors='replace')
                                                if before.is_file() else '', target.read_text(encoding='utf-8-sig', errors='replace'), root)
                    except (OSError, ValueError):
                        reason = ''
                    undefined = bool(reason)
                if rc == 0 and not reason:
                    with lock:
                        before.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(target, before)
                    return ''
                reason = reason or 'the call failed'
                if _CANNOT_NOT_THERE.search(reason):
                    # the same CANNOT ("the provided function X does not contain ...") from a SECOND model: the contract
                    # names the wrong place, a third try would only repeat it; the card goes back to the slicer
                    said_by = who(file) if who is not None else None
                    if any(m != said_by for m in cannots):
                        return '%s: %s: the contract describes another place than the code (two models answered CANNOT: %s)' % (
                            file, STALE_MARK, reason[:150])
                    cannots.append(said_by)
                if undefined and free_asks > 0:
                    free_asks -= 1
                    notify('undefined_name_reask')
                else:
                    tries += 1
                if 'CANNOT' in reason and not more:
                    # "the code is not shown" (live 23.11: 6 of 24 part_failed): the next ask shows what the file holds
                    # (names and signatures, read only), so the model can say where the code it misses is
                    room = channels.PROMPT_LIMIT_CHARS - len(base) - len(PART_RETRY_NOTE % reason) - 200
                    try:
                        table = K.outline(source, min(3000, room)) if room > 300 else ''
                    except (ValueError, SyntaxError):
                        table = ''
                    more = ('\nOutline of %s (names and signatures, read only; edit only what is shown above):\n%s\n'
                            % (file, table)) if table else ''
            finally:
                shutil.rmtree(folder, ignore_errors=True)
        return '%s: %s' % (file, reason)

    failed: list[str] = []
    index = 0
    for stage in K.stages(parts):
        batches: list[list] = []
        for part in stage:                       # one file twice in a stage: the copies would race, so in turn
            for batch in batches:
                if all(q['file'] != part['file'] for _, q in batch):
                    batch.append((index, part))
                    break
            else:
                batches.append([(index, part)])
            index += 1
        for batch in batches:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = [pool.submit(one, i, p) for i, p in batch]
            failed.extend(f.result() for f in futures if f.result())
        if failed:
            break
    if vgs is not None:
        vgs.alts = vgs_alternates(per_part) if not failed else []
    return (1, '\n'.join(answers), '; '.join(failed)) if failed else (0, '\n'.join(answers), '')


READY_RETURNED = 'ready_returned'      # fac-52: the event of a ready-code card sent back to its author (the loop refuses its contract)
READY_RETURN_CHARS = 4000


def proven_code(task) -> bool:
    """fac-69: the contract's code was proven by a green cloud run (``proof`` with green ids and no new red, or the box stamp):
    its border at the gates is the file of its parts. An architect's code without that proof is not."""
    contract = K.contract_of(task)
    proof = contract.get('proof')
    if isinstance(proof, dict) and proof.get('green') and not proof.get('new_red'):
        return True
    return ready_card(task)


def ready_card(task) -> bool:
    """fac-52: a card of the box (its contract carries ``box``, the parts_digest the loop stamps on a contract of the box, whose
    ready code a green cloud run proved): the station only gates it; a model never reworks it, and whatever keeps it from merging
    (red gate, contract rules, a card or context that does not fit) goes back to its author. Cards of the ladder's steps (paid,
    agent, free) with code are not ready cards, whoever their author."""
    contract = K.contract_of(task)
    return bool(contract.get('box')) and any(isinstance(p, dict) and (p.get('code') or p.get('file_text'))
                                             for p in contract.get('parts') or ())


def _digest(*parts) -> str:
    return sha256('|'.join(str(p) for p in parts).encode('utf-8', 'replace')).hexdigest()


def _counts(result) -> dict | None:
    if result is None:
        return None
    return dict(collected=result.collected, passed=result.passed,
                failed=result.failed + result.errors, skipped=result.skipped)


def self_memory() -> dict:
    """<id>: this worker process's own resident memory in MB (RSS; on Windows the working set, not the commit charge):
    ``self_mb`` now and ``self_peak_mb`` its peak, the card without its git/gh/pytest children (the loop's ``peak_mb`` is the whole job). {} when it cannot be read."""
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes as W

            class Counters(ctypes.Structure):
                _fields_ = [('cb', W.DWORD), ('page_faults', W.DWORD), ('peak_ws', ctypes.c_size_t),
                            ('ws', ctypes.c_size_t), ('qpp', ctypes.c_size_t), ('qp', ctypes.c_size_t),
                            ('qnpp', ctypes.c_size_t), ('qnp', ctypes.c_size_t), ('pf', ctypes.c_size_t),
                            ('peak_pf', ctypes.c_size_t), ('private', ctypes.c_size_t)]

            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, ctypes.POINTER(Counters), W.DWORD]
            c = Counters()
            c.cb = ctypes.sizeof(c)
            if not psapi.GetProcessMemoryInfo(W.HANDLE(-1), ctypes.byref(c), c.cb):
                return {}
            now, peak = float(c.ws), float(max(c.peak_ws, c.ws))
        else:
            import resource
            peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (1 if sys.platform == 'darwin' else 1024)
            try:
                with open('/proc/self/statm', encoding='ascii') as fh:
                    now = float(int(fh.read().split()[1]) * os.sysconf('SC_PAGE_SIZE'))
            except (OSError, ValueError, IndexError):
                now = peak
        return {'self_mb': round(max(now, 1.0) / 2 ** 20, 1), 'self_peak_mb': round(max(peak, now, 1.0) / 2 ** 20, 1)}
    except Exception:       # noqa: BLE001  a measure that cannot be read never changes the pass
        return {}


def once(**kwargs) -> dict:
    """One pass on ONE task (arguments: see ``_once``). A lease that was claimed (handed in, or taken here) and that
    the pass never began to use -- an early return or a raise before ``_pass`` -- goes back to READY (unclaim, the
    attempt back) instead of being held until it expires and counted as an expiry. The result carries the worker's own
    memory (``self_memory``, <id>) for the loop's run event."""
    box: dict = {}
    if kwargs.get('lease') is not None and kwargs.get('task_id'):
        box['claim'] = (kwargs['task_id'], kwargs['lease'])
    try:
        result = _once(_box=box, **kwargs)
    except BaseException:
        _drop_claim(kwargs, box)
        raise
    _drop_claim(kwargs, box)
    if isinstance(result, dict):
        result.update(self_memory())
    return result


def _drop_claim(kwargs: dict, box: dict) -> None:
    if box.get('passed') or not box.get('claim'):
        return
    tid, token = box['claim']
    try:
        Lease(kwargs['checkpoint'], kwargs['plan'], tid, token).commit(lambda s, r: unclaim(s, tid, token))
    except Exception as error:   # noqa: BLE001 - best effort: a stale/began/busy lease is released by its expiry
        _log.warning('lease of %s not returned: %s', tid, error)


def _once(*, root: Path, plan: Path, checkpoint: Path, staging: Path,
         small_model: str, large_model: str, execute: bool = False,
         acknowledge: bool = False, review_model: str | None = None,
         channel_config: Path | None = None, max_attempts: int = MAX_ATTEMPTS, reslice_after: int = 0,
         max_model_calls: int | None = None, base_sha: str | None = None, port_repo: Path | None = None,
         task_id: str | None = None, lease: str | None = None, _box: dict | None = None) -> dict:
    """One pass on ONE task. ``task_id`` + ``lease``: the loop (or the pool) claimed the task and hands over its lease
    token; without a lease the pass claims the task itself (``task_id``, else the first ready one). There is no lock
    over the pass: the state changes only in short fenced commits (agent_factory.Lease)."""
    tasks = read_plan(json.loads(plan.read_text(encoding="utf-8")))
    if staging.resolve().is_relative_to(root.resolve()):
        raise InvalidPlan("staging inside source project is forbidden")
    if checkpoint.resolve().is_relative_to(root.resolve()):
        raise InvalidPlan("checkpoint inside source project is forbidden")
    if lease is not None and not task_id:
        raise InvalidPlan("a lease belongs to a task: task_id is required")
    tasks, state = snapshot(checkpoint, plan)             # read-only: the pass changes the state only by commits
    if lease is not None:
        candidates = [task_id] if task_id in tasks else []
    else:
        candidates = list(ready(tasks, state)) if task_id is None else (
            [task_id] if startable(tasks, state, task_id) else [])
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
        configured = channels.validate(configured)
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
    except OSError as error:   # antivirus, a locked folder: the machine, not the task (a lease handed in is returned by once())
        return {'status': 'READY', 'reason': 'os_error', 'task_id': tid, 'task': tid,
                'backlog_id': task.backlog_id, 'base_sha': base_sha, 'calls': [], 'stages': {},
                'events': [], 'tests': None, 'infra': True, 'wait_s': 60.0,
                'error_type': type(error).__name__,
                'reason_detail': scrub_paths(redact(str(error))[:200], [root, staging]),
                'deploy_blocked': state['deploy_blocked']}
    if max_model_calls is not None:
        # Explicit operator budget for this checkpoint, never an implicit raise.
        with txn(checkpoint, plan) as (_tasks, fresh):
            fresh["max_model_calls"] = max_model_calls
    token = lease
    if token is None:
        try:
            claimed = claim(checkpoint, plan, tid)     # one transaction; calls are charged when they are made
        except BudgetExhausted:
            return {'status': 'WAITING_CHANNEL', 'reason': 'budget_exhausted', 'task_id': tid, 'task': tid,
                    'backlog_id': task.backlog_id, 'base_sha': base_sha, 'calls': [], 'stages': {}, 'events': [],
                    'tests': None, 'infra': False, 'wait_s': round(seconds_to_local_midnight(), 1),
                    'deploy_blocked': state['deploy_blocked']}
        if claimed is None:
            return {"status": "IDLE", "next": None, "deploy_blocked": state["deploy_blocked"]}
        tid, token = claimed
        _box['claim'] = (tid, token)
    _box['passed'] = True      # from here the pass itself returns or ends the lease
    return _pass(task, Lease(checkpoint, plan, tid, token), checkpoint=checkpoint, root=root, staging=staging,
                 small_model=small_model, large_model=large_model, review_model=review_model,
                 configured=configured, max_attempts=max_attempts, reslice_after=reslice_after, swept_failed=swept_failed,
                 base_sha=base_sha or os.environ.get('FACTORY_BASE_SHA'), port_repo=port_repo,
                 ledger=(channel_config.resolve().parent / 'quota') if channel_config is not None else None)


def _pass(task: Task, ck: Lease, **kwargs) -> dict:
    try:
        with scratch_redirect(kwargs['staging']):
            return _pass_inner(task, ck, **kwargs)
    except LockBusy:          # the checkpoint lock stayed busy: no verdict, nothing written, the lease expires on its own
        return {'status': 'READY', 'reason': 'lock_busy', 'task_id': task.id, 'task': task.id,
                'backlog_id': task.backlog_id, 'base_sha': kwargs.get('base_sha'), 'calls': [], 'stages': {},
                'events': [], 'tests': None, 'infra': False, 'wait_s': 30.0}
    except StaleLease:        # the lease is not this pass's any more (it expired, or another writer ended the pass)
        return {'status': 'STALE_LEASE', 'reason': 'stale_lease', 'task_id': task.id, 'task': task.id,
                'backlog_id': task.backlog_id, 'base_sha': kwargs.get('base_sha'), 'calls': [], 'stages': {},
                'events': [], 'tests': None, 'infra': False, 'wait_s': 0.0}


def _pass_inner(task: Task, ck: Lease, *, checkpoint: Path, root: Path, staging: Path,
          small_model: str, large_model: str, review_model: str, configured: list,
          max_attempts: int, base_sha: str | None, swept_failed=(), ledger: Path | None = None,
          port_repo: Path | None = None, reslice_after: int = 0) -> dict:
    """The pass of the lease ``ck`` (the task is already RUNNING under it). It keeps read-only facts (``state`` and
    ``row`` are a copy taken at the start); every change of the state is ONE ``ck.commit`` on the FRESH state."""
    tid, token = task.id, ck.token
    ck = _SerialLease(ck)       # the parts of a card call the router from threads: one transaction at a time
    try:
        staging.mkdir(parents=True, exist_ok=True)
        ck.commit(lambda s, r: begin(s, tid, token, os.getpid()))   # fenced: a foreign or dead lease stops the pass here
    except StaleLease:
        raise
    except BaseException:      # never began: give the lease back (unclaim refuses once the pass began)
        _drop_claim({'checkpoint': checkpoint, 'plan': ck.plan}, {'claim': (tid, token)})
        raise
    state = ck.read()
    prefix = "task-" + tid + "-" + token[:8]
    row = state['tasks'][tid]
    attempt = row['attempts']
    calls: list[dict] = []
    stages: dict[str, float] = {}
    events: list[str] = ['sweep_failed'] if swept_failed else []
    ctx = {'workdir': staging / prefix, 'baseline': {}, 'coder_model': None, 'coder_models': set(), 'counts': None,
           'role': 'code', 'lock': threading.Lock(),     # the lock guards what the threads of one card write: role, light, last_tokens
           'read_chars': 0, 'last_tokens': 0, 'last_text': '', 'roots': [root, staging]}
    scrub = lambda text: scrub_paths(text, ctx['roots'] + [ctx['workdir']])  # noqa: <id>
    report = {'task_id': tid, 'task': tid, 'backlog_id': task.backlog_id, 'base_sha': base_sha,
              'attempt': attempt, 'kind': task.kind, 'calls': calls, 'stages': stages,
              'events': events, 'reason': None, 'tests': None, 'wait_s': 0.0, 'infra': False,
              'deploy_blocked': state['deploy_blocked']}
    if reslice_after and paid_critic.agent_card(task) and any(p.get('code') or p.get('file_text') for p in K.contract_of(task).get('parts') or ()):
        reslice_after = 1       # its code is the edit: a red gate or a reject goes back to a strong author with the evidence; a small model
        # rewriting it (25.11: 14 of 15 such second attempts, up to 199 calls each) only buried that evidence
    started_pass = time.monotonic()
    prev_diff_file = staging / 'prev-diff' / (tid + '.diff')

    def end(apply, **extra) -> dict:
        """The end of the pass: ``apply(state, row)`` makes the transition(s) on the fresh state and returns
        (status, more report fields) -- all of it ONE commit."""
        def commit(state, row):
            status, more = apply(state, row)
            if status not in ('READY', 'WAITING_CHANNEL'):      # settled, blocked or quarantined: every series is over
                table = factory_env(state)
                for key in ('task:%s:code' % tid, 'task:%s:review' % tid):
                    table['idle'].pop(key, None)
                table['shortages'].pop(tid, None)
                table['other'].pop(tid, None)
            return status, more, state['deploy_blocked']
        status, more, blocked = ck.commit(commit)
        report.update(extra)
        report.update(more or {})
        report['deploy_blocked'] = blocked
        report['status'] = status
        report['tests'] = _counts(ctx['counts'])
        report['gate_secs'] = gate.where_secs()
        report['dur_s'] = round(time.monotonic() - started_pass, 3)
        return report

    def has_pending() -> bool:
        return bool(ck.read()['tasks'][tid].get('pending_review'))

    def set_pending(state, row) -> None:
        old = row.get('pending_review') if isinstance(row.get('pending_review'), dict) else {}
        row['pending_review'] = dict(workdir=str(ctx['workdir']), baseline_digest=baseline_digest,
                                     coder_model=ctx['coder_model'],
                                     coder_models=sorted(ctx['coder_models'] | {m for m in [ctx['coder_model']] if m}))
        short = old.get('chain_short')
        if old.get('workdir') == str(ctx['workdir']) and type(short) is int and short > 0:
            row['pending_review']['chain_short'] = short     # the same candidate: its short chains keep counting
        if old.get('workdir') == str(ctx['workdir']) and isinstance(old.get('votes'), list) and old.get('votes_diff'):
            row['pending_review']['votes'] = old['votes']    # W-review 2: the critics' voices of this very diff stay
            row['pending_review']['votes_diff'] = old['votes_diff']
        if old.get('workdir') == str(ctx['workdir']) and isinstance(old.get('gates'), dict):
            row['pending_review']['gates'] = old['gates']    # W-rev 2: the green gates of this very diff stay

    def keep_votes(row, log, diff_hash) -> None:
        """W-review 2: the critics' voices on the candidate (its diff hash is the key); dropped with pending_review."""
        pend = row.get('pending_review')
        if isinstance(pend, dict):
            pend['votes'], pend['votes_diff'] = log, diff_hash

    def chain_short(state, row) -> int:
        """One more chain of this candidate cut short; counted on the candidate itself, so a channel_wait between two
        short chains does not reset the term the way it resets defer_streak."""
        pend = row.get('pending_review')
        if not isinstance(pend, dict):
            return ESCALATE_AFTER
        prior = pend.get('chain_short')
        pend['chain_short'] = (prior if type(prior) is int and prior > 0 else 0) + 1
        return pend['chain_short']

    def live_quotas(state=None) -> dict:
        """W-gemma5 1: THE quota view of the executor: the state's channel_quotas merged with the other states' sections of
        the shared ledger (the same view call() books on). Every rule that asks main_dry / main_open / edit_dry / route_order /
        usable reads this one, never the raw state. For reading only: the state for a write is not changed."""
        quota = (state if state is not None else ck.read()).get('channel_quotas') or {}
        if ledger is None:
            return quota
        return quota_ledger.view(quota, quota_ledger.others(ledger, str(checkpoint)))

    def dry_now() -> bool:
        """W-dry 2: every channel of the edit role is closed by the day's mark (factory_channels.edit_dry): the review
        goes by Gemma with repeats and the paid Haiku gives the missing voice. Not dry (the normal mode) on any doubt."""
        if not configured:
            return False
        try:
            return bool(channels.edit_dry(configured, live_quotas(), os.environ))
        except Exception:       # noqa: BLE001 - a view that cannot be read is the normal mode
            return False

    router_table = factory_router.load(checkpoint.parent)    # fac-43: the score table of the code and edit calls, read once a pass
    router_draws: dict = {}     # fac-43: the Thompson draws of this pass by (role, attempt): the precheck and the call agree

    def timed(name: str, fn):
        t0 = time.monotonic()
        try:
            return fn()
        finally:
            stages[name] = round(stages.get(name, 0.0) + time.monotonic() - t0, 3)

    def release(reason: str, seconds: float, infra: bool | None = None, key: str = '') -> dict:
        """No strike, attempt not spent: back to READY, postponed. ``infra`` only for real faults. ``key``: the input's
        fingerprint kept in defer_streak (W-a2)."""
        return end(lambda s, r: (defer(s, tid, token, reason, seconds, key=key), None), reason=reason,
                   wait_s=round(float(seconds), 1), infra=(reason in INFRA_DEFERS) if infra is None else infra)

    def block(reason: str, detail: str = '', *, infra: bool = False, keep: bool = False) -> dict:
        """BLOCKED without a strike (also drops a stale pending review: agent_factory.quarantine)."""
        if reason == 'context_too_large' and ready_card(task):     # fac-52: no channel fault, no model may rework it: back now
            return ready_return('context_too_large: ' + str(detail))
        detail = scrub(redact(detail))[:400]
        voided = []

        def apply(state, row):
            voided.append(row.get('pending_review'))
            quarantine(state, tid, token, reason=reason)
            if detail:
                add_feedback(state, tid, 'gate', '[infra] ' + reason + ': ' + detail)
            return 'BLOCKED', {'blocked_reason': row.get('blocked_reason')}
        result = end(apply, reason=reason, reason_detail=detail, infra=infra)
        old = voided[0]
        if not keep and isinstance(old, dict) and isinstance(old.get('workdir'), str) and inside_staging(old['workdir'], staging):
            shutil.rmtree(old['workdir'], ignore_errors=True)   # the candidate is void with the block
        return result

    def release_or_block(reason: str, seconds: float) -> dict:
        """The same postponement three times in a row is not a wait any more: BLOCKED for Opus."""
        if reason in ESCALATE and defer_streak(ck.read(), tid, reason) + 1 >= ESCALATE_AFTER:
            return block(reason, 'postponed %d times in a row' % ESCALATE_AFTER, infra=reason in INFRA_DEFERS)
        return release(reason, seconds)

    def ready_return(why: str) -> dict:
        """fac-52: the one way back of a ready card (ready_card) that cannot merge here: to its author with the reason (the loop
        moves its contract to contracts/refused/ and holds the row for the author's next contract), never to a model to rework:
        FAILED reslice:stale, no strike, no unblock round; a pending review's candidate is void with it."""
        events.append(READY_RETURNED)
        why = scrub(redact(why))
        voided = []

        def apply(state, row):
            voided.append(row.get('pending_review'))
            return fail_row(state, tid, token, 'reslice:stale'), None
        result = end(apply, reason='reslice:stale', reason_detail=why[:300], ready_return=why[:READY_RETURN_CHARS],
                     ready_box=str(K.contract_of(task).get('box')))
        old = voided[0] if voided else None
        if isinstance(old, dict) and isinstance(old.get('workdir'), str) and inside_staging(old['workdir'], staging):
            shutil.rmtree(old['workdir'], ignore_errors=True)
        return result

    def not_green(ids, why='') -> dict:
        """fac-52: the reason of a ready card's return: the ids that are not green on this base (or the gate's reason)."""
        return ready_return('not green on base %s: %s' % (str(base_sha or '?')[:12], ', '.join(ids) if ids else why))

    def reject(source: str, reason: str, text: str, names=(), mark=None) -> dict:
        """A candidate failed a gate or the reviewer: feedback + previous diff + a strike. ``mark(row)``: one more
        change of the row in the same commit."""
        reason = scrub(redact(reason))[:300]
        text = scrub(text)
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

        asked_now = (asked_names(text) | frozenset(ctx.get('asked') or ())) & defined_names(task, ctx['workdir'])

        def apply(state, row):
            closer = source == 'gate' and progressed(fresh_feedback(state, tid), text)   # fewer tests red than last time
            add_feedback(state, tid, source, '[attempt %d] %s' % (attempt, text))
            if asked_now:                          # the next attempts show these whole first, whatever fails in between
                remember_asked(row, asked_now)
            if mark is not None:
                mark(row)
            failed = (list(ctx.get('tried', ())) + [m for m, _ in ctx.get('gate_red', ()) if m]
                      + ([ctx['coder_model']] if ctx.get('coder_model') else [])
                      + sorted(ctx['coder_models']))   # every model this pass tried
            status = settle(state, tid, token, tests_ok=False, evidence=_digest(reason, text),
                            max_attempts=max_attempts, unsafe=is_unsafe_reject(reason), failed_models=failed,
                            reslice_after=reslice_after + 1 if closer and reslice_after >= 2 else reslice_after)
            row.pop('pending_review', None)
            return status, None
        return end(apply, reason=reason, reason_detail=redact(text)[:400])

    def call_size(role, call_task, prompt_len, cyr) -> tuple:
        """(light, tokens, steps, requests) of a call: shared by call() and the review precheck (W-review fix 1)."""
        light = engine_for(role, call_task) == 'light'
        base_tokens = channels.estimate_tokens(prompt_len, 0 if light else ctx['read_chars'],
                                               overhead=LIGHT_OVERHEAD_TOKENS if light else None, cyrillic=cyr)
        steps = 1 if light else (REVIEW_STEPS if role == 'review' else PROVIDER_STEPS)
        return light, base_tokens, steps, (1 if light else requests_for(steps))

    def call_order(role, preferred, base_tokens, exclude_model, hopped, skip_tiers, later, live_state, light, steps,
                   sink=None) -> list:
        """The route a call walks (excluded models, tiers, the code fallback, Kilo rpm): shared with the precheck
        (which passes its own ``sink`` for the events, so it writes none of them). Code and edit (fac-43): the router's
        order, factory_router.pick -- a Thompson draw on the score table over the live channels, one draw per pass and
        attempt; a channel cooled by a raw mark walks after the open ones (never raises: choose() decides the wait)."""
        route = 'code' if role == 'repair' else role
        excl = sorted(channels.excluded_models(exclude_model) | set(hopped)) or None
        order = channels.route_order(configured, route, attempt, base_tokens, preferred=preferred,
                                     exclude_model=excl, skip_tiers=skip_tiers, state=live_state, later=later,
                                     env=os.environ)
        if not order and route in ('code', 'edit'):     # no channel fits the size: any channel is better than none
            order = channels.route_order(configured, 'code', 1, 0, preferred=preferred,
                                         exclude_model=excl,   # never a model the tournament tried
                                         skip_tiers=skip_tiers, state=live_state, later=later)
        if order and route in ('code', 'edit'):
            got = factory_router.pick(route, tid, channels_list=order, state=live_state, env=os.environ,
                                      table=router_table, preferred=preferred,
                                      draws=router_draws.setdefault((route, attempt), {}))
            if isinstance(got, factory_router.Wait):
                got = got.fallback
            if got is not None:
                order = list(got.walk)
        return _kilo_fits(order, steps, events if sink is None else sink) if order and not light else order

    def call_affinity(role) -> list:
        """The channel affinity of a call of this role (a reviewer must not move the coder's remembered channel):
        shared by call() and the review precheck (W-review fix 1, round 1 finding 1)."""
        family = os.path.splitext(task.touch_files[0].replace('\\', '/'))[0] if task.touch_files else ''
        suffix = ':review' if role == 'review' else ''
        return ['task:' + tid + suffix] + (['family:' + family + suffix] if family else [])

    def call_pick(order, seen, base_tokens, requests, affinity) -> tuple:
        """(channel, tokens): the choice on a quota view, nothing booked; raises ChannelUnavailable. Shared with the precheck."""
        live = channels.usable(order, seen, os.environ) or order   # a dead or keyless channel sets no ceiling
        tokens = min(base_tokens, max(c['tpm'] for c in live))     # a huge file may not make every channel "too small"
        return channels.choose(order, seen, tokens, os.environ, requests=requests, affinity=affinity), tokens

    def head_order(role, preferred, base_tokens, exclude_model, skip_tiers, later) -> list:
        """W-bucket: the route of a head call: the size and role rules of route_order WITHOUT the quota state (no rating,
        no day share, no cooling mark) and without the router's draw; tiers in the role's own order. The head itself
        chooses the channel inside a tier and when a tier is left (its pauses, closes and day limits)."""
        route = 'code' if role == 'repair' else role
        excl = sorted(channels.excluded_models(exclude_model)) or None
        order = channels.route_order(configured, route, attempt, base_tokens, preferred=preferred, exclude_model=excl,
                                     skip_tiers=skip_tiers, later=later, env=os.environ)
        if not order and route in ('code', 'edit'):     # no channel fits the size: any channel is better than none
            order = channels.route_order(configured, 'code', 1, 0, preferred=preferred, exclude_model=excl,
                                         skip_tiers=skip_tiers, later=later)
        ranks = channels.TIERS if route in ('code', 'edit') else channels._ROLE_TIERS.get(route, channels.TIERS)
        return sorted(order, key=lambda c: ranks.index(channels.tier_of(c)) if channels.tier_of(c) in ranks else len(ranks))

    def via_head(role, call_task, directory_for, prompt, small, tokens, head_file, candidate, models_out, on_booked, temperature,
                 wait_budget=None):
        """fac-40: one call of the light engine through the head; the head books, cools and hops, this only charges the
        card's call budget, keeps the telemetry row and maps a refusal to ChannelFault. HeadDown: the caller's old path.
        ``wait_budget`` (the review pass): the head waits no longer than what is left of it, and the wait is charged to it.
        A ticket never sent in its deadline: ChannelFault with ``head_expired`` and the head's ETA as the card's wait."""
        def charge(state, row):
            charge_call(state, tid)
            began = row.get('began')
            if isinstance(began, dict):
                began['booked'] = int(began.get('booked') or 0) + 1      # the pool's admission counts workers that did not book yet
        ck.commit(charge)
        box = {}

        def post(url, key, body, timeout):       # the key never travels: the head reads its own
            own = set().union(*(channels.body_extra(c['model']) for c in small))     # each model's fields: Head._run adds them
            sent = {k: v for k, v in body.items() if k not in own}
            if isinstance(sent.get('max_tokens'), int):      # the ceiling of the general limit: Head._run cuts it per channel's model
                sent['max_tokens'] = max(sent['max_tokens'], LIGHT_MAX_OUTPUT)
            left = None if wait_budget is None else max(0.0, wait_budget.left())
            answer = factory_head.ask(head_file, role, tokens, sent, [c['id'] for c in small],
                                      deadline_s=factory_head.ticket_deadline(timeout, left), call_timeout_s=timeout, card=tid)
            box.update(answer)
            if wait_budget is not None:
                wait_budget.spend(float(answer.get('queued_s') or 0.0))
            if answer.get('expired') and answer.get('status') not in (200, 400, 401, 403, 404):
                # never sent in its deadline (or every try came back 429 / 5xx): the head names what held it and its ETA,
                # which is the card's wait (never a guess from the ledger's old marks)
                eta = answer.get('eta_s')
                wait = min(HEAD_ETA_MAX_S, max(5.0, float(eta))) if isinstance(eta, (int, float)) else 60.0
                raise ChannelFault({'kind': 'rate_minute' if answer.get('status') == 429 else 'transient', 'head_expired': True,
                                    'message': 'head: %s' % (answer.get('held') or {}), 'retry_after_s': wait}, wait_s=wait)
            return answer['status'], (answer.get('body') or '').encode('utf-8')
        with ctx['lock']:
            ctx['last_tokens'] = tokens
        began, directory = time.monotonic(), directory_for(0)
        code, stdout, stderr = light_attempt(call_task, directory, small[0]['model'], timeout=90, prompt_override=prompt,
                                             steps=None, key_env=small[0]['key_env'], post=post,
                                             temperature=candidate_temperature(candidate) if temperature is None else temperature)
        model = box.get('model') or small[0]['model']
        answered = next((c for c in small if c['id'] == box.get('channel')), None)
        if models_out is not None:
            models_out.add(model)
        if on_booked is not None:
            on_booked(model)
        ctx['light_note'] = stderr.decode('utf-8', 'replace')[:300] if code == 0 else ''
        summary = event_summary(stdout, directory)
        info = channels.classify(stdout, stderr, code)
        kinds = ('input_tokens', 'cache_read_tokens', 'cache_write_tokens')
        used = sum(summary[k] or 0 for k in kinds) if any(summary[k] is not None for k in kinds) else None
        calls.append({'role': role, 'attempt': attempt, 'channel': box.get('channel'), 'model': model,
                      'tier': channels.tier_of(answered) if answered is not None else None,
                      'reserved_tokens': tokens, 'actual_tokens': used, 'actual_input_tokens': used, 'head': True,
                      'input_tokens': summary['input_tokens'], 'output_tokens': summary['output_tokens'],
                      'reasoning_tokens': summary['reasoning_tokens'], 'cache_read_tokens': summary['cache_read_tokens'],
                      'cache_write_tokens': summary['cache_write_tokens'], 'candidate': candidate if role != 'review' else None,
                      'dur_s': round(time.monotonic() - began, 3), 'error_class': None if info['kind'] == 'ok' else info['kind'],
                      'http_status': info.get('status'), 'returncode': code, 'tool_events': summary['tool_events'],
                      'steps': summary['steps'], 'last_step_tools': summary['last_step_tools'],
                      'finish_reason': summary['finish_reason'], 'files_read': summary['files_read'],
                      'provider_error': info['kind'] not in ('ok', 'unknown') or summary['provider_error'],
                      'cool_reason': None, 'cool_s': None,
                      **dict(zip(('quota_id', 'quota_dim'), channels.quota_fields(info, box.get('quota'))))})
        ctx['last_text'] = summary['text']
        if info['kind'] == 'ok' or (info['kind'] == 'unknown' and code == 0):
            return code, stdout, stderr
        raise ChannelFault(info)

    def call(role: str, call_task: Task, directory_for, preferred: str, prompt: str,
             *, exclude_model: str | None = None, skip_tiers: tuple = (), later: bool = False,
             candidate: int | None = None, models_out: set | None = None, on_booked=None,
             temperature: float | None = None, fast_retry: bool | str = False, wait_budget=None) -> tuple[int, bytes, bytes]:
        """W-rev: ``fast_retry='small'`` hands a 503 back at once only on the small tier (the review call asks again itself,
        RW.retry_overload); other tiers keep their own retry. W-vgs2 1-2: ``fast_retry`` (an ensemble branch): a 503 is handed back at once as ChannelFault (the ensemble
        retries the branch itself), the probe-mode fuse does not stop the call, and a channel's failure cooling is
        applied once per pass. One real model call with reservation, charging, classification, one transient retry. ``skip_tiers``:
        channel tiers this call may not use (factory_channels.route_order). ``candidate``: the number of the candidate
        the call belongs to (parts of one card run in threads, so it is not read from ``ctx``); ``models_out``: the set
        the model of the call is added to as soon as it is booked; ``on_booked(model)``: called at the same moment."""
        if candidate is None:
            candidate = ctx.get('candidate') or 0
        if channels.prompt_too_big(prompt):
            raise PromptTooLarge(str(len(prompt)))
        light, base_tokens, steps, booked = call_size(role, call_task, len(prompt), channels.cyrillic_share(prompt))
        with ctx['lock']:
            ctx['role'], ctx['light'] = role, light
        # booked: the whole run, what choose() checks and reserve() books; reconcile() writes the fact
        def booked_one(row) -> None:
            began = row.get('began')
            if isinstance(began, dict):
                began['booked'] = int(began.get('booked') or 0) + 1      # the pool's admission counts workers that did not book yet

        affinity = call_affinity(role)

        # fac-40 / W-bucket: with a live head (its pulse is fresh) every channel it serves (all Google tiers, in the route's
        # order) goes to its one queue; the head alone sends, waits or refuses. Own hop/breaker/cooling/retries below are
        # only for the channels it does not serve and for a dead head.
        head_file = (Path(ledger).parent / factory_head.STATE_NAME) if ledger is not None else None     # beside channels.json
        ctx['head_left'] = False             # fac-68b head_left: set when the head's ticket expired and other providers answer
        leave, head_fault = set(), None      # with a live head the old path below takes only the channels it does not serve
        if light and configured and factory_head.alive(head_file):
            first = head_order(role, preferred, base_tokens, exclude_model, skip_tiers, later)
            served = [c for c in first if factory_head.serves(c)]
            if served:
                try:
                    return via_head(role, call_task, directory_for, prompt, served, base_tokens, head_file, candidate,
                                    models_out, on_booked, temperature, wait_budget=wait_budget)
                except factory_head.HeadDown as error:
                    events.append('head_down')
                    if error.alive:     # the head lives but did not answer in time: the card waits 30 s, never goes around it
                        raise ChannelFault({'kind': 'rate_minute', 'message': 'head: no answer (%s)' % error,
                                            'retry_after_s': 30, 'head_expired': True}, wait_s=30) from error
                    _log.warning('head down (%s): the old path', error)       # dead: the old path below answers
                except ChannelFault as error:
                    if not error.info.get('head_expired'):
                        raise
                    # the head could not send it in time: the other providers of the route (cohere, openrouter ...) answer
                    # it now through the old path, never a Google channel around the head; none of them: the head's wait
                    leave, head_fault = {c['id'] for c in configured if factory_head.serves(c)}, error
                    ctx['head_left'] = True
                    events.append('head_expired_other_providers')

        hopped, last_info = [], None     # models that answered "overloaded" in THIS call: the next hop skips them
        pauses = list(channels.OVERLOAD_RETRY_S)    # W-503: no free channel after a 503: the same one again after 5 s, 15 s

        def overload_pause() -> bool:
            """After a 503 with no free channel left: wait the next pause, forget the hops (the cooling is short now)
            and let the loop ask again. False when the pauses are spent (the pass is deferred, no penalty to the card)."""
            if last_info is None or not pauses:
                return False
            time.sleep(pauses.pop(0))
            hopped.clear()
            return True

        big = {'sends': 0, 'round': 0, 'free': 0, 'skip': set()}   # W-gemma 1: hops over big-quota channels (not counted in retry)
        for retry in range(1 + TRANSIENT_HOPS + len(pauses) + 2 * channels.BIG_SENDS_MAX
                           + channels.BIG_ROUNDS * (channels.BIG_SENDS_MAX + 1)):
            selected, at, chosen, kwargs = None, None, preferred, {}
            if configured:
                route = 'code' if role == 'repair' else role
                whole = ck.read()
                live_state = live_quotas(whole)    # W-gemma5 1: the merged view (a private copy: ratings, parked 404s, cooling)
                order = call_order(role, preferred, base_tokens, exclude_model, hopped, skip_tiers, later, live_state,
                                   light, steps)
                if leave:          # W-bucket: the head's channels stay with the head
                    order = [c for c in order if c['id'] not in leave]
                    if not order:
                        raise head_fault
                if big['skip']:      # W-gemma 1: the circle of big channels: one that just answered 503 waits its turn
                    rest = [c for c in order if c['id'] not in big['skip']]
                    if rest and any(channels.is_big(c) for c in rest):
                        order = rest
                    else:
                        big['skip'].clear()
                if not order and hopped:              # every other model is overloaded too: pauses, then the old path
                    if overload_pause():
                        continue
                    raise ChannelFault(last_info or {'kind': 'transient'})
                if not order:
                    raise NoIndependentReviewer()

                def book(state, row):
                    """View + usable + choose + charge + reserve + publish: ONE commit on the fresh state, so two workers
                    never choose the same free request."""
                    quota = state.setdefault('channel_quotas', {})
                    seen = (quota_ledger.view(quota, quota_ledger.others(ledger, str(checkpoint)))
                            if ledger is not None else quota)    # <id>: the other states' bookings of the same keys
                    pick, tokens = call_pick(order, seen, base_tokens, booked, affinity)   # a multi-step call needs room
                    charge_call(state, tid)   # BEFORE booking: an exhausted budget must leave no reservation behind
                    when = channels.reserve(quota, pick, tokens, requests=booked,
                                           affinity=affinity)   # exactly what choose() checked
                    if fast_retry is not True and not (fast_retry == 'small' and channels.tier_of(pick) == 'small'):
                        channels.breaker_claim(quota, pick)   # W-flow 2: a probe of a channel in probe mode: nobody else for 45 s
                    if ledger is not None:
                        quota_ledger.publish(ledger, str(checkpoint), quota)
                    booked_one(row)
                    return pick, when, tokens
                try:
                    selected, at, tokens = ck.commit(book)
                except channels.ChannelUnavailable:
                    if head_fault is not None:    # fac-68: the other providers have no room (rate_day ...): the card goes back
                        raise head_fault from None    # to the head's queue with its ETA, never parked 12 h for a Google channel
                    # W-gemma2 2 (live 19:11:36, three sends, no cool_reason, 'transient'): checked and excluded: the call budget
                    # (refunded on every big 503), a deadline (none in call()), the same-channel ban (hopped is filled by the
                    # non-big path only), group cooling (a big 503 marks nothing). The cause: big['skip'] held the refusing channels
                    if (last_info is not None and fast_retry is not True and not (fast_retry == 'small' and order and all(
                            channels.tier_of(c) == 'small' for c in order)) and channels.breaker_open(live_state, order)):
                        raise ChannelFault(last_info)     # W-flow 2: probe mode: no pauses, no pounding; the pass is deferred (no strike)
                    if big['skip']:               # while the others were not free: the ones that answered 503 are asked again,
                        big['skip'].clear()       # no pause spent
                        continue
                    if overload_pause():          # nothing booked, nothing charged: the 503's channel is asked again
                        continue
                    if last_info is not None:     # the pauses are spent: the pass is deferred as 'transient' (no strike)
                        raise ChannelFault(last_info)
                    raise
                if tokens < base_tokens and 'reservation_capped' not in events:
                    events.append('reservation_capped')
                chosen, kwargs['key_env'] = selected['model'], selected['key_env']
            elif chosen in channels.excluded_models(exclude_model):
                raise NoIndependentReviewer()
            else:
                tokens = base_tokens

                def charge(state, row):
                    charge_call(state, tid)
                    booked_one(row)
                ck.commit(charge)
            with ctx['lock']:
                ctx['last_tokens'] = tokens
            if models_out is not None:
                models_out.add(chosen)
            if on_booked is not None:
                on_booked(chosen)
            # W-503: the small tier waits BIG_TIMEOUT_S for ANY role of the light engine (a review or a code call of Gemma
            # waited the full 180 s, live 23.11: 180 and 87 s)
            small_quick = bool(selected and channels.tier_of(selected) == 'small' and (role == 'edit' or light))
            began = time.monotonic()
            sent = False
            try:
                directory = directory_for(retry)
                engine = light_attempt if light else model_attempt
                if light:
                    kwargs['temperature'] = candidate_temperature(candidate) if temperature is None else temperature   # W-vgs: the ensemble's own row
                timeout = channels.BIG_TIMEOUT_S if small_quick else 240    # fac-43: one answer limit of the small tier
                sent = True        # W-dry 3: from here the request may be out; an interrupted call still counts
                code, stdout, stderr = engine(call_task, directory, chosen, timeout=timeout,
                                              prompt_override=prompt, steps=steps, **kwargs)
            except BaseException:
                if selected is not None:    # booked, never accounted: the reservation goes back (the call did not finish)
                    def unbook(state, row):
                        channels.reconcile(state['channel_quotas'], selected, at, tokens, 0,
                                           requests=booked, actual_requests=booked if sent else 0)   # W-dry 3: a sent request counts
                        if ledger is not None:
                            quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
                    try:
                        ck.commit(unbook)
                    except Exception as error:   # noqa: BLE001 - the original failure is what the pass reports
                        _log.warning('reservation not returned: %s', error)
                raise
            ctx['light_note'] = stderr.decode('utf-8', 'replace')[:300] if light and code == 0 else ''
            elapsed = round(time.monotonic() - began, 3)
            summary = event_summary(stdout, directory)
            # W-gemma 3: a Gemma call that ran out of its answer limit is a timeout (10 s rest), never a rate_minute in disguise
            idle = (code == 124 and summary['steps'] == 0 and summary['tool_events'] == 0
                    and not (selected is not None and channels.no_streak(selected)))
            kinds = ('input_tokens', 'cache_read_tokens', 'cache_write_tokens')
            actual_input = (sum(summary[k] or 0 for k in kinds) if any(summary[k] is not None for k in kinds)
                            else None)       # None = Kilo reported no usage: unknown, never 0
            actual = (None if actual_input is None and summary['output_tokens'] is None
                      else (actual_input or 0) + (summary['output_tokens'] or 0) + (summary['reasoning_tokens'] or 0))

            def account(state, row):
                """What the call showed, on the FRESH state: the idle series, a cooling, the true-up of the booking and
                the ledger -- one commit."""
                counters = factory_env(state)['idle']
                task_key = 'task:%s:%s' % (tid, 'review' if role == 'review' else 'code')
                keys = (task_key, 'channel:' + str(selected['id'] if selected else chosen))
                prior = counters.get(task_key) if type(counters.get(task_key)) is int else 0    # only the TASK's own series blocks it
                ceiling = idle and prior >= IDLE_SUSPECTS_ALLOWED      # a broken launch must trip the brake, not cool forever
                info = channels.classify(stdout, stderr, code, idle=idle and not ceiling)
                if ceiling:
                    info['ceiling'] = True
                    if selected is not None:       # the NEXT task on this channel must not meet the same wall at once
                        channels.cool(state.setdefault('channel_quotas', {}), selected,
                                      seconds=channels.RATE_SUSPECT_COOL_S)
                    counters.pop(keys[1], None)
                if idle and not ceiling:
                    for k in keys:
                        counters[k] = (counters.get(k) if type(counters.get(k)) is int else 0) + 1
                elif summary['steps'] > 0 or summary['tool_events'] > 0 or info['kind'] == 'ok':
                    for k in keys:
                        counters.pop(k, None)               # real work was seen: the series is over
                if selected is not None:
                    # no usage reported: the fact is unknown, so the token booking stays whole
                    charged = actual_input if actual_input is not None else tokens
                    # Kilo retries inside a failed call and the retries spend quota the stream never shows: after a
                    # failure, or when nothing was reported, the booking stays whole; only a clean call is trued up
                    unknown = summary['steps'] == 0 and actual_input is None
                    failed = code != 0 or info['kind'] != 'ok' or summary['provider_error']
                    fact = max(booked, summary['steps']) if (failed or unknown) else max(1, summary['steps'])
                    if info['kind'] == 'network' and 'timeout' not in str(info.get('message') or '').lower():
                        fact = 0         # no HTTP answer (refused, no route): the request never reached the provider's quota;
                        # a TIMEOUT did reach it (W-dry 3: Google counted 500, we 177-234) and stays counted
                    if info['kind'] == 'transient' and info.get('status') in channels.OVERLOAD_STATUSES and not summary['steps']:
                        charged = fact = 0      # refused by an overloaded model: nothing was read or written (25.11: three 503s of one second
                        # each held a Gemma channel's whole 16K minute, so a channel that answers every second call was asked 3 times a minute)
                    channels.reconcile(state['channel_quotas'], selected, at, tokens, charged,
                                       requests=booked, actual_requests=fact)
                    # the series of failed calls of this channel: 'ok' with the whole output limit spent and no word
                    # of answer is a failure too (live 20.11: ~174 s each); no connection at all is the laptop's net,
                    # a task too big for the channel is the task's problem
                    empty = (info['kind'] == 'ok' and summary['finish_reason'] in ('length', 'max_tokens')
                             and not (summary['text'] or '').strip())
                    if info['kind'] not in ('network', 'too_big'):
                        streak = channels.note_outcome(
                            state['channel_quotas'], selected,
                            not empty and (info['kind'] == 'ok' or (info['kind'] == 'unknown' and code == 0)),
                            channels=configured,
                            overload=info['kind'] == 'transient' and info.get('status') in channels.OVERLOAD_STATUSES)
                        if streak.get('reason'):
                            info['streak_cool'] = streak
                    if ledger is not None:
                        quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
                return info
            info = ck.commit(account)
            if info.get('suspect') and 'rate_limited_suspect' not in events:
                events.append('rate_limited_suspect')
            calls.append({'role': role, 'attempt': attempt, 'channel': selected['id'] if selected else None,
                          'model': chosen, 'tier': channels.tier_of(selected) if selected else 'main',
                          'reserved_tokens': tokens, 'actual_tokens': actual,
                          'actual_input_tokens': actual_input,
                          'input_tokens': summary['input_tokens'], 'output_tokens': summary['output_tokens'],
                          'reasoning_tokens': summary['reasoning_tokens'],
                          'cache_read_tokens': summary['cache_read_tokens'],
                          'cache_write_tokens': summary['cache_write_tokens'],
                          'candidate': candidate if role != 'review' else None,
                          'dur_s': elapsed, 'error_class': None if info['kind'] == 'ok' else info['kind'],
                          'http_status': info.get('status'), 'returncode': code,
                          'tool_events': summary['tool_events'], 'steps': summary['steps'],
                          'last_step_tools': summary['last_step_tools'],
                          'finish_reason': summary['finish_reason'], 'files_read': summary['files_read'],
                          'provider_error': info['kind'] not in ('ok', 'unknown') or summary['provider_error'],
                          'cool_reason': info.get('streak_cool', {}).get('reason'),
                          'cool_s': info.get('streak_cool', {}).get('cool_s'),
                          **dict(zip(('quota_id', 'quota_dim'), channels.quota_fields(info)))})   # ids only, never the text
            ctx['last_text'] = summary['text']
            kind = info['kind']
            if kind == 'ok' or (kind == 'unknown' and code == 0):
                return code, stdout, stderr
            if kind == 'timeout' and (small_quick or (selected is not None and channels.no_streak(selected))):
                info['kind'] = kind = 'transient'
                info['timed_out'] = True       # W-gemma 3: apply_failure rests the Gemma channel BIG_TIMEOUT_CLOSE_S
            if kind in ('timeout', 'launcher'):
                raise ChannelFault(info)
            overload_503 = (kind == 'transient' and selected is not None
                            and info.get('status') in channels.OVERLOAD_STATUSES)
            if overload_503 and (fast_retry is True or (fast_retry == 'small' and channels.tier_of(selected) == 'small')):
                with ctx['lock']:
                    first_time = selected['id'] not in ctx.setdefault('penalised', set())
                    ctx['penalised'].add(selected['id'])

                def refused_503(state, row):     # no quota spent, no model call of the card; the cooling once per pass
                    state['model_calls'] = max(0, int(state.get('model_calls') or 0) - 1)
                    if first_time:
                        channels.apply_failure(state['channel_quotas'], selected, info, env=os.environ)
                    if ledger is not None:
                        quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
                ck.commit(refused_503)
                last_info = info
                raise ChannelFault(dict(info, fast_retry=True))     # W-rev: the caller may ask again (RW.retry_overload)
            if selected is not None:
                def failure(state, row):
                    if ledger is not None:      # a success of another process ends our series of 503s too
                        channels.absorb_foreign_ok(state.setdefault('channel_quotas', {}),
                                                   quota_ledger.others(ledger, str(checkpoint)))
                    outcome = channels.apply_failure(state['channel_quotas'], selected, info, env=os.environ,
                                                     others=quota_ledger.others(ledger, str(checkpoint))
                                                     if ledger is not None else ())
                    if ledger is not None:
                        quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
                    return outcome
                done = ck.commit(failure)
            else:
                done = {'cool_s': info.get('retry_after_s') or 0}
            if (kind == 'transient' and selected is not None and info.get('status') in channels.OVERLOAD_STATUSES
                    and channels.is_big(selected) and role in channels.BIG_ROLES):
                # W-gemma 1: a 503 of Gemma: no cooling, no wait of 20 s: the next channel of the circle after 2 s
                circle = len({c['id'] for c in configured if channels.is_big(c)})
                step, pause = channels.big_hop(big, circle)
                last_info = info

                def refund(state):
                    # a refused send (503, 1 s, no quota) is no model call of the card: its day budget is given back
                    state['model_calls'] = max(0, int(state.get('model_calls') or 0) - 1)
                if step == 'hop':
                    big['skip'].add(selected['id'])
                    big['free'] += 1
                    ck.commit(lambda state, row: refund(state))
                    if not done.get('probe_mode'):      # W-flow 2: a channel in probe mode: no pause, the next one is asked
                        time.sleep(pause)
                    continue

                def close_it(state, row):
                    refund(state)
                    outcome = channels.close_big(state.setdefault('channel_quotas', {}), selected)
                    if ledger is not None:
                        quota_ledger.publish(ledger, str(checkpoint), state['channel_quotas'])
                    return outcome
                ck.commit(close_it)
                raise ChannelFault(info, channels.BIG_CLOSE_S)
            if kind == 'transient' and selected is not None and retry - big['free'] < TRANSIENT_HOPS:
                # owner: on a 503 the step does not wait or throw the candidate away, it moves to a free model at
                # once (live 21.11 20:41-21:01: <id>_test lost three gate-passed candidates, 4-7 min each, because both
                # review channels were one overloaded Gemma). Only this call skips the model; its cooling is the channel's.
                if done.get('action') != 'cool_channel':     # a hiccup rests only its channel: the model's other key stays
                    hopped.append(chosen)
                last_info = info
                continue
            if kind in ('transient', 'network') and retry - big['free'] == 0:
                if done.get('action') != 'cool_model' and not info.get('streak_cool'):   # cooled: the retry takes another one at once
                    time.sleep(channels.TRANSIENT_RETRY_S)   # (live 20.11: a 503 of Gemma cost ~67 s, 20 s of it here)
                continue
            raise ChannelFault(info, done.get('cool_s') or 0)
        raise ChannelFault({'kind': 'transient'})  # unreachable guard

    def soonest(default: float) -> float:
        """Wait of the channel that can actually serve the NEXT step (coder, or a reviewer of another model)."""
        if not configured:
            return default
        pool = [c for c in configured if not (ctx['role'] == 'review' and c['model'] == ctx['coder_model'])]
        seen = live_quotas()
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
        if error.info.get('head_expired') and kind in ('rate_minute', 'transient') and error.wait_s:
            return release(kind, error.wait_s)    # W-bucket: the head's own ETA, never the ledger's old marks (soonest)
        if kind in ('rate_minute', 'rate_day'):
            pause = soonest(error.wait_s or error.info.get('retry_after_s') or channels.DEFAULT_COOL_S)
            if ctx.get('head_left'):    # fac-68b head_left: the other providers' day is not the Google channel's: back in 5 min, not 12 h
                pause = min(pause, 300.0)
            if error.info.get('part_wait'):      # W-gemma5 2: no free channel within PART_WAIT_S: not back in 5 s to take the seat again
                pause = max(PART_WAIT_REST_S, pause)
            return release(kind, pause)
        if kind == 'region':
            return release(kind, soonest(60))
        if kind in ('key_invalid', 'model_missing'):
            return release(kind, soonest(60))
        if kind == 'too_big':      # the task does not fit the provider budget: the task's problem, not the channel's
            return block('context_too_large', error.info.get('message', ''))
        if kind == 'balance':
            return release('balance', soonest(error.wait_s or channels.BALANCE_COOL_S))
        if kind == 'transient':     # W-a2: an ensemble with no answer at all is counted on its input
            return release('transient', 5, key=str(error.info.get('input_key') or ''))    # fac-68: was 60 (a 503 is no overload)
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
    bg = bg_pool = None            # the red base measured in the background while the model answers (task 3.2)
    bank_hook: list = []           # W-vgs2 3: bank_base once the pass has one

    def bank_base_safe():
        for keep in bank_hook:
            keep()
    gate_tmp = staging / 'tmp'     # pytest's own temp (--basetemp) stays inside staging, never under the profile
    slot = {'armed': False, 'left': float(SLOT_BUDGET_S), 'waited': 0.0}   # armed at the FIRST gate run

    def gate_run(tree, tests, touched=None):
        """gate.run_tests with the pass-wide slot budget: what is left of it, never a fresh one per call, and it is
        spent by WAITING for a slot only (GateResult.slot_wait_s), never by the run time of the tests. What was cut
        at the limit on the base (files, single tests) is handed over: the candidate run starts file by file and runs
        those tests alone (a joint run would only be cut again)."""
        slot['armed'] = True
        known = getattr(ctx.get('counts'), 'timed_out', ())
        result = gate.run_tests(tree, tests, GATE_TIMEOUT_S, workdir=gate_tmp,
                                wait_s=max(0.0, slot['left']), **({'hung': known} if known else {}),
                                **({'touched': tuple(touched)} if touched is not None else {}))
        waited = float(getattr(result, 'slot_wait_s', 0.0) or 0.0)
        slot['left'] -= waited
        slot['waited'] += waited
        stages['slot_wait_s'] = round(slot['waited'], 3)
        return result

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
        if reason == 'bad_tests':
            # the contract names a test that is not there: the row goes back to the slicer, no strike
            events.append('bad_tests')
            return end(lambda s, r: (fail_row(s, tid, token, 'reslice:stale'), None), reason='reslice:stale')
        if reason == 'private_edit':
            # the scanner found private text in the files this candidate changed: an ordinary bad edit (a strike)
            return reject('gate', 'private_text', 'the edit carries private text; remove it and do not copy it from elsewhere',
                          [])
        if reason == 'scan_excluded':
            # the second instance: the scanner (or an import the mirror lacks) kept the candidate's test out of the cloud run. The SAME card
            # is asked again with the named cause (class of the hit and line), not charged as a red attempt; after SCAN_REASK_CEILING
            # asks in a row it is an ordinary red attempt, so a card that cannot fix it still ends.
            events.append('scan_excluded')
            try:
                from . import factory_cloud_gate as cloud_gate
                cause = cloud_gate.last_error().get('text') or ''
            except Exception:       # noqa: BLE001
                cause = ''
            cause = scrub(redact(cause))[:300] or 'the scanner excluded the test from the cloud run'
            report['reason_detail'] = cause
            note = ('your test was kept out of the cloud run, it never ran: %s. Fix exactly this (rename, remove or rewrite the text '
                    'the scanner names; import only modules the mirror publishes) and keep the asserts.' % cause)

            def ask_again(state, row):
                table = factory_env(state)['scan_excluded']
                was = table.get(tid) if type(table.get(tid)) is int else 0
                same = table.get(tid + '#cause') == cause       # the text of the last refusal sits beside the count
                seen = (was if same else 0) + 1
                table[tid] = seen
                table[tid + '#cause'] = cause
                # the same cause the second time in a row: the card does not fix it by asking again, a red attempt with the cause
                if seen >= SCAN_SAME_CAUSE_STRIKE or seen > SCAN_REASK_CEILING:
                    table.pop(tid, None)
                    table.pop(tid + '#cause', None)
                    return 'strike'
                add_feedback(state, tid, 'gate', '[attempt %d, no strike] %s' % (attempt, note))
                return 'again'
            if ck.commit(ask_again) == 'strike':
                return reject('gate', 'scan_excluded', note, [])
            return release('scan_excluded', 5)
        if reason in ('cloud_down', 'cloud_busy'):
            # the cloud gave no verdict (down, or no free place): the first thing handled. Not a strike, not counted toward
            # ENV_OTHER_CEILING, never parks the task; the finished candidate waits, the pass is released for a minute.
            events.append(reason)
            try:        # the cause is read before a later answer of the cloud forgets it: stage, error type, 200 characters
                from . import factory_cloud_gate as cloud_gate
                cause = cloud_gate.last_error()
            except Exception:       # noqa: BLE001
                cause = {}
            if cause:
                report['cloud_stage'] = cause['stage']
                report['cloud_error_type'] = cause['type'] or None
                report['cloud_error'] = scrub(redact(cause['text']))[:200]
                report['reason_detail'] = scrub(redact('%s: %s%s' % (cause['stage'], cause['type'] + ': ' if cause['type'] else '',
                                                                     cause['text'])))[:300]
            if candidate:
                report['pending_review'] = bool(ck.commit(lambda state, row: (set_pending(state, row), bool(row.get('pending_review')))[1]))
            if reason == 'cloud_down':
                def count_down(state, row):
                    table = factory_env(state)['cloud_down']
                    table[tid] = (table.get(tid) if type(table.get(tid)) is int else 0) + 1
                    return table[tid]
                try:        # a streak of cloud_down for ONE task while other runs answer is the task's own fault, not the cloud's
                    streak = ck.commit(count_down)
                    from . import factory_cloud_gate as cloud_gate
                    over = streak - cloud_gate.CLOUD_DOWN_STREAK - 1       # 0 at the first alarming pass; one alarm per 5 passes (~5 min) after
                    if over >= 0 and over % 5 == 0 and cloud_gate.alive():
                        events.append('cloud_down_streak')
                        report['cloud_down_streak'] = streak
                        cloud_gate.alarm('cloud_down_streak', task=tid, count=streak, stage=report.get('cloud_stage') or '',
                                         error_type=report.get('cloud_error_type') or '', error=report.get('cloud_error') or '')
                except Exception:       # noqa: BLE001  the alarm never changes the release
                    pass
                try:        # W-noxml 2: more than 3x the alarm streak while other cards still get the cloud's answers: not a dead cloud
                    from . import factory_cloud_gate as cloud_gate
                    stuck = streak > cloud_gate.CLOUD_DOWN_STREAK * 3 and cloud_gate.alive()
                except Exception:       # noqa: BLE001
                    stuck = False
                if stuck:
                    why = ('cloud_down %d times in a row for this card while the cloud answers other cards (%s): '
                           'the candidate or its tests keep the run from giving a result' % (streak, report.get('cloud_error') or 'no cause'))
                    events.append('cloud_down_reslice')

                    def stuck_fail(state, row):
                        factory_env(state)['cloud_down'].pop(tid, None)
                        add_feedback(state, tid, 'gate', '[no strike] ' + why)
                        return fail_row(state, tid, token, 'reslice'), None
                    return end(stuck_fail, reason='reslice', reason_detail=scrub(redact(why))[:300])
            return release(reason, 60)
        events.append('env_shortage')

        def count_it(state, row):
            """The environment counters and the kept candidate, on the fresh state: ONE commit."""
            table = factory_env(state)
            if not reason.startswith('pytest slot:'):
                seen = (table['other'].get(tid) if type(table['other'].get(tid)) is int else 0) + 1
                table['other'][tid] = seen
                if seen >= ENV_OTHER_CEILING:
                    table['other'].pop(tid, None)
                    return 'park', seen, False
            if candidate:      # (the red_before check runs before any candidate exists; a pending one stays as it is)
                set_pending(state, row)
            count = (table['shortages'].get(tid) if type(table['shortages'].get(tid)) is int else 0) + 1
            if reason.startswith('pytest slot:'):
                table['shortages'][tid] = count
            return 'release', count, bool(row.get('pending_review'))
        what, count, pending_now = ck.commit(count_it)
        if what == 'park':
            saved = park_candidate() if candidate else ''
            return block('gate_unknown', "ENV: %s (%d passes in a row; not the candidate fault).%s"
                         % (reason, count, saved), keep=True)
        report['pending_review'] = pending_now
        return release('transient', ENV_HOLD_S if count >= ENV_HOLD_AFTER else INFRA_DEFER_S)

    def base_root() -> Path:
        """Scratch copy of the source tree: the base runs execute untrusted tests, never in the live tree."""
        tree = Path(base_holder) / 'tree'
        if not tree.exists():
            factory_tree.sparse_tree(root, base_holder, {})     # the copy is made by the local gate only, when pytest runs here
            ctx['roots'].append(tree)
        return tree

    baseline_dir = None
    owned, live, parsed = set(), set(), True
    for other_tid, other in ck.read()['tasks'].items():     # fresh: other workers' candidates and leases are theirs
        for held in (other.get('pending_review'), other.get('candidate')):   # an approved candidate waits for its promote
            if held is not None:
                if isinstance(held, dict) and isinstance(held.get('workdir'), str):
                    try:
                        if '\0' in held['workdir']:      # Python 3.13+ resolve() no longer refuses an embedded NUL
                            raise ValueError('embedded null character')
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
            ck.commit(lambda s, r: r.pop('pending_review', None))  # corrupt record: treat as absent
            events.append('pending_dropped')
            pending = None
        baseline_dir = ctx['workdir'] if not pending else staging / (prefix + '-baseline')
        ctx['baseline'] = prepare(root, task, baseline_dir)
        ctx['read_chars'] = sum(len(ctx['baseline'][n]) for n in large_names(task, ctx['baseline']))
        baseline_digest = sha256(b''.join(n.encode() + sha256(v).digest()
                                          for n, v in sorted(ctx['baseline'].items()))).hexdigest()
        if pending:
            old = Path(pending['workdir'])
            inside = inside_staging(old, staging)
            if pending.get('baseline_digest') != baseline_digest or not old.is_dir() or not inside:
                # HEAD moved (or the work copy is gone): the old candidate is void. Start fresh, no strike.
                ck.commit(lambda s, r: r.pop('pending_review', None))
                events.append('pending_dropped')
                if inside and old.is_dir():
                    shutil.rmtree(old, ignore_errors=True)
                ctx['workdir'] = baseline_dir
                pending = None
            else:
                ctx['workdir'] = old.resolve()
                ctx['coder_model'] = pending.get('coder_model')
                ctx['coder_models'] = {m for m in (pending.get('coder_models') or []) if isinstance(m, str)}

        # 1. Base verdict before any model call: green = already done, unknown = infrastructure. A red base measured on
        # the same commit with the same tests and files is reused (base_red): it cannot change, and with a hanging
        # test file it cost 70 s every pass (live 20.11 05:25-05:37).
        # a contract is checked against the fresh snapshot before any model call: a part that no longer fits the code
        # (the file or the function is gone) goes back to the slicer, without a strike (reslice:stale)
        parts_now = []
        if task.kind == 'code' and not pending and K.contract_of(task).get('parts'):
            try:
                parts_now = K.contract_parts(task, root)
            except K.StaleContract as error:
                detail = scrub(redact(str(error)))[:300]
                return end(lambda s, r: (fail_row(s, tid, token, 'reslice:stale'), None), reason='reslice:stale',
                           reason_detail=detail)
        key = _base_key(base_sha, task, ctx['baseline'])
        core, shared = None, None
        if key and task.kind != 'unit_test':
            core = _base_core(root, task, ctx['baseline'])
        held = _held_base(row, key, task.kind, checkpoint.parent, core, base_sha, root)
        if core:
            if held is None:      # W-a3: another executor's measure (disk), or this one's on the commit before a base_moved
                shared = _shared_base_get(core, base_sha, root, checkpoint.parent)
                held = shared
        verdict, base = None, None        # the red base may still be running in the background: closures read None, never an unbound name
        if held is not None:
            verdict, base = 'red', held
            events.append('base_shared' if shared is not None else 'base_reused')
        else:
            red_args = (base_root() if task.kind != 'unit_test' else root, task.tests, GATE_TIMEOUT_S, task.kind)
            red_kwargs = dict(wait_s=(min(RED_BEFORE_WAIT_S, max(0.0, slot['left'])) if slot['armed'] else RED_BEFORE_WAIT_S),
                              workdir=gate_tmp, touched=(), **({'trace': path_trace(task)} if path_trace(task) else {}))

            def measure_base():
                return timed('red_before_s', lambda: gate.red_before(*red_args, **red_kwargs))
            if pending:
                verdict, base = measure_base()      # a candidate is already there: no model call to overlap with
            else:
                # 3.2: the red base is a cloud run too; it goes in the background while the coder answers, and the
                # gates wait for both (settle_base below, right after the first coder call)
                bg_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='red-base')
                bg = bg_pool.submit(measure_base)
        base_fresh = held is None or shared is not None      # a shared base is written on the row too
        base_settled = False
        on_mods, off_mods, off_short, path_focus = {}, {}, [], frozenset()

        def record_base():
            """Keeps a measured red base (the process cache and the row) once."""
            nonlocal base_fresh
            if not base_fresh:
                return
            base_fresh = False
            keep_red = (key and verdict == 'red' and not base.env_reason and task.kind != 'unit_test')
            if keep_red and shared is None:
                _shared_base_put(core, base_sha, task, base, checkpoint.parent)

            def note_base(state, row):
                row.pop('base_red', None)
                if keep_red:
                    kept = dataclasses.asdict(base)
                    if 'path' in kept:      # <id>: the trace goes to traces/<tid>.json, the state keeps only its name
                        try:
                            kept['path_file'] = put_trace(checkpoint.parent, task.id, kept.pop('path'))
                        except (OSError, ValueError, TypeError, IndexError):
                            kept.pop('path_file', None)
                            return          # no place for the trace: no record, the base is measured again next pass
                    row['base_red'] = {'key': key, 'at': _now(), 'result': kept, 'core': core, 'sha': base_sha,
                                       'deps': sorted(_base_deps(task, base)), 'carry': bool(getattr(base, 'path', ()))}
            ck.commit(note_base)

        def bank_base():
            """W-vgs2 3: a pass that ends before settle_base (the coder's 503 / wait) still keeps the red base it paid
            for: the next pass reuses it (base_reused) instead of measuring 17-150 s again (live 24.11 00:53)."""
            nonlocal verdict, base, bg
            if base_settled or bg is None:
                return
            future, bg = bg, None
            try:
                verdict, base = future.result()
                record_base()
            except Exception:       # noqa: BLE001 - a base that cannot be kept is measured again
                pass
        bank_hook.append(bank_base)

        def settle_base():
            """Waits for the red base (a fault of the background run surfaces here, as it did when the call was
            synchronous), records it and reads its path. A dict ends the pass (green / environment / unknown base);
            None goes on. Called once before the first coder call when the base is known already, else right after it."""
            nonlocal verdict, base, bg, base_fresh, base_settled, on_mods, off_mods, off_short, path_focus
            if base_settled:
                return None
            if bg is not None:
                future, bg = bg, None
                verdict, base = future.result()
            record_base()
            ctx['counts'] = base
            base_settled = True
            if verdict == 'green':
                return block('already_green', 'the task tests already pass on the base')
            if verdict == 'unknown' and base.env_reason:
                return env_release(base.env_reason, candidate=False)    # the machine, not the task: never a block
            if verdict == 'unknown':
                report['reason_detail'] = scrub(redact(base.diag))[:300]
                return release_or_block('gate_unknown', INFRA_DEFER_S)

            if verdict == 'red' and is_base_debt(task.backlog_id or tid) and fixture_private(base):
                # W-vgs3 4: the red test needs recordings of calls the mirror does not hold (privacy): not code, not a card
                return end(lambda s, r: (fail_not_code(s, tid, token, 'fixture_private'), None), reason='not_code:fixture_private')

            # the path of the failing tests: on it in the task's files (shown first) / outside them (named, checked)
            on_mods, off_mods = gate.path_split(getattr(base, 'path', ()), task.touch_files) if task.kind == 'code' \
                else ({}, {})
            try:
                off_short = gate.off_path_short(off_mods, root, task.tests, OFF_PATH_SHORT, base.failed_ids) \
                    if off_mods else []
                ranked_on = gate.rank_path(on_mods, root, task.tests, base.failed_ids) if on_mods else []
            except Exception:  # noqa: BLE001 - an order of names only: without it the lists stay unsorted
                off_short = ['%s.%s' % (m.rsplit('/', 1)[-1].rsplit('.', 1)[0], q)
                             for m, qs in off_mods.items() for q in qs][:OFF_PATH_SHORT]
                ranked_on = [(m, q) for m, qs in on_mods.items() for q in qs]
            leaves = [q.rpartition('.')[2] for _, q in ranked_on]
            path_focus = frozenset([n for n in dict.fromkeys(leaves)
                                    if identifier_tokens(n) == {n} and not n.startswith('__')][:PATH_FOCUS_MAX])
            return None

        if bg is None:                              # known now (held / pending): settled before the coder, as before
            early = settle_base()
            if early is not None:
                return early
        held_ne = row.get('no_effect')
        prior_ne = (held_ne['n'] if key and isinstance(held_ne, dict) and held_ne.get('key') == key
                    and type(held_ne.get('n')) is int else 0)

        def no_effects() -> int:
            return prior_ne + events.count('no_effect')

        def off_path_end(detail: str) -> dict:
            """BLOCKED off_path for a task with no contract; for a card of a contract NEVER a block (W-ctx 4): the row goes
            back to the slicer (reslice) with the functions the failing test runs outside the contract in its reason."""
            if K.contract_of(task):         # any contract: parts, a decision, a test to use or to write
                events.append('off_path_reslice')
                text = scrub(redact(detail))[:300]
                return end(lambda s, r: (fail_row(s, tid, token, 'reslice'), None), reason='reslice', reason_detail=text)
            return block('off_path', detail)

        def no_effect_block() -> dict | None:
            """The NO_EFFECT_BLOCK_AFTER-th change without effect on one base, with a path to show: BLOCKED for Opus
            with the functions the failing test runs outside the task (more passes would only repeat it)."""
            if not off_short or no_effects() < NO_EFFECT_BLOCK_AFTER:
                return None
            return off_path_end('the change had no effect %d times on the same base; the failing test runs '
                                'outside the task files: %s' % (no_effects(), ', '.join(off_short)))

        def scope_signal():
            """(module, name) when the last coder answer named a function of the failing test's path outside the task:
            a CANNOT name, or the file of an edit block outside the task; None otherwise."""
            note, text = ctx.get('light_note') or '', ctx.get('last_text') or ''
            said = said_cannot(note, text)
            names = cannot_names(said) if said else []
            if 'outside the task' in note and off_mods:   # the light engine's count of blocks for other files
                names += outside_names(text, tuple(task.touch_files))
            for name in names:
                module = gate.path_lookup(off_mods, name) if off_mods else None
                if module:
                    return module, name
            if task.kind == 'code':     # 21.11: a CANNOT naming any repo file or function outside the task: same path
                for name in cannot_names(said) if said else []:
                    module = repo_scope_target(root, name, task.touch_files, task.kind)
                    if module:
                        return module, name
            return None

        def cannot_loop():
            """The same CANNOT text twice in a row and no widening possible: more attempts would only repeat it;
            BLOCKED with the text as the reason (the existing quarantine), None otherwise."""
            note, text = ctx.get('light_note') or '', ctx.get('last_text') or ''
            said = said_cannot(note, text)
            if said and cannot_repeats(row.get('feedback'), said, scrub):
                return block('cannot_repeat', 'the model answered the same CANNOT twice in a row and no repo file or '
                             'function it names can be added to the task: ' + said.strip()[:150])
            return None

        def widen(module: str, name: str) -> dict:
            """The task's scope misses a module the failing test runs and the model named: the loop adds it to
            touch_files (report scope_add, no strike); over LIGHT_MAX_FILES or a forbidden path: BLOCKED for Opus."""
            limit = LIGHT_MAX_FILES
            why = gate.is_forbidden(module, task.kind) or (
                'more than %d files' % limit if len(task.touch_files) + 1 > limit else '')
            if why:
                return off_path_end('%s (%s) runs in the failing test outside the task; it cannot be added: %s'
                                    % (module, name, why))
            events.append('scope_add:' + module)
            report['scope_add'] = [module]
            report['reason_detail'] = scrub(redact('%s (%s) runs in the failing test outside the task' % (module, name)))
            return release('off_path', OFF_PATH_WAIT_S)

        def red_on(model) -> None:
            """<id>: the test ids the candidate of ``model`` was red on, for the loop's audit of a factory test."""
            ids = sorted(getattr(ctx.get('counts'), 'failed_ids', ()) or ())
            ctx.setdefault('gate_red', []).append([str(model or ''), ids])

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
            # the agent path (the model writes the files itself) keeps the gate's rejection with the exact marker line;
            # the runner writes a forgotten marker only for the edit-block answer of the contract card (see below)
            cand_files = {n: ctx['workdir'].joinpath(*n.split('/')).read_text(encoding='utf-8', errors='replace')
                          for n in changed}
            for name, source in cand_files.items():
                if name.endswith('.py'):
                    try:
                        compile(source, name, 'exec')
                    except (SyntaxError, ValueError) as error:
                        return reject('gate', 'gate: compile error in ' + name,
                                      'does not compile: %s' % error, changed)
                elif name.endswith(('.json', '.toml')):      # the standard library reads them: a parse error is red
                    try:
                        json.loads(source) if name.endswith('.json') else tomllib.loads(source)
                    except ValueError as error:
                        return reject('gate', 'gate: parse error in ' + name, 'does not parse: %s' % error, changed)
            problems = gate.weakening_violations(root, cand_files, task.kind, task.touch_files, rig=gate.is_rig_task(task))
            if problems:
                text = '; '.join(problems)
                return reject('gate', 'weakening: ' + text[:300], 'weakening of the checks: ' + text, changed)
            if parts_now:       # W-intake: the one rule check of a contract's edit (the author's cloud try calls it too)
                rules = gate.contract_rules(root, dict(K.contract_of(task), parts=parts_now), cand_files, ready=ready_card(task),
                                         by_files=proven_code(task))
                off = [f.partition(': ')[2] for f in rules if f.startswith(('off_contract: ', 'test_touched: '))]
                if off:     # the candidate's slip (another function, an accepted test changed): one more try, not a strike
                    text = 'the edit is outside the contract: ' + ', '.join(off)
                    return _GateRetry(('gate', 'gate: off_contract', text, changed), text, changed)
                if rules and ready_card(task):
                    return ready_return('the contract rules: ' + '; '.join(rules))     # fac-52: the author's contract, no model mends it
                if rules:
                    text = '; '.join(rules)
                    return reject('gate', 'gate: contract rules: ' + text[:300], 'the contract rules: ' + text, changed)
            if task.kind == 'unit_test':
                if gate.SELF_REPO:
                    events.append('unit_test_marker_not_required')   # the second instance: the row is known from the task
                elif task.backlog_id:
                    first = next((n for n in changed if n in task.tests), task.tests[0])   # the first CHANGED test file
                    marker_ok, marker_why = gate.accept_unit_test(MARKER_PROBE, cand_files.get(first, ''), task.backlog_id)
                    if not marker_ok:   # cheaper than running pytest first
                        return reject('gate', 'gate: ' + marker_why[:300], marker_why, changed)
                else:
                    events.append('unit_test_marker_skipped')   # nothing to check against: never an unfixable rejection
            try:      # mechanical facts for the critics (never a verdict): hollow findings, names added beyond the task
                ctx['hollow'], ctx['extra_names'] = gate.candidate_findings(root, cand_files, task.kind)
            except Exception:       # noqa: BLE001  a report fault must not stop the gate
                ctx['hollow'], ctx['extra_names'] = (), ()
            with tempfile.TemporaryDirectory(prefix='factory-gate-tree-', ignore_cleanup_errors=True) as d:
                tree = candidate_tree(root, ctx['workdir'], changed, Path(d))
                ctx['roots'].append(tree)
                # the gate decides whether a missing module is the environment or the candidate's own import (live
                # 19.11 18:06-18:08: written tests imported modules that do not exist and went round as 'environment')
                if task.kind != 'unit_test':     # the neighbour tests ride in the candidate's cloud run (one list of ids)
                    try:
                        gate.offer_companions(tree, gate_order(root, neighbor_tests(root, task)[:MAX_NEIGHBORS], ctx.get('neighbour_red', ())))
                    except Exception:       # noqa: BLE001 - the neighbours then get a run of their own, as before
                        pass
                red_ids = [i for _, ids in ctx.get('gate_red', ()) for i in ids]
                cand = gate.candidate_import(timed('gate_s', lambda: staged_run(
                    lambda part: gate_run(tree, part, touched=changed), root, task.tests,
                    red_entries(red_ids, task.tests))), root, tree, changed)
                ctx['counts'] = cand
                if cand.env_reason:
                    return env_release(cand.env_reason)
                def measured(state, row):       # measured: both environment series are over
                    factory_env(state)['shortages'].pop(tid, None)
                    factory_env(state)['other'].pop(tid, None)
                    factory_env(state)['cloud_down'].pop(tid, None)
                ck.commit(measured)
                # pytest executes untrusted code: it may not rewrite the frozen tests or inputs.
                for name in sorted((set(task.tests) | set(task.read_files)) - set(changed)):
                    original, after = root.joinpath(*name.split('/')), tree.joinpath(*name.split('/'))
                    if factory_tree.is_sparse(tree):
                        break                   # no pytest ran in this tree (the cloud ran it): nothing here could be rewritten
                    if original.is_file() and (not after.is_file() or after.read_bytes() != original.read_bytes()):
                        return reject('gate', 'gate: immutable file changed during pytest',
                                      'pytest changed a frozen file: ' + name, changed)
                if task.kind == 'unit_test':
                    added = []
                    for name in changed:     # the test functions this candidate ADDS (all of a new file)
                        if name in task.tests and name.endswith('.py'):
                            before = root.joinpath(*name.split('/'))
                            old_text = before.read_text(encoding='utf-8', errors='replace') if before.is_file() else ''
                            added += gate.added_tests(old_text, cand_files.get(name, ''))
                    ok, why = gate.accept_unit_test(cand, added=added)
                    if ok:       # the critics get the failing assert of the new test on the base as its red-before evidence
                        ctx['red_evidence'] = red_evidence(cand.diag)
                else:
                    ok, why = gate.accept(base, cand, verdict == 'red')
                    part_left = gate.partial_left(base, cand, gate.target_names(K.contract_of(task))) if not ok and verdict == 'red' else None
                    if part_left:       # the target is green and nothing new is red: the other reds of the file are other rows' work
                        ok, why = True, 'ok'
                        events.append('partial_green:%d' % len(part_left))

                    def note_left(state, row):
                        mine = state['tasks'][tid]
                        mine.pop('reds_left', None)
                        if part_left:
                            mine['reds_left'] = list(part_left)[:20]
                    ck.commit(note_left)
                if not ok and why.startswith('env:'):
                    return env_release(why)
                if not ok and task.kind != 'unit_test' and gate.undecided(base, cand):
                    # the budget left tests unrun and nothing that ran is red: not this candidate's failure, and the next
                    # model would spend the same budget again; the third such pass in a row blocks it (ESCALATE)
                    events.append('gate_undecided:%d' % len(cand.unrun))
                    report['reason_detail'] = ('%d test(s) of the task were not run here (the gate budget was spent); '
                                               'nothing that ran is red' % len(cand.unrun))
                    return release_or_block('gate_unknown', INFRA_DEFER_S)
                if not ok:
                    no_effect = task.kind != 'unit_test' and same_failure(base.diag, cand.diag)
                    if no_effect:
                        events.append('no_effect')
                    return _GateRetry(('gate', 'gate: ' + why[:300],
                                       ('[no effect] ' if no_effect else '') + why + '\n' + cand.diag, changed),
                                      cand.diag or why, changed, no_effect)
                left = gate.unmeasured(base, cand) if task.kind != 'unit_test' else ()
                if left:      # accepted on every test that ran; these hang or lack a package here on both sides
                    events.append('unmeasured:%d' % len(left))
                if task.kind != 'unit_test':
                    try:
                        near = gate_order(root, neighbor_tests(root, task)[:MAX_NEIGHBORS], ctx.get('neighbour_red', ()))
                    except Exception as error:  # noqa: BLE001 - "graph unavailable" is not "no neighbours"
                        events.append('neighbors_unavailable:' + redact(type(error).__name__))
                        near = []
                    if near:
                        def neighbours():
                            skipped_count = 0
                            last_result = None
                            settled = gate.cloud_each(tree, near)     # one cloud run for all of them; {} = route off: local
                            if isinstance(settled, str):          # the cloud gave no verdict (down / busy): nothing runs here
                                return 'env', replace(gate._failure(-1, 'cloud: ' + settled), env_reason=settled)
                            for name in near:
                                mine = settled[name] if name in settled else gate_run(tree, [name])
                                last_result = mine
                                if mine.env_reason:
                                    return 'env', mine
                                if not mine.junit_ok and not (mine.failed or mine.errors):
                                    skipped_count += 1
                                    continue
                                if mine.failed + mine.errors > 0:
                                    theirs = gate_run(base_root(), [name], touched=())
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
                                        ctx.setdefault('neighbour_red', []).append(name)
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
                            ck.commit(lambda s, r: set_pending(s, r))
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
            feedback = fresh_feedback(state, tid)       # the state of the start of the pass: its own feedback is final
            feedback = scrub(feedback) if feedback else feedback
            prev_diff = prev_diff_file.read_text(encoding='utf-8') if prev_diff_file.is_file() else ''
            role = 'repair' if (feedback or attempt > 1) else 'code'
            visible = {name: safe_source(ctx['workdir'] / name) for name in
                       sorted(set(task.touch_files + task.read_files + task.tests))
                       if (ctx['workdir'] / name).exists()}
            # the reviewer sees the small files whole plus its instructions and a diff: refuse BEFORE the coder is paid for
            small_total = sum(len(v) for n, v in visible.items() if n not in large_names(task, visible))
            has_contract = bool(parts_now) or bool((K.contract_of(task).get('test') or {}).get('new'))
            if not has_contract and small_total + REVIEW_DIFF_LIMIT + REVIEW_OVERHEAD > channels.PROMPT_LIMIT_CHARS:
                raise PromptTooLarge('coder+review prompts cannot both fit')
            def failing_text() -> str:       # the red base may still be running when the first prompt is built
                return K.failure_block(base.failed_ids, base.diag) if task.kind == 'code' and base_settled and base is not None else ''
            def off_bodies_text() -> str:    # the code the failing test runs outside the task files, once the red base is in
                if task.kind != 'code' or not base_settled or base is None or not off_mods:
                    return ''
                try:
                    return gate.off_path_bodies(off_mods, root, task.tests, base.failed_ids)
                except Exception:       # noqa: BLE001 - an addition to the card: without it the card is as before
                    return ''
            # ``root`` is the loop's plain copy of the sources (no .git): an old commit is read from the repository itself
            reference = port_reference(port_repo or root, task)
            if reference:
                events.append('port_reference:%d' % len(reference))
            elif task.port_from and task.kind != 'unit_test':
                events.append('port_reference_missing')      # a lost example shows in the telemetry, never silently
            ported = port_focus(port_repo or root, task) if reference else frozenset()
            remembered = frozenset(state['tasks'][tid].get('asked') or ()) & defined_names(task, ctx['workdir'])

            test_new = task.kind == 'unit_test' and bool(((K.contract_of(task).get('test') or {}).get('new') or {}).get('path'))
            # the architect's own test text (test.new.code): the first attempt applies it as the candidate, no model call
            architect_new = ((K.contract_of(task).get('test') or {}).get('new') or {}) if test_new else {}
            architect_code = architect_new.get('code') if isinstance(architect_new.get('code'), str) else ''
            architect_code = architect_code if architect_code.strip() and architect_new.get('path') in task.tests else ''
            architect_author = str(K.contract_of(task).get('author') or 'architect')

            def apply_architect_code() -> bool:
                """Writes test.new.code as the candidate (the marker line included); False when it cannot be written."""
                name = architect_new['path']
                target = ctx['workdir'].joinpath(*name.split('/'))
                try:
                    if target.exists():
                        return False
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(architect_code.replace('\r\n', '\n').encode('utf-8'))
                    ensure_test_marker(task, ctx['workdir'], [name])
                except OSError:
                    return False
                ctx['light_note'] = ctx['last_text'] = ''
                events.append('architect_test_applied')
                return True

            def contract_test_card(note: str = '') -> str:
                """A test task whose contract names the test (given / when / then / why it is red now): the card is
                written from the contract, and the code of its functions is shown read-only; '' for any other task."""
                contract = K.contract_of(task)
                new = (contract.get('test') or {}).get('new') if task.kind == 'unit_test' else None
                if not isinstance(new, dict) or not new.get('path'):
                    return ''
                regions, problems, sigs, symbols = {}, [], [], []
                for part in contract.get('parts') or []:
                    try:
                        source = (root / part['file']).read_text(encoding='utf-8-sig')
                        regions[part['file']] = K.part_region(source, part.get('symbols') or [], part.get('anchor') or '')
                    except (OSError, ValueError, SyntaxError, KeyError, TypeError) as error:
                        # the code is not shown: the card says so (never silently), the model may answer CANNOT
                        problems.append('%s: %s: %s' % (part.get('file', '?') if isinstance(part, dict) else '?',
                                                        type(error).__name__, str(error)[:200]))
                        continue
                    symbols.extend(part.get('symbols') or [])
                    sigs.extend(K.signature_lines(source, part.get('symbols') or [], part['file']))
                try:
                    example = K.example_test(root, symbols)
                except Exception:       # noqa: BLE001 - a missing example never stops the card
                    example = ''
                extra = ''
                if task.backlog_id and not gate.SELF_REPO:
                    extra += ("The test file does not exist yet: use an EMPTY SEARCH part. The FIRST line of the REPLACE "
                              "part must be exactly: # factory-backlog-id: " + task.backlog_id +
                              " . Never put the marker into SEARCH.\n")
                elif gate.SELF_REPO:
                    extra += "The test file does not exist yet: use an EMPTY SEARCH part. No marker line is needed.\n"
                extra += unit_rules() + "\n"
                if architect_code and (feedback or attempt > 1 or note):
                    extra += ("The architect wrote this test text; it was applied and rejected (the exact reason is below). "
                              "Correct THIS code, do not write another test from nothing:\n" + redact(architect_code) + "\n")
                if feedback:       # the feedback shrinks first (the oldest lines go), the card keeps its fixed blocks
                    extra += "The previous candidate was rejected. Feedback:\n" + redact(feedback)[-FEEDBACK_CARD_CHARS:] + "\n"
                # the read-only code and the example are squeezed to what the rest leaves (task W-ctx 1): a card over the
                # limit is no BLOCKED context_too_large that comes round, it is a reslice (CardTooLarge below). The note
                # of an earlier candidate (its failing line and the real shape of the code) rides inside the limit too.
                for tail in ((note + extra) if note else extra, extra):
                    try:
                        card = K.test_prompt(task, contract, regions, signatures='\n'.join(sigs), example=example,
                                             problems=problems, limit=channels.PROMPT_LIMIT_CHARS, reserve=len(tail) + 1)
                    except K.CardTooLarge:
                        if tail is extra:
                            raise
                        continue
                    return card + tail
                return ''

            def make_prompt(asked=frozenset(), note=''):
                if parts_now:       # contract_flow writes the card of each part itself; the whole-file prompt is not used
                    return ''
                card = contract_test_card(note)
                if card:
                    return card
                return build_coder_prompt(task, visible, feedback, prev_diff, failing=scrub(failing_text()),
                                          light=engine_for(role, task) == 'light',   # the same rule call() applies
                                          asked=frozenset(asked) | remembered, reference=reference, focus=ported | path_focus, off_path=tuple(off_short),
                                          off_bodies=off_bodies_text(), failing_chars=FAILING_CHARS)
            prompt = make_prompt()
            chosen = route(task, small_model=small_model, large_model=large_model, fallback=attempt > 1)

            def dir_for(retry: int) -> Path:
                if retry:  # a failed worker may have written files; never reuse its directory
                    # W-gemma 3: the second candidate's hop must not meet the first one's retry directory (FileExistsError, os_error)
                    ctx['workdir'] = staging / (prefix + ("-c%d" % ctx['candidate'] if ctx.get('candidate') else "") + "-retry-" + str(retry))
                    ctx['baseline'] = prepare(root, task, ctx['workdir'])
                return ctx['workdir']

            def unusable() -> str:
                """Step 3's mechanical checks, without a strike: why this candidate cannot go to the gate ('' when it
                can). A candidate that fails them makes room for the tournament's next model."""
                now = inspect_changes(task, ctx['workdir'], ctx['baseline'])
                if not now:
                    # the next model hears it in the words of a part (W-ctx 2): the edit changed nothing, and why
                    return part_failure(ctx.get('light_note') or '', False)
                if ensure_test_marker(task, ctx['workdir'], now):
                    events.append('marker_autofixed')
                texts = {n: ctx['workdir'].joinpath(*n.split('/')).read_text(encoding='utf-8', errors='replace')
                         for n in now}
                for name, source in texts.items():
                    if name.endswith('.py'):
                        try:
                            compile(source, name, 'exec')
                        except (SyntaxError, ValueError) as error:
                            return 'its edit of %s does not compile (%s)' % (name, error)
                if gate.weakening_violations(root, texts, task.kind, task.touch_files, rig=gate.is_rig_task(task)):
                    return 'its edit weakened a check'
                if task.kind == 'unit_test' and task.backlog_id:
                    first = next((n for n in now if n in task.tests), task.tests[0])
                    ok, why = gate.accept_unit_test(MARKER_PROBE, texts.get(first, ''), task.backlog_id)
                    return '' if ok else why
                return ''

            def test_error_hint(diag: str) -> str:
                """W-ctx 3: a test that does not collect or crashes before its assertion is asked again with the exact
                error line AND the real shape of the object it fell on (class, __init__, fields, exported names: the
                AST of the snapshot), never only 'it failed'."""
                if not any(m in (diag or '') for m in ('Error', 'collection', 'не собирается', 'crashes before')):
                    return ''
                contract = K.contract_of(task)
                files = [p['file'] for p in contract.get('parts') or [] if isinstance(p, dict) and p.get('file')]
                symbols = [s for p in contract.get('parts') or [] if isinstance(p, dict) for s in p.get('symbols') or []]
                try:
                    return K.signature_hint(root, scrub(redact(diag)), files, symbols)
                except Exception:       # noqa: BLE001 - a missing hint never stops the repeat
                    return ''

            def gate_note(failure) -> str:
                """The note for the next coder after a real test failure: the failing output (scrubbed, redacted) and the
                diff of the candidate. Over PROMPT_LIMIT_CHARS the diff goes first, then the output is shortened."""
                output = scrub(redact(failure.diag))[:TOURNAMENT_OUTPUT_LIMIT]
                diff = unified_diff(ctx['baseline'], ctx['workdir'], failure.changed, DIFF_LIMIT)
                room = channels.PROMPT_LIMIT_CHARS - len(prompt) if not test_new else GATE_NOTE_ROOM   # the contract card squeezes its code
                lead = (NO_EFFECT_NOTE + (OFF_PATH_NOTE % ', '.join(off_short) if off_short else '')
                        if getattr(failure, 'no_effect', False) else '')
                hint = test_error_hint(failure.diag) if task.kind == 'unit_test' else ''
                for part in (TOURNAMENT_DIFF_NOTE % diff if diff else '', ''):
                    note = lead + TOURNAMENT_GATE_NOTE % output + hint + part
                    if len(note) <= room:
                        return note
                fixed = len(TOURNAMENT_GATE_NOTE % '')
                return TOURNAMENT_GATE_NOTE % output[:max(0, room - fixed)] if room > fixed else ''

            def coder_exclusions(tried_now):
                """``exclude_model`` of a coder call. ``tried_now`` (this pass's earlier candidates) are always out; the
                models that failed this task in earlier attempts are out too while the router has another model for
                the call (factory_router.allowed: a preference, never a reason to stop: with none left the call takes any)."""
                now_out = list(tried_now)
                older = [m for m in failed_models_of(row) if m not in now_out]
                if older and configured:
                    live_now = live_quotas()
                    rest, lifted = factory_router.allowed(channels.route_order(
                        configured, 'code', attempt, channels.estimate_tokens(len(prompt), 0),
                        exclude_model=now_out, state=live_now), live_now, os.environ, older)
                    if rest and not lifted:   # a dead channel (checked with the call's own env) is no other model
                        tag = 'other_model_than_%d' % len(older)
                        if tag not in events:
                            events.append(tag)
                        return now_out + older
                return now_out or None

            gate_failed = []

            def contract_flow():
                """The card of a contract: one call per part (edit_parts), the parts of a stage at once. The first attempt
                has ONE candidate; from the second, two candidates of different models at once (the tournament), which
                go to the gates as they are ready: the first green one stands. The gates run once per candidate, over the
                union of its parts, and there are no repair rounds inside the pass: a red gate ends the candidate."""
                plan_k, main_step = 0, False
                vgs_key = vgs_input_key(task)
                if defer_streak(ck.read(), tid, 'transient', vgs_key) + 1 >= ESCALATE_AFTER:
                    # W-a2: this very input got no answer of the ensemble pass after pass: the input changes (the main step,
                    # one call per part), it is not asked again the same way
                    main_step = True
                    events.append('vgs_input_changed')
                if not main_step and configured and VGS_ON and not os.environ.get('FACTORY_NO_VGS'):
                    try:    # W-vgs 3/6: the router's draw for this edit puts the small tier first and it has free channels
                        # now: the ensemble, BIG_PER_CHANNEL calls a channel; else one call per part on the router's model
                        live_small = live_quotas()
                        head = call_order('edit', None, 0, None, [], (), False, live_small, True, 1, sink=[])
                        if not head or channels.tier_of(head[0]) != 'small':
                            raise LookupError('the router leads with another tier')
                        small_all = [c for c in configured if channels.tier_of(c) == 'small' and not channels.is_reserve(c)]
                        head_state = (Path(ledger).parent / factory_head.STATE_NAME) if ledger is not None else None
                        got_k = None
                        if factory_head.alive(head_state):
                            # W-bucket: a live head alone gives the width: places in tokens of its buckets (free within 30 s, minus
                            # the queued tokens), kept for this card; the old cooling marks of the ledger are not asked
                            try:
                                got_k = factory_head.grant(head_state, [c['id'] for c in small_all], VGS_K_MAX, tokens=EDIT_EST,
                                                           k_max=VGS_K_MAX, card=tid)
                                events.append('head_grant_%d_of_%d' % (got_k, VGS_K_MAX))
                            except factory_head.HeadDown:
                                got_k = None
                        if got_k is not None:
                            plan_k = got_k
                        else:               # no head: the card's own count of the ledger
                            free_n = 0
                            room_k = 0
                            for c in channels.usable(small_all, live_small, os.environ):
                                try:
                                    channels.choose([c], live_small, 1, os.environ, grace=channels.OPEN_SOON_S)
                                    free_n += 1
                                    # fac-yield: a real edit reserves ~EDIT_EST tokens: the branches a channel's minute window holds
                                    room_k += min(channels.BIG_PER_CHANNEL, channels.tpm_room(live_small, c, EDIT_EST))
                                except channels.ChannelUnavailable:
                                    pass
                            plan_k = min(VGS_K_MAX, channels.BIG_PER_CHANNEL * free_n, room_k)
                        if plan_k < 2:      # no room for an ensemble: the main step (one call per part), not a 120 s hopeless pass
                            plan_k = 0
                    except Exception:       # noqa: BLE001 - a view that cannot be read is the old path
                        plan_k = 0
                count = 1 if (attempt <= 1 or plan_k) else 2
                part_author = str(K.contract_of(task).get('author') or '')
                if part_author and any(isinstance(p, dict) and p.get('code') for p in parts_now):
                    ctx['coder_models'].add(part_author)     # W-dry 2: the model that wrote parts[].code never reviews it alone
                if attempt > 1 or feedback:    # a repeat shows the exact failing line: the red base must be in (a first pass overlaps it)
                    early = settle_base()
                    if early is not None:        # green / environment / unknown base ends the pass before any model call
                        return early
                # the failing block (ids and the last 12 lines of the failure: assert with its values) from the first
                # attempt on (empty while the red base runs); the same text on every repeat of a part
                line = scrub(failing_text())
                part_trace = tuple(getattr(base, 'path', ()) or ()) if base_settled and base is not None else ()
                part_fail_ids = tuple(getattr(base, 'failed_ids', ()) or ()) if base_settled and base is not None else ()
                see = {}        # the context pack of the parts: context_chars, context_sections (telemetry)
                models = [set() for _ in range(count)]
                first_booked = threading.Event()
                older = [m for m in failed_models_of(row) if isinstance(m, str)]

                part_tried: dict = {}       # (candidate, file) -> the models that already answered that part
                last_model: dict = {}       # (candidate, file) -> the model of the newest call for that part

                def part_call(k, part_task, directory, text):
                    waited = 0.0
                    part_key = part_task.touch_files[0] if part_task.touch_files else ''
                    own = part_tried.setdefault((k, part_key), set())
                    while True:
                        mine = set().union(*(models[j] for j in range(count) if j != k))
                        # a part asked again goes to ANOTHER model than the ones that already gave it an unusable
                        # answer (a preference: with no other model free the call takes any, below)
                        out = sorted(mine | own | (set(older) - mine))

                        def booked(model, k=k, own=own, part_key=part_key):
                            own.add(model)
                            last_model[(k, part_key)] = model
                            if k == 0:
                                first_booked.set()
                        extra = dict(later=bool(k), candidate=k, models_out=models[k], on_booked=booked)
                        try:
                            try:
                                return past_day_limit(lambda: call('edit', part_task, lambda _retry: directory, chosen, text,
                                                                   exclude_model=out or None, **extra))
                            except (channels.ChannelUnavailable, NoIndependentReviewer):
                                if len(out) <= len(mine):
                                    raise
                                events.append('other_model_none_free')
                                return call('edit', part_task, lambda _retry: directory, chosen, text,
                                            exclude_model=sorted(mine) or None, **extra)
                        except channels.ChannelUnavailable as error:
                            if error.reason in INFRA_CHANNEL_REASONS:
                                raise
                            if waited >= PART_WAIT_S:      # no free channel in time: deferred, no strike
                                raise ChannelFault({'kind': 'rate_minute', 'part_wait': True}, error.wait_s)
                            step = min(max(1.0, error.wait_s), PART_WAIT_S - waited)
                            time.sleep(step)
                            waited += step

                small_models = sorted({c['model'] for c in configured if channels.tier_of(c) == 'small'
                                       and not channels.is_reserve(c)})
                vgs_state = {'gates': 0, 'green_at': None}

                def vgs_ask(part_task, directory, text, n, temperature, channel):
                    """One ensemble call: small tier only, on ``channel`` (a model name) when there is a choice; a refused or
                    busy channel is no answer (ENS.ChannelRefused). Returns (rc, out, err, model)."""
                    got: list = []
                    others = [m for m in small_models if m != channel] if channel else []
                    left = getattr(_ENS_LEFT, 'left', None)      # fac-68: the ensemble's remaining term bounds the head's wait
                    try:
                        rc, out, err = call('edit', part_task, lambda _retry: directory, chosen, text,
                                            exclude_model=others or None, skip_tiers=('main', 'escalation'),
                                            candidate=0, on_booked=got.append, temperature=temperature,
                                            fast_retry=True,
                                            wait_budget=types.SimpleNamespace(left=left, spend=lambda s: None) if left else None)
                    except ChannelFault as error:
                        info = error.info or {}
                        if info.get('kind') == 'transient' and info.get('status') in channels.OVERLOAD_STATUSES:
                            raise ENS.ChannelRefused(str(error), kind='overload') from error
                        if info.get('kind') == 'rate_day':
                            raise ENS.ChannelRefused(str(error), kind='day') from error
                        if info.get('kind') == 'rate_minute':
                            raise ENS.ChannelRefused(str(error), kind='minute',
                                                     wait_s=error.wait_s or info.get('retry_after_s') or 0) from error
                        raise ENS.ChannelRefused(str(error)) from error
                    except channels.ChannelUnavailable as error:
                        raise ENS.ChannelRefused(str(error), kind='minute', wait_s=getattr(error, 'wait_s', 0) or 0) from error
                    except (NoIndependentReviewer, PromptTooLarge) as error:
                        raise ENS.ChannelRefused(str(error)) from error
                    return rc, out, err, (got[-1] if got else None)

                small_ids = [c['id'] for c in configured if channels.tier_of(c) == 'small' and not channels.is_reserve(c)]

                def vgs_capacity():
                    """W-a2: the head's free places of the small channels; None without a head (HeadDown: it does not answer)."""
                    state = (Path(ledger).parent / factory_head.STATE_NAME) if ledger is not None else None
                    return (factory_head.capacity(state, small_ids, tokens=EDIT_EST, k_max=VGS_K_MAX, card=tid)
                            if factory_head.alive(state) else None)

                vgs = VgsPlan(plan_k, vgs_ask, small_models if len(small_models) > 1 else None,
                              capacity=vgs_capacity) if plan_k else None
                if vgs is not None:
                    vgs.input_key = vgs_key

                def vgs_gates(found):
                    """W-vgs 4: the first union was red: the next ready unions go to the gates in turn (no new model call),
                    at most VGS_ALTS more. The first green stands. The reds are one strike for the pass (the caller counts
                    it once, after the last candidate); the diff and the evidence stay those of the last one."""
                    home, base_home = ctx['workdir'], ctx['baseline']
                    last = dict(ctx)
                    for number, (file, raw, model) in enumerate(vgs.alts, 2):
                        where = staging / ('%s-vgs-%d' % (prefix, number))
                        shutil.rmtree(where, ignore_errors=True)
                        shutil.copytree(home, where)
                        target = where / file
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(raw)
                        ctx.update(workdir=where, baseline=base_home)
                        if model:
                            models[0] = {model}
                        events.append('vgs_union_%d' % number)
                        if unusable():           # the mechanical checks again: not a gate try
                            continue
                        vgs_state['gates'] += 1
                        found = run_gates()
                        if not isinstance(found, _GateRetry):
                            if isinstance(found, tuple):
                                vgs_state['green_at'] = vgs_state['gates']
                            return found
                        if last.get('workdir') != home and last.get('workdir') != where:
                            shutil.rmtree(last['workdir'], ignore_errors=True)    # an older union: its evidence is superseded
                        last = dict(ctx)
                    ctx.update(last)            # the evidence and the diff belong to the last union that really ran
                    return found

                def run_candidate(k):
                    where = ctx['workdir'] if k == 0 else staging / ('%s-cand-%d' % (prefix, k))
                    try:
                        if k:
                            first_booked.wait(10)           # the second candidate knows the model of the first one
                            shutil.rmtree(where, ignore_errors=True)
                            base_k = prepare(root, task, where)
                        else:
                            base_k = ctx['baseline']
                        code, text, note = edit_parts(task, parts_now, where,
                                                      lambda pt, d, p: part_call(k, pt, d, p), failing=line,
                                                      use_code=paid_critic.agent_card(task) or (attempt <= 1 and not feedback and not k),   # a strong author's code is applied again after a deferral, never rewritten
                                                      trace=part_trace, fail_ids=part_fail_ids, info=see,
                                                      on_event=events.append,
                                                      who=lambda f, k=k: last_model.get((k, f)),
                                                      vgs=vgs if not k else None, root=root,
                                                      previous=(feedback, prev_diff) if feedback else None)
                        if vgs is not None and vgs.winners and not k:
                            models[0] = set(vgs.winners)    # only the models whose text stands are the authors
                    finally:
                        if k == 0:
                            first_booked.set()
                    return {'k': k, 'workdir': where, 'baseline': base_k, 'rc': code, 'text': text, 'note': note}

                fails, errors, retry, outcome = [], [], None, None
                report['fanout'] = {'parts': len(parts_now), 'candidates': count}
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                        futures = [pool.submit(run_candidate, k) for k in range(count)]
                        left = count
                        for future in concurrent.futures.as_completed(futures):
                            left -= 1
                            try:
                                cand = future.result()
                            except (ChannelFault, channels.ChannelUnavailable, NoIndependentReviewer) as error:
                                errors.append(error)
                                continue
                            used = sorted(models[cand['k']])
                            ctx.update(workdir=cand['workdir'], baseline=cand['baseline'], light_note=cand['note'],
                                       last_text=cand['text'], coder_model=used[0] if used else ctx['coder_model'])
                            if cand['rc'] and STALE_MARK in str(cand['note']):
                                # two models said the named place is not there: back to the slicer, no strike
                                outcome = end(lambda s, r: (fail_row(s, tid, token, 'reslice:stale'), None),
                                              reason='reslice:stale',
                                              reason_detail=scrub(redact(str(cand['note'])))[:300])
                                break
                            if cand['rc']:          # a part stayed unapplied after its re-asks: a red attempt
                                fails.append(('gate', 'gate:part_failed', cand['note'], ()))
                                continue
                            why = unusable()
                            if why and left:         # the other candidate may still be usable
                                fails.append(('gate', 'gate:unusable', why, ()))
                                continue
                            early = settle_base()    # the red base runs in the background: the gates judge against it, so wait for it here
                            if early is not None:    # green / environment / unknown base ends the pass
                                outcome = early
                                break
                            found = run_gates()
                            if vgs is not None:
                                vgs_state['gates'] = 1
                                if isinstance(found, tuple):
                                    vgs_state['green_at'] = 1
                                elif isinstance(found, _GateRetry) and vgs.alts and cand['k'] == 0:
                                    found = vgs_gates(found)
                                    used = sorted(models[0])
                                    if used:
                                        ctx['coder_model'] = used[0]
                            if isinstance(found, _GateRetry):
                                gate_failed.append(ctx['coder_model'])
                                red_on(ctx['coder_model'])
                                retry = (found, dict(ctx))
                                continue
                            outcome = found
                            break
                finally:
                    ctx['coder_models'] |= set().union(*models)
                    if vgs is not None:
                        report['vgs'] = dict(vgs.stats, k=vgs.stats['k'] or vgs.k, gates=vgs_state['gates'],
                                             green_at=vgs_state['green_at'])
                    report['context_chars'] = see.get('context_chars', 0)
                    report['context_sections'] = see.get('context_sections', [])
                    if see.get('code_applied') and not see.get('model_asked'):
                        report['edit_by'] = 'code'      # every part was the architect's code, applied without a model
                if outcome is not None:
                    return outcome
                if retry is not None:
                    ctx.update(workdir=retry[1]['workdir'], baseline=retry[1]['baseline'],
                               coder_model=retry[1]['coder_model'], counts=retry[1]['counts'])
                    return retry[0]
                if not fails:
                    raise errors[0]
                return reject(*fails[-1])

            size = 0 if parts_now else (TOURNAMENT_SIZE if configured and engine_for(role, task) == 'light' else 1)
            tried, k_prompt, held, next_note = [], prompt, None, ''
            ctx['tried'] = tried     # the models of this pass's earlier candidates: reject() remembers them as failed
            if parts_now:
                decision = contract_flow()
            asked = frozenset()      # code an earlier candidate of this pass asked for: every later one is shown it
            for k in range(size):
                if k:
                    held = (ctx['workdir'], ctx['baseline'])
                    tried.append(ctx['coder_model'])
                    view = make_prompt(asked, next_note if test_new else '')   # the first prompt may predate the base; later ones carry it
                    k_prompt = view if test_new else view + next_note        # a contract test card holds the note inside its limit
                    if channels.prompt_too_big(k_prompt):
                        k_prompt = view
                    ctx['workdir'] = staging / ('%s-cand-%d' % (prefix, k))
                    shutil.rmtree(ctx['workdir'], ignore_errors=True)
                    ctx['baseline'] = prepare(root, task, ctx['workdir'])
                    events.append('tournament_candidate_%d' % (k + 1))
                ctx['candidate'] = k
                def coder_call(tried=tried, k=k, k_prompt=k_prompt):
                    excluded = coder_exclusions(tried)
                    try:
                        return call(role, task, dir_for, chosen, k_prompt, exclude_model=excluded, later=bool(k))
                    except channels.ChannelUnavailable:
                        if len(excluded or ()) <= len(tried):
                            raise
                        events.append('other_model_none_free')
                        return call(role, task, dir_for, chosen, k_prompt, exclude_model=list(tried) or None, later=bool(k))

                architect_made = False
                try:
                    if architect_code and not k and not feedback and attempt <= 1 and apply_architect_code():
                        architect_made = True
                        rc, out, err = 0, b'', b''
                    else:
                        rc, out, err = timed('code_s', coder_call)
                except (ChannelFault, channels.ChannelUnavailable, NoIndependentReviewer):
                    if not k:
                        raise
                    ctx['workdir'], ctx['baseline'] = held      # no further model now: the last candidate stands
                    events.append('tournament_short')
                    break
                early = settle_base()                # the red base measured meanwhile: both are in, the gates judge
                if early is not None:
                    return early
                decision = None          # the earlier candidate's failure is history now; this one is judged afresh
                ctx['coder_model'] = architect_author if architect_made else calls[-1]['model']
                if event_summary(out)['finish_reason'] in ('length', 'max_tokens'):
                    events.append('output_truncated')
                signal = scope_signal()
                if signal:                           # it named code of the failing path outside the task
                    return widen(*signal)
                stuck = cannot_loop()
                if stuck:
                    return stuck
                if k + 1 >= size:
                    break                            # the tournament is full: this candidate stands
                why = unusable()
                if why:                              # mechanically unusable: the next model hears why
                    next_note = TOURNAMENT_NOTE % scrub(redact(why))[:300]
                    wanted = asked_names(why) - asked
                    if wanted:                       # it asked for code: the next view shows that code first
                        asked |= wanted
                        ctx['asked'] = asked
                        next_note += TOURNAMENT_ASKED_NOTE % ', '.join(sorted(wanted))
                    continue
                decision = run_gates()               # usable: the deterministic gates decide
                if not isinstance(decision, _GateRetry):
                    break                            # passed, or a final result (environment, unknown neighbour, ...)
                gate_failed.append(ctx['coder_model'])
                red_on(ctx['coder_model'])
                blocked = no_effect_block() if decision.no_effect else None
                if blocked is not None:
                    return blocked                   # the second change without effect on this base
                events.append('tournament_gate_retry_%d' % (k + 1))
                next_note = gate_note(decision)
            if size > 1:
                report['tournament'] = dict(size=size, candidates=ctx['candidate'] + 1,
                                            models=tried + [ctx['coder_model']])
                if gate_failed:
                    report['tournament']['gate_failed'] = list(gate_failed)
        def authors() -> list:
            """Every model that wrote a part of this candidate: none of them judges it (nor the paid critic)."""
            return sorted(ctx['coder_models'] | {m for m in [ctx.get('coder_model')] if m})

        def diff_of(changed) -> str:
            return unified_diff(ctx['baseline'], ctx['workdir'], changed, 10 ** 7) if ctx['baseline'] is not None else ''

        def kept_votes(diff_hash, banned=()) -> list:
            """W-review 2: the valid voices already given on THIS diff (key: its hash); an author or a repeated model never votes."""
            pend = ck.read()['tasks'][tid].get('pending_review') or {}
            kept = votes_of_diff(pend, diff_hash)
            fresh, seen_models, kept_models = [], set(banned), set()
            for old_vote in (kept if isinstance(kept, list) else []):
                if not (isinstance(old_vote, dict) and isinstance(old_vote.get('model'), str) and type(old_vote.get('ok')) is bool
                        and old_vote['model'] not in authors()):
                    continue
                # fac-41: a second look of a model already kept (flagged recheck) is a voice; any other repeat never votes
                if old_vote['model'] in seen_models and not (old_vote.get('recheck') is True and old_vote['model'] in kept_models):
                    continue
                seen_models.add(old_vote['model'])
                kept_models.add(old_vote['model'])
                fresh.append(old_vote)
            return fresh

        def only_model(keep) -> list:
            """fac-41: every configured model except ``keep``: the exclusion that leaves exactly one reviewer model."""
            return sorted({c['model'] for c in configured} - {keep})

        def said_line(number, ok, why) -> str:
            """What the next critic is told of an earlier voice (the loop below and the precheck's prompt use it)."""
            return 'critic %d %s: %s' % (number, 'approved' if ok else 'rejected', '; '.join(list(why or [])[:5]) or 'no remarks')

        def reviewers_wait() -> tuple:
            """W-review 1: (wait_s, reason, short, kept) of the review route right now, by the very helpers call() uses
            (call_size, call_order with the same exclusions: the authors AND the critics who already voted on this diff,
            call_pick on the ledger view, nothing booked). ``short``: a voice is kept and no other reviewer exists, so the
            chain would end cut short whatever the gates say. The prompt is the one review_candidate builds (its invoke
            only captures it), so the size is the call's own."""
            if not configured:
                return 0.0, '', [], []
            try:
                changed = inspect_changes(task, ctx['workdir'], ctx['baseline']) if ctx['baseline'] is not None else ()
            except Exception:                        # the gates will name it
                return 0.0, '', [], []
            text = diff_of(changed)
            diff_hash = sha256(text.encode('utf-8', 'replace')).hexdigest() if ctx['baseline'] is not None else ''
            kept = kept_votes(diff_hash)
            voted = [v['model'] for v in kept]
            class _PromptSeen(Exception):            # the real builder's prompt, caught before any model is asked
                pass

            def capture(call_task, directory, preferred, **kwargs):
                raise _PromptSeen(call_task, kwargs['prompt_override'])
            try:
                review_candidate(task, ctx['workdir'], review_model, capture, baseline=ctx['baseline'], scratch=staging,
                                 lens=REVIEW_LENSES[min(len(kept), len(REVIEW_LENSES) - 1)],
                                 prior=tuple(said_line(n + 1, v['ok'], v.get('why')) for n, v in enumerate(kept)),
                                 rejected=rejected_for(ck.read(), tid), rubric=True,
                                 execution=execution_report(base, tuple(ctx.get('hollow') or ()), tuple(ctx.get('extra_names') or ()),
                                                            ctx.get('red_evidence') or ''))
                return 0.0, '', [], kept             # the builder asked no model: nothing to wait for
            except _PromptSeen as seen_prompt:
                call_task, prompt = seen_prompt.args
            except Exception:                        # the gates / the call will name it
                return 0.0, '', [], []
            light, base_tokens, steps, booked = call_size('review', call_task, len(prompt), channels.cyrillic_share(prompt))
            live_state = live_quotas()
            scratch_events = list(events)            # _kilo_fits writes into it: the precheck leaves no event behind
            order = call_order('review', review_model, base_tokens, authors() + voted, (), (), False, live_state, light, steps,
                               scratch_events)
            lone = False
            if not order and voted:                  # fac-41: no independent model: the first critic's own model may look again
                order = call_order('review', review_model, base_tokens, authors() + only_model(voted[0]), (), (), False,
                                   live_state, light, steps, scratch_events)
                lone = bool(order)                   # ... but that is no "reviewer left today": the term of a short chain still counts
            if not order:
                ctx['review_left'] = False           # W-rev 2: no reviewer channel at all
                return 0.0, '', kept, kept           # without a voice the call's own NoIndependentReviewer path decides
            seen = live_state                        # already the merged view
            try:
                call_pick(order, seen, base_tokens, booked, call_affinity('review'))
            except channels.ChannelUnavailable as error:
                ctx['review_left'] = False if lone else RW.channel_left(order, error.reason or 'unknown')   # no reason: not a known open-today case
                return float(error.wait_s or 0), str(error.reason or ''), [], kept
            ctx['review_left'] = not lone
            return 0.0, '', [], kept

        def review_left() -> bool:
            """W-rev 2: some reviewer channel (not an author, not a model that already voted) can still answer today."""
            ctx['review_left'] = None
            try:
                reviewers_wait()
            except Exception:                        # noqa: BLE001 - unknown: the old rule (the term) stands
                return False
            return ctx.get('review_left') is True
        if decision is None and pending:             # a standing candidate: no cloud gates while no reviewer is free
            hold, why_hold, short_chain, kept_now = reviewers_wait()
            # rule 4 of 21.11: with a kept voice the paid critic is the insurance second voice, so while it can be asked
            # the chain is not cut short here: the gates run and the chain's own handler calls it (W-review fix 2)
            if (kept_now or paid_critic.agent_card(task)) and paid_critic.available():      # an agent card has two paid voices
                short_chain, hold = [], 0.0
            if short_chain:                          # a voice is kept, no other model exists: the gates would end in this
                events.append('review_deferred_before_gates')
                events.append('review_chain_short')
                report['review_verdict'] = 'unavailable'
                report['review_votes'] = [dict(model=v['model'], ok=v['ok']) for v in short_chain]
                report['critics'] = [v['model'] for v in short_chain]
                report['pending_review'] = True
                if dry_now():          # W-dry 2: a short chain is no failure of the card while the edit channels are dry
                    return release('review_chain_short', INFRA_DEFER_S)
                if ck.commit(chain_short) >= ESCALATE_AFTER:
                    return block('review_chain_short', 'review chain cut short %d times' % ESCALATE_AFTER)
                return release_or_block('review_chain_short', INFRA_DEFER_S)
            if hold > REVIEWER_WAIT_S:
                events.append('review_deferred_before_gates')
                report['pending_review'] = True
                return _wait(release, report, 'channel_wait', hold, status='WAITING_CHANNEL', channel_reason=why_hold or None)
        def gates_diff_hash(files) -> str:
            return sha256(diff_of(files).encode('utf-8', 'replace')).hexdigest() if ctx['baseline'] is not None else ''

        def kept_gates():
            """W-rev 2: the standing candidate whose gates were green on THIS diff (same base, same files) is not gated again:
            the next pass only asks the missing reviewer."""
            g = (ck.read()['tasks'][tid].get('pending_review') or {}).get('gates')
            if not (pending and isinstance(g, dict) and isinstance(g.get('receipt'), str) and g.get('diff')
                    and isinstance(g.get('changed'), list)):
                return None
            try:
                files = inspect_changes(task, ctx['workdir'], ctx['baseline']) if ctx['baseline'] is not None else ()
            except Exception:                        # noqa: BLE001 - the gates will name it
                return None
            if g.get('base_sha') != base_sha:        # the base moved (or was never noted): the gates run again
                return None
            if not files or sorted(files) != sorted(g['changed']) or gates_diff_hash(files) != g['diff']:
                return None
            events.append('gates_kept')
            # the side effects of run_gates() the critics read are restored from the note (same as a full run)
            ctx['hollow'] = tuple(str(x) for x in (g.get('hollow') or ()))
            ctx['extra_names'] = tuple(str(x) for x in (g.get('extra_names') or ()))
            ctx['red_evidence'] = g.get('red_evidence') or ''
            kept_counts = g.get('counts')
            if isinstance(kept_counts, dict):
                from types import SimpleNamespace
                ctx['counts'] = SimpleNamespace(collected=kept_counts.get('collected', 0), passed=kept_counts.get('passed', 0),
                                                failed=kept_counts.get('failed', 0), errors=0,
                                                skipped=kept_counts.get('skipped', 0))
            return files, g['receipt']
        if decision is None:
            decision = kept_gates() or run_gates()   # the standing candidate (or the kept one of a pending review)
            if isinstance(decision, _GateRetry):
                red_on(ctx.get('coder_model'))
                if 'tournament' in report:
                    report['tournament']['gate_failed'] = (report['tournament'].get('gate_failed', [])
                                                           + [ctx['coder_model']])
        if isinstance(decision, _GateRetry):
            if ctx.get('gate_red'):                  # <id>: which test ids each red model failed on (the loop's audit)
                report['gate_red'] = ctx['gate_red']
            if ready_card(task):        # fac-52: ready code is green or it goes back to its author: no strike, no model rework
                return not_green(sorted({i for _, ids in ctx.get('gate_red') or () for i in ids}), str(decision.reject_args[1]))
            blocked = no_effect_block() if decision.no_effect else None
            if blocked is not None:
                return blocked
            seen_ne = no_effects()
            mark = (lambda r: r.__setitem__('no_effect', {'key': key, 'n': seen_ne})) if key and seen_ne else None
            return reject(*decision.reject_args, mark=mark)   # the pass ends on its last gate failure: ONE rejection
        if isinstance(decision, dict):
            return decision
        changed, receipt = decision


        # 4. Independent reviewer: another model, reasons go back as feedback.
        ck.commit(lambda s, r: set_pending(s, r))
        if ctx['baseline'] is not None:              # W-rev 2: the green gates stay with the candidate
            gates_note = dict(diff=gates_diff_hash(changed), changed=list(changed), receipt=receipt, base_sha=base_sha,
                              hollow=list(ctx.get('hollow') or ()), extra_names=list(ctx.get('extra_names') or ()),
                              red_evidence=ctx.get('red_evidence') or '', counts=_counts(ctx.get('counts')))
            ck.commit(lambda s, r: r['pending_review'].__setitem__('gates', gates_note)
                      if isinstance(r.get('pending_review'), dict) else None)

        kept_log = []     # the voices of this candidate (the telemetry reads it on every exit)
        critics = []      # the models that reviewed this candidate: the next critic is none of them, nor the coder
        told = rejected_for(ck.read(), tid)

        look_again = []      # fac-41: while a second look runs, the models it may NOT use (all but the first critic's)
        pass_wait = [RW.PASS_WAIT_S]               # W-rev: the 503 sleeps of ALL tries of this pass share it (the lease lives 1800 s)

        def pass_sleep(seconds):
            pass_wait[0] -= seconds
            time.sleep(seconds)

        # W-bucket: a review call's wait in the head comes out of the same pass budget (6 dry tries x 330 s outlived the lease)
        head_budget = types.SimpleNamespace(left=lambda: pass_wait[0],
                                            spend=lambda seconds: pass_wait.__setitem__(0, pass_wait[0] - seconds))

        invalid_models = []   # models whose answer broke the rubric on this candidate: none of them is asked for the seat again

        def invoke(call_task, directory, preferred, **kwargs):
            tries = DRY_REVIEW_TRIES if dry_now() else 1     # W-dry 2: Gemma again and again while the edit channels are dry
            for number in range(1, tries + 1):
                try:
                    # W-rev 1: a 503 of the small tier is asked again round its channels (2, 4, 8, 12, 12 ... s, 120 s per
                    # call, at most PASS_WAIT_S of sleeping in the whole pass)
                    # W-guard 3: a channel shut only by its own minute window (rpm / tpm_window / cool, <= 60 s) is waited for
                    return RW.retry_own_window(
                        lambda: RW.retry_overload(
                            lambda: past_day_limit(lambda: call('review', call_task, lambda _retry: directory, preferred,
                                         kwargs['prompt_override'], exclude_model=authors() + list(look_again or critics) + invalid_models,
                                         fast_retry='small', wait_budget=head_budget)),
                            lambda err: isinstance(err, ChannelFault) and bool((err.info or {}).get('fast_retry')),
                            total_s=max(0.0, min(RW.RETRY_TOTAL_S, pass_wait[0])), sleep=pass_sleep,
                            on_retry=lambda n: events.append('review_503_retry_%d' % n) if n <= 3 else None),
                        lambda err: (getattr(err, 'wait_s', None) if isinstance(err, channels.ChannelUnavailable)
                                     and getattr(err, 'reason', None) in RW.OPEN_TODAY_REASONS else None),
                        budget_left=lambda: pass_wait[0], sleep=pass_sleep,
                        on_wait=lambda n: events.append('review_window_wait_%d' % n))
                except (channels.ChannelUnavailable, ChannelFault) as error:
                    kind = error.info.get('kind') if isinstance(error, ChannelFault) else None
                    # W-guard fix1 3: what ends a review call is now in the telemetry (the reason, not only "short chain")
                    events.append('review_end_%s' % re.sub(r'[^a-z0-9_]', '_', str(kind or getattr(error, 'reason', '') or 'unknown').lower())[:30])
                    if number >= tries or (kind is not None and kind not in DRY_REVIEW_RETRY_KINDS) or (
                            isinstance(error, channels.ChannelUnavailable) and error.reason in INFRA_CHANNEL_REASONS):
                        raise
                    events.append('dry_review_retry_%d' % number)
                    time.sleep(DRY_REVIEW_PAUSE_S * number)        # 10, 20, 30 ... s, every channel is asked again
        try:
            hollow, extra = tuple(ctx.get('hollow') or ()), tuple(ctx.get('extra_names') or ())
            exec_text = execution_report(base, hollow, extra, ctx.get('red_evidence') or '')
            mech_ok = mechanically_ok(base, hollow, extra)
            votes, said, rejections = [], [], []
            approved = None
            # W-review 2: the voices already given on THIS diff (key: its hash) are not asked again after a postponement
            diff_hash = sha256(diff_of(changed).encode('utf-8', 'replace')).hexdigest() if ctx['baseline'] is not None else ''
            for old_vote in kept_votes(diff_hash):      # a model never votes twice, and an author never judges its own work
                critics.append(old_vote['model'])
                votes.append(old_vote['ok'])
                kept_log.append(dict(model=old_vote['model'], ok=old_vote['ok'], why=list(old_vote.get('why') or [])[:5]))
                said.append(said_line(len(votes), old_vote['ok'], kept_log[-1]['why']))
                if not old_vote['ok']:
                    rejections.extend(kept_log[-1]['why'] or ['rejected without a stated reason'])
            if kept_log:
                events.append('review_votes_kept_%d' % len(kept_log))
            def ask_critic(n):
                """Step 4 (b) of VARIANTS_1426: a voice citing what it was not shown is not counted; its model is
                excluded (``invalid_models``) and another critic is asked, at most REVIEW_PANEL times."""
                unfounded = None
                for _ in range(REVIEW_PANEL):
                    try:
                        return timed('review_s', lambda: review_candidate(
                            task, ctx['workdir'], review_model, invoke, baseline=ctx['baseline'], scratch=staging,
                            lens=REVIEW_LENSES[n], prior=tuple(said), rejected=told, rubric=True, execution=exec_text))
                    except UnfoundedVote as error:
                        if calls and calls[-1].get('model'):
                            invalid_models.append(calls[-1]['model'])
                        events.append('review_vote_unfounded')
                        unfounded = error
                raise ReviewFault(str(unfounded))

            def vote(n):
                """One critic's (ok, why). fac-41: a second voice that finds no independent model now may be the FIRST critic's
                model, shown that critic's answer and asked to check both; a fault of that look re-raises the original one."""
                try:
                    for attempt in range(RUBRIC_INVALID_TRIES):
                        try:
                            return ask_critic(n)
                        except RubricInvalid:
                            events.append('review_invalid_vote_%d' % (attempt + 1))
                            if attempt + 1 >= RUBRIC_INVALID_TRIES or not calls or not calls[-1].get('model'):
                                raise
                            invalid_models.append(calls[-1]['model'])
                except (NoIndependentReviewer, channels.ChannelUnavailable, ChannelFault):
                    if n != 1 or len(votes) != 1 or not critics or critics[0] in authors():
                        raise
                    events.append('review_second_look')
                    look_again[:] = only_model(critics[0])
                    try:
                        found = timed('review_s', lambda: review_candidate(
                            task, ctx['workdir'], review_model, invoke, baseline=ctx['baseline'], scratch=staging,
                            lens=RECHECK_LENS, prior=tuple(said), rejected=told, rubric=True, execution=exec_text))
                        again.append(True)
                        return found
                    except (NoIndependentReviewer, channels.ChannelUnavailable, ReviewFault, ChannelFault):
                        pass
                    finally:
                        look_again.clear()
                    raise

            again = []       # fac-41: set when the voice just taken was the first critic's second look
            for n in range(len(votes), REVIEW_PANEL):
                again.clear()
                try:     # up to REVIEW_PANEL critics of different models, each with its own lens; the majority decides
                    ok, why = vote(n)
                except (NoIndependentReviewer, channels.ChannelUnavailable, ReviewFault, ChannelFault):
                    dry = dry_now()
                    if not votes:
                        both = paid_critic.pair(
                            task, unified_diff(ctx['baseline'], ctx['workdir'], task.touch_files, paid_critic.DIFF_LIMIT)
                            if ctx['baseline'] is not None else '', (exec_text + '\n' + told)[-paid_critic.FAIL_LIMIT:],
                            exclude_model=authors(), baseline=ctx['baseline'], workdir=ctx['workdir'])
                        if both is not None:
                            ctx['paid_done'] = both
                            events.append('paid_pair')
                            approved = both['verdict'] != 'reject'
                            kept_log.extend(dict(model=m, ok=approved or m != both['voices'][-1], why=[]) for m in both['voices'])
                            if not approved:
                                paid_critic.record_class(task, both)
                                rejections.append(scrub(redact('paid critic [%s]: %s' % (
                                    both['class'], both['reason'] or both['symptom']))))
                            break
                    if not votes and not dry:
                        raise                      # the first critic failed: the handlers below decide
                    # W-dry 2: with no free voice (Gemma stayed silent after its repeats) the paid Haiku below is the missing voice
                    approved = panel_verdict(votes, True, mech_ok)   # no further model: a split goes to the ranking
                    if approved is not None:
                        break
                    # 22.11 01:50: a lone free REJECT also waited (17 short chains in 30 min, the candidate neither
                    # accepted nor rejected): the paid critic is the deciding second voice either way; a lone free reject
                    # is overruled only when the mechanical checks are clean too.
                    if True:           # rule 4 of 21.11: the paid critic is the insurance second voice when no free
                        paid_second = paid_critic.control(   # model is left (live 17:20-17:50: 19 chains cut short)
                            task, paid_diff(ctx['baseline'], ctx['workdir'], task.touch_files)
                            if ctx['baseline'] is not None else '', paid_critic.failure_text(exec_text + '\n' + told),
                            exclude_model=authors() + ([paid_critic.MODELS[0]] if dry else []),   # W-dry 2: the second voice is Haiku, the control voice stays Sonnet
                            baseline=ctx['baseline'], workdir=ctx['workdir'])
                        if paid_second is not None:          # no key, no budget, a fault: the free wait below, as before
                            if not dry or paid_critic.MODELS[0] in authors():
                                ctx['paid_done'] = paid_second      # (dry: the control Sonnet still judges, unless it is the author)
                            events.append('paid_second_critic')
                            # step 4 (c): a reject without a quoted diff line or a red test name is advice
                            paid_no = paid_critic.blocks(paid_second)
                            if paid_second['verdict'] == 'reject' and not paid_no:
                                events.append('paid_advice')
                            approved = not paid_no and (all(votes) or mech_ok)
                            kept_log.append(dict(model=str(paid_second.get('model') or 'paid'),   # W-review fix 6: the paid voice is a voice
                                                 ok=not paid_no, why=[]))
                            if not approved:
                                paid_critic.record_class(task, paid_second)
                                rejections.append(scrub(redact('paid critic [%s]: %s' % (
                                    paid_second['class'], paid_second['reason'] or paid_second['symptom']))))
                            break
                    # no further model now: one critic never approves alone (live 20.11 16:46, <id> approved by one
                    # critic, its commit rejected 4 min later). The candidate stays pending, the chain starts again
                    # on a later pass; the same postponement ESCALATE_AFTER times in a row is BLOCKED (the term).
                    events.append('review_chain_short')
                    report['critics'] = list(critics)
                    report['review_verdict'] = 'unavailable'     # W-review 3: no verdict yet, only the voices so far
                    report['review_votes'] = [dict(model=v['model'], ok=v['ok']) for v in kept_log]
                    report['critiques'] = [scrub(redact(s))[:300] for s in said]
                    report['pending_review'] = True
                    if dry:                        # W-dry 2: no failure of the card while the edit channels are dry
                        return release('review_chain_short', INFRA_DEFER_S)
                    if review_left():              # W-rev 2: a channel can still answer today: 120 s, no strike, no block
                        events.append('review_chain_wait')
                        return release('review_chain_short', RW.RECHECK_S)
                    if ck.commit(chain_short) >= ESCALATE_AFTER:   # the term of the candidate, whatever came between
                        return block('review_chain_short', 'review chain cut short %d times' % ESCALATE_AFTER)
                    return release_or_block('review_chain_short', INFRA_DEFER_S)
                critics.append(calls[-1]['model'])
                if n:
                    events.append('review_chain_%d' % (n + 1))
                votes.append(ok)
                said.append('critic %d %s: %s' % (n + 1, 'approved' if ok else 'rejected', '; '.join(why) or 'no remarks'))
                if not ok:
                    rejections.extend(why or ['rejected without a stated reason'])
                kept_log.append(dict(model=critics[-1], ok=bool(ok), why=[scrub(redact(str(w)))[:300] for w in (why or [])][:5]))
                if again:
                    kept_log[-1]['recheck'] = True     # fac-41: kept_votes lets this model's second voice stand
                if diff_hash:                    # at once, not at the end: a chain cut short keeps this voice
                    ck.commit(lambda s, r, log=list(kept_log): keep_votes(r, log, diff_hash))
                approved = panel_verdict(votes, n + 1 == REVIEW_PANEL, mech_ok)
                if approved is not None:
                    break
            reasons = [] if approved else (rejections or ['the critics are split and the mechanical ranking is against'])
            report['critics'] = list(critics)
            report['review_verdict'] = 'approve' if approved else 'reject'     # W-review 3
            report['review_votes'] = [dict(model=v['model'], ok=v['ok']) for v in kept_log]
            # redacted like reason_detail: a critic may quote a key it saw (test_reason_and_feedback_are_redacted_...,
            # red since the chain landed; that test never reaches the public cloud run, its fake key blocks it)
            report['critiques'] = [scrub(redact(s))[:300] for s in said]
        except NoIndependentReviewer:
            report['pending_review'] = True
            report['review_verdict'] = 'unavailable'
            report['review_votes'] = [dict(model=v['model'], ok=v['ok']) for v in kept_log]
            return _wait(release_or_block, report, 'no_independent_reviewer', status='WAITING_CHANNEL')
        except channels.ChannelUnavailable as error:
            report['pending_review'] = True
            report['review_verdict'] = 'unavailable'
            report['review_votes'] = [dict(model=v['model'], ok=v['ok']) for v in kept_log]
            return _wait(release, report, 'channel_wait', error.wait_s, status='WAITING_CHANNEL',
                         channel_reason=error.reason)
        except ReviewFault as error:
            report['pending_review'] = True
            report['review_verdict'] = 'fault'
            report['reason_detail'] = scrub(redact(str(error)))[:300]
            return release_or_block('reviewer_failed', INFRA_DEFER_S)
        if not approved:
            if ready_card(task):        # fac-72: ready code is never reworked by a model: the critics' remarks go to its author
                return ready_return(scrub(redact('review: ' + '; '.join(reasons))))
            return reject('review', 'review: ' + '; '.join(reasons), '; '.join(reasons), changed)
        # owner rule 4: the paid control critic sees only would-be promotions (free chain approved, gates passed).
        # A reject goes back like a free critic's; the catch enters the error-class registry the free review reads.
        paid = ctx.get('paid_done') or paid_critic.control(task, paid_diff(ctx['baseline'], ctx['workdir'], task.touch_files)
                                                      if ctx['baseline'] is not None else '',
                                   paid_critic.failure_text(exec_text + '\n' + told),
                                   exclude_model=authors(), baseline=ctx['baseline'], workdir=ctx['workdir'])    # no author of a part judges its own work
        if paid is not None:
            report['paid_critic'] = paid
            if paid['verdict'] == 'reject' and not paid_critic.blocks(paid):
                events.append('paid_advice')    # step 4 (c): no quoted diff line, no red test name: advice only
            if paid_critic.blocks(paid):
                paid_critic.record_class(task, paid)
                why = scrub(redact('paid critic [%s]: %s' % (paid['class'], paid['reason'] or paid['symptom'])))
                if ready_card(task):    # fac-72: the catch is in the registry above; the card goes back to its author with the reason
                    return ready_return('review: ' + why)
                return reject('review', 'review: ' + why, why, changed)
        reviewed = staging / "for-review" / tid
        if reviewed.exists():
            shutil.rmtree(reviewed)  # left over from an earlier candidate of this task
        reviewed.mkdir(parents=True)
        for name in changed:
            dst = reviewed.joinpath(*name.split("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ctx['workdir'].joinpath(*name.split("/")), dst)

        def approve(state, row):
            status = settle(state, tid, token, tests_ok=True, evidence=receipt, max_attempts=max_attempts)
            row.pop('pending_review', None)
            return status, None
        result = end(approve, changed=len(changed), receipt_sha256=receipt, cross_review=True)
        prev_diff_file.unlink(missing_ok=True)
        return result
    except (StaleLease, LockBusy):
        raise                       # the lease is gone / the lock is busy: write nothing (the caller reports it)
    except ChannelFault as error:
        bank_base_safe()
        return fault(error)
    except BudgetExhausted:
        bank_base_safe()
        report['pending_review'] = has_pending()
        return release('budget_exhausted', seconds_to_local_midnight())
    except channels.ChannelUnavailable as error:
        bank_base_safe()
        report['pending_review'] = has_pending()
        return _wait(release, report, 'channel_wait', error.wait_s, status='WAITING_CHANNEL',
                     channel_reason=error.reason)
    except NoIndependentReviewer:
        report['pending_review'] = has_pending()
        return _wait(release_or_block, report, 'no_independent_reviewer', status='WAITING_CHANNEL')
    except (PromptTooLarge, K.CardTooLarge) as error:
        if ready_card(task):        # fac-52: its code does not shrink by a reslice of models: back to its author
            return ready_return('card_too_large: the card does not fit %d characters: %s' % (channels.PROMPT_LIMIT_CHARS, error))
        if K.contract_of(task).get('parts') or isinstance(error, K.CardTooLarge) or (
                K.contract_of(task).get('test') or {}).get('new'):
            # a card of a contract that does not fit even squeezed (W-ctx 1): back to the slicer for smaller parts,
            # no strike and no BLOCKED that is lifted and comes round again
            events.append('card_too_large')
            detail = scrub(redact('the card does not fit %d characters: %s' % (channels.PROMPT_LIMIT_CHARS, error)))[:300]
            return end(lambda s, r: (fail_row(s, tid, token, 'reslice'), None), reason='reslice', reason_detail=detail)
        return block('context_too_large', 'prompt of %s characters exceeds %d' %
                     (error, channels.PROMPT_LIMIT_CHARS))
    except Exception as error_obj:  # noqa: BLE001 - fail closed, never retry an uncertain worker
        text = scrub(redact(str(error_obj)))[:300]
        # prepare()/packet(): context over budget; a source over SOURCE_MAX_BYTES is the same resource limit (live 20.11:
        # it read 'scope_violation', the question asked "which files?" and the factory never retried the 6 rows)
        if isinstance(error_obj, InputTooLarge) or (isinstance(error_obj, InvalidPlan) and 'budget' in text):
            return block('context_too_large', text)
        if isinstance(error_obj, OSError):   # antivirus, a locked file, a full disk: the machine, not the task
            report['error_type'] = type(error_obj).__name__
            note = scrub(redact(str(error_obj)))[:200]
            report['reason_detail'] = note
            kind = 'os_error'   # whitelisted in agent_factory.DEFER_REASONS (seam test guards it)
            if defer_streak(ck.read(), tid, kind) + 1 >= ESCALATE_AFTER:
                # the same OS error on every pass is this task's problem (path clash, long path): block it,
                # and do not count it toward the brake of the whole factory
                return block('worker_exception', note, infra=False)
            return release(kind, 60, infra=True)
        reason = "scope_violation" if isinstance(error_obj, InvalidPlan) else "worker_exception"
        report['error_type'] = type(error_obj).__name__
        return block(reason, text)
    finally:
        if bg_pool is not None:
            bg_pool.shutdown(wait=True)      # the background red base reads base_holder: it ends before the copy goes
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


FAST_LOCAL_DEFAULT_S = 0.0   # <id>: a short product test is a pytest child of the card (+100 MB in its job) for ~3 s saved:
                             # the card sends every test to the cloud; --fast-local-s N brings the local slot back


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
    p.add_argument("--reslice-after", type=int, default=0, help="red attempts before re-slicing (0 disables)")
    p.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS,
                   help="a task becomes FAILED after N failed attempts (each next one on another model where possible)")
    p.add_argument("--max-model-calls", type=int,
                   help="explicit model-call budget written into this checkpoint")
    p.add_argument("--task", help="run this task (the one the loop claimed); default: the first ready one")
    p.add_argument("--lease", help="the lease token of --task, claimed by the caller (without it the pass claims its own)")
    p.add_argument("--port-repo", type=Path,
                   help="git repository that holds the old-branch commits of port tasks (--root is a copy without .git)")
    p.add_argument("--fast-local-s", type=float, default=FAST_LOCAL_DEFAULT_S,
                   help="tests known to last this long or less run locally; 0 (the default, T5) sends every test to the cloud")
    p.add_argument("--self-repo", action="store_true",
                   help="the second loop instance (the repository is the factory's own code): the gate runs in the cloud only")
    args = p.parse_args(argv)
    if args.self_repo:
        gate.SELF_REPO = True
    if args.fast_local_s < 0:
        p.error("--fast-local-s must be nonnegative")
    gate.FAST_LOCAL_S = args.fast_local_s
    if not 1 <= args.max_tasks <= 10:
        p.error("--max-tasks must be in 1..10")
    if args.reslice_after < 0:
        p.error("--reslice-after must be nonnegative")
    if not 1 <= args.max_attempts <= MAX_ATTEMPTS:
        p.error("--max-attempts must be in 1..%d" % MAX_ATTEMPTS)
    if args.max_model_calls is not None and not 1 <= args.max_model_calls <= MAX_MODEL_CALLS:
        p.error("--max-model-calls must be in 1..%d" % MAX_MODEL_CALLS)
    if args.execute and args.staging.resolve().is_relative_to(args.root.resolve()):
        p.error("staging must not be within original repository")
    if args.lease and not args.task:
        p.error("--lease needs --task")
    outcomes = []
    for _ in range(args.max_tasks if args.execute else 1):
        options = {}
        if args.execute:
            options.update(review_model=args.review_model or args.large_model,
                           channel_config=args.channels, base_sha=args.base_sha, port_repo=args.port_repo)
        result = once(root=args.root, plan=args.plan, checkpoint=args.checkpoint,
                      staging=args.staging, small_model=args.small_model,
                      large_model=args.large_model, execute=args.execute,
                      acknowledge=args.ack_host_access_risk,
                      max_attempts=args.max_attempts, reslice_after=args.reslice_after,
                      max_model_calls=args.max_model_calls, task_id=args.task, lease=args.lease, **options)
        outcomes.append(result)
        if result["status"] not in ("REVIEW", "READY"):
            break
    for result in outcomes:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if all(x["status"] in ("DRY_RUN", "REVIEW", "IDLE")
                    for x in outcomes) else 2


if __name__ == "__main__":
    from . import factory_cloud_gate
    factory_cloud_gate.enable_product()     # only the worker process the loop starts may send a candidate tree to the cloud gate
    sys.exit(main())
