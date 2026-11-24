"""W-true2 1: a deterministic check of NEW calls against the project's own definitions (no cloud, no reviewer).
pyright/mypy do not see mixin calls (self._source with no common base class), so a ready checker does not fit: this one
matches by NAME over every definition in echo_sync/ and tools/."""
from __future__ import annotations

import ast
import hashlib
from collections import Counter
from pathlib import Path

_BUILTIN = {n for t in (dict, list, str, set, bytes, tuple, int, Path) for n in dir(t)}   # x.get(...), s.split(...): not ours
_CACHE: dict = {}


def _defs(tree, rel, out, alias):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            pos = [x.arg for x in a.posonlyargs + a.args]
            names = set(pos) | {x.arg for x in a.kwonlyargs}
            out.setdefault(node.name, {}).setdefault(rel, []).append((node.lineno, len(pos), names, a.vararg is not None,
                                                                       a.kwarg is not None, ast.unparse(a)))
        elif isinstance(node, ast.Assign) and (isinstance(node.value, (ast.Name, ast.Attribute, ast.Lambda)) or (
                isinstance(node.value, ast.Call) and _tail(node.value.func) in ('staticmethod', 'classmethod', 'property',
                                                                                'partial', 'wraps'))):
            alias.update(t.id for t in node.targets if isinstance(t, ast.Name))


def _index(root: Path, file: str, new_text: str):
    paths = sorted(p for d in ('echo_sync', 'tools') if (root / d).is_dir() for p in (root / d).rglob('*.py'))
    stats = [(str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths]
    key = hashlib.sha256(repr(stats).encode()).hexdigest()
    if key not in _CACHE:
        _CACHE.clear()
        out, alias = {}, set()
        for p in paths:
            try:
                _defs(ast.parse(p.read_text(encoding='utf-8-sig', errors='replace')), p.relative_to(root).as_posix(), out, alias)
            except (SyntaxError, ValueError, OSError):
                pass
        _CACHE[key] = (out, alias)
    out, alias = _CACHE[key]
    out = {n: {f: v for f, v in d.items() if f != file} for n, d in out.items()}      # the edited file counts as its new text
    alias = set(alias)
    try:
        _defs(ast.parse(new_text), file, out, alias)
    except SyntaxError:
        pass
    return out, alias


def _external_names(tree) -> set:
    """Names bound by imports of modules outside the project (echo_sync/tools, relative imports are the project's)."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split('.')[0] not in ('echo_sync', 'tools'):
                    out.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, ast.ImportFrom) and not n.level and (n.module or '').split('.')[0] not in ('echo_sync', 'tools'):
            out.update(a.asname or a.name for a in n.names)
    return out


def _calls(text: str) -> Counter:
    c: Counter = Counter()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return c
    ext = _external_names(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id in ext:
                continue        # shutil.which(...): the receiver is an imported module that is not the project's
            name = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ''
            pos = -1 if any(isinstance(a, ast.Starred) for a in n.args) else len(n.args)
            if name:
                c[(name, tuple(sorted(k.arg for k in n.keywords if k.arg)), pos)] += 1
    return c


def new_bad_calls(file: str, old_text: str, new_text: str, root=None) -> list[str]:
    """Texts of the refusals for the NEW calls (not in the base) that no definition of the name accepts; [] = fine."""
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    old, new = _calls(old_text), _calls(new_text)
    fresh = [k for k, v in new.items() if v > old.get(k, 0) and k[0] not in _BUILTIN]
    if not fresh:
        return []
    defs, alias = _index(root, file, new_text)
    msgs = []
    for name, kws, npos in fresh:
        found = [(f, d) for f, ds in defs.get(name, {}).items() for d in ds]
        if not found or name in alias:
            continue
        show = '; '.join('%s:%d(%s)' % (f, d[0], d[5]) for f, d in found[:3])
        bad_kw = [k for k in kws if not any(k in d[2] or d[4] for _, d in found)]
        for k in bad_kw:
            msgs.append('call %s(%s=...) : no definition accepts it; defs: %s' % (name, k, show))
        if npos >= 0 and not bad_kw and all(not d[3] and npos > d[1] for _, d in found):
            msgs.append('call %s(%d positional) : no definition accepts that many; defs: %s' % (name, npos, show))
    return msgs


_MOCKERS = {'Mock', 'MagicMock', 'AsyncMock', 'PropertyMock', 'patch', 'create_autospec', 'monkeypatch', 'mocker'}
_MOCK_ATTRS = {'call_args', 'call_args_list', 'called', 'call_count', 'mock_calls', 'return_value', 'side_effect'}


def _tail(n):
    return n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else ''


def _fakeish(expr, fakes) -> bool:
    for s in ast.walk(expr):
        if isinstance(s, ast.Name) and (s.id in fakes or s.id in _MOCKERS):
            return True
        if isinstance(s, ast.Attribute) and (s.attr in _MOCK_ATTRS or s.attr.startswith('assert_called')):
            return True
    return False


def card_test_faults(code: str, root=None) -> list[str]:
    """W-true2 2: refusals for a card's new test text: every assert goes only through fakes (assert_called*/call_args/Mock
    attributes), or it patches a function, checks a kwarg of its call, and no real definition accepts that kwarg."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    fakes = {a.arg for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) for a in f.args.args if a.arg in _MOCKERS}
    patched, kws, real, seen = set(), set(), 0, 0
    for _ in range(2):          # two passes: ast.walk is breadth-first, a name may be assigned deeper than its first use
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and _fakeish(n.value, fakes):
                fakes.update(t.id for t in n.targets if isinstance(t, ast.Name))
            elif isinstance(n, ast.withitem) and n.optional_vars is not None and _fakeish(n.context_expr, fakes):
                fakes.update(s.id for s in ast.walk(n.optional_vars) if isinstance(s, ast.Name))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _tail(n.func) in ('patch', 'object', 'setattr', 'setitem'):
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    patched.add(a.value.rpartition('.')[2])
        if isinstance(n, ast.Call) and _tail(n.func).startswith('assert_called'):
            kws.update(k.arg for k in n.keywords if k.arg)
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str) and \
                _fakeish(n.value, fakes):
            kws.add(n.slice.value)
        if isinstance(n, ast.Assert):
            seen += 1
            real += not _fakeish(n.test, fakes)
    out = []
    if seen and not real:
        out.append('every assert goes only through fakes (assert_called*/call_args/Mock attributes): assert a value that '
                   'comes back from the real product code or its state')
    if patched and kws:
        defs = _index(Path(root) if root else Path(__file__).resolve().parent.parent, '', '')[0]
        known = [p for p in sorted(patched) if defs.get(p)]
        for k in sorted(kws):
            if known and not any(k in d[2] or d[4] for p in known for ds in defs[p].values() for d in ds):
                out.append('the test patches %s and checks kwarg %s, which no real definition accepts: %s' % (
                    '/'.join(known), k, '; '.join('%s:%d(%s)' % (f, ds[0][0], ds[0][5]) for p in known
                                                  for f, ds in defs[p].items())))
    return out
