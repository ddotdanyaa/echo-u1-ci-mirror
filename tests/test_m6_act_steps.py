"""M6 (the owner of the sound, slot S3): the gate ``ControlledMedia._act`` runs the steps of a row of ``ACTS`` by the table ``STEPS`` ({verb: fn}); a new row or a new verb is a line of data, the
body of ``_act`` does not change. The cue is made only by the step 'speak' (``_act('speak', 'cue')``); what the wire and the callers ask before a sound ('authorized', 'held', 'may_sound') are steps
of rows too. A row with a verb nobody has defined is the verdict 'unknown' and nothing of it is done. Every test drives the real ControlledMedia through the dictation rig of the other night-gate tests."""
import ast
import inspect
from pathlib import Path

import pytest

import helpers_s6_ack as H
from echo_sync import controlled_media
from echo_sync.controlled_media import ControlledMedia
from echo_sync.settings import CALL_SETTINGS
from cm_patch import controller_modules

ANSWER = 'Налог платят раз в квартал. Ставка составляет шесть процентов. Срок уплаты двадцать пятое число.'


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def call(tmp_path, name='a'):
    return H.Dictation(tmp_path / name, ANSWER, settings=dict(CALL_SETTINGS))


def test_a_toy_row_and_a_toy_verb_make_the_real_controller_act_without_a_line_of_the_gate(tmp_path, monkeypatch):
    c = call(tmp_path).controller
    body = inspect.getsource(ControlledMedia._act)

    def hum(controller, ctx, step):
        ctx['actions'].append({'type': 'hum', 'epoch': controller.epoch, 'by': ctx['by'], 'word': step[1]})

    monkeypatch.setitem(ControlledMedia.STEPS, 'hum', hum)
    monkeypatch.setitem(ControlledMedia.ACTS, 'toy_hum', ('cut_sound', (('hum', 'la'), ('cut',)), True, False))
    c.cue_outstanding = True
    verdict, actions = c._act('cut_sound', 'toy_hum')
    assert verdict == 'do' and actions == [{'type': 'hum', 'epoch': c.epoch, 'by': 'test_a_toy_row_and_a_toy_verb_make_the_real_controller_act_without_a_line_of_the_gate', 'word': 'la'}]
    assert c.cue_outstanding is False, 'the step after the toy verb ran too: the cut'
    assert 'hum' not in body and 'toy' not in body, 'the body of _act names no row and no verb'
    assert inspect.getsource(ControlledMedia._act) == body


def test_a_row_with_a_verb_nobody_defined_is_unknown_and_nothing_of_it_is_done(tmp_path, monkeypatch):
    c = call(tmp_path).controller
    monkeypatch.setitem(ControlledMedia.ACTS, 'toy_unknown', ('close_question', (('epoch', 'provider'), ('clear', ('question_id',)), ('not_a_verb',)), False, False))
    epoch, question = c.epoch, c.question_id
    assert question, 'precondition: a question is open'
    verdict, actions = c._act('close_question', 'toy_unknown')
    assert (verdict, actions) == ('unknown', [])
    assert c.epoch == epoch and c.question_id == question, 'the steps before the unknown verb did not run either: all or nothing'


def test_a_head_step_can_stop_the_entry_before_anything_is_done(tmp_path, monkeypatch):
    c = call(tmp_path).controller

    def veto(controller, ctx, step):
        ctx['stop'] = 'park'
    monkeypatch.setitem(ControlledMedia.STEPS, 'veto', veto)
    monkeypatch.setitem(ControlledMedia.ACTS, 'toy_veto', ('cut_sound', (('veto',), ('epoch', 'provider'), ('wire',)), False, False))
    epoch = c.epoch
    assert c._act('cut_sound', 'toy_veto') == ('park', [])
    assert c.epoch == epoch


def test_the_cue_is_made_by_the_gate_and_nowhere_else(tmp_path, monkeypatch):
    d = call(tmp_path)
    c = d.controller
    real = [a for a in c._cue('Налог платят раз в квартал.') if a['type'] == 'speak']
    assert real and c.authorized(real[0]), 'the real row makes a cue the plan waits for'
    # take the step out of the row: the same call of ``_cue`` makes no sound, so ``_cue`` is no way around the gate
    monkeypatch.setitem(ControlledMedia.ACTS, 'cue', ('speak', (), True, False))
    assert c._cue('Налог платят раз в квартал.') == []
    # and the dict of a cue stands only in the step, in the two shapes of one cue (the replay of the last portion, the plan's own)
    makers = []
    for module in controller_modules():
        for cls in [n for n in ast.parse(Path(module.__file__).read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef)]:
            for node in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                makers += [(module.__name__, node.name) for sub in ast.walk(node) if isinstance(sub, ast.Dict)
                           and any(isinstance(k, ast.Constant) and k.value == 'type' for k in sub.keys) and any(isinstance(v, ast.Constant) and v.value == 'speak' for v in sub.values)]
    assert makers == [('echo_sync.controlled_media', '_step_speak')] * 2, makers


def test_the_questions_before_a_sound_are_rows_of_the_gate(tmp_path, monkeypatch):
    d = call(tmp_path)
    c = d.controller
    cue = [a for a in c._cue('Налог платят раз в квартал.') if a['type'] == 'speak'][0]
    assert c._act('speak', 'authorized', cue=cue) == ('do', []) and c.authorized(cue)
    stale = {**cue, 'epoch': cue['epoch'] - 1}
    assert c._act('speak', 'authorized', cue=stale) == ('stale', []) and not c.authorized(stale), 'a cue of another reply token is not the one'
    # the real rule of the row: a service phrase never sounds over the cue of the open question that is still playing (see the host test below); here nothing plays
    c._cancelled()
    assert c.may_sound('say', (None, None, None)) is True
    # tighten the row of the service phrase: the wire's question now answers no (a rule of the table, no edit of the caller)
    monkeypatch.setitem(ControlledMedia.STEPS, 'quiet', lambda controller, ctx, step: ctx.__setitem__('stop', 'park'))
    monkeypatch.setitem(ControlledMedia.ACTS, 'may_sound', ('speak', (('quiet',),), True, False))
    assert c.may_sound('say', (None, None, None)) is False


def test_a_service_phrase_is_held_while_a_cue_of_the_open_question_plays_and_goes_when_it_has_ended(tmp_path):
    """The one rule of the row ``may_sound`` (it decided nothing before: a stub that said yes): the wire asks it, once, before the first frame of a service phrase (``NativeMediaSocket._sound_gate``)."""
    c = call(tmp_path).controller
    assert c.question_id, 'precondition: a question is open'
    assert c.may_sound('say', (None, None, None)) is True, 'nothing plays: the phrase goes'
    cue = [a for a in c._cue('Налог платят раз в квартал.') if a['type'] == 'speak'][0]
    assert c._cue_playing(c.clock()) and c.cue_outstanding
    assert c._act('speak', 'may_sound', what='say', told=(None, None, None)) == ('park', []) and c.may_sound('say', (None, None, None)) is False, 'the cue plays: the phrase is held'
    assert c.authorized(cue), 'the cue itself is untouched by the rule'
    c._cancelled()
    assert c.may_sound('say', (None, None, None)) is True, 'the cue is cut: the phrase goes again'
    c.cue_outstanding = True
    c.question_id = None
    assert c.may_sound('say', (None, None, None)) is True, 'a cue of no open question is nobody to wait for'


def test_the_wire_holds_the_phrase_through_the_real_sound_gate(tmp_path):
    import asyncio

    async def run():
        w = H.Wire(tmp_path / 'w', settings=dict(CALL_SETTINGS))
        await w.begin(ANSWER)
        c = w.controller
        c.cue_outstanding, c.cue_window = True, [c.clock(), c.clock() + 30]
        held = w.socket._sound_gate((None, None, None))()
        c.cue_outstanding = False
        free = w.socket._sound_gate((None, None, None))()
        await w.close()
        return held, free
    assert asyncio.run(run()) == (False, True)


def test_a_row_that_is_not_of_sound_takes_no_argument_but_basis_and_by_reflex(tmp_path):
    c = call(tmp_path).controller
    epoch, question = c.epoch, c.question_id
    for misspelt in ({'bassis': (None, None, None)}, {'by_reflexx': True}, {'cue': {}}):
        with pytest.raises(TypeError):
            c._act('close_question', 'provider', **misspelt)
    assert c.epoch == epoch and c.question_id == question, 'a refused call did nothing'
    assert c._act('close_question', 'provider', basis=(None, None, None))[0] in ('do', 'stale'), 'the spelt keywords still go'


def test_no_owner_of_another_family_stays_in_the_core():
    """controlled_media.py holds the constructor, the state accessor, the epochs, the table and the gate with its steps, and the shims through which the families ask it: nothing a family decides."""
    tree = ast.parse(Path(controlled_media.__file__).read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ControlledMedia')
    names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    core = {'__init__', 'state', '_act', '_new_epoch', '_cancelled', '_cue', 'authorized', 'held_cue', 'may_sound'}
    extra = {n for n in names if not n.startswith('_step_')} - core
    assert extra == set(), 'a method of a family stands in the core: %s' % sorted(extra)
    assert {n for n in names if n.startswith('_step_')} == {'_step_' + verb for verb in ControlledMedia.STEPS}, 'one function a verb of STEPS, no verb without its function'
    module_functions = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert module_functions == [], 'no module-level decision stays in the core: %s' % module_functions
    # nor an alias that binds a name of the module to what the class decides (``impersonal = ControlledMedia._impersonal`` was one)
    aliases = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign)) and any(isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == 'ControlledMedia' for sub in ast.walk(n))]
    assert aliases == [], 'a module-level name bound to an attribute of ControlledMedia stays in the core: %s' % aliases
