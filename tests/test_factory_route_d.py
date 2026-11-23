"""Route barriers #18-#30 (D): quota use through the real channel functions; no network, no model."""
import inspect
import json

import pytest

from tools import agent_factory as F
from tools import agent_factory_runner as W
from tools import factory_channels as C

NOW = 1_800_000_000.0
ENV = {'K1': 'a', 'K2': 'b'}


def ch(cid, group, model, key='K1', tier='main'):
    return dict(id=cid, group=group, model=model, key_env=key, tpm=100000, rpd=100, rpm=10, tier=tier)


A1 = ch('a1', 'g1', 'google/m-a')      # model A on key 1
B1 = ch('b1', 'g1', 'google/m-b')      # model B on key 1 (same project)
A2 = ch('a2', 'g2', 'google/m-a', 'K2')   # model A on key 2


def err429(quota_id):
    body = {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', 'message': 'quota',
                      'details': [{'violations': [{'quotaId': quota_id}]}]}}
    return json.dumps({'type': 'error', 'error': {'name': 'APIError', 'data': {
        'statusCode': 429, 'message': 'quota', 'responseBody': json.dumps(body)}}}).encode()


def test_a_per_model_daily_quota_cools_only_that_model_on_that_key():
    info = C.classify(err429('GenerateRequestsPerDayPerProjectPerModel-FreeTier'), b'', 1)
    state = {}
    C.apply_failure(state, A1, info, env=ENV, now=NOW)
    assert C.cooled_until(state, A1) > NOW
    assert C.cooled_until(state, B1) <= NOW        # the other model of the same project works
    assert C.cooled_until(state, A2) <= NOW        # and the same model on the other key


def test_a_project_level_daily_quota_still_cools_the_project():
    info = C.classify(err429('GenerateRequestsPerDayPerProject-FreeTier'), b'', 1)
    state = {}
    C.apply_failure(state, A1, info, env=ENV, now=NOW)
    assert C.cooled_until(state, B1) > NOW


def test_a_task_keeps_its_key_while_it_has_quota_even_when_the_other_key_has_more_left():
    state = {}
    first = C.reserve(state, A1, 100, now=NOW, affinity='task:T1')
    assert first is not None
    for _ in range(5):                  # key 1 is busier than key 2: the balancer alone would pick key 2
        C.reserve(state, A1, 100, now=NOW)
    pick = C.choose([A1, A2], state, 100, ENV, now=NOW + 1, affinity='task:T1')
    assert pick['id'] == 'a1'
    assert C.choose([A1, A2], state, 100, ENV, now=NOW + 1)['id'] == 'a2'      # no affinity: balanced


def test_tier_floor_gives_the_escalation_tier_first():
    small, main, esc = ch('s', 'g1', 'google/s', tier='small'), ch('m', 'g1', 'google/m'), ch('e', 'g1', 'google/e', tier='escalation')
    assert C.route_order([small, main, esc], 'code', 1, 100)[0]['id'] == 'm'
    assert C.route_order([small, main, esc], 'code', 2, 100)[0]['id'] == 'e'


def test_small_follow_up_is_off_by_default_by_the_data():
    assert inspect.signature(W._once).parameters['small_follow_up'].default is False
    assert inspect.signature(W._pass_inner).parameters['small_follow_up'].default is False
    src = inspect.getsource(W.main)
    assert '"--small-follow-up", choices=("on", "off"), default="off"' in src


def test_an_empty_answer_does_not_cool_the_whole_model():
    info = C.classify(W._light_error(None, b'x', 'EmptyAnswer'), b'', 1)
    state = {}
    out = C.apply_failure(state, A1, info, env=ENV, now=NOW)
    assert C.cooled_until(state, A1) <= NOW and C.cooled_until(state, A2) <= NOW
    assert out['action'] == 'none'


def test_the_hard_ceiling_is_plain_characters_the_router_weighs_cyrillic():
    # live 22.11 00:05-00:20: the weighted ceiling blocked 22-25 k character Russian prompts that passed before
    assert not C.prompt_too_large('a' * (C.PROMPT_LIMIT_CHARS - 10))
    assert C.prompt_too_large('a' * (C.PROMPT_LIMIT_CHARS + 1))
    assert not C.prompt_too_large('я' * 22711)
    assert C.estimate_tokens(14000, 0, cyrillic=1.0) > C.estimate_tokens(14000, 0, cyrillic=0.0)   # the router's weight


def _body(tmp_path, monkeypatch, model):
    for name in ('OPENROUTER_API_KEY', 'GOOGLE_GENERATIVE_AI_API_KEY'):
        monkeypatch.setenv(name, 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    task = F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    bodies = []

    def post(url, key, body, timeout):
        bodies.append(body)
        return 200, json.dumps(dict(choices=[dict(message=dict(content='x'), finish_reason='stop')])).encode()
    W.light_attempt(task, tmp_path, model, prompt_override='p', post=post)
    return bodies[0]


def test_reasoning_budget_only_goes_to_models_that_support_it(tmp_path, monkeypatch):
    assert 'reasoning' not in _body(tmp_path, monkeypatch, 'openrouter/unknown-lab/plain-model:free')
    assert 'reasoning' in _body(tmp_path, monkeypatch, 'openrouter/nvidia/nemotron-example:free')


def test_a_shaky_model_does_not_come_first_just_because_it_is_preferred():
    good, shaky = ch('g', 'g1', 'google/good'), ch('s', 'g1', 'google/shaky')
    state = {'channel_stats': {'s': {'model': 'google/shaky', 'results': [1, 0, 0, 1, 0, 1, 1, 0, 1, 1]},   # 0.6
                               'g': {'model': 'google/good', 'results': [1] * 10}}}
    order = C.route_order([shaky, good], 'code', 1, 100, preferred='google/shaky', state=state)
    assert order[0]['id'] == 'g'
    state['channel_stats']['s']['results'] = [1] * 10
    assert C.route_order([shaky, good], 'code', 1, 100, preferred='google/shaky', state=state)[0]['id'] == 's'


def test_a_retry_after_header_of_a_quota_reaches_the_classifier():
    raw = W._with_retry_after(b'{"error": {"code": 429, "message": "slow"}}', '37')
    info = C.classify(W._light_error(429, raw), b'', 1)
    assert info['retry_after_s'] == 37


def test_the_reviewer_verdict_is_the_last_json_object_of_the_answer():
    text = 'Looking at {the diff} first. {"approved": false, "reasons": ["draft"]}\nFinal: ```json\n{"approved": true, "reasons": []}\n```'
    assert W._last_json_object(text) == {'approved': True, 'reasons': []}
    assert W._last_json_object('prose {not json} only') is None
