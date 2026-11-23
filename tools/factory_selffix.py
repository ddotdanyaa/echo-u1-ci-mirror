"""<id>, the factory fixes itself: a failure class that repeated becomes a self-fix task. A free head model designs the task (a red test and the exact change), the self-build queue runs it, the coordinator only accepts the result."""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from tools import factory_classes
from tools import factory_context

WHERE = {
    'search-miss': ('tools/agent_factory_runner.py', 'tools/factory_patterns.py'),
    'no-edit-block': ('tools/agent_factory_runner.py',),
    'cannot': ('tools/factory_cards.py', 'tools/agent_factory_import.py'),
    'test-hang': ('tools/factory_gate.py',),
    'gate-cut': ('tools/factory_gate.py',),
    'weak-test': ('tools/factory_gate.py', 'tools/factory_cards.py'),
    'test-crash': ('tools/factory_gate.py', 'tools/agent_factory_runner.py'),
    'review-reject': ('tools/agent_factory_runner.py',),
    # <id> audit 20.11: the two largest classes were never asked (gate-red 212 rows, token-waste 27)
    'gate-red': ('tools/factory_gate.py', 'tools/agent_factory_runner.py'),
    'token-waste': ('tools/factory_context.py', 'tools/agent_factory_runner.py'),
    'secret-leak': ('tools/agent_factory_import.py',),
}
# what a factory-side cause of the class is: most gate-red rows are red PRODUCT tests, not a factory defect
SCOPE = {
    'gate-red': 'A red product test is a defect of the product, not of the factory: answer skip unless the factory gave '
                'the coder too little to fix it (no failure diff, the test not shown) or the gate itself broke (a lock '
                'or a PermissionError in its own temp folder factory-gate-*).',
    'token-waste': 'The defect is the prompt size or the step budget the factory chose for the task, not the model.',
    'secret-leak': 'The defect is a screen that let private material through, never the private text itself.',
}
TEST_FILE_RE = re.compile(r'^tests/test_selffix_[a-z0-9_]+\.py$')
RULES = (
    'You design ONE self-fix task for a code factory. Answer with ONE JSON object and nothing else, either\n'
    '{"title": "...", "touch_files": [1-2 existing factory files under tools/], "test_file": "tests/test_selffix_<something>.py", '
    '"test_code": "<a complete pytest file that reproduces this failure class with one of the recorded examples, imports the real '
    'factory function, and fails by an assertion on the current code>", '
    '"variation_code": "<a second complete pytest file: the same failure class with a DIFFERENT recorded example or a new '
    'variation of it, also red by an assertion on the current code and green after the change>", '
    '"goal": "<the exact change to make in the touch files so both tests pass>"}\n'
    'or {"skip": "<why this class is not a defect of the factory code>"}.\n'
    'The tests must use no network, no sleeps, no real audio. At most 2 touch files.')


OPEN_MAX_S = 24 * 3600     # an open self-fix whose task never reached a candidate within a day no longer locks its class
SKIP_HOLD_S = OPEN_MAX_S   # a class the head skipped is not asked again sooner (gate-red: 5-39 rows an hour)
INVALID_HOLD_S = 6 * 3600  # nor a class whose answer was not a valid task (else the most frequent class, gate-red,
                           # took every hourly turn with invalid answers and starved the other classes)
HOLD_S = {'skipped': SKIP_HOLD_S, 'invalid': INVALID_HOLD_S}
MAX_TRIES = 5              # 21.11 (was 3): failed self-fixes of one class before the class stops spawning them (left to the backlog)
WAITING = ('REVIEW', 'DONE')   # a candidate waits for the coordinator's acceptance: not a failure, never aged out
LEDGER = 'selffix_ledger.json'   # the register of self-fixes, in the factory's self dir: one for every project


def load_ledger(self_dir, seed=None):
    """The factory-wide self-fix ledger; ``seed`` (a project's old per-state entries) fills the classes it lacks."""
    try:
        data = json.loads((Path(self_dir) / LEDGER).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for cls, entry in (seed or {}).items():
        if isinstance(entry, dict):
            data.setdefault(cls, entry)
    return data


def save_ledger(self_dir, ledger, before=None):
    """Write the classes that changed since ``before`` (None: all) over the file's current content, atomically; a
    class another project's loop changed meanwhile is kept."""
    path = Path(self_dir) / LEDGER
    current = load_ledger(self_dir)
    before = before or {}
    for cls in set(before) | set(ledger):
        if cls in before and ledger.get(cls) == before[cls]:
            continue
        if cls in ledger:
            current[cls] = ledger[cls]
        else:
            current.pop(cls, None)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8', newline='\n')
    os.replace(tmp, path)


def _iso(text):
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _age_s(at_iso, now_iso):
    at, now = _iso(at_iso), _iso(now_iso)
    if at and now and at.tzinfo == now.tzinfo:
        return (now - at).total_seconds()
    return None


def _tests_of(entry, self_dir):
    """The entry's tests; an entry opened before they were stored reads them from its plan file."""
    if entry.get('tests'):
        return list(entry['tests'])
    if self_dir is not None and entry.get('plan'):
        try:
            return list(json.loads((Path(self_dir) / entry['plan']).read_text(encoding='utf-8'))[0].get('tests') or [])
        except (OSError, ValueError, IndexError, KeyError, AttributeError, TypeError):
            pass
    return []


def _open_ended(entry, self_dir, now_iso, repo_root=None):
    """'failed' when the open entry's self-build task FAILED or was BLOCKED (its state file next to the plan), or it
    reached no candidate (REVIEW/DONE) and the entry is older than OPEN_MAX_S; 'closed' when its candidate waits and
    its tests are in the source snapshot ``repo_root`` (accept.py commits them and exports HEAD as that snapshot: the
    candidate was accepted); else ''. Live 20.11: no code moved an entry out of 'open', so a failed self-fix locked
    its class, and no class was ever closed."""
    if self_dir is not None and entry.get('plan'):
        try:
            state = json.loads((Path(self_dir) / ('state_' + entry['plan'])).read_text(encoding='utf-8'))
            statuses = {t.get('status') for t in (state.get('tasks') or {}).values() if isinstance(t, dict)}
            if statuses & {'FAILED', 'BLOCKED'}:
                return 'failed'
            if statuses & set(WAITING):
                tests = _tests_of(entry, self_dir)
                if tests and repo_root is not None and all((Path(repo_root) / t).is_file() for t in tests):
                    entry['tests'] = tests
                    return 'closed'
                return ''
        except (OSError, ValueError, AttributeError):
            pass
    age = _age_s(entry.get('at'), now_iso)
    if age is not None and age > OPEN_MAX_S:
        return 'failed'
    return ''


def due(rows, ledger, threshold=2, self_dir=None, now_iso=None, repo_root=None):
    """The classes to self-fix now, most frequent first. An open entry ends as failed or closed (_open_ended); a
    skipped class waits SKIP_HOLD_S; a closed class reopens when it repeats ``threshold`` times after it closed, a
    reopened one (its variation test turned red, run()) is due at once."""
    res = []
    for cls in WHERE:
        entry = ledger.get(cls) or {}
        if entry.get('status') == 'open':
            ended = _open_ended(entry, self_dir, now_iso, repo_root)
            if ended == 'closed':      # an accepted fix: a recurrence starts with the full MAX_TRIES again
                entry.update(status='closed', closed_at=now_iso, tries=0)
                continue
            if not ended:
                continue
            # its failures since it opened count again; MAX_TRIES failed self-fixes end the class's self-fixes
            entry.update(status='failed', closed_at=now_iso, tries=int(entry.get('tries') or 0) + 1)
        status = entry.get('status')
        if status in HOLD_S:
            age = _age_s(entry.get('at'), now_iso)
            if age is not None and age < HOLD_S[status]:
                continue
        if int(entry.get('tries') or 0) >= MAX_TRIES:
            continue
        since = entry.get('closed_at') if status in ('closed', 'reopened') else entry.get('at')
        info = factory_classes.count(rows, since).get(cls)
        if status == 'reopened':
            info = dict(info or {'n': 0, 'tasks': [], 'examples': []})
            if entry.get('why'):
                info['examples'] = list(info.get('examples') or []) + ['variation test red: ' + str(entry['why'])]
            res.append((cls, info))
            continue
        if info and info.get('n', 0) >= threshold:
            if status == 'closed':
                entry.update(status='reopened', reopened_at=now_iso)
            res.append((cls, info))
    res.sort(key=lambda p: -p[1]['n'])
    return res


def still_green(entry, repo_root, python, timeout=30):
    """(green, tail): the closed class's tests in the source snapshot; a red one (or a missing file) is not green;
    a timeout is (None, 'timeout'): no verdict."""
    tests = list(entry.get('tests') or [])
    if not tests:
        return True, 'no tests'
    rc, text = _pytest(repo_root, tests, python, timeout)
    if rc is None:
        return None, text
    return rc == 0, text[-1500:]


def head_prompt(cls, info, outlines, clean=None):
    parts = [RULES, factory_classes.question(cls, info, clean=clean)]
    if cls in SCOPE:
        parts.append(SCOPE[cls])
    for path, text in outlines.items():
        parts.append(f"Outline of {path}:\n{text}")
    return '\n\n'.join(parts)


def _first_object(answer):
    dec = json.JSONDecoder()
    pos = answer.find('{')
    while pos != -1:
        try:
            obj, _ = dec.raw_decode(answer, pos)
        except ValueError:
            pos = answer.find('{', pos + 1)
            continue
        if isinstance(obj, dict):
            return obj
        pos = answer.find('{', pos + 1)
    return None


def parse(answer, repo_root):
    obj = _first_object(answer or '')
    if obj is None:
        return None
    if 'skip' in obj:
        return {'skip': str(obj['skip'])}
    root = Path(repo_root)
    title, goal = obj.get('title'), obj.get('goal')
    files, test_file, code = obj.get('touch_files'), obj.get('test_file'), obj.get('test_code')
    if not isinstance(title, str) or not title.strip() or len(title) > 160:
        return None
    if not isinstance(goal, str) or len(goal) < 40:
        return None
    if not isinstance(files, list) or not 1 <= len(files) <= 2:
        return None
    for f in files:
        if not isinstance(f, str) or not f.startswith('tools/') or '..' in f or not (root / f).is_file():
            return None
    if not isinstance(test_file, str) or not TEST_FILE_RE.match(test_file) or (root / test_file).exists():
        return None
    variation_file = test_file[:-3] + '_variation.py'
    variation = obj.get('variation_code')
    if (root / variation_file).exists() or not _test_code_ok(code) or not _test_code_ok(variation):
        return None
    return {'title': title.strip(), 'touch_files': list(files), 'test_file': test_file, 'test_code': code,
            'variation_file': variation_file, 'variation_code': variation, 'goal': goal}


def _test_code_ok(code):
    """A pytest file that parses and imports the real factory code (tools)."""
    if not isinstance(code, str) or 'def test_' not in code:
        return False
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    return any((isinstance(n, ast.ImportFrom) and (n.module or '').split('.')[0] == 'tools')
               or (isinstance(n, ast.Import) and any(a.name.split('.')[0] == 'tools' for a in n.names))
               for n in ast.walk(tree))


def _plan_tests(plan):
    return [(plan['test_file'], plan['test_code'])] + (
        [(plan['variation_file'], plan['variation_code'])] if plan.get('variation_file') else [])


def materialize(plan, src_root, self_dir, stamp, base_sha, cls='x'):
    self_dir = Path(self_dir)
    name = f"fx_{cls}_{stamp}"
    tree = self_dir / f"src_{name}"
    shutil.copytree(src_root, tree, ignore=shutil.ignore_patterns('.git', '__pycache__'))
    for rel, code in _plan_tests(plan):
        test_path = tree / rel
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(code, encoding='utf-8', newline='\n')
    task = {'id': name, 'title': plan['title'], 'touch_files': plan['touch_files'],
            'tests': [rel for rel, _ in _plan_tests(plan)],
            'goal': plan['goal'], 'read_files': [], 'privacy_safe': True, 'context_targets': {},
            'context_budget': 30000, 'estimated_tokens': 20000}
    plan_path = self_dir / f"plan_{name}.json"
    plan_path.write_text(json.dumps([task], ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    (self_dir / f"src_plan_{name}.txt").write_text(f"{tree}\n{base_sha}\n", encoding='utf-8', newline='\n')
    return plan_path


def _pytest(tree, files, python, timeout=30):
    """(returncode, output) of pytest on ``files`` in ``tree``; a timeout is (None, 'timeout')."""
    env = dict(os.environ, PYTHONUTF8='1')
    # pytest's own temp dirs stay next to the tree, never in the profile's %TEMP%: their paths reach a model through
    # the test output (the lock test_every_pytest_argv_the_factory_builds_is_cache_free_and_has_a_basetemp)
    holder = tempfile.mkdtemp(prefix='selffix-bt-', dir=str(Path(tree).parent))
    try:
        done = subprocess.run([str(python), '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                               '--basetemp=' + str(Path(holder) / 'bt'), *files],
                              cwd=str(tree), env=env, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, 'timeout'
    finally:
        shutil.rmtree(holder, ignore_errors=True)
    return done.returncode, (done.stdout or '') + (done.stderr or '')


def red_summary(text, width=300):
    """The FAILED and E lines of a pytest output (the tail when there are none), cut to ``width``."""
    lines = [ln.strip() for ln in str(text).splitlines() if ln.startswith(('FAILED', 'E ', 'ERROR'))]
    return (' | '.join(lines) if lines else str(text).strip()[-width:])[:width]


def red_on_base(tree, test_file, python, timeout=30):
    rc, text = _pytest(tree, [test_file], python, timeout)
    if rc is None:
        return False, 'timeout'
    if rc != 1:
        return False, f"rc={rc}\n{text[-1500:]}"
    if re.search(r'ImportError|ModuleNotFoundError|SyntaxError|error(s)? during collection|ERROR collecting', text):
        return False, f"broken before any assertion\n{text[-1500:]}"
    if not re.search(r'AssertionError|^E\s+assert ', text, re.M):
        return False, f"not red by an assertion\n{text[-1500:]}"
    return True, text[-1500:]


def check_closed(ledger, repo_root, python, now_iso):
    """One closed class a call, the longest unchecked first: its tests (the repro and the variation) still green in
    the source snapshot, else the class reopens with the red lines as its newest example."""
    closed = [(c, e) for c, e in ledger.items() if isinstance(e, dict) and e.get('status') == 'closed'
              and e.get('tests')]
    if not closed or not python:
        return None
    cls, entry = min(closed, key=lambda p: str(p[1].get('checked_at') or ''))
    entry['checked_at'] = now_iso
    green, text = still_green(entry, repo_root, python)
    if green is False:      # None (a timeout on a loaded laptop) says nothing about the fix: checked again later
        entry.update(status='reopened', reopened_at=now_iso, why=red_summary(text))
    return cls


def public_info(info, rows, cls, public):
    """``info`` with only the cases and task names of ``public`` tasks (None: all): a private task's failure text
    never goes to the free head, though its row still counts; the red lines of a closed class's own factory test
    (run(), check_closed) stay."""
    if public is None:
        return info
    own = [e for e in info.get('examples') or [] if str(e).startswith('variation test red: ')]
    cases = factory_classes.cases([r for r in rows if r.get('task_id') in public], cls, k=12)
    return dict(info, examples=list(reversed(cases)) + own,
                tasks=[t for t in info.get('tasks') or [] if t in public])


def run(rows, ledger, *, ask, repo_root, src_root, self_dir, base_sha, python, now_iso, stamp, clean=None,
        public=None):
    check_closed(ledger, repo_root, python, now_iso)
    items = due(rows, ledger, self_dir=self_dir, now_iso=now_iso, repo_root=repo_root)
    if not items:
        return {'status': 'none'}
    cls, info = items[0]
    info = public_info(info, rows, cls, public)
    tries = int((ledger.get(cls) or {}).get('tries') or 0)   # carried by every new entry: the MAX_TRIES cap holds
    root = Path(repo_root)
    outlines = {}
    for rel in WHERE[cls]:
        try:
            outlines[rel] = factory_context.outline((root / rel).read_text(encoding='utf-8', errors='replace'), tools=False)
        except OSError:
            continue
    answer = ask(head_prompt(cls, info, outlines, clean=clean))
    plan = parse(answer, root)
    if plan is None:
        why = 'the answer is not a valid self-fix task'
        ledger[cls] = {'at': now_iso, 'status': 'invalid', 'why': why, 'tries': tries}
        return {'cls': cls, 'status': 'invalid', 'why': why}
    if 'skip' in plan:
        ledger[cls] = {'at': now_iso, 'status': 'skipped', 'why': plan['skip'], 'tries': tries}
        return {'cls': cls, 'status': 'skipped', 'why': plan['skip']}
    plan_path = materialize(plan, src_root, self_dir, stamp, base_sha, cls)
    tree = Path(self_dir) / f"src_fx_{cls}_{stamp}"
    tests = [rel for rel, _ in _plan_tests(plan)]
    ok, text = True, ''
    for rel in tests:                       # the repro and the variation: each red by an assertion on the base
        ok, text = red_on_base(tree, rel, python)
        if not ok:
            text = f"{rel}: {text}"
            break
    if not ok:
        shutil.rmtree(tree, ignore_errors=True)
        for extra in (plan_path, Path(self_dir) / f"src_plan_fx_{cls}_{stamp}.txt"):
            try:
                extra.unlink()
            except OSError:
                pass
        ledger[cls] = {'at': now_iso, 'status': 'invalid', 'why': text[:300], 'tries': tries}
        return {'cls': cls, 'status': 'invalid', 'why': text[:300]}
    ledger[cls] = {'at': now_iso, 'status': 'open', 'plan': plan_path.name, 'tries': tries, 'tests': tests}
    return {'cls': cls, 'status': 'open', 'plan': plan_path.name}


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes as W
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.restype = W.HANDLE
        k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        k.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
        k.CloseHandle.argtypes = [W.HANDLE]
        handle = k.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        code = W.DWORD()
        ok = k.GetExitCodeProcess(handle, ctypes.byref(code))
        k.CloseHandle(handle)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def queue_running(self_dir):
    try:
        return pid_alive(int((Path(self_dir) / 'self_queue.pid').read_text().strip()))
    except (OSError, ValueError):
        return False


_BASE = Path(os.environ.get('SystemDrive', 'C:') + '\\') / 'agent-factory'   # outside the user profile (no name)
QUEUE = _BASE / 'coord' / 'self_queue.py'
QUEUE_LOG = _BASE / 'coord' / 'self_queue.log'


def launch(code_dir, plan_name, self_dir, python, *, queue=QUEUE, log=QUEUE_LOG):
    """Start the self-build queue for one plan, detached, its lines appended to the queue log the coordinator watches;
    never a second queue next to a running one (the queue writes self_queue.pid)."""
    if queue_running(self_dir):
        return False
    flags = 0x00000008 | 0x00000200 if os.name == 'nt' else 0
    try:
        with open(log, 'a', encoding='utf-8') as fh:
            fh.write('--- self-fix queue start (%s)\n' % plan_name)
            fh.flush()
            subprocess.Popen([str(python), '-B', str(queue), str(code_dir), str(plan_name)], cwd=str(self_dir),
                             stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=flags, close_fds=True)
    except OSError:
        return False
    return True
