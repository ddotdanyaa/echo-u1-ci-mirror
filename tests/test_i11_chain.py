"""I11 (U180, U182, U131, U69, W21, W02): the chain requirement -> ID -> commit -> test -> SHA and the owner's words -> ID, on a small git repo built in tmp_path.
A tool test, not a call: it has no ControlledMedia (the tool reads files and git, it does not decide a reply)."""
import subprocess
from pathlib import Path

from tools import backlog_register, id_query

BACKLOG = """| ID | кто | задача | пр. | состояние |
|---|---|---|---|---|
| U10 | ж | **задача один** | P0 | сделано: коммит и тест | **Как сказал владелец:** [16.11 07:09] «сделай»
| U11 | ж | **задача два** | P1 | открыто |
| U12 | ж | **задача три** | P1 | открыто |
| U13 | ж | **задача четыре** | P2 | закрыто | 
"""
WORDS = """# Слова
## ⟦владелец⟧ 2026-11-16 07:09:10 · сессия x

сделай задачу один, длинный текст сообщения владельца без номера

## ⟦владелец⟧ 2026-11-16 08:00:00 · сессия x

как там U12 и когда будет готово, скажи пожалуйста подробно

## ⟦владелец⟧ 2026-11-16 09:00:00 · сессия x

длинное сообщение без единого номера задачи, которое нигде не связано с очередью
"""


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True, capture_output=True)


def _repo(tmp_path):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_u10.py').write_text('# U10 green through the controller\n', encoding='utf-8')
    (tmp_path / 'notes.md').write_text('U11 is only mentioned here\n', encoding='utf-8')
    (tmp_path / 'BACKLOG_ECHO.md').write_text(BACKLOG, encoding='utf-8')
    (tmp_path / 'OWNER_WORDS.md').write_text(WORDS, encoding='utf-8')
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'add', '-A')
    _git(tmp_path, 'commit', '-q', '-m', 'U10, U13: first thing')
    _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', 'wave: look at U11 later')
    return tmp_path


def test_index_and_commits_split_close_from_mention(tmp_path):
    root = _repo(tmp_path)
    idx = id_query.index(root)
    assert idx['U10']['tests'] == ['tests/test_u10.py']
    assert 'notes.md' in idx['U11']['files']
    log = id_query.commits(root)
    closing = {i for c in log for i in c['closes']}
    assert closing == {'U10', 'U13'}
    assert any('U11' in c['mentions'] and not c['closes'] for c in log)


def test_chain_names_the_first_missing_link_and_links_words(tmp_path):
    root = _repo(tmp_path)
    ch = backlog_register.chain(root=root, backlog=root / 'BACKLOG_ECHO.md', owner_words=root / 'OWNER_WORDS.md')
    by = {r['id']: r for r in ch['ids']}
    assert by['U10']['broken'] is None and by['U10']['commits'] and by['U10']['tests'] and by['U10']['words'] == ['16.11 07:09']
    assert by['U11']['broken'] == 'words'
    assert by['U12']['words'] == ['16.11 08:00']          # named in the text of the message
    assert by['U12']['broken'] == 'commit'
    assert by['U11']['mentions']                          # a mention in a commit is not a closing commit
    assert by['U13']['closed'] and by['U13']['closed_without_proof']      # closed by the row, a commit but no test
    assert ch['owner_words'] == {'messages': 3, 'long_without_id': 1}


def test_unknown_words_file_is_not_no(tmp_path):
    root = _repo(tmp_path)
    (root / 'OWNER_WORDS.md').unlink()
    ch = backlog_register.chain(root=root, backlog=root / 'BACKLOG_ECHO.md', owner_words=root / 'missing.md')
    assert ch['owner_words'] is None
    assert all(r['stages']['words'] is None for r in ch['ids'])
    assert 'неизвестна' in backlog_register.render_chain(ch)
