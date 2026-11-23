"""fac-light-indent (live 19.11 21:05): 11 of 32 coder answers in the live loop failed with 'SEARCH not found
exactly once'. Models often copy a block with its indentation shifted as a whole; aider's editblock coder handles
the same failure (replace_part_with_missing_leading_whitespace). After the exact and the trailing-space matches
find nothing, a SEARCH whose lines all equal one place of the file but for one and the same leading prefix
matches there, if that place is the only one; the REPLACE lines get that prefix."""
from tools import agent_factory_runner as W


def test_a_dedented_search_matches_and_the_replace_gets_the_file_indent():
    text = 'class A:' '\n    def f(self):\n        return 1\n\nX = 2\n'
    assert (W._replace_once(text, 'def f(self):\n    return 1', 'def f(self):\n    return 3')
            == 'class A:' '\n    def f(self):\n        return 3\n\nX = 2\n')


def test_an_over_indented_search_matches_too():
    assert (W._replace_once('def f():\n    return 1\n', '    def f():\n        return 1',
                            '    def f():\n        return 2') == 'def f():\n    return 2\n')


def test_blank_lines_inside_the_block_stay_blank():
    text = 'if x:' '\n    a = 1\n\n    b = 2\n'
    assert W._replace_once(text, 'a = 1\n\nb = 2', 'a = 1\n\nb = 3') == 'if x:' '\n    a = 1\n\n    b = 3\n'


def test_an_uneven_shift_is_no_match():
    assert W._replace_once('def f():\n    x = 1\n    return x\n', 'def f():\nx = 1\n    return x', 'z') is None


def test_the_shifted_place_must_be_the_only_one():
    text = 'class A:' '\n    def f(self):\n        return 1\nclass B:' '\n    def f(self):\n        return 1\n'
    assert W._replace_once(text, 'def f(self):\n    return 1', 'x') is None


def test_a_shift_is_only_spaces_never_the_tail_of_a_longer_line():
    """Coordinator's acceptance: the factory's first version took any prefix, so 'return x' matched the tail of
    'foo_return x' and the edit went into another line."""
    assert W._replace_once('    foo_return x\n', 'return x', 'return y') is None
    assert W._replace_once('def f():\n    y = g(x)\n', 'g(x)', 'h(x)') is None


def test_an_exact_match_is_used_before_any_shift():
    text = 'def g():\n    return 1\nclass A:' '\n    def g():\n        return 1\n'
    assert (W._replace_once(text, 'def g():\n    return 1', 'def g():\n    return 2')
            == 'def g():\n    return 2\nclass A:' '\n    def g():\n        return 1\n')
