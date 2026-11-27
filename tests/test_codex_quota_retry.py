# factory-backlog-id: U108.s1
import time
import pytest
from echo_sync import codex_road as CR

class _FakeResponse:
    status_code = 200
    def iter_lines(self):
        yield 'data: {"type": "error", "error": {"code": "usage_limit"}}'
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

class _FakeClient:
    def stream(self, method, url, **kwargs):
        return _FakeResponse()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

def test_codex_transport_quota_backoff(monkeypatch):
    slept = []
    monkeypatch.setattr(time, 'sleep', lambda s: slept.append(s))
    
    made = [_FakeClient()]
    transport = CR.CodexTransport(lambda: ('tok', 'acc'), client_factory=lambda: made[0])
    
    # Make second attempt succeed
    class _SuccessResponse(_FakeResponse):
        def iter_lines(self):
            yield 'data: {"type": "response.output_text.delta", "delta": "hello"}'
            yield 'data: {"type": "response.completed"}'
    
    attempts = [0]
    def stream_side_effect(method, url, **kwargs):
        attempts[0] += 1
        if attempts[0] == 1:
            return _FakeResponse()
        return _SuccessResponse()
    
    made[0].stream = stream_side_effect
    
    res = list(transport({'x': 1}, type('C', (), {'is_set': lambda self: False})()))
    assert res == ['hello']
    assert len(slept) == 1
    assert slept[0] == CR.PRIMARY_QUOTA_REST_S
