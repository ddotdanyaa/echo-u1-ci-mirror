"""Function-level edit block of the light engine: ``REPLACE FUNCTION <path> <name>`` + a ```python fence holding the
whole new definition (live 20.11: free models cannot copy SEARCH lines exactly from big files)."""
import json
from dataclasses import replace

import pytest

from tools import agent_factory as F
from tools import agent_factory_runner as W

SRC = '''import os

X = 1


def add(a, b):
    return a - b


@staticmethod
def deco(a):
    return a


class Calc:
    """doc"""

    def run(self, a):
        return a

    @property
    def val(self):
        return 1

    def other(self):
        return 2


class Twin:
    def run(self):
        return 'twin'
'''


def task(touch=('calc.py',)):
    base = F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    return replace(base, touch_files=tuple(touch))


def fn_block(path, name, body):
    return 'REPLACE FUNCTION %s %s\n```python\n%s\n```\n' % (path, name, body)


def setup(tmp_path, text=SRC):
    (tmp_path / 'calc.py').write_text(text, encoding='utf-8', newline='\n')


def reply(content):
    body = dict(choices=[dict(message=dict(content=content), finish_reason='stop')], usage={})
    return lambda url, key, payload, timeout: (200, json.dumps(body).encode())


def run(tmp_path, answer, touch=('calc.py',), shown=None):
    blocks, outside = W.parse_edit_blocks(answer, touch)
    applied, failed = W.apply_edit_blocks(tmp_path, blocks, shown)
    return blocks, outside, applied, failed


def test_replace_a_top_level_function(tmp_path):
    setup(tmp_path)
    _, outside, applied, failed = run(tmp_path, fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b'))
    assert applied == ['calc.py'] and failed == {} and outside == 0
    text = (tmp_path / 'calc.py').read_text()
    assert 'def add(a, b):\n    return a + b\n' in text and 'a - b' not in text
    assert 'X = 1' in text and 'class Calc' in text


def test_a_decorator_the_new_text_omits_is_kept(tmp_path):
    setup(tmp_path)
    run(tmp_path, fn_block('calc.py', 'deco', 'def deco(a):\n    return a * 2'))
    text = (tmp_path / 'calc.py').read_text()
    assert '@staticmethod\ndef deco(a):\n    return a * 2\n' in text
    run(tmp_path, fn_block('calc.py', 'Calc.val', 'def val(self):\n    return 7'))
    ns = {}
    exec(compile((tmp_path / 'calc.py').read_text(), 'calc.py', 'exec'), ns)
    assert ns['Calc']().val == 7          # still a property, not a bound method


def test_a_new_decorator_replaces_the_old_ones(tmp_path):
    setup(tmp_path)
    run(tmp_path, fn_block('calc.py', 'deco', '@staticmethod\n' '@other\ndef deco(a):\n    return a * 3'))
    text = (tmp_path / 'calc.py').read_text()
    assert '@staticmethod\n' '@other\ndef deco(a):\n    return a * 3\n' in text and text.count('@staticmethod') == 1


def test_replace_a_method_of_a_class(tmp_path):
    setup(tmp_path)
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'Calc.run', '    def run(self, a):\n        return a + 1'))
    assert applied == ['calc.py'] and failed == {}
    text = (tmp_path / 'calc.py').read_text()
    assert '    def run(self, a):\n        return a + 1\n' in text
    assert "return 'twin'" in text and 'def other(self)' in text and '@property' in text


def test_a_method_given_at_column_zero_is_reindented(tmp_path):
    setup(tmp_path)
    run(tmp_path, fn_block('calc.py', 'Calc.val', '@property\ndef val(self):\n    x = 5\n\n    return x'))
    text = (tmp_path / 'calc.py').read_text()
    assert '    @property\n    def val(self):\n        x = 5\n\n        return x\n' in text
    compile(text, 'calc.py', 'exec')


def test_a_missing_name_is_not_applied_and_the_note_names_it(tmp_path):
    setup(tmp_path)
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'nope', 'def nope():\n    pass'))
    assert applied == [] and (tmp_path / 'calc.py').read_text() == SRC
    assert len(failed) == 1 and "'nope'" in next(iter(failed))
    note = W._light_note(1, applied, failed, 0, '')
    assert 'nope' in note and 'not found' in note


def test_a_duplicate_name_is_not_applied(tmp_path):
    setup(tmp_path, SRC + '\n\ndef add(a, b):\n    return 0\n')
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b'))
    assert applied == [] and len(failed) == 1 and 'more than once' in next(iter(failed))
    assert (tmp_path / 'calc.py').read_text().count('def add') == 2


@pytest.mark.parametrize('new,why', [
    ('def add(a, b):\nreturn a + b', 'does not parse'),
    ('def add(a, b:' '\n    return 1', 'does not parse'),
    ('def sub(a, b):\n    return a - b', 'same name'),
    ('def add(a, b):\n    return 1\n\ndef extra():\n    pass', 'exactly one'),
    ('X = 3', 'exactly one'),
])
def test_a_bad_new_text_is_not_applied(tmp_path, new, why):
    setup(tmp_path)
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'add', new))
    assert applied == [] and (tmp_path / 'calc.py').read_text() == SRC
    assert len(failed) == 1 and why in next(iter(failed))


def test_a_path_outside_touch_files_is_not_applied(tmp_path):
    setup(tmp_path)
    (tmp_path / 'other.py').write_text('def add():\n    pass\n', newline='\n')
    blocks, outside, applied, failed = run(tmp_path, fn_block('other.py', 'add', 'def add():\n    return 1'))
    assert blocks == [] and outside == 1 and applied == []
    assert (tmp_path / 'other.py').read_text() == 'def add():\n    pass\n'
    assert 'outside the task' in W._light_note(1, applied, failed, outside, '')


def test_an_unterminated_fence_is_not_applied(tmp_path, monkeypatch):
    setup(tmp_path)
    answer = ('REPLACE FUNCTION calc.py add\n```python\ndef add(a, b):\n    return 1\n'
              'calc.py\n<<<<<<< SEARCH\nX = 1\n=======\nX = 2\n>>>>>>> REPLACE\n')
    blocks, outside = W.parse_edit_blocks(answer, ('calc.py',))
    assert blocks == [] and outside == 0
    assert list(blocks.problems) == ['REPLACE FUNCTION block without a closing ``` line']
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    setup(tmp_path)
    rc, _, note = W.light_attempt(task(), tmp_path, 'google/gemini-3.5-flash-lite', prompt_override=SRC,
                                  post=reply(answer))
    assert rc == 0 and (tmp_path / 'calc.py').read_text() == SRC
    assert 'without a closing ``` line' in note.decode() and 'no SEARCH/REPLACE' not in note.decode()


def test_a_mixed_answer_applies_both_in_order(tmp_path):
    setup(tmp_path)
    answer = ('calc.py\n<<<<<<< SEARCH\nX = 1\n=======\nX = 2\n>>>>>>> REPLACE\n'
              + fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b + X'))
    blocks, outside, applied, failed = run(tmp_path, answer)
    assert len(blocks) == 2 and applied == ['calc.py'] and failed == {}
    text = (tmp_path / 'calc.py').read_text()
    assert 'X = 2' in text and 'return a + b + X' in text


def test_a_function_block_first_then_a_search_on_its_new_text(tmp_path):
    setup(tmp_path)
    answer = (fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b')
              + 'calc.py\n<<<<<<< SEARCH\n    return a + b\n=======\n    return b + a\n>>>>>>> REPLACE\n')
    _, _, applied, failed = run(tmp_path, answer)
    assert applied == ['calc.py'] and failed == {} and 'return b + a' in (tmp_path / 'calc.py').read_text()


def test_one_failed_function_block_leaves_the_search_block_unwritten(tmp_path):
    setup(tmp_path)
    answer = ('calc.py\n<<<<<<< SEARCH\nX = 1\n=======\nX = 2\n>>>>>>> REPLACE\n'
              + fn_block('calc.py', 'missing', 'def missing():\n    pass'))
    _, _, applied, failed = run(tmp_path, answer)
    assert applied == [] and failed and (tmp_path / 'calc.py').read_text() == SRC


def test_crlf_file_stays_crlf(tmp_path):
    (tmp_path / 'calc.py').write_bytes(SRC.replace('\n', '\r\n').encode())
    run(tmp_path, fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b'))
    raw = (tmp_path / 'calc.py').read_bytes()
    assert b'return a + b\r\n' in raw and b'\n' not in raw.replace(b'\r\n', b'')


def test_rules_document_the_format_and_stay_small():
    rules = W.light_rules(task())
    assert 'REPLACE FUNCTION' in rules and 'Class.method' in rules
    assert len(W.LIGHT_EDIT_RULES) < 1700


def test_light_attempt_applies_a_function_block_and_the_note_reports_failures(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    setup(tmp_path)

    rc, out, note = W.light_attempt(task(), tmp_path, 'google/gemini-3.5-flash-lite', prompt_override=SRC,
                                    post=reply(fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b')))
    assert rc == 0 and 'return a + b' in (tmp_path / 'calc.py').read_text()
    assert note.decode() == 'edit blocks 1, changed files 1'
    rc, out, note = W.light_attempt(task(), tmp_path, 'google/gemini-3.5-flash-lite', prompt_override=SRC,
                                    post=reply(fn_block('calc.py', 'zzz', 'def zzz():\n    pass')))
    assert 'zzz' in note.decode() and 'changed files 0' in note.decode()


# ---- the critic's findings (20.11, round 2) ---------------------------------------------------------------------
BIG = 'def big(x):\n' + ''.join('    x = x + %d\n' % i for i in range(60)) + '    return x\n'


def test_a_function_that_was_not_shown_whole_is_not_replaced(tmp_path):
    """HIGH: an outline or a '(part)' window hides code; the model must not delete what it never read."""
    setup(tmp_path, 'import os\n\n\n' + BIG + '\n\ndef small():\n    return 1\n')
    elided = 'def big(x):\n    # ... existing code ...\n    return x * 2'
    outline_only = 'FILE calc.py (LARGE)\nOUTLINE\ndef big(x): ...   # lines 4-65\ndef small(): ...\n'
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'big', elided), shown=outline_only)
    assert applied == [] and len(failed) == 1 and 'was not shown whole' in next(iter(failed))
    assert 'CANNOT: big' in next(iter(failed)) and 'SEARCH/REPLACE' in next(iter(failed))
    part = '# big, lines 4-30 (part)\n' + '\n'.join(BIG.split('\n')[:27]) + '\n'
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'big', 'def big(x):\n    return x * 2'), shown=part)
    assert applied == [] and 'was not shown whole' in next(iter(failed))
    assert 'x = x + 59' in (tmp_path / 'calc.py').read_text()


def test_a_function_shown_whole_is_replaced(tmp_path):
    setup(tmp_path, 'import os\n\n\n' + BIG)
    shown = 'FILE calc.py\n' + 'import os\n\n\n' + BIG
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'big', 'def big(x):\n    return x * 2'), shown=shown)
    assert applied == ['calc.py'] and failed == {}
    assert (tmp_path / 'calc.py').read_text() == 'import os\n\n\ndef big(x):\n    return x * 2\n'


@pytest.mark.parametrize('new', [
    'def add(a, b):\n    ...',
    'def add(a, b):\n    pass',
    'def add(a, b):\n    x = 1\n    ...\n    return x',
    'def add(a, b):\n    # ... existing code ...\n    return a + b',
    'def add(a, b):\n    # rest of the function\n    return a + b',
    'def add(a, b):\n    # unchanged\n    return a + b',
    'def add(a, b):\n    # existing code\n    return a + b',
])
def test_an_elided_body_is_not_applied(tmp_path, new):
    setup(tmp_path)
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'add', new))
    assert applied == [] and (tmp_path / 'calc.py').read_text() == SRC
    assert len(failed) == 1 and 'elides code' in next(iter(failed))


def test_a_comment_that_was_already_there_is_not_an_elision(tmp_path):
    setup(tmp_path, 'def add(a, b):\n    # the rest of the line is ignored\n    return a - b\n')
    _, _, applied, failed = run(tmp_path, fn_block(
        'calc.py', 'add', 'def add(a, b):\n    # the rest of the line is ignored\n    return a + b'))
    assert applied == ['calc.py'] and failed == {}


def test_a_stub_may_replace_a_stub(tmp_path):
    setup(tmp_path, 'class P:' '\n    def run(self):\n        ...\n')
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'P.run', '    def run(self):\n        pass'))
    assert applied == ['calc.py'] and failed == {}


SQL = ('class Db:\n    def q(self):\n        return """\nselect 1\n  \nfrom t\n"""\n\n    def z(self):\n        return 1\n')
SQL_VALUE = '\nselect 2\n  \nfrom t\n'


def value_of(tmp_path):
    ns = {}
    text = (tmp_path / 'calc.py').read_text()
    exec(compile(text, 'calc.py', 'exec'), ns)
    return ns['Db']().q(), text


def test_a_method_with_a_column_zero_string_given_verbatim(tmp_path):
    """MEDIUM: textwrap.dedent found no margin and the method did not parse."""
    setup(tmp_path, SQL)
    new = '    def q(self):\n        return """\nselect 2\n  \nfrom t\n"""'
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'Db.q', new))
    assert applied == ['calc.py'] and failed == {}
    value, text = value_of(tmp_path)
    assert value == SQL_VALUE and 'def z(self)' in text


def test_a_method_with_a_column_zero_string_given_at_column_zero(tmp_path):
    setup(tmp_path, SQL)
    new = 'def q(self):\n    return """\nselect 2\n  \nfrom t\n"""'
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'Db.q', new))
    assert applied == ['calc.py'] and failed == {}
    value, text = value_of(tmp_path)
    assert value == SQL_VALUE                       # the whitespace-only line inside the string survives
    assert '    def q(self):\n        return """\nselect 2\n  \nfrom t\n"""\n' in text


def test_a_multi_line_f_string_keeps_its_lines(tmp_path):
    setup(tmp_path, SQL)
    new = 'def q(self):\n    n = 2\n    return f"""\nselect {n}\n  \nfrom t\n"""'
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'Db.q', new))
    assert applied == ['calc.py'] and failed == {} and value_of(tmp_path)[0] == SQL_VALUE


TABS = 'class T:' '\n\tdef a(self):\n\t\treturn 1\n\n\tdef b(self):\n\t\treturn 2\n'


def test_tab_indented_file_gets_the_real_indentation_string(tmp_path):
    setup(tmp_path, TABS)
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'T.a', '\tdef a(self):\n\t\treturn 5'))
    assert applied == ['calc.py'] and failed == {}
    raw = (tmp_path / 'calc.py').read_bytes()
    assert b'class T:' b'\n\tdef a(self):\n\t\treturn 5\n\n\tdef b(self):' in raw
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'T.b', 'def b(self):\n\treturn 6'))
    assert applied == ['calc.py'] and failed == {}
    raw = (tmp_path / 'calc.py').read_bytes()
    assert b'\n\tdef b(self):\n\t\treturn 6\n' in raw and b'    ' not in raw


def test_the_bytes_of_an_lf_file_stay_lf(tmp_path):
    setup(tmp_path)
    answer = fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b').replace('\n', '\r\n')
    _, _, applied, failed = run(tmp_path, answer)
    assert applied == ['calc.py'] and failed == {}
    assert b'\r' not in (tmp_path / 'calc.py').read_bytes()


def test_a_lone_carriage_return_in_the_file_is_a_failure_not_a_wrong_cut(tmp_path):
    (tmp_path / 'calc.py').write_bytes(b'def add(a, b):\r    return a - b\r\r\rdef other():\r    return 1\r')
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b'))
    assert applied == [] and 'carriage return' in next(iter(failed))
    assert (tmp_path / 'calc.py').read_bytes().startswith(b'def add(a, b):\r    return a - b')


def test_a_parse_that_runs_out_of_stack_is_a_failure_not_a_crash(tmp_path, monkeypatch):
    setup(tmp_path)

    def boom(*a, **k):
        raise RecursionError('deep')
    monkeypatch.setattr('ast.parse', boom)
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b'))
    assert applied == [] and 'does not parse' in next(iter(failed))


def test_a_nested_function_with_the_target_name_is_not_the_target(tmp_path):
    text = 'def outer():\n    def add(a):\n        return a\n    return add\n\n\ndef add(a, b):\n    return a - b\n'
    setup(tmp_path, text)
    new = 'def add(a, b):\n    def add(x):\n        return x\n    return add(a) + b'
    _, _, applied, failed = run(tmp_path, fn_block('calc.py', 'add', new))
    assert applied == ['calc.py'] and failed == {}
    out = (tmp_path / 'calc.py').read_text()
    assert out.startswith('def outer():\n    def add(a):\n        return a\n    return add\n\n\n')
    assert out.endswith('def add(a, b):\n    def add(x):\n        return x\n    return add(a) + b\n')


@pytest.mark.parametrize('header', [
    'REPLACE FUNCTION calc.py add',
    'REPLACE FUNCTION calc.py add()',
    '**REPLACE FUNCTION** `calc.py` `add`',
    '`REPLACE FUNCTION calc.py add`',
    '### REPLACE FUNCTION calc.py add:',
    'replace function calc.py add',
])
def test_near_miss_headers_and_a_blank_line_before_the_fence(tmp_path, header):
    for gap in ('', '\n'):
        blocks, outside = W.parse_edit_blocks(header + '\n' + gap + '```python\ndef add(a, b):\n    return 1\n```\n',
                                              ('calc.py',))
        assert blocks == [('calc.py', 'add', 'def add(a, b):\n    return 1')] and not blocks.problems


def test_a_unicode_function_name_is_a_name():
    blocks, _ = W.parse_edit_blocks('REPLACE FUNCTION calc.py Größe.höhe\n```python\ndef höhe(self):\n    return 1\n```',
                                    ('calc.py',))
    assert blocks == [('calc.py', 'Größe.höhe', 'def höhe(self):\n    return 1')]


def test_a_header_that_gives_no_block_is_counted_and_named_with_the_shape(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    setup(tmp_path)
    for answer in ('REPLACE FUNCTION add\n```python\ndef add(a, b):\n    return 1\n```',
                   'REPLACE FUNCTION calc.py add\ndef add(a, b):\n    return 1\n'):
        blocks, _ = W.parse_edit_blocks(answer, ('calc.py',))
        assert blocks == [] and sum(blocks.problems.values()) == 1
        rc, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override=SRC, post=reply(answer))
        text = note.decode()
        assert rc == 0 and text.startswith('edit blocks 1, changed files 0; 1: ')
        assert 'REPLACE FUNCTION <path> <name>' in text and 'no SEARCH/REPLACE' not in text
    assert (tmp_path / 'calc.py').read_text() == SRC


def test_a_bad_function_header_stops_a_good_search_block_too(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    setup(tmp_path)
    answer = 'calc.py\n<<<<<<< SEARCH\nX = 1\n=======\nX = 2\n>>>>>>> REPLACE\nREPLACE FUNCTION add\n'
    rc, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override=SRC, post=reply(answer))
    assert (tmp_path / 'calc.py').read_text() == SRC and 'changed files 0' in note.decode()


def test_the_closing_fence_is_as_long_as_the_opening_one():
    answer = ('REPLACE FUNCTION calc.py add\n````python\ndef add(a, b):\n    s = """\n```\n"""\n'
              '    return a + b\n````\n')
    blocks, _ = W.parse_edit_blocks(answer, ('calc.py',))
    assert len(blocks) == 1 and '```' in blocks[0][2] and blocks[0][2].endswith('return a + b')


def test_a_fenced_body_with_search_markers_is_a_search_block(tmp_path):
    answer = ('REPLACE FUNCTION calc.py add\n```python\n<<<<<<< SEARCH\n    return a - b\n=======\n'
              '    return a + b\n>>>>>>> REPLACE\n```\n')
    setup(tmp_path)
    blocks, outside, applied, failed = run(tmp_path, answer)
    assert blocks == [('calc.py', '    return a - b', '    return a + b')] and outside == 0
    assert applied == ['calc.py'] and 'return a + b' in (tmp_path / 'calc.py').read_text()


def test_a_function_header_sets_the_file_of_a_later_search_block():
    answer = ('REPLACE FUNCTION b.py add\n```python\ndef add():\n    return 1\n```\n'
              '<<<<<<< SEARCH\nX = 1\n=======\nX = 2\n>>>>>>> REPLACE\n')
    blocks, outside = W.parse_edit_blocks(answer, ('a.py', 'b.py'))
    assert [b[0] for b in blocks] == ['b.py', 'b.py'] and outside == 0


def test_the_light_attempt_refuses_a_function_the_prompt_did_not_show(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    setup(tmp_path)
    rc, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p',
                                  post=reply(fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b')))
    assert (tmp_path / 'calc.py').read_text() == SRC and 'was not shown whole' in note.decode()
    assert len(note) <= 300
    crlf_prompt = SRC.replace('\n', '\r\n')       # the prompt may carry CRLF: it is compared as LF
    rc, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override=crlf_prompt,
                                  post=reply(fn_block('calc.py', 'add', 'def add(a, b):\n    return a + b')))
    assert note.decode() == 'edit blocks 1, changed files 1'


def test_the_rules_example_names_a_function_of_the_task(tmp_path):
    setup(tmp_path)
    base = task()
    said = replace(base, title='Fix Calc.other', goal='')
    assert 'REPLACE FUNCTION calc.py Calc.other\n```python\ndef other(' in W.light_rules(said, tmp_path)
    said = replace(base, title='sum is wrong', goal='the add function subtracts')
    assert 'REPLACE FUNCTION calc.py add\n' in W.light_rules(said, tmp_path)
    assert 'REPLACE FUNCTION calc.py add\n' in W.light_rules(replace(base, title='nothing'), tmp_path)
    assert 'REPLACE FUNCTION calc.py Class.method\n' in W.light_rules(base)
    assert 'only for a function shown WHOLE' in W.LIGHT_EDIT_RULES and 'shown whole' in W.LIGHT_HINT
    assert len(W.LIGHT_EDIT_RULES) < 1700


def test_the_retry_notes_mention_both_formats():
    assert 'REPLACE FUNCTION' in W.TOURNAMENT_NOTE and 'SEARCH' in W.TOURNAMENT_NOTE
    assert 'SEARCH/REPLACE' in W._light_note(0, [], {}, 0, 'x') and 'REPLACE FUNCTION' in W._light_note(0, [], {}, 0, 'x')
