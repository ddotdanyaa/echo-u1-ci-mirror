"""fac-102: a critic's approval that cites the measured failing output of the gate (the execution report) stands."""
import json

import pytest

from tests.test_factory_light import task
from tools import agent_factory_runner as W

LINE = 'assert add(2, 3) == 5'


def rubric(line, approved=True):
    return json.dumps(dict(defect_assert_line=line, fix_changes_value='add returns the sum instead of the difference',
                           independent_asserts=[], approved=approved, reasons=[]))


def _review(tmp_path, answer, execution='', prompts=None):
    (tmp_path / 'calc.py').write_text('def add(a,b): return a+b\n')
    (tmp_path / 'tests').mkdir(exist_ok=True)
    (tmp_path / 'tests/test_calc.py').write_text('from calc import add\n\n\ndef test_add():\n    ' + LINE + '\n')

    def invoke(reviewer, root, model, prompt_override):
        if prompts is not None:
            prompts.append(prompt_override)
        return 0, (json.dumps({'type': 'text', 'part': {'text': answer}}) + '\n').encode(), b''
    return W.review_candidate(task(touch=('calc.py',)), tmp_path, 'google/y', invoke,
                              baseline={'calc.py': b'def add(a,b): return a-b\n'}, rubric=True, execution=execution)


def test_a_line_of_the_red_before_output_is_a_cited_line_assert_false(tmp_path):
    execution = 'red before:\nE   assert False\n'
    assert _review(tmp_path, rubric('assert False'), execution)[0] is True


def test_a_line_of_the_red_before_output_is_a_cited_line_comparison(tmp_path):
    execution = "red before:\nE   assert [] == ['x']\n"
    assert _review(tmp_path, rubric("assert [] == ['x']"), execution)[0] is True


def test_a_line_in_neither_the_test_nor_the_execution_is_invalid(tmp_path):
    with pytest.raises(W.RubricInvalid, match='not in the test'):
        _review(tmp_path, rubric('def add(a,b): return a-b'), 'red before:\nE   assert 1 == 2\n')


def test_a_line_of_the_product_source_is_still_a_problem(tmp_path):
    with pytest.raises(W.RubricInvalid, match='not in the test'):
        _review(tmp_path, rubric('def add(a,b): return a+b'), 'red before:\nE   assert False\n')


def test_the_prompt_names_the_measured_failing_output(tmp_path):
    prompts = []
    _review(tmp_path, rubric(LINE), 'E   assert False\n', prompts)
    assert 'measured failing output' in ' '.join(prompts)
