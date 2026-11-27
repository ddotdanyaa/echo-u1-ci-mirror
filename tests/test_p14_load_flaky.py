"""HARVEST: the load-flaky list (tools/data/load_flaky.txt) names tests that exist, and none of them is a known red of the code (a flaky name must not hide a real red)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def entries():
    return [line.strip() for line in (ROOT / 'tools' / 'data' / 'load_flaky.txt').read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')]


def stem(entry):
    return entry.partition('::')[2].rsplit('::', 1)[-1].split('[')[0].replace('*', '')


def test_every_listed_test_exists():
    found = entries()
    assert len(found) == 6
    for entry in found:
        text = (ROOT / entry.partition('::')[0]).read_text(encoding='utf-8')
        assert stem(entry) and re.search(r'def ' + re.escape(stem(entry)), text), entry


def test_a_flaky_name_is_not_a_known_red():
    red = [line for line in (ROOT / 'tools' / 'data' / 'known_red.txt').read_text(encoding='utf-8').splitlines() if line.startswith(('FAILED', 'ERROR'))]
    for entry in entries():
        assert not [line for line in red if entry.partition('::')[0] in line and stem(entry) in line], entry
