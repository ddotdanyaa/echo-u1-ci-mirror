"""M5 (timers): the registry of the call's time is ``timer_policy``; the tick reads it. What this file holds:
  * a toy deadline put into ``timer_policy.DEADLINES`` fires through ``ControlledMedia`` without a line of ``cm_timers`` knowing it;
  * no literal second outside ``timer_policy`` that was not there at P08 (a ratchet), the waits have a reason or a limit, an unmeasured number says so.
"""
import pathlib


import helpers_s6_state as S
from echo_sync import controlled_host, loop_guard, timer_policy as tp
from test_h3_tempo import call      # noqa: F401 - the fixture

ECHO = pathlib.Path(tp.__file__).parent


def answered(rig, question='Сколько будет сорок на два', answer='Восемьдесят. Это ответ.'):
    rig.w.feed(S.turn_created('u1', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u1', 'user', question))
    rig.w.feed(S.turn_done('a1', 'assistant', answer))
    return rig.c


# --- the toy deadline: a row in the registry, nothing in the owner ------------------------------------------------------------------------

def test_a_toy_deadline_fires_through_the_controller_without_editing_the_timers_module(call, monkeypatch):
    c = answered(call())
    fired = []

    def fire(now):
        fired.append(now)
        return [{'type': 'speak', 'text': 'toy'}]
    c.toy_armed, c.toy_fire = c.clock(), fire
    monkeypatch.setitem(tp.DEADLINES, 'toy', tp.Deadline('toy_armed', 2.0, 'toy_fire'))
    assert 'toy' not in (ECHO / 'cm_timers.py').read_text(encoding='utf-8')
    assert c._deadlines_due(c.clock() + 1.9) == [] and fired == []
    got = c._deadlines_due(c.clock() + 2.0)
    assert got and got[0]['text'] == 'toy' and len(fired) == 1
    assert c.toy_armed is None and c._deadlines_due(c.clock() + 99) == [] and len(fired) == 1, 'it fires once: disarmed first'


def test_a_deadline_reads_its_seconds_from_the_registry_key(call, monkeypatch):
    c = answered(call())
    c.toy_armed, c.toy_fire = c.clock(), lambda now: ['x']
    monkeypatch.setitem(tp.DEADLINES, 'toy', tp.Deadline('toy_armed', 'timer_policy.ANSWER_WAIT_SECONDS', 'toy_fire'))
    assert c._deadlines_due(c.clock() + tp.value('timer_policy.ANSWER_WAIT_SECONDS') - 0.1) == []
    assert c._deadlines_due(c.clock() + tp.value('timer_policy.ANSWER_WAIT_SECONDS')) == ['x']


# --- U20: the registry ---------------------------------------------------------------------------------------------------------------------

def test_no_new_literal_second_outside_the_registry():
    """A number of seconds written into a call (timeout=, sleep, wait_for, ``*_seconds=`` defaults) is a deadline the table does not know. The count per file is the P08 census and only goes down: pay one, strike it from LITERAL_DEBT."""
    assert tp.literal_debt() == tp.LITERAL_DEBT, [x for x in tp.literal_seconds()]


def test_the_scan_sees_a_literal_second(tmp_path, monkeypatch):
    (tmp_path / 'x.py').write_text('import asyncio\nasync def f(q):\n    await asyncio.wait_for(q.get(), 7)\n    q.get(timeout=3)\n    asyncio.sleep(0)\ndef g(idle_s=60.0): pass\n', encoding='utf-8')
    monkeypatch.setattr(tp, '_DIR', tmp_path)
    assert sorted((site, v) for _, _, site, v in tp.literal_seconds()) == sorted([('wait_for(arg)', 7), ('get(timeout=)', 3), ('g(idle_s=)', 60.0)])


def test_the_helpers_read_their_seconds_from_the_registry():
    import inspect
    assert inspect.signature(loop_guard.LagMeter.__init__).parameters['period'].default == tp.LAG_PERIOD_S
    assert inspect.signature(loop_guard.WakeTicker.__init__).parameters['max_wait'].default == tp.WAKE_TICK_S
    assert controlled_host.WAKE_TICK_S == tp.WAKE_TICK_S, 'the host still has its own copy: the same number until it imports this one'
    assert all(k in tp.TIMERS for k in ('timer_policy.WAKE_TICK_S', 'timer_policy.LAG_PERIOD_S', 'timer_policy.CLOSE_WAIT_S', 'timer_policy.LATE_CUE_S'))


def test_the_waits_have_a_reason_or_a_limit_and_an_unmeasured_number_says_so():
    assert tp.validate_waits() == []
    assert 'timer_policy.PLAYED_FRESH_S' in tp.UNMEASURED and 'timer_policy.PLAYED_FRESH_S' in tp.TIMERS
    assert tp.value('timer_policy.PLAYED_FRESH_S') == 45.0 and tp.UNMEASURED['timer_policy.PLAYED_FRESH_S'].startswith('unmeasured')
    assert 'G-LATE' in tp.UNMEASURED['timer_policy.PLAYED_FRESH_S']
    assert {k for k in tp.UNMEASURED} <= set(tp.TIMERS)
    kind, why = tp.WAITS['controlled_media.FIRST_HOLD_SECONDS']
    assert kind == 'limit' and 'cue_late' in why and tp.value('controlled_media.FIRST_HOLD_SECONDS') <= tp.value('timer_policy.ANSWER_WAIT_SECONDS')


def test_a_limit_longer_than_the_wait_for_an_answer_is_caught(monkeypatch):
    from echo_sync import controlled_media as cm
    monkeypatch.setattr(cm, 'FIRST_HOLD_SECONDS', 9.0, raising=False)
    from echo_sync import cm_base
    monkeypatch.setattr(cm_base, 'FIRST_HOLD_SECONDS', 9.0)
    assert [k for k, _ in tp.validate_waits()] == ['controlled_media.FIRST_HOLD_SECONDS']


def test_the_relations_r12_and_r13_hold_and_are_counted():
    rules = {r.rule: r for r in tp.RELATIONS}
    assert len(rules) == 13 and {'R12', 'R13'} <= set(rules)
    assert rules['R12'].hard and rules['R13'].hard and tp.validate({}) == []


def test_the_seconds_of_the_hold_causes_exist():
    for rule, const in tp.HOLD_CONSTS.items():
        assert 'controlled_media.' + const in tp.TIMERS and tp.value('controlled_media.' + const) > 0, rule


