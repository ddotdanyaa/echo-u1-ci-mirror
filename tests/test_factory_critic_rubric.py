"""The critic answers a fixed rubric and the verdict is the majority of up to three critics of different models
(execution-ranked selection: the critic gets the mechanical execution report, an approval needs a cited test line that
is really in the code shown and no assert independent of the code under test; a tie goes to the mechanical ranking)."""
import json
from types import SimpleNamespace

import pytest

from tests.test_factory_light import task
from tests.test_factory_runtime import FIX_BLOCK, TWO_CHANNELS, Rig
from tests.test_factory_tournament import _wire
from tools import agent_factory_runner as W

LINE = 'assert add(2, 3) == 5'
RIG_LINE = 'assert add(2,3)==5'      # the line of the test the runner rig writes


def rubric(approved=True, line=LINE, fix='add returns the sum instead of the difference', independent=(), **extra):
    answer = dict(defect_assert_line=line, fix_changes_value=fix, independent_asserts=list(independent),
                  approved=approved, reasons=[])
    answer.update(extra)
    return json.dumps(answer)


def _review(tmp_path, answer, execution='', rubric_on=True, prompts=None):
    (tmp_path / 'calc.py').write_text('def add(a,b): return a+b\n')
    (tmp_path / 'tests').mkdir(exist_ok=True)
    (tmp_path / 'tests/test_calc.py').write_text('from calc import add\n\n\ndef test_add():\n    ' + LINE + '\n')

    def invoke(reviewer, root, model, prompt_override):
        if prompts is not None:
            prompts.append(prompt_override)
        return 0, (json.dumps({'type': 'text', 'part': {'text': answer}}) + '\n').encode(), b''
    return W.review_candidate(task(touch=('calc.py',)), tmp_path, 'google/y', invoke,
                              baseline={'calc.py': b'def add(a,b): return a-b\n'}, rubric=rubric_on,
                              execution=execution)


def test_a_complete_rubric_with_a_line_that_is_in_the_code_approves(tmp_path):
    assert _review(tmp_path, rubric()) == (True, [])


def test_a_cited_line_that_is_not_in_the_code_rejects(tmp_path):
    approved, reasons = _review(tmp_path, rubric(line='assert add(2, 3) == 6'))
    assert approved is False and 'not in the test' in ' '.join(reasons)


def test_a_line_cited_from_the_source_rather_than_the_test_rejects(tmp_path):
    approved, reasons = _review(tmp_path, rubric(line='def add(a,b): return a+b'))
    assert approved is False and 'not in the test' in ' '.join(reasons)


def test_the_cited_line_may_differ_in_whitespace_only(tmp_path):
    assert _review(tmp_path, rubric(line='  assert   add(2, 3)  == 5 '))[0] is True


@pytest.mark.parametrize('answer', [
    '{"approved": true, "reasons": []}',                                          # no rubric at all
    json.dumps(dict(approved=True, fix_changes_value='x', independent_asserts=[])),   # no cited line
    json.dumps(dict(approved=True, defect_assert_line=LINE, independent_asserts=[])),  # no value of the fix
    json.dumps(dict(approved=True, defect_assert_line=LINE, fix_changes_value='x')),   # no independent_asserts
    json.dumps(dict(approved=True, defect_assert_line='', fix_changes_value='x', independent_asserts=[])),
    json.dumps(dict(approved=True, defect_assert_line=LINE, fix_changes_value='x', independent_asserts='none')),
])
def test_a_missing_or_malformed_rubric_never_approves(tmp_path, answer):
    approved, reasons = _review(tmp_path, answer)
    assert approved is False and reasons


def test_an_independent_assert_rejects(tmp_path):
    approved, reasons = _review(tmp_path, rubric(independent=['assert 1 == 1']))
    assert approved is False and 'independent' in ' '.join(reasons) and 'assert 1 == 1' in ' '.join(reasons)


def test_an_unparsable_answer_is_a_critic_failure_never_an_approval(tmp_path):
    with pytest.raises(W.ReviewFault):
        _review(tmp_path, 'looks fine to me')


def test_without_the_rubric_flag_the_old_plain_verdict_still_works(tmp_path):
    assert _review(tmp_path, '{"approved": true}', rubric_on=False) == (True, [])


def test_the_prompt_carries_the_execution_report_and_the_rubric_keys(tmp_path):
    seen = []
    _review(tmp_path, rubric(), execution='Mechanical execution report:\nFailing path: calc.py::add\n', prompts=seen)
    assert 'Failing path: calc.py::add' in seen[0]
    assert all(key in seen[0] for key in ('defect_assert_line', 'fix_changes_value', 'independent_asserts'))
    plain = []
    _review(tmp_path, '{"approved": true}', rubric_on=False, prompts=plain)
    assert 'defect_assert_line' not in plain[0]


def test_the_execution_report_lists_the_measured_facts_redacted():
    base = SimpleNamespace(diag='FAILED test_calc::test_add AssertionError: 1 != 5',
                           path=(('calc.py', 'add', 3), ('calc.py', 'helper', 9)))
    text = W.execution_report(base, hollow=('assert True',), extra_names=('new_helper',))
    for part in ('1 != 5', 'calc.py::add', 'calc.py::helper', 'assert True', 'new_helper'):
        assert part in text
    assert len(text) <= W.EXEC_REPORT_LIMIT
    assert W.execution_report(SimpleNamespace(diag='', path=())) == ''


def test_the_mechanical_ranking_needs_a_measured_path_and_nothing_hollow():
    path = (('calc.py', 'add', 3),)
    assert W.mechanically_ok(SimpleNamespace(path=path))
    assert not W.mechanically_ok(SimpleNamespace(path=()))
    assert not W.mechanically_ok(SimpleNamespace(path=path), hollow=('assert True',))
    assert not W.mechanically_ok(SimpleNamespace(path=path), extra_names=('x',))


def test_two_of_three_decide_and_a_split_goes_to_the_mechanical_ranking():
    pv = W.panel_verdict
    assert W.REVIEW_PANEL == 3
    assert pv([True, True], False, False) is True            # two approvals end it, a third critic is not asked
    assert pv([False, False], False, True) is False
    assert pv([True], False, True) is None and pv([False], False, True) is None
    assert pv([True, False], False, True) is None             # a third critic can still be asked
    assert pv([True, False, True], True, False) is True
    assert pv([False, True, False], True, True) is False
    assert pv([True, False], True, True) is True              # no third model: the ranking decides
    assert pv([False, True], True, False) is False
    assert pv([True], True, True) is None                     # one critic never decides alone


def _four_models(tmp_path):
    rows = TWO_CHANNELS + [dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100,
                                verified=True),
                           dict(id='c4', group='p4', model='google/w', key_env='KEY', tpm=100000, rpd=100,
                                verified=True)]
    cfg = tmp_path / 'four.json'
    cfg.write_text(json.dumps(dict(channels=rows)))
    return cfg


def test_the_loop_approves_with_two_rubric_approvals_and_asks_no_third_critic(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: rubric(line=RIG_LINE))
    result = rig.once(channel_config=_four_models(tmp_path))
    assert result['status'] == 'REVIEW' and len([s for s in sent if s['review']]) == 2
    assert all('defect_assert_line' in s['prompt'] for s in sent if s['review'])


def test_the_loop_takes_the_majority_when_the_first_critic_disagrees(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    answers = {1: rubric(approved=False, line=RIG_LINE, reasons=['the sum is not pinned']), 2: rubric(line=RIG_LINE), 3: rubric(line=RIG_LINE)}
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: answers[n])
    result = rig.once(channel_config=_four_models(tmp_path))
    assert result['status'] == 'REVIEW' and len([s for s in sent if s['review']]) == 3
    assert result['critiques'][0].startswith('critic 1 rejected')


def test_two_rejections_reject_without_a_third_critic(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    answers = {1: rubric(approved=False, line=RIG_LINE), 2: rubric(approved=False, line=RIG_LINE), 3: rubric(line=RIG_LINE)}
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: answers[n])
    result = rig.once(channel_config=_four_models(tmp_path))
    assert result['status'] == 'READY' and result['reason'].startswith('review:')
    assert len([s for s in sent if s['review']]) == 2


def test_a_plain_approval_without_the_rubric_is_rejected_by_the_loop(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: '{"approved": true, "reasons": []}')
    result = rig.once(channel_config=_four_models(tmp_path))
    assert result['status'] != 'REVIEW' and 'critic rubric' in result['reason']


def test_a_split_with_no_third_model_and_no_measured_path_is_rejected(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    answers = {1: rubric(line=RIG_LINE), 2: rubric(approved=False, line=RIG_LINE, reasons=['not pinned'])}
    _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: answers[n])
    result = rig.once(channel_config=_cfg_two_critics(tmp_path))
    assert result['status'] == 'READY' and result['reason'].startswith('review:')


def _cfg_two_critics(tmp_path):
    rows = TWO_CHANNELS + [dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100,
                                verified=True)]
    cfg = tmp_path / 'three.json'
    cfg.write_text(json.dumps(dict(channels=rows)))
    return cfg
