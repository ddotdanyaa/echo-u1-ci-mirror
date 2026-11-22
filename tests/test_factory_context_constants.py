"""fac-context-constants (live 19.11 21:31): the task 'append one sentence to UNIT_TEST_RULES' failed three passes,
the model answered 'CANNOT: UNIT_TEST_RULES'. The prompt used 9 458 of 28 000 characters but never showed the
constant: only defs and classes were fragment candidates. A module-level assignment whose name the task gives is a
candidate like a definition."""
from tools import factory_context as X


def _module():
    funcs = ''.join('def f%d(x):\n    return x + %d\n\n' % (i, i) for i in range(400))
    return ('import re\n\nLIMIT = 5\nRULES = (\n    "first sentence. "\n    "second sentence.")\n\n' + funcs
            + 'TABLE: dict = {\n    "a": 1,\n    "b": 2,\n}\n')


def test_a_module_level_constant_named_by_the_task_is_shown():
    view = X.large_view('m.py', _module(), {'RULES', 'TABLE'}, 6000, frozenset({'RULES', 'TABLE'}), tools=False)
    assert 'RULES = (\n    "first sentence. "\n    "second sentence.")' in view
    assert 'TABLE: dict = {\n    "a": 1,\n    "b": 2,\n}' in view


def test_a_constant_the_task_does_not_name_is_not_shown():
    view = X.large_view('m.py', _module(), {'RULES'}, 6000, frozenset({'RULES'}), tools=False)
    assert 'RULES = (' in view and 'LIMIT = 5' not in view
