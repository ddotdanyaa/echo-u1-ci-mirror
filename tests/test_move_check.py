"""X-BASE: ``tools/move_check`` proves a pure move: the same methods with the same normalised code, every global name still defined."""
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import move_check as M      # noqa: E402

BEFORE = textwrap.dedent('''
    import os
    LIMIT = 3

    def helper(x):
        """doc"""
        return x + LIMIT

    class Controller:
        def a(self):
            # a comment
            return helper(1)

        def b(self):
            return os.sep
''')


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


def snap(tmp_path, *files):
    return M.snapshot([str(path) for path in files])


def test_a_snapshot_of_itself_has_no_difference(tmp_path):
    one = write(tmp_path, 'one.py', BEFORE)
    a = snap(tmp_path, one)
    assert M.diff(a, snap(tmp_path, one)) == {'added': [], 'removed': [], 'changed': [], 'allowed': []}


def test_comments_docstrings_blank_lines_and_line_numbers_do_not_count(tmp_path):
    a = snap(tmp_path, write(tmp_path, 'one.py', BEFORE))
    moved = BEFORE.replace('# a comment', '# other words').replace('"""doc"""', '"""another doc"""').replace('\n    def b', '\n\n\n    def b')
    assert M.diff(a, snap(tmp_path, write(tmp_path, 'two.py', moved)))['changed'] == []


def test_a_move_between_files_is_no_change(tmp_path):
    a = snap(tmp_path, write(tmp_path, 'one.py', BEFORE))
    head, tail = BEFORE.split('    def b', 1)
    parts = [write(tmp_path, 'p1.py', head), write(tmp_path, 'p2.py', 'class Controller:\n    def b' + tail)]
    assert M.diff(a, snap(tmp_path, *parts)) == {'added': [], 'removed': [], 'changed': [], 'allowed': []}


def test_a_changed_body_a_lost_and_a_new_method_are_seen(tmp_path):
    a = snap(tmp_path, write(tmp_path, 'one.py', BEFORE))
    changed = BEFORE.replace('helper(1)', 'helper(2)').replace('    def b(self):\n        return os.sep\n', '    def c(self):\n        return 1\n')
    got = M.diff(a, snap(tmp_path, write(tmp_path, 'two.py', changed)))
    assert got['changed'] == ['Controller.a'] and got['removed'] == ['Controller.b'] and got['added'] == ['Controller.c']


def test_an_allow_list_moves_names_out_of_the_difference(tmp_path):
    a = snap(tmp_path, write(tmp_path, 'one.py', BEFORE))
    got = M.diff(a, snap(tmp_path, write(tmp_path, 'two.py', BEFORE.replace('helper(1)', 'helper(2)'))), allow={'Controller.a'})
    assert got['changed'] == [] and got['allowed'] == ['Controller.a']


def test_a_duplicate_definition_is_not_hidden(tmp_path):
    twice = BEFORE + '\n\nclass Controller:\n    def a(self):\n        return 5\n'
    a = snap(tmp_path, write(tmp_path, 'one.py', BEFORE))
    got = M.diff(a, snap(tmp_path, write(tmp_path, 'two.py', twice)))
    assert got['added'] or got['changed']


def test_globals_report_a_name_the_moved_code_no_longer_finds(tmp_path):
    ok = write(tmp_path, 'ok.py', BEFORE)
    assert M.missing_globals([str(ok)]) == {}
    broken = write(tmp_path, 'broken.py', BEFORE.replace('import os\n', ''))
    assert M.missing_globals([str(broken)]) == {'Controller.b': ['os']}


def test_globals_know_builtins_comprehensions_and_nested_functions(tmp_path):
    text = 'T = 1\n\ndef f(items):\n    def g(x):\n        return len(x) + T\n    return [g(i) for i in items if isinstance(i, str)]\n'
    assert M.missing_globals([str(write(tmp_path, 'a.py', text))]) == {}


def test_the_command_exit_codes(tmp_path, capsys):
    one = write(tmp_path, 'one.py', BEFORE)
    out = tmp_path / 'a.json'
    assert M.main(['snapshot', '-o', str(out), str(one)]) == 0
    assert M.main(['diff', str(out), str(out)]) == 0
    other = tmp_path / 'b.json'
    assert M.main(['snapshot', '-o', str(other), str(write(tmp_path, 'two.py', BEFORE.replace('helper(1)', 'helper(9)')))]) == 0
    assert M.main(['diff', str(out), str(other)]) == 1
    assert M.main(['globals', str(one)]) == 0
    assert 'missing names: 0' in capsys.readouterr().out
    assert json.loads(out.read_text(encoding='utf-8'))['methods']['Controller.a']


def test_the_outcome_sets_of_a_pytest_summary_and_their_difference():
    one = 'PASSED tests/a.py::t1\nPASSED tests/a.py::t2[x-1]\nXFAIL tests/a.py::t3 - reason\nSKIPPED [1] tests/a.py:9: no\nFAILED tests/a.py::t4 - boom\n'
    got = M.outcomes(one)
    assert got['PASSED'] == ['tests/a.py::t1', 'tests/a.py::t2[x-1]'] and got['XFAIL'] == ['tests/a.py::t3'] and got['FAILED'] == ['tests/a.py::t4'] and got['SKIPPED'] == 1
    assert M.outcomes_diff(got, M.outcomes(one)) == {}
    assert M.outcomes_diff(got, M.outcomes(one.replace('XFAIL', 'XPASS')))['tests/a.py::t3'] == ('XFAIL', 'XPASS')
    assert M.outcomes_diff(got, M.outcomes(one.replace('PASSED tests/a.py::t1\n', '')))['tests/a.py::t1'] == ('PASSED', None)


def test_the_decision_multisets_of_two_folders(tmp_path):
    for folder, lines in (('a', ['x', 'y', 'x']), ('b', ['x', 'x', 'y']), ('c', ['x', 'y'])):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'j.json').write_text(json.dumps({'lines': lines}), encoding='utf-8')
    assert M.decisions_diff(tmp_path / 'a', tmp_path / 'b') == {}
    assert M.decisions_diff(tmp_path / 'a', tmp_path / 'c') == {'j.json': {'only_a': 1, 'only_b': 0}}
