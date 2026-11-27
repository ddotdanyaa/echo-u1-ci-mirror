# factory-backlog-id: U108.s1
import time
import pytest
from echo_sync import codex_road as CR

class _FakeClient:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

def test_codex_transport_quota_backoff(monkeypatch):
    slept = []
    def mock_sleep(s):
        slept.append(s)
    monkeypatch.setattr(time, 'sleep', mock_sleep)
    
    client = _FakeClient()
    # We use a factory that returns the same client instance
    transport = CR.CodexTransport(lambda: ('tok', 'acc'), client_factory=lambda: client)
    
    class _SuccessResponse:
        def __iter__(self):
            yield 'hello'
    
    attempts = [0]
    # Signature must match: CodexTransport._once(self, client, headers, request, cancelled)
    # Since we patch CR._once, the first argument passed by the caller is 'self'
    def fake_once(self, client, headers, request, cancelled):
        attempts[0] += 1
        if attempts[0] == 1:
            raise CR.FastTextError('usage_limit')
        return _SuccessResponse()
    
    monkeypatch.setattr(CR.CodexTransport, '_once', fake_once)
    
    class Cancelled:
        def is_set(self):
            return False

    # On current code, this will raise FastTextError because the retry logic 
    # in __call__ only handles _dead_socket(error) and doesn't check failed_token(error)
    # and doesn't implement the sleep/retry for quota.
    with pytest.raises(CR.FastTextError) as excinfo:
        list(transport({'x': 1}, Cancelled()))
    
    assert 'usage_limit' in str(excinfo.value)
    # The test fails here because slept is empty; it should have contained PRIMARY_QUOTA_REST_S
    assert len(slept) == 1
    assert slept[0] == CR.PRIMARY_QUOTA_REST_S
