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


def test_windows_follow_the_named_identifiers_not_common_words():
    """fac-context-priority (live 20:40): plain words of the task title ('the', 'task', 'not', 'note') matched almost
    every line, so the windows of a large definition filled up from its top and the named part at its end was cut."""
    top = '\n'.join('    note%d = "the task is not done"  # the error of the task' % i for i in range(300))
    src = ('def _pass_inner(task):\n' + top + '\n'
           '    def neighbours():\n'
           '        mine = gate_run(tree, near)\n'
           '        return mine\n'
           '    return neighbours()\n')
    words = {'the', 'task', 'not', 'note', 'error', '_pass_inner', 'neighbours', 'gate_run'}
    view = C._fragments(src, words, 20000, frozenset(words), tools=False)
    assert 'mine = gate_run(tree, near)' in view


def test_the_window_with_the_named_part_wins_when_not_all_windows_fit():
    """Coordinator's acceptance: the factory's version computed the scores and then chose the windows in line order,
    so two early windows of an unnamed helper filled the fragment and the named closure at the end was cut."""
    def block(tag):
        return '\n'.join('    r%s%d = other_call(%d)' % (tag, i, i) for i in range(103))
    src = ('def _pass_inner(task):\n' + block('a') + '\n' + _filler('    ', 60) + '\n' + block('b') + '\n'
           + _filler('    ', 60) + '\n'
           '    def neighbours():\n'
           '        return gate_run(tree, near)\n'
           '    return neighbours()\n')
    view = C._fragments(src, {'_pass_inner', 'other_call', 'neighbours', 'gate_run'}, 20000,
                        frozenset({'neighbours'}), tools=False)
    assert 'return gate_run(tree, near)' in view


def test_a_definition_dense_with_hits_still_shows_its_named_part():
    """Coordinator's acceptance: hits on almost every line merged into one window larger than a fragment, and that
    window was dropped whole (live: _apply_one and answer_main of factory_loop were never shown)."""
    body = ['    r%d = other_call(%d)' % (i, i) for i in range(300)]
    body[150] = '    picked = neighbours_marker(150)'
    view = C._fragments('def _pass_inner(task):\n' + '\n'.join(body) + '\n',
                        {'_pass_inner', 'other_call', 'neighbours_marker'}, 20000,
                        frozenset({'neighbours_marker'}), tools=False)
    assert 'picked = neighbours_marker(150)' in view


def test_every_shown_code_line_is_a_whole_line_of_the_file():
    source = _big_module()
    view = C._fragments(source, {'Loop', '_apply_one', 'neighbours', 'gate_run'}, 20000, frozenset(), tools=False)
    lines = set(source.splitlines())
    shown = [ln for ln in view.splitlines() if ln.strip() and not ln.lstrip().startswith('#')]
    assert shown and all(ln in lines for ln in shown)
