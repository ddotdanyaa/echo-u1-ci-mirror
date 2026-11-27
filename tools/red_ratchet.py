"""U23: «признанные расхождения не растут». Compare the failures of a run with tools/data/known_red.txt: exit 1 on any name that is not in it, print the count.

  python -m pytest -rfE -q ... | tee run.txt; python tools/red_ratchet.py run.txt        (pytest -rfE/-rA lines: FAILED/ERROR <node id> [- message])
  python tools/red_ratchet.py report.xml                                                 (junit xml: a failure or an error of a testcase)
A plain list of node ids (one per line) works too. The known list only shrinks: fix a red, delete its line and lower KNOWN_RED_COUNT in tests/test_u23_locks.py.
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_KNOWN = Path(__file__).resolve().parent / 'data' / 'known_red.txt'
ESCAPE = re.compile(r'\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})')


def norm(line):
    """One name in one form: no FAILED/ERROR prefix, no \\uXXXX escapes (pytest prints a Russian id either way)."""
    line = re.sub(r'^(?:FAILED|ERROR)\s+', '', line.strip())
    return ESCAPE.sub(lambda m: chr(int(m.group(1) or m.group(2), 16)), line)


def cut(name):
    """Drop `` - message`` (a ``-`` inside the [parameters] of an id is kept)."""
    for at in (m.start() for m in re.finditer(' - ', name)):
        if name[:at].count('[') == name[:at].count(']'):
            return name[:at]
    return name


def parse(lines):
    """Failed/errored names from -rfE/-rA lines or a plain list; everything else (headers, PASSED, counts) is skipped."""
    out = []
    for line in lines:
        s = line.strip()
        if s.startswith(('FAILED ', 'ERROR ')) or ('::' in s and not s.startswith(('PASSED', 'SKIPPED', 'XFAIL', 'XPASS', '=', '_'))) or re.match(r'^\S+\.py$', s):
            out.append(norm(s))
    return out


def parse_junit(text):
    out = []
    for case in ET.fromstring(text).iter('testcase'):
        if case.find('failure') is None and case.find('error') is None:
            continue
        parts, name = [p for p in case.get('classname', '').split('.') if p], case.get('name', '')
        if not parts:
            out.append(name.replace('.', '/') + '.py')
            continue
        modules = [i for i, p in enumerate(parts) if p.startswith('test_')]
        at = modules[-1] if modules else len(parts) - 1
        out.append('::'.join(['/'.join(parts[:at + 1]) + '.py', *parts[at + 1:], name]))
    return out


def load_known(path=DEFAULT_KNOWN):
    return {norm(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')}


def new_reds(names, known):
    """The failed names that the known list does not hold (a name with its message matches by any ``-`` cut), in order, once each."""
    out = []
    for name in names:
        name = norm(name)
        at = [m.start() for m in re.finditer(' - ', name)]
        if name in known or any(name[:i] in known for i in at):
            continue
        if cut(name) not in out:
            out.append(cut(name))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', help='pytest -rfE/-rA output, a plain list of names, or a junit xml')
    parser.add_argument('--known', default=str(DEFAULT_KNOWN))
    args = parser.parse_args(argv)
    text = Path(args.run).read_text(encoding='utf-8', errors='replace')
    names = parse_junit(text) if text.lstrip().startswith('<') else parse(text.splitlines())
    known = load_known(args.known)
    new = new_reds(names, known)
    seen = {cut(norm(n)) for n in names}
    fixed = sum(1 for k in known if k not in seen)
    print(f'red: {len(seen)}  known: {len(known)}  new: {len(new)}  fixed: {fixed}')
    for name in new:
        print(f'NEW RED {name}')
    return 1 if new else 0


if __name__ == '__main__':
    sys.exit(main())
