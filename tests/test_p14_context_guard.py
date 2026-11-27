"""harvest11 #1: a test that reads ``cloud_context/`` must never pass or skip because the data is missing. Here the data is checked once,
loudly: every folder the tests and tools name must exist and hold files. (The data itself is ported by P03; this guard turns its absence into one red
test with the names of the missing folders, never into a silent skip.)"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTX = ROOT / 'cloud_context'
SUB = re.compile(r"cloud_context['\"/ ,]+((?:bank|material|scripts|reports|analysis|tasks|safe)\b(?:/merged)?)")
SELF = Path(__file__).name


def _named_folders():
    names = set()
    for base in ('tests', 'tools'):
        for path in (ROOT / base).rglob('*.py'):
            if path.name == SELF:
                continue
            for match in SUB.finditer(path.read_text(encoding='utf-8', errors='replace')):
                names.add(match.group(1))
    return names


def test_the_folders_the_tests_name_exist_and_hold_files():
    named = _named_folders()
    assert {'bank', 'material', 'scripts', 'reports'} <= named, f'the scan found too few folder names: {sorted(named)}'
    empty = sorted(name for name in named if not (CTX / name).is_dir() or not any(p.is_file() for p in (CTX / name).rglob('*')))
    assert not empty, f'cloud_context data missing for tests/tools that read it: {empty} (P03 ports the data; a test must fail, not skip)'


def test_no_tracked_site_packages():
    import subprocess
    tracked = subprocess.run(['git', 'ls-files', '.test-venv', '.test-deps'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout.split()
    assert tracked == [], f'{len(tracked)} files of a local venv are tracked'
    ignored = (ROOT / '.gitignore').read_text(encoding='utf-8').split()
    assert '.test-venv/' in ignored and '.test-deps/' in ignored
