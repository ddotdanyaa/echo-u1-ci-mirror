# factory-backlog-id: W09
from datetime import date

from tools import link_check


def test_iso_date_counts_as_newest_date():
    # heartbeat lines start with an ISO date: 2026-11-04 21:02 main: ...
    got = link_check.newest_date('2026-11-20 10:00 main: live server', date(2026, 11, 21))
    assert got == date(2026, 11, 20)


def test_heartbeat_with_iso_date_is_not_marked_stale(tmp_path):
    root = tmp_path / 'w'
    (root / 'autocontinue').mkdir(parents=True)
    work = root / 'BACKLOG_ECHO.md'
    work.write_text('| W01 | обновлено 20.11 |\n', encoding='utf-8')
    (root / 'autocontinue' / 'MAIN_HEARTBEAT.txt').write_text('2026-11-20 10:00 main: ok\nNext: continue\n', encoding='utf-8')
    res = link_check.check_stale(root, work, 3, date(2026, 11, 21))
    hb = [r for r in res['files'] if r['path'].endswith('MAIN_HEARTBEAT.txt')][0]
    assert hb['newest'] == '2026-11-20'
    assert hb['stale'] is False

