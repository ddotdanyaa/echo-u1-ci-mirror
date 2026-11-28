# factory-backlog-id: U179
import inspect
import os

from echo_sync.utterance_judge import Resolutions

KIND = 'ack'
KEYS = ('tid', 'resolution', 'cause', 'reason', 'final_rev', 'going')


def fresh(**kw):
    params = inspect.signature(Resolutions.__init__).parameters
    keep = params.get('keep')
    if keep is not None and keep.default is inspect.Parameter.empty:
        kw['keep'] = 100
    return Resolutions(**kw)


def make(path):
    if 'path' in inspect.signature(Resolutions.__init__).parameters:
        return fresh(path=str(path))
    return fresh()


def test_resolutions_persistence(tmp_path, monkeypatch):
    journal = tmp_path / 'journal.json'
    r1 = make(journal)
    _, out1 = r1.resolve('t1', resolution=KIND, cause='c1', reason='why1', going='go1')
    _, out2 = r1.resolve('t2', resolution=KIND, cause='c2', reason='why2', going='go2')
    assert out1 == 'new'
    assert out2 == 'new'

    r2 = make(journal)
    assert list(r2.records) == ['t1', 't2']
    for tid in ('t1', 't2'):
        for key in KEYS:
            assert r2.records[tid][key] == r1.records[tid][key]
    assert r2.records['t1']['reason'] == 'why1'
    assert r2.records['t2']['going'] == 'go2'
    assert r2.records['t1']['final_rev'] == 1

    bad = tmp_path / 'bad.json'
    bad.write_text('{not json', encoding='utf-8')
    r3 = make(bad)
    assert r3.records == {}

    workdir = tmp_path / 'cwd'
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    tmp_before = sorted(os.listdir(tmp_path))
    cwd_before = sorted(os.listdir(workdir))
    r4 = fresh()
    _, out4 = r4.resolve('t3', resolution=KIND)
    assert out4 == 'new'
    assert sorted(os.listdir(tmp_path)) == tmp_before
    assert sorted(os.listdir(workdir)) == cwd_before

    text_before = journal.read_text(encoding='utf-8')
    _, again = r1.resolve('t1', resolution=KIND, cause='c1', reason='why1', going='go1')
    assert again == 'same'
    assert journal.read_text(encoding='utf-8') == text_before
