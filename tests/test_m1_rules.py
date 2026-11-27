"""M1 (ARCH_ONE): the judge of an utterance is ONE table of rows (``utterance_judge.JUDGE_RULES``, one ``Rule`` per kind verdict) walked by ``ControlledMedia._judge``, which decides nothing itself.
This file holds the three promises of the table: every row has scenes where it speaks and scenes where it does not, and the scenes are run through the REAL ControlledMedia; a row added in a test changes
the verdict of a call without ``_judge`` being edited; the names a verdict carries are one closed registry (``reasons``)."""
import ast
import json
import logging
import re
from pathlib import Path

import pytest

import helpers_night_memory as M
from echo_sync import reasons, utterance_judge as J
from echo_sync.classifier import QUIET, QUESTION, Decision
from echo_sync.controlled_media import ControlledMedia

ROOT = Path(__file__).resolve().parents[1]
ANSWER = 'Первая часть ответа про инерцию. Вторая часть ответа про силу. Третья часть ответа про массу.'
RIG_ANSWER = 'Основная ставка налога на доходы составляет 13 процентов. Пособие по беременности не облагается налогом. Декларацию подают до тридцатого апреля.'
RIG_FIRST = 'основная ставка налога на доходы составляет 13 процентов'
ROWS = {row['id']: row for row in json.loads((Path(__file__).resolve().parent / 'fixtures' / 'brain_eval_n2.json').read_text(encoding='utf-8'))['rows']}
FEATURES = ('disputed', 'going', 'text')      # what a row may change besides the verdict: read to tell that it spoke


def watched(fired, table=None):
    """The table with every row wrapped: a row ``speaks`` when the verdict, the text, the plan of going on, the dispute flag or the controller's own marks differ after it ran, or it returned a verdict."""
    def mark(c):
        cm = c.cm
        return (id(c.decision), c.going, c.disputed, c.text, getattr(cm, 'go_on', None), id(getattr(cm, 'suspended', None)), id(getattr(cm, 'fast_mark', None)), len(c.chain), id(c.taken), c.hold)

    def wrap(rule):
        def fn(c):
            before = mark(c)
            out = rule.fn(c)
            if out is not None or mark(c) != before:
                fired.append(rule.name)
            return out
        return J.Rule(rule.name, fn, rule.pos_examples, rule.neg_examples, rule.after)
    return tuple(wrap(rule) for rule in (table or J.JUDGE_RULES))


def spoken(monkeypatch, name, scene, tmp_path):
    """Run ``scene`` and tell whether the row ``name`` spoke for its last final. ``('test', ...)`` scenes are proven by the named test (see ``test_a_named_test_exists``)."""
    fired = []
    monkeypatch.setattr(J, 'JUDGE_RULES', watched(fired))
    kind = scene[0]
    logging.disable(logging.CRITICAL)
    try:
        if kind in ('call', 'corpus'):
            if kind == 'call':
                before, text, extras = scene[1], scene[2], (scene[3] if len(scene) > 3 else {})
            else:
                row = ROWS[scene[1]]
                before, text, extras = [c['text'] for c in row['context'] if c['kind'] != 'answer'][-2:], row['text'], {}
            call = M.Call(tmp_path, mind=lambda request: ANSWER, fast_text='on', **extras.get('profile', {}))
            try:
                for said in before:
                    call.say(said)
                    call.pump(1.0)
                for key, value in extras.get('set', {}).items():
                    setattr(call.c, key, dict(value))
                fired.clear()
                call.say(text)
            finally:
                call.close()
        else:
            from tools.replay import repeat_scenes as R
            rig = R.make_rig({'repeat_rule': 'on', 'dictation': 'on'} if scene[1] == 'dict' else {})
            try:
                rig.asks('q1', 'Какая ставка налога на доходы физических лиц?', 0, RIG_ANSWER)
                rig.pump(0.5)
                if scene[1] == 'dict':
                    R.utter(rig, RIG_FIRST)
                    rig.pump(2.0)
                for said in scene[2][:-1]:
                    R.utter(rig, said)
                    rig.pump(0.5)
                fired.clear()
                R.utter(rig, scene[2][-1])
                rig.pump(1.0)
            finally:
                rig.close()
                rig._mp.undo()
    finally:
        logging.disable(logging.NOTSET)
    return name in fired


def examples(side):
    return [pytest.param(rule.name, scene, id='%s-%s-%d' % (rule.name, side, n))
            for rule in J.JUDGE_RULES for n, scene in enumerate(getattr(rule, side + '_examples')) if scene[0] != 'test']


def test_the_table_is_rows_with_examples_on_both_sides():
    names = [rule.name for rule in J.JUDGE_RULES]
    assert len(names) == len(set(names)) == len(J.RULE_NAMES) and names[0] == 'recall'
    for rule in J.JUDGE_RULES:
        assert isinstance(rule, J.Rule) and callable(rule.fn)
        assert rule.pos_examples and rule.neg_examples, rule.name + ': a row without a scene where it speaks and one where it does not'
        assert all(scene[0] in ('call', 'rig', 'corpus', 'test') for scene in rule.pos_examples + rule.neg_examples), rule.name
    assert [rule.name for rule in J.JUDGE_RULES if rule.after] == ['not_addressed', 'ear_number_veto', 'going_on', 'own_voice', 'held']


@pytest.mark.parametrize('name,scene', examples('pos'))
def test_a_row_speaks_where_its_scene_says(monkeypatch, tmp_path, name, scene):
    assert spoken(monkeypatch, name, scene, tmp_path), (name, scene)


@pytest.mark.parametrize('name,scene', examples('neg'))
def test_a_row_is_silent_where_its_scene_says(monkeypatch, tmp_path, name, scene):
    assert not spoken(monkeypatch, name, scene, tmp_path), (name, scene)


def named_tests():
    return [pytest.param(rule.name, scene[1], id='%s-%s' % (rule.name, scene[1].split('::')[1][:40]))
            for rule in J.JUDGE_RULES for scene in rule.pos_examples + rule.neg_examples if scene[0] == 'test']


@pytest.mark.parametrize('name,node', named_tests())
def test_a_named_test_exists(name, node):
    """A state the row needs (the ear, a veto, coalescing) is built by an existing test that drives the real controller: it has to be there, and ``TESTS`` of the packet lists its file."""
    path, func = node.split('::')
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    assert any(isinstance(item, ast.FunctionDef) and item.name == func for item in ast.walk(tree)), node


def test_a_row_added_in_a_test_changes_the_verdict_and_the_judge_is_not_edited(monkeypatch, tmp_path, caplog):
    """The toy row speaks for one phrase only: the verdict of the call is its verdict and the judge line names it. The walker (``_judge``) is the one of the product."""
    def toy(c):
        return Decision(QUIET, 'toy_reason', None, None) if 'тестовая фраза' in c.text else None
    toy_row = J.Rule('toy', toy, (('call', (), 'тестовая фраза про инерцию?'),), (('call', (), _plain()),))
    rows = list(J.JUDGE_RULES)
    rows.insert([row.name for row in rows].index('long_talk'), toy_row)
    monkeypatch.setattr(J, 'JUDGE_RULES', tuple(rows))
    caplog.set_level(logging.INFO)
    call = M.Call(tmp_path, mind=lambda request: ANSWER, fast_text='on')
    try:
        tid = call.say('тестовая фраза про инерцию?')
        plain = call.say('Что такое сила?')
    finally:
        call.close()
    rows = lambda who: [dict(re.findall(r'(\w+)=(\S+)', r.getMessage())) for r in caplog.records if r.getMessage().startswith('echo-sync judge ') and ('tid=%s ' % who) in r.getMessage()]
    assert rows(tid) and rows(tid)[-1]['kind'] == QUIET and rows(tid)[-1]['reason'] == 'toy_reason' and rows(tid)[-1]['rule'] == 'toy', rows(tid)
    assert rows(plain) and rows(plain)[-1]['kind'] == QUESTION and rows(plain)[-1]['rule'] != 'toy', rows(plain)
    assert 'toy' not in __import__('inspect').getsource(ControlledMedia._judge)


def _plain():
    return 'Что такое сила?'


def test_the_names_of_a_verdict_are_one_closed_registry():
    from echo_sync import classifier
    kinds = {classifier.ACK, classifier.REPEAT, classifier.STOP, classifier.QUESTION, classifier.REPLAY, classifier.QUIET, classifier.GREETING, classifier.CORRECTION,
             classifier.CLARIFY_REPAIR, classifier.RESUME, classifier.NEXT}
    assert set(reasons.KINDS) == kinds
    assert len(reasons.REVISE_CAUSES) == 7 and set(reasons.REVISE_CAUSES) == {'cloud_final', 'early_tail', 'ear_take', 'ear_overruled', 'redo', 'resume', 'local_ear'}
    assert not set(reasons.REVISE_CAUSES) & set(reasons.FIRST_CAUSES)
    assert set(reasons.REASONS) == {'kind', 'revise', 'first'} and J.REVISE_CAUSES is reasons.REVISE_CAUSES


def test_resolve_reads_the_registry():
    records = J.Resolutions()
    assert records.resolve('t1', resolution='question', cause='cloud_final')[1] == 'new'
    assert records.resolve('t1', resolution='silent', cause='cloud_final')[1] == 'revised'      # a named cause of the closed list
    assert records.resolve('t1', resolution='question', cause='stable_partial')[1] == 'untyped'      # a first-look name is no reason to revise
    rec, outcome = records.resolve('t2', resolution='no_such_kind')
    assert outcome == 'unknown_kind' and records.unknown_kinds == 1 and 't2' not in records.records
