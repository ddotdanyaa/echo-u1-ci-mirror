import json
from tools import agent_factory as F

def _row(tid):
    return {
        'id': tid,
        'title': 'task ' + tid,
        'depends_on': [],
        'touch_files': ['src/%s.py' % tid.lower()],
        'read_files': [],
        'tests': ['tests/test_%s.py' % tid.lower()],
    }

def test_claim_takes_a_fresh_card_before_a_repeat(tmp_path):
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'tasks': [_row('T1'), _row('T2')]}), encoding='utf-8')
    cp = tmp_path / 'cp.json'
    with F.txn(cp, plan) as (tasks, state):
        F.add_feedback(state, 'T1', 'gate', 'failed once')
    got = F.claim(cp, plan)
    assert got[0] == 'T2'
