"""<id> foundation and the 429 class (20.11 00:00): every task state - the live loop's, each self-build plan's - kept its
own ledger of key usage, so a new state never knew a key was spent today and paid a 429 per model to learn it again
(fac_requeue, fac_parse_cache, fac_triage_example: 'repair:gemini-3.6-flash:429' while the second key had requests
left). One shared ledger folder per channel registry: every state publishes its own channel quotas as ONE section
file (one writer per state: the checkpoint lock), and a call chooses on the union of its own quotas and the other
sections. Old sections stop counting; an unreadable file is skipped, never a crash."""
import json
import os

from tools import factory_channels as C
from tools import factory_quota as Q

NOW = 1_000_000.0
ENV = {'K1': 'x', 'K2': 'y'}


def _ch(cid, key, group):
    return dict(id=cid, model='google/m', key_env=key, group=group, tpm=100000, rpd=2, verified=True)


CH = [_ch('a', 'K1', 'g1'), _ch('b', 'K2', 'g2')]


def test_a_section_is_seen_by_every_other_state_and_not_by_itself(tmp_path):
    Q.publish(tmp_path, 'state-A', {'g1': {'request_times': [NOW - 5]}}, now=NOW)
    assert Q.others(tmp_path, 'state-B', now=NOW) == [{'g1': {'request_times': [NOW - 5]}}]
    assert Q.others(tmp_path, 'state-A', now=NOW) == []
    Q.publish(tmp_path, 'state-A', {'g1': {'request_times': [NOW - 5, NOW - 1]}}, now=NOW)   # replaced, not added
    assert Q.others(tmp_path, 'state-B', now=NOW) == [{'g1': {'request_times': [NOW - 5, NOW - 1]}}]


def test_the_view_joins_bookings_and_takes_the_longest_cooling(tmp_path):
    own = {'g1': {'request_times': [1.0], 'rpm_times': [1.0], 'minute': [[1.0, 10]], 'cool_until': 5},
           'model_cool': {'google/m': 10}}
    other = {'g1': {'request_times': [2.0], 'rpm_times': [2.0], 'minute': [[2.0, 20]], 'cool_until': 9},
             'g2': {'request_times': [3.0]}, 'model_cool': {'google/m': 50, 'google/n': 7},
             'dead': {'c9': {'key': 'f', 'since': 1}}}
    seen = Q.view(own, [other])
    assert seen['g1']['request_times'] == [1.0, 2.0]
    assert seen['g1']['rpm_times'] == [1.0, 2.0]
    assert seen['g1']['minute'] == [[1.0, 10], [2.0, 20]]
    assert seen['g1']['cool_until'] == 9
    assert seen['g2']['request_times'] == [3.0]
    assert seen['model_cool'] == {'google/m': 50, 'google/n': 7}
    assert seen['dead'] == {'c9': {'key': 'f', 'since': 1}}
    assert own['g1']['request_times'] == [1.0]                      # the own ledger is not changed by the view


def test_a_key_spent_by_another_state_is_not_chosen(tmp_path):
    Q.publish(tmp_path, 'live-loop', {'g1': {'request_times': [NOW - 5, NOW - 4]}}, now=NOW)
    own = {}
    assert C.choose(CH, own, 100, ENV, now=NOW)['id'] == 'a'                                    # alone: blind
    assert C.choose(CH, Q.view(own, Q.others(tmp_path, 'self-plan', now=NOW)), 100, ENV, now=NOW)['id'] == 'b'


def test_old_and_unreadable_sections_do_not_count(tmp_path):
    Q.publish(tmp_path, 'old', {'g1': {'request_times': [1.0]}}, now=NOW - Q.STALE_S - 10)
    (tmp_path / 'broken.json').write_text('{not json', encoding='utf-8')
    assert Q.others(tmp_path, 'me', now=NOW) == []


def test_a_section_file_is_replaced_whole(tmp_path):
    Q.publish(tmp_path, 'state-A', {'g1': {'request_times': [NOW]}}, now=NOW)
    files = [p for p in tmp_path.iterdir() if p.suffix == '.json']
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding='utf-8'))
    assert data['section'] == 'state-A' and data['saved'] == NOW and data['quotas'] == {'g1': {'request_times': [NOW]}}
    assert not [p for p in tmp_path.iterdir() if p.suffix != '.json']                  # no temp file left behind
    assert os.path.basename(files[0]) == Q.section_file(tmp_path, 'state-A').name


def test_a_file_that_is_not_a_section_is_skipped(tmp_path):
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    (tmp_path / "noq.json").write_text("{\"saved\": 1}", encoding="utf-8")
    assert Q.others(tmp_path, "me", now=NOW) == []


def test_own_tuple_bookings_and_the_file_list_bookings_join_without_a_crash():
    """Live 20.11 00:37: reserve() keeps (time, tokens) tuples, the file gives [time, tokens] lists; the view sorted
    the mix and every runner pass crashed with "'<' not supported between list and tuple"."""
    own = {'g1': {'minute': [(NOW - 2, 100)], 'request_times': [NOW - 2]}}
    seen = Q.view(own, [{'g1': {'minute': [[NOW - 1, 50]], 'request_times': [NOW - 1]}}])
    assert len(seen['g1']['minute']) == 2
    assert C.choose(CH, seen, 100, ENV, now=NOW)['id'] in ('a', 'b')


def test_the_view_takes_the_longest_channel_cooling():
    own = {'channel_cool': {'c1': 10}}
    other = {'channel_cool': {'c1': 50, 'c2': 7}}
    assert Q.view(own, [other])['channel_cool'] == {'c1': 50, 'c2': 7}
    assert Q.view({}, [other])['channel_cool'] == {'c1': 50, 'c2': 7}
    assert own == {'channel_cool': {'c1': 10}}
