"""<id>: «признанные расхождения не растут». Compare the failures of a run with tools/data/known_red.txt: exit 1 on any name that is not in it, print the count.

  python -m pytest -rfE -q ... | tee run.txt; python tools/red_ratchet.py run.txt        (pytest -rfE/-rA lines: FAILED/ERROR <node id> [- message])
  python tools/red_ratchet.py report.xml                                                 (junit xml: a failure or an error of a testcase)
A plain list of node ids (one per line) works too. The known list only shrinks: fix a red, delete its line and lower KNOWN_RED_COUNT in tests/<id>_locks.py.

Two lists, two meanings (<id>, <id>): ``known_red.txt`` = reds of the CODE that are acknowledged (they are defects); ``cloud_env_red.txt`` = reds of the cloud's ENVIRONMENT
(Linux, no SAPI, no real models, no razdel), each under a ``## reason:`` header, so the ratchet does not confuse a missing speech engine with a bug. Both only shrink.
A pytest text run must end with its summary line (<id>: a hung or cut run is not a green one): no summary line = exit 2; a summary that counts more failures than
the run names (no -rfE) = exit 3.

CONF (w6): the cloud run is read without hand edits. (a) A red that is on neither list but whose own message names a thing only the environment can lack (a third-party module that is not installed, a data file of
cloud_context/ or tests/fixtures/harvest_scenes/ that git does not hold) is labelled «cloud-env (auto)» with that reason and is NOT counted as new; it is printed apart, so it never hides in the count.
A message that names nothing of the kind (a cut text, a KeyError, an assert) stays a new red. (b) ``--base RUN``: the same kind of run of the base commit; a name red there too is «base» (not a regression of the merge).
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
AUTO_MODULES = ('rapidfuzz', 'razdel', 'pymorphy3', 'snowballstemmer', 'hypothesis', 'httpx', 'numpy', 'sherpa_onnx', 'onnxruntime', 'diskcache', 'websockets', 'jsonschema', 'referencing')
NO_MODULE = re.compile(r"No module named ['\"]([A-Za-z0-9_]+)")
NO_DATA = re.compile(r"FileNotFoundError.*?((?:cloud_context|harvest_scenes)[/\\][^\s'\"]+|real_questions_ru\.json)")
ESCAPE = re.compile(r'\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})')


_BRACKET_ESCAPE = re.compile(r'\\U([0-9a-fA-F]{8})|\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})')


def _bracket_split(test_id):
    """(head, bracket part) of a test id: the part from the first ``[`` on is the parametrize id pytest escapes."""
    test_id = str(test_id)
    at = test_id.find('[')
    return (test_id, '') if at < 0 else (test_id[:at], test_id[at:])


def readable(test_id):
    """fac-91: the one form of a test id inside the machine: the escapes (backslash u/U/x + hex) of the bracket part
    are the characters. An id without a bracket part is returned as it is."""
    head, tail = _bracket_split(test_id)
    if not tail:
        return head
    return head + _BRACKET_ESCAPE.sub(lambda m: chr(int(m.group(1) or m.group(2) or m.group(3), 16)), tail)


def runnable(test_id):
    """fac-91: the form pytest finds at its door: every non-ASCII character of the bracket part is escaped the way pytest
    prints it (the unicode_escape codec); ASCII is left alone. ``readable(runnable(x)) == readable(x)``."""
    head, tail = _bracket_split(readable(test_id))
    if not tail:
        return head
    return head + ''.join(c if ord(c) < 128 else c.encode('unicode_escape').decode('ascii') for c in tail)


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


def messages(text):
    """``{cut name: message}`` of the failures of a text run (``FAILED id - message``) or a junit xml (the message / text of the failure or error)."""
    out = {}
    if text.lstrip().startswith('<'):
        for case in ET.fromstring(text).iter('testcase'):
            bad = case.find('failure') if case.find('failure') is not None else case.find('error')
            if bad is None:
                continue
            parts, name = [p for p in case.get('classname', '').split('.') if p], case.get('name', '')
            modules = [i for i, p in enumerate(parts) if p.startswith('test_')]
            at = modules[-1] if modules else len(parts) - 1
            key = '::'.join(['/'.join(parts[:at + 1]) + '.py', *parts[at + 1:], name]) if parts else name.replace('.', '/') + '.py'
            out[key] = (bad.get('message') or '') + ' ' + (bad.text or '')[:2000]
        return out
    for line in text.splitlines():
        if line.startswith(('FAILED ', 'ERROR ')):
            full = norm(line)
            name = cut(full)
            out[name] = full[len(name):]
    return out


def auto_env(message):
    """The reason (str) when the message of a red names a missing third-party module or a missing cloud data file, else ``''``. Only what the environment can lack, never an assert or a KeyError."""
    found = NO_MODULE.search(message)
    if found and found.group(1) in AUTO_MODULES:
        return f'cloud-env (auto): the module {found.group(1)} is not installed (bash cloud_context/SETUP_CLOUD.sh)'
    found = NO_DATA.search(message)
    if found:
        return f'cloud-env (auto): the data file {found.group(1)} is not in git, put it into the cloud session'
    return ''


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


def compare(names, known=DEFAULT_KNOWN, env=DEFAULT_ENV, base_names=(), notes=None, extra_known=()):
    """The one comparison of a run with the lists (``main`` and the release sweep call it).

    ``known`` / ``env`` are list files (a path) or ready sets / ``{name: reason}`` dicts; ``extra_known`` is a set that joins ``known``.
    ``notes`` = ``{name: message}`` (see ``messages``) feeds the cloud-environment auto label; ``base_names`` = names red on the base too.
    Returns ``{"new": [...], "auto": {name: reason}, "seen": set, "known": set, "env": dict, "base": set}``."""
    if isinstance(known, (str, Path)):
        known = load_known(known) if Path(known).exists() else set()
    known = set(known) | {norm(n) for n in extra_known}
    env = load_env(env) if isinstance(env, (str, Path)) else dict(env or {})
    base = {cut(norm(n)) for n in base_names}
    notes = notes or {}
    auto = {}
    for name in names:
        key = cut(norm(name))
        if key not in known and key not in env and key not in base:
            reason = auto_env(notes.get(key, '') + ' ' + norm(name)[len(key):])
            if reason:
                auto[key] = reason
    new = [n for n in new_reds(names, known | set(env) | base) if n not in auto]
    return {'new': new, 'auto': auto, 'seen': {cut(norm(n)) for n in names}, 'known': known, 'env': env, 'base': base}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run', help='pytest -rfE/-rA output, a plain list of names, or a junit xml')
    parser.add_argument('--known', default=str(DEFAULT_KNOWN))
    parser.add_argument('--base', default='', help='a run of the BASE commit (same formats): a name red there too is the base, not a regression')
    parser.add_argument('--env', dest='env_list', default=str(DEFAULT_ENV), help='the cloud-environment reds (not defects); a missing file is an empty list')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')          # a Russian test id must not kill the verdict on a cp1251 console
    text = Path(args.run).read_text(encoding='utf-8', errors='replace')
    names = parse_junit(text) if text.lstrip().startswith('<') else parse(text.splitlines())
    known = load_known(args.known)                  # a missing known list is an error here, as before
    base_names = set()
    if args.base:
        base_text = Path(args.base).read_text(encoding='utf-8', errors='replace')
        base_names = {cut(norm(n)) for n in (parse_junit(base_text) if base_text.lstrip().startswith('<') else parse(base_text.splitlines()))}
    got = compare(names, known, args.env_list, base_names, messages(text))
    env, auto, new, seen = got['env'], got['auto'], got['new'], got['seen']
    fixed = sum(1 for k in (known | set(env)) if k not in seen)
    xpass = sorted({line.split(None, 1)[1].strip() for line in text.splitlines() if line.startswith('XPASS ') and len(line.split(None, 1)) > 1})
    xpass = sorted(set(xpass) | {cut(norm(line)) for line in text.splitlines() if line.startswith('FAILED ') and 'XPASS(strict)' in line})        # 82 of the 86 xfail are strict: a fixed defect shows as a FAILED XPASS(strict)
    print(f'red: {len(seen)}  known: {len(known)}  cloud-env: {len(env)}  cloud-env-auto: {len(auto)}  base: {len(seen & base_names)}  new: {len(new)}  fixed: {fixed}  xpass: {len(xpass)}')
    print('env: ' + environment())
    for reason in sorted(set(env.values())):
        print(f"  cloud-env {sum(1 for n in seen if env.get(n) == reason)} of the red: {reason}")
    for reason in sorted(set(auto.values())):
        print(f"  {sum(1 for r in auto.values() if r == reason)} red: {reason}")
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
