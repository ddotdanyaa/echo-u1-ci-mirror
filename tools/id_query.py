"""U24: a query by a backlog ID (U78, N158, E33, W03, R31-4, E05.1) gives the files that mention it and the tests among them: ``python tools/id_query.py U78 [U29 ...] [--json]``.
The ID is a whole token: not glued to a word char, a dash or a dot before it, and not followed by a word char, a dash or ``.digit`` (``E05`` misses ``E05.1``, ``R31`` misses ``R31-4``; ``E05.`` at a sentence end still hits).
Tests are the matching paths under ``tests/``, files are the other matching text files. Scans git-tracked files (``git ls-files``), os.walk when root is not a git repo. Standard library only."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pattern(id):
    return re.compile(r'(?<![\w.-])' + re.escape(id) + r'(?![\w-]|\.\w)')


def _paths(root):
    try:
        out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True).stdout
        return sorted(p for p in out.decode('utf-8', 'replace').split('\0') if p)
    except (OSError, subprocess.CalledProcessError):
        found = []
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if x not in ('.git', '__pycache__')]
            found += [os.path.relpath(os.path.join(d, n), root) for n in names]
        return sorted(p.replace(os.sep, '/') for p in found)


def _text(path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return None if b'\0' in data[:8192] else data.decode('utf-8', 'replace')


def query(root, id):
    root, rx = Path(root), pattern(id)
    files, tests = [], []
    for rel in _paths(root):
        text = _text(root / rel)
        if text is None or not rx.search(text):
            continue
        (tests if rel.startswith('tests/') else files).append(rel)
    return {'id': id, 'files': files, 'tests': tests}


def main(argv=None):
    ap = argparse.ArgumentParser(description='U24: files and tests that mention backlog IDs')
    ap.add_argument('ids', nargs='+')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    res = [query(ROOT, i) for i in a.ids]
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    for r in res:
        print(f"{r['id']}: файлы {len(r['files'])}, тесты {len(r['tests'])}")
        for p in r['files']:
            print('  ' + p)
        for p in r['tests']:
            print('  [тест] ' + p)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
