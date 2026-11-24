"""g37: the register of the backlog is complete and its proofs exist. No network, no model."""
import os, re
from pathlib import Path

import pytest

from tools import backlog_register as B

ROOT = Path(__file__).resolve().parents[1]


def test_every_id_of_the_source_file_is_classified_once():
    source = set(B.load_source_ids())
    reg = [r['id'] for r in B.register()]
    assert len(reg) == len(set(reg)), 'an id twice'
    assert source - set(reg) == set(), 'not classified: %s' % sorted(source - set(reg))
    assert set(reg) - source == set(), 'not in the source file: %s' % sorted(set(reg) - source)
    assert len(source) == 200, len(source)


@pytest.mark.parametrize('row', B.register(), ids=lambda r: r['id'])
def test_the_proof_files_exist(row):
    for f in row['files']:
        assert os.path.exists(ROOT / os.path.normpath(f)), '%s: %s' % (row['id'], f)
    if row['class'] in (B.DONE, B.FLAG, B.WIRE):
        assert row['files'], '%s has no proof' % row['id']


def test_a_done_row_names_a_test_or_a_report():
    for r in B.register():
        if r['class'] == B.DONE:
            assert any(f.startswith(('tests/', 'cloud_context/reports/', 'cloud_context/analysis/', 'cloud_context/material/')) for f in r['files']), r['id']


def test_the_rendered_register_counts_every_class():
    text = B.render(B.register())
    assert text.startswith('# Реестр') and 'Всего: 200' in text


# c24-e: honest statuses. DONE is the code and a test in the snapshot; six separate stages say how far a row really is.
STAGES = ('implemented', 'verified_shared', 'enabled', 'deployed', 'on_device', 'target_met')


def by_id():
    return {r['id']: r for r in B.register()}


def test_every_row_has_the_six_stages_with_known_values():
    for r in B.register():
        assert tuple(r['stages']) == STAGES, r['id']
        for k in STAGES:
            assert r['stages'][k]['v'] in B.VALUES, (r['id'], k)


def test_done_is_not_accepted_and_no_row_is_accepted_without_all_six():
    rows = B.register()
    for r in rows:
        assert r['accepted'] == all(r['stages'][k]['v'] == 'yes' for k in STAGES), r['id']
    # nothing in the cloud snapshot can be on the device or have met a laptop target by itself
    assert not [r['id'] for r in rows if r['stages']['on_device']['v'] == 'yes' or r['stages']['deployed']['v'] == 'yes'], 'the cloud knows no device and no deploy'
    assert 'Принято целиком' in B.render(rows)


def test_n02_with_its_half_second_target_is_not_closed_by_the_file():
    r = by_id()['N02']
    assert r['class'] == B.DONE and r['stages']['implemented']['v'] == 'yes'
    assert r['stages']['target_met']['v'] != 'yes' and not r['accepted']
    assert '0,5' in r['stages']['target_met']['basis']


def test_the_server_profile_marks_enabled_and_a_flag_off_marks_no():
    rows = by_id()
    assert B.PROFILE['repeat_rule'] == 'on' and B.PROFILE['stop_in_flight'] == 'on' and B.PROFILE['stumble_place'] == 'on' and B.PROFILE['local_fallback'] == 'on'
    assert B.PROFILE['voice_gain'] == 2.0 and B.PROFILE['dictation'] == 'off'
    for flag, ids in B.PROFILE_ROWS.items():
        for i in ids.split():
            assert rows[i]['stages']['enabled']['v'] in ('yes', 'part'), (flag, i)
    for r in rows.values():
        if r['class'] == B.FLAG and r['id'] not in B.OVR:
            assert r['stages']['enabled']['v'] == 'no', r['id']
        if r['class'] == B.WIRE:
            assert r['stages']['implemented']['v'] == 'part' and r['stages']['enabled']['v'] == 'no', r['id']


def test_the_37_owner_rows_are_split_into_the_owner_and_the_agent():
    rows = B.register()
    split = [r for r in rows if r['class'] in (B.OWNER, B.AGENT)]
    assert len(split) == 37 and set(B.SPLIT) <= {r['id'] for r in split}
    assert {r['id'] for r in split} == set(B.SPLIT), 'a row left with no side'
    agent = [r for r in split if r['class'] == B.AGENT]
    assert len(agent) >= 20, 'the automatable work is not parked under «нужен владелец»'
    for r in split:
        assert r['what'], r['id']
    for r in rows:
        if r['class'] == B.OWNER:
            assert any(w in r['what'] for w in ('телефон', 'наушник', 'решение', 'владелец', 'руки', 'человек', 'нажатия')), r['id']


def test_test_table_decides_verified_shared():
    from pathlib import Path
    f = 'tests/test_w5_instant.py'
    ok = B.register({f: True, 'tests/test_w13_pcm_cache.py': True})
    bad = B.register({f: False, 'tests/test_w13_pcm_cache.py': True})
    assert {r['id']: r for r in ok}['N02']['stages']['verified_shared']['v'] == 'yes'
    assert {r['id']: r for r in bad}['N02']['stages']['verified_shared']['v'] == 'no'
    table = B.load_tests()
    if table:
        for r in B.register():
            tf = [x for x in r['files'] if x.startswith('tests/')]
            if tf and any(table.get(x) is False for x in tf):
                assert r['stages']['verified_shared']['v'] == 'no', r['id']


def test_n82_to_n85_reconciliation_is_a_fact_of_the_files():
    rc = B.reconcile()
    assert len(rc['r']) == 24 and len(rc['blockers']) == rc['claim_list']
    assert rc['claim_note'][-1][1] == len(rc['blockers']) == 54 and rc['claim_note'][-2][1] == 53, 'the count of blockers followed the register\'s own history: 53 at 21:45, 54 at 22:30'
    assert 'E92' in rc['claim_note'][-1][2], 'the 54th blocker is the one the last entry added'
    assert all(b['row'] for b in rc['blockers']), 'a blocker with no row in the queue'
    assert all(not r['dangling'] for r in rc['r']), [r for r in rc['r'] if r['dangling']]
    text = B.render_reconcile(rc)
    assert 'N82' in text and 'N83' in text and 'N84' in text
    assert (ROOT / 'cloud_context/reports/c24-e-reconcile.md').read_text(encoding='utf-8') == text, 'regenerate: python -m tools.backlog_register --reconcile cloud_context/reports/c24-e-reconcile.md'
    assert by_id()['N82']['class'] == B.OPEN, 'the node graph and the branch code stay with the laptop'
