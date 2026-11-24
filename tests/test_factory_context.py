"""Big-file views for prompts: outline, ranked fragments, ast line numbers, redaction."""
import ast as _ast

from tools import factory_context as X


def test_fragments_rank_title_names_before_test_names_and_skip_what_does_not_fit():
    src = ('def alpha(x):\n    return x\n\n'
           'def beta(x):\n    """%s"""\n    return x\n\n' % ('b' * 3000) +
           'def gamma(x):\n    return x + 1\n')
    both = {'alpha', 'beta', 'gamma'}
    # only title names {gamma}; the test names alpha and beta. Room fits gamma + one small one, never the big beta
    got = X._fragments(src, both, 400, frozenset({'gamma'}))
    assert 'def gamma' in got and 'def alpha' in got and 'def beta' not in got   # continue, not break
    only = X._fragments(src, both, 60, frozenset({'gamma'}))
    assert 'def gamma' in only and 'def alpha' not in only                        # priority wins the scarce room


def test_keywords_ignore_short_and_generic_words_but_keep_unicode_identifiers():
    words = X.keywords_from('self test assert ab fix_sum привет_мир parse_text')
    assert 'fix_sum' in words and 'parse_text' in words and 'привет_мир' in words
    assert not ({'self', 'test', 'assert', 'ab'} & words)


def test_fragment_and_view_line_numbers_follow_ast_not_splitlines():
    src = 'def one():\n    return "a\x0cb"\n\n\ndef target(x):\n    return x\n'   # \x0c would shift splitlines
    node = [n for n in _ast.parse(src).body if getattr(n, 'name', '') == 'target'][0]
    got = X._fragments(src, {'target'}, 1000)
    assert 'lines %d-%d' % (node.lineno, node.end_lineno) in got and 'def target(x):\n    return x' in got
    assert 'return x' in got and 'one()' not in got
    assert ' %d lines' % len(src.split('\n')) in X.large_view('m.py', src, set(), 2000)


def test_a_big_non_py_file_head_is_redacted():
    text = 'AI' 'zaSyA12345' '67890abcdefg' 'hijklmnopqrstuv123\n' + 'x' * 13000
    view = X.large_view('notes.md', text, set(), 4000)
    assert 'AI' 'zaSyA1234567890' not in view


def test_a_big_read_file_with_a_selector_shows_the_slice_not_the_outline():
    src = 'def keep_me(a):\n    return a\n\n' + '\n'.join('def pad_%d(): return %d' % (i, i) for i in range(1500))
    files = {'big.py': src.encode()}
    out = X.render(files, {'big.py': 'keep_me'}, large={'big.py'}, keywords=set(), budget_chars=20000, small_tokens=10**6)
    assert 'slice keep_me' in out and 'def keep_me' in out and 'OUTLINE' not in out
    out = X.render(files, {'big.py': '1:2'}, large={'big.py'}, keywords=set(), budget_chars=20000, small_tokens=10**6)
    assert 'def keep_me' in out and 'pad_1499' not in out


def test_review_hint_forbids_edits_while_the_coder_hint_names_touch_files():
    assert 'touch_files' in X.READ_HINT
    out = X.large_view('m.py', 'def a():\n    pass\n' * 800, set(), 3000, hint='Do not edit anything')
    assert 'Do not edit anything' in out and 'touch_files' not in out



def test_slice_source_uses_ast_line_numbers_even_with_form_feeds():
    src = 'def one():\n    return "a\x0cb c"\n\n\ndef target(x):\n    return x\n'
    out = X.slice_source('m.py', src, 'target')
    assert out.endswith('def target(x):\n    return x') and 'one' not in out
    big = ('def pad():\n    return "\x0c"\n' * 600 + src).encode()
    shown = X.render({'big.py': big}, {'big.py': 'target'}, large={'big.py'}, keywords=set(),
                     budget_chars=20000, small_tokens=10**6)
    assert shown.rstrip().endswith('def target(x):\n    return x')


def test_lines_follow_ast_for_crlf_and_lone_cr():
    assert X._lines('a\r\nb\rc\nd\x0ce') == ['a', 'b', 'c', 'd\x0ce']


def test_title_names_are_never_filtered_as_service_words():
    src = 'class Task:\n    ident = 1\n\n' + 'def other():\n    return 2\n'
    assert 'Task' in X.keywords_from('Fix Task.id', strict=False)
    assert 'return' in X.keywords_from('return', strict=False) and 'return' not in X.keywords_from('return')
    got = X._fragments(src, X.keywords_from('Fix Task.id', strict=False), 2000, frozenset({'Task'}))
    assert 'class Task' in got


def test_a_method_named_by_the_title_is_not_lost_inside_a_class_named_by_the_test():
    src = ('class Box:\n    def put(self, x):\n        return x\n\n    def take(self):\n        return 1\n\n'
           'def free():\n    return 3\n')
    got = X._fragments(src, {'Box', 'take', 'free'}, 2000, frozenset({'take'}))
    assert 'def take(self)' in got and 'def free' in got
    assert 'def put' not in got        # the class was not pulled in on top of the method it overlaps


def test_a_secret_cut_by_the_head_limit_is_redacted_before_cutting():
    secret = 'AI' 'zaSyA12345' '67890abcdefg' 'hijklmnopqrstuv123'
    text = 'x' * (3000 - 20) + secret + '\n' + 'y' * 13000   # the secret straddles the 3000-char border
    view = X.large_view('notes.md', text, set(), 6000)
    assert 'AI' 'zaSyA1234567' not in view and 'AI' 'za' not in view



def test_slice_source_with_lone_cr_separators_ends_with_the_target_body():
    src = 'def one():\r    return 1\r\r\rdef target(x):\r    return x\r'
    out = X.slice_source('m.py', src, 'target')
    assert out.endswith('def target(x):\n    return x') or out.endswith('def target(x):\r    return x')
    assert 'one' not in out


def test_fragment_taken_only_when_actually_picked():
    src = ('class Big:\n' + ''.join('    def m%d(self):\n        return %d\n' % (i, i) for i in range(300)) +
           '\ndef later():\n    return 9\n')
    # Big does not fit the room, so it must not shadow its small method m1 that the test names
    got = X._fragments(src, {'Big', 'm1'}, 200, frozenset({'Big'}))
    assert 'def m1(self)' in got and 'class Big' not in got


def test_only_identifier_like_tokens_of_a_feedback_become_priority():
    got = X.identifier_tokens('Fix the broken thing in parse_text and TextUtil.normalize because renderBox fails')
    assert {'parse_text', 'TextUtil', 'normalize', 'renderBox'} <= got
    assert not ({'broken', 'thing', 'because', 'fails', 'Fix'} & got)


def test_python_fragments_are_deliberately_not_redacted():
    """Code is shown as it is (redaction could corrupt it); the boundary is: secrets live in dotenv files and
    forbidden paths, which never reach the work copy, and non-.py text IS redacted (see the head test)."""
    secret = 'AI' 'zaSyA12345' '67890abcdefg' 'hijklmnopqrstuv123'
    src = 'def target():\n    return "%s"\n' % secret + '\n'.join('def pad_%d(): return %d' % (i, i) for i in range(900))
    assert secret in X._fragments(src, {'target'}, 2000)



def test_scrub_paths_hides_the_user_name_and_the_copy_prefixes():
    diag = (r'failure C:' r'\Us' r'ers\X\AppData\Local\Temp\factory-base-1\tree\echo_sync\a.py:12: boom '
            r'and C:' r'\Us' r'ers\X\AppData\Roaming\other\b.py')
    out = X.scrub_paths(diag, [Path(r'C:' r'\Us' r'ers\X\AppData\Local\Temp\factory-base-1\tree')])
    assert '<repo>/echo_sync/a.py:12' in out
    assert 'Users' not in out and '\\X\\' not in out and 'factory-base' not in out
    # the generic fallback works without any known root, and forward-slash forms too
    out = X.scrub_paths('at C:' '/Us' 'ers/Y/AppData/Local/Temp/factory-gate-tree-9/tree/x/y.py and /home/z/proj/q.py')
    assert '<repo>/x/y.py' in out and 'Y' not in out.replace('<repo>', '') and '/home/z' not in out


def test_scrub_paths_replaces_the_home_directory():
    home = str(Path.home())
    out = X.scrub_paths('error in ' + home + os.sep + 'work' + os.sep + 'f.py')
    assert home not in out and out.startswith('error in ~/')


import os
from pathlib import Path
import pytest



@pytest.mark.parametrize('raw,gone', [
    (r'at C:' r'\Us' r'ers\ABCD' r'~1\AppData\Local\Temp\x.py', 'ABCD'),
    (r'at C:' r'\Us' r'ers\Zq9name\proj\q.py', 'Zq9name'),
    ('at /c/Us' 'ers/Bob/proj/f.py', 'Bob'),
    ('at /mnt/c/Us' 'ers/Bob/proj/f.py', 'Bob'),
    (r'at C:' r'\Us' r'ers\John Smith\AppData\f.py', 'Smith'),
    (r'at C:' r'\Us' r'ers\John Smith\AppData\f.py', 'John'),
])
def test_user_profile_forms_leave_no_name_or_tail(raw, gone):
    out = X.scrub_paths(raw)
    assert gone not in out and out.startswith('at ~'), out


def test_a_root_does_not_eat_a_sibling_with_a_longer_name():
    out = X.scrub_paths('/tmp/staging2/x /tmp/staging/y', ['/tmp/staging'])
    assert out == '/tmp/staging2/x <repo>/y'


def test_file_extensions_are_not_identifiers():
    got = X.identifier_tokens('see notes.md data.json config.yaml mod.py then KindMixin._cue_over_before')
    assert {'KindMixin', '_cue_over_before'} <= got
    assert not ({'md', 'json', 'yaml', 'py', 'notes', 'data', 'config', 'mod'} & got)

import pytest


def test_user_paths_are_matched_case_insensitively():
    out = X.scrub_paths(r'at c:' r'\us' r'ers\bob\proj\a.py and C:' r'\US' r'ERS\Bob\x')
    assert 'bob' not in out.lower().replace('<repo>', '') and out.startswith('at ~')


def test_a_root_followed_by_sentence_punctuation_is_still_replaced():
    root = Path(r'C:' r'\Us' r'ers\Bob\proj')
    for tail in ('.', '!', '?', ',', ''):
        out = X.scrub_paths('see C:' '\\Us' 'ers\\Bob\\proj' + tail, [root])
        assert 'Bob' not in out and out.startswith('see <repo>/'), out
    assert X.scrub_paths(r'see C:' r'\Us' r'ers\Bob\projects\x', [root]).count('Bob') == 0   # the longer name is not the root


def test_prose_after_a_profile_name_is_not_eaten():
    assert X.scrub_paths('open C:' '\\Us' 'ers\\Bob and then /tmp/x fails') == 'open ~ and then /tmp/x fails'
    out = X.scrub_paths(r'at C:' r'\Us' r'ers\John Smith\AppData\f.py')
    assert 'Smith' not in out and 'John' not in out


def test_identifier_tokens_skip_file_names_with_underscores_but_keep_code_chains():
    got = X.identifier_tokens('edit agent_factory_runner.py and factory_gate.py in tests/test_calc.py; '
                              'then fix parse_text')
    assert got == {'parse_text'}
    got = X.identifier_tokens('Task.log is wrong and self.logger.log too')
    assert {'Task', 'self', 'logger'} <= got and 'log' not in got
    assert not (X.identifier_tokens('see notes.log and README.txt') & {'notes', 'log', 'README', 'txt'})



def test_posix_user_routes_keep_their_case_while_windows_forms_do_not():
    assert X.scrub_paths('GET /us' 'ers/42 failed in test') == 'GET /us' 'ers/42 failed in test'
    assert 'bob' not in X.scrub_paths(r'at c:' r'\us' r'ers\bob\x').lower().replace('<repo>', '')
    out = X.scrub_paths(r'at C:' r'\Us' r'ers\A B C\AppData\f.py')               # up to three words before a separator
    assert out == 'at ~\\AppData\\f.py'
    assert X.scrub_paths(r'at C:' r'\Us' r'ers\A B C D\AppData\f.py').startswith('at ~ ')    # four words: only the first is a name


def test_identifier_tokens_distinguish_calls_from_file_names():
    assert {'obj', 'log'} <= X.identifier_tokens('see obj.log(msg) in it')
    assert not (X.identifier_tokens('update Changelog.md and Notes.md and Data.json') & {'Changelog', 'Notes', 'Data', 'md', 'json'})
    assert not (X.identifier_tokens('edit app.config.json first') & {'app', 'config', 'json'})
    assert {'self', 'logger'} <= X.identifier_tokens('self.logger.log is wrong')
