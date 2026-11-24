"""U15-S1: ``_accept_user`` is staged: ``AcceptCtx`` + ordered ``_rule_*`` (``JUDGE_RULES``). A pure move: the verdict is what it was; the new thing is ONE ``echo-sync judge``
line per judged final that names the rule that decided, the chain of rules that spoke and the number of ``analyze`` calls."""
import logging
import re

import pytest

from echo_sync.controlled_media import ControlledMedia
from echo_sync.utterance_judge import JUDGE_RULES, RULE_NAMES, AcceptCtx
from test_stable_partial_ack import Speaker, dictation


def judge_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync judge ')]


def fields(line):
    return dict(re.findall(r'(\w+)=(\S+)', line))


def ask(tmp_path, caplog, said):
    caplog.set_level(logging.INFO)
    d = dictation(tmp_path / 'j')
    s = Speaker(d).start().words(said)
    s.wait(0.8)
    caplog.clear()
    s.final()
    return d, judge_lines(caplog)


def test_every_rule_in_the_order_has_a_method():
    assert JUDGE_RULES[0].name == 'recall', 'the hook position of U14-S6 is the first'
    assert len(set(RULE_NAMES)) == len(JUDGE_RULES)
    for rule in JUDGE_RULES:
        assert callable(rule.fn) and (hasattr(ControlledMedia, '_rule_' + rule.name) or rule.fn.__name__ != 'row_' + rule.name), rule.name      # a row is a controller method, or a function of its own


def test_the_hook_position_says_nothing():
    ctx = AcceptCtx({}, 'provider_turn_done', False, '', False, False, False, 't', 'x', None)
    ControlledMedia._rule_recall(None, ctx)
    assert ctx.chain == [] and ctx.rule == 'base' and ctx.analyses == 0


def test_chain_names_the_rule(tmp_path, caplog):
    d, lines = ask(tmp_path, caplog, 'а почему вода кипит при ста градусах?')
    assert len(lines) == 1, lines
    f = fields(lines[0])
    assert int(f['analyses']) >= 1
    chain = [] if f['chain'] == '-' else f['chain'].split('>')
    assert all(name in RULE_NAMES for name in chain)
    assert f['rule'] == (chain[-1] if chain else 'base'), 'the rule named is the last that spoke (last wins)'


def test_the_chain_lists_the_rules_in_the_order_they_spoke():
    ctx = AcceptCtx({}, 'provider_turn_done', False, '', False, False, False, 't', 'x', None)
    ctx.decision = type('D', (), {'kind': 'quiet', 'reason': 'gate_talk'})()
    ctx.spoke('bank_question')
    ctx.spoke('gate_talk')
    ctx.analyses = 2
    assert ctx.rule == 'gate_talk'
    assert ctx.line() == 'echo-sync judge tid=t kind=quiet reason=gate_talk rule=gate_talk chain=bank_question>gate_talk analyses=2'


def test_a_command_is_judged_once_too(tmp_path, caplog):
    d, lines = ask(tmp_path, caplog, 'стоп')
    assert len(lines) == 1, lines
    assert fields(lines[0])['kind'] == 'stop'
