"""V6 U09 (= R6, H31-02): «ready=False on short calls (К10)»: the cause is unknown from the logs of 07.11; what was missing is the observation: the close code of the phone's socket and the stages before ready (U07-S1,
523e79d, written into the call trace). Guard through the real ``controlled_host.serve`` (HostRig, virtual time): a call that ends before ready names who closed it and with what code (the phone, 1006),
and a call whose cloud channel was lost names the cloud (1011) with ``ready`` as it was. The CAUSE of the 07.11 short calls cannot be found by a test: the journals of that day (cloudflared, agent.log) are
the evidence; nothing here claims it."""
import helpers_s6_fault as F
from test_ux_call_trace_host import WebSocketDisconnect, read_trace
from test_helper_stall import packet, stall
from helpers_spoken_diagnostics import run_host
from echo_sync import controlled_host


def test_who_closed_names_the_closer_and_the_code_in_every_case():
    assert controlled_host.who_closed(None, {'by': 'cloud', 'code': 1011}) == ('cloud', 1011)
    assert controlled_host.who_closed(WebSocketDisconnect(1006), {'by': None, 'code': None}) == ('phone', 1006)
    assert controlled_host.who_closed(RuntimeError('x'), {'by': None, 'code': None}) == ('host', None)
    assert controlled_host.who_closed(None, {'by': None, 'code': None}) == ('host', None)


def test_a_call_that_ends_before_ready_has_its_close_code_its_closer_and_its_stages_in_the_trace(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.advance(0.5)
            host.ws.inbox.put_nowait(WebSocketDisconnect(1006))
            await host.advance(1)
        last = read_trace(host.home)[-1]
        assert last['ev'] == 'call_close' and last['ready'] is False
        assert (last['closer'], last['close_code']) == ('phone', 1006)
    F.run(main)


def test_a_call_whose_cloud_channel_was_lost_goes_on_locally_and_its_end_still_names_who_closed_it(tmp_path, monkeypatch):
    """Owner rule (c22, ``helper_lost``): a channel that dies mid-call does NOT close the call, it falls into local mode in place. The loss is in the trace as the
    ``error`` line (``controlled_upstream_closed``); the call's end is then the phone's, with the code it carries."""
    async def body(host):
        stall(host)
        host.phone_audio(1)
        assert await host.until(lambda: any(r['ev'] == 'error' for r in read_trace(host.home)), 30)
        assert not host.finished and host.ws.close_code is None
        assert [r['code'] for r in read_trace(host.home) if r['ev'] == 'error'] == ['controlled_upstream_closed']
        host.ws.inbox.put_nowait(WebSocketDisconnect(1006))
        assert await host.until(lambda: host.finished, 5)
        last = read_trace(host.home)[-1]
        assert last['ev'] == 'call_close' and (last['closer'], last['close_code']) == ('phone', 1006), last
    run_host(tmp_path, monkeypatch, body)
