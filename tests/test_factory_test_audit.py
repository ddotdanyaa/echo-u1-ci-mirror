"""<id>, the factory's own test is checked at once (skeptic verdict test-red-review, 20.11): of the code tasks that were red
on a test the factory had written and promoted for their row, 7 of 7 had an unfit test, and the 2 with a fit test passed
on their first pass; yet such a test was audited only after two returns on a new factory version (nine passes and
more). A pass records, per model whose candidate failed the gate, the test ids it was red on (report 'gate_red'). When
two or more different models of one pass are red on the same test of the promoted test task of the row, that test goes
back to its test task at once, once per test, and the code task waits for the rewritten test."""
import json

from tests.test_factory_runtime import FIX_BLOCK, Rig
from tests.test_factory_tournament import _wire
from tools import factory_requeue as Q

APPROVE = '{"approved": true, "reasons": []}'
GATE = 'gate: rc=1 (0 required)'
TID2 = 'T' + '2'      # the loop env plans <id>, <id> ...; built at runtime so no ID-shaped literal stays in the source


def _state():
    return {'tasks': {'bl_A': {'status': 'READY', 'backlog_id': 'A', 'kind': 'code'},
                      'bl_A_test': {'status': 'PROMOTED', 'backlog_id': 'A', 'kind': 'unit_test'}}}


def _tests_of(tid):
    return ['tests/test_a.py'] if tid == 'bl_A_test' else []


def _answers(box):
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((box / 'answers').glob('*.json'))]


def test_the_pass_records_the_ids_every_red_model_failed_on(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    wrong = FIX_BLOCK.replace('return a+b', 'return a*b')
    _wire(rig, monkeypatch, lambda model: wrong, lambda model, n: APPROVE)
    result = rig.once()
    assert result['reason'].startswith('gate:'), result
    reds = result['gate_red']
    assert len({model for model, _ in reds}) == 3 and all(ids == ['t::red'] for _, ids in reds)   # the rig: 3 models


def test_two_models_red_on_the_promoted_factory_test_send_it_back_at_once_and_only_once(tmp_path):
    report = {'reason': GATE, 'gate_red': [['x', ['tests.test_a::test_one']],
                                           ['y', ['tests.test_a::test_one', 'tests.test_b::test_two']]]}
    assert Q.audit_after_pass(tmp_path, _state(), 'bl_A', report, 'v9', _tests_of) == 'bl_A_test'
    answers = _answers(tmp_path)
    back = [a for a in answers if a.get('task_id') == 'bl_A_test']
    assert len(back) == 1 and back[0]['reject'] is True and 'v9' in back[0]['note']
    assert any(a.get('task_id') == 'bl_A' and a.get('depends_on') == ['bl_A_test'] for a in answers)
    ledger = json.loads((tmp_path / 'requeue_ledger.json').read_text(encoding='utf-8'))
    assert 'audit:bl_A_test' in ledger
    assert Q.audit_after_pass(tmp_path, _state(), 'bl_A', report, 'v9', _tests_of) is None
    assert len(_answers(tmp_path)) == len(answers)


def test_one_model_another_test_or_different_tests_are_no_audit(tmp_path):
    for reds in ([['x', ['tests.test_a::test_one']], ['x', ['tests.test_a::test_one']]],          # one model twice
                 [['x', ['tests.test_b::test_two']], ['y', ['tests.test_b::test_two']]],          # not the factory test
                 [['x', ['tests.test_a::test_one']], ['y', ['tests.test_a::test_three']]]):       # not the same test
        assert Q.audit_after_pass(tmp_path, _state(), 'bl_A', {'reason': GATE, 'gate_red': reds}, 'v9', _tests_of) is None
    assert not (tmp_path / 'answers').exists()


def test_the_loop_sends_the_factory_test_back_after_such_a_pass(tmp_path, monkeypatch):
    from test_factory_loop import Env, task_row
    env = Env(tmp_path, monkeypatch, tasks=[
        task_row(1, backlog_id='A'),
        task_row(2, backlog_id='A', kind='unit_test', touch_files=['tests/test_a.py'], tests=['tests/test_a.py'])])
    env.set_row(TID2, status='PROMOTED')
    loop = env.loop()
    env.runner_says({'status': 'READY', 'task': 'T1', 'reason': GATE, 'calls': [],
                     'gate_red': [['x', ['tests.test_a::test_one']], ['y', ['tests.test_a::test_one']]]})
    loop.step()
    sent = [json.loads(p.read_text(encoding='utf-8')) for p in (env.state_dir / 'answers').rglob('*.json')]
    assert any(a.get('task_id') == TID2 and a.get('reject') is True for a in sent), sent
    assert any(e['span'] == 'audit' and e.get('reason') == TID2 for e in env.events())


def test_a_task_without_a_promoted_factory_test_or_a_pass_without_a_red_gate_is_never_audited(tmp_path):
    reds = [['x', ['tests.test_a::test_one']], ['y', ['tests.test_a::test_one']]]
    alone = {'tasks': {'bl_A': {'status': 'READY', 'backlog_id': 'A', 'kind': 'code'}}}
    assert Q.audit_after_pass(tmp_path, alone, 'bl_A', {'reason': GATE, 'gate_red': reds}, 'v9', _tests_of) is None
    review = {'reason': 'review: the edit is wrong', 'gate_red': reds}
    assert Q.audit_after_pass(tmp_path, _state(), 'bl_A', review, 'v9', _tests_of) is None
    assert not (tmp_path / 'answers').exists()
