"""U15-S11: first match by priority is the only order of the judge (the key ``judge_order`` is gone), one analyze per resolution."""
from echo_sync import settings as cfg
from echo_sync.classifier import ACK, QUESTION, QUIET, Decision
from echo_sync.controlled_media import ControlledMedia
from echo_sync.utterance_judge import AcceptCtx, diff_hash, first_match


def _ctx(analyses=1):
    ctx = AcceptCtx({'id': 't'}, 'provider_turn_done', False, '', False, False, False, 't', 'text', None, decision=Decision(QUESTION, 'question', 'text', None))
    ctx.analyses = analyses
    return ctx


def _spoken(*rules):
    """A context where each named rule changed the verdict in turn: kind QUIET, then ACK, then QUESTION."""
    ctx = _ctx(analyses=3)
    for rule, kind in zip(rules, (QUIET, ACK, QUESTION)):
        ctx.decision = Decision(kind, rule, None, None)
        ctx.spoke(rule)
    return ctx


def test_there_is_one_order_and_no_key_for_it():
    assert 'judge_order' not in cfg.DEFAULTS and 'judge_order' not in cfg.resolve({'judge_order': 'off'}) and not hasattr(ControlledMedia, '_judge_order')


def test_first_match_is_the_first_rule_that_spoke():
    ctx = _spoken('gate_talk', 'read_again')
    step = first_match(ctx)
    assert step[0] == 'gate_talk' and step[1].kind == QUIET
    assert first_match(_ctx()) is None


def test_diff_list_hash_is_stable_and_order_free():
    rows = [('b', 'ack/x', 'quiet/y'), ('a', 'question/q', 'quiet/g')]
    assert diff_hash(rows) == diff_hash(list(reversed(rows))) and len(diff_hash(rows)) == 16
    assert diff_hash(rows) != diff_hash(rows[:1])


def test_a_step_with_no_verdict_is_skipped():
    ctx = _ctx(analyses=1)
    ctx.decision = None
    ctx.spoke('no_to_the_cue')
    ctx.decision = Decision(QUESTION, 'question', 'text', None)
    assert first_match(ctx) is None


def test_not_addressed_is_a_veto_outside_the_table():
    ctx = _spoken('gate_talk')
    ctx.decision = Decision(QUIET, 'not_addressed', None, None)
    ctx.spoke('not_addressed')
    assert first_match(ctx)[0] == 'gate_talk'
