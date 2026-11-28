"""c22-reviewfix: review of master 4a91807, local mode (local-lifecycle and local-accuracy), confirmed findings only, at the wire.

1. A line about the channel («Связь с облаком вернулась.», «Облако недоступно…») never cuts the portion that sounds: it waits for its end,
   and the controller's own playback_done runs (no portion left outstanding with no repeat armed).
2. The input clock starts again at 0 on the upgrade, and the controller's marks on it start again with it (portion_heard, cue_input_ms,
   the ear's input ms): «дальше» after the upgrade is not turned into «повтори».
3. A fall in the window between the cloud's return and the end of its line still starts a retry, and the listener, who last heard «вернулась»,
   is told again.
4. A question under way at the cloud's return is decided by when it began: the ear's whole text is its final, the head is not lost.
5. The ear's record that the cloud already finalized gives no second final after a fall; one the cloud never finalized is not lost.
"""
import asyncio

from echo_sync.native_media_socket import LOCAL_PHRASES
from test_local_fallback import PCM, Ear, Source, build, cues, heard, open_call, settle

LONG = b'\x11\x22' * 24000                                  # 1 s of "spoken" PCM: a portion that is still sounding when the line comes


class Bank:
    def lookup(self, text, bank_only=False):
        return type('Hit', (), {'answer': 'Двадцать процентов.'})() if 'ндс' in text.lower() else None


def responses(sent):
    """(text, completed) of every spoken response on the phone, in order, and the number of clears."""
    out, texts = {}, {}
    for f in sent:
        rid = (f.get('response') or {}).get('id')
        if f.get('type') == 'response.created' and rid:
            out[rid] = False
        elif f.get('type') == 'response.audio_transcript.delta':
            texts[f.get('response_id')] = f.get('delta')
        elif f.get('type') == 'response.done' and rid in out:
            out[rid] = True
    return [(texts.get(rid), done) for rid, done in out.items()]


async def until(predicate, rounds=4000):
    for _ in range(rounds):
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return predicate()


def offline():
    async def connect():
        raise TimeoutError('handshake timed out')
    return connect


def test_the_line_of_the_cloud_back_waits_for_the_portion_that_sounds(tmp_path):
    async def run():
        async def say(text, end=None):
            return LONG if 'Двадцать' in text else b'\x11\x22' * 2400
        wire, controller, sent, spoken = build(tmp_path, connect=offline(), instant=Bank(), synthesize=say)
        await open_call(wire, sent)
        await until(lambda: wire.audio is None or wire.audio.done())
        wire.ear = Ear(heard('Какая ставка НДС'))
        await wire.tick()
        assert await until(lambda: any(t and 'Двадцать' in t for t, _ in responses(sent))), 'precondition: the answer sounds'
        before = sum(f.get('type') == 'output_audio_buffer.clear' for f in sent)
        await wire._leave_local(Source())
        assert await until(lambda: any(t == LOCAL_PHRASES['local_back'] and done for t, done in responses(sent)))
        answer = [done for t, done in responses(sent) if t and 'Двадцать' in t]
        assert answer == [True], f'the portion was cut by the line: {responses(sent)}'
        assert sum(f.get('type') == 'output_audio_buffer.clear' for f in sent) == before
        assert not controller.cue_outstanding, 'the cut portion is left outstanding with no repeat armed'
        await wire.close()
    asyncio.run(run())


def test_the_line_of_a_fall_waits_for_the_portion_that_sounds(tmp_path):
    async def run():
        source = Source()

        async def connect():
            return source

        async def say(text, end=None):
            return LONG if 'Двадцать' in text else b'\x11\x22' * 2400
        wire, controller, sent, spoken = build(tmp_path, connect=connect, instant=Bank(), synthesize=say)
        await open_call(wire, sent)
        await until(lambda: wire.audio is None or wire.audio.done())
        assert await wire.enter_local('helper_closed', source_lost=True)
        await until(lambda: any(t == LOCAL_PHRASES['local_opened'] and done for t, done in responses(sent)))
        sent.clear()
        wire.local_opened_said = False                       # the line of a fall comes while an answer sounds
        wire.ear = Ear(heard('Какая ставка НДС'))
        await wire.tick()
        assert await until(lambda: any(t and 'Двадцать' in t for t, _ in responses(sent)))
        wire.local_mode = False;wire.source = source
        assert await wire.enter_local('write_timeout', source_lost=True)
        assert await until(lambda: any(t == LOCAL_PHRASES['local_opened'] and done for t, done in responses(sent)))
        assert [done for t, done in responses(sent) if t and 'Двадцать' in t] == [True], responses(sent)
        start = next(k for k, f in enumerate(sent) if f.get('type') == 'response.audio_transcript.delta' and 'Двадцать' in f.get('delta', ''))
        assert not any(f.get('type') == 'output_audio_buffer.clear' for f in sent[start:]), 'the portion was cleared on the phone'
        await wire.close()
    asyncio.run(run())


def test_the_marks_on_the_input_clock_start_again_with_it(tmp_path):
    async def run():
        wire, controller, sent, spoken = build(tmp_path, connect=offline())
        await open_call(wire, sent)
        controller.portion_heard = ((1, 0), 120000)
        controller.cue_input_ms = 118000
        controller.ear_pieces = [{'uid': 'e1', 'text': 'дальше', 'onset_input_ms': 119000, 'offset_input_ms': 119500}]
        controller.ear_take = {'tid': 't', 'offset_input_ms': 119500}
        wire.input_bytes = 48000 * 120
        await wire._leave_local(Source())
        assert wire.input_bytes == 0
        assert controller.portion_heard == ((1, 0), 0), controller.portion_heard
        assert controller.cue_input_ms in (None, 0)
        assert controller.ear_pieces[0]['onset_input_ms'] is None and controller.ear_pieces[0]['offset_input_ms'] is None
        assert controller.ear_take['offset_input_ms'] is None
        await wire.close()
    asyncio.run(run())


def test_a_fall_while_the_line_of_the_return_renders_still_retries_and_is_told(tmp_path, monkeypatch):
    async def run():
        import echo_sync.native_media_socket as nms
        monkeypatch.setattr(nms, 'LOCAL_RETRY_FIRST_S', 0)
        monkeypatch.setattr(nms, 'LOCAL_RETRY_EVERY_S', 0)
        tries, release = [], asyncio.Event()

        async def connect():
            tries.append(1)
            if len(tries) < 3:
                raise TimeoutError('handshake timed out')
            if len(tries) == 3:
                return Source()
            raise TimeoutError('still down')

        spoken = []

        async def say(text, end=None):
            spoken.append(text)
            if text == LOCAL_PHRASES['local_back']:
                await release.wait()
            return b'\x11\x22' * 2400
        wire, controller, sent, _ = build(tmp_path, connect=connect, synthesize=say)
        await open_call(wire, sent)
        assert await until(lambda: LOCAL_PHRASES['local_back'] in spoken), 'precondition: the cloud came back'
        assert await wire.enter_local('helper_closed', source_lost=True)           # it falls again while the line renders
        release.set()
        await settle(wire, 40)
        assert wire.local_mode
        assert await until(lambda: len(tries) > 3), f'no retry after the second fall: {len(tries)} tries'
        assert spoken.count(LOCAL_PHRASES['local_opened']) == 2, spoken
        await wire.close()
    asyncio.run(run())


class BusyEar(Ear):
    """An ear with an utterance under way (``spans``, as ear_shadow.ShadowEar keeps it from onset to its record)."""

    def __init__(self):
        super().__init__()
        self.spans = {'e1': {'onset': 0.0}}

    def poll(self):
        records = super().poll()
        for record in records:
            self.spans.pop(record.get('uid'), None)
        return records


def test_a_question_under_way_at_the_return_is_the_ear_s_whole_text(tmp_path):
    async def run():
        wire, controller, sent, spoken = build(tmp_path, connect=offline())
        await open_call(wire, sent)
        ear = wire.ear = BusyEar()
        source = Source()
        leaving = asyncio.ensure_future(wire._leave_local(source))
        await settle(wire, 20)
        assert wire.local_mode, 'the switch came in the middle of the question'
        await wire.client({'type': 'input_audio_buffer.append', 'audio': __import__('base64').b64encode(PCM).decode()})
        assert source.frames == [], 'the new helper heard the tail of a question begun in local mode'
        ear.records = [heard('Не облагается ли экспорт НДС', uid='e1')]
        await wire.tick()
        await asyncio.wait_for(leaving, 15)
        turn = controller.ledger.latest_user()
        assert turn and turn['text'] == 'Не облагается ли экспорт НДС' and turn['final']
        assert not wire.local_mode and wire.source is source
        await wire.close()
    asyncio.run(run())


def test_a_record_the_cloud_already_finalized_gives_no_second_final_after_a_fall(tmp_path):
    async def run():
        source = Source()

        async def connect():
            return source
        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        await wire.provider({'type': 'turn.created', 'turn': {'id': 't1', 'role': 'user', 'transcript': 'Какая'}})
        await wire.provider({'type': 'turn.done', 'turn': {'id': 't1', 'role': 'user', 'transcript': 'Какая ставка НДС'}})
        assert await wire.enter_local('provider_session_closed', source_lost=True)
        record = heard('Какая ставка НДС', uid='e1')
        record['offset'] = wire.clock() - 1.0                              # the utterance ended before the cloud's final came
        wire.ear = Ear(record)
        await wire.tick()
        await settle(wire, 20)
        assert wire.local_turns == 0, 'the same utterance was finalized twice'
        await wire.close()
    asyncio.run(run())


def test_a_record_the_cloud_never_finalized_is_not_lost_in_the_fall(tmp_path):
    async def run():
        source = Source()

        async def connect():
            return source
        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        await open_call(wire, sent)
        record = heard('Какая ставка НДС', uid='e1')
        record['offset'] = wire.clock()
        wire.ear = Ear(record)
        await wire.tick()                                                  # polled while the cloud still ran: its final was to come
        assert controller.ledger.latest_user() is None
        assert await wire.enter_local('helper_closed', source_lost=True)
        await settle(wire, 20)
        turn = controller.ledger.latest_user()
        assert turn and turn['text'] == 'Какая ставка НДС' and turn['final'], turn
        await wire.close()
    asyncio.run(run())
