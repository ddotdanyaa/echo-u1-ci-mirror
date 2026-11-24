"""U24: a query by a backlog ID (U78, N158, E33, W03, R31-4, E05.1) gives the files that mention it and the tests among them: ``python tools/id_query.py U78 [U29 ...] [--json]``.
The ID is a whole token: not glued to a word char, a dash or a dot before it, and not followed by a word char, a dash or ``.digit`` (``E05`` misses ``E05.1``, ``R31`` misses ``R31-4``; ``E05.`` at a sentence end still hits).
Tests are the matching paths under ``tests/``, files are the other matching text files. Scans git-tracked files (``git ls-files``), os.walk when root is not a git repo. Standard library only.
I11 (U180, U131): ``index(root)`` is the same answer for every ID in ONE pass over the files; ``commits(root)`` reads ``git log`` and says which commits name an ID in the subject prefix (``U15, U38: ...`` closes U15 and U38) and which only mention it; ``--commits`` prints them. A mention is a link, not a proof that a test passes: only a cloud run proves that."""
import argparse
import json
import os
import re
import subprocess
import sys
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


TOKEN = re.compile(r'(?<![\w.-])([A-ZА-Я]{1,2}\d+(?:[.-]\d+)*)(?![\w-]|\.\w)')


def ids_in(text):
    """Every ID token of a text, with the same whole-token rule as pattern()."""
    return TOKEN.findall(text)


def index(root, only=None):
    """{id: {'files': [...], 'tests': [...]}} for every ID token (or only the ones in `only`), one pass over the tracked files."""
    root, out = Path(root), {}
    for rel in _paths(root):
        text = _text(root / rel)
        if text is None:
            continue
        key = 'tests' if rel.startswith('tests/') else 'files'
        for i in set(TOKEN.findall(text)):
            if only is None or i in only:
                out.setdefault(i, {'files': [], 'tests': []})[key].append(rel)
    return out


def commits(root):
    """[{sha, subject, closes, mentions}]: `closes` = IDs in the subject prefix before the first colon, `mentions` = IDs anywhere in the subject. [] when root is not a git repo."""
    try:
        raw = subprocess.run(['git', '-C', str(root), 'log', '--format=%H%x1f%s'], capture_output=True, check=True).stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.CalledProcessError):
        return []
    res = []
    for line in raw.splitlines():
        sha, _, subj = line.partition('\x1f')
        prefix = subj.split(':', 1)[0] if ':' in subj else ''
        res.append({'sha': sha, 'subject': subj, 'closes': sorted(set(TOKEN.findall(prefix))), 'mentions': sorted(set(TOKEN.findall(subj)))})
    return res


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
    ap.add_argument('--commits', action='store_true', help='add the commits that name the ID in the subject')
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    res = [query(ROOT, i) for i in a.ids]
    if a.commits:
        log = commits(ROOT)
        for r in res:
            r['commits'] = [{'sha': c['sha'][:10], 'subject': c['subject'], 'closes': r['id'] in c['closes']} for c in log if r['id'] in c['mentions']]
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    for r in res:
        print(f"{r['id']}: файлы {len(r['files'])}, тесты {len(r['tests'])}")
        for p in r['files']:
            print('  ' + p)
        for p in r['tests']:
            print('  [тест] ' + p)
        for c in r.get('commits', []):
            print('  [коммит%s] %s %s' % (' закрывает' if c['closes'] else '', c['sha'], c['subject']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
