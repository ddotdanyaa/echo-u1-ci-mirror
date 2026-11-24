"""The coordinator's replay of 96 failed SEARCH blocks (20.11 07:10): 63 aimed at a definition the coder's view did
not show whole (34 not at all, 29 in part), and the retry got the very same view. The note of a failed block now names
the definition it aimed at in the form the asked-code rule reads ("function 'name' was not shown whole"), right after
the counts, so the next candidate of the pass and the next pass are shown it first and whole. Aimed at = the
definition a header line of the SEARCH names, else the smallest one holding two or more of its lines. A definition the
prompt showed whole (a copy error) and one the file does not have (invented code) are not asked for."""
import json

from tools import agent_factory as F
from tools import agent_factory_runner as W
from tools import factory_context as X

MODEL = 'google/gemini-3.5-flash-lite'
CALC = 'def deep(x):\n    y = x + 1\n    return y * 2\n\n\ndef add(a, b):\n    return a + b\n'


def _task():
    return F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']


def _note(tmp_path, monkeypatch, search, shown='only the outline was shown'):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text(CALC)
    answer = 'calc.py\n<<<<<<< SEARCH\n%s\n=======\n    pass\n>>>>>>> REPLACE\n' % search
    body = dict(choices=[dict(message=dict(content=answer), finish_reason='stop')],
                usage=dict(prompt_tokens=500, completion_tokens=20))
    _, _, note = W.light_attempt(_task(), tmp_path, MODEL, prompt_override=shown,
                                 post=lambda url, key, payload, timeout: (200, json.dumps(body).encode()))
    assert (tmp_path / 'calc.py').read_text() == CALC                    # still all or nothing
    return note.decode()


def test_a_search_whose_header_names_an_unseen_definition_asks_for_it(tmp_path, monkeypatch):
    note = _note(tmp_path, monkeypatch, 'def deep(x):\n    y = x + 2')
    assert note.startswith("edit blocks 1, changed files 0; 1: SEARCH not found exactly once; "
                           "function 'deep' was not shown whole")
    assert X.asked_names(note) == {'deep'}


def test_two_lines_of_an_unseen_definition_aim_at_it_without_a_header(tmp_path, monkeypatch):
    note = _note(tmp_path, monkeypatch, '    y = x + 1\n    return y * 2\n    log(y)')
    assert X.asked_names(note) == {'deep'}


def test_a_definition_the_prompt_showed_whole_is_not_asked_again(tmp_path, monkeypatch):
    note = _note(tmp_path, monkeypatch, 'def deep(x):\n    y = x + 2', shown='FILE calc.py\n' + CALC)
    assert X.asked_names(note) == frozenset()


def test_a_definition_the_file_does_not_have_is_not_asked_for(tmp_path, monkeypatch):
    note = _note(tmp_path, monkeypatch, 'def reason_of(marks):\n    return marks')
    assert X.asked_names(note) == frozenset()
