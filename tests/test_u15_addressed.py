"""U15-S9: ``addressed_gate``: the cues read aloud and long talk are not a question; an ask feature in the tail always passes. Quantities, no phrase list."""
import json
import logging
import pathlib

import pytest

from echo_sync import settings as cfg
from echo_sync.classifier import QUESTION, QUIET, Decision
from echo_sync.controlled_media import ControlledMedia
from echo_sync import timer_policy as tp
from echo_sync.timer_policy import unregistered
from echo_sync.utterance_judge import AcceptCtx, JUDGE_RULES, UNKNOWN_ADDRESSED, not_addressed

CUE = ('Активный счёт учитывает имущество организации и обязательства перед контрагентами, остаток по нему показывается в активе баланса, '
       'а оборот по дебету увеличивает сумму, оборот по кредиту уменьшает её, поэтому сальдо активного счёта бывает только дебетовым')
SCENES = pathlib.Path(__file__).parent / 'fixtures' / 'harvest_scenes' / 'scenes.json'


def test_cue_read_back_is_not_addressed():
    found = not_addressed(CUE, [CUE])
    assert found and found[0] == 'read' and found[1] >= cfg.READ_SHARE


def test_an_ask_at_the_end_passes():
    assert not_addressed(CUE + ' а что такое сальдо?', [CUE]) is None


def test_few_words_are_never_read_aloud():
    assert not_addressed('активный счёт баланс', [CUE]) is None


def test_long_talk_without_an_ask_is_not_addressed():
    talk = ' '.join(['вот я сейчас смотрю на экран и вижу, идут секунды в телефоне'] * 3)
    assert not_addressed(talk, [])[0] == 'long'
    assert not_addressed(talk + ' объясни', []) is None


@pytest.mark.skipif(not SCENES.exists(), reason='data outside the repository: tests/fixtures/harvest_scenes/scenes.json (real call scenes of the owner are kept out of git)')
def test_the_request_inside_long_scenes_are_still_answered():
    scenes = [s for s in json.load(open(SCENES, encoding='utf-8'))['scenes'] if s['kind'] == 'request_inside_long']
    assert len(scenes) == 7
    for scene in scenes:
        assert not_addressed(scene['text'], []) is None, scene['id']


def test_settings_and_registry():
    assert 'addressed_gate' not in cfg.resolve({'addressed_gate': 'on'})      # a rule of the judge, not a switch
    assert (cfg.READ_SHARE, cfg.READ_MIN_WORDS, cfg.LONG_READ_WORDS, cfg.ASK_TAIL_WORDS, tp.CONTEXT_AGE_S) == (0.6, 6, 25, 8, 120)
    assert unregistered() == [] and UNKNOWN_ADDRESSED == 'listen' and [r.name for r in JUDGE_RULES if r.after] == ['not_addressed', 'ear_number_veto', 'going_on', 'own_voice', 'held']


class Stub:
    clock = staticmethod(lambda: 100.0)
    said_log = [(50.0, CUE, True), (-100.0, 'очень давняя реплика про налоги и взносы организации', True)]
    ledger = type('L', (), {'snapshot': staticmethod(lambda tid: None), 'history': staticmethod(lambda: [])})()
    _plan_said = staticmethod(lambda: [])
    _read_sources = ControlledMedia._read_sources
    _ruled = ControlledMedia._ruled              # the one place a rule of the judge writes its verdict


def _ctx(text):
    return AcceptCtx({}, 'provider_turn_done', False, '', False, False, False, 't', text, None, decision=Decision(QUESTION, 'question', text, None))


def _run(text, caplog):
    stub = Stub()
    caplog.set_level(logging.INFO)
    ctx = _ctx(text)
    ControlledMedia._rule_not_addressed(stub, ctx)
    return stub, ctx


def test_rule(caplog):
    stub, ctx = _run(CUE, caplog)
    assert ctx.decision.kind == QUIET and ctx.decision.reason == 'not_addressed' and ctx.rule == 'not_addressed' and 'addressed_gate witness=read' in caplog.text
    stub, ctx = _run(CUE + ' а что такое сальдо?', caplog)
    assert ctx.decision.kind == QUESTION and ctx.chain == []


def test_old_cue_is_out_of_the_window(caplog):
    stub, ctx = _run('очень давняя реплика про налоги и взносы организации', caplog)
    assert ctx.decision.kind == QUESTION
