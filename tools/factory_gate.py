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
from .factory_process import run_owned

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


# --- laptop rule: at most 2 pytest machine-wide, and only while free RAM > 2 GB ---------------------
SLOT_NAMES = ('night_pytest.lock', 'night_pytest.lock2')   # shared with verify_run.py and the executors
SLOT_STALE_S = 120
SLOT_WAIT_S = 120
SLOT_POLL_S = 3
SLOT_TOUCH_S = 30          # a holder refreshes its slot dir at least this often (stale = 120 s)
NOT_STARTED = 'pytest not started: '   # diag prefix of a run that never began (no slot / no RAM)
MIN_FREE_RAM = 2 * 2 ** 30


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


@contextmanager
def pytest_slot(wait_s=None):
    """Hold one of the shared pytest slots while free RAM > 2 GB.  Yields '' when the run may start, else the
    reason (no slot / low RAM within the bounded wait): the caller reports unknown/environment, never a pass
    and never a strike.  The slot is released in finally."""
    dirs = list(SLOT_DIRS)
    if not dirs:                      # a gate with no slots would run unbounded: never silently
        raise RuntimeError('SLOT_DIRS is empty: the pytest slots are not configured')
    deadline = _clock() + (SLOT_WAIT_S if wait_s is None else wait_s)
    held, why = None, 'no free pytest slot'
    while True:
        free = _free_ram()
        if free is not None and free <= MIN_FREE_RAM:
            why = 'free RAM %.1f GB <= 2 GB' % (free / 2 ** 30)
        else:
            held = _take_slot(dirs)
            if held:
                break
            why = 'no free pytest slot'
        if _clock() >= deadline:
            break
        _sleep(SLOT_POLL_S)
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
        yield '' if held else why
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
    node = segments[-1] if segments else None
    for case in cases:
        cn, name = case.get('classname', ''), case.get('name', '')
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


def run_tests(root, tests, timeout_s, workdir=None, wait_s=None, hung=(), budget_s=None) -> GateResult:
    """Run ``tests`` in ``root``: one pytest call (_run_once) of at most ``timeout_s``. A call cut at the limit goes on
    in smaller calls (_fit), so a slow or a hanging test no longer hides the verdict of the others (live 20.11: three
    tasks stayed unknown or unacceptable on every pass: one test waits on a speech process, other files need more
    than 30 s under load). ``hung``: what was cut on the base (files or single tests): the run then starts file by
    file, a test of that list runs alone and its file runs without it (the joint call would only spend the limit
    again). The continuation spends at most ``budget_s`` (SPLIT_BUDGET_S) seconds."""
    deadline = time.monotonic() + (SPLIT_BUDGET_S if budget_s is None else budget_s)
    if not hung:
        parts = _fit(root, list(tests), timeout_s, workdir, wait_s, deadline, first=True)
    else:
        singles = [h for h in dict.fromkeys(hung) if '::' in h and _within([h], tests)][:HUNG_ALONE_MAX]
        parts = []
        for f in dict.fromkeys(t.split('::', 1)[0] for t in tests):
            mine = [t for t in tests if t.split('::', 1)[0] == f and t not in singles]
            if mine:
                parts += _fit(root, mine, timeout_s, workdir, wait_s, deadline, first=True,
                              deselect=[h for h in singles if _within([h], mine)])
        for h in singles:
            parts += _fit(root, [h], timeout_s, workdir, wait_s, deadline, first=True)
    return parts[0][1] if len(parts) == 1 else _merge(parts)


def _fit(root, tests, timeout_s, workdir, wait_s, deadline, first=False, deselect=()) -> list:
    """[(names, GateResult)] for ``tests``: one call; a call cut at the limit goes on. Its progress names the test that
    was running (it runs alone, last: cut alone, it hangs here and is timed out) and how many finished (the others
    run in chunks of SPLIT_SHARE of that count, each chunk the same way). Without progress (cut while collecting) a
    call over several files goes on file by file. A call after the deadline is not run (timed out: never a pass)."""
    if not first and time.monotonic() >= deadline:
        return [(tuple(tests), _failure(-1, SPENT_DIAG % timeout_s))]
    seen = {}
    result = _run_once(root, tests, timeout_s, workdir=workdir, wait_s=wait_s, progress=seen, deselect=deselect)
    if not _timed_out(result):
        return [(tuple(tests), result)]
    items, started = seen.get('items') or [], seen.get('started') or []
    if len(items) > 1 and started and started[-1] in items:
        suspect, done = started[-1], len(started) - 1
        others = [i for i in items if i != suspect]
        size = max(1, int(done * SPLIT_SHARE)) if done else len(others)
        parts = []
        for k in range(0, len(others), size):
            parts += _fit(root, others[k:k + size], timeout_s, workdir, wait_s, deadline)
        return parts + _fit(root, [suspect], timeout_s, workdir, wait_s, deadline)
    files = list(dict.fromkeys(t.split('::', 1)[0] for t in tests))
    if len(files) > 1:
        return [p for f in files for p in _fit(root, [t for t in tests if t.split('::', 1)[0] == f], timeout_s,
                                               workdir, wait_s, deadline, deselect=deselect)]
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
                      tuple(sorted({i for r in runs for i in r.env_failed})))


def _node(test: str) -> str:
    return _rel(test.split('::', 1)[0]) + ('::' + test.split('::', 1)[1] if '::' in test else '')


def _run_once(root, tests, timeout_s, workdir=None, wait_s=None, progress=None, deselect=()) -> GateResult:
    """Run ``tests`` (pytest node ids / files / dirs) in ``root`` in one pytest call; the verdict comes from JUnit XML.
    ``deselect``: node ids left out of the call. ``progress`` (a dict) receives what a call cut at the limit did: the
    collected names in run order ('items') and the started ones ('started')."""
    root = Path(root)
    for t in [*tests, *deselect]:
        raw = t.split('::', 1)[0]
        parts = _clean(raw)
        if parts is None or any(seg.startswith('-') for seg in parts):
            return _failure(-1, f'test path not allowed (outside the repository or option-like): {raw}')
    tests = [_node(t) for t in tests]
    if not tests:
        return _failure(-1, 'no tests given')
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
        args = [sys.executable, '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider', *plugin,
                '--rootdir=' + str(root), '--basetemp=' + str(Path(d) / 'bt'),
                '--junitxml=' + str(xml), *['--deselect=' + _node(t) for t in deselect], *tests]
        try:
            with pytest_slot(wait_s) as why:
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
                crashed.append('%s::%s: %s' % (case.get('classname', ''), case.get('name', ''),
                                               (msg.splitlines() or [''])[0][:120]))   # an empty message too
            notes.append('failure %s::%s: %s' % (case.get('classname', ''), case.get('name', ''), msg[:300]))
        err = case.find('error')
        if err is not None:
            notes.append('error %s::%s: %s' % (case.get('classname', ''), case.get('name', ''), (err.get('message') or '')[:300]))
    missing = [t for t in tests if not _covered(cases, t)]
    if missing:
        notes.append('no testcase for: ' + ', '.join(missing))
    junit_ok = bool(cases) and errors == 0 and not missing
    reasons, env_ids = [], set()
    for case in cases:
        whys = [_env_reason(_exception_text(child), root, notes) for child in case if child.tag in ('failure', 'error')]
        reasons += whys
        if whys and all(whys):
            env_ids.add('%s::%s' % (case.get('classname', ''), case.get('name', '')))
    # the environment is to blame only when EVERY red case is environmental
    env_reason = reasons[0] if reasons and all(reasons) else ''
    if not cases:
        notes.append('empty JUnit (rc=%s): %s' % (run.returncode, tail))
    return GateResult(run.returncode, len(cases), passed, failed, errors, skipped, junit_ok,
                      redact('\n'.join(notes[:6]))[:DIAG_LIMIT], env_reason,
                      tuple(missing),
                      tuple(sorted('%s::%s' % (c.get('classname', ''), c.get('name', '')) for c in cases
                                   if c.find('failure') is not None or c.find('error') is not None)),
                      tuple(sorted(crashed)), (), tuple(sorted(env_ids)))


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


def red_before(base_root, tests, timeout_s, kind=None, wait_s=None, workdir=None):
    """``(verdict, GateResult)``, verdict in red | green | unknown.

    red: at least one task test fails on the base (not by a missing module/data: that is unknown). green: junit_ok and nothing red (the task is
    already done). unknown: timeout, no XML, no file: never read as green. unit_test: red at once.
    """
    if kind == 'unit_test':
        return 'red', EMPTY_BASE
    result = run_tests(base_root, tests, timeout_s, workdir=workdir, wait_s=wait_s)
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


def is_forbidden(path: str, kind=None, named=()):
    """The ONE rule of which paths a candidate may not write: the reason, or None when allowed.

    ``named``: the touch_files of the candidate's own task - only they open the factory's own code (OWNER_*).
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
    if kind != 'unit_test' and parts[0] == 'tests':
        return 'tests/** may be changed only by a unit_test task'
    return None


def weakening_violations(base_root, cand_files: dict, kind, named=()) -> list[str]:
    """Deterministic list of reasons a candidate weakens the checks (empty = clean); ``named`` as in is_forbidden."""
    return weakening_check(base_root, cand_files, kind, named)[0]


def weakening_check(base_root, cand_files: dict, kind, named=()):
    """``(violations, notes)``: notes are neutral remarks (a check that had to be skipped), not violations."""
    out, notes = [], []
    root = Path(base_root)
    for raw, text in sorted(cand_files.items()):
        path = _canon(raw)
        reason = is_forbidden(raw, kind, named)
        if reason is not None:
            out.append(f'{raw if path is None else path}: {reason}')
            continue
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
        if kind == 'unit_test' and base_exists and _is_test_file(path) and path.endswith('.py'):
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


def accept_unit_test(cand_on_base: GateResult, test_text=None, backlog_id=None):
    """unit_test task: the NEW test run on the OLD base code must be red on the merits.

    With ``test_text`` and ``backlog_id`` the first line of the new test must be the marker
    ``# factory-backlog-id: <ID>`` (it is what lets the triage reuse the file only for its own row)."""
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
# recorded for the FIRST test that needed it (later tests reuse the cached value), never for the others.  Without sys.monitoring: sys.setprofile / threading.setprofile ('call').
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
        tests[nodeid] = {"outcome": outcome, "calls": [list(c) for c in _tests.get(nodeid, [])],
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
