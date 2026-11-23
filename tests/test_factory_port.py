"""Port tasks (coordinator's spec, 20.11): a backlog row says its behaviour was built on an old branch ("реализовано на
ветке ... `<sha>`") and its guard test is red on the head of the unified code. tools/factory_port.py gives the factory
what such a task needs, without a model: the commit named in the row, the functions that commit changed, the files of
the current tree that define them now, and the commit's diff as a reference (code only, never tests, never a key)."""
import importlib
import importlib.util
import subprocess

import pytest


def port():
    assert importlib.util.find_spec('tools.factory_port'), 'tools/factory_port.py is the module under test'
    return importlib.import_module('tools.factory_port')

OLD_HOST = (
    'class Host:\n'
    '    def _stop(self, word):\n'
    '        return word == "stop"\n'
    '\n'
    '    def _go(self):\n'
    '        return 1\n'
)
NEW_HOST = (
    'class Host:\n'
    '    def _stop(self, word):\n'
    '        if not self.whole:\n'
    '            return False\n'
    '        return word == "stop"\n'
    '\n'
    '    def _go(self):\n'
    '        return 1\n'
    '\n'
    '    def _wait(self):\n'
    '        return self.ear\n'
)


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / 'repo'
    (r / 'echo_sync').mkdir(parents=True)
    (r / 'tests').mkdir()
    git(r, 'init', '-q')
    git(r, 'config', 'user.email', 'factory@localhost')
    git(r, 'config', 'user.name', 'factory')
    (r / 'echo_sync' / 'host.py').write_text(OLD_HOST, encoding='utf-8')
    (r / 'tests' / 'test_host.py').write_text('def test_a():\n    assert 1\n', encoding='utf-8')
    git(r, 'add', '-A')
    git(r, 'commit', '-q', '-m', 'old layout')
    (r / 'echo_sync' / 'host.py').write_text(NEW_HOST, encoding='utf-8')
    (r / 'tests' / 'test_host.py').write_text('def test_a():\n    assert 2\n\ndef test_wait():\n    assert 3\n',
                                              encoding='utf-8')
    git(r, 'add', '-A')
    git(r, 'commit', '-q', '-m', 'commands only on whole speech')
    return r


@pytest.fixture
def current(tmp_path):
    """The unified tree: the old Host is split into family files; _go is defined twice (ambiguous), _wait is gone."""
    c = tmp_path / 'current'
    (c / 'echo_sync').mkdir(parents=True)
    (c / 'tests').mkdir()
    (c / 'echo_sync' / 'cm_kind.py').write_text('class KindMixin:\n    def _stop(self, word):\n        return False\n',
                                                 encoding='utf-8')
    (c / 'echo_sync' / 'cm_go.py').write_text('class GoMixin:\n    def _go(self):\n        return 1\n', encoding='utf-8')
    (c / 'echo_sync' / 'cm_other.py').write_text('def _go():\n    return 2\n', encoding='utf-8')
    (c / 'tests' / 'test_kind.py').write_text('def _stop():\n    return 0\n', encoding='utf-8')
    return c


@pytest.mark.parametrize('row, sha', [
    ('| X1 | **Команды** | блокер · реализовано на ветке: H6 п.5 `27c11f6`, в `integ-c15000`; не выложено |', '27c11f6'),
    ('| X2 | **Job** | улучшение · реализовано за `prepare_wide`: H7000 п.3 `a7fdc20`, отчёт, флаг выключен |', 'a7fdc20'),
    ('| X3 | **План** | реализовано в ветке `781c924abc`, не в `integ-c15000` |', '781c924abc'),
    ('| X4 | **Без ветки** | открыто · дубль 289c5f89, тест `5a6b7c8` |', None),
    ('| X5 | **Пусто** | реализовано на ветке H9, коммит не назван |', None),
    ('| X6 | **Заглавные** | реализовано на ветке `ABCDEF1` |', None),   # a commit id is lower-case hex
])
def test_the_commit_named_after_the_word_implemented_is_the_port_source(row, sha):
    assert port().port_sha(row) == sha


def test_the_functions_a_commit_changed_are_named_from_the_code_at_that_commit(repo):
    head = git(repo, 'rev-parse', 'HEAD')
    assert port().changed_names(repo, head) == ['_stop', '_wait']           # a test file of the commit never counts
    assert port().changed_names(repo, 'deadbeef') == []                     # an unknown commit: nothing


def test_the_files_that_define_those_names_now_are_the_scope(current):
    # _stop lives in one family file now; _go is defined in two files (ambiguous: counts for none); _wait is gone;
    # a definition under tests/ never counts
    assert port().locate(current, ['_stop', '_go', '_wait']) == ['echo_sync/cm_kind.py']
    assert port().locate(current, ['_wait']) == []
    (current / 'echo_sync' / 'cm_ear.py').write_text('def _wait():\n    return 1\n', encoding='utf-8')
    assert port().locate(current, ['_stop', '_wait'], limit=1) == ['echo_sync/cm_ear.py']   # equal scores: by path


def test_the_reference_is_the_code_diff_only_cut_with_a_mark_and_never_a_key(repo):
    head = git(repo, 'rev-parse', 'HEAD')
    text = port().reference(repo, head)
    assert 'echo_sync/host.py' in text and 'if not self.whole:' in text and 'def _wait' in text
    assert 'test_host.py' not in text and 'test_wait' not in text
    cut = port().reference(repo, head, max_chars=120)
    assert len(cut) < 260 and cut.rstrip().endswith('[the reference is cut here at 120 characters]')
    assert port().reference(repo, 'deadbeef') == ''
    (repo / 'echo_sync' / 'host.py').write_text(NEW_HOST + "KEY = 's" + "k-" + 'a' * 30 + "'\n", encoding='utf-8')
    git(repo, 'commit', '-q', '-am', 'a key by mistake')
    assert port().reference(repo, git(repo, 'rev-parse', 'HEAD')) == ''


def test_without_git_every_answer_is_empty(repo, monkeypatch):
    # the coordinator's review: a missing git is an empty answer like any git error, never an exception in the pass
    head = git(repo, 'rev-parse', 'HEAD')

    def no_git(*args, **kwargs):
        raise FileNotFoundError('git')
    monkeypatch.setattr(port().subprocess, 'run', no_git)
    assert port().changed_names(repo, head) == [] and port().reference(repo, head) == ''
