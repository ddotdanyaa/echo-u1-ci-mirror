"""Deterministic QC gates of the agent factory (contract K-C). No LLM, no git.

pytest runs inside the Job Object of ``factory_process.run_owned``: on timeout the whole
process tree dies. The verdict is read from JUnit XML, never from the exit code alone:
an empty suite, a collection error or an all-skipped run is not green.
"""
from __future__ import annotations

import ast
import json
import math
import shutil
import fnmatch
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from .agent_factory import redact
from . import factory_tree
from . import red_ratchet      # fac-91: readable / runnable test ids
from .factory_process import run_owned
try:                                       # the public mirror does not carry the cloud gate: its own number there
    from .factory_cloud_gate import SLOT_QUEUE_S
except ImportError:
    SLOT_QUEUE_S = 900

ENV_ALLOW = ('PATH', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
             'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'HOMEDRIVE', 'HOMEPATH', 'HOME',
             'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS')

# Files the candidate may never touch. Compared canonical: casefolded, no '.', '//', trailing dots/spaces.
FORBIDDEN_BASENAMES = frozenset((
    'conftest.py', 'pytest.ini', '.pytest.ini', 'pytest.toml', 'setup.cfg', 'pyproject.toml', 'tox.ini',
    'sitecustomize.py', 'usercustomize.py'))
# The factory's own code: the acceptance and every factory module (new ones too). A candidate may change such a file
# only when its OWN task names it in touch_files. The triage and Opus' answers ask is_forbidden without names (they
# never put these paths into a task) and the loop's promote checks without names (it never merges them), so only a
# task the coordinator wrote by hand reaches them and its result is taken by hand (fac-self 19.11: the factory works
# on its own code, the coordinator accepts) - the CODEOWNERS rule, not a switch.
OWNER_PATHS = frozenset((
    'tools/red_ratchet.py', 'tools/push_guard.py',
    # The tools modules the factory really imports in a process that holds the channel keys (checked by grep over
    # agent_factory_runner, factory_loop, factory_gate, agent_factory_import):
    #   id_query.py       - top-level import of agent_factory_import (the loop calls it every portion);
    #   affected_tests.py - top-level import of the runner, lazy import of the triage;
    #   backlog_register.py - lazy import of agent_factory_import.main (the CLI), which in turn imports tools.rehearsal;
    #   __init__.py       - loaded by every `import tools.*`.
    # tools/replay, harvest, ladder and rehearsal are NOT listed: the loop never reaches them (they hang off
    # backlog_register's CLI path only), and rows about them are ordinary project work.
    'tools/affected_tests.py', 'tools/id_query.py', 'tools/backlog_register.py',
    'tools/__init__.py',
    # the localization the triage runs with the channel keys in the process (agent_factory_import._localized_scope):
    'tools/slicer_localize.py',
    # the cloud route of the gate (lazy import of factory_cloud_gate): it publishes trees and runs git/gh
    'tools/echo_cloud.py',
    # the data that decides the verdicts of the acceptance tools (critic 19.11).
    'tools/data/push_guard_allow.txt', 'tools/data/known_red.txt', 'tools/owner_census_caps.json'))
OWNER_GLOBS = ('tools/factory_*.py', 'tools/agent_factory*.py')
FORBIDDEN_GLOBS = ('*cloud_env_red*.txt', '*.pth')   # closed even when named, like FORBIDDEN_BASENAMES
# Concrete constructs only, case-sensitive: skip_silence, "skipped", skip_chunks are legitimate code.
WEAKENING = re.compile(
    r'\bpytest\.(?:skip|xfail|exit|importorskip)\b|\bmark\.(?:skip|skipif|xfail)\b|\bunittest\.skip\w*'
    r'|\bskipIf\b|\bskipUnless\b|\bSkipTest\b|\bskipTest\b|\bexpectedFailure\b|PYTEST_CURRENT_TEST'
    r'|from\s+pytest\s+import[^\n]*\b(?:skip|xfail|importorskip|exit)\b')
DIAG_LIMIT = 1500
TRACEBACK_LIMIT = 1100   # of an import fault's traceback kept in the note of the second instance (the tail: the exact line is last)
WEAK_NAMES = frozenset(('skip', 'xfail', 'importorskip', 'exit'))
# A red caused by the environment (missing module/data) cannot be fixed by a candidate.
ENV_ERROR = re.compile(r'(ModuleNotFoundError|ImportError|FileNotFoundError)\b')
ENV_MODULE = re.compile(r"(?:No module named|from) '([\w.]+)'")
COLLECTION_LINE = re.compile(r'^E\s+(\w+(?:Error|Exception)\b.*)$', re.M)


@dataclass(frozen=True)
class GateResult:
    rc: int
    collected: int
    passed: int
    failed: int
    errors: int
    skipped: int
    junit_ok: bool
    diag: str = ''
    env_reason: str = ''
    missing: tuple = ()
    failed_ids: tuple = ()   # sorted 'classname::name' of red testcases (set comparison against the base)
    crashed: tuple = ()
    timed_out: tuple = ()    # files / tests cut at the limit that could not be split further, or not run (run_tests)
    env_failed: tuple = ()   # 'classname::name' of red testcases whose every failure is environmental (_env_reason)
    unrun: tuple = ()        # tests the split budget left unrun (SPENT_DIAG): neither red nor green, never measured
    slot_wait_s: float = 0.0  # seconds this run WAITED for a pytest slot / free RAM (not the run time): the runner's budget
    path: tuple = ()          # sorted (relpath, qualname, line) of source functions the FAILING tests ran (run with trace)


# --- laptop rule: at most 2 pytest machine-wide, and only while free RAM > 2 GB ---------------------
SLOT_NAMES = ('night_pytest.lock', 'night_pytest.lock2')   # shared with verify_run.py and the executors
SLOT_STALE_S = 120
SLOT_POLL_S = 3                      # a pytest slot is waited for as long as a cloud place (SLOT_QUEUE_S): one queue time
SLOT_TOUCH_S = 30          # a holder refreshes its slot dir at least this often (stale = 120 s)
NOT_STARTED = 'pytest not started: '   # diag prefix of a run that never began (no slot / no RAM)
MIN_FREE_RAM = 2 * 2 ** 30
SLOT_MIN_FREE_RAM = 1 * 2 ** 30   # the local pytest wait floor (MIN_FREE_RAM stays the loop's engine floor)


def _user_temp() -> str:
    """The USER's Temp folder (the one verify_run.py and the executors use), not this process's TEMP: the loop moves TEMP
    into its state dir, and the slots must stay shared whatever the process environment says."""
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
        return os.path.join(base, 'Temp')
    return '/tmp'


SLOT_DIRS = [os.path.join(_user_temp(), n) for n in SLOT_NAMES]   # tests replace this attribute
_clock = time.monotonic
_sleep = time.sleep


def _free_ram():
    """Free physical RAM in bytes (GlobalMemoryStatusEx ullAvailPhys); None where it cannot be read."""
    if os.name != 'nt':
        try:                                  # Linux: MemAvailable (kB) from /proc/meminfo
            with open('/proc/meminfo', encoding='ascii', errors='replace') as fh:
                for line in fh:
                    if line.startswith('MemAvailable:'):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        return None
    import ctypes

    class _Mem(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    mem = _Mem()
    mem.dwLength = ctypes.sizeof(_Mem)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            return None
    except (AttributeError, OSError):
        return None
    return int(mem.ullAvailPhys)


def _take_slot(dirs):
    for d in dirs:
        for _ in range(2):
            try:
                os.mkdir(d)
                return d
            except FileExistsError:
                try:
                    if time.time() - os.stat(d).st_mtime <= SLOT_STALE_S:
                        break
                    os.rmdir(d)          # stale: its owner is gone
                except OSError:
                    break
            except OSError:
                break
    return None


class _Slot(str):
    """What pytest_slot yields: '' (the run may start) or the reason it may not; ``waited`` = seconds spent waiting."""
    waited = 0.0

    def __new__(cls, why, waited):
        self = super().__new__(cls, why)
        self.waited = float(waited)
        return self


@contextmanager
def pytest_slot(wait_s=None):
    """Hold one of the shared pytest slots while free RAM > 1 GB.  Yields '' when the run may start, else the
    reason (no slot / low RAM within the bounded wait): the caller reports unknown/environment, never a pass
    and never a strike.  The slot is released in finally."""
    dirs = list(SLOT_DIRS)
    if not dirs:                      # a gate with no slots would run unbounded: never silently
        raise RuntimeError('SLOT_DIRS is empty: the pytest slots are not configured')
    start = _clock()
    deadline = start + (SLOT_QUEUE_S if wait_s is None else wait_s)
    held, why = None, 'no free pytest slot'
    while True:
        free = _free_ram()
        if free is not None and free <= SLOT_MIN_FREE_RAM:
            why = 'free RAM %.1f GB <= %d GB' % (free / 2 ** 30, SLOT_MIN_FREE_RAM // 2 ** 30)
        else:
            held = _take_slot(dirs)
            if held:
                break
            why = 'no free pytest slot'
        if _clock() >= deadline:
            break
        _sleep(SLOT_POLL_S)
    waited = max(0.0, _clock() - start)
    stop = threading.Event()
    beat = None
    if held:
        def _beat():                  # a live holder refreshes the mtime: it is never taken for a stale dir
            while not stop.wait(SLOT_TOUCH_S):
                try:
                    os.utime(held, None)
                except OSError:
                    return
        beat = threading.Thread(target=_beat, name='pytest-slot-heartbeat', daemon=True)
        beat.start()
    try:
        yield _Slot('' if held else why, waited)
    finally:
        stop.set()
        if beat:
            beat.join(2)
        if held:
            try:
                os.rmdir(held)
            except OSError:
                pass


PRIVATE_VARS = ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP')


def _env(sandbox) -> dict:
    """Allow-listed environment; every profile/temp variable points to the run's own folder (no personal files)."""
    env = {k: v for k, v in os.environ.items() if k.upper() in ENV_ALLOW}
    for key in ('HOMEDRIVE', 'HOMEPATH'):
        env.pop(key, None)
    home = Path(sandbox) / 'home'
    home.mkdir(parents=True, exist_ok=True)
    env.update({key: str(home) for key in PRIVATE_VARS})
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    return env


def _dotted(test: str) -> str:
    path = _rel(test.split('::', 1)[0])
    if path.endswith('.py'):
        path = path[:-3]
    return path.replace('/', '.')


def _rel(path: str) -> str:
    path = path.replace('\\', '/')
    parts = [p for p in path.split('/') if p not in ('', '.')]
    return '/'.join(parts)


def _covered(cases, test: str) -> bool:
    """True when ``test`` (file, dir or file::node) produced at least one testcase."""
    dotted = _dotted(test)
    segments = test.split('::')[1:]
    node = red_ratchet.readable(segments[-1]) if segments else None
    for case in cases:
        cn, name = case.get('classname', ''), red_ratchet.readable(case.get('name', ''))
        in_file = cn == dotted or cn.startswith(dotted + '.')
        error = case.find('error')
        if (error is not None and (error.get('message') or '').startswith('collection failure')
                and (name == dotted or dotted.endswith('.' + name))):
            return True  # the file itself failed to collect: it covers every node-id of that file
        if node is None:
            if in_file or name == dotted:
                return True
        elif in_file and (name == node or name.startswith(node + '[')):
            return True
        elif in_file and len(segments) == 1 and cn.endswith('.' + node):
            return True  # file::Class
    return False


def _failure(rc, diag):
    return GateResult(rc, 0, 0, 0, 0, 0, False, redact(diag)[:DIAG_LIMIT])


TIMEOUT_DIAG = 'timeout after %ss (process tree killed)'
SPENT_DIAG = 'timeout after %ss: the split budget was spent, not run'
SPLIT_BUDGET_S = 300     # a call cut at the limit goes on in smaller calls for at most this long in all
SPLIT_SHARE = 0.6        # a chunk holds this share of the tests the cut call finished: well inside the limit
HUNG_ALONE_MAX = 5       # at most this many tests cut on the base run alone (the others run in their files)
PROGRESS_PLUGIN = 'factory_gate_progress'
# pytest plugin written next to every gate call (PYTHONPATH + -p, as the profile plugin below): which tests were
# collected and which one started last, flushed per test, so a call killed at the limit still tells what it did.
_PROGRESS_SOURCE = r'''
import os

_out = os.environ.get("FACTORY_PROGRESS_OUT", "")


def _note(kind, nodeid):
    if _out:
        with open(_out, "a", encoding="utf-8") as f:
            f.write(kind + "\t" + nodeid.replace("\r", " ").replace("\n", " ") + "\n")


def pytest_collection_finish(session):
    for item in session.items:
        _note("item", item.nodeid)


def pytest_runtest_logstart(nodeid, location):
    _note("start", nodeid)
'''


def _timed_out(result: GateResult) -> bool:
    return result.rc == -1 and result.diag.startswith('timeout after')


def _within(names, labels) -> bool:
    """Every name is one of ``labels`` or a test inside one of them (a label may name a whole file)."""
    labels = tuple(labels)
    return all(n in labels or any(n.startswith(label + '::') for label in labels) for n in names)


def _traced(trace) -> dict:
    """The ``trace`` keyword only when there is one: a run without it calls exactly as before (and fakes of these
    functions that take no trace keep working)."""
    return {'trace': tuple(trace)} if trace else {}


def run_tests(root, tests, timeout_s, workdir=None, wait_s=None, hung=(), budget_s=None, trace=(),
              touched=None) -> GateResult:
    """Run ``tests`` in ``root``: one pytest call (_run_once) of at most ``timeout_s``. A call cut at the limit goes on
    in smaller calls (_fit), so a slow or a hanging test no longer hides the verdict of the others (live 20.11: three
    tasks stayed unknown or unacceptable on every pass: one test waits on a speech process, other files need more
    than 30 s under load). ``hung``: what was cut on the base (files or single tests): the run then starts file by
    file, a test of that list runs alone and its file runs without it (the joint call would only spend the limit
    again). ``touched`` (the candidate's changed files; None = unknown): with it the first call of a factory-code
    task (mirror route) or of any tree with a ``touched`` of () or more (product route) may run in the cloud gate (_cloud_attempt), a continuation call stays local. The continuation spends at most ``budget_s`` (SPLIT_BUDGET_S) seconds. ``trace``: source prefixes whose
    functions the failing tests ran are recorded in GateResult.path (the verdict never depends on it)."""
    deadline = time.monotonic() + (SPLIT_BUDGET_S if budget_s is None else budget_s)
    if SELF_REPO:
        hung = ()                # the cloud runs the whole list as one call: a base-hang list is for the local pytest only
        if touched is None:
            touched = ()
    if not hung:
        parts = _fit(root, list(tests), timeout_s, workdir, wait_s, deadline, first=True, touched=touched,
                     **_traced(trace))
    else:
        singles = [h for h in dict.fromkeys(hung) if '::' in h and _within([h], tests)][:HUNG_ALONE_MAX]
        parts = []
        for f in dict.fromkeys(t.split('::', 1)[0] for t in tests):
            mine = [t for t in tests if t.split('::', 1)[0] == f and t not in singles]
            if mine:
                parts += _fit(root, mine, timeout_s, workdir, wait_s, deadline, first=True,
                              deselect=[h for h in singles if _within([h], mine)], **_traced(trace))
        for h in singles:
            parts += _fit(root, [h], timeout_s, workdir, wait_s, deadline, first=True, **_traced(trace))
    return parts[0][1] if len(parts) == 1 else _merge(parts)


def _fit(root, tests, timeout_s, workdir, wait_s, deadline, first=False, deselect=(), trace=(), touched=None) -> list:
    """[(names, GateResult)] for ``tests``: one call; a call cut at the limit goes on. Its progress names the test that
    was running (it runs alone, last: cut alone, it hangs here and is timed out) and how many finished (the others
    run in chunks of SPLIT_SHARE of that count, each chunk the same way). Without progress (cut while collecting) a
    call over several files goes on file by file. A call after the deadline is not run (timed out: never a pass)."""
    if not first and time.monotonic() >= deadline:
        return [(tuple(tests), _failure(-1, SPENT_DIAG % timeout_s))]
    seen = {}
    result = _run_once(root, tests, timeout_s, workdir=workdir, wait_s=wait_s, progress=seen, deselect=deselect,
                       **_traced(trace), **({'touched': touched} if (first or SELF_REPO) and touched is not None else {}))
    if not _timed_out(result):
        return [(tuple(tests), result)]
    items, started = seen.get('items') or [], seen.get('started') or []
    if len(items) > 1 and started and started[-1] in items:
        suspect, done = started[-1], len(started) - 1
        others = [i for i in items if i != suspect]
        size = max(1, int(done * SPLIT_SHARE)) if done else len(others)
        parts = []
        for k in range(0, len(others), size):
            parts += _fit(root, others[k:k + size], timeout_s, workdir, wait_s, deadline, **_traced(trace))
        return parts + _fit(root, [suspect], timeout_s, workdir, wait_s, deadline, **_traced(trace))
    files = list(dict.fromkeys(t.split('::', 1)[0] for t in tests))
    if len(files) > 1:
        return [p for f in files for p in _fit(root, [t for t in tests if t.split('::', 1)[0] == f], timeout_s,
                                               workdir, wait_s, deadline, deselect=deselect, **_traced(trace))]
    return [(tuple(items) if len(items) == 1 else tuple(tests), result)]


def _progress(log) -> dict:
    """What a cut call wrote through the progress plugin: collected names in run order, started names."""
    items, started = [], []
    try:
        text = Path(log).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return {'items': items, 'started': started}
    for line in text.splitlines():
        kind, _, name = line.partition('\t')
        if kind == 'item' and name:
            items.append(name)
        elif kind == 'start' and name:
            started.append(name)
    return {'items': items, 'started': started}


def _merge(parts) -> GateResult:
    """One verdict of several calls: counts and ids summed; a call cut at the limit (or not run: budget spent) is
    timed out and its names are missing, as are the names of a call that came back without any testcase; junit_ok
    only when every call ran clean; a call pytest could not start (no slot, no RAM) makes the whole run
    environmental, as does a red made only of environmental failures."""
    runs = [r for _, r in parts]
    timed = {n for names, r in parts if _timed_out(r) for n in names}
    unrun = {n for names, r in parts if _timed_out(r) and r.diag.endswith(SPENT_DIAG.split('%s', 1)[1])
             for n in names}
    empty = {n for names, r in parts if not r.collected for n in names}
    not_started = next((r.env_reason for r in runs if r.env_reason and not r.collected), '')
    red = [r for r in runs if r.failed or r.errors]
    env = not_started or (red[0].env_reason if red and all(r.env_reason for r in red) else '')

    def label(names):
        return names[0] if len(names) == 1 else '%s (+%d more)' % (names[0], len(names) - 1)
    diag = '\n'.join('%s: %s' % (label(n), r.diag) for n, r in sorted(parts, key=lambda p: not _timed_out(p[1]))
                     if r.diag)
    return GateResult(next((r.rc for r in runs if r.rc), 0), sum(r.collected for r in runs),
                      sum(r.passed for r in runs), sum(r.failed for r in runs), sum(r.errors for r in runs),
                      sum(r.skipped for r in runs), all(r.junit_ok for r in runs), redact(diag)[:DIAG_LIMIT], env,
                      tuple(sorted({m for r in runs for m in r.missing} | timed | empty)),
                      tuple(sorted({i for r in runs for i in r.failed_ids})),
                      tuple(sorted({c for r in runs for c in r.crashed})), tuple(sorted(timed)),
                      tuple(sorted({i for r in runs for i in r.env_failed})), tuple(sorted(unrun)),
                      round(sum(r.slot_wait_s for r in runs), 3), path=tuple(sorted({p for r in runs for p in r.path})))


def _node(test: str) -> str:
    return _rel(test.split('::', 1)[0]) + ('::' + test.split('::', 1)[1] if '::' in test else '')


def _run_once(root, tests, timeout_s, workdir=None, wait_s=None, progress=None, deselect=(), trace=(),
              touched=None) -> GateResult:
    """One pytest call, and how long it waited for its slot (GateResult.slot_wait_s)."""
    waits: list = []
    began = time.monotonic()
    _where['v'] = 'local'
    result = _run_once_raw(root, tests, timeout_s, workdir, wait_s, progress, deselect, waits, trace, touched)
    GATE_SECS[_where['v']] = GATE_SECS.get(_where['v'], 0.0) + max(0.0, time.monotonic() - began)
    return replace(result, slot_wait_s=round(sum(waits), 3)) if waits else result


GATE_SECS = {'cloud': 0.0, 'local_fast': 0.0, 'local': 0.0}   # seconds of this process's gate runs by where they ran
_where = {'v': 'local'}


def where_secs() -> dict:
    """``{'cloud', 'local_fast', 'local'}``: seconds of the gate runs of this process (the pass report; the loop's share)."""
    return {k: round(v, 3) for k, v in GATE_SECS.items()}


def _run_once_raw(root, tests, timeout_s, workdir, wait_s, progress, deselect, waits, trace=(),
                  touched=None) -> GateResult:
    """Run ``tests`` (pytest node ids / files / dirs) in ``root`` in one pytest call; the verdict comes from JUnit XML.
    ``deselect``: node ids left out of the call. ``progress`` (a dict) receives what a call cut at the limit did: the
    collected names in run order ('items') and the started ones ('started'). ``trace`` (source prefixes): the profile
    plugin rides in the same call and GateResult.path gets the functions the failing tests ran; any fault of it
    (no file, a broken file, a timeout) leaves path empty, never the verdict changed."""
    root = Path(root)
    for t in [*tests, *deselect]:
        raw = t.split('::', 1)[0]
        parts = _clean(raw)
        if parts is None or any(seg.startswith('-') for seg in parts):
            return _failure(-1, f'test path not allowed (outside the repository or option-like): {raw}')
    tests = [_node(t) for t in tests]
    if not tests:
        return _failure(-1, 'no tests given')
    if SELF_REPO and (touched is None or deselect):
        # the second instance has no local run on any path (a continuation, a hung list, a deselect): never pytest here
        return replace(_failure(-1, NOT_STARTED + 'cloud: cloud_down'), env_reason='cloud_down')
    if touched is not None and not deselect and (SELF_REPO or not _known_fast(root, tests)):   # the product route runs the profile plugin too
        cloud = _cloud_attempt(root, tests, touched, trace)
        if cloud is not None:
            _where['v'] = 'cloud'
            return cloud                         # no slot is taken and no RAM is waited for: the run was not here
    elif touched is not None and not deselect:
        _where['v'] = 'local_fast'               # known fast: it runs here, in a local slot, and never goes to the cloud
    try:
        factory_tree.materialize(root)           # a sparse candidate tree is filled in only when pytest really runs here
    except OSError as error:
        return replace(_failure(-1, NOT_STARTED + 'tree'), env_reason='tree: ' + type(error).__name__)
    # ignore_cleanup_errors: a handle still held after the tree was killed must not crash the pass.
    with tempfile.TemporaryDirectory(prefix='factory-gate-', dir=workdir, ignore_cleanup_errors=True) as d:
        xml = Path(d) / 'result.xml'
        log = Path(d) / 'progress.txt'
        env, plugin = _env(d), []
        try:
            (Path(d) / 'plug').mkdir()
            (Path(d) / 'plug' / (PROGRESS_PLUGIN + '.py')).write_text(_PROGRESS_SOURCE, encoding='utf-8')
            env.update(PYTHONPATH=str(Path(d) / 'plug'), FACTORY_PROGRESS_OUT=str(log))
            plugin = ['-p', PROGRESS_PLUGIN]
        except OSError:
            pass      # without progress a cut call goes on file by file only
        profile = Path(d) / 'profile.json'
        if trace and plugin:
            try:
                (Path(d) / 'plug' / (PROFILE_PLUGIN + '.py')).write_text(_PROFILE_PLUGIN, encoding='utf-8')
                env.update(FACTORY_PROFILE_ROOT=str(root), FACTORY_PROFILE_OUT=str(profile),
                           FACTORY_PROFILE_PREFIXES='|'.join(trace))
                plugin += ['-p', PROFILE_PLUGIN]
            except OSError:
                pass  # no trace: the verdict as without it
        args = [sys.executable, '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider', *plugin,
                '--rootdir=' + str(root), '--basetemp=' + str(Path(d) / 'bt'),
                '--junitxml=' + str(xml), *['--deselect=' + red_ratchet.runnable(_node(t)) for t in deselect],
                *[red_ratchet.runnable(t) for t in tests]]
        try:
            with pytest_slot(wait_s) as why:
                waits.append(float(getattr(why, 'waited', 0.0) or 0.0))
                if why:
                    return replace(_failure(-1, NOT_STARTED + why), env_reason='pytest slot: ' + why)
                run = run_owned(args, cwd=str(root), env=env, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            if progress is not None:
                progress.update(_progress(log))
            return _failure(-1, TIMEOUT_DIAG % timeout_s)
        except OSError as error:
            return _failure(-1, f'cannot run pytest: {type(error).__name__}')
        tail = (run.stdout or b'')[-600:].decode('utf-8', 'replace')
        try:
            cases = list(ET.parse(xml).getroot().iter('testcase'))
        except (OSError, ET.ParseError):
            return _failure(run.returncode, 'no readable JUnit XML: ' + tail)
        path = _failing_path(profile) if trace else ()
    return _judge(cases, tests, run.returncode, tail, root, path)


FAST_LOCAL_S = 3.0     # a run known to last this long or less is not worth a push and a queue: it runs in a local slot
DURATIONS_FILE = 'tests/data/factory_durations.json'    # measured seconds per test file of the previous cloud run


def _known_fast(root, tests) -> bool:
    """True when EVERY file of ``tests`` has a recorded duration of FAST_LOCAL_S or less (the table of the base: a sparse tree
    reads it from its base). One unknown or slow file sends the whole call to the cloud. Any fault: not known fast."""
    try:
        raw = factory_tree.read_bytes(root, DURATIONS_FILE)
        table = json.loads(raw.decode('utf-8')) if raw else {}
        files = {_node(t).split('::', 1)[0] for t in tests}
        return bool(files) and isinstance(table, dict) and all(
            isinstance(table.get(f), (int, float)) and not isinstance(table.get(f), bool) and table[f] <= FAST_LOCAL_S
            for f in files)
    except (ValueError, TypeError, OSError, UnicodeError):
        return False


SELF_REPO = False   # set by the runner of the second loop instance (--self-repo): the gate is the cloud only, never a local run
CLOUD_SIGNS = ('cloud_down', 'cloud_busy', 'bad_tests', 'private_edit', 'scan_excluded')   # env_reason of a run the cloud gave no verdict for


def _cloud_sign(cg, got):
    """The env_reason string of a distinct answer of the cloud gate (CLOUD_DOWN, CLOUD_BUSY, BAD_TESTS, PRIVATE_EDIT), else ''."""
    for special, sign in zip((cg.CLOUD_DOWN, cg.CLOUD_BUSY, cg.BAD_TESTS, cg.PRIVATE_EDIT, cg.SCAN_EXCLUDED), CLOUD_SIGNS):
        if got is special:
            return sign
    return ''


_companion = {'offer': (), 'root': None, 'xml': None, 'names': ()}   # the LAST slot offered (tests look at it)
_companions: dict = {}     # W-base 2: one slot per candidate tree; the cards run in parallel and ONE shared slot was
                           # overwritten by the next card, so the neighbours of the first got a cloud run of their own
_companions_lock = threading.Lock()
COMPANION_SLOTS = 64


def _slot(root, create=False):
    key = str(root)
    with _companions_lock:
        slot = _companions.get(key)
        if slot is None and create:
            while len(_companions) >= COMPANION_SLOTS:
                _companions.pop(next(iter(_companions)))
            slot = _companions[key] = {'offer': (), 'root': key, 'xml': None, 'names': ()}
        return slot


def offer_companions(root, names):
    """The neighbour tests ``names`` of the candidate tree ``root`` go to the cloud in the SAME run as the candidate's own
    tests (one list of ids, one run) instead of a second run after it; ``cloud_each`` then finds their cases already there."""
    global _companion
    slot = _slot(root, create=True)
    slot.update(offer=tuple(_node(n) for n in names), root=str(root), xml=None, names=())
    _companion = slot
    _start_base_run(root, names)


def _take_companions(root, tests):
    slot = _slot(root)
    if slot is None or not slot['offer']:
        return []
    mine = {_node(t) for t in tests}
    extra = [n for n in slot['offer'] if n not in mine]
    slot['offer'] = ()                            # once: the first cloud call of the candidate carries them
    return extra


def _split_companions(root, xml_text, rc, tests, extra):
    """``(xml_text, rc)`` of the candidate's own tests out of a run that carried ``extra`` neighbour tests too; the whole XML
    is kept for ``cloud_each`` when every neighbour has its cases in it. Any fault: the XML as it came."""
    try:
        top = ET.fromstring(xml_text)
        cases = list(top.iter('testcase'))
        def mine(c):
            return any(_covered([c], _node(t)) for t in tests)
        def theirs(c):
            return any(_covered([c], n) for n in extra)
        own = [c for c in cases if mine(c) or not theirs(c)]
        if all(_covered(cases, n) for n in extra):
            slot = _slot(root, create=True)
            slot.update(root=str(root), xml=xml_text, names=tuple(extra))
        only = ET.Element('testsuites')
        for child in top:
            if child.tag == 'properties':
                only.append(child)
        for c in own:
            only.append(c)
        bad = any(c.find('failure') is not None or c.find('error') is not None for c in own)
        return ET.tostring(only, encoding='unicode'), (1 if bad else 0)
    except (ET.ParseError, ValueError, TypeError):
        return xml_text, rc


_base_runs: dict = {}      # <id>: (str(base), its commit) -> [{'names': nodes, 'done': Event, 'xml': str | None}]


def _base_sig(src):
    """The commit of the base ``src`` (a base run of an empty sparse tree measures that commit), '' when it is no git tree;
    a verdict measured on another commit is never read."""
    try:
        from . import factory_cloud_gate
        return factory_cloud_gate._base_sha(src) or ''
    except Exception:           # noqa: BLE001
        return ''


def _start_base_run(root, names):
    """The base run of the neighbour tests ``names`` of the candidate tree ``root`` starts NOW, beside the candidate's own
    run of them, not after it (live 26.11: neighbors_s median 171 s, up to 607 s - one cloud run on the candidate, then one
    on the base per red name). Every card on the same base commit reads it (a base verdict is the same for all of them)."""
    src = factory_tree.base_of(root)
    nodes = tuple(dict.fromkeys(_node(n) for n in names))
    if src is None or not nodes:
        return
    key = (str(src), _base_sig(src))
    entry = {'names': nodes, 'done': threading.Event(), 'xml': None}
    with _companions_lock:
        runs = _base_runs.setdefault(key, [])
        if any(set(nodes) <= set(e['names']) for e in runs):
            return
        runs.append(entry)
        while sum(len(v) for v in _base_runs.values()) > COMPANION_SLOTS:
            oldest = next(iter(_base_runs))
            _base_runs[oldest].pop(0)
            if not _base_runs[oldest]:
                del _base_runs[oldest]

    def run():
        holder = None
        try:
            from . import factory_cloud_gate
            holder = tempfile.mkdtemp(prefix='factory-nbase-')
            tree = factory_tree.sparse_tree(src, holder, {})
            got = factory_cloud_gate.attempt(tree, list(nodes), (), **({'self_repo': True} if SELF_REPO else {}))
            if not _cloud_sign(factory_cloud_gate, got) and got and (SELF_REPO or got[2]):
                entry['xml'] = got[0]
        except Exception:       # noqa: BLE001  no answer: the base run of a red name runs itself, as before
            entry['xml'] = None
        finally:
            entry['done'].set()
            if holder:
                shutil.rmtree(holder, ignore_errors=True)
    threading.Thread(target=run, name='factory-neighbour-base', daemon=True).start()


def _held_base_neighbours(root, tests):
    """The verdict of ``tests`` (a base run: touched ()) from the base run of a candidate's neighbours that is already
    going on the same base commit, or None (no such run, or it did not settle them: the base run goes on its own)."""
    src = factory_tree.base_of(root)
    if src is None:
        return None
    nodes = [_node(t) for t in tests]
    with _companions_lock:
        if not any(key[0] == str(src) for key in _base_runs):
            return None
    with _companions_lock:
        runs = list(_base_runs.get((str(src), _base_sig(src)), ()))
    entry = next((e for e in runs if nodes and set(nodes) <= set(e['names'])), None)
    if entry is None:
        return None
    from . import factory_cloud_gate
    if not entry['done'].wait(getattr(factory_cloud_gate, 'WAIT_S', 300) + 60) or not entry['xml']:
        return None
    try:
        cases = [c for c in ET.fromstring(entry['xml']).iter('testcase') if any(_covered([c], n) for n in nodes)]
    except (ET.ParseError, ValueError, TypeError):
        return None
    rc = 1 if any(c.find('failure') is not None or c.find('error') is not None for c in cases) else 0
    result = _judge(cases, nodes, rc, '', Path(root))
    return result if _conclusive(result) else None


def _held_companions(root, names):
    """The testcases of the neighbour tests ``names`` from the candidate's own cloud run, or None (they did not ride in it)."""
    slot = _slot(root)
    if slot is None or not slot['xml']:
        return None
    try:
        cases = list(ET.fromstring(slot['xml']).iter('testcase'))
    except (ET.ParseError, ValueError, TypeError):
        return None
    if not all(_covered(cases, _node(n)) for n in names):
        return None
    slot.update(xml=None, offer=(), names=())           # once
    return cases


def _cloud_attempt(root, tests, touched, trace=()):
    """The verdict of the cloud gate, or None (ineligible, error, no answer in time): the caller then runs locally,
    unchanged. Any fault of the cloud path is None, never a verdict. ``trace``: as in run_tests; the cloud shards run the
    same profile plugin and the JUnit comes back with the path of the failing tests (parse_junit fills GateResult.path)."""
    try:
        from . import factory_cloud_gate
        held = _held_base_neighbours(root, tests) if not touched else None    # touched (): a base run
        if held is not None:
            return held
        if SELF_REPO:            # the second loop instance: the cloud only, the answer is the candidate's own run; no local fallback
            extra = []           # decided before taking: the offer is left for cloud_each, which runs the neighbours itself
            got = factory_cloud_gate.attempt(root, tests, touched, self_repo=True)
        else:
            extra = _take_companions(root, tests)
            got = factory_cloud_gate.attempt(root, tests, touched, **({'companions': extra} if extra else {}), **_traced(trace))
        sign = _cloud_sign(factory_cloud_gate, got)
        if sign:                 # the cloud gave no verdict: nothing runs here; the pass is released or the row re-sliced
            return replace(_failure(-1, NOT_STARTED + 'cloud: ' + sign), env_reason=sign)
        if not got:
            return replace(_failure(-1, NOT_STARTED + 'cloud: cloud_down'), env_reason='cloud_down') if SELF_REPO else None
        xml_text, rc, trusted = got
        if extra:
            xml_text, rc = _split_companions(root, xml_text, rc, tests, extra)
        if (SELF_REPO or trusted) and _file_not_found(xml_text, root, tests):
            # the cloud could not open a test file that the candidate commit carries (the checkout's line endings, a stale
            # workflow): a fault of the environment, not of the card - no strike, no "junit not ok"
            return replace(_failure(-1, NOT_STARTED + 'cloud: cloud_down'), env_reason='cloud_down')
        result = parse_junit(xml_text, tests, rc, root, tail=_NO_TESTS_TAIL if _no_testcase(xml_text) else '')
        if (SELF_REPO or trusted) and _no_testcase(xml_text):
            return result       # the run finished and no test ran there (file missing, collection stopped): the cloud's answer, not its absence
    except Exception as error:  # noqa: BLE001  a fault while reading the cloud's answer
        # with the product route on there is no local fallback run: the pass waits for the cloud (cloud_down); None (the local
        # gate decides) stays for a process whose product route is off
        try:
            from . import factory_cloud_gate as _cg
            _cg.note_error('cloud_attempt', error)
            on = bool(_cg._product['on']) or SELF_REPO
        except Exception:       # noqa: BLE001
            on = SELF_REPO
        return replace(_failure(-1, NOT_STARTED + 'cloud: cloud_down'), env_reason='cloud_down') if on else None
    if SELF_REPO:               # the factory's own gate has no local run: a result the cloud did not settle waits for the cloud
        return result if _conclusive(result) else replace(_failure(-1, NOT_STARTED + 'cloud: cloud_down'), env_reason='cloud_down')
    if trusted:
        return result if _conclusive(result) else None
    # The mirror tree can differ from the local base: only a clean green is taken from the mirror route, a red is
    # confirmed by the local run instead of being charged as a strike.
    clean = (result.collected and result.rc == 0 and not result.failed and not result.errors
             and not result.missing and not result.crashed)
    return result if clean else None


_NO_TESTS_TAIL = ('the cloud run finished and ran no test (pytest "no tests ran", exit 4/5): a test file named in the '
                  'task is missing there or its collection stopped; this is the cloud\'s answer, not its absence')


_NOT_FOUND = re.compile(r'file or directory not found:\s*([^\s"\'<>]+)', re.I)


def _file_not_found(xml_text, root=None, tests=()) -> bool:
    """True when a collection <error> of the cloud's JUnit says pytest could not find a test file AND that file is in the
    candidate's commit (``root / file`` exists): then the cloud's checkout is at fault. A file the card never created, or the
    same words inside an ordinary failed test, is not this."""
    if root is None:
        return False
    try:
        errors = [e for e in ET.fromstring(xml_text).iter('error')]
    except (ET.ParseError, ValueError, TypeError):
        return False
    for e in errors:
        for m in _NOT_FOUND.finditer((e.get('message') or '') + '\n' + (e.text or '')):
            name = m.group(1).split('::', 1)[0].replace('\\', '/').strip('.,:;')
            if name and (Path(root) / name).is_file():
                return True
    return False


def _no_testcase(xml_text) -> bool:
    """True for a readable JUnit with no testcase at all (a finished run that ran nothing)."""
    try:
        return not list(ET.fromstring(xml_text).iter('testcase'))
    except (ET.ParseError, ValueError, TypeError):
        return False


def _conclusive(result: GateResult) -> bool:
    """A cloud answer about the candidate's own tree is taken, red or green, when every asked test ran there and nothing is
    environmental (a package the cloud lacks, a missing data file): then the local run decides."""
    return bool(result.collected) and not result.missing and not result.env_reason


def cloud_each(root, names):
    """``{name: GateResult}`` of several test names from ONE cloud run (the neighbour tests of a candidate), each judged
    by the same code as a local call of that name alone; a name the cloud did not settle (no answer, environmental, not
    all of it ran) is left out and the caller runs it locally. {} when the product route is off. When the cloud gave no verdict
    the answer is the sign of it instead of a dict: the env_reason string ``cloud_down`` / ``cloud_busy`` (no run is local
    then). Never raises."""
    try:
        cases = _held_companions(root, names)     # they rode in the candidate's own run: no second run
        if cases is None:
            _start_base_run(root, names)          # their base run goes beside this one, not after it
            from . import factory_cloud_gate
            if SELF_REPO:                         # the neighbours too go to the factory's own mirror branch, not the product route
                # `touched` here is the neighbours' own test files, not modules: they are only overlaid onto the mirror tree
                got = factory_cloud_gate.attempt(root, list(names), sorted({_node(n).split('::', 1)[0] for n in names}), self_repo=True)
            else:
                got = factory_cloud_gate.run_product(root, list(names))
            sign = _cloud_sign(factory_cloud_gate, got)
            if sign:
                return sign
            if not got:
                return {}
            cases = list(ET.fromstring(got[0]).iter('testcase'))
    except Exception:           # noqa: BLE001
        return {}
    out = {}
    for name in names:
        mine = [c for c in cases if _covered([c], _node(name))]
        rc = 1 if any(c.find('failure') is not None or c.find('error') is not None for c in mine) else 0
        result = _judge(mine, [_node(name)], rc, '', Path(root))
        if _conclusive(result):
            out[name] = result
    return out


def parse_junit(xml_text, tests, rc, root, tail='') -> GateResult:
    """The verdict of a JUnit XML produced elsewhere (the cloud gate): the same judgement as a local call."""
    try:
        top = ET.fromstring(xml_text)
        cases = list(top.iter('testcase'))
    except (ET.ParseError, ValueError, TypeError):
        return _failure(rc, 'no readable JUnit XML: ' + str(tail)[-600:])
    return _judge(cases, [_node(t) for t in tests], rc, str(tail)[-600:], Path(root), xml_path(top))


def _judge(cases, tests, rc, tail, root, path=()) -> GateResult:
    """JUnit testcases -> GateResult (counts, crashed, missing, environmental reasons)."""
    failed = sum(1 for c in cases if c.find('failure') is not None)
    errors = sum(1 for c in cases if c.find('error') is not None and c.find('failure') is None)
    skipped = sum(1 for c in cases if c.find('skipped') is not None)
    passed = len(cases) - failed - errors - skipped
    notes = []
    crashed = []
    for case in cases:
        fail = case.find('failure')
        if fail is not None:
            msg = fail.get('message') or ''
            if not (msg.startswith('assert') or msg.startswith('AssertionError')
                    or (msg.startswith('Failed:') and re.search(r'\.py:\d+: in \w', fail.text or ''))):
                crashed.append('%s::%s: %s' % (case.get('classname', ''), red_ratchet.readable(case.get('name', '')),
                                               (msg.splitlines() or [''])[0][:120]))   # an empty message too
            notes.append('failure %s::%s: %s' % (case.get('classname', ''), case.get('name', ''), msg[:300]))
        err = case.find('error')
        if err is not None:
            line = 'error %s::%s: %s' % (case.get('classname', ''), case.get('name', ''), (err.get('message') or '')[:300])
            if (err.get('message') or '').startswith('collection failure'):
                # the real cause (``E   ModuleNotFoundError: ...``) first, so the note limit never cuts it off
                real = [text[:200] for text in COLLECTION_LINE.findall(err.text or '')][-3:]
                if SELF_REPO and (err.text or '').strip():
                    # the second instance's coder has no local run to see the import fault in: it gets the traceback itself
                    notes.insert(0, line + ' | traceback: ' + (err.text or '').strip()[-TRACEBACK_LIMIT:])
                    continue
                if real:
                    notes.insert(0, line + ': ' + ' | '.join(real))
                    continue
            notes.append(line)
    missing = [t for t in tests if not _covered(cases, t)]
    if missing:
        notes.append('no testcase for: ' + ', '.join(missing))
    junit_ok = bool(cases) and errors == 0 and not missing
    reasons, env_ids = [], set()
    for case in cases:
        whys = [_env_reason(_exception_text(child), root, notes) for child in case if child.tag in ('failure', 'error')]
        reasons += whys
        if whys and all(whys):
            env_ids.add('%s::%s' % (case.get('classname', ''), red_ratchet.readable(case.get('name', ''))))
    # the environment is to blame only when EVERY red case is environmental
    env_reason = reasons[0] if reasons and all(reasons) else ''
    if not cases:
        notes.append('empty JUnit (rc=%s): %s' % (rc, tail))
    return GateResult(rc, len(cases), passed, failed, errors, skipped, junit_ok,
                      redact('\n'.join(notes[:6]))[:DIAG_LIMIT], env_reason,
                      tuple(missing),
                      tuple(sorted('%s::%s' % (c.get('classname', ''), red_ratchet.readable(c.get('name', ''))) for c in cases
                                   if c.find('failure') is not None or c.find('error') is not None)),
                      tuple(sorted(crashed)), (), tuple(sorted(env_ids)), path=path)


PROFILE_PLUGIN = 'factory_profile_plugin'
PATH_MAX = 5000      # entries of GateResult.path kept (it rides in the state's base_red record)


PATH_PROPERTY = 'factory-path'   # the <property> of a merged cloud JUnit that carries GateResult.path (JSON [[rel, qual, line], ..])


def path_of(data) -> tuple:
    """The union of the functions the failed / erroring tests of a profile (the plugin's JSON, parsed) ran; () on any fault."""
    try:
        found = {(str(c[0]), str(c[1]), int(c[2])) for v in data['tests'].values()
                 if isinstance(v, dict) and v.get('outcome') in ('failed', 'error') for c in v.get('calls') or ()}
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        return ()
    return tuple(sorted(found))[:PATH_MAX]


def _failing_path(profile) -> tuple:
    """path_of a profile FILE; () on any fault."""
    try:
        return path_of(json.loads(Path(profile).read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return ()


def xml_path(top) -> tuple:
    """GateResult.path carried by a merged cloud JUnit (its PATH_PROPERTY); () when absent or unreadable."""
    try:
        for prop in top.findall('properties/property'):     # the root's own, never a test's record_property
            if prop.get('name') == PATH_PROPERTY:
                return tuple(sorted((str(c[0]), str(c[1]), int(c[2])) for c in json.loads(prop.get('value') or '[]')))[:PATH_MAX]
    except (ValueError, TypeError, IndexError, AttributeError):
        pass
    return ()


def _exception_text(node) -> str:
    """The exception line of a failure/error: its message; for a collection error the last ``E  Name: ..`` line."""
    message = node.get('message') or ''
    if message.startswith('collection failure'):
        lines = COLLECTION_LINE.findall(node.text or '')
        return lines[-1] if lines else message
    return message


def _env_reason(message: str, root, notes=None) -> str:
    """Name of an environment error (missing module/data outside the repo) or ''. Repo modules are task red."""
    hit = ENV_ERROR.match(message.strip())
    if not hit:
        return ''
    if hit.group(1) == 'FileNotFoundError':
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", message)
        if quoted:  # a path inside the repository is the task's own defect, not the environment
            try:
                target = Path(quoted[-1])
                target = target if target.is_absolute() else Path(root) / target
                if os.path.normcase(os.path.abspath(target)).startswith(
                        os.path.normcase(os.path.abspath(root)) + os.sep):
                    return ''
            except (OSError, ValueError) as error:
                if notes is not None:
                    notes.append('env_reason: path check failed (%s), treated as environment' % type(error).__name__)
        return hit.group(1)
    module = ENV_MODULE.search(message)
    if module:
        top = module.group(1).split('.')[0]
        if (Path(root) / top).is_dir() or (Path(root) / (top + '.py')).is_file():
            return ''
        # the module's name travels with the class: the runner tells a module the CANDIDATE started to import
        # (its defect) from a package the factory's venv lacks (the environment)
        return '%s: %s' % (hit.group(1), module.group(1))
    return hit.group(1)


_SKIP_DIRS = frozenset(('.git', '__pycache__', 'node_modules', '.venv', 'venv', '.pytest_cache'))


def _imports(text: str, top: str) -> bool:
    return re.search(r'^\s*(?:import|from)\s+' + re.escape(top) + r'(?:[.\s,]|$)', text, re.M) is not None


def _project_imports(root, top: str) -> bool:
    """True when a .py file of the project at ``root`` imports the package ``top``."""
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for file in files:
            if file.endswith('.py'):
                try:
                    if _imports((Path(folder) / file).read_text(encoding='utf-8', errors='replace'), top):
                        return True
                except OSError:
                    continue
    return False


def candidate_import(result: GateResult, base_root, tree, changed) -> GateResult:
    """THE decision "environment or the candidate" for a missing module (critic 19.11: it had a second owner in the
    runner). A module only the candidate's changed files import, which no file of the base project imports, is the
    candidate's own defect: env_reason cleared (the red result is judged like any red one) and a note for the next
    attempt. A package the project already imports and this venv lacks stays the environment (parked, no strike)."""
    kind, _, module = (result.env_reason or '').partition(':')
    module = module.strip()
    if kind.strip() not in ('ModuleNotFoundError', 'ImportError') or not re.fullmatch(r'[\w.]+', module):
        return result
    top = module.split('.')[0]
    mine = False
    for name in changed or ():
        if name.endswith('.py'):
            try:
                mine = mine or _imports(Path(tree).joinpath(*name.split('/')).read_text(
                    encoding='utf-8', errors='replace'), top)
            except OSError:
                continue
    if not mine or _project_imports(base_root, top):
        return result
    note = ('the candidate imports a module that is not available: %s (use only the project modules and the '
            'standard library)' % module)
    return replace(result, env_reason='', diag=redact(note + '\n' + result.diag)[:DIAG_LIMIT])


# Base for a unit_test task: the new test does not exist yet, so nothing may be compared against it.
EMPTY_BASE = GateResult(0, 0, 0, 0, 0, 0, True, 'unit_test: no base tests')


def red_before(base_root, tests, timeout_s, kind=None, wait_s=None, workdir=None, trace=(), touched=None):
    """``(verdict, GateResult)``, verdict in red | green | unknown. ``trace``: see run_tests (GateResult.path).

    red: at least one task test fails on the base (not by a missing module/data: that is unknown). green: junit_ok and nothing red (the task is
    already done). unknown: timeout, no XML, no file: never read as green. unit_test: red at once.
    """
    if kind == 'unit_test':
        return 'red', EMPTY_BASE
    result = run_tests(base_root, tests, timeout_s, workdir=workdir, wait_s=wait_s, **_traced(trace),
                       **({'touched': touched} if touched is not None else {}))   # () = the cloud may run the base too
    if result.failed + result.errors > 0:
        # a file killed at the limit (run_tests) is not a doubt about the red of the files that ran
        only_timed_out = bool(result.timed_out) and _within(result.missing, result.timed_out)
        if result.env_reason or not (result.junit_ok or not result.missing or only_timed_out):
            return 'unknown', result
        return 'red', result
    if result.junit_ok and result.passed >= 1:
        return 'green', result
    return 'unknown', result


def _clean(raw: str):
    """Path segments without '', '.', trailing dots/spaces; None for absolute, drive, '..' or ':' (NTFS stream)."""
    path = raw.replace('\\', '/')
    if path.startswith('/') or re.match(r'^[A-Za-z]:', path):
        return None
    parts = []
    for seg in path.split('/'):
        if seg.rstrip('. ') == '' and '..' in seg:
            return None
        seg = seg.rstrip('. ')
        if ':' in seg:
            return None
        if seg in ('', '.'):
            continue
        parts.append(seg)
    return parts or None


def _canon(raw: str):
    """Canonical casefolded relative posix path, or None when it escapes the repository."""
    parts = _clean(raw)
    if parts is None:
        return None
    return posixpath.normpath('/'.join(parts)).casefold()


def _is_test_file(path: str) -> bool:
    return path.startswith('tests/') or path.rsplit('/', 1)[-1].startswith('test_')


def _shape(text: str):
    """(checks, test names) of a test module via ast: asserts, raises, self.assert*; qualified def test*."""
    tree = ast.parse(text)
    checks, names = 0, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            checks += 1
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr.startswith('assert') or (attr == 'raises' and isinstance(node.func.value, ast.Name)
                                             and node.func.value.id == 'pytest'):
                checks += 1

    def walk(body, prefix):
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + '.')
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test'):
                names.add(prefix + node.name)
    walk(tree.body, '')
    return checks, names


def _weak_count(text: str, is_py: bool) -> int:
    """Weakening constructs: regex over the text plus ast (multi-line imports, module aliases)."""
    count = len(WEAKENING.findall(text))
    if not is_py:
        return count
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return count
    aliases = {'pytest': set(), 'unittest': set()}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name in aliases and item.asname:
                    aliases[item.name].add(item.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == 'pytest':
            count += sum(1 for item in node.names if item.name in WEAK_NAMES)
        elif isinstance(node, ast.ImportFrom) and node.module == 'unittest':
            count += sum(1 for item in node.names if item.name.startswith('skip') or item.name == 'expectedFailure')
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in aliases['pytest'] and node.attr in WEAK_NAMES:
                count += 1
            elif node.value.id in aliases['unittest'] and (node.attr.startswith('skip') or node.attr == 'expectedFailure'):
                count += 1
        elif isinstance(node, ast.Attribute) and node.attr in ('skip', 'skipif', 'xfail') \
                and isinstance(node.value, ast.Attribute) and node.value.attr == 'mark' \
                and isinstance(node.value.value, ast.Name) and node.value.value.id in aliases['pytest']:
            count += 1
    return count


# A loosened check (acceptance 20.11: <id> dropped the ^ of link_check.ID_RE so the priority cell <id> counted as an ID;
# <id>#2 turned the fail-closed `except: return True` of generator._cancelled into `return False`). Both passed the gate
# and every critic. Counted, not listed: a regex keeps as many anchors as it had, an error path keeps its result.
REGEX_CALLS = frozenset(('compile', 'search', 'match', 'fullmatch', 'findall', 'finditer', 'sub', 'subn', 'split'))
_ANCHOR = re.compile(r'\\[AZzbB]|\\.|\[(?:\\.|[^\]\\])*\]|[\^$]')


def _anchors(pattern: str) -> int:
    """^ $ \\A \\Z \\z \\b \\B outside a character class and not escaped."""
    return sum(1 for m in _ANCHOR.finditer(pattern)
               if m.group() in ('^', '$', r'\A', r'\Z', r'\z', r'\b', r'\B'))


def _checks_of(text: str):
    """``(patterns, error_results)`` of a module: regex literals by owner (the assigned name, else ``function#``),
    each a list in order, and the constant results of each function's except handlers, in order."""
    tree = ast.parse(text)
    patterns, errors = {}, {}

    def walk(node, owner, target):
        for child in ast.iter_child_nodes(node):
            name, tgt = owner, target
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name, tgt = owner + '.' + child.name if owner else child.name, None
            elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                if len(targets) == 1 and isinstance(targets[0], ast.Name):
                    tgt = (owner + '.' if owner else '') + targets[0].id
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr in REGEX_CALLS and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == 're' and child.args and isinstance(child.args[0], ast.Constant)
                    and isinstance(child.args[0].value, str)):
                patterns.setdefault(tgt or owner + '#', []).append(child.args[0].value)
            if isinstance(child, ast.ExceptHandler):
                for sub in ast.walk(child):
                    if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant):
                        errors.setdefault(owner, []).append(sub.value.value)
            walk(child, name, tgt)
    walk(tree, '', None)
    return patterns, errors


def loosened_checks(old: str, new: str) -> list[str]:
    """What a code change loosens: a regex that lost anchors, an error path that now returns another constant."""
    try:
        old_p, old_e = _checks_of(old)
        new_p, new_e = _checks_of(new)
    except (SyntaxError, ValueError, RecursionError):
        return []
    out = []
    # summed per owner: a regex added next to an anchored one (a new `m = re.match(...)` above it) is not a loss
    for key in sorted(set(old_p) & set(new_p)):
        before, after = sum(map(_anchors, old_p[key])), sum(map(_anchors, new_p[key]))
        if after < before:
            gone = [x for x in old_p[key] if x not in new_p[key]] or old_p[key]
            came = [x for x in new_p[key] if x not in old_p[key]] or new_p[key]
            out.append('regex %s lost anchors %d -> %d (%r -> %r): a loosened matcher accepts far more than the '
                       'test needs; keep the anchor and widen only the part the case needs'
                       % (key, before, after, gone[0][:80], came[0][:80]))
    for key in sorted(set(old_e) & set(new_e)):
        if len(old_e[key]) == len(new_e[key]) and old_e[key] != new_e[key]:
            out.append('the error path of %s returns %r instead of %r: an except branch decides what happens when '
                       'the check itself fails; change the normal path instead' % (key, new_e[key], old_e[key]))
    return out


# A hollow unit test (night 20.11: five factory tests passed the gate and a critic, a brand-new test file was never
# inspected). Red only because it asserts an invented name (hasattr(trace, 'environment_consistency')),
# reads the code text instead of running it (inspect.getsource), or asserts only `is not None`.
# Deterministic: ast of the test + a symbol index of the base tree. Measured on the 796 accepted test files
# of the integration tree: the invented-name rules flag none; the source-text and not-None rules exist in accepted grep-lock files, so an edited file is
# rejected only when a rule's count grows. Not enforced (too noisy there): "a test must call project code" (~100 files).
_IDENT = re.compile(r'[A-Za-z_]\w*\Z')
_LINE = re.compile(r'line \d+ ')
_SETTERS = frozenset({'setattr', '__setattr__', 'patch', 'object', 'setitem'})   # calls that create a name by string
_INDEX: dict = {}     # resolved base root -> (signature, (names, modules)); rebuilt when a .py file changes


def _parse_py(text: str):
    try:
        return ast.parse(text.lstrip('﻿'))
    except (SyntaxError, ValueError, RecursionError):
        return None


class _Names(frozenset):
    """The identifier set of the base tree; ``words`` also holds every word inside any string literal."""
    words = frozenset()


def symbol_index(base_root):
    """``(names, modules)`` of the base tree, cached per root while no .py file changes. names: every identifier the
    non-test source defines or mentions (identifier-shaped string literals too: getattr tables, __slots__, namedtuple
    fields) plus what modules under tests/ define. modules: importable top names (folders, .py stems)."""
    root = Path(base_root)
    files, modules = [], set()
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        modules.update(dirs)
        for name in names:
            if name.endswith('.py'):
                modules.add(name[:-3])
                path = Path(folder) / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                files.append((path, st.st_mtime_ns, st.st_size))
    signature = hash(tuple((str(p), m, s) for p, m, s in files))
    key = str(root.resolve()) if root.exists() else str(root)
    cached = _INDEX.get(key)
    if cached and cached[0] == signature:
        return cached[1]
    found, words = set(), set()
    for path, _, _ in files:
        try:
            tree = _parse_py(path.read_text(encoding='utf-8', errors='replace'))
        except OSError:
            continue
        if tree is None:
            continue
        in_tests = path.relative_to(root).parts[0] == 'tests'
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                words.update(_WORD.findall(n.value))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.add(n.name)
            elif isinstance(n, ast.alias):
                found.add((n.asname or n.name).split('.')[-1])
                if not in_tests:
                    found.update(n.name.split('.'))
            elif in_tests:
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    found.add(n.id)
                elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name) \
                        and n.value.id in ('self', 'cls'):
                    found.add(n.attr)
            elif isinstance(n, ast.Name):
                found.add(n.id)
            elif isinstance(n, ast.Attribute):
                found.add(n.attr)
            elif isinstance(n, ast.arg):
                found.add(n.arg)
            elif isinstance(n, ast.keyword) and n.arg:
                found.add(n.arg)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and _IDENT.match(n.value):
                found.add(n.value)
    names_out = _Names(found)
    names_out.words = frozenset(words)
    result = (names_out, frozenset(modules))
    _INDEX[key] = (signature, result)
    return result


def _defined_names(text: str) -> set:
    """What a test module defines or stores itself (its own helpers and the attributes it sets)."""
    tree = _parse_py(text)
    out = set()
    if tree is None:
        return out
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            out.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store):
            out.add(n.attr)
        elif isinstance(n, ast.Call) and (n.func.attr if isinstance(n.func, ast.Attribute) else getattr(
                n.func, 'id', None)) in _SETTERS:
            # setattr(obj, 'n'), monkeypatch.setattr('pkg.mod.n', ...), mock.patch.object(obj, 'n', create=True),
            # mock.patch('pkg.mod.n', create=True), object.__setattr__(obj, 'n', v), monkeypatch.setitem(d, 'n', v)
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    last = a.value.rsplit('.', 1)[-1]
                    if _IDENT.match(last):
                        out.add(last)
    return out


def _negated(node) -> bool:
    """Under `not`, compared with False/None, or inside assertFalse/assertIsNone: proves a name is ABSENT."""
    cur = node
    while hasattr(cur, '_up'):
        up = cur._up
        if isinstance(up, ast.UnaryOp) and isinstance(up.op, ast.Not):
            return True
        if isinstance(up, ast.Compare) and any(isinstance(c, ast.Constant) and c.value in (False, None)
                                               for c in up.comparators):
            return True
        if isinstance(up, ast.Call) and isinstance(up.func, ast.Attribute) and up.func.attr in (
                'assertFalse', 'assertIsNone'):
            return True
        if isinstance(up, ast.stmt):
            return False
        cur = up
    return False


def _in_assert(node) -> bool:
    cur = node
    while hasattr(cur, '_up'):
        up = cur._up
        if isinstance(up, ast.Assert):
            return True
        if isinstance(up, ast.Call) and isinstance(up.func, ast.Attribute) and up.func.attr in (
                'assertTrue', 'assertIsNotNone', 'assertEqual'):
            return True
        if isinstance(up, ast.stmt):
            return False
        cur = up
    return False


def _lookup_keys(node) -> list:
    """The string keys / attribute names looked up inside one expression: x['k'], x.get('k'), hasattr(x, 'k'),
    getattr(x, 'k')."""
    keys = []
    for n in ast.walk(node):
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
            keys.append(n.slice.value)
        elif isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant)                 and isinstance(n.args[0].value, str) and isinstance(n.func, ast.Attribute) and n.func.attr == 'get':
            keys.append(n.args[0].value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('hasattr', 'getattr')                 and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
            keys.append(n.args[1].value)
    return keys


def _key_lookups(expr, loop_var=None) -> list:
    """``[(key_or_None, node)]`` for the lookups inside one expression that are compared to something:
    ``'k' in x``, ``x['k'] == v``, ``x.get('k') is v``. With ``loop_var`` a lookup by that loop variable is reported
    with ``None`` as its key."""
    def keyof(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if loop_var and isinstance(node, ast.Name) and node.id == loop_var:
            return None
        return False

    found = []
    for n in ast.walk(expr):
        cand = None
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.In):
            cand = keyof(n.left)
        elif isinstance(n, ast.Subscript) and isinstance(getattr(n, '_up', None), ast.Compare):
            cand = keyof(n.slice)
        elif isinstance(n, ast.Call) and n.args and isinstance(n.func, ast.Attribute) and n.func.attr == 'get' \
                and isinstance(getattr(n, '_up', None), ast.Compare):
            cand = keyof(n.args[0])
        if cand is not False and not _negated(n):
            found.append((cand, n))
    return found


def _word_counts(nodes) -> dict:
    from collections import Counter
    out = Counter()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                out.update(_WORD.findall(n.value))
    return out


def _unknown_membership_hits(tree, known, words) -> list:
    """Rule G, membership form: an assert of ``'k' in x`` / ``x['k']`` / ``x.get('k')`` compared to a value, directly
    or through a for-loop over a tuple/list of string constants, where the key is identifier-shaped, occurs nowhere in
    the base tree and nowhere else in the test file (a key the test builds in a fixture is fine). A loop is hollow
    when at least half of its constants are such unknown keys."""
    # words of every string the test holds, except docstrings and assert messages (prose, not data)
    prose = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    prose |= {id(n.msg) for n in ast.walk(tree) if isinstance(n, ast.Assert) and n.msg is not None}
    total = _word_counts([n for n in ast.walk(tree) if isinstance(n, ast.Constant) and id(n) not in prose])
    out = []
    for loop in ast.walk(tree):
        if not (isinstance(loop, ast.For) and isinstance(loop.target, ast.Name)
                and isinstance(loop.iter, (ast.Tuple, ast.List)) and loop.iter.elts
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in loop.iter.elts)):
            continue
        consts = [e.value for e in loop.iter.elts]
        used = any(k is None for st in loop.body for a in ast.walk(st) if isinstance(a, ast.Assert)
                   for k, _ in _key_lookups(a.test, loop.target.id))
        inside = _word_counts([loop.iter])
        unknown = [k for k in dict.fromkeys(consts)
                   if _IDENT.match(k) and k not in known and k not in words and total[k] == inside[k]]
        if used and unknown and 2 * sum(1 for c in consts if c in unknown) >= len(consts):
            out.append(('G', 'line %d loops over keys (%s) and asserts each is looked up, but %d of %d keys occur '
                             'nowhere in the project: the keys are guessed. Look the keys up in the code and assert '
                             'the exact ones it holds' % (loop.lineno, ', '.join(repr(k) for k in dict.fromkeys(consts)),
                                                          sum(1 for c in consts if c in unknown), len(consts))))
    for assertion in ast.walk(tree):
        if not isinstance(assertion, ast.Assert):
            continue
        test = assertion.test
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            continue
        inside = _word_counts([test])
        bad = [k for k, _ in _key_lookups(test) if k and _IDENT.match(k) and k not in known and k not in words
               and total[k] == inside[k]]
        if bad:
            out.append(('G', 'line %d asserts a lookup by key (%s), but none of these keys occurs in the project: '
                             'the keys are guessed. Look the key up in the code and assert the exact one it holds'
                        % (assertion.lineno, ', '.join(repr(k) for k in dict.fromkeys(bad)))))
    return out


def _guessed_key_hits(tree, known, words=frozenset()) -> list:
    """Rule G: an assert that ORs two or more lookups by string key (``d.get('a') is True or d.get('b') is True``,
    ``x['a'] or x['b']``) where none of the keys occurs anywhere in the base tree (``known``: its identifiers and
    identifier-shaped string literals) nor elsewhere in the test itself: the author guessed the key names and the
    assert is red (or green) for no reason the code gives. A key that is not identifier-shaped cannot be looked up in
    the index, so such an assert is left alone."""
    from collections import Counter
    everywhere = Counter(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str))
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._up = parent
    out = list(_unknown_membership_hits(tree, known, words))
    for assertion in ast.walk(tree):
        if not isinstance(assertion, ast.Assert):
            continue
        test = assertion.test
        if not (isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or)):
            continue
        per_operand = [_lookup_keys(v) for v in test.values]
        looked = [k for k in per_operand if k]
        if len(looked) < 2:
            continue
        keys = [k for ks in looked for k in ks]
        if not all(_IDENT.match(k) for k in keys):
            continue
        inside = Counter(n.value for n in ast.walk(test) if isinstance(n, ast.Constant) and isinstance(n.value, str))
        if any(k in known or everywhere[k] > inside[k] for k in keys):
            continue
        out.append(('G', 'line %d asserts an OR of lookups by key (%s), but none of these keys occurs in the project: '
                         'the keys are guessed. Look the key up in the code and assert the exact value it holds'
                    % (assertion.lineno, ', '.join(repr(k) for k in dict.fromkeys(keys)))))
    return out


# What the coder is told up front about the rules below and accept_unit_test: ONE line per rule code that _hollow
# emits (a test checks the codes match), so a rule and its sentence change together.
HOLLOW_RULE_TEXT = {
    'A': 'Call the real code and assert what it returns or does; hasattr/getattr on a name that exists nowhere in '
         'the code is rejected.',
    'A2': 'Use no names or attributes that are absent from the code shown: an invented module.name is rejected.',
    'B': 'Never read the source text (inspect.getsource or similar): run the code instead.',
    'E': 'Never assert only "is not None": assert the exact value the defect gets wrong.',
    'G': 'Use no guessed dict keys: look every key up in the code; a lookup by a key found nowhere in the code is '
         'rejected.',
}
ALL_RED_RULE_TEXT = ('Every new test function must fail on today\'s code, because of the defect: one that already '
                     'passes is rejected.')
UNIT_TEST_RULES = 'The gate rejects a unit test that breaks any of these:\n' + '\n'.join(
    '- ' + text for text in (*HOLLOW_RULE_TEXT.values(), ALL_RED_RULE_TEXT))


def _hollow(text: str, names, modules) -> list:
    """``[(rule, message)]`` for one test module; see hollow_test_reasons."""
    tree = _parse_py(text)
    if tree is None:
        return []
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            c._up = n
    stdlib = getattr(sys, 'stdlib_module_names', frozenset())
    project, inspect_as = set(), {'inspect'}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            inspect_as.update(a.asname for a in n.names if a.name == 'inspect' and a.asname)
        if isinstance(n, ast.ImportFrom):
            top = (n.module or '').split('.')[0]
            if n.level > 0 or (top in modules and top not in stdlib):
                project.update(a.asname or a.name for a in n.names)
        elif isinstance(n, ast.Import):
            for a in n.names:
                top = a.name.split('.')[0]
                if top in modules and top not in stdlib:
                    project.add(a.asname or top)
    known = names | _defined_names(text)
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('hasattr', 'getattr') \
                and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
            attr = n.args[1].value
            if names and attr not in known and not attr.startswith('__') and _in_assert(n) and not _negated(n):
                out.append(('A', 'line %d asserts %s(..., %r), but %r is defined nowhere in the project (no def, '
                                 'class, assignment or attribute): the test is red only because the name is invented. '
                                 'Call the code that exists and assert its wrong behaviour'
                            % (n.lineno, n.func.id, attr, attr)))
        elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load) and isinstance(n.value, ast.Name) \
                and n.value.id in project and names and n.attr not in known and not n.attr.startswith('__') \
                and not _negated(n):
            out.append(('A2', 'line %d uses %s.%s, but %r is defined nowhere in the project: the test is red only '
                              'because the name is invented. Call the code that exists and assert its wrong behaviour'
                        % (n.lineno, n.value.id, n.attr, n.attr)))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in (
                'getsource', 'getsourcelines') and isinstance(n.func.value, ast.Name) and n.func.value.id in inspect_as:
            out.append(('B', 'line %d reads the code text (inspect.%s): a unit test must run the code and assert what '
                             'it does, not grep its source' % (n.lineno, n.func.attr)))
        elif isinstance(n, ast.ImportFrom) and n.module == 'inspect' and any(
                a.name in ('getsource', 'getsourcelines') for a in n.names):
            out.append(('B', 'line %d imports inspect.getsource: a unit test must run the code and assert what it '
                             'does, not grep its source' % n.lineno))

    if names:
        out.extend(_guessed_key_hits(tree, known, getattr(names, 'words', frozenset())))

    def tests_in(body, cls=None):
        for node in body:
            if isinstance(node, ast.ClassDef):
                yield from tests_in(node.body, node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test'):
                yield cls, node

    for cls, fn in tests_in(tree.body):
        asserts = [x for x in ast.walk(fn) if isinstance(x, ast.Assert)]
        other = any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and (
            x.func.attr.startswith('assert') or x.func.attr in ('raises', 'fail')) for x in ast.walk(fn))
        if asserts and not other and all(
                isinstance(a.test, ast.Compare) and len(a.test.ops) == 1 and isinstance(a.test.ops[0], ast.IsNot)
                and isinstance(a.test.comparators[0], ast.Constant) and a.test.comparators[0].value is None
                for a in asserts):
            out.append(('E', '%s%s (line %d) asserts only "is not None", which any result passes: assert the exact '
                             'value the defect gets wrong' % (cls.name + '.' if cls else '', fn.name, fn.lineno)))
    return out


def hollow_test_reasons(base_root, path, old: str, new: str, extra_names=()) -> list[str]:
    """Why a unit_test candidate's test module is hollow (empty = fine). A: a positive hasattr/getattr in an assert
    names something defined nowhere (``not hasattr`` proving an old name is gone is fine); <id>: ``project_module.name``
    defined nowhere; B: inspect.getsource; E: a test whose every assert is ``is not None``. ``old`` is the base copy
    ('' for a new file): then only a rule whose count grew rejects, with the hits the base did not have.
    ``extra_names``: what the candidate's other changed files define."""
    names, modules = symbol_index(base_root)
    if names:
        indexed = getattr(names, 'words', frozenset())
        names = _Names(names | frozenset(extra_names))
        names.words = indexed
    new_hits = _hollow(new or '', names, modules)
    if not old:
        return [why for _, why in new_hits]
    old_hits = _hollow(old, names, modules)
    out = []
    for rule in sorted({r for r, _ in new_hits}):
        now = [why for r, why in new_hits if r == rule]
        was = [why for r, why in old_hits if r == rule]
        if len(now) > len(was):
            seen = {_LINE.sub('', w) for w in was}
            out.extend([w for w in now if _LINE.sub('', w) not in seen] or now)
    return out


OWN_TEST_RE = re.compile(r'tests/(?:test_agent_factory\.py|test_factory_[a-z0-9_]+\.py)')   # the factory's own tests (the mirror's whitelist)


def own_test_edit(path: str, kind=None, named=(), own_tests=None) -> bool:
    """True for the second instance's edit of an existing factory test file of a code task that NAMES it (tests/test_factory_*.py).
    ``own_tests``: the caller's say (the loop, the architect); None takes the process flag SELF_REPO (the runner of the second
    instance). The product instance never gets it: tests/** stays closed to a code task there."""
    canon = _canon(path)
    if canon is None or kind == 'unit_test' or not (SELF_REPO if own_tests is None else own_tests):
        return False
    return bool(OWN_TEST_RE.fullmatch(canon)) and canon in {_canon(n) for n in named}


# W-restate: a rig card of the agent step (never of a free model: to_tasks drops the mark) may say what an existing test expects anew:
# the product's rule was replaced on purpose and the test still asks for the old one. Tests and asserts are not fewer, no skip.
RESTATE, RESTATE_AUTHOR = 'restate', 'claude-sonnet-5-5'


def is_rig_task(task):
    """W-rig: True for a code task whose contract says ``rig: true`` (a test-stand card)."""
    try:
        contract = json.loads(getattr(task, 'contract', '') or '')
    except (ValueError, TypeError):
        return False
    if not (isinstance(contract, dict) and contract.get('rig') is True and getattr(task, 'kind', 'code') == 'code'):
        return False
    return RESTATE if contract.get('restate') is True and contract.get('author') == RESTATE_AUTHOR else True


RIG_MAX_ECHO = 3    # W-rig: a rig card touches tests/** and at most this many echo_sync/** files


def rig_touch_faults(named) -> list[str]:
    """W-rig: the shape of a rig card's touch_files: tests/** and up to RIG_MAX_ECHO files of echo_sync/**, nothing else."""
    out, echo = [], 0
    for raw in named:
        canon = _canon(raw)
        if canon is None:
            out.append('%s: path outside the repository' % raw)
        elif canon.startswith('echo_sync/'):
            echo += 1
        elif not canon.startswith(('tests/', 'tools/replay/')):      # tools/replay is the stand of the recorded calls, no product
            out.append('%s: a rig card touches only tests/**, tools/replay/** and echo_sync/**' % canon)
    if echo > RIG_MAX_ECHO:
        out.append('a rig card names at most %d echo_sync files (%d named)' % (RIG_MAX_ECHO, echo))
    return out


def is_forbidden(path: str, kind=None, named=(), own_tests=None, rig=False):
    """The ONE rule of which paths a candidate may not write: the reason, or None when allowed.

    ``named``: the touch_files of the candidate's own task - only they open the factory's own code (OWNER_*), and, for the second
    instance (``own_tests`` / SELF_REPO, see own_test_edit), a factory test file of a code task. Weakening of that test is
    still refused by weakening_check (the number of test_* and of asserts never goes down).
    Canonicalised like everything else here (_canon: casefold, '//' and '.' collapsed, backslashes).
    weakening_violations and the triage (agent_factory_import) both call this."""
    canon = _canon(path)
    if canon is None:
        return 'path outside the repository'
    parts = canon.split('/')
    name = parts[-1]
    if (name in FORBIDDEN_BASENAMES
            or any(fnmatch.fnmatchcase(name, g) or fnmatch.fnmatchcase(canon, g) for g in FORBIDDEN_GLOBS)):
        return 'forbidden file'
    if ((canon in OWNER_PATHS or any(fnmatch.fnmatchcase(canon, g) for g in OWNER_GLOBS))
            and canon not in {_canon(n) for n in named}):
        return "forbidden file (the factory's own code: only a task that names it)"
    if kind != 'unit_test' and parts[0] == 'tests' and not own_test_edit(path, kind, named, own_tests):
        if rig and canon in {_canon(n) for n in named} and not rig_touch_faults(named):
            return None             # W-rig: a rig card's own named files under tests/**
        return 'tests/** may be changed only by a unit_test task'
    return None


def candidate_findings(base_root, cand_files: dict, kind) -> tuple:
    """``(hollow, extra_names)`` for the critic's execution report (facts, never a verdict): the hollow findings of the
    candidate's test files, and, for a unit_test task, the names its non-test files define that the base copy of the
    same file did not."""
    root = Path(base_root)
    hollow, extra = [], set()
    if kind != 'unit_test':
        return tuple(hollow), tuple(extra)
    defined = set()
    for raw, text in cand_files.items():
        if raw.endswith('.py'):
            defined |= _defined_names(text or '')
    for raw, text in sorted(cand_files.items()):
        if not raw.endswith('.py'):
            continue
        path = raw.replace('\\', '/')
        base_file = root / path
        try:
            old = base_file.read_text(encoding='utf-8', errors='replace') if base_file.is_file() else ''
        except OSError:
            old = ''
        if _is_test_file(path):
            hollow.extend(f'{path}: {why}' for why in hollow_test_reasons(root, path, old, text or '', defined))
        else:
            extra |= _defined_names(text or '') - _defined_names(old)
    return tuple(hollow), tuple(sorted(extra))


# Approximate by design: the words are counted per file as plain text, so a comment or a string can give a false refusal,
# and a word moved from one file of the card to another is not caught.
_RIG_MARK = re.compile(r'\b(skip|skipif|skipTest|xfail|sleep|monkeypatch)\b')


def _is_raises(node) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('raises', 'warns')


def _rig_checks(fn) -> list[str]:
    """The assert / pytest.raises nodes of a test function (in source order) as ast.dump strings."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            out.append(ast.dump(node))
        elif _is_raises(node):
            out.append(ast.dump(node))
    return sorted(out)


def _rig_tests(tree) -> dict:
    """``{qualified name: function node}`` of every test_* function (module level and in classes)."""
    found = {}

    def walk(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test'):
                found[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + '.')
    walk(tree.body, '')
    return found


def rig_weakens(base_root, cand_files: dict, restate=False) -> list[str]:
    """W-rig AST lock: the violations (``rig_weakens: <path>::<function>: ...``) of a rig candidate's tests/**/*.py files.
    Per file: the number of test_* functions and of assert/pytest.raises never goes down; no assert/pytest.raises inside
    a base test_* function is changed (ast.dump equal); skip/xfail/sleep/monkeypatch do not grow. Helpers, fixtures,
    stand classes, constants and imports are free."""
    out, root = [], Path(base_root)
    for raw, text in sorted(cand_files.items()):
        path = _canon(raw)
        if path is None or not path.startswith('tests/') or not path.endswith('.py'):
            continue
        base_file = root / path
        old = base_file.read_text(encoding='utf-8', errors='replace') if base_file.is_file() else ''
        new = text or ''
        marks = [[w for w in _RIG_MARK.findall(t) if w != 'monkeypatch' or path != 'tests/conftest.py'] for t in (new, old)]
        if len(marks[0]) > len(marks[1]):       # W-pack: a fixture of tests/conftest.py may use monkeypatch; asserts stay locked
            out.append(f'rig_weakens: {path}: new skip/xfail/sleep/monkeypatch')
        try:
            new_tree = ast.parse(new)
        except (SyntaxError, ValueError, RecursionError):
            out.append(f'rig_weakens: {path}: candidate does not parse')
            continue
        try:
            old_tree = ast.parse(old)
        except (SyntaxError, ValueError, RecursionError):
            continue
        old_fns, new_fns = _rig_tests(old_tree), _rig_tests(new_tree)
        if len(new_fns) < len(old_fns):
            out.append(f'rig_weakens: {path}: tests removed: ' + ', '.join(sorted(set(old_fns) - set(new_fns))))
        for name, fn in sorted(old_fns.items()):
            other = new_fns.get(name)
            if other is None:
                out.append(f'rig_weakens: {path}::{name}: test function is gone')
                continue
            was, now = _rig_checks(fn), _rig_checks(other)
            if len(now) < len(was):
                out.append(f'rig_weakens: {path}::{name}: assert/raises dropped {len(was)} -> {len(now)}')
            elif was != now and not restate:
                out.append(f'rig_weakens: {path}::{name}: an assert/raises changed')
    return out


BARE_ID = 'bare_id: '       # fac-52: the fault class of a test id without its parameter where the test is parametrized


def _parametrized(text) -> set:
    """The test functions ('name' or 'Class.name') of a test file's text under @...parametrize (on the function or on its class); by the AST, no run."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return set()

    def marked(node):
        return any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == 'parametrize'
                   for d in node.decorator_list)
    out = set()

    def walk(body, prefix, inherited):
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + '.', inherited or marked(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (inherited or marked(node)):
                out.add(prefix + node.name)
    walk(tree.body, '', False)
    return out


def bare_ids(base_root, contract, texts: dict) -> list[str]:
    """fac-52: the ids of test.use / test.also without a [parameter] whose test is parametrized (in ``texts`` {path: new text}, else
    in the base file): the bare id takes in every parameter, a red one of the base among them, so the station sees a partial green
    where the author's cloud run of the exact ids was green. The author must name the exact ids."""
    spec = contract.get('test') if isinstance(contract.get('test'), dict) else {}
    out, seen = [], {}
    for tid in [spec.get('use')] + list(spec.get('also') or []):
        if not isinstance(tid, str) or '::' not in tid or '[' in tid:
            continue
        path, _, name = tid.partition('::')
        if path not in seen:
            text = texts.get(path)
            if text is None:
                try:
                    text = (Path(base_root) / path).read_text(encoding='utf-8-sig', errors='replace')
                except OSError:
                    text = ''
            seen[path] = _parametrized(text)
        if name.replace('::', '.') in seen[path]:
            out.append(BARE_ID + '%s is parametrized: name the exact ids with [parameter]' % tid)
    return out


def _test_names(contract) -> set:
    """The function names of the contract's own target tests (test.use and test.also, ``path::name`` or ``path::Class::name``)."""
    spec = contract.get('test') if isinstance(contract.get('test'), dict) else {}
    ids = [spec.get('use')] + list(spec.get('also') or [])
    return {'.'.join(str(t).split('::')[1:]).split('[')[0] for t in ids if isinstance(t, str) and '::' in t}


def contract_rules(base_root, contract, cand_files: dict, *, ready=None, by_files: bool = False) -> list[str]:
    """W-intake: the ONE deterministic rule check of a contract's edit, shared by the author's cloud try (roots/cloudtry.py, before
    the run) and the station's gate (agent_factory_runner). ``cand_files``: {repo path: new text} of the changed files. Faults, each
    with its class: ``off_contract:`` the edit is outside the named parts (files, functions; a new function where a part says
    add_after); ``test_touched:`` a base test function that is not the contract's target nor named by a part changed;
    ``rig_weakens:`` a test is weaker (the AST lock); ``anchor:`` the anchor line of a part without symbols is neither in the base nor
    in the new file; ``bare_id:`` (ready code) a target id without its [parameter] where the test is parametrized (fac-52). ``ready``:
    the contract is an author's ready code (the station passes runner.ready_card; None: its parts carry code, as in cloudtry, whose
    contracts are all ready code): a ladder step's card with code is not checked for bare ids (its proof is the station's own gate)."""
    from . import factory_cards as K
    root, out = Path(base_root), []

    def rel(raw):           # the repository path as written (the case kept: the cloud's disk is case-sensitive)
        clean = _clean(raw)
        return raw if clean is None else posixpath.normpath('/'.join(clean))
    parts = [dict(p, file=rel(p['file'])) for p in contract.get('parts') or []
             if isinstance(p, dict) and isinstance(p.get('file'), str)]
    texts = {}
    for raw, text in cand_files.items():
        path = rel(raw)
        base_file = root / path
        try:
            old = base_file.read_text(encoding='utf-8-sig', errors='replace') if base_file.is_file() else ''
        except OSError:
            old = ''
        texts[path] = (old, text or '')
    touched = {}
    for path, (old, new) in texts.items():
        names = K.changed_symbols(old, new) if path.endswith('.py') else set()
        if any(p['file'] == path and p.get('add_after') for p in parts):
            names -= K.defined(new) - K.defined(old)
        touched[path] = set() if by_files else names      # fac-69: code proven in the cloud: the border is the file of the parts
    out += ['off_contract: ' + o for o in K.contract_conformance(touched, {'parts': parts})]
    targets = _test_names(contract)
    restate = (contract.get('rig') is True and contract.get('restate') is True
               and contract.get('author') == RESTATE_AUTHOR)       # the same card as is_rig_task's RESTATE
    for path, (old, new) in sorted(texts.items()):
        if not (path.startswith('tests/') and path.endswith('.py')):
            continue
        if restate:             # a restate card (rig, its named author) restates an accepted test by design
            break
        named = {s for p in parts if p['file'] == path for s in p.get('symbols') or []}
        try:
            before, after = _rig_tests(ast.parse(old)), _rig_tests(ast.parse(new))
        except (SyntaxError, ValueError, RecursionError):
            continue            # a test that does not parse is the AST lock's refusal
        out += ['test_touched: %s::%s' % (path, name) for name, fn in sorted(before.items())
                if name not in targets and name not in named and name in after and ast.dump(fn) != ast.dump(after[name])]
    out += rig_weakens(root, {p: new for p, (_, new) in texts.items()}, restate=restate)
    for part in parts:
        anchor, path = str(part.get('anchor') or ''), part['file']
        if not anchor or part.get('symbols'):        # named functions are the target; the anchor is read only without them
            continue
        old, new = texts.get(path) or (None, None)
        if old is None:
            try:
                old = new = (root / path).read_text(encoding='utf-8-sig', errors='replace')
            except OSError:
                old = new = ''
        if anchor not in old.splitlines() and anchor not in new.splitlines():
            out.append('anchor: %s: %r is not in the file' % (path, anchor))
    if ready if ready is not None else any(p.get('code') or p.get('file_text') for p in parts):     # ready code: its proof holds for the exact ids only
        out += bare_ids(root, contract, {p: new for p, (_, new) in texts.items()})
    return out


def weakening_violations(base_root, cand_files: dict, kind, named=(), own_tests=None, rig=False) -> list[str]:
    """Deterministic list of reasons a candidate weakens the checks (empty = clean); ``named`` as in is_forbidden."""
    return weakening_check(base_root, cand_files, kind, named, own_tests, rig)[0]


def weakening_check(base_root, cand_files: dict, kind, named=(), own_tests=None, rig=False):
    """``(violations, notes)``: notes are neutral remarks (a check that had to be skipped), not violations.
    ``rig``: a W-rig card (named tests/** open, the AST lock rig_weakens on top)."""
    out, notes = [], []
    root = Path(base_root)
    if rig:
        out.extend(rig_weakens(root, cand_files, restate=rig == RESTATE))
    extra = set()
    if kind == 'unit_test':
        for raw, text in cand_files.items():
            if raw.endswith('.py'):
                extra |= _defined_names(text or '')
    for raw, text in sorted(cand_files.items()):
        path = _canon(raw)
        reason = is_forbidden(raw, kind, named, own_tests, rig)
        if reason is not None:
            out.append(f'{raw if path is None else path}: {reason}')
            continue
        own_edit = own_test_edit(raw, kind, named, own_tests)
        old, base_exists = '', False
        base_file = root / raw.replace('\\', '/')
        try:
            inside = base_file.resolve().is_relative_to(root.resolve())
        except OSError:
            inside = False
        if base_file.exists() and not inside:
            out.append(f'{path}: resolves outside the repository')
            continue
        if inside and base_file.is_file():
            old, base_exists = base_file.read_text(encoding='utf-8', errors='replace'), True
        new = text or ''
        is_py = path.endswith('.py')
        before, after = _weak_count(old, is_py), _weak_count(new, is_py)
        if after > before:
            out.append(f'{path}: skip/xfail/exit markers grew {before} -> {after}')
        if is_py and base_exists and not _is_test_file(path):
            out.extend(f'{path}: {why}' for why in loosened_checks(old, new))
        if kind == 'unit_test' and is_py and _is_test_file(path):    # new files too: they had no content check
            out.extend(f'{path}: {why}' for why in hollow_test_reasons(root, path, old, new, extra))
        if own_edit and not base_exists:
            out.append(f'{path}: a code task edits an existing factory test, it does not create one')
            continue
        if (kind == 'unit_test' or own_edit) and base_exists and _is_test_file(path) and path.endswith('.py'):
            try:
                old_checks, old_names = _shape(old)
            except (SyntaxError, ValueError, RecursionError):
                notes.append(f'{path}: base test file does not parse, assert/test-name comparison skipped')
                continue
            try:
                new_checks, new_names = _shape(new)
            except (SyntaxError, ValueError, RecursionError):
                out.append(f'{path}: candidate test file does not parse')
                continue
            if new_checks < old_checks:
                out.append(f'{path}: checks (assert/raises) dropped {old_checks} -> {new_checks}')
            if old_names - new_names:
                out.append(f'{path}: tests removed: ' + ', '.join(sorted(old_names - new_names)))
    return out, notes


def target_names(contract) -> tuple:
    """The functions ('test_x' or 'test_x[param]') the contract names as its target (test.use, test.also)."""
    spec = contract.get('test') if isinstance(contract, dict) else None
    if not isinstance(spec, dict) or not isinstance(spec.get('use'), str):
        return ()
    also = spec.get('also') if isinstance(spec.get('also'), (list, tuple)) else ()
    return tuple(str(u).split('::')[-1] for u in (spec['use'], *also) if '::' in str(u))


def _is_target(red_id, names) -> bool:
    tail = str(red_id).split('::', 1)[-1]
    return any(tail == n or ('[' not in n and tail.split('[', 1)[0] == n) for n in names)


def partial_left(base: GateResult, cand: GateResult, targets) -> tuple | None:
    """W-part 3: the red ids of the base the candidate leaves red, when it did what its contract asks: every target red on the base
    (at least one) is green now and nothing is red that was not red on the base. None otherwise. A file often holds reds
    of several causes; one card repairs one cause."""
    red, was = set(cand.failed_ids), set(base.failed_ids)
    if not targets or not base.junit_ok or not cand.junit_ok or cand.errors or not red or cand.failed != len(red):
        return None
    if cand.timed_out or cand.missing or not red <= was or cand.collected < base.collected or cand.skipped > base.skipped:
        return None
    if not any(_is_target(i, targets) for i in was) or any(_is_target(i, targets) for i in red):
        return None
    return tuple(sorted(red))


def accept(base: GateResult, cand: GateResult, red_before_ok: bool):
    """(ok, reason). ``red_before_ok`` is ``verdict == 'red'``. ``reason`` is ``ok`` or the first violation."""
    # TDD: the task test cannot be collected on the base (imports a module the task adds). That is a
    # known red base, not an unknown one: compare nothing with it, just demand a clean candidate.
    for side in (cand, base):         # no slot / no RAM / broken environment: never a strike, the caller releases the task
        if side.env_reason:
            return False, 'env:' + side.env_reason[:200]
    red_collection = red_before_ok and base.errors > 0 and not base.env_reason
    # red in the tests that ran, the rest cut at the limit (run_tests): known red
    red_partial = red_before_ok and bool(base.timed_out) and _within(base.missing, base.timed_out)
    if not base.junit_ok and not (red_collection or red_partial):
        return False, 'base_unknown'
    # Not measurable here on either side (live 20.11): cut at the limit on the base too (it hangs here), or red by the
    # environment on both sides (a package the gate's Python lacks). The candidate is judged on every other test;
    # anything else cut, missing or red fails it. unmeasured() names these for the report.
    spared = set(cand.env_failed) & set(base.env_failed)
    red_left = cand.failed + cand.errors - sum(1 for i in cand.failed_ids if i in spared)    # counts, not only names
    excused = (cand.collected > 0 and bool(cand.timed_out or spared) and _within(cand.missing, cand.timed_out)
               and _within(cand.timed_out, base.timed_out) and not (cand.errors and red_left > 0))
    if not cand.junit_ok and not excused:
        return False, 'junit not ok: ' + (cand.diag or 'no valid result')[:300]
    if cand.rc != 0 and not (cand.timed_out or spared):
        return False, f'rc={cand.rc} (0 required)'
    if red_left > 0:
        return False, f'failed={cand.failed} errors={cand.errors}'
    if cand.collected < 1:
        return False, 'nothing collected'
    if not red_collection and cand.collected < base.collected:
        return False, f'collected dropped {base.collected} -> {cand.collected}'
    if cand.skipped > base.skipped:
        return False, f'more skipped tests {base.skipped} -> {cand.skipped}'
    if cand.passed < 1:
        return False, f'passed={cand.passed} (at least 1 required)'
    if not red_before_ok:
        return False, 'tests were not red before (task already done or test is vacuous)'
    return True, 'ok'


def unmeasured(base: GateResult, cand: GateResult) -> tuple:
    """What an accepted candidate was not measured on (accept): cut on both sides, red by the environment on both."""
    return tuple(sorted(set(cand.timed_out) | (set(cand.env_failed) & set(base.env_failed))))


def undecided(base: GateResult, cand: GateResult) -> bool:
    """A candidate accept() refused only because the split budget left tests unrun (live 20.11 07:20, bl_E7_35: ten
    tests never ran, nothing that ran was red, and three models spent the budget in turn): no red that ran (the
    environment's red on both sides aside), and every other cut test is cut on the base too. A test the candidate
    makes hang alone while it ran on the base is its own failure, never undecided."""
    if not cand.unrun:
        return False
    spared = set(cand.env_failed) & set(base.env_failed)
    if cand.errors or any(i not in spared for i in cand.failed_ids) or cand.failed > len(spared & set(cand.failed_ids)):
        return False
    return _within(set(cand.timed_out) - set(cand.unrun), base.timed_out)


def added_tests(old_text: str, new_text: str) -> list:
    """Qualified names (``Class.test_x``) of the test functions ``new_text`` adds to ``old_text``; [] when unreadable."""
    try:
        names = _shape(new_text or '')[1]
    except (SyntaxError, ValueError, RecursionError):
        return []
    try:
        names = names - _shape(old_text or '')[1]
    except (SyntaxError, ValueError, RecursionError):
        pass
    return sorted(names)


def _red_id(case_id: str, qualified: str) -> bool:
    """Does the junit id ``classname::name[params]`` belong to the function ``Class.test_x``?"""
    klass, _, name = case_id.partition('::')
    owner, _, leaf = qualified.rpartition('.')
    if name.split('[', 1)[0] != leaf:
        return False
    return not owner or klass.rsplit('.', 1)[-1] == owner.rsplit('.', 1)[-1]


def accept_unit_test(cand_on_base: GateResult, test_text=None, backlog_id=None, added=None):
    """unit_test task: the NEW test run on the OLD base code must be red on the merits.

    With ``test_text`` and ``backlog_id`` the first line of the new test must be the marker
    ``# factory-backlog-id: <ID>`` (it is what lets the triage reuse the file only for its own row)."""
    if SELF_REPO:       # the second instance: the row of the test is known from the task; a marker is neither required nor checked
        test_text = None
    if test_text is not None and not backlog_id:
        return False, 'backlog_id не передан: маркер «# factory-backlog-id: <ID>» нечем проверить'
    if test_text is not None:
        lines = [ln.strip() for ln in test_text.lstrip('\ufeff').splitlines() if ln.strip()]
        if lines and lines[0].startswith('#!'):      # a shebang may precede the marker; blank lines never count
            lines = lines[1:]
        if not lines or lines[0] != '# factory-backlog-id: ' + backlog_id:
            return False, 'добавь маркер первой строкой: # factory-backlog-id: ' + backlog_id
    if cand_on_base.env_reason:
        return False, 'env: тест красный по среде, а не по делу: ' + cand_on_base.env_reason[:200]
    if cand_on_base.errors:
        return False, 'тест не собирается (collection/setup error): ' + (cand_on_base.diag or '')[:300]
    if not cand_on_base.junit_ok:
        return False, 'junit not ok: ' + (cand_on_base.diag or 'no valid result')[:300]
    if cand_on_base.collected < 1:
        return False, 'тест не собирается: ни одного testcase'
    if cand_on_base.failed < 1:
        return False, 'тест не ловит дефект: на старом коде зелёный'
    if cand_on_base.crashed:
        return False, 'the test crashes before its assertion on the current code: ' + cand_on_base.crashed[0] + ' - call the code the way its signature says and assert the wrong behaviour; if the defect itself is this exception, catch it and call pytest.fail with the reason'
    # every function the candidate adds must be red here: one that passes pins today's behaviour (an id the environment
    # turned red is unknown, never a pass)
    red = tuple(cand_on_base.failed_ids) + tuple(cand_on_base.env_failed)
    green = [q for q in (added or ()) if not any(_red_id(i, q) for i in red)]
    if green:
        return False, ('%s passes on the base code: it pins current behaviour instead of catching the defect'
                       % ', '.join(green))
    return True, 'ok'


# --- spectrum localisation: which source functions does a failing test really run? -------------------
# Same ignore rule as agent_factory_runner.COPY_IGNORE (runner will switch to copy_tree later).
COPY_IGNORE = shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache', '.env*', 'SECRETS_LOCAL',
                                     '*.pem', '*.key')


def copy_tree(root, dest) -> Path:
    """One-off copy of a tree (secrets and caches left out); the original is never written."""
    shutil.copytree(root, dest, ignore=COPY_IGNORE)
    return Path(dest)


# pytest plugin written into a temp folder and loaded with ``-p`` + PYTHONPATH (NOT through the
# ``tools`` package: the ECHO tree has its own ``tools``).  Mechanism: sys.monitoring, Python docs
# "sys.monitoring" (3.12+): use_tool_id / register_callback / set_events(PY_START); the callback
# returns sys.monitoring.DISABLE (one hit per code object) and restart_events() re-arms it at the
# start of every test.  Caveat: functions run while a session/module-scoped fixture is created are
# recorded for the FIRST test that needed it; pytest_fixture_setup keeps them per owner node and the end of the session gives them to every test it serves.  Without sys.monitoring: sys.setprofile / threading.setprofile ('call').
_PROFILE_PLUGIN = r'''
import json, os, sys, threading
import pytest

_root = os.path.realpath(os.environ["FACTORY_PROFILE_ROOT"])
_root_n = os.path.normcase(_root) + os.sep
_prefixes = tuple(p for p in os.environ.get("FACTORY_PROFILE_PREFIXES", "").split("|") if p)
_out = os.environ["FACTORY_PROFILE_OUT"]
_cur = set()
_tests = {}
_res = {}
_tool = None
_fallback = False
_cache = {}
_shared = {}        # node id of a module/package/session/class fixture's owner -> calls made while the fixture was built


def _rel(filename):
    r = _cache.get(filename)
    if r is None:
        r = ""
        try:
            full = os.path.realpath(filename)
        except (OSError, ValueError):
            full = ""
        if full and os.path.normcase(full).startswith(_root_n):
            rel = full[len(_root) + 1:].replace(os.sep, "/")
            if (rel.startswith(_prefixes) and not rel.startswith("tests/")
                    and rel.rsplit("/", 1)[-1] != "conftest.py"):
                r = rel
        _cache[filename] = r
    return r


def _record(code):
    rel = _rel(code.co_filename)
    if rel and "<" not in code.co_qualname:
        _cur.add((rel, code.co_qualname, code.co_firstlineno))


def _cb(code, offset):
    _record(code)
    return sys.monitoring.DISABLE


def _prof(frame, event, arg):
    if event == "call":
        _record(frame.f_code)


def pytest_configure(config):
    global _tool, _fallback
    mon = None if os.environ.get("FACTORY_PROFILE_FALLBACK") else getattr(sys, "monitoring", None)
    if mon is not None:
        for tid in (3, 4, 1, 2):
            try:
                mon.use_tool_id(tid, "factory_profile")
            except ValueError:
                continue
            mon.register_callback(tid, mon.events.PY_START, _cb)
            mon.set_events(tid, mon.events.PY_START)
            _tool = tid
            return
    _fallback = True
    sys.setprofile(_prof)
    threading.setprofile(_prof)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    global _cur
    _cur = set()
    if _tool is not None:
        sys.monitoring.restart_events()
    yield
    _tests[item.nodeid] = sorted(_cur)


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    # a wide-scope fixture is built once, inside the FIRST test that needs it: its calls belong to every test it serves
    global _cur
    if fixturedef.scope == "function":
        yield
        return
    saved, _cur = _cur, set()
    try:
        yield
    finally:
        got, _cur = _cur, saved
        _cur |= got
        try:
            _shared.setdefault(request.node.nodeid, set()).update(got)
        except Exception:
            pass


def pytest_runtest_logreport(report):
    st = _res.setdefault(report.nodeid, {"call": None, "error": False, "skipped": False, "msg": ""})
    if report.failed:
        crash = getattr(report.longrepr, "reprcrash", None)
        st["msg"] = st["msg"] or str(getattr(crash, "message", "") or "")[:300]
    if report.when == "call":
        st["call"] = report.outcome
    elif report.failed:
        st["error"] = True
    elif report.skipped:
        st["skipped"] = True


def pytest_sessionfinish(session):
    if _tool is not None:
        sys.monitoring.set_events(_tool, 0)
    else:
        sys.setprofile(None)
    tests = {}
    for nodeid, st in _res.items():
        outcome = "error" if st["error"] else (st["call"] or ("skipped" if st["skipped"] else "error"))
        mine = set(_tests.get(nodeid, []))
        for owner, calls in _shared.items():
            if not owner or nodeid == owner or nodeid.startswith(owner + "::") or nodeid.startswith(owner + "/"):
                mine |= calls
        tests[nodeid] = {"outcome": outcome, "calls": [list(c) for c in sorted(mine)],
                          "msg": st["msg"]}
    with open(_out, "w", encoding="utf-8") as f:
        json.dump({"fallback": _fallback, "tests": tests}, f)
'''


@dataclass(frozen=True)
class ProfileResult:
    verdict: str            # 'ok' | 'unknown' (timeout, no XML, nothing recorded)
    outcomes: dict          # node id -> 'passed' | 'failed' | 'error' | 'skipped'
    calls: dict             # node id -> set of (relpath, co_qualname, co_firstlineno) of source functions run
    fallback: bool = False  # sys.setprofile used instead of sys.monitoring
    diag: str = ''
    reasons: dict = field(default_factory=dict)   # node id -> first failure line of a red test
    env_reason: str = ''    # the run never started (no pytest slot / no RAM): environment, not a failed profile


def _unknown(diag: str, env_reason: str = '') -> ProfileResult:
    return ProfileResult('unknown', {}, {}, False, redact(diag)[:DIAG_LIMIT], {}, env_reason)


def profile_tests(root, tests, timeout_s, src_prefixes=('echo_sync/', 'tools/'),
                  force_fallback=False, workdir=None, wait_s=None) -> ProfileResult:
    """Run ``tests`` in a throw-away COPY of ``root`` and record, per test, which source functions
    (files under ``src_prefixes``; never tests/** or conftest) it called.  Same path as run_tests:
    run_owned (Job Object), sandboxed environment, JUnit XML, timeout.  Any failure -> verdict unknown."""
    root = Path(root)
    for t in tests:
        raw = t.split('::', 1)[0]
        parts = _clean(raw)
        if parts is None or any(seg.startswith('-') for seg in parts):
            return _unknown(f'test path not allowed: {raw}')
    if not tests:
        return _unknown('no tests given')
    with tempfile.TemporaryDirectory(prefix='factory-profile-', dir=workdir, ignore_cleanup_errors=True) as d:
        d = Path(d)
        try:
            tree = copy_tree(root, d / 'tree')
        except (OSError, shutil.Error) as error:
            return _unknown(f'cannot copy the tree: {type(error).__name__}')
        plug = d / 'plug'
        plug.mkdir()
        (plug / 'factory_profile_plugin.py').write_text(_PROFILE_PLUGIN, encoding='utf-8')
        out, xml = d / 'profile.json', d / 'result.xml'
        env = _env(d)
        env.update(PYTHONPATH=str(plug), FACTORY_PROFILE_ROOT=str(tree), FACTORY_PROFILE_OUT=str(out),
                   FACTORY_PROFILE_PREFIXES='|'.join(src_prefixes))
        if force_fallback:
            env['FACTORY_PROFILE_FALLBACK'] = '1'
        args = [sys.executable, '-m', 'pytest', '-q', '--tb=no', '-p', 'no:cacheprovider',
                '-p', 'factory_profile_plugin', '--rootdir=' + str(tree), '--basetemp=' + str(d / 'bt'),
                '--junitxml=' + str(xml), *[_rel(t.split('::', 1)[0]) + ('::' + t.split('::', 1)[1] if '::' in t else '') for t in tests]]
        try:
            with pytest_slot(wait_s) as why:
                if why:
                    return _unknown(NOT_STARTED + why, 'pytest slot: ' + why)
                run = run_owned(args, cwd=str(tree), env=env, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return _unknown(f'timeout after {timeout_s}s (process tree killed)')
        except OSError as error:
            return _unknown(f'cannot run pytest: {type(error).__name__}')
        tail = (run.stdout or b'')[-400:].decode('utf-8', 'replace')
        try:
            ET.parse(xml)
            data = json.loads(out.read_text(encoding='utf-8'))
        except (OSError, ValueError, ET.ParseError):
            return _unknown('no readable JUnit XML or profile: ' + tail)
    outcomes = {k: v['outcome'] for k, v in data['tests'].items()}
    calls = {k: {tuple(c) for c in v['calls']} for k, v in data['tests'].items()}
    if not outcomes:
        return _unknown('nothing recorded: ' + tail)
    reasons = {k: v['msg'] for k, v in data['tests'].items() if v.get('msg')}
    return ProfileResult('ok', outcomes, calls, bool(data.get('fallback')), '', reasons)


def rank_modules(outcomes: dict, calls: dict, targets=None):
    """Ochiai spectrum ranking (pure).  Ochiai(f) = ef / sqrt(F * (ef + ep)) with F the failing tests,
    ef/ep the failing/passing tests that called f.  ``targets`` (test file paths) limits the FAILING
    side to the task's own tests: a red neighbour has a defect of its own and must not shift the
    ranking; any passed test counts on the passing side.  Module score = max over its functions; equal
    scores: the module with more top-scoring functions first, then by name.
    Returns ([(module, score, n_top_functions)], {module: [(qualname, line, score)] best first})."""
    failing = {t for t, o in outcomes.items() if o in ('failed', 'error')
               and (targets is None or t.split('::', 1)[0] in targets)}
    passing = {t for t, o in outcomes.items() if o == 'passed'}
    total = len(failing)
    funcs: dict = {}
    for t in failing | passing:
        for fn in calls.get(t, ()):
            e = funcs.setdefault(fn, [0, 0])
            e[0 if t in failing else 1] += 1
    leaders: dict = {}
    for (rel, qual, line), (ef, ep) in funcs.items():
        score = ef / math.sqrt(total * (ef + ep)) if ef and total else 0.0
        if score > 0:
            leaders.setdefault(rel, []).append((qual, line, score))
    mods = []
    for rel, items in leaders.items():
        items.sort(key=lambda x: (-x[2], x[0], x[1]))
        top = items[0][2]
        mods.append((rel, top, sum(1 for x in items if x[2] >= top - 1e-9)))
    mods.sort(key=lambda m: (-m[1], -m[2], m[0]))
    return mods, leaders


# ---- path-checked scope: what the failing tests of a code task ran (GateResult.path), split by the task's files ----
# Live 20.11 12:19 on: 11 of 20 passes had no effect (the model edited code the failing test never runs). Ranking modules
# by passing siblings (rank_modules) gave noise on the real tree (<id>: settings/timers first, <id>/<id>: no passing
# sibling); the path cannot pick a module by itself, it only CHECKS a module a model names (path_lookup).

def path_split(path, touch_files) -> tuple[dict, dict]:
    """``(on, off)``: {module: sorted qualnames} of the functions in ``path`` inside / outside ``touch_files``."""
    def norm(p):
        p = str(p).replace(chr(92), '/')
        while p.startswith('./'):
            p = p[2:]
        return p
    own = {norm(t) for t in touch_files}

    def inside(rel):    # FILE level: any function of a touched file is inside the task, however the path is spelled
        rel = norm(rel)
        return rel in own or any(t.endswith('/' + rel) or rel.endswith('/' + t) for t in own)
    on: dict = {}
    off: dict = {}
    for rel, qual, _line in path or ():
        (on if inside(rel) else off).setdefault(rel, set()).add(qual)
    return ({k: sorted(v) for k, v in sorted(on.items())}, {k: sorted(v) for k, v in sorted(off.items())})


def _stem(rel: str) -> str:
    return rel.rsplit('/', 1)[-1].rsplit('.', 1)[0]


def path_lookup(off: dict, name: str):
    """The module of ``off`` that ``name`` (a CANNOT name or the file of an edit block) means: a file path, an exact
    qualname, ``stem.qualname`` or a leaf found in exactly one module; None when absent or ambiguous."""
    name = (name or '').strip().strip('`\'"*()[]:;,').replace(chr(92), '/')
    while name.startswith('./'):
        name = name[2:]
    if not name or not off:
        return None
    if name.endswith('.py'):
        hits = [m for m in off if m == name or m.endswith('/' + name)]
        return hits[0] if len(hits) == 1 else None
    # a dotted name is exact; a bare one is a leaf (``_fits`` of one module and ``FastText._fits`` of another: ambiguous)
    exact = [m for m, quals in off.items() if '.' in name
             and (name in quals or any(name == _stem(m) + '.' + q for q in quals))]
    if exact:
        return exact[0] if len(exact) == 1 else None
    leaf = name.rpartition('.')[2]
    hits = [m for m, quals in off.items() if any(q.rpartition('.')[2] == leaf for q in quals)]
    return hits[0] if len(hits) == 1 else None


_WORD = re.compile(r'[A-Za-z_]\w*')


def _words(text: str) -> set:
    """Lower-case identifier words of a text, with the parts of snake_case names (4+ letters)."""
    out = set()
    for w in _WORD.findall(text or ''):
        w = w.lower()
        if len(w) >= 3:
            out.add(w)
        out.update(p for p in w.split('_') if len(p) >= 4)
    return out


def _test_words(base_root, test_files, failed=()) -> set:
    """Identifiers and string literals of the failing test functions (``failed``: their ids), else of the whole files."""
    names = {f.rsplit('::', 1)[-1].split('[', 1)[0] for f in failed or ()}
    words: set = set()
    for rel in test_files or ():
        try:
            tree = ast.parse(Path(base_root).joinpath(*rel.split('::', 1)[0].split('/')).read_text(
                encoding='utf-8', errors='replace'))
        except (OSError, SyntaxError, ValueError):
            continue
        funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in names] or [tree]
        for f in funcs:
            for node in ast.walk(f):
                if isinstance(node, ast.Name):
                    words |= _words(node.id)
                elif isinstance(node, ast.Attribute):
                    words |= _words(node.attr)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    words |= _words(node.value)
    return words - {'self', 'test', 'tests', 'assert', 'none', 'true', 'false', 'return'}


def _def_sources(text: str) -> dict:
    """{qualname: source} of every function of a module (methods as Class.method)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    lines = text.splitlines()
    out = {}

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = prefix + child.name
                if not isinstance(child, ast.ClassDef):
                    out[qual] = '\n'.join(lines[child.lineno - 1:getattr(child, 'end_lineno', child.lineno)])
                walk(child, qual + '.')
    walk(tree, '')
    return out


def rank_path(funcs: dict, base_root, test_files, failed=()) -> list:
    """``[(module, qualname)]`` of {module: [qualnames]}, the ones whose source shares the most words with the failing
    tests first (an ORDER for a short list, never a decision); a module that cannot be read scores 0."""
    want = _test_words(base_root, test_files, failed)
    scored = []
    for rel, quals in funcs.items():
        try:
            sources = _def_sources(Path(base_root).joinpath(*rel.split('/')).read_text(encoding='utf-8',
                                                                                      errors='replace'))
        except OSError:
            sources = {}
        for q in quals:
            scored.append((-len(want & _words(sources.get(q, '') or q)), rel, q))
    return [(rel, q) for _, rel, q in sorted(scored)]


OFF_BODIES_CHARS = 4000


def off_path_bodies(off: dict, base_root, test_files, failed=(), limit: int = OFF_BODIES_CHARS, k: int = 4) -> str:
    """The bodies of the first ``k`` off-path functions (rank_path order, dunders out), one per block headed by
    ``module.qualname``, at most ``limit`` characters in all: the code the failing test runs outside the task's files,
    so a model that cannot see it is not left to guess (live 23.11: off_path / no_effect on <id>, <id>, <id>)."""
    out, used = [], 0
    for rel, q in rank_path(off, base_root, test_files, failed):
        if q.rpartition('.')[2].startswith('__') or len(out) >= k:
            continue
        try:
            body = _def_sources(Path(base_root).joinpath(*rel.split('/')).read_text(encoding='utf-8',
                                                                                  errors='replace')).get(q, '')
        except OSError:
            continue
        if not body:
            continue
        block = '# %s.%s (%s)\n%s\n' % (_stem(rel), q, rel, body)
        if used + len(block) > limit:
            if out:
                break
            block = block[:limit]
        out.append(block)
        used += len(block)
    return '\n'.join(out)


def off_path_short(off: dict, base_root, test_files, k: int = 8, failed=()) -> list:
    """The first ``k`` off-path functions as ``stem.qualname`` (rank_path order). Dunders are left out: a constructor
    shares the most words with any test (live <id>: ``ControlledMedia.__init__`` ranked first) and names no decision."""
    ranked = [(rel, q) for rel, q in rank_path(off, base_root, test_files, failed)
              if not q.rpartition('.')[2].startswith('__')]
    return ['%s.%s' % (_stem(rel), q) for rel, q in ranked[:k]]
