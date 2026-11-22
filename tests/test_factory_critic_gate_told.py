"""Live 20.11 07:48: the factory's self-build queue gave a free model a coordinator's task; its candidate passed the gate
(compiled, every task test green), and the critic rejected it as "the candidate diff is truncated, leaving the function
incomplete and syntactically invalid": the diff had been cut at the review limit under the bare mark "[diff
truncated]". A critic now hears that the gate already compiled the candidate and ran the task tests, and a cut diff
says where it is cut and that the rest is not shown."""
from pathlib import Path

from tests.test_factory_runtime import FIX_BLOCK, Rig
from tests.test_factory_tournament import _wire
from tools import agent_factory_runner as W


def test_a_cut_diff_says_it_is_cut_not_ended(tmp_path):
    (tmp_path / 'a.py').write_text(''.join('x%d = %d\n' % (i, i) for i in range(400)), encoding='utf-8')
    diff = W.unified_diff({'a.py': b''}, Path(tmp_path), ['a.py'], 300)
    assert diff.endswith(W.DIFF_CUT % 300) and 'the rest of the change is not shown' in diff


def test_every_critic_hears_the_gate_already_passed(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    sent = _wire(rig, monkeypatch, lambda model: FIX_BLOCK, lambda model, n: '{"approved": true, "reasons": []}')
    rig.once()
    reviews = [s for s in sent if s['review']]
    assert reviews and all(W.GATE_PASSED.strip() in s['prompt'] for s in reviews)
