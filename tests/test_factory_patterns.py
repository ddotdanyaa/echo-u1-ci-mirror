"""fac-error-patterns (owner: «сам защищался от целых классов ошибок (ERROR_PATTERNS)»). Live 23:03:
fac_context_imports failed twice in a row on classes, not on the task: the model copied the view's own header
'# _fragments, lines 165-247' into SEARCH, and it joined a signature that the file wraps over two lines. A class of
a weak model's edit mistakes gets a repair that applies only when exactly ONE place of the file matches, or a hint
for the next attempt when no safe repair exists."""
from tools import factory_patterns as P

FILE = ('import ast\n\n\ndef _fragments(source: str, keywords: set, room: int, priority: frozenset = frozenset(),\n'
        '               tools: bool = True) -> str:\n    return source\n\n\ndef large_view(name):\n    return name\n')
JOINED = ('def _fragments(source: str, keywords: set, room: int, priority: frozenset = frozenset(), '
          'tools: bool = True) -> str:')


def test_view_lines_are_dropped_from_search_and_replace():
    search = '# large_view, lines 9-10\ndef large_view(name):'
    replace = '# large_view, lines 9-10\ndef helper():\n    pass\n\n\ndef large_view(name):'
    s, r, dropped = P.strip_view_lines(search, replace)
    assert s == 'def large_view(name):' and r.startswith('def helper():') and dropped == 1


def test_a_window_header_and_the_view_markers_are_view_lines_too():
    s, _, dropped = P.strip_view_lines('# _fragments, lines 165-247 (part)\nOUTLINE\nSELECTED PARTS\nx = 1', 'x = 2')
    assert s == 'x = 1' and dropped == 3


def test_a_real_comment_stays():
    s, r, dropped = P.strip_view_lines('# a real comment\nx = 1', '# a real comment\nx = 2')
    assert dropped == 0 and s == '# a real comment\nx = 1' and r == '# a real comment\nx = 2'


def test_a_joined_signature_matches_the_wrapped_lines_once():
    assert P.collapsed_match(FILE, JOINED) == (3, 4)      # 0-based first and last line of the place


def test_a_collapsed_match_needs_exactly_one_place():
    text = 'x = 1\ny = 2\nx = 1\ny = 2\n'
    assert P.collapsed_match(text, 'x = 1 y = 2') is None
    assert P.collapsed_match(text, 'z = 3') is None
    assert P.collapsed_match(text, '   \n ') is None


def test_repair_drops_the_view_header_then_matches_the_reflowed_lines():
    new = P.repair(FILE, '# _fragments, lines 4-6\n' + JOINED,
                   'def _imports(source):\n    return ""\n\n\n' + JOINED)
    assert new is not None and new.index('def _imports(source):') < new.index('def _fragments(')
    assert 'lines 4-6' not in new and new.count('def _fragments(') == 1 and new.endswith('    return name\n')


def test_repair_matches_whole_lines_once_after_the_view_lines_are_gone():
    new = P.repair(FILE, 'SELECTED PARTS\ndef large_view(name):\n    return name', 'def large_view(name):\n    return name + 1')
    assert new == FILE.replace('    return name\n', '    return name + 1\n')


def test_repair_gives_none_when_nothing_matches_or_the_place_is_not_unique():
    assert P.repair(FILE, 'def missing():', 'pass') is None
    assert P.repair('x = 1\nx = 1\n', '# x, lines 1-1\nx = 1', 'x = 2') is None


def test_hints_name_an_elided_search_and_say_what_to_do():
    hints = P.hints([('a.py', 'x = 1', 'x = 2'), ('a.py', 'X = re.compile(r"a|b|...|z")', 'X = 1')])
    assert len(hints) == 1 and hints[0].startswith('block 2 (a.py)') and "'...'" in hints[0]
    assert P.hints([('a.py', 'y = "…"', 'y = 1')])          # the one-character ellipsis too


def test_every_pattern_has_an_id_a_kind_and_a_description():
    assert {row[1] for row in P.PATTERNS} <= {'repair', 'note'}
    assert {'view-line', 'reflow', 'elided'} <= {row[0] for row in P.PATTERNS}
