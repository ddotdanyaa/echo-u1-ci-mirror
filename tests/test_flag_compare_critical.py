"""U25 item 4: the comparer blocks on a critical regression in ONE journal even when the bad sum falls (the two owner counterexamples)."""
import json

from tools.replay import flag_compare


def _write(folder, journal, **checks):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{journal}.json').write_text(json.dumps({'journal': journal, 'flags': {}, 'checks': checks, 'decisions': []}), encoding='utf-8')


def test_all_questions_vanish_blocks(tmp_path):
    _write(tmp_path / 'a', 'j1', loops=5, stale=0, questions=10)
    _write(tmp_path / 'b', 'j1', loops=0, stale=0, questions=0)
    r = flag_compare.compare(tmp_path / 'a', tmp_path / 'b')
    assert r['worse'] == [] and r['blocking'] and r['critical'][0][1] == {'questions': (10, 0)}


def test_loop_gone_but_stale_appears_blocks(tmp_path):
    _write(tmp_path / 'a', 'j1', loops=3, stale=0, questions=4)
    _write(tmp_path / 'b', 'j1', loops=0, stale=1, questions=4)
    r = flag_compare.compare(tmp_path / 'a', tmp_path / 'b')
    assert r['worse'] == [] and r['blocking'] and r['critical'][0][1] == {'stale': (0, 1)}


def test_plain_improvement_passes(tmp_path):
    _write(tmp_path / 'a', 'j1', loops=3, stale=1, questions=4)
    _write(tmp_path / 'b', 'j1', loops=0, stale=1, questions=4)
    assert not flag_compare.compare(tmp_path / 'a', tmp_path / 'b')['blocking']
