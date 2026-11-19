"""fac-context-windows: the coder of a large file never saw the code it had to change. Live 19.11 20:18-20:22:
(1) the reject task named Loop._apply_one; 'Loop' matched the whole class (lines 293-2189), which was cut after its
first 6 000 characters and hid every method inside it, so the model answered 'CANNOT: _apply_one'; (2) the code of
the neighbours task is a closure inside a 580-line function, shown only from its top, so the model guessed the
SEARCH text. A definition is shown by its innermost named part; a definition too large to show whole is shown as
windows around the lines that mention the keywords, never as its first characters; a line is never cut."""
from tools import factory_context as C


def _filler(indent, n=700):
    return '\n'.join('%sx%d = %d' % (indent, i, i) for i in range(n))       # well over 6 000 characters


def _big_module():
    return ('class Loop:\n'
            '    def first(self):\n' + _filler('        ') + '\n'
            '        return 1\n'
            '\n'
            '    def _apply_one(self, ans):\n'
            '        if ans.get("accept"):\n'
            '            return "accepted"\n'
            '        return "other"\n'
            '\n'
            '\n'
            'def _pass_inner(task):\n' + _filler('    ') + '\n'
            '    def neighbours():\n'
            '        mine = gate_run(tree, near)\n'
            '        return mine\n'
            '    return neighbours()\n')


def test_a_named_method_is_shown_even_when_its_class_is_named_too():
    view = C._fragments(_big_module(), {'Loop', '_apply_one'}, 20000, frozenset({'Loop', '_apply_one'}), tools=False)
    assert 'if ans.get("accept"):' in view


def test_a_closure_deep_in_a_large_function_is_shown_around_its_keywords():
    view = C._fragments(_big_module(), {'_pass_inner', 'neighbours', 'gate_run'}, 20000,
                        frozenset({'_pass_inner', 'neighbours'}), tools=False)
    assert 'mine = gate_run(tree, near)' in view


def test_the_windows_of_one_large_definition_stay_within_one_fragment():
    """Coordinator's acceptance: the factory's version bounded the windows only by the whole room."""
    body = '\n'.join('    hit%d = gate_run(%d)\n' % (i, i) + '\n'.join('    y%d_%d = 0' % (i, j) for j in range(30))
                     for i in range(40))
    view = C._fragments('def huge():\n' + body + '\n', {'huge', 'gate_run'}, 100000, frozenset(), tools=False)
    assert 'gate_run' in view and len(view) <= C.FRAGMENT_MAX_CHARS + 200


def test_every_shown_code_line_is_a_whole_line_of_the_file():
    source = _big_module()
    view = C._fragments(source, {'Loop', '_apply_one', 'neighbours', 'gate_run'}, 20000, frozenset(), tools=False)
    lines = set(source.splitlines())
    shown = [ln for ln in view.splitlines() if ln.strip() and not ln.lstrip().startswith('#')]
    assert shown and all(ln in lines for ln in shown)
