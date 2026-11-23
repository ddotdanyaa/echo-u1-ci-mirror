"""fac-context-scoring (critic round 1, two medium findings, 19.11 21:33): (1) the window score counted every word of
the title, so 'task', 'not', 'the' on every line of a helper outranked the part the task names; (2) a plain one-word
name ('neighbours', 'summary') never became a window target, so a large definition or closure the task names could
disappear. Windows are scored only by names that are real parts of the code (defined names or identifiers), each
counted once per window, and a named definition's own names are window targets."""
from tools import factory_context as C


def _filler(indent, n=700):
    return '\n'.join('%sx%d = %d' % (indent, i, i) for i in range(n))


def _big_module():
    return ('class Loop:\n'
            '    def first(self):\n' + _filler('        ') + '\n'
            '        return 1\n'
            '\n'
            '\n'
            'def _pass_inner(task):\n' + _filler('    ') + '\n'
            '    def neighbours():\n'
            '        mine = gate_run(tree, near)\n'
            '        return mine\n'
            '    return neighbours()\n')


def test_common_title_words_do_not_outrank_the_named_part():
    def block(tag):
        return '\n'.join('    r%s%d = other_call(task) if not task.done else None' % (tag, i) for i in range(103))
    src = ('def _pass_inner(task):\n' + block('a') + '\n' + _filler('    ', 60) + '\n' + block('b') + '\n'
           + _filler('    ', 60) + '\n'
           '    def neighbours():\n'
           '        return gate_run(tree, near)\n'
           '    return neighbours()\n')
    priority = frozenset(C.keywords_from('neighbours: a task is not seen', strict=False))
    view = C._fragments(src, {'_pass_inner', 'other_call', 'neighbours', 'gate_run', 'task', 'not'}, 20000,
                        priority, tools=False)
    assert 'return gate_run(tree, near)' in view


def test_a_named_plain_closure_is_a_window_target():
    view = C._fragments(_big_module(), {'_pass_inner', 'neighbours'}, 20000,
                        frozenset({'_pass_inner', 'neighbours'}), tools=False)
    assert 'def neighbours():' in view


def test_a_large_definition_named_by_a_plain_word_shows_its_head():
    src = 'def summary(state):\n' + '\n'.join('    v%d = state.get(%d)' % (i, i) for i in range(400)) + '\n'
    view = C._fragments(src, {'summary', 'tmp_path'}, 20000, frozenset({'summary'}), tools=False)
    assert 'def summary(state):' in view
