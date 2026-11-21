"""The light engine of the runner: one REST request, SEARCH/REPLACE blocks applied to the task's files only
(owner: small edits and reviews through fast calls, Kilo only for multi-file edits)."""
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
    # 3 files were light since 20.11 (Kilo never reached a review in 14 passes); 21.11: LIGHT_MAX_FILES 5 = the triage's
    # MAX_TOUCH, so 4 and 5 files are light too and only a sixth file goes to Kilo
    assert W.LIGHT_MAX_FILES == 5
    assert W.engine_for('code', task(touch=('a.py', 'b.py', 'c.py'))) == 'light'
    assert W.engine_for('code', task(touch=('a.py', 'b.py', 'c.py', 'd.py', 'e.py'))) == 'light'
    assert W.engine_for('code', task(touch=('a.py', 'b.py', 'c.py', 'd.py', 'e.py', 'f.py'))) == 'kilo'


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


def test_apply_keeps_crlf_and_creates_a_new_file(tmp_path):
    (tmp_path / 'calc.py').write_bytes(b'def add(a,b): return a-b\r\nX = 1\r\n')
    blocks = [('calc.py', 'def add(a,b): return a-b', 'def add(a,b): return a+b'),
              ('tests/test_new.py', '', 'def test_new(): pass'), ('calc.py', 'X = 1', 'X = 2')]
    applied, failed = W.apply_edit_blocks(tmp_path, blocks)
    assert applied == ['calc.py', 'tests/test_new.py'] and failed == {}
    assert (tmp_path / 'calc.py').read_bytes() == b'def add(a,b): return a+b\r\nX = 2\r\n'
    assert (tmp_path / 'tests/test_new.py').read_text() == 'def test_new(): pass\n'


def test_apply_is_all_or_nothing_and_counts_every_failure(tmp_path):
    """Critic 19.11: a block that did not apply left the others in the file, a half candidate."""
    (tmp_path / 'calc.py').write_bytes(b'def add(a,b): return a-b\r\nX = 1\r\n')
    blocks = [('calc.py', 'def add(a,b): return a-b', 'def add(a,b): return a+b'),
              ('calc.py', 'missing', 'x'), ('tests/test_new.py', '', 'def test_new(): pass'),
              ('calc.py', '', 'overwrite'), ('calc.py', 'X = 1', '\ud83d')]
    applied, failed = W.apply_edit_blocks(tmp_path, blocks)
    assert applied == [] and not (tmp_path / 'tests/test_new.py').exists()
    assert (tmp_path / 'calc.py').read_bytes() == b'def add(a,b): return a-b\r\nX = 1\r\n'
    assert failed == {'SEARCH not found exactly once': 1, 'empty SEARCH on a file that is not empty': 1,
                      'text that cannot be written as UTF-8': 1}


def test_an_exact_search_is_a_whole_line_never_the_head_of_a_longer_one():
    assert W._replace_once('    return x_list\n', '    return x', '    return y') is None
    assert W._replace_once('a = 1\n    return x\n', '    return x', '    return y') == 'a = 1\n    return y\n'
    assert W._replace_once('def f():\n    pass\n', 'def f():\n', 'def g():\n') == 'def g():\n    pass\n'


def test_a_longer_underline_inside_search_is_text_not_the_separator():
    text = 'doc.rst\n<<<<<<< SEARCH\nTitle\n==========\n=======\nTitle 2\n==========\n>>>>>>> REPLACE\n'
    blocks, outside = W.parse_edit_blocks(text, ('doc.rst',))
    assert blocks == [('doc.rst', 'Title\n==========', 'Title 2\n==========')] and outside == 0


def test_attempt_applies_the_edit_and_reports_like_kilo(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    usage = dict(prompt_tokens=900, completion_tokens=40, prompt_tokens_details=dict(cached_tokens=100),
                 completion_tokens_details=dict(reasoning_tokens=7))
    rc, out, note = W.light_attempt(task(), tmp_path, 'google/gemini-3.5-flash-lite', prompt_override='p',
                                    post=reply(BLOCK, usage=usage))
    assert rc == 0 and (tmp_path / 'calc.py').read_text() == 'def add(a,b): return a+b\n'
    summary = W.event_summary(out, tmp_path)
    assert summary['steps'] == 1 and summary['tool_events'] == 1 and summary['last_step_tools'] == 1
    assert (summary['input_tokens'], summary['cache_read_tokens'], summary['output_tokens'],
            summary['reasoning_tokens']) == (800, 100, 33, 7)    # completion 40 holds the 7 of reasoning
    assert C.classify(out, note, rc)['kind'] == 'ok'
    assert note.decode() == 'edit blocks 1, changed files 1'


def test_the_reviewer_copy_is_never_edited_and_answers_with_its_text(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
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
    (None, 'URLError', 'network'),              # no connection at all: the machine's network (critic 19.11)
    (200, 'not json', 'other'),                 # an unreadable answer: the provider's fault, escalates
    (200, dict(error=dict(code=502, message='upstream')), 'transient'),   # OpenRouter: the error inside a 200
])
def test_provider_errors_get_the_same_classes_as_through_kilo(tmp_path, monkeypatch, status, body, kind):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic')
    raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    rc, out, note = W.light_attempt(task(), tmp_path, 'openrouter/cohere/north-mini-code:free', prompt_override='p',
                                    post=lambda *a: (status, raw))
    assert rc == 1 and C.classify(out, note, rc)['kind'] == kind


TOOL_WORDS = ('read tool', 'read the file', 'read it by', 'grep', 'working directory', 'offset/limit')


def _big_module():
    """A python file over LARGE_FILE_CHARS whose outline overflows and whose named function is cut."""
    long_body = '\n'.join('    x_%d = %d' % (i, i) for i in range(900))
    rows = ['def f_%d(alpha, beta, gamma):\n    return alpha + beta + gamma + %d\n' % (i, i) for i in range(700)]
    return ('def target_func(a):\n' + long_body + '\n    return a\n\n' + '\n'.join(rows)).encode()


def test_no_prompt_of_the_light_engine_tells_the_model_to_use_tools(tmp_path, monkeypatch):
    """Critic 19.11: the reviewer always goes through the light engine, but its prompt still said 'read tool' and
    'grep'; the coder's outline and fragments did too. A model without tools answers CANNOT or rejects."""
    t = task(touch=('calc.py',))
    t = replace(t, title='fix target_func')
    visible = {'calc.py': _big_module(), 'tests/test_calc.py': b'from calc import target_func\n'}
    coder = W.build_coder_prompt(t, visible, light=True)
    assert 'target_func' in coder and '... ' in coder
    assert not [w for w in TOOL_WORDS if w in coder]
    (tmp_path / 'calc.py').write_bytes(visible['calc.py'])
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_calc.py').write_bytes(visible['tests/test_calc.py'])
    seen = []

    def invoke(reviewer, root, model, prompt_override):
        seen.append(prompt_override)
        return 0, (json.dumps({'type': 'text', 'part': {'text': '{"approved": true, "reasons": []}'}}) + '\n').encode(), b''
    approved, _ = W.review_candidate(t, tmp_path, 'google/y', invoke, baseline={'calc.py': b'old\n'})
    assert approved and seen and not [w for w in TOOL_WORDS if w in seen[0]]


def test_the_test_author_is_told_to_write_its_file_and_never_to_leave_tests_alone():
    t = replace(task(touch=('tests/test_new.py',)), kind='unit_test', tests=('tests/test_new.py',))
    prompt = W.build_coder_prompt(t, {'calc.py': b'def add(a,b): return a-b\n'}, light=True)
    assert 'Write ONLY the test' in prompt and W.UNIT_TEST_RULES in prompt
    assert 'Do not modify tests' not in prompt and 'Read-only tests' not in prompt


def test_a_test_only_task_is_reviewed_as_a_test_not_as_a_fix(tmp_path):
    """Live 19.11 19:14-19:16: with the checks of a fix, good tests were rejected 'does not implement the fix'."""
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_new.py').write_text('from calc import add\ndef test_add(): assert add(2, 3) == 5\n')
    (tmp_path / 'tests/test_calc.py').write_text('from calc import add\n')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    t = replace(task(touch=('tests/test_new.py',)), kind='unit_test', tests=('tests/test_new.py',),
                read_files=('calc.py',))
    seen = []

    def invoke(reviewer, root, model, prompt_override):
        seen.append(prompt_override)
        return 0, (json.dumps({'type': 'text', 'part': {'text': '{"approved": true}'}}) + '\n').encode(), b''
    assert W.review_candidate(t, tmp_path, 'google/y', invoke, baseline={'tests/test_new.py': b''}) == (True, [])
    assert W.REVIEW_CHECKS_TEST in seen[0] and 'the behaviour is really fixed' not in seen[0]
    code = []
    W.review_candidate(task(touch=('calc.py',)), tmp_path, 'google/y',
                       lambda r, root, m, prompt_override: code.append(prompt_override) or invoke(r, root, m, prompt_override),
                       baseline={'calc.py': b'old\n'})
    assert W.REVIEW_CHECKS in code[0] and W.REVIEW_CHECKS_TEST not in code[0]


def test_the_reviewer_verdict_is_found_inside_prose_or_a_fence(tmp_path):
    (tmp_path / 'calc.py').write_text('def add(a,b): return a+b\n')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_calc.py').write_text('from calc import add\n')

    def verdict_of(text):
        out = (json.dumps({'type': 'text', 'part': {'text': text}}) + '\n').encode()
        return W.review_candidate(task(touch=('calc.py',)), tmp_path, 'google/y',
                                  lambda *a, **k: (0, out, b''), baseline=None)
    assert verdict_of('Here is the verdict: {"approved": false, "reasons": ["stub"]} done') == (False, ['stub'])
    assert verdict_of('```json\n{"approved": true}\n```\nThe patch is fine.') == (True, [])


def test_a_paid_openrouter_model_never_leaves_the_machine_and_a_redirect_is_never_followed(tmp_path, monkeypatch):
    """Owner's 0 rubles rule inside the engine itself (critic 19.11: a manual --review-model skipped MODEL_ID); and a
    3xx must not carry the Authorization header to another host."""
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic')
    rc, _, note = W.light_attempt(task(), tmp_path, 'openrouter/vendor/paid-model', prompt_override='p',
                                  post=lambda *a: (_ for _ in ()).throw(AssertionError('sent')))
    assert rc == 125 and b'refused' in note
    import urllib.request
    handler = next(h for h in W._LIGHT_OPENER.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    request = urllib.request.Request(W.LIGHT_ENDPOINTS['openrouter'], headers={'Authorization': 'token-k'})
    assert handler.redirect_request(request, None, 302, 'Found', {}, W.LIGHT_ENDPOINTS['google']) is None


def test_an_answer_that_does_not_come_in_time_follows_the_timeout_contract(tmp_path, monkeypatch):
    """Critic 19.11: a light timeout was 'transient' for ever; now it is Kilo's timeout (idle series, ceiling)."""
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    rc, out, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p',
                                    post=lambda *a: (None, b'TimeoutError'))
    assert (rc, out, note) == (124, b'', b'worker-timeout')
    assert C.classify(out, note, rc)['kind'] == 'timeout' and C.classify(out, note, rc, idle=True)['suspect']


def test_reasoning_before_the_answer_is_dropped_and_a_draft_inside_it_is_never_applied(tmp_path, monkeypatch):
    """Gemma 4 answers '<thought>...</thought>OK' on the OpenAI-compatible endpoint (live 19.11)."""
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
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
    assert note.decode() == 'the answer had no SEARCH/REPLACE edit block (nor a REPLACE FUNCTION block)'   # an unterminated thought hides all


def test_no_key_is_key_invalid_without_a_request(tmp_path, monkeypatch):
    monkeypatch.delenv('GOOGLE_GENERATIVE_AI_API_KEY', raising=False)
    rc, out, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p')   # _no_network would fail
    assert rc == 1 and C.classify(out, note, rc)['kind'] == 'key_invalid'


def test_an_answer_without_blocks_tells_the_next_attempt_why(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    _, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p',
                                 post=reply('CANNOT: the function is not in the shown part'))
    assert note.decode() == 'the model answered CANNOT: the function is not in the shown part'
    _, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p', post=reply('I think it is fine.'))
    assert note.decode() == 'the answer had no SEARCH/REPLACE edit block (nor a REPLACE FUNCTION block)'


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


def test_a_model_that_stays_overloaded_is_tried_less_often_and_a_quiet_half_hour_starts_over():
    channel = dict(id='c1', group='p', model='google/x', key_env='KEY', tpm=100000, rpd=100)
    state, now, cools = {}, 1000.0, []
    for _ in range(5):                                   # each next try comes when the cooling is over
        cools.append(C.apply_failure(state, channel, {'kind': 'transient', 'status': 503}, now=now)['cool_s'])
        now += cools[-1]
    assert cools == [120, 240, 480, C.OVERLOAD_COOL_MAX_S, C.OVERLOAD_COOL_MAX_S]
    now += C.OVERLOAD_FORGET_S
    assert C.apply_failure(state, channel, {'kind': 'transient', 'status': 503}, now=now)['cool_s'] == 120
    other = dict(channel, model='google/y')               # the series belongs to one model
    assert C.apply_failure(state, other, {'kind': 'transient', 'status': 503}, now=now)['cool_s'] == 120


def test_light_tokens_book_the_light_overhead_not_kilos():
    assert C.estimate_tokens(3500, 0, overhead=W.LIGHT_OVERHEAD_TOKENS) == 1000 + W.LIGHT_OVERHEAD_TOKENS
    assert C.estimate_tokens(3500) == 1000 + C.KILO_OVERHEAD_TOKENS


def test_an_answer_that_is_all_reasoning_is_the_models_overload_not_the_tasks_failure(tmp_path, monkeypatch):
    """Live 20.11: Gemma 4 ended 13 of 16 coder calls since midnight with finish 'length' and no answer (~100 s each),
    and its API refuses a thinking budget or level. Such a call cools the MODEL (the overload series) and is no
    candidate; an answer cut at the limit that says something stays an answer."""
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    channel = dict(id='c1', group='p', model='google/gemma-4-26b-a4b-it', key_env='KEY', tpm=100000, rpd=100)
    for content in ('', '<thought>' + 'step ' * 40):
        rc, out, note = W.light_attempt(task(), tmp_path, channel['model'], prompt_override='p',
                                        post=reply(content, finish='length', usage=dict(prompt_tokens=900,
                                                                                         completion_tokens=8192)))
        info = C.classify(out, note, rc)
        assert rc == 1 and info['kind'] == 'transient' and info['name'] == 'EmptyAnswer'
        # D #22 (21.11): the task was too big for the model, not the model down: no instant cooling; the call hops to
        # another model and a model that does it again and again is cooled by the failure streak (note_outcome)
        assert C.apply_failure({}, channel, info, now=1000.0) == {'action': 'none', 'cool_s': 0}
    rc, _, note = W.light_attempt(task(), tmp_path, 'google/x', prompt_override='p', post=reply('CANNOT: add', finish='length'))
    assert rc == 0 and b'CANNOT' in note



def test_wQX09_replay_the_test_critic_sees_the_task_text_and_the_made_up_defect_check(tmp_path):
    """Acceptance 20.11: the critics of <id>_test saw only the title 'Тест для <id>' and approved a test of indented
    table rows, a defect the row never names. They now get the task text the coder got and check (7)."""
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_new.py').write_text('from calc import add\n# indented rows\n')
    (tmp_path / 'tests/test_calc.py').write_text('from calc import add\n')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    goal = 'Local check of links and registry integrity: a broken relative link is reported.'
    t = replace(task(touch=('tests/test_new.py',)), kind='unit_test', tests=('tests/test_new.py',),
                read_files=('calc.py',), goal=goal)
    seen = []

    def invoke(reviewer, root, model, prompt_override):
        seen.append(prompt_override)
        return 0, (json.dumps({'type': 'text', 'part': {'text': '{"approved": true}'}}) + '\n').encode(), b''
    W.review_candidate(t, tmp_path, 'google/y', invoke, baseline={'tests/test_new.py': b''})
    assert goal in seen[0] and "the model's own guess" in seen[0]
    code = []
    W.review_candidate(replace(task(touch=('calc.py',)), goal=goal), tmp_path, 'google/y',
                       lambda r, root, m, prompt_override: code.append(prompt_override) or invoke(r, root, m, prompt_override),
                       baseline={'calc.py': b'old\n'})
    assert goal in code[0]
