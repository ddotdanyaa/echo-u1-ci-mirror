"""U22 P0: the MECHANICAL cut of ``echo_sync/controlled_media.py`` into family mixins (``cm_kind``, ``cm_question``, ... ) and ``cm_base``.

    python -m tools.split_controlled_media            apply the table ``tools/split_controlled_media_table.json`` to the tree (writes the files)
    python -m tools.split_controlled_media --check    write nothing; exit 1 when the files would change (so 0 on an already split tree: idempotent)
    python -m tools.split_controlled_media --propose  add the methods the table does not know to the table (by the owner census sites); then apply as above

What it does, by the syntax tree, with no change of any method text:
  * ``cm_base.py`` holds the module level of the old file (imports, constants, helpers) verbatim; ``controlled_media`` re-exports every name of it, explicitly.
  * a method the table gives to a family goes, text byte for byte (decorators, comments above it, comments inside), to that family's mixin class; the mixin
    imports from ``cm_base`` the module names it reads and never imports ``controlled_media`` (the cycle).
  * a method STAYS in ``controlled_media.py`` (and is listed) when: the table does not know it, the table says ``stay``, it is a dunder, its text matches a
    ``stay_tokens`` regex (what the tests read in the text of the file), it reads a ``pinned_names`` name, it reads a name no cm_ module can bind (``ControlledMedia``),
    it uses a private ``__name`` (mangling) or ``super``. Class-level non-method members always stay. A property and its setter move together (one name, one place).
  * works on the old single file and on an already split tree: the result is the same (idempotent); a table change moves a method in either direction.
  * self-check before writing: the multiset of member texts of the new files is that of the old files.
"""
import argparse
import ast
import builtins
import json
import re
import symtable
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'echo_sync'
TABLE = ROOT / 'tools' / 'split_controlled_media_table.json'
SITES = ROOT / 'tools' / 'owner_census_sites.jsonl'
CM = 'controlled_media'
BASE = 'cm_base'
CLASS = 'ControlledMedia'
MARK = '# cm-split: assembled by tools/split_controlled_media.py (re-run it, do not edit the generated head by hand)'
BASE_MARK = '# cm-split: the module level of the former controlled_media.py, verbatim; controlled_media re-exports every name of it'
BASE_DOC = '"""The module level of the former ``controlled_media.py``: imports, constants and helpers the family mixins and ``ControlledMedia`` read."""'
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_HEADER = re.compile(r'^class ControlledMedia(\([^)]*\))?:\s*$')


def mixin_name(module):
    return module[3:].capitalize() + 'Mixin'


def load_table(path=TABLE):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class Tree:
    """One state of the controller: the module docstring, the module level, the members of the class (chunks of lines), the tail of the file."""
    pass


def _read(path):
    return Path(path).read_text(encoding='utf-8', newline='').split('\n')


def _chunks(lines, cls):
    """The members of ``cls`` as ``[(name or None, [lines])]``: each node with everything between the previous node and its last line (comments above it)."""
    out, prev = [], cls.lineno
    for node in cls.body:
        out.append((node.name if isinstance(node, _DEFS) else None, lines[prev:node.end_lineno]))
        prev = node.end_lineno
    return out


def _class_of(tree, name):
    found = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
    return found[0] if found else None


def _node_lines(lines, tree, node):
    """The lines of a top-level node with the comments above it (back to the node before)."""
    at = tree.body.index(node)
    return lines[(tree.body[at - 1].end_lineno if at else 0):node.end_lineno]


def _module_reads(text):
    found = set()
    _reads(symtable.symtable(text, '<module>', 'exec'), found)
    return found


def _take_heads(base):
    """The module level of the old file split in ``(base lines, head functions)``: a top-level function that reads ``ControlledMedia`` cannot live in cm_base (the cycle)."""
    tree = ast.parse('\n'.join(base))
    keep, head, prev = [], [], 0
    for node in tree.body:
        chunk = base[prev:node.end_lineno]
        prev = node.end_lineno
        if isinstance(node, _DEFS) and CLASS in _module_reads('\n'.join(_strip_blank(chunk))):
            head.append(chunk)
        else:
            assert CLASS not in {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}, 'a module-level statement other than a def reads ControlledMedia'
            keep += chunk
    return keep + base[prev:], head


def load(pkg, table):
    """The state of the tree: ``Tree`` with ``doc`` (lines), ``base`` (lines of the module level), ``members`` [(name, lines, where)], ``tail``."""
    cm_lines = _read(pkg / (CM + '.py'))
    cm_tree = ast.parse('\n'.join(cm_lines))
    cls = _class_of(cm_tree, CLASS)
    t = Tree()
    first = cm_tree.body[0] if cm_tree.body else None
    has_doc = isinstance(first, ast.Expr) and isinstance(getattr(first, 'value', None), ast.Constant) and isinstance(first.value.value, str)
    t.doc = cm_lines[:first.end_lineno] if has_doc else []
    split = MARK in '\n'.join(cm_lines) and (pkg / (BASE + '.py')).is_file()
    t.head = []
    if split:
        base = _read(pkg / (BASE + '.py'))
        t.base = base[base.index(BASE_MARK) + 1:]
        for node in cm_tree.body:
            if isinstance(node, _DEFS):
                t.head.append(_node_lines(cm_lines, cm_tree, node))
    else:
        t.base, t.head = _take_heads(cm_lines[len(t.doc):cls.lineno - 1])
    assert not cls.decorator_list and _HEADER.match(cm_lines[cls.lineno - 1]), 'the class header of ControlledMedia is not the plain one'
    t.members = [(name, lines, CM) for name, lines in _chunks(cm_lines, cls)]
    t.tail = cm_lines[cls.end_lineno:]
    if split:
        for module in table['modules']:
            path = pkg / (module + '.py')
            if not path.is_file():
                continue
            lines = _read(path)
            mixin = _class_of(ast.parse('\n'.join(lines)), mixin_name(module))
            if mixin is not None:
                t.members += [(name, chunk, module) for name, chunk in _chunks(lines, mixin) if chunk != ['    pass']]
    return t


def bound_names(lines):
    """The names the module level binds: imports, assignments, defs, classes, ``global`` assignments (by symtable)."""
    top = symtable.symtable('\n'.join(lines), BASE, 'exec')
    names = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}

    def declared(sub):
        for s in sub.get_symbols():
            if s.is_declared_global() and s.is_assigned():
                names.add(s.get_name())
        for child in sub.get_children():
            declared(child)
    declared(top)
    return names


def _reads(table, found):
    for s in table.get_symbols():
        if s.is_global() and s.is_referenced():
            found.add(s.get_name())
    for child in table.get_children():
        _reads(child, found)


def reads_of(text):
    """The global names a group of methods reads (decorators and defaults included) and the private ``__x`` names it uses."""
    top = symtable.symtable('class _C:\n' + text, '<group>', 'exec')
    found = set()
    _reads(top.get_children()[0], found)
    private = {n.attr for n in ast.walk(ast.parse('class _C:\n' + text)) if isinstance(n, ast.Attribute) and n.attr.startswith('__') and not n.attr.endswith('__')}
    return found, private


def decide(name, lines, bound, table):
    """The module a method goes to, or ``(None, why)`` when it stays."""
    module = table['methods'].get(name)
    if name in table['stay']:
        return None, 'table: ' + table['stay'][name]
    if module is None:
        return None, 'not in the table'
    if name.startswith('__') and name.endswith('__'):
        return None, 'dunder'
    text = '\n'.join(lines)
    for pattern, why in table['stay_tokens'].items():
        if re.search(pattern, text):
            return None, 'token ' + why
    found, private = reads_of(text)
    if private or re.search(r'\bsuper\b|__class__', text):
        return None, 'private name / super'
    pinned = sorted(found & set(table['pinned_names']))
    if pinned:
        return None, 'reads patched name ' + ','.join(pinned)
    lost = sorted(found - bound - set(dir(builtins)) - {'__name__', '__file__'} - {name})
    if lost or {'__name__', '__file__'} & found:
        return None, 'reads a name no cm_ module binds: ' + ','.join(lost or ['__name__'])
    return module, None


def names_wrap(names, head, width=150):
    lines, cur = [], head + '('
    for n in names:
        piece = n + ', '
        if len(cur) + len(piece) > width and cur.strip() and not cur.endswith('('):
            lines.append(cur.rstrip())
            cur = '    '
        cur += piece
    lines.append(cur.rstrip().rstrip(',') + ')')
    return lines


def assemble(t, table):
    """``(files {name: text}, report)`` for the state ``t``."""
    bound = bound_names(t.base)
    group_lines = defaultdict(list)
    for name, lines, _ in t.members:
        if name is not None:
            group_lines[name] += _strip_blank(lines)
    place = {name: decide(name, lines, bound, table) for name, lines in group_lines.items()}
    by_module = defaultdict(list)
    stay_chunks = []
    for name, lines, where in t.members:
        module = place[name][0] if name is not None else None
        if module is None:
            stay_chunks += lines if where == CM else _strip_blank(lines)
        else:
            by_module[module] += _strip_blank(lines)
    files = {}
    exported = sorted(bound - {n for n in bound if n.startswith('__') and n.endswith('__')})
    files[BASE] = '\n'.join([BASE_DOC, BASE_MARK] + t.base) + ('' if t.base and t.base[-1] == '' else '\n')
    head = list(t.doc) + [MARK] + names_wrap(exported, 'from .' + BASE + ' import ')
    head += ['from .%s import %s' % (m, mixin_name(m)) for m in table['modules']]
    for chunk in t.head:
        head += ['', ''] + _strip_blank(chunk)
    head += ['', '', 'class %s(%s):' % (CLASS, ', '.join(mixin_name(m) for m in table['modules']))]
    files[CM] = '\n'.join(head + stay_chunks + t.tail)
    for module in table['modules']:
        lines = by_module.get(module, [])
        used = set()
        for name, chunk, _ in t.members:
            if name is not None and place[name][0] == module:
                used |= reads_of('\n'.join(_strip_blank(chunk)))[0]
        want = sorted(used & bound)
        doc = '"""The %s methods of ``ControlledMedia`` (cut from controlled_media.py by tools/split_controlled_media.py). Imports from cm_base, never from controlled_media."""' % module[3:]
        out = [doc] + (names_wrap(want, 'from .' + BASE + ' import ') if want else []) + ['', '', 'class %s:' % mixin_name(module)] + (lines or ['    pass']) + ['']
        files[module] = '\n'.join(out)
    return files, place


def _strip_blank(lines):
    at = 0
    while at < len(lines) and not lines[at].strip():
        at += 1
    return list(lines[at:])


def member_texts(files, table):
    """The multiset of member texts of a set of files (the self-check: what moved is what was)."""
    bag = Counter()
    cm = files[CM].split('\n')
    cls = _class_of(ast.parse(files[CM]), CLASS)
    for name, lines in _chunks(cm, cls):
        bag['\n'.join(_strip_blank(lines))] += 1
    for module in table['modules']:
        lines = files[module].split('\n')
        for name, chunk in _chunks(lines, _class_of(ast.parse(files[module]), mixin_name(module))):
            if chunk != ['    pass']:
                bag['\n'.join(_strip_blank(chunk))] += 1
    return bag


def propose(table, t):
    """Adds to the table the methods it does not know, by the owner census sites (the family with the most sites)."""
    sites = defaultdict(Counter)
    if SITES.is_file():
        for line in SITES.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row['file'] == 'echo_sync/controlled_media.py' and row['func'].startswith(CLASS + '.'):
                sites[row['func'].split('.', 1)[1]][row['family']] += 1
    added = {}
    for name, _, _ in t.members:
        if name and name not in table['methods'] and name not in table['stay'] and name in sites:
            family = sites[name].most_common(1)[0][0]
            table['methods'][name] = added[name] = table['family_module'][family]
    return added


def write_table(table, path=TABLE):
    ordered = dict(table)
    ordered['methods'] = dict(sorted(table['methods'].items(), key=lambda kv: (table['modules'].index(kv[1]), kv[0])))
    Path(path).write_text(json.dumps(ordered, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def run(argv=None, pkg=PKG, table_path=TABLE):
    parser = argparse.ArgumentParser(prog='split_controlled_media')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--propose', action='store_true')
    args = parser.parse_args(argv)
    table = load_table(table_path)
    t = load(pkg, table)
    if args.propose:
        added = propose(table, t)
        write_table(table, table_path)
        print('proposed %d methods into the table' % len(added))
    files, place = assemble(t, table)
    old = Counter('\n'.join(_strip_blank(lines)) for _, lines, _ in t.members)
    new = member_texts(files, table)
    assert old == new, 'a member text changed or got lost: %s' % list((old - new) + (new - old))[:3]
    moved, stayed = Counter(), defaultdict(list)
    for name, (module, why) in place.items():
        if module:
            moved[module] += 1
        else:
            stayed[why].append(name)
    changed = []
    for name, text in files.items():
        path = pkg / (name + '.py')
        if not path.is_file() or path.read_text(encoding='utf-8', newline='') != text:
            changed.append(name)
            if not args.check:
                path.write_text(text, encoding='utf-8', newline='')
    print('moved: ' + ', '.join('%s %d' % (m, moved[m]) for m in table['modules']) + ' (total %d)' % sum(moved.values()))
    print('stayed in controlled_media.py: %d method names' % sum(len(v) for v in stayed.values()))
    for why in sorted(stayed, key=lambda w: -len(stayed[w])):
        names = sorted(stayed[why])
        print('  %s (%d): %s' % (why, len(names), ', '.join(names) if len(names) <= 40 else ', '.join(names[:40]) + ', ...'))
    print(('would change: ' if args.check else 'wrote: ') + (', '.join(changed) or 'nothing (already in this state)'))
    return 1 if args.check and changed else 0


if __name__ == '__main__':
    sys.exit(run())
