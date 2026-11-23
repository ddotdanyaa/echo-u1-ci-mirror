"""Lock on a whole class of live faults (23.11): a name used inside a function that no scope defines
(``NameError: name 'failing' is not defined``), and a closure variable read before it is bound.

No new dependency: the stdlib ``symtable`` lists, for every function, the names it resolves globally; each must be a
module-level name (assigned, imported, defined, or declared ``global`` somewhere), a builtin, or a module dunder.
pyflakes is used on top when it is installed."""
import ast
import builtins
import symtable
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / 'tools'
FILES = sorted(TOOLS.glob('*.py'))
DUNDERS = {'__file__', '__name__', '__doc__', '__package__', '__spec__', '__loader__', '__builtins__',
           '__path__', '__class__', '__annotations__', '__qualname__', '__module__'}


def _walk(table):
    yield table
    for child in table.get_children():
        yield from _walk(child)


def undefined_globals(source: str, name: str = '<src>') -> list:
    """(scope, name) of every global reference that nothing defines; [] for a file with a star import."""
    tree = ast.parse(source, name)
    if any(isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names) for n in ast.walk(tree)):
        return []
    top = symtable.symtable(source, name, 'exec')
    defined = set(DUNDERS) | set(dir(builtins))
    for table in _walk(top):
        for sym in table.get_symbols():
            if table is top and (sym.is_assigned() or sym.is_imported() or sym.is_namespace()):
                defined.add(sym.get_name())
            elif sym.is_declared_global() and sym.is_assigned():
                defined.add(sym.get_name())          # ``global x`` + assignment inside a function defines it
    found = []
    for table in _walk(top):
        if table is top:
            continue
        for sym in table.get_symbols():
            if (sym.is_referenced() and sym.is_global() and not sym.is_local() and not sym.is_parameter()
                    and not sym.is_assigned() and sym.get_name() not in defined):
                found.append((table.get_name(), sym.get_name()))
    return found


def test_the_scanner_sees_a_missing_name():
    assert undefined_globals('def f():\n    return failing\n') == [('f', 'failing')]
    assert undefined_globals('def f():\n    failing = 1\n    return failing\n') == []
    assert undefined_globals('import os\ndef f():\n    return os.sep + len("")\n') == []
    assert undefined_globals('def f():\n    global z\n    z = 1\ndef g():\n    return z\n') == []


def test_the_scanner_sees_nothing_in_a_comprehension_or_a_closure():
    src = ('def f(rows):\n    base = None\n    def g():\n        return base\n'
           '    return [r for r in rows if g() or r]\n')
    assert undefined_globals(src) == []


@pytest.mark.parametrize('path', FILES, ids=lambda p: p.name)
def test_no_undefined_name_in_tools(path):
    source = path.read_text(encoding='utf-8-sig')
    assert undefined_globals(source, path.name) == []


@pytest.mark.parametrize('path', FILES, ids=lambda p: p.name)
def test_pyflakes_undefined_names_when_available(path):
    pyflakes_api = pytest.importorskip('pyflakes.api')
    import io
    from pyflakes import reporter
    out, err = io.StringIO(), io.StringIO()
    pyflakes_api.check(path.read_text(encoding='utf-8-sig'), path.name, reporter.Reporter(out, err))
    bad = [line for line in out.getvalue().splitlines() if 'undefined name' in line or 'referenced before assignment' in line]
    assert bad == []
