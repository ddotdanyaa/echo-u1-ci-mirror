"""U24: a query by a backlog ID finds the files that mention it and the tests among them; U780 does not hit U78, E05.1 does not hit E05, R31-4 does not hit R31."""
from pathlib import Path

from tools import id_query


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')


def test_query_finds_module_report_and_test_and_skips_longer_id(tmp_path):
    _write(tmp_path, 'echo_sync/host.py', '# U78: the host prints «недоступно»\n')
    _write(tmp_path, 'tests/test_host.py', 'def test_host():\n    # U78 red test\n    pass\n')
    _write(tmp_path, 'lane_reports/reports/u78.md', '# U78 report\n')
    _write(tmp_path, 'lane_reports/reports/u780.md', '# U780 report\n')
    r = id_query.query(tmp_path, 'U78')
    assert r == {'id': 'U78', 'files': ['echo_sync/host.py', 'lane_reports/reports/u78.md'], 'tests': ['tests/test_host.py']}
    assert id_query.query(tmp_path, 'U780')['files'] == ['lane_reports/reports/u780.md']


def test_whole_token_boundaries(tmp_path):
    _write(tmp_path, 'a.md', 'E05.1 and R31-4 and W03-x\n')
    _write(tmp_path, 'b.md', 'see E05. and (W03)\n')
    assert id_query.query(tmp_path, 'E05')['files'] == ['b.md']
    assert id_query.query(tmp_path, 'E05.1')['files'] == ['a.md']
    assert id_query.query(tmp_path, 'R31')['files'] == []
    assert id_query.query(tmp_path, 'R31-4')['files'] == ['a.md']
    assert id_query.query(tmp_path, 'W03')['files'] == ['b.md']


def test_repo_u29_finds_bank_test_and_data():
    r = id_query.query(id_query.ROOT, 'U29')
    assert 'tests/test_u29_bank.py' in r['tests']
    assert 'tools/data/bank_u29.json' in r['files'] or 'lane_reports/reports/u29.md' in r['files']
