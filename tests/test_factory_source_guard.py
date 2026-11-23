"""Source guard of the factory (live 20.11): a size cap and two false secret alarms blocked rows for good.

The product's largest file (330 715 bytes) was refused under a 200 000-byte cap; six rows that named it read
'scope_violation' and the question to the head asked "which files?" without the cause. A size refusal is a resource
limit (context_too_large, retried on a new factory version), every refusal names its file, the head sees the refusal,
and code that only looks like a key (a key prefix inside a word, a keyword after 'password:') is staged.
"""
import json

import pytest

from tools import agent_factory as F
from test_factory_runtime import Rig, _kilo_engine  # noqa: <id>  (_kilo_engine: autouse)
from test_factory_loop import env  # noqa: <id>


def test_the_largest_product_file_is_staged_and_a_bigger_one_is_a_resource_limit(tmp_path, monkeypatch):
    big = tmp_path / 'cm_big.py'
    line = 'def handler_%06d(event):\n    return event\n\n'
    body = ''.join(line % i for i in range(8400))
    assert len(body.encode('utf-8')) > 330_000
    big.write_bytes(body.encode('utf-8'))   # bytes: text mode would add CR on Windows
    assert F.safe_source(big) == body.encode('utf-8')
    monkeypatch.setattr(F, 'SOURCE_MAX_BYTES', 100)
    with pytest.raises(F.InputTooLarge) as caught:
        F.safe_source(big)
    assert isinstance(caught.value, F.InvalidPlan) and 'cm_big.py' in str(caught.value)


def test_an_oversized_touch_file_blocks_as_context_too_large_and_names_it(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(F, 'SOURCE_MAX_BYTES', 10)
    result = rig.once()
    assert result['status'] == 'BLOCKED' and result['blocked_reason'] == 'context_too_large'
    assert 'calc.py' in result['reason_detail'] and not rig.models   # refused before any model is paid


def test_code_that_only_looks_like_a_key_is_staged_and_a_real_key_is_not(tmp_path):
    looks = {
        'sherpa.py': '"""the model alphacep/vosk-model-small-streaming-ru, int8"""\n',
        'urls.py': 'for parts in found:\n    if parts.username or parts.password:continue\n',
    }
    for name, text in looks.items():
        (tmp_path / name).write_text(text, encoding='utf-8')
        assert F.safe_source(tmp_path / name)
    real = {
        'a.py': "KEY = 's" + "k-" + 'a' * 24 + "'\n",
        'b.py': "my_password = 'synthetic_demo_1234'\n",
        'c.py': 'password: continueXYZ123 \n',
        'd.py': 'token = gs' + 'k_' + 'b' * 24 + '\n',
    }
    for name, text in real.items():
        (tmp_path / name).write_text(text, encoding='utf-8')
        with pytest.raises(F.InvalidPlan) as caught:
            F.safe_source(tmp_path / name)
        assert 'secret' in str(caught.value) and name in str(caught.value)
    # free text is masked as before: the guard of staged sources is narrower than redaction, never redaction itself
    assert '[REDACTED]' in F.redact('model vosk-model-small-streaming-ru')


def test_the_head_sees_why_a_scope_was_refused(env):
    env.set_row('T1', status='BLOCKED', blocked_reason='scope_violation',
                feedback=[{'source': 'gate', 'text': '[infra] scope_violation: input over 1000000 bytes: big_module.py'}])
    loop = env.loop(triage_fn=lambda **kw: {'tasks': [], 'holds': [], 'stale': [], 'skipped': []})
    loop.step()   # TRIAGE (empty)
    loop.step()   # HOLD writes the questions
    text = (env.state_dir / 'opus_questions.md').read_text(encoding='utf-8')
    line = next(x for x in text.splitlines() if 'вопрос:' in x and 'Какие файлы менять' in x)
    assert 'Причина:' in line and 'big_module.py' in line
