"""P13 / U94.7 (M7, slot S1): the controller reads the language through ONE door, ``cm_probes.probe(name, text, ctx)``; no function of ``classifier.py`` is called from any other module of it.

The 61 direct calls of ``classifier.*`` in ``controlled_media.py`` were each a place where a reading of the words was also a decision (ARCH_ONE M7: «зонд только сообщает признак, решает хозяин семейства»). The lock is the AST
(CLAUDE.md: a lock counts, it lists no phrase):

  * a controller module (``controlled_media.py`` and every ``cm_*.py`` but ``cm_probes.py``) calls no function that ``classifier.py`` defines, by its bare name or as ``classifier.<name>(...)``;
  * it imports none either (a function imported from ``.classifier``, or from ``cm_base`` which re-exports it, is a call waiting to be written): what stays importable from ``classifier`` is its VOCABULARY, the kind
    words (``QUESTION``, ``QUIET`` ...), the constants and the ``Decision`` / ``Feature`` carriers, which are names of verdicts and decide nothing;
  * ``cm_probes.py`` is the only module of the controller that calls the functions of ``classifier.py``, and every row of ``PROBES`` is a pure reading (no state of a controller, no write): it takes text and context and returns a value.

A new probe is one row of ``PROBES`` and no other file; the toy row of ``tests/test_extension_slots.py`` is how it is proved."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'echo_sync'
PROBES_FILE = 'cm_probes.py'
CARRIERS = frozenset({'Decision', 'Feature', 'Settings'})      # classes that carry a verdict or a feature: vocabulary, no reading


def controller_files():
    return [path for path in sorted(PACKAGE.glob('cm_*.py')) + [PACKAGE / 'controlled_media.py'] if path.name != PROBES_FILE]


def classifier_functions():
    """The functions ``classifier.py`` defines at module level (public and private): the readings. Constants and classes are its vocabulary."""
    tree = ast.parse((PACKAGE / 'classifier.py').read_text(encoding='utf-8'))
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def calls_and_imports(path, readings):
    """``[(line, what)]``: the calls of a reading of the classifier (bare or ``classifier.name``) and the imports of one, in the module ``path``."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}      # a name the module defines itself is its own, not the classifier's
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in ('classifier', 'cm_base'):
            found += [(node.lineno, 'import %s from %s' % (alias.name, node.module)) for alias in node.names if alias.name in readings and node.module == 'classifier']
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in readings and func.id not in defined:
                found.append((node.lineno, func.id + '('))
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == 'classifier' and func.attr in readings:
                found.append((node.lineno, 'classifier.%s(' % func.attr))
    return found


def test_the_controller_calls_no_function_of_the_classifier_outside_cm_probes():
    readings = classifier_functions()
    assert readings and 'analyze' in readings, 'the AST of classifier.py found no readings: the lock would pass for the wrong reason'
    left = {path.name: calls_and_imports(path, readings) for path in controller_files()}
    left = {name: rows for name, rows in left.items() if rows}
    total = sum(len(rows) for rows in left.values())
    assert total == 0, '%d direct reading(s) of the classifier outside cm_probes.py (each is a probe row and a decision of the owner):\n%s' % (
        total, '\n'.join('  %s:%d %s' % (name, line, what) for name, rows in sorted(left.items()) for line, what in rows[:12]))


def test_the_detector_sees_a_bare_call_a_module_call_and_an_import_and_spares_a_local_name_and_the_vocabulary(tmp_path):
    source = ('from .classifier import analyze, QUESTION, Decision\nimport classifier\n\ndef open_tail(x):\n    return x\n\n'
              'def judge(text):\n    a = analyze(text)\n    b = classifier.question_part(text)\n    c = open_tail(text)\n    return QUESTION, Decision, a, b, c\n')
    path = tmp_path / 'toy.py'
    path.write_text(source, encoding='utf-8')
    assert calls_and_imports(path, {'analyze', 'question_part', 'open_tail'}) == [(1, 'import analyze from classifier'), (8, 'analyze('), (9, 'classifier.question_part(')]


def test_cm_probes_is_the_door_and_its_rows_are_pure_readings():
    tree = ast.parse((PACKAGE / PROBES_FILE).read_text(encoding='utf-8'))
    names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    assert 'probe' in names, 'cm_probes.probe is the one entry'
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.Global, ast.Nonlocal)), 'a probe keeps no state (line %d)' % node.lineno
        if isinstance(node, ast.Assign):
            for target in node.targets:
                assert not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in ('self', 'controller', 'cm', 'c')), 'a probe writes no controller (line %d)' % node.lineno


def test_a_row_added_to_probes_is_read_through_the_door_and_decides_nothing():
    from echo_sync import cm_probes
    import pytest
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(cm_probes.PROBES, 'toy_len', lambda text, **_: len(str(text).split()))
        found = cm_probes.probe('toy_len', 'раз два три')
        assert getattr(found, 'value', found) == 3
    with pytest.raises(KeyError):
        cm_probes.probe('toy_len', 'раз два три')      # the row was a row of a test: it is gone with it, and an unknown name is an error, never a silent miss
