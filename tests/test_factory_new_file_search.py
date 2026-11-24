"""A new test file: the model repeats the marker line as SEARCH (the file does not exist yet)."""
from tools import agent_factory_runner as W

MARK = '# factory-backlog-id: B1'


def test_marker_search_on_missing_file_creates_it(tmp_path):
    body = MARK + '\nimport pytest\n\n\ndef test_a():\n    assert True\n'
    applied, failed = W.apply_edit_blocks(tmp_path, [('tests/test_new.py', MARK + '\n', body)])
    assert failed == {}
    assert list(applied) == ['tests/test_new.py']
    assert (tmp_path / 'tests' / 'test_new.py').read_text(encoding='utf-8') == body


def test_marker_search_with_other_replace_start_is_refused(tmp_path):
    applied, failed = W.apply_edit_blocks(tmp_path, [('tests/test_new.py', MARK, 'import pytest\n')])
    assert not applied
    assert failed == {'SEARCH not found exactly once': 1}
    assert not (tmp_path / 'tests' / 'test_new.py').exists()


def test_other_search_on_missing_file_is_refused(tmp_path):
    for search in ('def f():\n    pass\n', MARK + '\nimport os\n'):
        applied, failed = W.apply_edit_blocks(tmp_path, [('tests/test_new.py', search, MARK + '\nx = 1\n')])
        assert not applied
        assert failed == {'SEARCH not found exactly once': 1}


def test_code_task_missing_file_is_refused(tmp_path):
    applied, failed = W.apply_edit_blocks(tmp_path, [('pkg/mod.py', 'def f():\n    return 1\n', 'def f():\n    return 2\n')])
    assert not applied
    assert failed == {'SEARCH not found exactly once': 1}
    assert not (tmp_path / 'pkg').exists()


def test_marker_search_on_existing_file_without_marker_is_refused(tmp_path):
    target = tmp_path / 'tests' / 'test_old.py'
    target.parent.mkdir()
    target.write_text('import os\n', encoding='utf-8')
    applied, failed = W.apply_edit_blocks(tmp_path, [('tests/test_old.py', MARK, MARK + '\nimport os\n')])
    assert not applied
    assert failed == {'SEARCH not found exactly once': 1}


def test_empty_search_on_non_empty_file_is_refused(tmp_path):
    target = tmp_path / 'a.py'
    target.write_text('x = 1\n', encoding='utf-8')
    applied, failed = W.apply_edit_blocks(tmp_path, [('a.py', '', MARK + '\n')])
    assert not applied
    assert failed == {'empty SEARCH on a file that is not empty': 1}
