"""U23: «признанные расхождения не растут». Compare the failures of a run with tools/data/known_red.txt: exit 1 on any name that is not in it, print the count.

  python -m pytest -rfE -q ... | tee run.txt; python tools/red_ratchet.py run.txt        (pytest -rfE/-rA lines: FAILED/ERROR <node id> [- message])
  python tools/red_ratchet.py report.xml                                                 (junit xml: a failure or an error of a testcase)
A plain list of node ids (one per line) works too. The known list only shrinks: fix a red, delete its line and lower KNOWN_RED_COUNT in tests/test_u23_locks.py.

Two lists, two meanings (H31-11, R9): ``known_red.txt`` = reds of the CODE that are acknowledged (they are defects); ``cloud_env_red.txt`` = reds of the cloud's ENVIRONMENT
(Linux, no SAPI, no real models, no razdel), each under a ``## reason:`` header, so the ratchet does not confuse a missing speech engine with a bug. Both only shrink.
A pytest text run must end with its summary line (E33.2: a hung or cut run is not a green one): no summary line = exit 2; a summary that counts more failures than
the run names (no -rfE) = exit 3.
"""
import argparse
import importlib.util
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_KNOWN = Path(__file__).resolve().parent / 'data' / 'known_red.txt'
DEFAULT_FLAKY = Path(__file__).resolve().parent / 'data' / 'load_flaky.txt'
DEFAULT_ENV = Path(__file__).resolve().parent / 'data' / 'cloud_env_red.txt'
SUMMARY = re.compile(r'^=*\s*(?:(?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|subtests passed|rerun)),? ?)+.*\bin [\d.]+s', re.M)
COUNT = re.compile(r'(\d+) (failed|errors?)\b')
PYTEST_RUN = re.compile(r'test session starts|short test summary|\[\s*\d+%\]|^tests/\S+ [.FEsxX]+', re.M)
ENV_MODULES = ('razdel', 'rapidfuzz', 'numpy', 'sherpa_onnx', 'onnxruntime')
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


def load_env(path=DEFAULT_ENV):
    """``{name: reason}`` of the cloud-environment list (``## reason: ...`` lines set the reason of the names under them)."""
    out, reason = {}, ''
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith('## reason:'):
            reason = line[len('## reason:'):].strip()
        elif line.strip() and not line.startswith('#'):
            out[norm(line)] = reason
    return out


def is_load_flaky(name, path=DEFAULT_FLAKY):
    """True when ``name`` is on the load-flaky list (a trailing ``*`` is a prefix, a ``[..]`` id is exact): such a new red is rerun ALONE before it is called a regression."""
    if not Path(path).exists():
        return False
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        entry = norm(line)
        if entry and not entry.startswith('#') and (name.startswith(entry[:-1]) if entry.endswith('*') else name == entry):
            return True
    return False


def environment():
    """What this Python lacks that the cloud-environment list blames (printed with the verdict, so a red can be read against it)."""
    missing = [m for m in ENV_MODULES if importlib.util.find_spec(m) is None]
    return f"platform={sys.platform} no-sapi={'yes' if sys.platform != 'win32' else 'no'} missing-modules={','.join(missing) or '-'}"


def summary_problem(text, names):
    """None, or (exit code, text): the run of pytest did not end with its summary line / counts more failures than it names."""
    if not PYTEST_RUN.search(text):
        return None                                   # a plain list or a junit file has no summary
    lines = SUMMARY.findall(text)
    if not lines:
        return 2, 'NO SUMMARY LINE: the run was cut or hung; a run that did not finish is not a green one'
    last = [m for m in re.finditer(r'^.*\bin [\d.]+s.*$', text, re.M) if SUMMARY.match(m.group(0))]
    counted = sum(int(n) for n, _ in COUNT.findall(last[-1].group(0))) if last else 0
    if len(last) == 1 and counted > len({cut(norm(n)) for n in names}):
        return 3, f'the summary counts {counted} failed/errors, the run names {len({cut(norm(n)) for n in names})} (run with -rfE)'
    return None


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
    parser.add_argument('--env', default=str(DEFAULT_ENV), help='the cloud-environment reds (not defects); a missing file is an empty list')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')          # a Russian test id must not kill the verdict on a cp1251 console
    text = Path(args.run).read_text(encoding='utf-8', errors='replace')
    names = parse_junit(text) if text.lstrip().startswith('<') else parse(text.splitlines())
    known, env = load_known(args.known), load_env(args.env)
    new = new_reds(names, known | set(env))
    seen = {cut(norm(n)) for n in names}
    fixed = sum(1 for k in (known | set(env)) if k not in seen)
    xpass = sorted({line.split(None, 1)[1].strip() for line in text.splitlines() if line.startswith('XPASS ') and len(line.split(None, 1)) > 1})
    xpass = sorted(set(xpass) | {cut(norm(line)) for line in text.splitlines() if line.startswith('FAILED ') and 'XPASS(strict)' in line})        # 82 of the 86 xfail are strict: a fixed defect shows as a FAILED XPASS(strict)
    print(f'red: {len(seen)}  known: {len(known)}  cloud-env: {len(env)}  new: {len(new)}  fixed: {fixed}  xpass: {len(xpass)}')
    print('env: ' + environment())
    for reason in sorted(set(env.values())):
        print(f"  cloud-env {sum(1 for n in seen if env.get(n) == reason)} of the red: {reason}")
    for name in new:
        print(f'NEW RED {name}' + ('  (on load_flaky.txt: rerun it ALONE before calling it a regression)' if is_load_flaky(name) else ''))
    for name in xpass:
        print(f'XPASS (fixed: drop its xfail) {name}')
    problem = None if text.lstrip().startswith('<') else summary_problem(text, names)
    if problem:
        print(problem[1])
        return problem[0]
    return 1 if new else 0


if __name__ == '__main__':
    sys.exit(main())
