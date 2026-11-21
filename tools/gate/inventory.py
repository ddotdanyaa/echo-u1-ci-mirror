"""N181 (E50): static inventory of skip/xfail in tests, each with its reason. AST only: nothing is imported or run.
Counts are declarations (a class mark counts its test methods, a parametrized test counts once), so they differ from pytest's runtime 632/214."""
import ast
import argparse
import json
import sys
from pathlib import Path


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _const(node):
    return node.value if isinstance(node, ast.Constant) else (ast.unparse(node) if node is not None else None)


def _mark(dec):
    """-> (kind, reason, strict) for a skip/skipif/xfail decorator, else None."""
    call = dec if isinstance(dec, ast.Call) else None
    name = ast.unparse(dec.func if call else dec)
    kind = {'pytest.mark.skip': 'skip', 'pytest.mark.skipif': 'skip', 'pytest.mark.xfail': 'xfail', 'unittest.skip': 'skip', 'unittest.skipIf': 'skip', 'unittest.skipUnless': 'skip', 'unittest.expectedFailure': 'xfail', 'skip': 'skip', 'expectedFailure': 'xfail'}.get(name)
    if not kind:
        return None
    reason = _const(_kw(call, 'reason')) if call else None
    if reason is None and call and name in ('unittest.skip', 'skip') and call.args:
        reason = _const(call.args[0])
    if reason is None and call and name in ('unittest.skipIf', 'unittest.skipUnless') and len(call.args) > 1:
        reason = _const(call.args[1])
    if reason is None and call and name == 'pytest.mark.skipif' and len(call.args) > 1:
        reason = _const(call.args[1])
    strict = _const(_kw(call, 'strict')) is True if call else False
    return kind, str(reason or ''), strict


def _inline(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and ast.unparse(n.func) in ('pytest.skip', 'pytest.xfail', 'self.skipTest', 'pytest.importorskip'):
            kind = 'xfail' if n.func.attr == 'xfail' else 'skip'
            yield kind, str(_const(n.args[0]) if n.args else '') if kind == 'skip' or n.args else ''


def inventory(root):
    rows = []
    for path in sorted(Path(root).rglob('test*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError) as e:
            rows.append({'file': str(path), 'test': '<unparsable>', 'kind': 'error', 'reason': str(e), 'strict': False, 'count': 0})
            continue
        rel = str(path.relative_to(root))
        for node in tree.body:
            nodes = [(node, None)] + ([(m, node) for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))] if isinstance(node, ast.ClassDef) else [])
            for fn, cls in nodes:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                marks = [m for m in map(_mark, fn.decorator_list) if m]
                if isinstance(fn, ast.ClassDef):
                    n = sum(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith('test') for m in fn.body)
                    cm = marks
                elif fn.name.startswith('test'):
                    n, cm = 1, marks
                else:
                    continue
                for kind, reason, strict in cm:
                    rows.append({'file': rel, 'test': fn.name, 'kind': kind, 'reason': reason, 'strict': strict, 'count': n})
                if isinstance(fn, ast.ClassDef) or not fn.name.startswith('test'):
                    continue
                for kind, reason in _inline(fn):
                    rows.append({'file': rel, 'test': fn.name, 'kind': kind, 'reason': reason, 'strict': False, 'count': 1})
        for node in ast.walk(tree):                                          # xfail applied by assignment: f = pytest.mark.xfail(...)(f)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Call):
                m = _mark(node.value.func)
                if m:
                    rows.append({'file': rel, 'test': ast.unparse(node.targets[0]), 'kind': m[0], 'reason': m[1], 'strict': m[2], 'count': 1})
    out = {k: sum(r['count'] for r in rows if r['kind'] == k) for k in ('skip', 'xfail')}
    out['no_reason'] = sum(1 for r in rows if r['kind'] in ('skip', 'xfail') and not r['reason'].strip())
    out['rows'] = rows
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', nargs='?', default=str(Path(__file__).resolve().parents[2] / 'tests'))
    p.add_argument('--rows', action='store_true')
    a = p.parse_args(argv)
    inv = inventory(a.root)
    if not a.rows:
        inv.pop('rows')
    print(json.dumps(inv, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
