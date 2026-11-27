"""fac-light-manual: without --channels, once() and model_attempt check GOOGLE_GENERATIVE_AI_API_KEY; the light engine
must read that same name, not a second one (critics 19.11). The first task the factory did on its own code."""
import json

from tools import agent_factory as F
from tools import agent_factory_runner as W

BLOCK = 'calc.py\n<<<<<<< SEARCH\ndef add(a,b): return a-b\n=======\ndef add(a,b): return a+b\n>>>>>>> REPLACE\n'


def test_the_light_engine_reads_the_same_google_key_as_kilo_when_no_channel_names_one(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')
    (tmp_path / 'calc.py').write_text('def add(a,b): return a-b\n')
    task = F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    keys = []

    def post(url, key, body, timeout):
        keys.append(key)
        answer = dict(choices=[dict(message=dict(content=BLOCK), finish_reason='stop')],
                      usage=dict(prompt_tokens=10, completion_tokens=5))
        return 200, json.dumps(answer).encode()
    rc, _, _ = W.light_attempt(task, tmp_path, 'google/gemini-3.5-flash-lite', prompt_override='p', post=post)
    assert rc == 0 and keys == ['synthetic']
