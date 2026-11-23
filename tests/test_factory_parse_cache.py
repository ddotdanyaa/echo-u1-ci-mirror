"""Laptop load (owner: take the load off the laptop; found 23:55). Every factory process loaded the whole
parse cache of the import graph at import time: one file in %TEMP% with an entry per (folder, file) for EVERY folder
ever scanned (each self-build snapshot, each test tree), never pruned - 59 MB on disk, about 600 MB in every runner
process. Now the cache is keyed by the file's path and the hash of its text, so a copy of the same tree adds nothing;
it is read by the first Graph, not by the import; it keeps at most CACHE_MAX entries, the newest."""
import os
import pickle
import re
import subprocess
import sys
from pathlib import Path

from tools import affected_tests as A


def _tree(root, n=3):
    (root / 'echo_sync').mkdir(parents=True)
    (root / 'tests').mkdir()
    for i in range(n):
        (root / 'echo_sync' / ('m%d.py' % i)).write_text('X = %d\n' % i, encoding='utf-8')
    (root / 'tests' / 'test_m0.py').write_text('from echo_sync.m0 import X\n\n\ndef test_x():\n    assert X == 0\n',
                                               encoding='utf-8')
    return root


def _isolated(monkeypatch, path):
    monkeypatch.setattr(A, '_CACHE_FILE', path)
    monkeypatch.setattr(A, '_CACHE', None)


def test_a_copy_of_the_same_tree_adds_no_entries(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path / 'cache.pkl')
    g1 = A.Graph(_tree(tmp_path / 'a'))
    n = len(pickle.loads((tmp_path / 'cache.pkl').read_bytes()))
    g2 = A.Graph(_tree(tmp_path / 'b'))
    assert n == 4 and len(pickle.loads((tmp_path / 'cache.pkl').read_bytes())) == n
    assert g1.rev['echo_sync/m0.py'] == g2.rev['echo_sync/m0.py'] == {'tests/test_m0.py'}


def test_entries_are_keyed_by_the_path_and_the_hash_of_the_text(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path / 'cache.pkl')
    A.Graph(_tree(tmp_path / 'a'))
    keys = list(pickle.loads((tmp_path / 'cache.pkl').read_bytes()))
    assert ('echo_sync/m0.py' in {k[0] for k in keys})
    assert all(isinstance(k, tuple) and len(k) == 2 and re.fullmatch(r'[0-9a-f]{40}', k[1]) for k in keys)


def test_the_cache_keeps_the_newest_entries_up_to_its_cap(tmp_path, monkeypatch):
    _isolated(monkeypatch, tmp_path / 'cache.pkl')
    monkeypatch.setattr(A, 'CACHE_MAX', 3)
    g = A.Graph(_tree(tmp_path / 'a', n=5))
    assert len(g.files) == 6
    assert len(pickle.loads((tmp_path / 'cache.pkl').read_bytes())) == 3


def test_the_import_alone_does_not_read_the_cache():
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, '-c', 'import tools.affected_tests as A; print(A._CACHE is None)'],
                         cwd=str(root), capture_output=True, text=True, timeout=60, env=dict(os.environ))
    assert out.stdout.strip() == 'True', out.stderr[-500:]
