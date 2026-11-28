"""Minimal test set for a change: reverse import graph (static, ast), no pytest run, no LLM.

    python -m tools.affected_tests --base <sha> [--head <sha>] [--radius K] [--shards N] [--json]
    python -m tools.affected_tests path/a.py path/b.py [...]

A test file is selected when it reaches a changed file through import edges (direct = radius 1,
transitive = radius K, default unlimited), or names the changed module in a string literal
(monkeypatch targets, importlib, file paths) or, for non-.py files, mentions the file name.
Changed test file -> itself. Changed tests/conftest.py or pytest config -> every test.
Shards: greedy longest-first on cost = source lines of the test file plus its test-function count * 40.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import pickle
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIRS = ('echo_sync', 'tools', 'tests')
ALL_TESTS_TRIGGERS = {'tests/conftest.py', 'pytest.ini', 'setup.cfg', 'tox.ini', 'pyproject.toml', 'conftest.py'}


def _py_files(root: Path):
    for d in SRC_DIRS:
        for p in sorted((root / d).rglob('*.py')):
            if '__pycache__' not in p.parts:
                yield p


def _module_names(rel: str):
    """Names under which a file can be imported (tests/* also as top-level: tests dir is on sys.path)."""
    parts = rel[:-3].split('/')
    names = []
    if parts[-1] == '__init__':
        parts = parts[:-1]
    names.append('.'.join(parts))
    if parts[0] == 'tests' and len(parts) > 1:
        names.append('.'.join(parts[1:]))
    return names


def idents(node) -> set:
    """Every name a piece of code can refer to: Name ids, attribute names, import aliases, identifier-like strings."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, (ast.alias,)):
            out.update((n.name.split('.')[-1], (n.asname or '')))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 120 \
                and re.fullmatch(r'[A-Za-z_]\w*(\.[A-Za-z_]\w*)*', n.value):   # getattr/monkeypatch names, not prose
            out.update(n.value.split('.'))
    out.discard('')
    return out


def _bound(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        tg = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [n.id for t in tg for n in ast.walk(t) if isinstance(n, ast.Name)]
    return []


def top_defs(tree) -> dict:
    out = {}
    for node in tree.body:
        names = _bound(node) or ['<module>']
        for nm in names:
            out.setdefault(nm, set()).update(idents(node))
    return out


def sym_fingerprints(tree) -> dict:
    """name -> dump of the definition; classes also expose Class.method entries."""
    out = {}
    for node in tree.body:
        names = _bound(node)
        if not names:
            out['<module>'] = out.get('<module>', '') + ast.dump(node)
            continue
        for nm in names:
            out[nm] = out.get(nm, '') + ast.dump(node)
        if isinstance(node, ast.ClassDef):
            for m in node.body:
                for nm in _bound(m):
                    out[node.name + '.' + nm] = ast.dump(m)
    return out


def changed_symbols(rel, root, base):
    """Top-level names whose definition differs between base and the worktree file; None = unknown (use whole file)."""
    try:
        old = subprocess.run(['git', 'show', f'{base}:{rel}'], cwd=root, capture_output=True, text=True,
                             encoding='utf-8', errors='replace')
        if old.returncode:
            return None
        a = sym_fingerprints(ast.parse(old.stdout))
        b = sym_fingerprints(ast.parse((root / rel).read_text(encoding='utf-8', errors='replace')))
    except (SyntaxError, OSError):
        return None
    out = set()
    for k in set(a) | set(b):
        if a.get(k) != b.get(k):
            out.add(k.split('.')[0])
            if '.' in k:
                out.add(k.split('.')[1])    # a changed method is reached as obj.method
    if '<module>' in out:
        return None
    return out



# Laptop load 19.11 23:55: the old cache (keyed by folder and file, read by every import, never pruned) reached 59 MB
# on disk and about 600 MB in every runner process. Now: keyed by the file and its text, read by the first Graph only,
# at most CACHE_MAX entries (the newest). A new file name leaves the old cache unread.
_CACHE_FILE = Path(tempfile.gettempdir()) / 'affected_tests_parse_cache2.pkl'
CACHE_MAX = 20000   # entries (path, text hash) -> parse; the newest are kept
_CACHE = None       # read by the first Graph, never by the import (the loop imports this module for nothing else)


def _cache() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = pickle.loads(_CACHE_FILE.read_bytes())
        except Exception:
            _CACHE = {}
        if not isinstance(_CACHE, dict):
            _CACHE = {}
    return _CACHE


def _save_cache():
    cache = _cache()
    for key in list(cache)[:max(0, len(cache) - CACHE_MAX)]:   # the oldest first: a dict keeps insertion order
        del cache[key]
    try:
        _CACHE_FILE.write_bytes(pickle.dumps(cache))
    except Exception:
        pass


def _parse_raw(rel: str, src: str) -> dict:
    """Pure function of the file text (so it can be cached by size+mtime): imports, dotted/path strings, tests, defs."""
    raw = {'imports': [], 'dotted': [], 'paths': [], 'nt': 0, 'defs': {}}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return raw
    pkg = _module_names(rel)[0].split('.')
    if not rel.endswith('__init__.py'):
        pkg = pkg[:-1]
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                raw['imports'].append(('i', a.name, []))
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ''
            if n.level:
                up = pkg[:len(pkg) - (n.level - 1)] if n.level > 1 else pkg
                base = '.'.join(up + ([n.module] if n.module else []))
            if base:
                raw['imports'].append(('f', base, [a.name for a in n.names]))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and 4 < len(n.value) < 300:
            v = n.value
            if re.match(r'^[A-Za-z_][\w]*(\.[A-Za-z_]\w*)+$', v):
                raw['dotted'].append(v)
            elif '/' in v or v.endswith('.py'):
                raw['paths'].append(v)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test'):
            raw['nt'] += 1
    raw['defs'] = top_defs(tree)
    return raw


class Graph:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.files = {p.relative_to(root).as_posix(): p for p in _py_files(root)}
        self.mod = {}  # module name -> rel
        for rel in self.files:
            for n in _module_names(rel):
                self.mod.setdefault(n, rel)
        self.edges = {rel: set() for rel in self.files}   # rel -> files it depends on
        self.strings = {rel: set() for rel in self.files}
        self.text = {}
        self.ntests = {}
        self.defs = {}   # rel -> {top-level name: identifiers it uses}; '<module>' = loose statements
        for rel, p in self.files.items():
            self._scan(rel, p)
        _save_cache()
        self.rev = {rel: set() for rel in self.files}
        for a, deps in self.edges.items():
            for b in deps:
                self.rev[b].add(a)

    def _resolve(self, name: str):
        """Longest dotted prefix that is a module -> rel (plus parent package inits)."""
        parts = name.split('.')
        for i in range(len(parts), 0, -1):
            r = self.mod.get('.'.join(parts[:i]))
            if r:
                return r
        return None

    def _pkg_inits(self, rel: str):
        out = set()
        d = Path(rel).parent
        while str(d) not in ('.', ''):
            init = (d / '__init__.py').as_posix()
            if init in self.files and init != rel:
                out.add(init)
            d = d.parent
        return out

    def _scan(self, rel: str, p: Path):
        try:
            src = p.read_text(encoding='utf-8', errors='replace')
        except OSError:
            src = ''
        self.text[rel] = src
        cache = _cache()
        key = (rel, hashlib.sha1(src.encode('utf-8', 'replace')).hexdigest())
        raw = cache.pop(key, None)       # taken out and put back: a used entry moves to the newest end
        if raw is None:
            raw = _parse_raw(rel, src)
        cache[key] = raw
        deps = self.edges[rel]
        for kind, name, names in raw['imports']:
            r = self._resolve(name)
            if r:
                deps.add(r)
            for nm in names:
                r2 = self.mod.get(name + '.' + nm)
                if r2:
                    deps.add(r2)
        for name in raw['dotted']:
            r = self._resolve(name)
            if r:
                deps.add(r)
        self.strings[rel] = set(raw['paths'])
        for s in raw['paths']:
            m = re.search(r'((?:echo_sync|tools|tests)/[\w/]+\.py)', s)
            if m and m.group(1) in self.files:
                deps.add(m.group(1))
        for init in self._pkg_inits(rel):
            deps.add(init)
        deps.discard(rel)
        self.ntests[rel] = raw['nt']
        self.defs[rel] = raw['defs']

    def is_test(self, rel: str):
        b = rel.rsplit('/', 1)[-1]
        return rel.startswith('tests/') and b.startswith('test_') and b.endswith('.py')

    def cost(self, rel: str):
        return self.text[rel].count('\n') + 1 + 40 * self.ntests.get(rel, 0)


def affected(changed, radius=None, g: Graph | None = None, hub=0.15):
    """-> (sorted tests, {test: depth}, notes)"""
    g = g or Graph()
    changed = [c.replace('\\', '/') for c in changed]
    all_tests = sorted(r for r in g.files if g.is_test(r))
    notes = []
    depth = {}
    if any(c in ALL_TESTS_TRIGGERS for c in changed):
        notes.append('conftest/pytest config changed: every test')
        return all_tests, {t: 0 for t in all_tests}, notes
    cap = max(8, int(hub * len(g.files))) if hub else None   # fan-in above cap: a hub, not walked through
    q = deque()
    for c in changed:
        if c in g.files:
            depth[c] = 0
            q.append(c)
        elif not c.endswith('.py'):
            base = c.rsplit('/', 1)[-1]
            hit = [r for r, t in g.text.items() if base in t or c in t]
            if not hit:
                notes.append(f'non-python file {c}: no test or module mentions it')
            for r in hit:
                if r not in depth:
                    depth[r] = 1
                    q.append(r)
        else:
            notes.append(f'{c}: not under echo_sync/tools/tests or deleted; ignored')
    while q:
        cur = q.popleft()
        if radius is not None and depth[cur] >= radius:
            continue
        if cap and depth[cur] > 0 and len(g.rev.get(cur, ())) > cap:
            notes.append(f'hub not walked through: {cur} ({len(g.rev[cur])} importers)')
            continue
        for nxt in g.rev.get(cur, ()):
            if nxt not in depth:
                depth[nxt] = depth[cur] + 1
                q.append(nxt)
    tests = sorted(r for r in depth if g.is_test(r))
    return tests, {t: depth[t] for t in tests}, notes


def affected_symbols(changed, base, radius=None, g: Graph | None = None):
    """Name-level reverse walk: a file is touched only if some definition in it mentions a changed name of a module it imports.
    -> (sorted tests, {test: depth}, notes). Falls back to whole-file taint for files whose symbols cannot be diffed."""
    g = g or Graph()
    changed = [c.replace(chr(92), '/') for c in changed]
    notes = []
    all_tests = sorted(r for r in g.files if g.is_test(r))
    if any(c in ALL_TESTS_TRIGGERS for c in changed):
        notes.append('conftest/pytest config changed: every test')
        return all_tests, {t: 0 for t in all_tests}, notes
    taint = {}    # rel -> set of tainted top-level names
    depth = {}
    q = deque()
    plain = []
    for c in changed:
        if c not in g.files:
            plain.append(c)
            continue
        names = changed_symbols(c, g.root, base)
        if names is None:
            names = set(g.defs.get(c, {}))
            notes.append(f'{c}: whole file treated as changed (new file or loose module-level statements changed)')
        taint[c] = set(names)
        depth[c] = 0
        q.append(c)
    base_tests, base_depth, base_notes = affected(plain, radius, g, None) if plain else ([], {}, [])
    notes += base_notes
    for t, d in base_depth.items():
        depth.setdefault(t, d)
        taint.setdefault(t, set(g.defs.get(t, {})))
    while q:
        cur = q.popleft()
        if radius is not None and depth[cur] >= radius:
            continue
        names = taint[cur]
        if not names:
            continue
        for imp in g.rev.get(cur, ()):
            hit = {d for d, ids in g.defs[imp].items() if ids & names}
            if not hit:
                continue
            new = hit - taint.get(imp, set())
            if imp not in depth:
                depth[imp] = depth[cur] + 1
            if new or imp not in taint:
                taint.setdefault(imp, set()).update(new)
                q.append(imp)
    tests = sorted(r for r in depth if g.is_test(r))
    return tests, {t: depth[t] for t in tests}, notes


def shard(tests, n, g: Graph):
    bins = [[0, []] for _ in range(max(1, n))]
    for t in sorted(tests, key=lambda r: -g.cost(r)):
        b = min(bins, key=lambda x: x[0])
        b[0] += g.cost(t)
        b[1].append(t)
    return [{'cost': c, 'tests': sorted(ts)} for c, ts in bins]


def changed_between(base, head, root=ROOT):
    out = subprocess.run(['git', 'diff', '--name-only', f'{base}...{head}'], cwd=root, capture_output=True,
                         text=True, encoding='utf-8', check=True).stdout
    return [x.strip() for x in out.splitlines() if x.strip()]


def neighbors_map(root: Path, radius: int = 1) -> dict[str, list[str]]:
    """``{file: [tests within ``radius`` import hops of it]}`` for every .py file of the tree (the union of
    ``affected([file], radius)``); a file of ALL_TESTS_TRIGGERS has no entry (a change there means every test). Built ONCE per
    base commit by a background job, so that the workers read this file and never build the import graph themselves."""
    g = Graph(Path(root))
    out: dict[str, list[str]] = {}
    for rel in sorted(g.files):
        if rel in ALL_TESTS_TRIGGERS or not rel.endswith('.py'):
            continue
        found, _, _ = affected([rel], radius=radius, g=g)
        out[rel] = sorted(found)
    return out


def build_neighbors(root: Path, out: Path, *, run=None, timeout: int = 300) -> bool:
    """Build the neighbour map of ``root`` in ONE child process (``python -B -m tools.affected_tests neighbors ROOT TMP``) and
    put it at ``out`` with ``os.replace``. True when the file is there. Never raises. (The child, not this process, holds the
    graph: the loop stays small; ``run`` is factory_process.run_owned unless a test gives its own.)"""
    import os
    try:
        if run is None:
            from . import factory_process as PR
            run = PR.run_owned
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + '.tmp%d' % os.getpid())
        home = Path(__file__).resolve().parents[1]      # the factory's own code, never the product's old tools/affected_tests.py
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join([str(home)] + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
        done = run([sys.executable, '-B', '-m', 'tools.affected_tests', 'neighbors', str(Path(root).resolve()), str(tmp)],
                   cwd=str(home), env=env, timeout=timeout)
        if getattr(done, 'returncode', 1) != 0 or not tmp.is_file():
            tmp.unlink(missing_ok=True)
            return False
        os.replace(tmp, out)
        return True
    except Exception:           # noqa: BLE001  a map that was not built is "no map": the workers use the graph as before
        return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'neighbors':       # before parse_args: its positional list is changed files, not ROOT OUT
        if len(argv) != 3:
            print('usage: python -m tools.affected_tests neighbors ROOT OUT', file=sys.stderr)
            return 2
        Path(argv[2]).write_text(json.dumps(neighbors_map(Path(argv[1]).resolve()), sort_keys=True), encoding='utf-8')
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('files', nargs='*')
    ap.add_argument('--base')
    ap.add_argument('--head', default='HEAD')
    ap.add_argument('--radius', type=int, default=1, help='import hops from the changed files: 1 = direct neighbours (default), 2 = neighbours of neighbours, 0 = unlimited')
    ap.add_argument('--shards', type=int)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--hub', type=float, default=0.15, help='fan-in share (of all files) above which a module is a hub and not walked through; 0 = walk everything')
    ap.add_argument('--files-only', action='store_true', help='with --base: whole-file graph instead of name-level (bigger, safer)')
    ap.add_argument('--root', default=str(ROOT), help='repository to analyse (default: this one)')
    a = ap.parse_args(argv)
    changed = list(a.files)
    if a.base:
        changed += changed_between(a.base, a.head, Path(a.root))
    if not changed:
        ap.error('give changed files or --base')
    radius = a.radius or None
    g = Graph(Path(a.root).resolve())
    if a.base and not a.files and not a.files_only:
        tests, depth, notes = affected_symbols(changed, a.base, radius, g)
    else:
        tests, depth, notes = affected(changed, radius, g, a.hub or None)
    total = sum(1 for r in g.files if g.is_test(r))
    if a.shards:
        out = {'shards': shard(tests, a.shards, g)}
    else:
        out = {'tests': tests}
    out.update(selected=len(tests), total=total, changed=len(changed), notes=notes)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        if a.shards:
            for i, s in enumerate(out['shards']):
                print(f'# shard {i} cost={s["cost"]}: ' + ' '.join(s['tests']))
        else:
            print('\n'.join(tests))
        print(f'# selected {len(tests)} of {total} test files; changed {len(changed)} files', file=sys.stderr)
        for n in notes:
            print('# ' + n, file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
