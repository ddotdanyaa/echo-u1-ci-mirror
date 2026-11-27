"""X-BASE: proof that a move of code is a pure move.

    python -m tools.move_check snapshot [-o out.json] [file.py ...]    the methods (qualified name -> hash of the normalised code) and the module constants
    python -m tools.move_check diff a.json b.json [--allow Name ...]  added / removed / changed; exit 0 only with none of them (the allowed names are listed apart)
    python -m tools.move_check globals [file.py ...]                  every global name a function reads is defined in its own file (or is a builtin): "missing names: 0"
    python -m tools.move_check outcomes out.txt [-o ids.json]         the pass/fail/xfail id sets of a ``pytest -rA`` output; two of them are compared by ``outcomes-diff a b``
    python -m tools.move_check decisions a_dir b_dir                  two folders of the per-journal 'echo-sync decision' multisets (``tests/test_x_base_decisions.py``)

Normalised: the syntax tree with no line numbers, no comments and no docstrings; a method counts by its class-qualified name, wherever the file is. With no file
the controller (``echo_sync/controlled_media.py`` and ``echo_sync/cm_*.py``) is read. Nothing is imported or run.
"""
import argparse
import ast
import builtins
import hashlib
import json
import re
import symtable
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_NAMES = frozenset(('__file__', '__name__', '__doc__', '__package__', '__spec__', '__loader__', '__builtins__', '__path__'))
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def default_files():
    folder = ROOT / 'echo_sync'
    return [str(folder / 'controlled_media.py')] + [str(path) for path in sorted(folder.glob('cm_*.py'))]


def _strip(node):
    """Drops the docstring of every body, so a doc change is no change."""
    for child in ast.walk(node):
        body = getattr(child, 'body', None)
        if isinstance(child, (*_DEFS, ast.ClassDef, ast.Module)) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], 'value', None), ast.Constant) and isinstance(body[0].value.value, str):
            child.body = body[1:] or [ast.Pass()]
    return node


def _hash(node):
    return hashlib.sha256(ast.dump(node, annotate_fields=True, include_attributes=False).encode('utf-8')).hexdigest()[:16]


def _put(store, key, value):
    """A name defined twice keeps both (the second as ``name#2``): a duplicate method is never hidden."""
    at, mark = 1, key
    while mark in store:
        at += 1
        mark = f'{key}#{at}'
    store[mark] = value


def _collect(body, prefix, methods, consts):
    for node in body:
        if isinstance(node, _DEFS):
            _put(methods, prefix + node.name, _hash(node))
        elif isinstance(node, ast.ClassDef):
            _collect(node.body, prefix + ('ControlledMedia' if node.name.endswith('Mixin') else node.name) + '.', methods, consts)      # the family mixins of the controller count as the class they were cut from
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        _put(consts, 'const:' + prefix + name.id, _hash(node))
        elif isinstance(node, (ast.If, ast.Try, ast.With)):
            for part in ('body', 'orelse', 'finalbody'):
                _collect(getattr(node, part, []) or [], prefix, methods, consts)
            for handler in getattr(node, 'handlers', []):
                _collect(handler.body, prefix, methods, consts)


def snapshot(files=None):
    methods, consts = {}, {}
    for name in files or default_files():
        tree = _strip(ast.parse(Path(name).read_text(encoding='utf-8'), filename=str(name)))
        _collect(tree.body, '', methods, consts)
    return {'methods': methods, 'consts': consts}


def diff(a, b, allow=()):
    allow = set(allow)
    old, new = {**a['methods'], **a['consts']}, {**b['methods'], **b['consts']}
    out = {'added': sorted(set(new) - set(old)), 'removed': sorted(set(old) - set(new)),
           'changed': sorted(key for key in set(old) & set(new) if old[key] != new[key]), 'allowed': []}
    for kind in ('added', 'removed', 'changed'):
        keep = []
        for key in out[kind]:
            bare = key.split('#')[0]
            (out['allowed'] if bare in allow or bare.removeprefix('const:') in allow else keep).append(key)
        out[kind] = keep
    out['allowed'] = sorted(set(out['allowed']))
    return out


def _defined(table):
    names = {s.get_name() for s in table.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}

    def declared(sub):
        for symbol in sub.get_symbols():
            if symbol.is_declared_global() and symbol.is_assigned():
                names.add(symbol.get_name())
        for child in sub.get_children():
            declared(child)
    declared(table)
    return names


def _reads(table, found):
    for symbol in table.get_symbols():
        if symbol.is_global() and symbol.is_referenced():
            found.add(symbol.get_name())
    for child in table.get_children():
        _reads(child, found)


def missing_globals(files=None):
    """``{qualified function: [names it reads that its file does not define]}``; the builtins and the module attributes are known."""
    known, out = set(dir(builtins)) | MODULE_NAMES, {}
    for name in files or default_files():
        top = symtable.symtable(Path(name).read_text(encoding='utf-8'), str(name), 'exec')
        have = _defined(top) | known

        def walk(table, prefix):
            for child in table.get_children():
                if child.get_type() == 'class':
                    walk(child, prefix + child.get_name() + '.')
                elif child.get_type() == 'function':
                    found = set()
                    _reads(child, found)
                    lost = sorted(found - have)
                    if lost:
                        out[prefix + child.get_name()] = lost
        walk(top, '')
    return out


def decisions_diff(a_dir, b_dir):
    """Per journal, the lines that differ between two multisets: ``{journal: {'only_a': n, 'only_b': n}}``; a journal missing on a side is named."""
    bad = {}
    a_dir, b_dir = Path(a_dir), Path(b_dir)
    for name in sorted({p.name for p in a_dir.glob('*.json')} | {p.name for p in b_dir.glob('*.json')}):
        if not (a_dir / name).exists() or not (b_dir / name).exists():
            bad[name] = {'missing': 'a' if not (a_dir / name).exists() else 'b'}
            continue
        one, two = (Counter(json.loads((folder / name).read_text(encoding='utf-8'))['lines']) for folder in (a_dir, b_dir))
        if one != two:
            bad[name] = {'only_a': sum((one - two).values()), 'only_b': sum((two - one).values())}
    return bad


_OUTCOME = re.compile(r'^(PASSED|FAILED|ERROR|XFAIL|XPASS)\s+(\S+)', re.M)


def outcomes(text):
    """``{outcome: sorted node ids}`` from the short summary of ``pytest -rA``; the skipped are counted, not named (their lines carry no id)."""
    out = {name: set() for name in ('PASSED', 'FAILED', 'ERROR', 'XFAIL', 'XPASS')}
    for name, node in _OUTCOME.findall(text):
        out[name].add(node)
    got = {name: sorted(ids) for name, ids in out.items()}
    got['SKIPPED'] = len(re.findall(r'^SKIPPED\b', text, re.M))
    return got


def outcomes_diff(a, b):
    """``{id: (before, after)}`` for each test id whose outcome differs (``None``: absent)."""
    def flat(got):
        return {node: name for name, ids in got.items() if isinstance(ids, list) for node in ids}
    one, two = flat(a), flat(b)
    bad = {node: (one.get(node), two.get(node)) for node in set(one) | set(two) if one.get(node) != two.get(node)}
    if a.get('SKIPPED') != b.get('SKIPPED'):
        bad['<skipped count>'] = (a.get('SKIPPED'), b.get('SKIPPED'))
    return dict(sorted(bad.items()))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='move_check')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('snapshot')
    p.add_argument('-o', '--out')
    p.add_argument('files', nargs='*')
    p = sub.add_parser('diff')
    p.add_argument('a')
    p.add_argument('b')
    p.add_argument('--allow', nargs='*', default=[])
    p = sub.add_parser('globals')
    p.add_argument('files', nargs='*')
    p = sub.add_parser('outcomes')
    p.add_argument('text')
    p.add_argument('-o', '--out')
    p = sub.add_parser('outcomes-diff')
    p.add_argument('a')
    p.add_argument('b')
    p = sub.add_parser('decisions')
    p.add_argument('a')
    p.add_argument('b')
    args = parser.parse_args(argv)
    if args.cmd == 'snapshot':
        got = snapshot(args.files or None)
        if args.out:
            Path(args.out).write_text(json.dumps(got, ensure_ascii=False, indent=0, sort_keys=True), encoding='utf-8')
        print(f"snapshot: {len(got['methods'])} methods, {len(got['consts'])} constants" + (f' -> {args.out}' if args.out else ''))
        return 0
    if args.cmd == 'diff':
        got = diff(*(json.loads(Path(p).read_text(encoding='utf-8')) for p in (args.a, args.b)), allow=args.allow)
        bad = got['added'] + got['removed'] + got['changed']
        print(f"diff: {len(bad)} changes (added {len(got['added'])}, removed {len(got['removed'])}, changed {len(got['changed'])}), allowed {len(got['allowed'])}")
        for kind in ('added', 'removed', 'changed'):
            for key in got[kind]:
                print(f'  {kind}: {key}')
        return 1 if bad else 0
    if args.cmd == 'globals':
        got = missing_globals(args.files or None)
        print(f'missing names: {sum(len(v) for v in got.values())}')
        for key, names in sorted(got.items()):
            print(f"  {key}: {', '.join(names)}")
        return 1 if got else 0
    if args.cmd == 'outcomes':
        got = outcomes(Path(args.text).read_text(encoding='utf-8', errors='replace'))
        if args.out:
            Path(args.out).write_text(json.dumps(got, ensure_ascii=False, indent=0), encoding='utf-8')
        print(', '.join(f'{name} {len(ids) if isinstance(ids, list) else ids}' for name, ids in got.items()))
        return 0
    if args.cmd == 'outcomes-diff':
        got = outcomes_diff(*(json.loads(Path(p).read_text(encoding='utf-8')) for p in (args.a, args.b)))
        print(f'outcomes: {len(got)} tests differ')
        for node, (before, after) in got.items():
            print(f'  {node}: {before} -> {after}')
        return 1 if got else 0
    got = decisions_diff(args.a, args.b)
    print(f'decision lines: {len(got)} journals differ')
    for key, value in got.items():
        print(f'  {key}: {value}')
    return 1 if got else 0


if __name__ == '__main__':
    sys.exit(main())
