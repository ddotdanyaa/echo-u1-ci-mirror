"""Lane A (13.11, map §8.4, step 5 of §8.5): the lock on the QUANTITY of places that decide «the waiting portion yields».

``ControlledMedia._question_fate`` (door 'asleep') is the one owner. The census below is of the source as it stands (``cm_patch.controller_source``, so the lock
does not go blind when the controller is cut into ``cm_*`` modules). Counting calls of the base ``v7-main`` (c1d2434, 13.11): one
``_abandons`` call, one ``_abandon`` call, one ``_act(.., 'abandon')``, one redo. A new place that retires the portion fails here: the test
lists no phrase and no case, it counts.
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import cm_patch      # noqa: E402

from echo_sync import timer_policy as tp      # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / 'echo_sync'

# the base v7-main c1d2434 (13.11): where each is, and how many
BASE_ABANDONS_CALLS = {'_accept_user': 1}      # 16.11: the door 'asleep' of the one decider ``_question_fate``
BASE_ABANDON_CALLS = {'_accept_user': 1}      # ... and the one closing ``_end_question`` that its CLOSE verdict asks for
BASE_REDO = {'_accept_user': 1}
BASE_CAPPED_WRITES = {'tick': 1}
ONLY_IN_ABANDONS = ('ABANDON_SHARE', 'ABANDON_FINALS', '_MOVED_ON')


def functions(tree):
    """Every function and method of ``tree`` with its (innermost) name."""
    return [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def own_nodes(function):
    """The nodes of ``function`` itself: not those of the functions nested in it."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


@pytest.fixture(scope='module')
def tree():
    return ast.parse(cm_patch.controller_source())


def where(tree, wanted):
    """``{function name: how many nodes}`` for the nodes of ``tree`` that ``wanted(node)`` accepts."""
    found = {}
    for function in functions(tree):
        count = sum(1 for node in own_nodes(function) if wanted(node))
        if count:
            found[function.name] = found.get(function.name, 0) + count
    return found


def method_call(name):
    return lambda node: (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name
                         and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self')


def test_one_owner_decides_the_portion_yields(tree):
    """A9: one call each of the owner, of what it does, and of the second judgement; nothing else retires a waiting portion."""
    asleep = lambda n: method_call('_question_fate')(n) and any(isinstance(a, ast.Constant) and a.value == 'asleep' for a in n.args)
    assert where(tree, asleep) == BASE_ABANDONS_CALLS
    assert where(tree, method_call('_end_question')) == {'_accept_user': 1, '_begin_call': 1}      # the abandon and the new call close through the one executor
    assert not where(tree, method_call('_abandons')) and not where(tree, method_call('_abandon'))      # the old two places are gone
    assert where(tree, lambda n: isinstance(n, ast.keyword) and n.arg == 'cause' and isinstance(n.value, ast.Constant) and n.value.value == 'redo') == BASE_REDO


def test_the_clock_is_read_in_two_places_only(tree):
    assert not where(tree, lambda n: isinstance(n, ast.Attribute) and n.attr == 'abandon_seconds')      # the attribute is gone: the constant of timer_policy is read in the one place
    for name in ('ABANDON_SECONDS',) + ONLY_IN_ABANDONS:
        assert set(where(tree, lambda n, name=name: isinstance(n, ast.Name) and n.id == name)) == {'_question_fate'}, name


def test_the_cap_mark_is_written_by_the_timer_only(tree):
    """``self.abandon['capped'] = ..`` (a literal dict with the key does not count: it only starts a mark)."""
    def store(node):
        return (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) and isinstance(node.slice, ast.Constant) and node.slice.value == 'capped'
                and isinstance(node.value, ast.Attribute) and node.value.attr == 'abandon')
    assert where(tree, store) == BASE_CAPPED_WRITES


def test_the_feature_is_read_in_one_place_and_defined_once():
    calls, defined = {}, 0
    for path in sorted(ROOT.glob('*.py')):
        module = ast.parse(path.read_text(encoding='utf-8'))
        for function in functions(module):
            if function.name == 'portion_share' and path.name == 'classifier.py':
                defined += 1
            hits = sum(1 for node in own_nodes(function) if isinstance(node, ast.Call) and getattr(node.func, 'id', getattr(node.func, 'attr', None)) == 'portion_share')
            if hits:
                calls[(path.name, function.name)] = hits
    assert defined == 1
    assert calls == {('cm_probes.py', '_portion_share'): 1}, calls      # the one row of the probe registry (M7/S1) that reports the feature; the portion owner's rule (cm_question._question_fate) asks the registry


def test_the_owner_reads_no_word_of_the_text_itself(tree):
    """The old test of the owner was a list of what looked like a try (a common stem, a number to a number); the new one is a share (a feature)."""
    owner = next(f for f in functions(tree) if f.name == '_question_fate')
    names = {n.id for n in own_nodes(owner) if isinstance(n, ast.Name)} | {n.func.attr for n in own_nodes(owner) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not names & {'_stems', '_holds_a_number', 'cue_window'}, names
    asked = {n.args[0].value for n in own_nodes(owner) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'probe' and n.args and isinstance(n.args[0], ast.Constant)}
    assert 'portion_share' in asked and 'portion_share' not in names and '_plan_mark' in names      # the owner asks the registry (cm_probes), it does not call the classifier


def test_the_g3_clock_and_the_asleep_clock_are_one(tree):
    """A10: of the places that need «when was the plan cued» only ``_plan_mark`` reads ``cue_window``; R12 binds the two clocks."""
    readers = where(tree, lambda n: isinstance(n, ast.Attribute) and n.attr == 'cue_window')
    for name in ('_question_fate', '_plan_stands'):
        assert name not in readers, (name, readers)
    assert '_plan_mark' in readers
    assert not [v for v in tp.validate({}) if v.rule == 'R12']


def test_r12_catches_a_portion_that_outlives_the_plan(monkeypatch):
    monkeypatch.setattr(tp, 'ABANDON_SECONDS', tp.PLAN_BACK_SECONDS + 1.0)
    assert [(v.rule, v.hard) for v in tp.validate({}) if v.rule == 'R12'] == [('R12', True)]
