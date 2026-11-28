"""fac-context-fit-whole (critic round 1, two low findings, 19.11 21:33): (1) a named definition between the free
room and 6 000 characters was dropped whole, only larger ones got windows; (2) a method the test names inside a
class the title names was cut to the class's window and then skipped as overlapping. A definition is shown whole
only when it also fits, else it gets windows; a candidate inside a title-named candidate has that candidate's rank."""
from tools import factory_context as C


def _filler(indent, n=700):
    return '\n'.join('%sx%d = %d' % (indent, i, i) for i in range(n))


def test_a_named_definition_that_does_not_fit_whole_gets_windows():
    src = 'def f_x():\n' + '\n'.join('    v%d = %d' % (i, i) for i in range(400)) + '\n'
    view = C._fragments(src, {'f_x'}, 4000, frozenset({'f_x'}), tools=False)
    assert 'def f_x():' in view


def test_a_method_the_test_names_inside_a_class_the_title_names_is_shown_whole():
    src = ('class Loop:\n    def first(self):\n' + _filler('        ') + '\n        return 1\n\n'
           '    def _close_answer(self, ans):\n'
           + '\n'.join('        a%d = ans.get(%d)' % (i, i) for i in range(30)) + '\n        return aQX29\n')
    view = C._fragments(src, {'Loop', '_close_answer'}, 20000, frozenset({'Loop'}), tools=False)
    assert '        return aQX29' in view
