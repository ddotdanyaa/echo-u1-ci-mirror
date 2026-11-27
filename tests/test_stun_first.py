"""CL1 / UP-02: the cloud channel of a call keeps HOST candidates first, STUN is the retry; there is no switch and no probe
parameter for the order (one rule, ``controlled_host.ice_tries``). ``open_subscription`` is ONE try; the retry of a failed open (any failure, once) is the loop of
``controlled_host.open_with_retry`` and its ``attempt`` picks the other configuration (route merge, 16.11).

Why the default stays host-first: the ECHO profile log of 2026-11-02 (05:50-12:48) has 39 of 39 successful opens with
``stun=False`` - the host-only first try connected every time (3.4-15.5 s) and no open ever needed the STUN retry that STUN-first was
meant to save. STUN puts its address gathering (aioice waits up to 5 s for one interface that never answers) into the OFFER phase of
every open. So the order is flipped only on evidence from A/B probes on one build, not here: these tests pin the default, the ORDER
of both settings, the fallback rule (a media-connect timeout only, never an unbounded retry, never on an auth or exchange error), that
both tries hand the same instructions to the session, and the numbers the ready line logs to explain a slow open.
"""
import asyncio
import json
import re
from types import SimpleNamespace

import pytest

import helpers_s6_fault as F
from echo_sync import controlled_host
from echo_sync.content_policy import ANSWER_POLICY
from echo_sync.controlled_host import open_subscription

STUN = ('stun:example.test:19302',)
RUNTIME = ('python', {}, (), '')


class Logger:
    def __init__(self):
        self.lines = []

    def info(self, message, *args):
        self.lines.append(message % args if args else message)

    warning = info


class Rig:
    """A helper pipe whose media only connects with the configurations in ``works_with`` ({'stun'}, {'host'}, both or none).

    ``offer_delay`` / ``exchange_delay`` are the virtual seconds the helper takes to hand over its offer and the subscription
    exchange takes to answer (what ICE gathering and the cloud cost in a real open)."""

    def __init__(self, works_with, *, stun=STUN, connect_timeout=5, break_after_connect=False, offer_delay=0, exchange_delay=0):
        self.works_with = set(works_with)
        self.bridges, self.sessions = [], []
        self.logger = Logger()
        self.break_after_connect = break_after_connect
        rig = self

        class Bridge:
            def __init__(self, *args, **kwargs):
                self.stun, self.stage, self.closed = None, 0, False
                rig.bridges.append(self)

            async def start(self):
                pass

            async def send(self, kind, payload=b''):
                if kind == 'C':
                    self.stun = json.loads(payload)['stun']

            async def receive(self, timeout):
                self.stage += 1
                if self.stage == 1:
                    if offer_delay:
                        await asyncio.sleep(offer_delay)
                    return ('O', b'v=0\n')
                if ('stun' if self.stun else 'host') not in rig.works_with:
                    await asyncio.sleep(timeout)
                    raise asyncio.TimeoutError()
                if self.stage == 2:
                    return ('R', b'')
                if rig.break_after_connect:
                    await asyncio.sleep(timeout)
                    raise asyncio.TimeoutError()
                return ('e', b'{"type":"session.started"}')

            async def close(self):
                self.closed = True

        self.factory = Bridge

        async def scoped(profile, function, executor=None):
            if exchange_delay:
                await asyncio.sleep(exchange_delay)
            return function()

        def create(sdp, **kwargs):
            rig.sessions.append(kwargs)
            return {'auth': 'subscription', 'transport': {'sdp': 'answer'}}

        self.api = SimpleNamespace(_run_scoped=scoped, _limiter_key=lambda profile: 'limiter', create_gpt_live_session=create,
                                   WATCH_AUDIO_CONNECT_TIMEOUT_S=connect_timeout, WATCH_AUDIO_STUN=stun, logger=self.logger)

    def open(self, monkeypatch, attempts=2, **options):
        """(the bridge that came back or the last error, virtual seconds spent): the open as the wire makes it - ``attempts`` tries of
        ``controlled_host.open_with_retry`` (the one loop: any failure is retried, ``attempt`` picks the configuration)."""
        async def body():
            F.patch_clock(monkeypatch)
            monkeypatch.setattr(controlled_host, 'UPSTREAM_OPEN_ATTEMPTS', attempts)
            started = asyncio.get_running_loop().time()
            try:
                result = await controlled_host.open_with_retry(lambda attempt: open_subscription(
                    self.api, 'echo-sync', 'unused', RUNTIME, bridge_factory=self.factory, attempt=attempt, **options))
            except Exception as error:
                result = error
            return result, asyncio.get_running_loop().time() - started
        return F.run(body)


def test_a_real_call_tries_host_candidates_first_and_stun_is_only_the_fallback(monkeypatch):
    """Break: STUN first on every real call - 39 of 39 opens of 2 Nov connected with host candidates alone, and STUN adds its
    address gathering (up to 5 s for one interface that never answers) in front of the offer of every one of them."""
    assert not hasattr(controlled_host, 'STUN_FIRST')
    assert controlled_host.ice_tries(SimpleNamespace(WATCH_AUDIO_STUN=STUN)) == ((), STUN)
    rig = Rig({'stun', 'host'})
    result, spent = rig.open(monkeypatch)                
    assert result is rig.bridges[0] and not result.closed
    assert [bridge.stun for bridge in rig.bridges] == [[]]
    assert len(rig.sessions) == 1 and spent < 1
    assert any('stun=False' in line for line in rig.logger.lines)
    fallback = Rig({'stun'}, connect_timeout=5)
    result, spent = fallback.open(monkeypatch)
    assert result is fallback.bridges[1] and not result.closed
    assert [bridge.stun for bridge in fallback.bridges] == [[], list(STUN)]
    assert fallback.bridges[0].closed and len(fallback.sessions) == 2
    assert 5 <= spent < 12


def test_when_neither_configuration_connects_there_are_two_tries_and_then_the_error(monkeypatch):
    """Break: a retry loop without an end would hold a call open for ever."""
    rig = Rig(set(), connect_timeout=5)
    result, spent = rig.open(monkeypatch)
    assert isinstance(result, TimeoutError)
    assert len(rig.bridges) == 2 and all(bridge.closed for bridge in rig.bridges)
    assert [bridge.stun for bridge in rig.bridges] == [[], list(STUN)]
    assert spent < 2 * 5 + 5, 'two bounded tries'


def test_open_subscription_makes_one_try_even_when_the_media_had_connected(monkeypatch):
    """Break: a second loop of retries inside the open (next to the one of the wire) - one rule for the retry, in one place."""
    rig = Rig({'stun', 'host'}, break_after_connect=True)
    result, _ = rig.open(monkeypatch, attempts=1)
    assert isinstance(result, TimeoutError)
    assert len(rig.bridges) == 1 and rig.bridges[0].closed


@pytest.mark.parametrize('failure', ['no offer', 'offer timed out', 'exchange refused', 'exchange timed out', 'not a subscription',
                                     'closed before ready', 'setup refused'])
def test_a_failed_try_of_open_subscription_is_one_try_whatever_failed(monkeypatch, failure):
    """Break: open_subscription retrying by itself (its own rule, next to the wire's: any failure, once) - it raises and closes its helper."""
    rig = Rig({'stun', 'host'})
    original = rig.factory.receive

    async def receive(bridge, timeout):
        if failure == 'no offer' and bridge.stage == 0:
            bridge.stage += 1
            return None
        if failure == 'offer timed out' and bridge.stage == 0:
            bridge.stage += 1
            raise asyncio.TimeoutError()
        if failure == 'closed before ready' and bridge.stage == 1:
            bridge.stage += 1
            return ('X', b'')
        if failure == 'setup refused' and bridge.stage == 1:
            bridge.stage += 1
            return ('e', b'{"type":"error"}')
        return await original(bridge, timeout)
    rig.factory.receive = receive
    if failure in ('exchange refused', 'exchange timed out'):
        async def refused(profile, function, executor=None):
            raise RuntimeError('refused') if failure == 'exchange refused' else asyncio.TimeoutError()
        rig.api._run_scoped = refused
    if failure == 'not a subscription':
        rig.api.create_gpt_live_session = lambda sdp, **kwargs: {'auth': 'api', 'transport': {'sdp': 'answer'}}
    result, _ = rig.open(monkeypatch, attempts=1)
    assert isinstance(result, (RuntimeError, TimeoutError))
    assert len(rig.bridges) == 1 and rig.bridges[0].closed


def test_with_no_stun_server_configured_there_is_one_try_not_two_identical_ones(monkeypatch):
    rig = Rig(set(), stun=(), connect_timeout=5)
    result, _ = rig.open(monkeypatch, attempts=1)
    assert isinstance(result, TimeoutError) and len(rig.bridges) == 1 and rig.bridges[0].stun == []
    result, _ = rig.open(monkeypatch)      # the retry has nothing else to try but the same configuration
    assert [bridge.stun for bridge in rig.bridges[1:]] == [[], []]


def test_both_tries_hand_the_same_instructions_to_the_session(monkeypatch):
    rig = Rig({'stun'})
    rig.open(monkeypatch, instructions='POLICY + LESSON')
    assert [session['_content_instructions'] for session in rig.sessions] == ['POLICY + LESSON', 'POLICY + LESSON']
    assert all(session['billing'] == 'subscription' and session['call_opening'] is False for session in rig.sessions)


def test_without_instructions_the_session_gets_the_bare_policy(monkeypatch):
    bare = Rig({'host'})
    bare.open(monkeypatch)
    assert bare.sessions[0]['_content_instructions'] == ANSWER_POLICY


def ready_line(rig):
    return next(line for line in rig.logger.lines if line.startswith('Controlled media ready'))


def test_the_ready_line_tells_how_long_the_offer_and_the_exchange_took_as_plain_numbers(monkeypatch):
    """Break: the 8-15 s opens of 2 Nov stay unexplained - nothing in the log says whether the helper (ICE gathering) or the cloud was slow."""
    rig = Rig({'host'}, offer_delay=1.5, exchange_delay=2.0)
    result, _ = rig.open(monkeypatch)
    assert result is rig.bridges[0]
    line = ready_line(rig)
    assert re.fullmatch(r'Controlled media ready stun=(True|False) elapsed_ms=\d+ offer_ms=\d+ exchange_ms=\d+', line), line
    numbers = {name: int(value) for name, value in re.findall(r'(\w+_ms)=(\d+)', line)}
    assert numbers['offer_ms'] == 1500 and numbers['exchange_ms'] == 2000 and numbers['elapsed_ms'] == 3500, line


def test_the_offer_and_exchange_numbers_belong_to_the_try_that_opened_the_channel(monkeypatch):
    """Break: after a fallback the numbers would add up the failed try as well and the slow phase could not be told from the wait."""
    rig = Rig({'stun'}, connect_timeout=5, offer_delay=1.5, exchange_delay=2.0)
    result, _ = rig.open(monkeypatch)
    assert result is rig.bridges[1]
    numbers = {name: int(value) for name, value in re.findall(r'(\w+_ms)=(\d+)', ready_line(rig))}
    assert numbers['offer_ms'] == 1500 and numbers['exchange_ms'] == 2000
    assert numbers['elapsed_ms'] == 3500, 'elapsed_ms is of this try (the retry is a new open)'


def test_a_failure_is_logged_with_its_phase_and_class(monkeypatch):
    rig = Rig(set(), connect_timeout=5)
    rig.open(monkeypatch)
    assert any('setup failed phase=subscription_channel type=TimeoutError' in line for line in rig.logger.lines)
