"""The code a model asked for comes first. Live 20.11 03:18 (<id>): three tournament candidates in a row answered
CANNOT: _last_clause_question, a 28-line function of a 145 KB file: smaller functions the task text names filled the
4.5 KB room of the view, and every later candidate got the very same view. Now a definition a model asked for
('CANNOT: name', or the runner's "function 'name' was not shown whole") is shown first and whole, to the next
candidate of the pass as to the next pass."""
import json

from tools import factory_context as X

BIG = 'def wanted(text):\n' + ''.join('    text = text.replace("%d", "%d")\n' % (i, i + 1) for i in range(40)) + \
    '    return text\n'
BODY_LINE = '    text = text.replace("17", "18")'


def _smalls(n):
    return ''.join('def small_%d(x):\n    return x + %d\n\n\n' % (i, i) for i in range(n))


def test_asked_names_reads_cannot_and_the_not_shown_whole_refusal():
    assert X.asked_names('the model answered CANNOT: _last_clause_question') == {'_last_clause_question'}
    assert X.asked_names("1: function 'Gate.close' was not shown whole: use SEARCH/REPLACE") == {'close'}
    assert X.asked_names('edit blocks 2, changed files 0') == frozenset() and X.asked_names(None) == frozenset()


def test_an_asked_definition_is_shown_whole_before_the_names_of_the_task_text():
    source = _smalls(40) + BIG
    priority = frozenset('small_%d' % i for i in range(40))
    plain = X._fragments(source, set(priority) | {'wanted'}, 2200, priority)
    assert BODY_LINE not in plain                                        # the small named ones fill the room
    first = X._fragments(source, set(priority) | {'wanted'}, 2200, priority, asked=frozenset({'wanted'}))
    assert 'def wanted(text):\n' + BIG.split('\n', 1)[1].rstrip('\n') in first      # whole, every line


def test_a_nested_definition_the_model_asked_for_is_shown_too():
    source = 'def outer(a):\n' + ''.join('    a += %d\n' % i for i in range(300)) + \
        '    def inner(b):\n        return b * 2\n    return inner(a)\n'
    out = X._fragments(source, {'outer'}, 3000, frozenset(), asked=frozenset({'inner'}))
    assert 'def inner(b):\n        return b * 2' in out


def test_the_coder_prompt_shows_what_the_feedback_says_the_model_asked_for():
    from tools import agent_factory_runner as W
    from tools.agent_factory import read_plan
    task = read_plan([dict(id='T1', title='fix small_1', touch_files=['big.py'], read_files=[],
                           tests=['tests/test_big.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    visible = {'big.py': (_smalls(500) + BIG).encode(), 'tests/test_big.py': b'def test_x():\n    assert True\n'}
    assert BODY_LINE not in W.build_coder_prompt(task, visible, None, light=True)
    assert BODY_LINE in W.build_coder_prompt(task, visible, 'the model answered CANNOT: wanted', light=True)
    assert BODY_LINE in W.build_coder_prompt(task, visible, None, light=True, asked=frozenset({'wanted'}))


def test_the_next_candidate_of_the_pass_is_shown_the_code_the_previous_one_asked_for(tmp_path, monkeypatch):
    from tests.test_factory_runtime import FIX_BLOCK, Rig, approval_json
    rig = Rig(tmp_path, monkeypatch)
    sent = []

    def post(url, key, body, timeout):
        review = body['messages'][0]['content'] == rig.w.LIGHT_REVIEW_RULES
        sent.append(dict(model=body['model'], review=review, prompt=body['messages'][1]['content']))
        content = (approval_json() if review else
                   'CANNOT: add' if body['model'] == 'x' else FIX_BLOCK)
        return 200, json.dumps(dict(choices=[dict(message=dict(content=content), finish_reason='stop')],
                                    usage=dict(prompt_tokens=900, completion_tokens=40))).encode()
    monkeypatch.setattr(rig.w, 'engine_for', lambda role, task: 'light')
    monkeypatch.setattr(rig.w, '_light_post', post)
    built = []
    real = rig.w.build_coder_prompt

    def spy(*args, **kwargs):
        built.append(frozenset(kwargs.get('asked') or ()))
        return real(*args, **kwargs)
    monkeypatch.setattr(rig.w, 'build_coder_prompt', spy)
    result = rig.once()
    coders = [s for s in sent if not s['review']]
    assert [s["model"] for s in coders] == ["x", "y"] and result["status"] == "REVIEW", (result.get("blocked_reason"), result.get("reason"), result.get("reason_detail"), result.get("events"))
    assert built == [frozenset(), frozenset({'add'})]                    # the second view was built for it
    assert 'The code it asked for (add) is shown above now' in coders[1]['prompt']
    assert 'The code it asked for' not in coders[0]['prompt']
