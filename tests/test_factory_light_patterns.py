"""fac-error-patterns-wire: the light coder's edit blocks go through ERROR_PATTERNS (tools/factory_patterns.py). Live
19.11 23:03: a view header copied into SEARCH ('# _fragments, lines 165-247') and a signature joined into one line
made fac_context_imports fail; both still apply when ONE place of the file matches. An elided SEARCH ('...') gets a
hint that tells the next attempt what to do."""
import json

from tools import agent_factory as F
from tools import agent_factory_runner as W

MODEL = 'google/gemini-3.5-flash-lite'
SRC = ('def big(source: str, keywords: set, room: int, priority: frozenset = frozenset(),\n'
       '        tools: bool = True) -> str:\n    return source\n')
JOINED = 'def big(source: str, keywords: set, room: int, priority: frozenset = frozenset(), tools: bool = True) -> str:'


def _task():
    return F.read_plan([dict(id='T1', title='Add a helper', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']


def _reply(content):
    body = dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                usage=dict(prompt_tokens=500, completion_tokens=20))
    return lambda url, key, payload, timeout: (200, json.dumps(body).encode())


def _block(search, replace):
    return 'calc.py\n<<<<<<< SEARCH\n%s\n=======\n%s\n>>>>>>> REPLACE\n' % (search, replace)


def test_a_view_header_and_a_joined_signature_still_apply(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text(SRC)
    answer = _block('# big, lines 1-3\n' + JOINED, 'def helper():\n    return 1\n\n\n' + JOINED)
    _, _, note = W.light_attempt(_task(), tmp_path, MODEL, prompt_override='p', post=_reply(answer))
    assert note == b'edit blocks 1, changed files 1'
    text = (tmp_path / 'calc.py').read_text()
    assert text.startswith('def helper():') and 'lines 1-3' not in text and text.endswith('    return source\n')


def test_an_elided_search_gets_the_hint_and_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('X = re.compile(r"a|b|c|d")\n')
    answer = _block('X = re.compile(r"a|b|...|d")', 'X = 1')
    _, _, note = W.light_attempt(_task(), tmp_path, MODEL, prompt_override='p', post=_reply(answer))
    assert "block 1 (calc.py): SEARCH must not shorten code with '...'" in note.decode()
    assert (tmp_path / 'calc.py').read_text() == 'X = re.compile(r"a|b|c|d")\n'
