"""I4 (U218, U121): the old build against the new one on the same scenes, as a table. The tools are pure functions of the two runs; the stand run goes through the real
``ControlledMedia`` (``tools.replay.stand``), so two runs of ONE build are the same scenes and give the same cues: the comparison of a build with itself shows nothing fixed, nothing new."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.replay import flag_compare as FC                                      # noqa: E402
from tools.replay import speed as G                                              # noqa: E402


def _write(folder, journal, latency=None, tokens=None, sha=None, **checks):
    folder.mkdir(parents=True, exist_ok=True)
    body = {'journal': journal, 'flags': {}, 'checks': checks, 'decisions': []}
    body.update({k: v for k, v in (('latency_ms', latency), ('tokens', tokens), ('sha', sha)) if v is not None})
    (folder / f'{journal}.json').write_text(json.dumps(body), encoding='utf-8')


def test_table_names_fixed_remained_new_and_same_per_journal(tmp_path):
    for name, old, new in (('a', dict(loops=2, cues=3), dict(loops=0, cues=3)), ('b', dict(failures=1, cues=2), dict(failures=1, cues=2)),
                           ('c', dict(cues=4, questions=2), dict(stale=1, cues=4, questions=2)), ('d', dict(cues=1), dict(cues=1))):
        _write(tmp_path / 'old', name, **old)
        _write(tmp_path / 'new', name, **new)
    t = FC.table(tmp_path / 'old', tmp_path / 'new')
    assert t['journals'] == {'a': 'fixed', 'b': 'remained', 'c': 'new', 'd': 'same'}
    assert t['counts'] == {'fixed': 1, 'remained': 1, 'new': 1, 'same': 1}
    assert not t['not_worse'] and not t['faster'] and t['same_journals']


def test_a_gain_elsewhere_does_not_hide_a_new_failure(tmp_path):
    _write(tmp_path / 'old', 'a', loops=5, cues=3, questions=3)
    _write(tmp_path / 'new', 'a', loops=0, cues=3, questions=3)
    _write(tmp_path / 'old', 'b', cues=2, questions=2)
    _write(tmp_path / 'new', 'b', failures=1, cues=2, questions=2)
    t = FC.table(tmp_path / 'old', tmp_path / 'new')
    assert t['verdict']['bad'] == 'better' and t['counts']['new'] == 1 and not t['not_worse']


def test_latency_and_tokens_are_unknown_until_the_replay_wrote_them(tmp_path):
    _write(tmp_path / 'old', 'a', cues=2)
    _write(tmp_path / 'new', 'a', cues=2)
    t = FC.table(tmp_path / 'old', tmp_path / 'new')
    assert t['old']['median_ms'] is None and t['verdict']['median_ms'] == 'unknown' and t['verdict']['tokens_per_useful_answer'] == 'unknown' and not t['faster']


def test_faster_needs_median_and_p90_lower_and_the_same_journals(tmp_path):
    _write(tmp_path / 'old', 'a', latency=[900, 1000, 1500], tokens=300, cues=3)
    _write(tmp_path / 'new', 'a', latency=[700, 800, 1200], tokens=240, cues=3)
    t = FC.table(tmp_path / 'old', tmp_path / 'new')
    assert t['faster'] and t['verdict']['tokens_per_useful_answer'] == 'better'
    _write(tmp_path / 'new', 'extra', cues=1)                          # the sets differ: nothing is called faster
    assert not FC.table(tmp_path / 'old', tmp_path / 'new')['faster']


def test_overlay_copies_the_runner_onto_an_older_tree_and_keeps_its_engine(tmp_path):
    src, dst = tmp_path / 'src', tmp_path / 'dst'
    for root, text in ((src, 'new'), (dst, 'old')):
        for name in FC.OVERLAY:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding='utf-8')
        (root / 'echo_sync').mkdir()
        (root / 'echo_sync' / 'engine.py').write_text(text, encoding='utf-8')
    assert sorted(FC.overlay(src, dst)) == sorted(FC.OVERLAY)
    assert (dst / 'echo_sync' / 'engine.py').read_text(encoding='utf-8') == 'old'
    assert FC.overlay(src, dst) == []


def _row(family, seed, cue, right=True, violations=(), question='q'):
    return {'key': f'{family}:{seed}', 'family': family, 'seed': seed, 'question': question, 'cue': cue, 'right': right, 'violations': list(violations)}


def _run(rows, sha):
    return {'sha': sha, 'times': {'cloud': 3.3}, 'early': False, 'rows': rows}


def test_scene_table_fixed_remained_new_same_and_faster():
    old = _run([_row('mult', 0, None, False), _row('mult', 1, 2.0, False), _row('money', 0, 2.0), _row('money', 1, 3.0)], 'old')
    new = _run([_row('mult', 0, 1.0), _row('mult', 1, 1.5, False), _row('money', 0, 1.0), _row('money', 1, 2.0, violations=['stale'])], 'new')
    c = G.compare_runs(old, new)
    assert c['scenes'] == {'mult:0': 'fixed', 'mult:1': 'remained', 'money:1': 'new'}
    assert c['counts'] == {'fixed': 1, 'remained': 1, 'new': 1, 'same': 1} and not c['faster'] and not c['not_worse']
    assert c['total']['old']['silent'] == 1 and c['total']['new']['silent'] == 0


def test_faster_only_when_median_and_p90_fall_with_no_new_scene():
    old = _run([_row('mult', n, 3.0 + n) for n in range(5)], 'old')
    new = _run([_row('mult', n, 2.0 + n) for n in range(5)], 'new')
    assert G.compare_runs(old, new)['faster']
    new['rows'][4] = _row('mult', 4, 2.0, right=False)
    assert not G.compare_runs(old, new)['faster']


def test_other_questions_or_times_are_not_the_same_scenes():
    old = _run([_row('mult', 0, 2.0, question='a')], 'old')
    new = _run([_row('mult', 0, 1.0, question='b')], 'new')
    c = G.compare_runs(old, new)
    assert not c['same_scenes'] and c['question_differs'] == ['mult:0'] and not c['faster']
    new = _run([_row('mult', 0, 1.0, question='a')], 'new')
    new['times'] = {'cloud': 1.5}
    assert not G.compare_runs(old, new)['same_scenes']


def test_a_build_against_itself_on_the_real_stand_changes_nothing():
    """Two runs of this checkout through the real controller on the stand (phone times, 2 scenes per family): the same cues, nothing fixed, nothing new."""
    a, b = G.run(range(2), **G.PHONE), G.run(range(2), **G.PHONE)
    c = G.compare_runs(a, b)
    assert c['same_scenes'] and c['counts']['fixed'] == 0 and c['counts']['new'] == 0 and c['not_worse']
    assert a['sha'] and len(a['rows']) == 2 * len(G.FAMILIES)
    assert [r['cue'] for r in a['rows']] == [r['cue'] for r in b['rows']]
