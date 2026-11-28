"""V U236: a closed backlog row is checked against the FIRST SOURCE (the owner's words), not against a retelling: a row that is closed and has no link to a line of OWNER_WORDS.md is flagged ``closed_without_words``
(and listed by the chain report). A tool test on a small git repo in tmp_path (like test_i11_chain); not run on the laptop."""
import subprocess

from tools import backlog_register

BACKLOG = """| ID | кто | задача | пр. | состояние |
|---|---|---|---|---|
| U10 | ж | **задача один** | P0 | сделано: коммит и тест | **Как сказал владелец:** [16.11 07:09] «сделай»
| U13 | ж | **задача четыре** | P2 | закрыто |
"""
WORDS = """# Слова
## ⟦владелец⟧ 2026-11-16 07:09:10 · сессия x

сделай задачу один, длинный текст сообщения владельца без номера
"""


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True, capture_output=True)


def test_closed_row_without_a_words_link_is_flagged(tmp_path):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_u10_u13.py').write_text('# U10 U13\n', encoding='utf-8')
    (tmp_path / 'BACKLOG_ECHO.md').write_text(BACKLOG, encoding='utf-8')
    (tmp_path / 'OWNER_WORDS.md').write_text(WORDS, encoding='utf-8')
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'add', '-A')
    _git(tmp_path, 'commit', '-q', '-m', 'U10, U13: done')
    ch = backlog_register.chain(root=tmp_path, backlog=tmp_path / 'BACKLOG_ECHO.md', owner_words=tmp_path / 'OWNER_WORDS.md')
    by = {r['id']: r for r in ch['ids']}
    assert by['U10']['words'] == ['16.11 07:09'] and by['U13']['words'] == []        # the base: the link exists for U10 only
    assert by['U13']['closed'] and by['U13'].get('closed_without_words') is True, by['U13']
    assert not by['U10'].get('closed_without_words')
    assert 'U13' in backlog_register.render_chain(ch).split('| ID |')[1]               # the report lists it
