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


def test_a_reflow_keeps_the_indent_of_every_line_both_start():
    text = 'def f():\n    x = g(a,\n          b)\n    return x\n'
    assert P.collapsed_match(text, 'def f():\n    x = g(a, b)\n    return x') == (0, 3)
    assert P.collapsed_match(text, 'def f():\nx = g(a, b)\n    return x') is None      # 'x = ...' re-indented
    assert P.repair(text, 'def f():\nx = g(a, b)\n    return x', 'z') is None


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


def test_every_light_call_asks_for_no_inline_thought():
    """inline-thought (live 20.11): Gemma 4 ran its <thought> section to the 8192 cap in ~175 s on coder calls."""
    from tools import agent_factory_runner as W
    from tools.agent_factory import read_plan
    task = read_plan([dict(id='T1', title='t', touch_files=['calc.py'], read_files=[], tests=['tests/test_c.py'],
                           privacy_safe=True, estimated_tokens=100)])['T1']
    assert W.LIGHT_REVIEW_RULES.startswith(W.NO_THOUGHT) and W.light_rules(task).startswith(W.NO_THOUGHT)
    assert 'inline-thought' in {row[0] for row in P.PATTERNS}


def test_the_test_critic_checks_the_real_function_and_its_arguments():
    """20.11 02:55: promoted tests no correct fix could make green: one faked the function the behaviour lives in
    (<id>, say), one called a function with arguments of another kind (<id>, reason_of)."""
    from tools import agent_factory_runner as W
    assert 'does not replace (monkeypatch, fake) the function inside which' in W.REVIEW_CHECKS_TEST
    assert 'the kind of arguments its signature and docstring take' in W.REVIEW_CHECKS_TEST


def test_every_pattern_has_an_id_a_kind_and_a_description():
    assert {row[1] for row in P.PATTERNS} <= {'repair', 'note'}
    assert {'view-line', 'reflow', 'elided', 'outline-row'} <= {row[0] for row in P.PATTERNS}


# outline-row (live 20.11 03:13-03:16, <id> and <id>: '<id> def _open_question(...' and the same row without
# its label were the SEARCH of 3 of 10 missed blocks): a row of the view's OUTLINE is no line of the file
GATE = ("class Gate:\n"
        "    def _open_question(self, turn, decision, *, tail=False, whole='',\n"
        "                       utterance=False) -> bool:\n"
        "        \"\"\"Open (a, b).\"\"\"\n"
        "        return tail\n"
        "\n"
        "    def close(self):\n"
        "        return None\n")


def _row(name, source=GATE):
    from tools import factory_context as X
    return next(r for r in X.outline(source).split('\n') if ' %s(' % name in r).strip()


def test_an_outline_row_in_search_and_replace_is_the_real_header_of_its_definition():
    row = _row('_open_question')
    assert row.startswith('L2-5 def _open_question(')                    # the view's own row, label and all
    body = '\n        """Open (a, b)."""\n        return '
    new = P.repair(GATE, row + body + 'tail', row + body + 'not tail')
    assert new == GATE.replace('return tail', 'return not tail')
    unlabeled = row.split(' ', 1)[1]                                       # the model dropped the label itself
    assert P.repair(GATE, '    ' + unlabeled + body + 'tail', '    ' + unlabeled + body + 'tail and 1') == \
        GATE.replace('return tail', 'return tail and 1')


def test_a_changed_signature_written_as_an_outline_row_is_never_put_into_the_file():
    row = _row('_open_question')
    assert P.repair(GATE, row + '\n        """Open (a, b)."""', 'L2-5 def _open_question(self)\n        """x"""') is None
    assert P.repair(GATE, row, row + '\n' + _row('close')) is None        # a row SEARCH has not


def test_a_row_that_replace_does_not_keep_names_the_whole_function_and_is_not_expanded():
    """Live 20.11 probe of the kept answers: SEARCH '<id> def provider(self, event)' with a whole new function as
    REPLACE, SEARCH 'def who_closed(error, closing)' with 'def who_closed(error, closing, marks=None)': expanding only
    the header left the old body behind, 2 of 11 such edits did not compile."""
    row = _row('close')
    whole = '    def close(self):\n        return 0'
    assert P.repair(GATE, row, whole) is None
    assert P.repair(GATE, row.split(' ', 1)[1], 'def close(self, now=None)') is None
    hint = P.hints([('a.py', 'def who_closed(error, closing)', 'def who_closed(error, closing, marks=None)')])
    assert len(hint) == 1 and 'REPLACE FUNCTION who_closed' in hint[0]


def test_a_row_names_one_definition_or_nothing_is_expanded():
    two = GATE + "\n\nclass Other:\n    def close(self):\n        return 1\n"
    row = _row('close', two)                                                # '<id> def close(self)'
    assert P.repair(two, row + '\n        return None', row + '\n        return 0') == two.replace(
        'return None', 'return 0')                                          # the label picks Gate.close
    assert P.repair(two, 'def close(self)\n        return None', 'def close(self)\n        return 0') is None
    assert P.expand_outline_rows('x = (\n', 'L1-2 def f()', 'y') == ('L1-2 def f()', 'y')   # no parse: unchanged


def test_the_hint_names_an_outline_row_and_what_to_do():
    hint = P.hints([('a.py', 'L2-5 def f(a)\n    return a', 'x')])
    assert len(hint) == 1 and 'OUTLINE' in hint[0] and 'REPLACE FUNCTION f' in hint[0]
