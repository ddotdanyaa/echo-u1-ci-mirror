"""g36: what the call must do with no cloud at all (tools/replay/no_cloud.py: the rules NC1-NC7, the scenes, the checker).

Three runs of one rehearsal (a bank question, a repeat, a stumble, a law question, an unknown question, the cloud back, a bank question):
  cloud    the cloud hears and announces the turns as usual: the reference, every rule holds (else the scene or the checker is wrong, not the product)
  deaf     the helper is open and nothing comes back from it: what the controller can do alone
  refused  the helper cannot be opened (06.11 12:43, ``handshake operation timed out``): the call must still open and work on the laptop's own parts
c22-nocloud: every rule is kept now (the profile's ``local_fallback`` = "on" is on in the scenes, ``PROFILE`` of no_cloud.py): the xfail marks of g36 are gone.
The text model is unreachable in all three (no network). ``controlled_host.py`` is not touched here.
"""
import functools
import logging

import pytest

from tools.replay import no_cloud as N


@functools.lru_cache(maxsize=None)
def scene(mode, model='fail', script='standard'):
    logging.disable(logging.WARNING)
    try:
        return N.run(mode, getattr(N, script), length=60.0 if script == 'standard' else 30.0, model=model)
    finally:
        logging.disable(logging.NOTSET)


def broken(rec, rule):
    return [v for v in rec.violations if v[0] == rule]


def kept(rec, rule):
    assert not broken(rec, rule), N.describe(rec)


# --- the checker itself: the rules are not empty -----------------------------------------------------------------------------------

def test_honest_is_a_short_i_do_not_know_and_never_the_channel_phrase_or_a_figure():
    assert N.honest('Не знаю точно.') and N.honest('Нет ответа. Повторите вопрос.') and N.honest('Нет связи, ответа нет.')
    assert not N.honest(N.CHANNEL), 'the channel phrase is NC7\'s, it tells nothing about the question'
    assert not N.honest('Не знаю, наверное 20 процентов.') and not N.honest('Статья 80 — налоговая декларация.') and not N.honest('')


def test_the_checker_flags_silence_lateness_a_wrong_start_and_an_invented_answer():
    line = N.Line('ask', 'q', 'q', 1.0, 2.0, want='bank', answer='Имущество без физической формы; его стоимость переносят амортизацией.')
    unknown = N.Line('ask', 'u', 'u', 10.0, 11.0, want='unknown')
    silent = N.Record('refused', lines=[line, unknown], opened=True)
    assert [v[0] for v in N.check(silent)] == ['NC2', 'NC4']
    late = N.Record('refused', lines=[line], opened=True, cues=[(4.0, 'Имущество без физической формы;', 1, 0, (), False, False)])
    assert 'began' in N.check(late)[0][2]
    wrong = N.Record('refused', lines=[line], opened=True, cues=[(2.5, 'Патенты, товарные знаки', 1, 0, (), False, False)])
    assert 'not the start' in N.check(wrong)[0][2]
    invented = N.Record('refused', lines=[unknown], opened=True, cues=[(12.0, 'Её зовут Жучка.', 1, 0, (), False, False)])
    assert [v[0] for v in N.check(invented)] == ['NC4', 'NC4'], 'an invented answer, and still no honest phrase'
    twice = N.Record('refused', opened=True, cues=[(0.0, N.CHANNEL, None, None, (), False, True), (5.0, N.CHANNEL, None, None, (), False, True)])
    assert [v[0] for v in N.check(twice)] == ['NC7']
    assert [v[0] for v in N.check(N.Record('refused'))] == ['NC1']


# --- the reference: with the cloud the scene and the checker agree with the product ------------------------------------------------

def test_with_the_cloud_every_rule_holds():
    rec = scene('cloud')
    assert not rec.violations, N.describe(rec)
    assert [l.kind for l in sorted(rec.lines, key=lambda l: l.onset)] == ['ask', 'repeat', 'stumble', 'ask', 'ask', 'ask'], 'the scene is played whole'


# --- deaf: the helper is open, nothing comes back ------------------------------------------------------------------------------------

def test_deaf_a_bank_question_is_answered():
    kept(scene('deaf'), 'NC2')


def test_deaf_a_law_question_is_answered():
    kept(scene('deaf'), 'NC3')


def test_deaf_an_unknown_question_gets_one_honest_phrase():
    kept(scene('deaf'), 'NC4')


def test_deaf_the_outage_is_told_at_most_once():
    kept(scene('deaf'), 'NC7')


def test_deaf_a_repeat_moves_on_and_a_stumble_is_prompted_from_its_word():
    kept(scene('deaf'), 'NC5')


@pytest.mark.parametrize('mode', ['cloud', 'deaf'])
def test_a_stumble_is_prompted_from_the_word_where_it_stopped(mode):
    rec = scene(mode, script='stumbles')
    assert [l.kind for l in rec.lines if l.kind == 'stumble'], N.describe(rec)
    kept(rec, 'NC5')


# --- refused: the helper cannot be opened (06.11) ------------------------------------------------------------------------------------

def test_refused_the_call_opens():
    kept(scene('refused'), 'NC1')


def test_refused_a_bank_question_is_answered_without_waiting_for_a_cloud_that_is_not_there():
    kept(scene('refused'), 'NC2')


def test_refused_a_law_question_is_answered():
    kept(scene('refused'), 'NC3')


def test_refused_an_unknown_question_gets_one_honest_phrase_at_once():
    kept(scene('refused'), 'NC4')


def test_refused_a_repeat_and_a_stumble_work_as_usual():
    kept(scene('refused'), 'NC5')
    kept(scene('refused', script='stumbles'), 'NC5')


def test_refused_the_cloud_coming_back_does_not_restart_the_call():
    kept(scene('refused'), 'NC6')
    back = scene('refused').back
    assert back['source'] and back['after_controller'] == back['controller'] and back['after_wire'] == back['wire']


def test_refused_the_outage_is_told_at_most_once():
    rec = scene('refused')
    kept(rec, 'NC7')
    assert rec.errors.count('controlled_upstream_unavailable') == 1


def test_refused_a_text_model_that_hangs_does_not_hold_the_honest_phrase():
    """No network: the text model's request may hang (a handshake that times out) instead of failing at once; the unknown question is told within the bound all the same."""
    rec = scene('refused', 'hang')
    kept(rec, 'NC4')
    kept(rec, 'NC2')
