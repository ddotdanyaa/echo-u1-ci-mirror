"""W-tfirst: the solver of a row WITHOUT a red test writes the test first (fake model, fake cloud; no network)."""
import types

import pytest

from tools import factory_architect as A
from tools import factory_hypo as HY
from tools import factory_loop as L
from tools import factory_solver as S

SRC = ('def helper(x):\n    return x + 1\n\n\n'
       'def add(a, b):\n    return helper(a) - b\n')
PATH = 'tests/test_factory_b1_add.py'
ID = PATH + '::test_add_sums'
GOOD = 'from echo_sync.calc import add\n\n\ndef test_add_sums():\n    assert add(1, 2) == 3\n'
PASSING = 'from echo_sync.calc import add\n\n\ndef test_add_sums():\n    assert add(0, 0) == 0\n'
BROKEN = 'from echo_sync.calc import add\n\n\ndef test_add_sums():\n    import missing_thing_zz\n    assert add(1, 2) == 3\n'
MISSING = 'from echo_sync.nope import add\n\n\ndef test_add_sums():\n    assert add(1, 2) == 3\n'
FIX = 'EDIT echo_sync/calc.py\n<<<<<<< SEARCH\n    return helper(a) - b\n=======\n    return a + b\n>>>>>>> REPLACE\n'
RED_TEXT = 'tests/test_factory_b1_add.py:5: in test_add_sums\n    assert add(1, 2) == 3\nE   assert 0 == 3\n'


def newfile(code, path=PATH):
    return 'Test first.\nGIVEN: add exists\nWHEN: 1 and 2 are added\nTHEN: the sum is 3\nNEWFILE %s\n```python\n%s```\n' % (path, code)


@pytest.fixture
def root(tmp_path):
    (tmp_path / 'echo_sync').mkdir()
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'echo_sync' / 'calc.py').write_text(SRC, encoding='utf-8')
    (tmp_path / 'tests' / 'test_calc.py').write_text('def test_other():\n    assert True\n', encoding='utf-8')
    return tmp_path


class Cloud:
    def __init__(self):
        self.calls = []

    def __call__(self, root, ids, files):
        self.calls.append((list(ids), {n: sorted(m) for n, m in files.items()}))
        out = {}
        for n, mapping in files.items():
            code = mapping.get(PATH, '')
            fixed = 'return a + b' in mapping.get('echo_sync/calc.py', SRC) and n != HY.CONTROL
            passed, failed, text = [], [], ''
            for i in ids:
                if i.startswith('@'):
                    passed.append('tests/test_calc.py::test_other')
                elif i == ID and PATH in mapping:
                    if 'add(0, 0)' in code or fixed:
                        passed.append(i)
                    elif 'missing_thing_zz' in code:
                        failed.append(i)
                        text = 'ERROR collecting\nE   ModuleNotFoundError: No module named missing_thing_zz'
                    else:
                        failed.append(i)
                        text = RED_TEXT
                else:
                    failed.append(i)
            out[n] = dict(passed=passed, failed=failed, text=text)
        return out


def ctx_of(root, replies, cloud=None):
    seen = {'prompts': [], 'left': list(replies)}

    def ask(text, small=None):
        seen['prompts'].append(text)
        if not seen['left']:
            raise S.NoChannel('no channel')
        return seen['left'].pop(0)
    c = S.Ctx(root=root, ask=ask, cloud=cloud or Cloud(), sleep=lambda s: None)
    c.seen = seen
    return c


def run(ctx, steps=24):
    return S.solve_row(ctx, 'B1', 'add returns a - b', 'add(1, 2) is 3', ['echo_sync/calc.py :: add'], quotes='sum them', steps=steps)


def test_a_passing_test_is_refused_with_the_reason(root):
    ctx = ctx_of(root, [newfile(PASSING), newfile(GOOD)])
    res = run(ctx)
    assert 'PASSES' in ctx.seen['prompts'][1] and res.test and res.test['code'] == GOOD     # the second try is red and accepted


def test_a_test_with_an_import_error_is_refused_by_the_gate_and_by_the_cloud(root):
    ctx = ctx_of(root, [newfile(MISSING), newfile(BROKEN), 'READ echo_sync/calc.py 1 5'])
    res = run(ctx)
    assert res.test is None and res.status == 'no_channel'
    assert 'does not exist' in ctx.seen['prompts'][1] or 'module' in ctx.seen['prompts'][1]
    assert 'ERROR' in ctx.seen['prompts'][2] and 'not with its own assert' in ctx.seen['prompts'][2]
    assert len(ctx.cloud.calls) == 1                         # the unusable import never reached the cloud


def test_the_product_is_not_edited_before_the_test_is_red(root):
    ctx = ctx_of(root, [FIX, newfile(GOOD)])
    res = run(ctx, steps=2)
    assert 'no red test yet' in ctx.seen['prompts'][1] and res.test and not res.overlay


def test_red_then_fix_then_green_gives_a_contract_of_two_tasks(root):
    ctx = ctx_of(root, ['Look.\nGREP def add :: echo_sync/', newfile(GOOD), FIX])
    res = run(ctx)
    assert res.green and res.test['id'] == ID and 'return a + b' in res.overlay['echo_sync/calc.py']
    final = ctx.cloud.calls[-1]
    assert '@' + PATH in final[0] and 'tests/test_calc.py' not in final[0] and PATH in final[1]['1']
    contract = S.to_contract_tfirst('B1', res, root)
    assert contract['test']['new']['path'] == PATH and contract['test']['new']['code'] == GOOD and 'parts' in contract
    assert contract['test']['new']['given'] == 'add exists' and 'test_only' not in contract
    assert A.validate(contract, root, bid='B1', engine='solver') == []
    tasks = A.to_tasks(contract, bid='B1', base_id='bl_B1', gen=1, priority=1, title='B1')
    assert [t['kind'] for t in tasks] == ['unit_test', 'code'] and tasks[1]['depends_on'] == [tasks[0]['id']]


def test_a_red_test_without_a_green_fix_gives_the_test_task_only(root):
    ctx = ctx_of(root, [newfile(GOOD)])            # then the channel is gone
    res = run(ctx)
    assert not res.green and res.test and res.status == 'no_channel'
    contract = S.to_contract_tfirst('B1', res, root)
    assert contract['test_only'] and contract['parts'] == []
    assert A.validate(contract, root, bid='B1', engine='solver') == []
    tasks = A.to_tasks(contract, bid='B1', base_id='bl_B1', gen=1, priority=1, title='B1')
    assert [t['kind'] for t in tasks] == ['unit_test']
    assert any('red test' in e for e in res.evidence())


def test_the_red_test_is_frozen_and_two_tests_in_a_file_are_refused(root):
    tree = S.Tree(root)
    tree.frozen[PATH] = GOOD
    text, ok = S.do_edit(tree, 'EDIT %s\n<<<<<<< SEARCH\n    assert add(1, 2) == 3\n=======\n    assert True\n>>>>>>> REPLACE\n' % PATH)
    assert not ok and 'frozen' in text
    two = GOOD + '\n\ndef test_second():\n    assert add(2, 2) == 4\n'
    ctx = ctx_of(root, [])
    res = S.Result()
    res.row = 'B1'
    obs = S._new_test(ctx, tree, [], S.parse_newfile(newfile(two)), res)
    assert 'exactly ONE' in obs and not ctx.cloud.calls


def test_the_feeder_takes_rows_without_a_red_test_after_the_red_ones_and_the_solver_first_set_does_not_hold_them():
    stub = types.SimpleNamespace(_hypers={}, _slicers={}, _hypo_skip={}, base_sha='b', HYPO_RETRY_S=L.Loop.HYPO_RETRY_S)
    guard = {'guard': 'tests/t.py::test_a', 'at': 0}
    ls = {'to_slice': {'E1': guard, 'E6': {'at': 0}, 'E7': {'at': 0}, 'fac-3': {'at': 0}, 'rel-ab12-1': {'at': 0}}}
    assert L.Loop._hypo_candidates(stub, {}, {'tasks': {}}, ls, 5.0) == ['E1', 'rel-ab12-1']   # the slicer's rows are not held
    assert L.Loop._hypo_candidates(stub, {}, {'tasks': {}}, ls, 5.0, tfirst=True) == ['E1', 'rel-ab12-1', 'E6', 'E7']
    stub._hypers['E6'] = object()                         # a row under a solve is not taken by the slicing (as before)
    assert L.Loop._hypo_candidates(stub, {}, {'tasks': {}}, ls, 5.0, tfirst=True) == ['E1', 'rel-ab12-1', 'E7']
