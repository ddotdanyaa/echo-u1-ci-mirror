"""Channel router: a per-minute limit cools one channel, sticky keys, live reliability rating, 404 series, restart.

Pure state tests on tools.factory_channels; no model or network is called."""
import copy
import json

import pytest

from tools import factory_channels as C

NOW = 1_000_000.0
ENV = {'K1': 'x', 'K2': 'y'}


def ch(cid, model, key, group, **extra):
    return dict(id=cid, model=model, key_env=key, group=group, tpm=100000, rpd=1000, **extra)


A1 = ch('a1', 'google/a', 'K1', 'g1')
B1 = ch('b1', 'google/b', 'K1', 'g1')
A2 = ch('a2', 'google/a', 'K2', 'g2')
B2 = ch('b2', 'google/b', 'K2', 'g2')
ALL = [A1, B1, A2, B2]
MINUTE = {'kind': 'rate_minute', 'retry_after_s': 34, 'status': 429}


def test_a_minute_rate_limit_without_provider_code_cools_only_that_channel():
    state = {}
    out = C.apply_failure(state, A1, MINUTE, env=ENV, now=NOW)
    assert out == {'action': 'cool_channel', 'cool_s': 34}
    assert not state.get('g1', {}).get('cool_until') and not state.get('model_cool')
    for other in (B1, A2, B2):     # the project's other model, and the same model on the other key, keep working
        assert C.choose([other], state, 10, ENV, now=NOW + 1)['id'] == other['id']
    with pytest.raises(C.ChannelUnavailable) as caught:
        C.choose([A1], state, 10, ENV, now=NOW + 1)
    assert caught.value.reason == 'cool' and 30 <= caught.value.wait_s <= 34
    assert C.choose([A1], state, 10, ENV, now=NOW + 35)['id'] == 'a1'      # and it comes back by itself


def test_a_suspected_minute_stall_cools_one_channel_not_the_project():
    state = {}
    info = C.classify(b'', b'', 124, idle=True)
    assert info['kind'] == 'rate_minute' and info['suspect']
    C.apply_failure(state, A1, info, env=ENV, now=NOW)
    assert not state.get('g1', {}).get('cool_until')
    assert C.choose([B1], state, 10, ENV, now=NOW + 1)['id'] == 'b1'


def test_a_channel_cooling_never_shortens_and_is_not_widened_by_a_shorter_one():
    state = {}
    C.cool_channel(state, A1, now=NOW, seconds=900)
    C.cool_channel(state, A1, now=NOW, seconds=30)
    assert C.cooled_until(state, A1) == NOW + 900


@pytest.mark.parametrize('info', [{'kind': 'rate_day', 'retry_after_s': 4000, 'reset_at': NOW + 4000},
                                  {'kind': 'region'}, {'kind': 'balance'},
                                  {'kind': 'rate_minute', 'status': 402, 'retry_after_s': 60}])
def test_daily_quota_region_and_account_budget_still_cool_the_whole_key(info):
    state = {}
    C.apply_failure(state, A1, info, env=ENV, now=NOW)
    assert state['g1']['cool_until'] > NOW
    with pytest.raises(C.ChannelUnavailable):
        C.choose([B1], state, 10, ENV, now=NOW + 1)
    assert C.choose([A2], state, 10, ENV, now=NOW + 1)['id'] == 'a2'


def test_an_invalid_key_still_kills_the_channel():
    state = {}
    C.apply_failure(state, A1, {'kind': 'key_invalid'}, env=ENV, now=NOW)
    assert state['dead']['a1']['reason'] == 'key_invalid'


# ---- sticky key ----------------------------------------------------------------------------------

def test_without_affinity_the_order_is_unchanged():
    state = {}
    C.reserve(state, A1, 10, now=NOW, affinity='task:T1')
    assert C.choose(ALL, state, 10, ENV, now=NOW + 1)['id'] == 'a2'       # the old balancing decides: key 1 has less left
    assert C.choose(ALL, {}, 10, ENV, now=NOW + 1)['id'] == 'a1'          # and the given order breaks ties


def test_the_steps_of_one_task_keep_the_key_and_model_while_it_has_room():
    state = {'g1': {'request_times': [NOW - 5] * 10}}                      # balancing alone would prefer key 2
    C.reserve(state, A1, 10, now=NOW, affinity=['task:T1', 'family:tools/x'])
    assert C.choose(ALL, state, 10, ENV, now=NOW + 1)['id'] == 'a2'
    assert C.choose(ALL, state, 10, ENV, now=NOW + 1, affinity='task:T1')['id'] == 'a1'
    assert C.choose(ALL, state, 10, ENV, now=NOW + 1, affinity='task:T2000')['id'] == 'a2'   # another task: no memory
    # a task of the same module family follows the family's key
    assert C.choose(ALL, state, 10, ENV, now=NOW + 1, affinity=['task:T9', 'family:tools/x'])['id'] == 'a1'


def test_the_sticky_channel_is_left_when_it_has_no_room_or_is_cooled():
    state = {}
    C.reserve(state, A1, 10, now=NOW, affinity='task:T1')
    C.cool_channel(state, A1, now=NOW, seconds=60)
    assert C.choose(ALL, state, 10, ENV, now=NOW + 1, affinity='task:T1')['id'] != 'a1'
    rpm = [dict(c, rpm=1) for c in ALL]
    state = {}
    C.reserve(state, rpm[0], 10, now=NOW, affinity='task:T1')              # its minute is used up
    assert C.choose(rpm, state, 10, ENV, now=NOW + 1, affinity='task:T1')['id'] != 'a1'


def test_the_memory_expires_and_never_outranks_a_better_tier():
    small = dict(A2, id='s2', model='google/s', tier='small')
    main = dict(A1, tier='main')
    state = {}
    C.reserve(state, main, 10, now=NOW, affinity='task:T1')
    order = [small, main]                                                  # route_order put the small tier first
    assert C.choose(order, state, 10, ENV, now=NOW + 1, affinity='task:T1')['id'] == 's2'
    assert C.choose([A2, A1], state, 10, ENV, now=NOW + C.AFFINITY_TTL_S + 1, affinity='task:T1')['id'] == 'a2'


def test_the_memory_is_bounded():
    state = {}
    for i in range(C.AFFINITY_MAX + 50):
        C.reserve(state, A1, 1, now=NOW + i, affinity='task:%d' % i)
    assert len(state['affinity']) <= C.AFFINITY_MAX


def test_a_failing_model_is_not_kept_by_the_memory():
    state = {}
    C.reserve(state, A1, 10, now=NOW, affinity='task:T1')
    for i in range(6):
        C.note_outcome(state, A1, False, now=NOW + i, channels=[])
    state['g1'].pop('cool_until', None)
    assert C.choose(ALL, state, 10, ENV, now=NOW + 10, affinity='task:T1')['id'] != 'a1'


# ---- live reliability rating ----------------------------------------------------------------------

def test_route_order_puts_models_that_keep_failing_last_within_their_tier_only():
    base = [dict(A1, tier='main'), dict(B1, tier='main'), dict(A2, id='e', model='google/e', tier='escalation')]
    state = {}
    assert [c['id'] for c in C.route_order(base, 'code', 1, 100, state=state)] == ['a1', 'b1', 'e']
    for i in range(8):
        C.note_outcome(state, base[0], i < 2, now=NOW + i)              # 2 of 8 succeeded: 0.25
    assert [c['id'] for c in C.route_order(base, 'code', 1, 100, state=state)] == ['b1', 'a1', 'e']
    assert [c['id'] for c in C.route_order(base, 'code', 1, 100)] == ['a1', 'b1', 'e']          # no state: as before


def test_the_preferred_model_stays_first_among_equally_healthy_models():
    base = [dict(A1, tier='main'), dict(B1, tier='main')]
    assert C.route_order(base, 'code', 1, 100, preferred='google/b', state={})[0]['id'] == 'b1'


def test_a_better_rating_orders_healthy_models_and_few_calls_say_nothing():
    base = [dict(A1, tier='main'), dict(B1, tier='main')]
    state = {}
    for i in range(10):
        C.note_outcome(state, base[0], i < 8, now=NOW + i)              # 0.8
        C.note_outcome(state, base[1], True, now=NOW + i)               # 1.0
    assert C.route_order(base, 'code', 1, 100, state=state)[0]['id'] == 'b1'
    young = {}
    C.note_outcome(young, base[0], False, now=NOW)
    assert C.rating(young, 'google/a') == 1.0
    assert C.route_order(base, 'code', 1, 100, state=young)[0]['id'] == 'a1'


def test_only_the_recent_window_counts():
    state = {}
    for i in range(30):
        C.note_outcome(state, A1, False, now=NOW + i)
    for i in range(C.RATING_WINDOW):
        C.note_outcome(state, A1, True, now=NOW + 100 + i)
    assert C.rating(state, 'google/a') == 1.0


# ---- 404 on every call --------------------------------------------------------------------------------

def test_a_model_answering_not_found_every_time_is_skipped_until_the_config_changes():
    base = [dict(A1, tier='main'), dict(B1, tier='main')]
    state = {}
    for n in range(C.MISSING_STREAK - 1):
        out = C.apply_failure(state, base[0], {'kind': 'model_missing', 'status': 404}, env=ENV, now=NOW + n)
        assert out['action'] == 'dead' and 'reason' not in out
        assert [c['id'] for c in C.route_order(base, 'code', 1, 100, state=state)] == ['a1', 'b1']   # still probed
    out = C.apply_failure(state, base[0], {'kind': 'model_missing', 'status': 404}, env=ENV, now=NOW + 9)
    assert out['reason'] == 'model_missing_streak'
    assert [c['id'] for c in C.route_order(base, 'code', 1, 100, state=state)] == ['b1']
    later = NOW + 10 * C.MODEL_MISSING_TTL_S                              # no timer revives it
    with pytest.raises(C.ChannelUnavailable):
        C.choose([base[0]], state, 10, ENV, now=later)
    assert not C.usable([base[0]], state, ENV, now=later)
    changed = dict(base[0], model='google/a2')                            # the registry entry was edited
    assert C.usable([changed], state, ENV, now=later) and C.choose([changed], state, 10, ENV, now=later)
    assert C.route_order([changed], 'code', 1, 100, state=state)


def test_one_success_ends_the_not_found_series():
    state = {}
    C.apply_failure(state, A1, {'kind': 'model_missing'}, env=ENV, now=NOW)
    C.apply_failure(state, A1, {'kind': 'model_missing'}, env=ENV, now=NOW + 1)
    C.note_outcome(state, A1, True, now=NOW + 2)
    out = C.apply_failure(state, A1, {'kind': 'model_missing'}, env=ENV, now=NOW + 3)
    assert 'reason' not in out and not C.missing_for_good(state, A1)


def test_a_changed_config_forgets_the_old_series():
    state = {}
    for n in range(C.MISSING_STREAK):
        C.apply_failure(state, A1, {'kind': 'model_missing'}, env=ENV, now=NOW + n)
    new = dict(A1, tpm=50000)
    out = C.apply_failure(state, new, {'kind': 'model_missing'}, env=ENV, now=NOW + 50)
    assert 'reason' not in out


# ---- restart ---------------------------------------------------------------------------------------------

def test_bookings_coolings_memory_and_ratings_survive_a_json_round_trip():
    state = {}
    rpm = [dict(c, rpm=2) for c in ALL]
    for i in range(2):
        C.reserve(state, rpm[0], 10, now=NOW + i, affinity='task:T1')
    C.apply_failure(state, rpm[2], MINUTE, env=ENV, now=NOW)
    for i in range(6):
        C.note_outcome(state, rpm[1], False, now=NOW + i)
    state['g1'].pop('cool_until', None)
    restored = json.loads(json.dumps(state))                              # the checkpoint is JSON on disk
    assert restored == json.loads(json.dumps(copy.deepcopy(state)))
    now = NOW + 10
    for s in (state, restored):
        assert C.cooled_until(s, rpm[2]) > now                            # the channel cooling is still there
        assert C.rating(s, 'google/b') == 0.0
        pick = C.choose(rpm, s, 10, ENV, now=now, affinity='task:T1')
        assert pick['id'] not in ('a1', 'a2')                             # a1's minute is full, a2 is cooled
    assert C.choose(rpm, restored, 10, ENV, now=now)['id'] == C.choose(rpm, state, 10, ENV, now=now)['id']


def test_a_channel_cooled_model_is_not_another_free_route_for_the_series_cap():
    ch_list = [A1, B1]
    state = {}
    C.cool_channel(state, B1, now=NOW, seconds=600)
    for _ in range(8):
        out = C.note_outcome(state, A1, False, now=NOW, channels=ch_list)
    assert out['cool_s'] == C.STREAK_COOL_S
