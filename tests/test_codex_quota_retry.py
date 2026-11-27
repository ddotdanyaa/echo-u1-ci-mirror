# factory-backlog-id: U108.s1
import threading
import time
import pytest
from echo_sync import codex_road as CR
from echo_sync import reserve_text
from echo_sync.reserve_text import Roads


class _FakeClient:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_codex_transport_quota_backoff(monkeypatch):
    """A usage limit is carried by the transport as the token 'usage_limit' (no retry, no wait inside a job with a
    4 s budget); the rest of the first road, PRIMARY_QUOTA_REST_S, is kept by Roads (reserve_text._rest)."""
    slept = []
    monkeypatch.setattr(time, 'sleep', slept.append)
    transport = CR.CodexTransport(lambda: ('tok', 'acc'), client_factory=lambda: _FakeClient())
    attempts = [0]

    def fake_once(self, client, headers, request, cancelled):
        attempts[0] += 1
        raise CR.FastTextError('usage_limit')
        yield

    monkeypatch.setattr(CR.CodexTransport, '_once', fake_once)
    with pytest.raises(CR.FastTextError) as excinfo:
        list(transport({'x': 1}, threading.Event()))
    assert 'usage_limit' in str(excinfo.value)
    assert attempts[0] == 1          # a quota refusal is not retried by the transport
    assert slept == []               # and the transport does not wait: the rest belongs to Roads
    failure = excinfo.value

    def refuses(request, cancelled):
        raise failure
        yield
    reserve_text._PRIMARY['until'] = 0.0
    try:
        with pytest.raises(CR.FastTextError):
            list(Roads(refuses, None, clock=lambda: 100.0)({'x': 1}, threading.Event()))
        assert reserve_text._PRIMARY['until'] == 100.0 + reserve_text.PRIMARY_QUOTA_REST_S
        assert reserve_text.PRIMARY_QUOTA_REST_S > 4.0
    finally:
        reserve_text._PRIMARY['until'] = 0.0
