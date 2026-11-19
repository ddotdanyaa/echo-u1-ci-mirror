"""<id> wiring of the shared quota ledger (tools/factory_quota.py) into the runner. The ledger folder is 'quota' next to
the channel registry file, so every state that uses one registry folder (the live loop, every self-build plan) sees
the others: a key spent today by another state is not chosen, and this state's own bookings are published for them."""
import json
import time

from tests.test_factory_runtime import FIX_BLOCK, Rig
from tests.test_factory_tournament import _wire
from tools import factory_quota as Q

APPROVE = '{"approved": true, "reasons": []}'


def _registry(tmp_path):
    rows = [dict(id='c1', group='p1', model='google/x', key_env='KEY', tpm=100000, rpd=2, verified=True),
            dict(id='c2', group='p2', model='google/y', key_env='KEY', tpm=100000, rpd=100, verified=True),
            dict(id='c3', group='p3', model='google/z', key_env='KEY', tpm=100000, rpd=100, verified=True)]
    path = tmp_path / 'registry' / 'channels.json'
    path.parent.mkdir()
    path.write_text(json.dumps(dict(channels=rows)), encoding='utf-8')
    return path


def test_a_key_spent_by_another_state_is_not_chosen_and_the_own_bookings_are_published(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    cfg = _registry(tmp_path)
    now = time.time()
    Q.publish(cfg.parent / 'quota', 'another-state', {'p1': {'request_times': [now - 5, now - 4]}})
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: APPROVE)
    result = rig.once(channel_config=cfg)
    assert [s['model'] for s in sent if not s['review']] == ['y']       # x's key is spent by the other state
    assert [s['model'] for s in sent if s['review']] == ['z']
    assert result['status'] == 'REVIEW'
    seen = Q.others(cfg.parent / 'quota', 'a-third-state')
    mine = [q for q in seen if 'p2' in q]
    assert len(mine) == 1 and mine[0]['p2']['request_times'] and mine[0]['p3']['request_times']
