"""<id>/<id> (owner: «второй аккаунт Google ... ускориться минимум в два раза», «ёмкость по всем подключённым
ключам»). Live 23:30: the second Google key's channels (k2-*) got no call at all, because choose() takes the first
channel with room and the first key is first in the order. Channels of ONE model on several keys are tried with the
most requests left today first; the order of the models (tiers, the preferred model) never changes."""
from tools import factory_channels as C

NOW = 1_000_000.0
ENV = {'K1': 'x', 'K2': 'y'}


def _ch(cid, model, key, group):
    return dict(id=cid, model=model, key_env=key, group=group, tpm=100000, rpd=10, verified=True)


CH = [_ch('a', 'google/m', 'K1', 'g1'), _ch('b', 'google/m', 'K2', 'g2'), _ch('c', 'google/n', 'K1', 'g3')]


def test_one_model_on_two_keys_goes_to_the_key_with_more_left_today():
    assert C.choose(CH, {'g1': {'request_times': [NOW - 5] * 4}}, 100, ENV, now=NOW)['id'] == 'b'
    assert C.choose(CH, {'g2': {'request_times': [NOW - 5] * 4}}, 100, ENV, now=NOW)['id'] == 'a'


def test_equal_left_keeps_the_given_order():
    assert C.choose(CH, {}, 100, ENV, now=NOW)['id'] == 'a'


def test_another_model_never_jumps_ahead_of_the_first_model():
    order = [_ch('c', 'google/n', 'K1', 'g3'), _ch('a', 'google/m', 'K1', 'g1'), _ch('b', 'google/m', 'K2', 'g2')]
    busy = {'g3': {'request_times': [NOW - 5] * 9}}                 # n has 1 left, m has 10 on each key
    assert C.choose(order, busy, 100, ENV, now=NOW)['id'] == 'c'


def test_requests_older_than_a_day_do_not_count():
    old = {'g1': {'request_times': [NOW - 90000] * 9}, 'g2': {'request_times': [NOW - 5] * 2}}
    assert C.choose(CH, old, 100, ENV, now=NOW)['id'] == 'a'          # g1: 10 left (old ones expired), g2: 8 left
