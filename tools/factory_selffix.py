"""<id>, the factory fixes itself: a failure class that repeated becomes a self-fix task. A free head model designs the task (a red test and the exact change), the self-build queue runs it, the coordinator only accepts the result."""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools import factory_classes
from tools import factory_context

WHERE = {
    'search-miss': ('tools/agent_factory_runner.py', 'tools/factory_patterns.py'),
    'no-edit-block': ('tools/agent_factory_runner.py',),
    'cannot': ('tools/factory_spec.py', 'tools/agent_factory_import.py'),
    'test-hang': ('tools/factory_gate.py',),
    'gate-cut': ('tools/factory_gate.py',),
    'weak-test': ('tools/factory_gate.py', 'tools/factory_spec.py'),
    'test-crash': ('tools/factory_gate.py', 'tools/agent_factory_runner.py'),
    'review-reject': ('tools/agent_factory_runner.py',),
}
TEST_FILE_RE = re.compile(r'^tests/test_selffix_[a-z0-9_]+\.py$')
RULES = (
    'You design ONE self-fix task for a code factory. Answer with ONE JSON object and nothing else, either\n'
    '{"title": "...", "touch_files": [1-2 existing factory files under tools/], "test_file": "tests/test_selffix_<something>.py", '
    '"test_code": "<a complete pytest file that reproduces this failure class with one of the recorded examples, imports the real '
    'factory function, and fails by an assertion on the current code>", "goal": "<the exact change to make in the touch files so the test passes>"}\n'
    'or {"skip": "<why this class is not a defect of the factory code>"}.\n'
    'The test must use no network, no sleeps, no real audio. At most 2 touch files.')


def due(rows, ledger, threshold=2):
    res = []
    for cls in WHERE:
        entry = ledger.get(cls) or {}
        if entry.get('status') == 'open':
            continue
        counts = factory_classes.count(rows, entry.get('at'))
        info = counts.get(cls)
        if info and info.get('n', 0) >= threshold:
            res.append((cls, info))
    res.sort(key=lambda p: -p[1]['n'])
    return res


def head_prompt(cls, info, outlines):
    parts = [RULES, factory_classes.question(cls, info)]
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
    if not isinstance(code, str) or 'def test_' not in code:
        return None
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    if not any((isinstance(n, ast.ImportFrom) and (n.module or '').split('.')[0] == 'tools')
               or (isinstance(n, ast.Import) and any(a.name.split('.')[0] == 'tools' for a in n.names))
               for n in ast.walk(tree)):
        return None
    return {'title': title.strip(), 'touch_files': list(files), 'test_file': test_file, 'test_code': code, 'goal': goal}


def materialize(plan, src_root, self_dir, stamp, base_sha, cls='x'):
    self_dir = Path(self_dir)
    name = f"fx_{cls}_{stamp}"
    tree = self_dir / f"src_{name}"
    shutil.copytree(src_root, tree, ignore=shutil.ignore_patterns('.git', '__pycache__'))
    test_path = tree / plan['test_file']
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(plan['test_code'], encoding='utf-8', newline='\n')
    task = {'id': name, 'title': plan['title'], 'touch_files': plan['touch_files'], 'tests': [plan['test_file']],
            'goal': plan['goal'], 'read_files': [], 'privacy_safe': True, 'context_targets': {},
            'context_budget': 30000, 'estimated_tokens': 20000}
    plan_path = self_dir / f"plan_{name}.json"
    plan_path.write_text(json.dumps([task], ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    (self_dir / f"src_plan_{name}.txt").write_text(f"{tree}\n{base_sha}\n", encoding='utf-8', newline='\n')
    return plan_path


def red_on_base(tree, test_file, python, timeout=30):
    env = dict(os.environ, PYTHONUTF8='1')
    # pytest's own temp dirs stay next to the tree, never in the profile's %TEMP%: their paths reach a model through
    # the test output (the lock test_every_pytest_argv_the_factory_builds_is_cache_free_and_has_a_basetemp)
    holder = tempfile.mkdtemp(prefix='selffix-bt-', dir=str(Path(tree).parent))
    try:
        done = subprocess.run([str(python), '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                               '--basetemp=' + str(Path(holder) / 'bt'), test_file],
                              cwd=str(tree), env=env, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, 'timeout'
    finally:
        shutil.rmtree(holder, ignore_errors=True)
    text = (done.stdout or '') + (done.stderr or '')
    if done.returncode != 1:
        return False, f"rc={done.returncode}\n{text[-1500:]}"
    if re.search(r'ImportError|ModuleNotFoundError|SyntaxError|error(s)? during collection|ERROR collecting', text):
        return False, f"broken before any assertion\n{text[-1500:]}"
    if not re.search(r'AssertionError|^E\s+assert ', text, re.M):
        return False, f"not red by an assertion\n{text[-1500:]}"
    return True, text[-1500:]


def run(rows, ledger, *, ask, repo_root, src_root, self_dir, base_sha, python, now_iso, stamp):
    items = due(rows, ledger)
    if not items:
        return {'status': 'none'}
    cls, info = items[0]
    root = Path(repo_root)
    outlines = {}
    for rel in WHERE[cls]:
        try:
            outlines[rel] = factory_context.outline((root / rel).read_text(encoding='utf-8', errors='replace'), tools=False)
        except OSError:
            continue
    answer = ask(head_prompt(cls, info, outlines))
    plan = parse(answer, root)
    if plan is None:
        why = 'the answer is not a valid self-fix task'
        ledger[cls] = {'at': now_iso, 'status': 'invalid', 'why': why}
        return {'cls': cls, 'status': 'invalid', 'why': why}
    if 'skip' in plan:
        ledger[cls] = {'at': now_iso, 'status': 'skipped', 'why': plan['skip']}
        return {'cls': cls, 'status': 'skipped', 'why': plan['skip']}
    plan_path = materialize(plan, src_root, self_dir, stamp, base_sha, cls)
    tree = Path(self_dir) / f"src_fx_{cls}_{stamp}"
    ok, text = red_on_base(tree, plan['test_file'], python)
    if not ok:
        shutil.rmtree(tree, ignore_errors=True)
        for extra in (plan_path, Path(self_dir) / f"src_plan_fx_{cls}_{stamp}.txt"):
            try:
                extra.unlink()
            except OSError:
                pass
        ledger[cls] = {'at': now_iso, 'status': 'invalid', 'why': text[:300]}
        return {'cls': cls, 'status': 'invalid', 'why': text[:300]}
    ledger[cls] = {'at': now_iso, 'status': 'open', 'plan': plan_path.name}
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
