"""fac-light-telemetry (critic 19.11, live data 19:44; confirmed again by critic round 1 at 21:33): a light call of
Nemotron was booked as actual_tokens 21 899 = 5 515 input + 8 192 output + 8 192 reasoning, although the provider's
completion_tokens already include the reasoning tokens (OpenAI usage schema). The light engine reports the Kilo
shape, where output and reasoning are apart: output = completion_tokens - reasoning_tokens."""
import json

from tools import agent_factory as F
from tools import agent_factory_runner as W


def _task():
    return F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']


def _reply(content, usage):
    body = dict(choices=[dict(message=dict(content=content), finish_reason='stop')], usage=usage)
    return lambda url, key, payload, timeout: (200, json.dumps(body).encode())


def test_reasoning_inside_completion_tokens_is_counted_once(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('x = 1\n')
    usage = dict(prompt_tokens=5515, completion_tokens=8192, completion_tokens_details=dict(reasoning_tokens=8192))
    _, out, _ = W.light_attempt(_task(), tmp_path, 'openrouter/nvidia/nemotron-ultra-big:free',
                                prompt_override='p', post=_reply('no block here', usage))
    s = W.event_summary(out, tmp_path)
    assert (s['input_tokens'], s['output_tokens'], s['reasoning_tokens']) == (5515, 0, 8192)


def test_a_model_without_reasoning_keeps_all_its_completion_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('x = 1\n')
    _, out, _ = W.light_attempt(_task(), tmp_path, 'google/gemini-3.5-flash-lite', prompt_override='p',
                                post=_reply('no block here', dict(prompt_tokens=900, completion_tokens=40)))
    s = W.event_summary(out, tmp_path)
    assert (s['input_tokens'], s['output_tokens'], s['reasoning_tokens']) == (900, 40, None)
