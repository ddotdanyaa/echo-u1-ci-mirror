"""fac-light-reasoning: Nemotron 3 Ultra (OpenRouter, free) spent the whole 8192-token output cap on reasoning in
4 of 4 live repair calls (19.11 19:41-19:54: tokens_out 8192 = tokens_reasoning 8192, no edit block). A probe showed
that the unified `reasoning` parameter bounds it (662 -> 339 reasoning tokens, the same edit). The light engine must
give an OpenRouter call a reasoning budget that leaves the answer room, and must not send that field to Google."""
import json

from tools import agent_factory as F
from tools import agent_factory_runner as W

BLOCK = 'calc.py\n<<<<<<< SEARCH\ndef add(a,b): return a-b\n=======\ndef add(a,b): return a+b\n>>>>>>> REPLACE\n'


def _body(tmp_path, monkeypatch, model):
    for name in ('OPENROUTER_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_GENERATIVE_AI_API_KEY'):
        monkeypatch.setenv(name, 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    task = F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    bodies = []

    def post(url, key, body, timeout):
        bodies.append(body)
        answer = dict(choices=[dict(message=dict(content=BLOCK), finish_reason='stop')],
                      usage=dict(prompt_tokens=10, completion_tokens=5))
        return 200, json.dumps(answer).encode()
    rc, _, _ = W.light_attempt(task, tmp_path, model, prompt_override='p', post=post)
    assert rc == 0 and len(bodies) == 1
    return bodies[0]


def test_an_openrouter_call_bounds_reasoning_and_leaves_the_answer_room(tmp_path, monkeypatch):
    body = _body(tmp_path, monkeypatch, 'openrouter/nvidia/nemotron-3-u' 'ltra-550b-aQX55b:free')
    budget = (body.get('reasoning') or {}).get('max_tokens')
    assert type(budget) is int and 0 < budget <= body['max_tokens'] // 2


def test_a_google_call_carries_no_reasoning_field(tmp_path, monkeypatch):
    assert 'reasoning' not in _body(tmp_path, monkeypatch, 'google/gemini-3.5-flash-lite')
