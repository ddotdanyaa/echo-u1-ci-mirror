"""The card of a new test: the file is not there yet, signatures and one neighbouring test are shown, a marker
the model forgot is written by the runner (another row's marker is never replaced)."""
from types import SimpleNamespace

from tools import agent_factory_runner as W
from tools import factory_cards as K
from tools import factory_gate as fg

NAME = 'tests/test_new.py'


def _task():
    return SimpleNamespace(kind='unit_test', backlog_id='B7', tests=[NAME], title='t')


def _write(root, text):
    path = root / 'tests' / 'test_new.py'
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(text.encode('utf-8'))
    return path


def test_forgotten_marker_is_written_first(tmp_path):
    path = _write(tmp_path, 'import pytest\n\n\ndef test_a():\n    assert 1\n')
    assert W.ensure_test_marker(_task(), tmp_path, [NAME]) == [NAME]
    assert path.read_text(encoding='utf-8').startswith('# factory-backlog-id: B7\nimport pytest\n')


def test_marker_goes_after_a_shebang_and_keeps_crlf(tmp_path):
    path = _write(tmp_path, '#!/usr/bin/env python\r\nimport os\r\n')
    W.ensure_test_marker(_task(), tmp_path, [NAME])
    assert path.read_bytes().decode('utf-8') == '#!/usr/bin/env python\r\n# factory-backlog-id: B7\r\nimport os\r\n'


def test_right_marker_and_foreign_marker_are_left_alone(tmp_path):
    for text in ('# factory-backlog-id: B7\nx = 1\n', '# factory-backlog-id: B9\nx = 1\n'):
        path = _write(tmp_path, text)
        assert W.ensure_test_marker(_task(), tmp_path, [NAME]) == []
        assert path.read_text(encoding='utf-8') == text


def test_other_kinds_and_other_files_are_not_touched(tmp_path):
    path = _write(tmp_path, 'x = 1\n')
    code = SimpleNamespace(kind='code', backlog_id='B7', tests=[NAME])
    assert W.ensure_test_marker(code, tmp_path, [NAME]) == []
    assert W.ensure_test_marker(_task(), tmp_path, ['pkg/mod.py']) == []
    assert path.read_text(encoding='utf-8') == 'x = 1\n'


SRC = '''class Trace:
    def __init__(self, directory, call_id, *, clock=None):
        self.d = directory

    def decision(self, kind):
        return kind


def helper(a, b=2):
    return a + b
'''


def test_signatures_carry_init_and_named_functions():
    lines = K.signature_lines(SRC, ['Trace.decision', 'helper'], 'pkg/trace.py')
    text = '\n'.join(lines)
    assert 'def __init__(self, directory, call_id, *, clock=None)' in text
    assert 'def decision(self, kind)' in text
    assert 'def helper(a, b=2)' in text


def test_example_is_one_neighbouring_test_within_the_cap(tmp_path):
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_other.py').write_text('def test_x():\n    assert 1\n', encoding='utf-8')
    (tests / 'test_trace.py').write_text(
        'from pkg import Trace\n\n\ndef test_t(tmp_path):\n    t = Trace(tmp_path, 3)\n    assert t.decision(1) == 1\n' + '# pad\n' * 900,
        encoding='utf-8')
    got = K.example_test(tmp_path, ['Trace.decision'], limit=300)
    assert 'Trace(tmp_path, 3)' in got
    assert len(got) < 400
    assert K.example_test(tmp_path, ['Missing.thing']) == ''


def test_card_says_file_is_new_and_shows_signatures_example_and_problems():
    contract = {'test': {'new': {'path': NAME, 'given': 'g', 'when': 'w', 'then': 't', 'red_now_because': 'r'}}}
    card = K.test_prompt(_task(), contract, {}, signatures='pkg/trace.py: def __init__(self, directory)',
                         example='tests/test_trace.py:\ndef test_t(): pass', problems=['pkg/gone.py: ValueError: missing symbol: Gone'])
    assert 'EMPTY SEARCH' in card
    assert 'def __init__(self, directory)' in card
    assert 'def test_t(): pass' in card
    assert 'pkg/gone.py: ValueError: missing symbol: Gone' in card
    assert 'EMPTY SEARCH' in W.UNIT_TEST_RULES


def test_no_file_answer_without_a_block_is_a_cannot():
    for answer in ('Cannot find the file tests/test_x.py', 'The file tests/test_x.py was not provided.'):
        note = W._light_note(0, [], {}, 0, answer)
        assert note.startswith('the model answered CANNOT: ')
    assert 'no SEARCH/REPLACE edit block' in W._light_note(0, [], {}, 0, 'Here is my idea')


def test_collection_failure_diag_carries_exception_line():
    xml = ('<testsuites><testsuite><testcase classname="tests.test_b1" name="test_b1">'
           '<error message="collection failure">tests/test_b1.py:1: in &lt;module&gt;\n'
           'E   ModuleNotFoundError: No module named \'pkg_b1\'\n</error></testcase></testsuite></testsuites>')
    result = fg.parse_junit(xml, ['tests/test_b1.py'], 2, '.')
    assert "ModuleNotFoundError: No module named 'pkg_b1'" in result.diag
    assert result.diag.startswith('error tests.test_b1::test_b1: collection failure')
