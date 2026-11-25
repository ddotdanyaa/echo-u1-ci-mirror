"""X-MAN: one corpus manifest (journal ids, set sha256, dev/holdout split) that every acceptance cites."""
import json

from tools import harvest as H


def _folder(tmp_path, names):
    for name in names:
        (tmp_path / f'{name}.json').write_text(json.dumps({'cues': [[1, 'x', 'y']] if name.endswith('a') else [], 'name': name}), encoding='utf-8')
    (tmp_path / 'counters.json').write_text('{}', encoding='utf-8')
    return tmp_path


def test_manifest_lists_journals_without_counters_and_is_stable(tmp_path):
    folder = _folder(tmp_path, ['20261103-1-a', '20261103-2-b'])
    first, second = H.manifest(folder), H.manifest(folder)
    assert first == second
    assert first['ids'] == ['20261103-1-a', '20261103-2-b']
    assert len(first['sha256']) == 64


def test_manifest_hash_follows_the_content(tmp_path):
    folder = _folder(tmp_path, ['20261103-1-a', '20261103-2-b'])
    before = H.manifest(folder)['sha256']
    (folder / '20261103-2-b.json').write_text('{"changed": 1}', encoding='utf-8')
    assert H.manifest(folder)['sha256'] != before


def test_split_is_dev_holdout_or_rest_and_subsets_are_filters(tmp_path):
    dev, hold = sorted(H.DEV)[0], sorted(H.HOLDOUT)[0]
    folder = _folder(tmp_path, [dev, hold, '20261103-9-a'])
    got = H.manifest(folder)
    assert got['split'][dev] == 'dev' and got['split'][hold] == 'holdout' and got['split']['20261103-9-a'] == 'rest'
    assert not set(H.DEV) & set(H.HOLDOUT) and (len(H.DEV), len(H.HOLDOUT)) == (8, 14)
    assert H.manifest_subset(folder, lambda fx: bool(fx.get('cues'))) == ['20261103-9-a']


def test_manifest_command_prints_ids_and_one_hash_and_writes_the_file(tmp_path, capsys):
    folder = _folder(tmp_path, ['20261103-1-a', '20261103-2-b'])
    assert H.main(['--manifest', '--out', str(folder)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ['20261103-1-a', '20261103-2-b'] and out[-1].startswith('sha256 ')
    assert json.loads((folder / 'MANIFEST.json').read_text(encoding='utf-8'))['sha256'] == out[-1].split()[1]
    assert H.main(['--manifest', '--out', str(folder)]) == 0    # MANIFEST.json itself is not a journal
    assert capsys.readouterr().out.splitlines() == out


def test_the_corpus_hash_ignores_what_the_checker_derives_but_the_manifest_carries_the_checker_hash(tmp_path):
    folder = _folder(tmp_path, ['20261103-1-a'])
    before = H.manifest(folder)
    body = json.loads((folder / '20261103-1-a.json').read_text(encoding='utf-8'))
    body.update(events=[{'t': 1, 'label': 'x'}], passport={'checker_sha256': 'abc'}, checks={'k': 1})
    (folder / '20261103-1-a.json').write_text(json.dumps(body), encoding='utf-8')
    after = H.manifest(folder)
    assert after['sha256'] == before['sha256'] and len(after['checker_sha256']) == 64
