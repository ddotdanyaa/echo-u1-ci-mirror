"""kind / early-tail + stable-partial + flow-ahead: a portion confirmed AHEAD of its final (the cloud's stable partial, the ear's stable tail, the pace of the speaker) goes through ONE entry
(``_take_early``), is noted for its final in ONE place (``_accept_user``), and the tail after it has ONE function (``_tail_after``)."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / 'echo_sync'


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def _src():
    return {p.name: p.read_text(encoding='utf-8') for p in PKG.glob('*.py')}


def test_the_old_names_of_the_early_take_are_gone():
    text = '\n'.join(_src().values())
    assert '_tail_after_portion' not in text


def test_one_note_site_and_one_entry_for_a_portion_confirmed_ahead():
    files = _src()
    notes = sum(len(re.findall(r'self\._note_early\((?!tid,state,kind|tid,take|head,state)', t)) for t in files.values())
    assert notes == 1, notes      # the ear's takes (kind/piece/ear) note their own; the confirmation ahead is noted in _accept_user only
    for name in ('cm_kind.py', 'cm_portion.py'):
        assert "boundary='stable_partial',cause='stable_partial'" not in files[name]
        assert "boundary='ear_tail',cause='ear_tail'" not in files[name]
        assert "boundary='flow_ahead',cause='flow_ahead'" not in files[name]
    assert files['cm_kind.py'].count('def _take_early(') == 1 and files['cm_kind.py'].count('def _open_turn_id(') == 1
    assert 'latest_user()' not in files['cm_portion.py'].split('def _flow_due')[1].split('def first_cue_opens')[0]
