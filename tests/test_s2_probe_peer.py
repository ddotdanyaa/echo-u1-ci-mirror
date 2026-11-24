"""S2 (Strix): the probe switches of the address (echo_trace and what hangs on it) are the laptop's own.
A call that comes from a foreign peer or through the tunnel/proxy (cf-* / x-forwarded-for headers) is a plain phone call, whatever its query says.
Observable through controlled_host.serve (HostRig): a plain phone call is recorded; a probe that does not ask for the recording is not.
"""
import types

from echo_sync.controlled_host import probe_allowed
from test_u07_call_audio_host import pcm_root, run_call


def peer(host, address=None, headers=None):
    def prepare(rig):
        if address is not None:
            rig.ws.client = types.SimpleNamespace(host=address, port=1)
        if headers is not None:
            rig.ws.headers = headers
    return prepare


def test_a_local_probe_is_a_probe(tmp_path, monkeypatch):
    host = run_call(tmp_path, monkeypatch, prepare=peer(None, '127.0.0.1', {}), query={'echo_trace': '1'})
    assert not pcm_root(host.home).exists()


def test_a_foreign_peer_with_echo_trace_gets_a_plain_phone_call(tmp_path, monkeypatch):
    host = run_call(tmp_path, monkeypatch, prepare=peer(None, '203.0.113.7', {}), query={'echo_trace': '1'})
    assert pcm_root(host.home).exists(), 'not a probe: recorded like every phone call'


def test_the_tunnel_header_makes_a_loopback_peer_a_plain_call(tmp_path, monkeypatch):
    host = run_call(tmp_path, monkeypatch, prepare=peer(None, '127.0.0.1', {'CF-Connecting-IP': '198.51.100.1'}),
                    query={'echo_trace': '1', 'echo_pcm_record': '1', 'echo_debug_text': '1'})
    assert pcm_root(host.home).exists()
    assert not any('source_text_debug' in f.data for f in host.ws.frames), 'no debug text for a foreign client'


def test_probe_allowed_table():
    ws = lambda host, headers=None: types.SimpleNamespace(client=types.SimpleNamespace(host=host), headers=headers or {})
    assert probe_allowed(ws('127.0.0.1')) and probe_allowed(ws('::1'))
    assert not probe_allowed(ws('10.0.0.5'))
    assert not probe_allowed(ws('127.0.0.1', {'x-forwarded-for': '1.2.3.4'}))
    assert probe_allowed(types.SimpleNamespace(query_params={}))
