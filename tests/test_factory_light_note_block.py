"""fac-light-note-block (live 19.11 21:10): fac_reject_cli failed three passes in a row with 'edit blocks 4, changed
files 0; 1: SEARCH not found exactly once'. A replay of the call showed block 4 searched for a line that is not in
the file at all (the model guessed code it was not shown), and the note never said which block it was, so every
retry repeated it. The note names each failing block (at most two), its file and the first line it searched for."""
import json

from tools import agent_factory as F
from tools import agent_factory_runner as W

MODEL = 'google/gemini-3.5-flash-lite'


def _task():
    return F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']


def _reply(content):
    body = dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                usage=dict(prompt_tokens=500, completion_tokens=20))
    return lambda url, key, payload, timeout: (200, json.dumps(body).encode())


def _block(search, replace):
    return 'calc.py\n<<<<<<< SEARCH\n%s\n=======\n%s\n>>>>>>> REPLACE\n' % (search, replace)


def test_the_note_names_the_block_whose_search_is_not_in_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\nX = 1\n')
    answer = _block('X = 1', 'X = 2') + _block('\n    if not any(ans.get(k) for k in keys):', '    pass')
    _, _, note = W.light_attempt(_task(), tmp_path, MODEL, prompt_override='p', post=_reply(answer))
    text = note.decode()
    assert text.startswith('edit blocks 2, changed files 0; 1: SEARCH not found exactly once; ')
    assert "block 2 (calc.py) SEARCH is not in the file: 'if not any(ans.get(k) for k in keys):'" in text
    assert 'block 1' not in text
    assert (tmp_path / 'calc.py').read_text() == 'def add(a,b): return a-b\nX = 1\n'       # still all or nothing


def test_the_note_says_when_a_search_is_found_more_than_once_and_names_two_blocks_at_most(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('x = 1\nx = 1\n')
    answer = _block('x = 1', 'x = 2') + _block('y = 1', 'y = 2') + _block('z = 1', 'z = 2')
    _, _, note = W.light_attempt(_task(), tmp_path, MODEL, prompt_override='p', post=_reply(answer))
    text = note.decode()
    assert "block 1 (calc.py) SEARCH is in the file more than once: 'x = 1'" in text
    assert "block 2 (calc.py) SEARCH is not in the file: 'y = 1'" in text
    assert 'block 3' not in text


def test_the_note_names_the_first_line_that_is_not_in_the_file(tmp_path, monkeypatch):
    """Live 19.11 22:30: the note said "SEARCH is not in the file: 'import ast'" although 'import ast' was there;
    the lines after it were the guess. The note names the first line of the block that the file does not have."""
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('import ast\nimport os\n\nX = 1\n')
    answer = _block('import ast\nimport json', 'import ast\nimport json\nimport types')
    _, _, note = W.light_attempt(_task(), tmp_path, MODEL, prompt_override='p', post=_reply(answer))
    assert "block 1 (calc.py) SEARCH is not in the file: 'import json'" in note.decode()


def test_a_successful_edit_keeps_the_short_note(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('X = 1\n')
    _, _, note = W.light_attempt(_task(), tmp_path, MODEL, prompt_override='p', post=_reply(_block('X = 1', 'X = 2')))
    assert note == b'edit blocks 1, changed files 1'
