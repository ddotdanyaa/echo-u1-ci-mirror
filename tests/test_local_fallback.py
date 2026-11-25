"""The call must open and be useful when the cloud is unreachable (the profile's ``local_fallback``).

The owner's rehearsal of 06.11 failed twice (12:42:59 and 12:44:33): the laptop could not reach OpenAI (the TLS handshake timed out,
two attempts of 18 s) and both calls died after 36 s with ``controlled_upstream_unavailable``, although the bank, the law base, the chart
of accounts and the owner's material had answered in 0.6-0.8 s the same morning. These tests pin what the flag must do:

1. the controlled setup fails -> the call OPENS (the phone gets its ``session.updated`` and its readiness marker) and a bank question is
   answered from the local bank;
2. a law question is answered from the law base;
3. a question no local source answers gets ONE short honest line - never silence, never a loop, never over a cue that sounds;
4. the channel that dies MID-CALL falls into local mode in place, without closing the call;
5. the cloud comes back -> the SAME call upgrades to the full path and says one short line;
6. the flag off: everything is exactly as it was before it existed.
"""
import asyncio
import base64
import json

from cm_patch import patch_controller
import pytest

from echo_sync import settings as settings_module
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import LOCAL_PHRASES, NativeMediaSocket

PCM = b'\x00\x01' * 480                                    # 20 ms of 24 kHz 16-bit audio, as the phone sends it
VOICE = b'\x11\x22' * 2400                                 # 0.1 s of "spoken" PCM, enough to be playable


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


class Source:
    def __init__(self):
        self.frames = []
        self.closed = False

    async def send(self, kind, payload=b''):
        self.frames.append((kind, payload))

    async def close(self):
        self.closed = True


class Ear:
    """A stand-in for ``ear_shadow.ShadowEar``: it hands the transport the records the real one polls, and nothing else."""

    acting = False
    current = None

    def __init__(self, *records):
        self.records = list(records)
        self.fed = 0
        self.closed = False

    def feed(self, pcm, input_ms=None):
        self.fed += len(pcm)

    def poll(self):
        records, self.records = self.records, []
        return records

    def close(self):
        self.closed = True


def heard(text, uid='u1'):
    return {'uid': uid, 'text': text, 'offset': 0.0, 'onset_input_ms': 0, 'offset_input_ms': 0}


def build(tmp_path, *, connect, settings=None, synthesize=None, instant=None):
    spoken = []
    sent = []

    async def emit(frame):
        sent.append(frame)

    async def say(text, end=None):
        spoken.append(text)
        return VOICE

    controller = ControlledMedia(tmp_path / 's.db', session_id='s', lookup_policy='required',
                                settings=settings or {'words_per_portion': 6})
    if instant is not None:
        controller.instant = instant
    wire = NativeMediaSocket(controller, emit, connect, lambda _: None, synthesize or say)
    return wire, controller, sent, spoken


async def open_call(wire, sent):
    """The three frames the phone sends to open a call, and what the transport answers."""
    await wire.client({'type': 'session.update', 'session': {}})
    marker = 'conduit-ready-test'
    await wire.client({'type': 'response.create',
                       'response': {'conversation': 'none', 'input': [{'content': [{'text': marker}]}]}})
    turn = next((f for f in sent if f.get('type') == 'conduit.turn'), None)
    if turn is not None:
        await wire.client({'type': 'conduit.turn.done', 'turn_id': turn['turn_id']})
    # The «cloud unavailable» line is spawned, not awaited, so that the handshake is never held for a synthesis: let it land.
    await settle(wire, 10)
    return turn


async def settle(wire, rounds=8):
    """Let the tasks the transport spawned (a spoken line, a cue) run without waiting on real time."""
    for _ in range(rounds):
        await asyncio.sleep(0)


def cues(sent):
    return [f for f in sent if f.get('type') == 'response.audio.delta']


# ---- the flag itself -------------------------------------------------------------------------------------------------------

def test_the_key_is_gone_and_an_unreachable_cloud_opens_the_call_in_local_mode(tmp_path):
    """The owner's rule of the call, no key: a profile that still says ``local_fallback: off`` changes nothing."""
    assert 'local_fallback' not in settings_module.DEFAULTS and 'local_fallback' not in settings_module.resolve({'local_fallback': 'off'})

    async def run():
        async def connect():
            raise TimeoutError('handshake operation timed out')
        wire, _, sent, _ = build(tmp_path, connect=connect)
        await wire.client({'type': 'session.update'})
        assert wire.local_mode
        assert any(f['type'] == 'session.updated' for f in sent)
        assert not any(f.get('error', {}).get('code') == 'controlled_upstream_unavailable' and f.get('announce') for f in sent)
        await wire.close()
    asyncio.run(run())


# ---- 1. the setup fails and the call opens in local mode -------------------------------------------------------------------

def test_the_setup_fails_the_call_opens_and_the_bank_answers(tmp_path):
    """The owner's 12:42:59: the controlled setup cannot reach OpenAI. The call must open and the bank must answer."""
    async def run():
        attempts = []

        async def connect():
            attempts.append(1)
            raise TimeoutError('_ssl.c:1064: The handshake operation timed out')

        class Bank:
            """``instant.Instant`` as ``_reference`` uses it: one pre-rendered row of the bank."""
            def lookup(self, text, bank_only=False):
                if 'ндс' in text.lower():
                    return type('Hit', (), {'answer': 'Двадцать процентов.'})()
                return None

        wire, controller, sent, spoken = build(tmp_path, connect=connect, instant=Bank())
        marker = await open_call(wire, sent)
        # The call is OPEN: the phone got its session and its readiness marker, as on the full path.
        assert marker is not None and wire.ready and wire.local_mode and wire.source is None
        assert any(f['type'] == 'session.updated' for f in sent)
        assert any(f['type'] == 'response.done' for f in sent)
        assert len(attempts) == 2                           # the two open attempts of the full path, and then local mode
        # 2. the listener is told ONCE, in one short spoken line, why - and the channel phrase is NOT said on top of it.
        await settle(wire)
        assert spoken.count(LOCAL_PHRASES['local_opened']) == 1
        assert not any(f.get('type') == 'conduit.echo.stage' and f.get('stage') == 'diagnostic_start' for f in sent)
        assert any(f.get('error', {}).get('code') == 'controlled_upstream_unavailable' for f in sent)

        # The microphone is heard by the local ear and goes nowhere upstream (there is nothing upstream).
        wire.ear = Ear(heard('Какая ставка НДС в России'))
        await wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(PCM).decode()})
        assert wire.ear.fed == len(PCM)

        # 1. the bank answers the question the ear heard, through the controller's own reference path.
        await wire.tick()
        await settle(wire, 40)
        assert controller.local_answer and 'Двадцать' in controller.published
        assert any('Двадцать' in text for text in spoken)
        assert cues(sent)
        await wire.close()
    asyncio.run(run())


# ---- 1b. the law base -------------------------------------------------------------------------------------------------------

def test_a_law_question_is_answered_from_the_law_base_in_local_mode(tmp_path, monkeypatch):
    async def run():
        async def connect():
            raise TimeoutError('handshake timed out')

        import echo_sync.controlled_media as media
        patch_controller(monkeypatch, 'reference_lookup',
                            lambda text, history=(), **kw: 'Статья сто сорок восьмая — о сроке.' if 'статья' in text.lower() else None)
        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        assert wire.local_mode and wire.ready
        wire.ear = Ear(heard('Что говорит статья сто сорок восемь'))
        await wire.tick()
        await settle(wire, 40)
        assert controller.local_answer and 'сто сорок восьмая' in controller.published
        assert any('сто сорок восьмая' in text for text in spoken)
        await wire.close()
    asyncio.run(run())


# ---- 3. a question no local source answers ---------------------------------------------------------------------------------

def test_an_unknown_question_gets_one_short_honest_line_and_no_lookup(tmp_path):
    async def run():
        searched = []

        async def connect():
            raise TimeoutError('handshake timed out')

        async def lookup(question):
            searched.append(question)
            return []

        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        wire.lookup = lookup
        await open_call(wire, sent)
        spoken.clear()
        wire.ear = Ear(heard('Сколько стоит баррель нефти прямо сейчас'))
        await wire.tick()
        await settle(wire, 40)
        # One short honest line, and the search never left the laptop.
        assert spoken == [LOCAL_PHRASES['local_unknown']]
        assert not searched
        # Never a loop: the same question is told once.
        await wire.actions([{'type': 'lookup', 'epoch': controller.epoch, 'question': 'x',
                             'input_turn_id': controller.question_id}])
        await settle(wire)
        assert spoken == [LOCAL_PHRASES['local_unknown']]
        await wire.close()
    asyncio.run(run())


def test_the_honest_line_never_cuts_an_answer_that_is_already_sounding(tmp_path):
    """``lookup_moot``'s rule: the answer that sounds owns the question, so nothing is said over it."""
    async def run():
        async def connect():
            raise TimeoutError('handshake timed out')
        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        await settle(wire)
        spoken.clear()
        controller.local_answer = True
        controller.published = 'Двадцать процентов.'
        await wire.actions([{'type': 'lookup', 'epoch': controller.epoch, 'question': 'x', 'input_turn_id': 'q'}])
        await settle(wire)
        assert spoken == []
        await wire.close()
    asyncio.run(run())


# ---- 4. the channel dies mid-call -------------------------------------------------------------------------------------------

def test_a_channel_that_dies_mid_call_falls_into_local_mode_in_place(tmp_path):
    """A VPN flap during the rehearsal: the cloud dies with the call running. The call must not close, and the cursor must stay."""
    async def run():
        source = Source()

        async def connect():
            return source

        class Bank:
            def lookup(self, text, bank_only=False):
                return type('Hit', (), {'answer': 'Двадцать процентов.'})() if 'ндс' in text.lower() else None

        wire, controller, sent, spoken = build(tmp_path, connect=connect, instant=Bank())
        await open_call(wire, sent)
        assert wire.ready and not wire.local_mode and wire.source is source
        before = (controller.epoch, (controller.state() or {}).get('chunk_index'))

        fell = await wire.enter_local('helper_closed', source_lost=True)
        await settle(wire)
        assert fell and wire.local_mode and wire.source is None
        assert wire.ready                                   # the phone's session is untouched: no new handshake
        assert source.closed
        assert (controller.epoch, (controller.state() or {}).get('chunk_index')) == before
        assert spoken.count(LOCAL_PHRASES['local_opened']) == 1

        # And it is useful at once: the ear's question is answered from the bank.
        wire.ear = Ear(heard('Какая ставка НДС'))
        await wire.tick()
        await settle(wire, 40)
        assert controller.local_answer and 'Двадцать' in controller.published
        await wire.close()
    asyncio.run(run())


def test_a_second_complaint_of_the_same_dead_channel_says_nothing_new(tmp_path):
    """Its reader ends, its writer times out, its queue overflows: whoever notices next must not say the line again."""
    async def run():
        source = Source()

        async def connect():
            return source
        wire, _, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        assert await wire.enter_local('helper_closed', source_lost=True)
        await settle(wire)
        assert await wire.enter_local('write_timeout', source_lost=True)
        await settle(wire)
        assert spoken.count(LOCAL_PHRASES['local_opened']) == 1
        assert wire.local_mode and wire.ready
        await wire.close()
    asyncio.run(run())


# ---- 5. the cloud comes back ------------------------------------------------------------------------------------------------

def test_the_cloud_comes_back_and_the_same_call_upgrades(tmp_path, monkeypatch):
    async def run():
        import echo_sync.native_media_socket as nms
        monkeypatch.setattr(nms, 'LOCAL_RETRY_FIRST_S', 0)
        monkeypatch.setattr(nms, 'LOCAL_RETRY_EVERY_S', 0)
        source = Source()
        tries = []

        async def connect():
            tries.append(1)
            if len(tries) < 3:
                raise TimeoutError('handshake timed out')
            return source

        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        assert spoken.count(LOCAL_PHRASES['local_opened']) == 1      # it DID fall into local mode first
        for _ in range(200):
            if not wire.local_mode:
                break
            await asyncio.sleep(0)
        await settle(wire, 40)
        # The full path, in the SAME call: no restart, one short line, and the microphone goes upstream again.
        assert not wire.local_mode and wire.source is source and wire.ready
        assert len(tries) == 3
        assert spoken.count(LOCAL_PHRASES['local_back']) == 1
        assert sum(f['type'] == 'session.updated' for f in sent) == 1
        assert wire.input_bytes == 0                        # the new helper counts its own input clock from 0
        await wire.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(PCM).decode()})
        assert source.frames == [('P', PCM)]
        await wire.close()
    asyncio.run(run())


def test_a_quiet_retry_that_fails_says_nothing_and_keeps_answering_locally(tmp_path, monkeypatch):
    async def run():
        import echo_sync.native_media_socket as nms
        monkeypatch.setattr(nms, 'LOCAL_RETRY_FIRST_S', 0)
        monkeypatch.setattr(nms, 'LOCAL_RETRY_EVERY_S', 0)
        tries = []

        async def connect():
            tries.append(1)
            raise TimeoutError('handshake timed out')

        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        await settle(wire, 60)
        assert len(tries) > 1 and wire.local_mode
        assert spoken.count(LOCAL_PHRASES['local_opened']) == 1   # still once, however many tries failed
        assert LOCAL_PHRASES['local_back'] not in spoken
        assert not any(f.get('error', {}).get('code') == 'controlled_upstream_closed' for f in sent)
        await wire.close()
    asyncio.run(run())


# ---- 5b. nothing of the listener's words is changed -------------------------------------------------------------------------

def test_the_ear_words_reach_the_controller_exactly_as_heard(tmp_path):
    """Numbers, «не» and the condition of the question are the controller's own code: local mode only hands it the final."""
    async def run():
        async def connect():
            raise TimeoutError('handshake timed out')
        asked = 'Сколько процентов НДС, если это не экспорт'
        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        wire.ear = Ear(heard(asked))
        await wire.tick()
        await settle(wire, 20)
        turn = controller.ledger.latest_user()
        assert turn['text'] == asked and turn['final']
        await wire.close()
    asyncio.run(run())


def test_an_empty_or_blank_ear_record_opens_no_turn(tmp_path):
    async def run():
        async def connect():
            raise TimeoutError('handshake timed out')
        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        wire.ear = Ear(heard('   '), heard(None), {'uid': 'x'})
        await wire.tick()
        await settle(wire, 20)
        assert controller.ledger.latest_user() is None and wire.local_turns == 0
        await wire.close()
    asyncio.run(run())


def test_a_slow_cloud_does_not_hold_the_handshake_and_the_late_open_upgrades_the_call(tmp_path, monkeypatch):
    """Call of 10.11 23:34: each open took 10-15 s to be refused, the phone left before local mode began. The handshake is answered
    within LOCAL_OPEN_GRACE_S, the error frame is marked for the host (not for the phone), and an open that comes later is taken."""
    import echo_sync.native_media_socket as nms
    monkeypatch.setattr(nms, 'LOCAL_OPEN_GRACE_S', 0.05)
    async def run():
        gate = asyncio.Event()
        class Source:
            closed = False
            async def send(self, *a): pass
            async def close(self): self.closed = True
        source = Source()
        async def connect():
            await gate.wait()
            return source
        wire, _, sent, _ = build(tmp_path, connect=connect)
        await asyncio.wait_for(wire.client({'type': 'session.update'}), 1)
        assert wire.local_mode and any(f['type'] == 'session.updated' for f in sent)
        errors = [f for f in sent if f.get('type') == 'error']
        assert errors and all(f.get('echo_local') for f in errors)
        gate.set()
        for _ in range(200):
            if not wire.local_mode: break
            await asyncio.sleep(0.01)
        assert not wire.local_mode and wire.source is source and not source.closed
        await wire.close()
    asyncio.run(run())


def test_the_line_of_local_mode_waits_for_the_end_of_the_handshake(tmp_path):
    """Probe of 11.11 05:30: audio before the ready marker was answered. Nothing is said until the phone's handshake is over."""
    async def run():
        async def connect():
            raise TimeoutError('handshake operation timed out')
        wire, _, sent, spoken = build(tmp_path, connect=connect)
        await wire.client({'type': 'session.update'})
        await settle(wire)
        assert wire.local_mode and not wire.ready and LOCAL_PHRASES['local_opened'] not in spoken
        assert not any(f.get('type') == 'response.audio.delta' for f in sent)
        await wire.close()
    asyncio.run(run())


def test_with_a_reserve_road_the_lookup_of_local_mode_goes_its_usual_way(tmp_path):      # U48: the one road is always there (no key asks for it)
    """11.11 08:42: the reserve had the answer («9 июня 1672 года») and the line «В местных базах этого нет» was said over it."""
    async def run():
        searched = []

        async def connect():
            raise TimeoutError('handshake timed out')

        class Early:
            async def resolve(self, turn_id, question):
                searched.append(question)
                return []

            async def close(self):
                pass

        class Fast:
            roads = type('Roads', (), {'alive': lambda self, now=None: True})()      # the one road of the text channel (``reserve_text.Roads``): not out, whatever the cloud does
            closed = off = False

            def release(self, **job):
                return 'ok'

            def prepare(self, *a, **k):
                pass

            def drop(self):
                pass

        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        spoken.clear()
        wire.early, wire.fast = Early(), Fast()
        await wire.actions([{'type': 'lookup', 'epoch': controller.epoch, 'question': 'Когда родился Пётр Первый',
                             'input_turn_id': controller.question_id}])
        await settle(wire, 20)
        assert searched == ['Когда родился Пётр Первый']
        assert LOCAL_PHRASES['local_unknown'] not in spoken
        wire.fast = None
        await wire.close()
    asyncio.run(run())
