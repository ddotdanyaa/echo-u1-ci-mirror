"""always-answer, step 3: the wire (``NativeMediaSocket``) asks ONE question of the text channel - does it have a road that is not out? - and answers by it. With a live road local mode says no
«Облако недоступно», sends the question to the channel and says no «Связь вернулась» it never said; with none, as before; and a channel that gives the question back in local mode is told
honestly, once, with the controller told (``answer_diagnosed``)."""
import asyncio

from test_local_fallback import Ear, build, heard, open_call, settle

from echo_sync.native_media_socket import LOCAL_PHRASES


class Roads:
    def __init__(self, alive=True):
        self.living = alive

    def alive(self, now=None):
        return self.living


class Fast:
    """A stand-in for ``fast_text.FastText`` with roads: what the wire asks of it and what it answers to a release."""
    closed = off = False
    reopen_at = None

    def __init__(self, alive=True, answer='started'):
        self.roads, self.answer, self.released, self.dropped = Roads(alive), answer, [], 0

    def release(self, **job):
        self.released.append(job)
        return self.answer

    def prepare(self, *a, **k):
        return True

    def drop(self):
        self.dropped += 1

    def close(self):
        self.closed = True

    def note(self, *a, **k):
        pass


def release(controller, qid='q1'):
    return {'type': 'fast', 'op': 'release', 'qid': qid, 'turn': 't1', 'epoch': controller.epoch, 'question': 'Когда родился Пётр Первый', 'route': 'plain', 'sources': []}


async def refused_open(tmp_path, alive, *, connect=None, **keywords):
    async def fails():
        raise TimeoutError('handshake timed out')
    wire, controller, sent, spoken = build(tmp_path, connect=connect or fails, **keywords)
    wire.fast = Fast(alive)
    await open_call(wire, sent)
    return wire, controller, sent, spoken


def test_a_call_that_falls_into_local_mode_with_a_live_road_of_text_says_no_cloud_is_gone(tmp_path):
    async def run():
        wire, controller, sent, spoken = await refused_open(tmp_path, True)
        assert wire.local_mode and LOCAL_PHRASES['local_opened'] not in spoken
        await wire.close()
    asyncio.run(run())


def test_with_no_live_road_the_line_is_said_once_as_before(tmp_path):
    async def run():
        wire, controller, sent, spoken = await refused_open(tmp_path, False)
        assert wire.local_mode and spoken.count(LOCAL_PHRASES['local_opened']) == 1
        await wire.close()
    asyncio.run(run())


def test_a_channel_with_no_roads_at_all_is_as_before(tmp_path):
    async def run():
        wire, controller, sent, spoken = await refused_open(tmp_path, True)
        await wire.close()
        wire, controller, sent, spoken = build(tmp_path, connect=lambda: (_ for _ in ()).throw(TimeoutError()))
        wire.fast = type('Plain', (), {'closed': False, 'off': False, 'stream': object(), 'close': lambda self: None})()
        assert not wire._text_road(alive=True)
        wire.fast = None
        assert not wire._text_road(alive=True)
    asyncio.run(run())


def test_a_closed_channel_has_no_live_road_whatever_its_roads_say(tmp_path):
    async def run():
        wire, controller, sent, spoken = await refused_open(tmp_path, True)
        assert wire._text_road(alive=True)
        wire.fast.closed = True
        assert not wire._text_road(alive=True)
        wire.fast.closed = False
        wire.fast.roads.living = False
        assert not wire._text_road(alive=True)
        await wire.close()
    asyncio.run(run())


def test_a_released_question_in_local_mode_with_live_roads_goes_to_the_channel_and_not_to_the_honest_line(tmp_path):
    async def run():
        wire, controller, sent, spoken = await refused_open(tmp_path, True)
        spoken.clear()
        await wire.actions([release(controller)])
        await settle(wire, 20)
        assert [job['qid'] for job in wire.fast.released] == ['q1'] and LOCAL_PHRASES['local_unknown'] not in spoken
        await wire.close()
    asyncio.run(run())


def test_with_every_road_resting_the_released_question_is_still_asked_of_the_channel_a_rest_is_an_order_never_a_ban(tmp_path):
    async def run():
        wire, controller, sent, spoken = await refused_open(tmp_path, False)
        spoken.clear()
        await wire.actions([release(controller)])
        await settle(wire, 20)
        assert [job['qid'] for job in wire.fast.released] == ['q1'] and LOCAL_PHRASES['local_unknown'] not in spoken      # the link may be back: the channel asks the resting roads last, and says the line itself when none answers
        await wire.close()
    asyncio.run(run())


def test_a_closed_channel_is_not_asked_in_local_mode_and_the_released_question_gets_the_honest_line(tmp_path):
    async def run():
        wire, controller, sent, spoken = await refused_open(tmp_path, True)
        wire.fast.closed = True
        spoken.clear()
        await wire.actions([release(controller)])
        await settle(wire, 20)
        assert wire.fast.released == [] and spoken == [LOCAL_PHRASES['local_unknown']]
        await wire.close()
    asyncio.run(run())


def test_the_cloud_back_says_the_line_only_when_the_fall_said_the_other(tmp_path, monkeypatch):
    async def run():
        import echo_sync.native_media_socket as nms
        monkeypatch.setattr(nms, 'LOCAL_RETRY_FIRST_S', 0)
        monkeypatch.setattr(nms, 'LOCAL_RETRY_EVERY_S', 0)
        for alive in (True, False):
            class Source:
                closed = False

                async def send(self, *a):
                    pass

                async def close(self):
                    self.closed = True
            tries = []

            async def connect():
                tries.append(1)
                if len(tries) < 3:
                    raise TimeoutError('handshake timed out')
                return Source()
            wire, controller, sent, spoken = await refused_open(tmp_path, alive, connect=connect)
            for _ in range(200):
                if not wire.local_mode:
                    break
                await asyncio.sleep(0)
            await settle(wire, 40)
            assert not wire.local_mode
            assert spoken.count(LOCAL_PHRASES['local_opened']) == spoken.count(LOCAL_PHRASES['local_back']) == (0 if alive else 1)
            await wire.close()
    asyncio.run(run())


def test_a_channel_that_gives_the_question_back_in_local_mode_is_told_honestly_once_and_the_controller_knows(tmp_path):
    async def run():
        wire, controller, sent, spoken = await refused_open(tmp_path, True)
        wire.fast.answer = 'off'
        told = []
        controller.answer_diagnosed = told.append
        spoken.clear()
        await wire.actions([release(controller)])
        await settle(wire, 20)
        assert spoken == [LOCAL_PHRASES['local_unknown']] and told == [controller.epoch]
        await wire.actions([release(controller)])      # the retry of the same question: the line is said once
        await settle(wire, 20)
        assert spoken == [LOCAL_PHRASES['local_unknown']]
        await wire.close()
    asyncio.run(run())


def test_a_channel_that_gives_the_question_back_with_the_cloud_up_says_nothing_new(tmp_path):
    async def run():
        class Source:
            async def send(self, *a):
                pass

            async def close(self):
                pass

        async def connect():
            return Source()
        wire, controller, sent, spoken = build(tmp_path, connect=connect)
        wire.fast = Fast(True, answer='off')
        await open_call(wire, sent)
        spoken.clear()
        await wire.actions([release(controller)])
        await settle(wire, 20)
        assert not wire.local_mode and LOCAL_PHRASES['local_unknown'] not in spoken
        await wire.close()
    asyncio.run(run())
