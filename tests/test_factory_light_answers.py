"""fac-light-answers (live 19.11 21:05): in the live loop 29 of 32 coder answers changed no file (11 'SEARCH not
found exactly once', 8 without an edit block, 8 CANNOT) and no answer text was kept anywhere, so nobody could see
why. A coder answer that changed no file is kept beside the work copy, in <staging>/answers/<work copy name>.txt
(local only, never inside the candidate), the newest LIGHT_ANSWERS_KEPT of them."""
import json
import os
from dataclasses import replace

from tools import agent_factory as F
from tools import agent_factory_runner as W

MISSING = 'calc.py\n<<<<<<< SEARCH\ndef add(a,b): return a-b\n=======\ndef add(a,b): return a+b\n>>>>>>> REPLACE'
MODEL = 'google/gemini-3.5-flash-lite'


def _task():
    return F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']


def _reply(content):
    body = dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                usage=dict(prompt_tokens=500, completion_tokens=20))
    return lambda url, key, payload, timeout: (200, json.dumps(body).encode())


def _work(tmp_path, name, text):
    work = tmp_path / name
    work.mkdir()
    (work / 'calc.py').write_text(text)
    return work


def test_a_coder_answer_that_changed_no_file_is_kept_beside_the_work_copy(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    work = _work(tmp_path, 'task-T1-abc', 'def add(a, b):\n    return a - b\n')
    rc, _, note = W.light_attempt(_task(), work, MODEL, prompt_override='p', post=_reply(MISSING))
    kept = tmp_path / 'answers' / 'task-T1-abc.txt'
    assert rc == 0 and b'SEARCH not found' in note
    assert kept.is_file() and kept.read_text(encoding='utf-8') == MISSING
    assert sorted(p.name for p in work.iterdir()) == ['calc.py']          # never inside the candidate
    W.light_attempt(_task(), _work(tmp_path, 'task-T1-xyz', 'x = 1\n'), MODEL, prompt_override='p',
                    post=_reply('I think it is fine. ' * 2000))
    long = tmp_path / 'answers' / 'task-T1-xyz.txt'
    assert long.is_file() and len(long.read_text(encoding='utf-8')) == 20000


def test_an_applied_answer_and_a_review_keep_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    work = _work(tmp_path, 'task-T1-def', 'def add(a,b): return a-b\n')
    W.light_attempt(_task(), work, MODEL, prompt_override='p', post=_reply(MISSING))
    assert (work / 'calc.py').read_text() == 'def add(a,b): return a+b\n'
    W.light_attempt(replace(_task(), touch_files=()), _work(tmp_path, 'task-T1-rev', 'x = 1\n'),
                    'google/gemma-4-31b-it', prompt_override='p', post=_reply('{"approved": false, "reasons": []}'))
    assert not (tmp_path / 'answers').exists()


def test_the_answers_folder_keeps_only_the_newest(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    answers = tmp_path / 'answers'
    answers.mkdir()
    for i in range(W.LIGHT_ANSWERS_KEPT + 5):
        old = answers / ('task-old-%03d.txt' % i)
        old.write_text('old')
        os.utime(old, (1000 + i, 1000 + i))
    W.light_attempt(_task(), _work(tmp_path, 'task-T1-new', 'x = 1\n'), MODEL, prompt_override='p',
                    post=_reply('no block here'))
    names = {p.name for p in answers.iterdir()}
    assert len(names) == W.LIGHT_ANSWERS_KEPT and 'task-T1-new.txt' in names
    assert 'task-old-005.txt' not in names and 'task-old-006.txt' in names


def test_keeping_the_answer_never_breaks_the_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'answers').write_text('a file where the folder should be')
    rc, _, note = W.light_attempt(_task(), _work(tmp_path, 'task-T1-ghi', 'x = 1\n'), MODEL, prompt_override='p',
                                  post=_reply('no block here'))
    assert rc == 0 and note == b'the answer had no SEARCH/REPLACE edit block (nor a REPLACE FUNCTION block)'
