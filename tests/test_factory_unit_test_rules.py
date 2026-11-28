"""The unit_test coder is told the gate's rules up front, from the gate's own constant."""
from __future__ import annotations

import ast
from pathlib import Path

from tools import agent_factory_runner as runner
from tools import factory_gate as gate


def _emitted_codes():
    tree = ast.parse(Path(gate.__file__).read_text(encoding='utf-8'))
    codes = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in ('_hollow', '_guessed_key_hits', '_unknown_membership_hits'):
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'append' and n.args \
                        and isinstance(n.args[0], ast.Tuple) and isinstance(n.args[0].elts[0], ast.Constant):
                    codes.add(n.args[0].elts[0].value)
    return codes


def test_every_emitted_rule_has_a_line():
    codes = _emitted_codes()
    assert codes >= {'A', 'A2', 'B', 'E', 'G'}
    assert codes == set(gate.HOLLOW_RULE_TEXT)
    for text in gate.HOLLOW_RULE_TEXT.values():
        assert text in gate.UNIT_TEST_RULES
    assert gate.ALL_RED_RULE_TEXT in gate.UNIT_TEST_RULES


def test_rules_text_names_the_main_rules():
    text = gate.UNIT_TEST_RULES.lower()
    for part in ('call the real code', 'absent from the code', 'guessed dict keys', 'source text',
                 'is not none', 'fail on today'):
        assert part in text


def _task(kind):
    touch = ('tests/test_x.py',) if kind == 'unit_test' else ('echo_sync/x.py',)
    return runner.Task(id='t1', title='a title', kind=kind, touch_files=touch, tests=('tests/test_x.py',),
                       read_files=(), depends_on=(), privacy_safe=True, estimated_tokens=100)


def test_unit_test_prompt_has_the_rules_once_and_code_prompt_not():
    unit = runner.build_coder_prompt(_task('unit_test'), {}, light=True)
    assert unit.count(gate.UNIT_TEST_RULES) == 1
    code = runner.build_coder_prompt(_task('code'), {}, light=True)
    assert 'The gate rejects a unit test' not in code
