"""U31 (cold start: the first session after idle is ready at 15 s, the second at 1.8 s; the cause of the slow ``upstream_open`` was never measured, the trace of the first
probe was off). Two things the cloud can prove from code, on virtual time (the numbers below are the test's own, NOT a measurement of the laptop or the phone):

1. every open is traced by default, stage by stage, with the time since it began: ``open_subscription(marks=...)`` fills ``helper`` (the helper process started, or ``spare`` when a
   started one was taken), ``offer`` (the helper's ICE offer), ``instructions`` (the call's text was ready), ``exchange`` (the cloud's answer: sign-in, TLS and the request),
   ``connected`` (the media channel), ``started`` (the session). A failed open keeps the stages it reached. The host writes them to the agent log and the call trace.
2. a spare helper (helper_pool) that nobody takes is not left to go stale: after half its age limit the idle line replaces it, so the first open after a long idle finds a started one
   (before: ``take`` refused a spare older than ``max_age_s`` - 30 minutes - and the open paid the helper start, offer_ms 5-11 s against 1.2 s warm).
"""
import asyncio
import logging
from types import SimpleNamespace

import pytest

from echo_sync import helper_pool
from echo_sync.controlled_host import open_subscription


class Clock:
    now = 100.0

    def __call__(self): return self.now      # noqa: E704


def rig(clock, *, start=3.0, offer=1.2, exchange=0.5, channel=0.4, session=0.1, refuse=False):
    made = []

    class Bridge:
        def __init__(self, *args, **kwargs): self.stage, self.closed, self.process = 0, False, SimpleNamespace(returncode=None); made.append(self)  # noqa: E704

        async def start(self): clock.now += start  # noqa: E704

        async def send(self, kind, payload): pass  # noqa: E704

        async def receive(self, timeout):
            self.stage += 1
            clock.now += (offer, channel, session)[min(self.stage, 3) - 1]
            return (('O', b'v=0\n'), ('R', b''), ('e', b'{"type":"session.started"}'))[min(self.stage, 3) - 1]

        async def close(self): self.closed = True; self.process.returncode = 0  # noqa: E702,E704

    async def scoped(profile, fn):
        clock.now += exchange
        if refuse:
            raise RuntimeError('refused')
        return {'auth': 'subscription', 'transport': {'sdp': 'answer'}}

    return made, Bridge, SimpleNamespace(_run_scoped=scoped, WATCH_AUDIO_CONNECT_TIMEOUT_S=5, WATCH_AUDIO_STUN=(), logger=logging.getLogger('echo-sync'))


def test_every_open_names_its_stages_with_the_time_since_it_began(caplog):
    caplog.set_level(logging.INFO)
    clock = Clock()
    made, Bridge, api = rig(clock)
    marks = {}
    asyncio.run(open_subscription(api, 'p', 'unused', ('python', {}, (), ''), bridge_factory=Bridge, marks=marks, clock=clock))
    assert marks == {'helper': 3000, 'offer': 4200, 'instructions': 4200, 'exchange': 4700, 'connected': 5100, 'started': 5200}, marks
    assert list(marks) == ['helper', 'offer', 'instructions', 'exchange', 'connected', 'started'], 'in the order they happened'
    line = next(r.getMessage() for r in caplog.records if 'Controlled media open stages' in r.getMessage())
    assert 'stages=helper:3000,offer:4200,instructions:4200,exchange:4700,connected:5100,started:5200' in line, 'the log line of every open has them, trace or not'


def test_a_taken_spare_says_so_and_a_failed_open_keeps_the_stages_it_reached(caplog):
    caplog.set_level(logging.INFO)
    clock = Clock()
    made, Bridge, api = rig(clock, refuse=True)
    spare = helper_pool.SpareHelper(Bridge, clock=clock)
    marks = {}

    async def run():
        await spare.ensure()
        clock.now += 1000
        with pytest.raises(RuntimeError):
            await open_subscription(api, 'p', 'unused', ('python', {}, (), ''), bridge_factory=Bridge, spare=spare, marks=marks, clock=clock)
        await spare.close()
    asyncio.run(run())
    assert marks == {'spare': 0, 'offer': 1200, 'instructions': 1200}, 'a started helper: no start in the open; the exchange was refused, so nothing after it'
    assert any('setup failed' in r.getMessage() and 'stages=spare:0,offer:1200,instructions:1200' in r.getMessage() for r in caplog.records)


def test_an_idle_spare_is_renewed_before_it_is_too_old_to_be_taken():
    clock = Clock()
    made, Bridge, api = rig(clock, start=0)

    async def sleep(seconds):      # virtual time: wakes when the test has moved the clock far enough
        until = clock.now + seconds
        while clock.now < until:
            await asyncio.sleep(0)
    spare = helper_pool.SpareHelper(Bridge, max_age_s=1800, clock=clock, sleep=sleep)

    async def run():
        await spare.ensure()
        for _ in range(12):                      # three hours of an idle line, 15 minutes at a time
            clock.now += 900
            for _ in range(20):
                await asyncio.sleep(0)
            assert spare._fresh(), 'the spare is never older than its limit'
        assert len(made) >= 6 and all(old.closed for old in made[:-1]), 'the old ones were closed as they were replaced'
        bridge = spare.take()
        assert bridge is not None and bridge.process.returncode is None, 'after hours of idle line the next open still finds a started helper'
        await spare.close()
    asyncio.run(run())


def test_a_spare_that_was_taken_is_not_renewed_behind_the_call():
    clock = Clock()
    made, Bridge, api = rig(clock, start=0)

    async def sleep(seconds):
        until = clock.now + seconds
        while clock.now < until:
            await asyncio.sleep(0)
    spare = helper_pool.SpareHelper(Bridge, max_age_s=1800, clock=clock, sleep=sleep)

    async def run():
        await spare.ensure()
        assert spare.take() is made[0]
        clock.now += 5000
        for _ in range(20):
            await asyncio.sleep(0)
        assert len(made) == 1 and spare.bridge is None, 'the call has it; the new one is the call-end ensure(), as before'
        await spare.close()
    asyncio.run(run())


# --- the host: where the stages go ------------------------------------------------------------------------------------------------------------

def test_a_phone_call_has_its_open_stages_in_its_trace_and_a_probe_streams_them_to_its_client(tmp_path, monkeypatch):
    import json
    import helpers_s6_fault as F

    async def phone():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path / 'phone', monkeypatch) as host:
            await host.handshake()
        files = sorted((host.home / 'logs' / 'echo_calls').glob('*.jsonl'))
        return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]

    async def probe():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path / 'probe', monkeypatch, query={'echo_trace': '1'}) as host:
            host.ws.push({'type': 'session.update', 'session': {}})
            assert await host.until(lambda: any(f.type == 'session.updated' for f in host.ws.frames), 120)
            return [f.data for f in host.ws.frames if f.type == 'conduit.echo.observation' and 'open_stages' in f.data]
    rows = F.run(phone)
    stages = [r for r in rows if r['ev'] == 'open_stages']
    assert len(stages) == 1 and {'helper', 'offer', 'exchange', 'started'} <= set(stages[0]) and isinstance(stages[0]['since_serve_ms'], int), stages
    seen = F.run(probe)
    assert len(seen) == 1 and {'helper', 'offer', 'exchange', 'started'} <= set(seen[0]['open_stages']), seen
