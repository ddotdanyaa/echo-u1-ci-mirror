"""V-U202 (owner 16.11 17:11): the number of owners of decisions is cut in BIG steps (132 -> ~80 -> ~20 -> 15), not one by one. The step 132 -> ~80 is done (the ceilings sum to 77);
the next step is ~20 in all. Measured on the real list ``tools/owner_census_sites.ndjson`` against the working tree by ``tools.owner_census`` (nothing is run, nothing is mocked)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from tools import owner_census as C  # noqa: E402

NEXT_STEP_TOTAL = 20


def _counts():
    out = C.report(C.load_sites(C.SITES_PATH), C.Tree.from_dir(ROOT))
    return {key: out['families'][key]['owners'] for key, _ in C.FAMILIES}


def test_the_owners_of_the_tree_are_cut_to_the_next_big_step_of_twenty():
    counts = _counts()
    assert sum(counts.values()) <= NEXT_STEP_TOTAL, 'owners: %d (the next step is %d, then 15): %s' % (sum(counts.values()), NEXT_STEP_TOTAL, counts)


def test_the_ceilings_of_the_ratchet_follow_the_step_in_the_same_commit():
    caps = json.loads((ROOT / 'tools' / 'owner_census_caps.json').read_text(encoding='utf-8'))['families']
    assert sum(caps.values()) <= NEXT_STEP_TOTAL, 'the ceilings sum to %d, the step is %d' % (sum(caps.values()), NEXT_STEP_TOTAL)

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)
