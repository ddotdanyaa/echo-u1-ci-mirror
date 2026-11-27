"""W-prio 3: a red test that checks behaviour the product no longer has (a setting, a function, an attribute, a module that is gone).

The check is mechanical and has no model: the names the test spells out (a settings key, ``monkeypatch.setattr`` / ``setitem``,
``getattr`` without a default, ``from <product package>.x import name``) are compared with the whole product tree.  A name that is
nowhere in the tree makes the test outdated.  A name the test (or a conftest) creates itself, a name set with ``raising=False``, a
dynamic name (not a plain string) and a target that is not a product module are never counted - a false alarm hides a live defect.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

SKIP_DIRS = frozenset(('.git', '__pycache__', 'node_modules', '.venv', 'venv', 'tests', 'test', 'testing', 'build', 'dist', '.mypy_cache', '.pytest_cache'))
TEXT_SUFFIX = ('.py', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.example')
FILE_MAX = 600_000
TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
PLAIN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
SETTINGS_HINT = re.compile(r'setting|config|cfg|flag|option', re.I)


def is_test_path(rel: str) -> bool:
    parts = rel.replace('\\', '/').split('/')
    name = parts[-1]
    return (any(p in ('tests', 'test', 'testing') for p in parts[:-1]) or name.startswith('test_')
            or name.endswith('_test.py') or name == 'conftest.py')


class Index:
    """The product tree of one snapshot: every identifier of its non-test text files, the stems of its files and folders."""

    def __init__(self, root):
        self.root = Path(root)
        self.tokens: set = set()
        self.packages: set = set()
        self.files = 0
        self._build()

    def _build(self):
        for path in sorted(self.root.iterdir()) if self.root.is_dir() else ():
            if path.name in SKIP_DIRS or path.name.startswith('.'):
                continue
            if path.is_dir() or path.suffix == '.py':
                self.packages.add(path.stem if path.is_file() else path.name)
        stack = [self.root]
        while stack:
            folder = stack.pop()
            try:
                entries = list(folder.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.name in SKIP_DIRS or entry.name == '.git':
                    continue
                if entry.is_dir():
                    self.tokens.add(entry.name)
                    stack.append(entry)
                    continue
                self.tokens.add(entry.stem)
                if not entry.name.endswith(TEXT_SUFFIX):
                    continue
                try:
                    rel = entry.relative_to(self.root).as_posix()
                    if is_test_path(rel) or entry.stat().st_size > FILE_MAX:
                        continue
                    self.tokens.update(TOKEN.findall(entry.read_text(encoding='utf-8', errors='replace')))
                    self.files += 1
                except OSError:
                    continue

    def has(self, name: str) -> bool:
        return name in self.tokens


def _created(tree) -> set:
    """Names the code of ``tree`` makes itself: defs, classes, assignment targets, ``x.attr = ...``, imports' aliases."""
    made = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            made.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        made.add(sub.id)
                    elif isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Store):
                        made.add(sub.attr)
        elif isinstance(node, ast.Dict):
            made.update(k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
    return made


def _root_name(node):
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.value if not isinstance(node, ast.Call) else node.func
    return node.id if isinstance(node, ast.Name) else ''


def _text_of(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:       # noqa: BLE001 - an aid
        return ''


def _find_test(tree, test_name: str):
    """The function node of a test id tail (``Class::test_x[param]`` -> test_x), or None."""
    parts = [re.sub(r'\[.*$', '', p) for p in str(test_name).split('::') if p]
    want = parts[-1] if parts else ''
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == want:
            return node
    return None


def named_by_test(source: str, test_name: str, packages) -> list:
    """The names the test spells out about the product: ``[(kind, name)]``.  A name the test creates itself is left out.
    Returns [] when the source does not parse or the test function is not found (no judgement)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    func = _find_test(tree, test_name)
    if func is None:
        return []
    created = _created(tree)
    aliases, found = set(), []
    for node in tree.body:      # module level imports of the product
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 and node.module.split('.')[0] in packages:
            for part in node.module.split('.')[1:]:
                found.append(('module', part))
            for alias in node.names:
                if alias.name != '*':
                    aliases.add(alias.asname or alias.name)
                    found.append(('import', alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in packages:
                    aliases.add((alias.asname or alias.name).split('.')[0])
                    found.extend(('module', part) for part in alias.name.split('.')[1:])
    for node in ast.walk(func):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 and node.module.split('.')[0] in packages:
            for part in node.module.split('.')[1:]:
                found.append(('module', part))
            for alias in node.names:
                if alias.name != '*':
                    aliases.add(alias.asname or alias.name)
                    found.append(('import', alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in packages:
                    aliases.add((alias.asname or alias.name).split('.')[0])
                    found.extend(('module', part) for part in alias.name.split('.')[1:])
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr, args = node.func.attr, node.args
            raising_off = any(k.arg == 'raising' and isinstance(k.value, ast.Constant) and k.value.value is False for k in node.keywords)
            if attr == 'setattr' and not raising_off and args:
                first = args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str) and len(args) >= 2:
                    segs = first.value.split('.')       # "pkg.mod.name": the product path
                    if segs[0] in packages:
                        found.extend(('module', s) for s in segs[1:-1])
                        found.append(('attr', segs[-1]))
                elif len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str) \
                        and _root_name(first) in aliases:
                    found.append(('attr', args[1].value))
            elif attr == 'setitem' and not raising_off and len(args) >= 2 and isinstance(args[1], ast.Constant) \
                    and isinstance(args[1].value, str) and SETTINGS_HINT.search(_text_of(args[0])):
                found.append(('key', args[1].value))
            elif attr == 'get' and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str) \
                    and SETTINGS_HINT.search(_text_of(node.func.value)) and _root_name(node.func.value) in aliases:
                found.append(('key', args[0].value))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'getattr' \
                and len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str) \
                and _root_name(node.args[0]) in aliases:
            found.append(('attr', node.args[1].value))
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str) \
                and isinstance(node.ctx, ast.Load) and SETTINGS_HINT.search(_text_of(node.value)) and _root_name(node.value) in aliases:
            found.append(('key', node.slice.value))
    out, seen = [], set()
    for kind, name in found:
        if not PLAIN.match(name) or (name.startswith('__') and name.endswith('__')) or name in created or (kind, name) in seen:
            continue
        seen.add((kind, name))
        out.append((kind, name))
    return out


def _conftest_made(root: Path, rel: str) -> set:
    """Names the conftest.py files on the way to the test file create (fixtures and helpers the test relies on)."""
    made = set()
    folder = (root / rel).parent
    while True:
        conf = folder / 'conftest.py'
        if conf.is_file():
            try:
                made |= _created(ast.parse(conf.read_text(encoding='utf-8', errors='replace')))
            except (OSError, SyntaxError, ValueError):
                pass
        if folder == root or folder.parent == folder:
            break
        folder = folder.parent
    return made


def missing_names(root, test: str, index: Index | None = None) -> list:
    """The names the red test ``file::name`` spells out that are nowhere in the product tree: ``[(kind, name)]`` (empty = not outdated)."""
    root = Path(root)
    rel, _, tail = str(test).partition('::')
    path = root / rel
    try:
        source = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []
    index = index or Index(root)
    if not index.packages:
        return []
    names = named_by_test(source, tail, index.packages)
    if not names:
        return []
    made = _conftest_made(root, rel)
    return [(k, n) for k, n in names if n not in made and not index.has(n)]


def last_seen(repo, name: str, timeout: float = 8.0) -> str:
    """``<short sha> <date>`` of the last commit that touched ``name`` (git log -S), or '' when it is slow or unknown."""
    try:
        proc = subprocess.run(['git', '-C', str(repo), 'log', '-S' + name, '-1', '--format=%h %cs'],
                              capture_output=True, text=True, timeout=timeout, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def report_md(book: dict) -> str:
    """The file <state>/outdated_tests.md: test, missing name, the last commit where the name was."""
    lines = ['# Outdated tests (W-prio 3)', '',
             'A red test names something the product no longer has. It is not deleted; no cards are made for it.', '']
    for row, rec in sorted(book.items()):
        for name in rec.get('names') or []:
            lines.append('- %s: %s - `%s` (%s) - last commit with the name: %s' % (
                row, rec.get('test', ''), name.get('name', ''), name.get('kind', ''), name.get('last') or 'unknown'))
    return '\n'.join(lines) + '\n'
