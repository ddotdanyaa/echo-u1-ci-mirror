# factory-backlog-id: U94.5.s1
import ast
import pathlib

from echo_sync import timer_policy as tp

ECHO = pathlib.Path(tp.__file__).parent


def _targets(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        for el in node.elts:
            yield from _targets(el)
    elif isinstance(node, ast.Starred):
        yield from _targets(node.value)
    else:
        yield node


class _Scan(ast.NodeVisitor):
    def __init__(self, name):
        self.name = name
        self.stack = []
        self.found = []

    def _scoped(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_ClassDef = _scoped
    visit_FunctionDef = _scoped
    visit_AsyncFunctionDef = _scoped

    def _hit(self, node):
        if self.stack[-2:] != ['TimersMixin', '_arm']:
            self.found.append((self.name, node.lineno, '.'.join(self.stack)))

    def _assign(self, node, targets):
        for t in targets:
            for leaf in _targets(t):
                if isinstance(leaf, ast.Attribute) and leaf.attr == 'repeat_at':
                    self._hit(node)
        self.generic_visit(node)

    def visit_Assign(self, node):
        self._assign(node, node.targets)

    def visit_AugAssign(self, node):
        self._assign(node, [node.target])

    def visit_AnnAssign(self, node):
        self._assign(node, [node.target])

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Name) and f.id == 'setattr' and len(node.args) >= 2:
            a = node.args[1]
            if isinstance(a, ast.Constant) and a.value == 'repeat_at':
                self._hit(node)
        self.generic_visit(node)


def test_repeat_at_is_written_only_by_arm():
    found = []
    for path in sorted(ECHO.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        scan = _Scan(path.name)
        scan.visit(tree)
        found.extend(scan.found)
    assert found == []
