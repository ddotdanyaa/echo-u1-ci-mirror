"""P13 / U95, U111: the registry of functions is EXECUTABLE. Every function that ``registry_proof/<id>.json`` records has, besides its record, a test through the real controller, and nothing in the record can say
more than the test proves. This is the meta-test of the coverage: it reads the records and the test files and holds them to each other (it runs no controller itself; the tests of ``tests/registry/`` do).

  * 96 records, the file name is the id, the id is the registry's number («3.11a»);
  * a record names its test (``tests/registry/test_fn_<id>.py``) and the file is there; a function with NO test is one of four honest outcomes (``not_built``, ``removed``, ``needs_laptop``, ``needs_phone``) and the record
    says why in its evidence; a record whose test file is gone while the verdict still claims a test is the lie this test exists for (4.13: the module was deleted with its test, the record kept the old word);
  * the test DRIVES the real thing: through the imports of the file (its helpers, ``tools/replay`` stands, depth 4) it reaches ``ControlledMedia`` / the host (``controlled_host.serve``, ``HostRig``) / the stand's world;
    the two functions of the machine outside the call (7.05 the gate of the deploy and 8.11 the telemetry of the model and the voice) are driven through the real tool they are, named in the test;
  * a test file of ``tests/registry/`` no record owns is an orphan; a test is never skipped (``skip`` is a hole in the registry), a strict xfail stays only where the verdict says the function does not work yet;
  * a function that ``works`` has its test checked on an empty function (``mutation_checked``): the test went red with the function off;
  * the numbers a record gives for a measurement have a source (2.10: the figures '461', '0,60' and '97 %' were found in no measurement file; the sourced ones stand, tagged «чужие голоса»)."""
import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECORDS = {path.stem: json.loads(path.read_text(encoding='utf-8')) for path in sorted((ROOT / 'registry_proof').glob('*.json'))}
HONEST = {'not_built', 'removed', 'needs_laptop', 'needs_phone'}      # a function with no test: it is not there, it is gone, or only the laptop or the phone can show it
DRIVERS = frozenset({'ControlledMedia', 'controlled_host', 'HostRig', 'NativeMediaSocket', 'World', 'Call', 'Dictation', 'make_rig'})      # what a test must reach: the real controller, its host or its stand
OUTSIDE_THE_CALL = {'7.05': ('tools/profile_backup', 'tools/gate'), '8.11': ('echo_sync',)}      # a function of the machine around the call: driven through its own real tool, which the test names
ID = re.compile(r'^\d\.\d\d[a-d]?$')


def test_there_is_one_record_a_function_and_its_name_is_its_number():
    assert len(RECORDS) == 96, len(RECORDS)
    assert all(ID.match(name) for name in RECORDS), [name for name in RECORDS if not ID.match(name)]
    assert all(row['id'] == name for name, row in RECORDS.items())
    assert all(row.get('name') and row.get('verdict') for row in RECORDS.values())


def test_every_record_names_a_test_that_is_there_or_an_honest_reason_why_not():
    lies, empty = [], []
    for name, row in RECORDS.items():
        test_file = row.get('test_file')
        if test_file:
            if not (ROOT / test_file).is_file() or test_file != 'tests/registry/test_fn_%s.py' % name.replace('.', '_'):
                lies.append((name, test_file))
        elif row['verdict'] not in HONEST or len(str(row.get('evidence') or '')) < 80:
            empty.append((name, row['verdict']))
    assert lies == [], 'the record names a test that is not there (or is not the function\'s own): %s' % lies
    assert empty == [], 'no test and no honest reason (verdict in %s with an evidence): %s' % (sorted(HONEST), empty)


def test_no_test_of_the_registry_is_an_orphan():
    owned = {row['test_file'] for row in RECORDS.values() if row.get('test_file')}
    files = {path.relative_to(ROOT).as_posix() for path in (ROOT / 'tests' / 'registry').glob('test_fn_*.py')}
    assert files - owned == set(), 'a test no record owns: %s' % sorted(files - owned)


def closure(path, seen=None, depth=0):
    """Every name a test file can reach through its own imports: the file, the helpers it imports from ``tests/``, the stands of ``tools/`` (depth 4); nothing of ``echo_sync`` is opened (the controller is the target)."""
    seen = set() if seen is None else seen
    if path in seen or depth > 4 or not path.is_file():
        return set()
    seen.add(path)
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            dotted = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module + '.' + alias.name for alias in node.names] if node.module else []
            names |= {alias.name for alias in node.names} | {part for module in dotted for part in module.split('.')[-1:]}
            for module in dotted + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else []):
                if module.split('.')[0] == 'echo_sync':
                    continue      # the controller is the target: it is named, never opened
                rel = module.replace('.', '/')
                for candidate in (ROOT / 'tests' / (rel + '.py'), ROOT / 'tests' / 'registry' / (rel + '.py'), ROOT / (rel + '.py'), ROOT / rel / '__init__.py'):
                    names |= closure(candidate, seen, depth + 1)
    return names


def with_tests():
    return [(name, row) for name, row in RECORDS.items() if row.get('test_file') and (ROOT / row['test_file']).is_file()]


@pytest.mark.parametrize('name,row', with_tests(), ids=[name for name, _ in with_tests()])
def test_the_test_of_a_function_drives_the_real_thing(name, row):
    path = ROOT / row['test_file']
    if name in OUTSIDE_THE_CALL:
        text = path.read_text(encoding='utf-8')
        assert any(tool in text for tool in OUTSIDE_THE_CALL[name]), '%s is a function of the machine around the call: its test drives the real tool %s' % (name, OUTSIDE_THE_CALL[name])
        return
    assert closure(path) & DRIVERS, '%s: no path from the test to the real controller (%s)' % (name, sorted(DRIVERS))
    assert any(isinstance(node, ast.FunctionDef) and node.name.startswith('test') for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))), name + ': the file has no test'


def marks(path):
    """``(skips, loose xfails)`` of a test file by the AST: the lines of a skip (``skip``, ``skipif``, ``importorskip``) and of an xfail that is not ``strict=True`` (a target that may stay red unseen)."""
    skips, loose = set(), set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ('skip', 'skipif', 'importorskip'):
                skips.add(node.lineno)
            elif node.func.attr == 'xfail' and not any(k.arg == 'strict' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                loose.add(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr in ('skip', 'skipif') and isinstance(node.value, ast.Attribute) and node.value.attr == 'mark':
            skips.add(node.lineno)
    return sorted(skips), sorted(loose)


def test_a_test_of_the_registry_is_never_skipped_and_every_xfail_is_strict():
    skipped, loose = {}, {}
    for name, row in with_tests():
        found = marks(ROOT / row['test_file'])
        if found[0]:
            skipped[name] = found[0]
        if found[1]:
            loose[name] = found[1]
    assert skipped == {}, 'a skip is a hole in the registry: %s' % skipped
    assert loose == {}, 'a non-strict xfail may stay red unseen (a target is strict: it fails the day the function works): %s' % loose


def test_the_detector_of_marks_sees_a_skip_a_loose_xfail_and_spares_a_strict_one(tmp_path):
    path = tmp_path / 'test_toy.py'
    path.write_text(chr(10).join(['import pytest', '', '@pytest.mark.skip(reason="x")', 'def test_a():', '    pass', '', '@pytest.mark.xfail(strict=True, reason="y")', 'def test_b():', '    pass', '',
                               '@pytest.mark.xfail(reason="z")', 'def test_c():', '    pass', '']), encoding='utf-8')
    assert marks(path) == ([3], [11])


def test_a_function_that_works_has_its_test_checked_on_an_empty_function():
    unchecked = [name for name, row in with_tests() if row['verdict'] == 'works' and str(row.get('mutation_checked')).lower() != 'true']
    assert unchecked == [], 'the test went red with the function off (mutation_checked) is not recorded for: %s' % unchecked


def test_the_figures_of_the_intonation_record_have_a_source_and_say_whose_voices_they_are():
    row = RECORDS['2.10']
    text = json.dumps(row, ensure_ascii=False)
    assert not re.search(r'\b461\b|0,60|\b97 ?%', text), 'a figure no measurement file holds (HARVEST U94.7)'
    assert 'REVIEW_20261112_V4' in text and 'ЧУЖИХ голосах' in text and '266' in text and '0,75–0,81' in text, 'the sourced figures stand, and they are those of foreign voices, not of the owner'


def test_the_detector_of_a_closure_follows_a_helper_and_a_stand(tmp_path, monkeypatch):
    package = tmp_path / 'tests'
    package.mkdir()
    (package / 'helper_a.py').write_text('from tools.stand import Run\n', encoding='utf-8')
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools' / 'stand.py').write_text('from echo_sync.controlled_media import ControlledMedia\n\nclass Run:\n    c = ControlledMedia\n', encoding='utf-8')
    (package / 'test_x.py').write_text('import helper_a\n\ndef test_x():\n    assert helper_a\n', encoding='utf-8')
    monkeypatch.setitem(closure.__globals__, 'ROOT', tmp_path)
    assert 'ControlledMedia' in closure(package / 'test_x.py')
    (package / 'test_y.py').write_text('def test_y():\n    assert 1 + 1 == 2\n', encoding='utf-8')
    assert not closure(package / 'test_y.py') & DRIVERS
