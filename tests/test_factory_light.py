"""The light engine of the runner: one REST request, SEARCH/REPLACE blocks applied to the task's files only
(owner 19.11 16:51: small edits and reviews through fast calls, Kilo only for multi-file edits)."""
import json
from dataclasses import replace

import pytest

from tools import agent_factory as F
from tools import agent_factory_runner as W
from tools import factory_channels as C


def task(touch=('calc.py',)):
    """A planned task; ``touch=()`` is the reviewer's copy the runner makes (replace(), as review_candidate)."""
    base = F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    return replace(base, touch_files=tuple(touch))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError('a test reached the network')
    monkeypatch.setattr(W, '_light_post', refuse)


def reply(content, status=200, finish='stop', usage=None):
    body = dict(choices=[dict(message=dict(content=content), finish_reason=finish)],
                usage=usage if usage is not None else dict(prompt_tokens=500, completion_tokens=20))
    return lambda url, key, payload, timeout: (status, json.dumps(body).encode())


BLOCK = 'calc.py\n<<<<<<< SEARCH\ndef add(a,b): return a-b\n=======\ndef add(a,b): return a+b\n>>>>>>> REPLACE\n'


def test_engine_rule_review_and_small_tasks_are_light_multi_file_edits_are_kilo():
    assert W.engine_for('review', task(touch=())) == 'light'
    assert W.engine_for('code', task(touch=('a.py',))) == 'light'
    assert W.engine_for('repair', task(touch=('a.py', 'b.py'))) == 'light'
    assert W.engine_for('code', task(touch=('a.py', 'b.py', 'c.py'))) == 'kilo'


def test_blocks_name_their_file_and_a_block_for_another_file_is_refused():
    text = ('Fix:\n' + BLOCK + 'tests/test_calc.py\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE\n'
            'echo_sync/fast_text.py\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n')
    blocks, outside = W.parse_edit_blocks(text, ('calc.py', 'echo_sync/fast_text.py'))
    assert [b[0] for b in blocks] == ['calc.py', 'echo_sync/fast_text.py'] and outside == 1


def test_a_block_without_a_file_line_belongs_to_the_only_file_and_an_open_block_is_dropped():
    text = '<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nc\n=======\nd\n'
    blocks, outside = W.parse_edit_blocks(text, ('pkg/one.py',))
    assert blocks == [('pkg/one.py', 'a', 'b')] and outside == 0
    assert W.parse_edit_blocks(text, ('one.py', 'two.py')) == ([], 1)   # two files: whose block is it?


def test_a_short_file_name_is_resolved_only_when_unique():
    assert W._light_target('`fast_text.py`', ('echo_sync/fast_text.py',)) == 'echo_sync/fast_text.py'
    assert W._light_target('x.py', ('a/x.py', 'b/x.py')) == ''
    assert W._light_target('Here is the fix', ('a.py',)) is None


def test_replace_once_exact_then_trailing_space_tolerant_never_ambiguous():
    assert W._replace_once('a\nb\nc\n', 'b', 'B') == 'a\nB\nc\n'
    assert W._replace_once('x = 1  \ny\n', 'x = 1\ny', 'x = 2\ny') == 'x = 2\ny\n'
    assert W._replace_once('a\na\n', 'a', 'b') is None
    assert W._replace_once('a\n', 'zzz', 'b') is None


def test_apply_keeps_crlf_creates_a_new_file_and_counts_failures(tmp_path):
    (tmp_path / 'calc.py').write_bytes(b'def add(a,b): return a-b\r\nX = 1\r\n')
    blocks = [('calc.py', 'def add(a,b): return a-b', 'def add(a,b): return a+b'),
              ('calc.py', 'missing', 'x'), ('tests/test_new.py', '', 'def test_new(): pass'),
              ('calc.py', '', 'overwrite')]
    applied, failed = W.apply_edit_blocks(tmp_path, blocks)
    assert applied == ['calc.py', 'tests/test_new.py']
    assert (tmp_path / 'calc.py').read_bytes() == b'def add(a,b): return a+b\r\nX = 1\r\n'
    assert (tmp_path / 'tests/test_new.py').read_text() == 'def test_new(): pass\n'
    assert failed == {'SEARCH not found exactly once': 1, 'empty SEARCH on a file that is not empty': 1}


def test_attempt_applies_the_edit_and_reports_like_kilo(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    usage = dict(prompt_tokens=900, completion_tokens=40, prompt_tokens_details=dict(cached_tokens=100),
                 completion_tokens_details=dict(reasoning_tokens=7))
    rc, out, note = W.light_attempt(task(), tmp_path, 'google/gemini-3.5-flash-lite', prompt_override='p',
                                    post=reply(BLOCK, usage=usage))
    assert rc == 0 and (tmp_path / 'calc.py').read_text() == 'def add(a,b): return a+b\n'
    summary = W.event_summary(out, tmp_path)
    assert summary['steps'] == 1 and summary['tool_events'] == 1 and summary['last_step_tools'] == 1
    assert (summary['input_tokens'], summary['cache_read_tokens'], summary['output_tokens'],
            summary['reasoning_tokens']) == (800, 100, 40, 7)
    assert C.classify(out, note, rc)['kind'] == 'ok'
    assert note.decode() == 'edit blocks 1, changed files 1'


def test_the_reviewer_copy_is_never_edited_and_answers_with_its_text(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    seen = []

    def post(url, key, payload, timeout):
        seen.append(payload['messages'][0]['content'])
        return reply('{"approved": false, "reasons": ["r"]}\n' + BLOCK)(url, key, payload, timeout)
    rc, out, _ = W.light_attempt(task(touch=()), tmp_path, 'google/gemma-4-31b-it', prompt_override='p', post=post)
    assert rc == 0 and (tmp_path / 'calc.py').read_text() == 'def add(a,b): return a-b\n'
    assert seen == [W.LIGHT_REVIEW_RULES] and W.event_summary(out)['text'].startswith('{"approved": false')


@pytest.mark.parametrize('status, body, kind', [
    (429, [dict(error=dict(code=429, details=[dict(violations=[
        dict(quotaId='GenerateRequestsPerDayPerProjectPerModel-FreeTier')])]))], 'rate_day'),
    (429, dict(error=dict(code=429, message='Rate limit exceeded: per minute')), 'rate_minute'),
    (400, [dict(error=dict(code=400, message='API key not valid. Please pass a valid API key.'))], 'key_invalid'),
    (403, dict(error=dict(code=403, message='User location is not supported for the API use.')), 'region'),
    (404, dict(error=dict(code=404, message='model not found')), 'model_missing'),
    (503, dict(error=dict(code=503, message='overloaded')), 'transient'),
    (None, 'TimeoutError', 'transient'),
])
def test_provider_errors_get_the_same_classes_as_through_kilo(tmp_path, monkeypatch, status, body, kind):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic')
    raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    rc, out, note = W.light_attempt(task(), tmp_path, 'openrouter/cohere/north-mini-code:free', prompt_override='p',
                                    post=lambda *a: (status, raw))
    assert rc == 1 and C.classify(out, note, rc)['kind'] == kind


def test_reasoning_before_the_answer_is_dropped_and_a_draft_inside_it_is_never_applied(tmp_path, monkeypatch):
    """Gemma 4 answers '<thought>...</thought>OK' on the OpenAI-compatible endpoint (live 19.11)."""
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    draft = BLOCK.replace('a+b', 'a*b')
    rc, out, note = W.light_attempt(task(), tmp_path, 'google/gemma-4-31b-it', prompt_override='p',
                                    post=reply('<thought>maybe:\n' + draft + '</thought>\n' + BLOCK))
    assert (tmp_path / 'calc.py').read_text() == 'def add(a,b): return a+b\n' and note.decode().startswith('edit blocks 1,')
    _, out, _ = W.light_attempt(task(touch=()), tmp_path, 'google/gemma-4-31b-it', prompt_override='p',
                                post=reply('<THINK>hm</THINK>{"approved": true, "reasons": []}'))
    assert W.event_summary(out)['text'] == '{"approved": true, "reasons": []}'
    _, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p',
                                 post=reply('<thought>cut off by the length limit ' + BLOCK))
    assert note.decode() == 'the answer had no SEARCH/REPLACE edit block'   # an unterminated thought hides all


def test_no_key_is_key_invalid_without_a_request(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    rc, out, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p')   # _no_network would fail
    assert rc == 1 and C.classify(out, note, rc)['kind'] == 'key_invalid'


def test_an_answer_without_blocks_tells_the_next_attempt_why(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    _, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p',
                                 post=reply('CANNOT: the function is not in the shown part'))
    assert note.decode() == 'the model answered CANNOT: the function is not in the shown part'
    _, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p', post=reply('I think it is fine.'))
    assert note.decode() == 'the answer had no SEARCH/REPLACE edit block'


def test_the_coder_rules_name_the_task_files_never_a_placeholder_path():
    """Live 19.11 17:50: the model copied 'path/of/the/file.py' from the format example."""
    rules = W.light_rules(task(touch=('echo_sync/a.py', 'echo_sync/b.py')))
    assert 'Allowed files: echo_sync/a.py, echo_sync/b.py.' in rules and '\necho_sync/a.py\n<<<<<<< SEARCH' in rules
    assert 'path/of' not in rules


def test_the_light_prompt_has_no_tool_instructions_and_says_what_is_shown():
    """Live 19.11 17:50: with read/grep instructions the light model answered CANNOT: needs access outside."""
    big = ''.join('def f%d(x):\n    return x + %d\n\n' % (i, i) for i in range(700)).encode()
    t = task()
    visible = {'calc.py': big, 'tests/test_calc.py': b'from calc import f1\n'}
    light = W.build_coder_prompt(t, visible, light=True)
    kilo = W.build_coder_prompt(t, visible)
    assert 'read tool' not in light and 'grep' not in light and W.LIGHT_HINT in light
    assert 'read tool' in kilo and W.LIGHT_HINT not in kilo


def test_an_overloaded_model_is_cooled_so_the_next_try_takes_another_channel():
    """Live 19.11 18:18-18:20: a 503 'high demand' of one model deferred the task while other channels idled."""
    channel = dict(id='c1', group='p', model='google/x', key_env='KEY', tpm=100000, rpd=100)
    state = {}
    done = C.apply_failure(state, channel, {'kind': 'transient', 'status': 503}, now=1000.0)
    assert done == {'action': 'cool_model', 'cool_s': C.OVERLOAD_COOL_S}
    assert state['model_cool']['google/x'] == 1000.0 + C.OVERLOAD_COOL_S
    assert C.apply_failure({}, channel, {'kind': 'transient', 'status': None}, now=1000.0)['action'] == 'none'


def test_light_tokens_book_the_light_overhead_not_kilos():
    assert C.estimate_tokens(3500, 0, overhead=W.LIGHT_OVERHEAD_TOKENS) == 1000 + W.LIGHT_OVERHEAD_TOKENS
    assert C.estimate_tokens(3500) == 1000 + C.KILO_OVERHEAD_TOKENS
