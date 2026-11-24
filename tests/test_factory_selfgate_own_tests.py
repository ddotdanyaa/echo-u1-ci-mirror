"""The second instance may edit an existing factory test file in a code card (contract, plan scope, gate), and only without
weakening it: the number of test functions and of asserts never goes down. The product instance never may."""
import json

import pytest

from tools import agent_factory as F
from tools import factory_architect as A
from tools import factory_gate as G

TEST = 'tests/test_factory_widget.py'
BASE = ('def test_one():\n    assert 1 == 1\n    assert 2 == 2\n\n\n'
        'def test_two():\n    assert 3 == 3\n')


def _root(tmp_path, text=BASE):
    (tmp_path / 'tests').mkdir(exist_ok=True)
    (tmp_path / TEST).write_text(text, encoding='utf-8')
    return tmp_path


def test_a_factory_test_is_open_to_a_code_card_only_for_the_second_instance_and_only_when_named():
    assert G.is_forbidden(TEST, 'code', named=[TEST], own_tests=True) is None
    assert 'unit_test' in G.is_forbidden(TEST, 'code', named=[TEST], own_tests=False)
    assert 'unit_test' in G.is_forbidden(TEST, 'code', named=[], own_tests=True)               # not named: closed
    assert 'unit_test' in G.is_forbidden('tests/test_other_thing.py', 'code', named=['tests/test_other_thing.py'], own_tests=True)
    assert G.is_forbidden('tests/conftest.py', 'code', named=['tests/conftest.py'], own_tests=True)
    assert 'unit_test' in G.is_forbidden(TEST, 'code', named=[TEST])                            # the process flag is off by default


def test_the_process_flag_of_the_second_instance_opens_it_too(monkeypatch):
    monkeypatch.setattr(G, 'SELF_REPO', True)
    assert G.is_forbidden(TEST, 'code', named=[TEST]) is None
    assert 'unit_test' in G.is_forbidden(TEST, 'code', named=[TEST], own_tests=False)           # an explicit no wins


def test_an_edit_of_the_test_that_keeps_every_test_and_assert_is_clean(tmp_path):
    root = _root(tmp_path)
    more = BASE + '\n\ndef test_three():\n    assert 4 == 4\n'
    assert G.weakening_violations(root, {TEST: more}, 'code', [TEST], True) == []
    assert G.weakening_violations(root, {TEST: BASE.replace('3 == 3', '5 == 5')}, 'code', [TEST], True) == []


@pytest.mark.parametrize('text, word', [
    (BASE.replace('    assert 2 == 2\n', '    pass\n'), 'checks'),                              # an assert fewer
    (BASE.split('def test_two')[0], 'tests removed'),                                          # a test function fewer
    ('import pytest\n\n\n' + BASE.replace('def test_two', '@pytest.mark.skip\ndef test_two'), 'markers'),
    (BASE + '\ndef broken(:\n', 'does not parse'),
])
def test_a_weaker_edit_of_the_test_is_refused(tmp_path, text, word):
    root = _root(tmp_path)
    found = G.weakening_violations(root, {TEST: text}, 'code', [TEST], True)
    assert found and any(word in line for line in found), found


def test_the_product_instance_and_a_missing_test_file_are_refused(tmp_path):
    root = _root(tmp_path)
    assert any('unit_test' in line for line in G.weakening_violations(root, {TEST: BASE}, 'code', [TEST], False))
    fresh = 'tests/test_factory_brand_new.py'
    found = G.weakening_violations(root, {fresh: BASE}, 'code', [fresh], True)
    assert found and 'existing' in found[0]


def _contract(root, **extra):
    parts = [{'file': TEST, 'symbols': ['test_one'], 'anchor': '', 'stage': 1,
              'instruction': 'Make the existing test importable from the cloud mirror: keep its asserts and add nothing else.'}]
    return {'decision': 'fix', 'parts': parts, 'test': {'use': TEST + '::test_one'}, **extra}


def test_the_contract_of_the_second_instance_may_name_an_existing_factory_test(tmp_path):
    root = _root(tmp_path)
    mine = _contract(root)
    assert A.validate(mine, root, named_ok=True) == []
    assert mine['own_test_edit'] is True                      # the plan reads it back
    theirs = _contract(root)
    faults = A.validate(theirs, root, named_ok=False)
    assert any('tests/**' in fault for fault in faults) and 'own_test_edit' not in theirs


def _row(contract, **kw):
    row = {'id': 'fac_t', 'title': 'x', 'touch_files': [TEST], 'tests': [TEST], 'kind': 'code', 'depends_on': [],
           'contract': json.dumps(contract)}
    row.update(kw)
    return row


def test_the_plan_lets_the_scope_of_such_a_card_meet_its_test_and_no_other_card(tmp_path):
    marked = {'decision': 'fix', 'own_test_edit': True}
    assert 'fac_t' in F.read_plan({'tasks': [_row(marked)]})
    with pytest.raises(F.InvalidPlan):
        F.read_plan({'tasks': [_row({'decision': 'fix'})]})                                    # no mark: as before
    other = 'tests/test_not_a_factory_one.py'
    with pytest.raises(F.InvalidPlan):
        F.read_plan({'tasks': [_row(marked, touch_files=[other], tests=[other])]})             # the mark opens factory tests only
    with pytest.raises(F.InvalidPlan):
        F.read_plan({'tasks': [dict(_row(marked), contract='not json')]})
