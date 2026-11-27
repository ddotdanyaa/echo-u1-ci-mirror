"""U23: two locks that stop a quiet slide. (1) The stand's substitutions are a registry: a new fake that is not listed turns this red.
(2) The acknowledged reds do not grow: tools/data/known_red.txt is frozen at KNOWN_RED_COUNT, tools/red_ratchet.py fails on a red outside it.
(The owner-consent Stop hook of the U1 rules is NOT installed here: see lane_reports/reports/u56_u23.md.)"""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import red_ratchet as R  # noqa: E402

REGISTRY = ROOT / 'tools' / 'data' / 'stand_substitutions.json'
KNOWN_RED = ROOT / 'tools' / 'data' / 'known_red.txt'
KNOWN_RED_COUNT = 190        # acknowledged reds on the base commit; it only goes DOWN: lower this number when a red is fixed, never raise it
SCAN_DIRS = ('tests', 'tools/replay')
CLASS_NAME = re.compile(r'^(Fake|Stub|Mock|Dummy|Scripted)\w*$|^Virtual(Loop|Asyncio)$|^\w*Clock$')
FUNC_NAME = re.compile(r'^(fake|stub)_\w+$')
WHAT = {'gpt-live', 'sapi', 'phone', 'clock', 'sherpa-silero', 'ear', 'text-model', 'http', 'lookup', 'process', 'controller', 'embedding', 'modules', 'wire', 'cloud'}


def convention_names():
    """(file, name) of every class/function that the naming convention marks as a substitution (a TestCase named Fake* is a test, not a fake)."""
    found = {}
    for folder in SCAN_DIRS:
        for path in sorted((ROOT / folder).rglob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and CLASS_NAME.match(node.name):
                    bases = {getattr(b, 'attr', getattr(b, 'id', '')) for b in node.bases}
                    if 'TestCase' not in bases:
                        found.setdefault((path.relative_to(ROOT).as_posix(), node.name), node.lineno)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and FUNC_NAME.match(node.name):
                    found.setdefault((path.relative_to(ROOT).as_posix(), node.name), node.lineno)
    return found


def registry():
    return json.loads(REGISTRY.read_text(encoding='utf-8'))['entries']


# 1. the registry of the stand's substitutions

def test_every_substitution_by_the_naming_convention_is_in_the_registry():
    listed = {(e['file'], e['name']) for e in registry()}
    missing = sorted(f'{f}:{line} {n}' for (f, n), line in convention_names().items() if (f, n) not in listed)
    assert not missing, 'a substitution of the stand that tools/data/stand_substitutions.json does not know (add it with what it replaces and why): ' + ', '.join(missing)


def test_every_registry_entry_exists_and_says_what_it_replaces_and_why():
    for e in registry():
        text = (ROOT / e['file']).read_text(encoding='utf-8')
        assert re.search(rf'^\s*(?:async\s+)?(?:class|def)\s+{re.escape(e["name"])}\b', text, re.M), f'{e["file"]}: {e["name"]} is gone, drop it from the registry'
        assert e['replaces'] in WHAT, (e['name'], e['replaces'])
        assert len(e['what'].split()) >= 3 and len(e['why'].split()) >= 3, e['name']


def test_the_registry_has_no_duplicates_and_names_the_main_replaced_parts():
    keys = [(e['file'], e['name']) for e in registry()]
    assert len(keys) == len(set(keys))
    assert {'gpt-live', 'sapi', 'phone', 'clock', 'sherpa-silero'} <= {e['replaces'] for e in registry()}


def test_an_unlisted_substitution_would_turn_the_lock_red(tmp_path, monkeypatch):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_new.py').write_text('class FakePhone:\n    pass\n\ndef stub_clock():\n    pass\n\nclass FakeX(__import__("unittest").TestCase):\n    pass\n')
    monkeypatch.setattr(sys.modules[__name__], 'ROOT', tmp_path)
    assert set(convention_names()) == {('tests/test_new.py', 'FakePhone'), ('tests/test_new.py', 'stub_clock')}


# 2. «признанные расхождения не растут»

def test_the_known_red_list_is_frozen_and_clean():
    names = [line for line in KNOWN_RED.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(names) == KNOWN_RED_COUNT
    assert len(set(map(R.norm, names))) == len(names)
    assert all(re.match(r'^(FAILED|ERROR) tests/', line) for line in names)


def test_a_red_inside_the_known_list_passes_the_ratchet():
    known = R.load_known(KNOWN_RED)
    sample = next(iter(sorted(known)))
    assert R.new_reds([sample], known) == []


def test_a_red_outside_the_known_list_fails_the_ratchet():
    known = R.load_known(KNOWN_RED)
    assert R.new_reds(['tests/test_brand_new.py::test_x'], known) == ['tests/test_brand_new.py::test_x']


def test_rA_lines_are_normalized_prefix_message_and_unicode_escapes():
    known = {R.norm('FAILED tests/test_a.py::test_p[\\u0434\\u0430 - b]')}
    lines = ['FAILED tests/test_a.py::test_p[да - b] - AssertionError: x - y', 'ERROR tests/test_a.py::test_p[да - b]', 'FAILED tests/test_z.py::test_q - boom']
    assert R.new_reds(R.parse(lines), known) == ['tests/test_z.py::test_q']


def test_junit_failures_and_errors_become_node_ids():
    xml = ('<testsuites><testsuite><testcase classname="tests.test_a.TestK" name="test_x"><failure message="m"/></testcase>'
           '<testcase classname="tests.test_a" name="test_ok"/><testcase classname="tests.test_b" name="test_y[1]"><error message="e"/></testcase>'
           '<testcase classname="tests.sub.test_c" name="test_s"><skipped/></testcase></testsuite></testsuites>')
    assert R.parse_junit(xml) == ['tests/test_a.py::TestK::test_x', 'tests/test_b.py::test_y[1]']


def test_cli_prints_the_count_and_exits_1_only_on_a_new_red(tmp_path):
    known = tmp_path / 'known.txt'
    known.write_text('FAILED tests/test_a.py::test_one\nERROR tests/test_b.py\n', encoding='utf-8')
    ok, bad = tmp_path / 'ok.txt', tmp_path / 'bad.txt'
    ok.write_text('FAILED tests/test_a.py::test_one - boom\n', encoding='utf-8')
    bad.write_text('FAILED tests/test_a.py::test_one - boom\nFAILED tests/test_c.py::test_new - boom\n', encoding='utf-8')
    run = lambda f: subprocess.run([sys.executable, str(ROOT / 'tools' / 'red_ratchet.py'), str(f), '--known', str(known)], capture_output=True, text=True)
    got = run(ok)
    assert got.returncode == 0 and 'red: 1' in got.stdout and 'new: 0' in got.stdout, got.stdout
    got = run(bad)
    assert got.returncode == 1 and 'new: 1' in got.stdout and 'tests/test_c.py::test_new' in got.stdout, got.stdout
