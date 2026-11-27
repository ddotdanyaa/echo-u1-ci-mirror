"""tools.affected_tests: reverse import graph picks the minimal test set (static, no pytest run)."""
import subprocess
from pathlib import Path

from tools import affected_tests as A


def _repo(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    return tmp_path


FILES = {
    'echo_sync/__init__.py': '',
    'echo_sync/base.py': 'def f():\n    return 1\n\ndef g():\n    return 2\n',
    'echo_sync/mid.py': 'from echo_sync import base\n\ndef use_f():\n    return base.f()\n\ndef other():\n    return 0\n',
    'echo_sync/top.py': 'from echo_sync.mid import use_f\n\ndef run():\n    return use_f()\n',
    'echo_sync/lonely.py': 'X = 1\n',
    'tools/__init__.py': '',
    'tests/conftest.py': '',
    'tests/helpers_x.py': 'import echo_sync.top\n\ndef go():\n    return echo_sync.top.run()\n',
    'tests/test_base.py': 'from echo_sync.base import g\n\ndef test_g():\n    assert g()\n',
    'tests/test_mid.py': 'from echo_sync import mid\n\ndef test_o():\n    assert mid.other() == 0\n',
    'tests/test_top.py': 'import helpers_x\n\ndef test_t():\n    helpers_x.go()\n',
    'tests/test_lonely.py': 'def test_s(monkeypatch):\n    monkeypatch.setattr("echo_sync.lonely.X", 2)\n',
    'tests/test_none.py': 'def test_n():\n    pass\n',
}


def test_transitive_and_radius(tmp_path):
    g = A.Graph(_repo(tmp_path, FILES))
    t, d, _ = A.affected(['echo_sync/base.py'], None, g, None)
    assert t == ['tests/test_base.py', 'tests/test_mid.py', 'tests/test_top.py']
    assert d['tests/test_base.py'] == 1 and d['tests/test_top.py'] == 4
    t1, _, _ = A.affected(['echo_sync/base.py'], 1, g, None)
    assert t1 == ['tests/test_base.py']


def test_string_reference_and_unrelated(tmp_path):
    g = A.Graph(_repo(tmp_path, FILES))
    t, _, _ = A.affected(['echo_sync/lonely.py'], None, g, None)
    assert t == ['tests/test_lonely.py']          # monkeypatch target string, test_none not selected


def test_changed_test_and_conftest(tmp_path):
    g = A.Graph(_repo(tmp_path, FILES))
    assert A.affected(['tests/test_none.py'], None, g)[0] == ['tests/test_none.py']
    assert len(A.affected(['tests/conftest.py'], None, g)[0]) == 5


def test_shards_balanced_and_complete(tmp_path):
    g = A.Graph(_repo(tmp_path, FILES))
    tests = sorted(r for r in g.files if g.is_test(r))
    parts = A.shard(tests, 2, g)
    assert sorted(x for p in parts for x in p['tests']) == tests
    assert all(p['tests'] for p in parts)


def _git(cwd, *a):
    subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)


def test_symbol_level_skips_tests_that_do_not_use_changed_name(tmp_path):
    root = _repo(tmp_path, FILES)
    _git(root, 'init', '-q')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base')
    (root / 'echo_sync/base.py').write_text('def f():\n    return 11\n\ndef g():\n    return 2\n', encoding='utf-8')
    g = A.Graph(root)
    t, _, _ = A.affected_symbols(['echo_sync/base.py'], 'HEAD', None, g)
    # f changed: mid.use_f uses it -> top -> helpers_x -> test_top; test_base uses only g, test_mid only other()
    assert t == ['tests/test_top.py']
    assert A.affected(['echo_sync/base.py'], None, g, None)[0] != t   # file-level is wider
