"""<id> (owner, rule 5): free models' candidates died as 'SEARCH not found exactly once'. Replay of the stored
answers (stage/answers, 21.11) showed one whitespace class the matchers still missed: a continuation line of an
open bracket aligned one column off ('def __init__(self, ...,' then 'facts=False, ...' under the paren): every
other line is the file's. The lines of a bracket continuation may move on their own; any other line may not, and the
place must still be the only one."""
from tools import agent_factory_runner as W

FILE = ('class Trace:\n'
        '    KEEP = 3\n'
        '\n'
        '    def __init__(self, directory, call_id, *, clock=None, threaded=False,\n'
        '                 facts=False, mic_gap_ms=1500):\n'
        '        self.threaded = threaded\n'
        '        self.facts = bool(facts)\n')


def test_a_continuation_line_one_column_off_still_matches_and_the_replace_keeps_the_file_indent():
    search = ('    def __init__(self, directory, call_id, *, clock=None, threaded=False,\n'
              '                  facts=False, mic_gap_ms=1500):')      # one space too many under the paren
    replace = ('    def environment_ok(self):\n'
               '        return True\n'
               '\n'
               '    def __init__(self, directory, call_id, *, clock=None, threaded=False,\n'
               '                  facts=False, mic_gap_ms=1500):')
    new, how = W._replace_once_how(FILE, search, replace)
    assert new is not None and how == 'squeezed'
    assert new.count('def __init__') == 1 and 'def environment_ok(self):\n        return True\n' in new
    assert new.endswith('        self.facts = bool(facts)\n')


def test_a_body_line_off_by_one_is_still_refused():
    """Only a bracket continuation is free: a statement line with another indent is another place."""
    search = ('    def __init__(self, directory, call_id, *, clock=None, threaded=False,\n'
              '                 facts=False, mic_gap_ms=1500):\n'
              '         self.threaded = threaded')                    # body off by one column
    assert W._replace_once(FILE, search, 'x') is None


def test_the_continuation_match_is_refused_when_the_place_is_not_the_only_one():
    twice = FILE + '\n' + FILE.replace('Trace', 'Other')
    search = ('    def __init__(self, directory, call_id, *, clock=None, threaded=False,\n'
              '                  facts=False, mic_gap_ms=1500):')
    assert W._replace_once(twice, search, 'x') is None


def test_a_continuation_line_with_other_words_is_no_match():
    search = ('    def __init__(self, directory, call_id, *, clock=None, threaded=False,\n'
              '                  facts=True, mic_gap_ms=1500):')
    assert W._replace_once(FILE, search, 'x') is None
