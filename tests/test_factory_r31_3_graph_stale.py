# factory-backlog-id: R31-3
import importlib.util
import json
import os
from pathlib import Path


def _load_link_check():
    p = Path(__file__).resolve().parents[1] / 'tools' / 'link_check.py'
    spec = importlib.util.spec_from_file_location('link_check_under_test', str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_graph_stale_logic(tmp_path):
    lc = _load_link_check()
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'graphify-out').mkdir()
    a_py = root / 'echo_sync' / 'a.py'
    a_py.parent.mkdir(parents=True)
    a_py.write_text('print(1)\n', encoding='utf-8')
    backlog = root / 'BACKLOG.md'
    backlog.write_text('', encoding='utf-8')
    graph_json = root / 'graphify-out' / 'graph.json'
    graph_json.write_text(json.dumps({'nodes': []}), encoding='utf-8')
    argv = ['--root', str(root), '--work', str(backlog)]

    # stale: graph older than the source
    os.utime(str(graph_json), (1000, 1000))
    os.utime(str(a_py), (2000, 2000))
    res = lc.check_graph(root, [])
    assert res.get('present') is True
    assert res.get('readable') is True
    assert res.get('stale') is True, 'check_graph result: %r' % (res,)
    assert res.get('stale_by') == 1, 'check_graph result: %r' % (res,)
    assert lc.main(argv) == 1

    # fresh: graph newer than the source
    os.utime(str(graph_json), (2000, 2000))
    os.utime(str(a_py), (1000, 1000))
    res = lc.check_graph(root, [])
    assert res.get('stale') is False, 'check_graph result: %r' % (res,)
    assert res.get('stale_by') == 0, 'check_graph result: %r' % (res,)
    assert lc.main(argv) == 0

    # no graph at all
    graph_json.unlink()
    assert lc.check_graph(root, []) == {'present': False}
    assert lc.main(argv) == 0
