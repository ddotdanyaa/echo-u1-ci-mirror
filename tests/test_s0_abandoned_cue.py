"""Task S0, ruling 3 (scripts/DUAL_SYSTEM_DESIGN.md §1.4.6): a cue the phone has begun is never abandoned silently.

From its first audio frame the phone holds the model's turn (``modelTurnActive``) and, on the open speaker, keeps its microphone
closed until ``response.done``, ``output_audio_buffer.clear``, Interrupt or a reconnect. ``_play`` used to return early without a
word when the cue stopped being authorized mid-play: no ``response.done``, no clear. With no cue after it (the answer was complete)
the phone stayed deaf until the owner pressed Interrupt.

Required: a cue that has started and is abandoned for a reason of its own (it is no longer authorized; the write to the phone failed)
clears the phone at once. A cue that never started sends nothing; a cue that is superseded (a newer generation: a replacing speak, a
diagnostic, a cancel) or closed does not clear - whoever took the audio over has cleared it, and a late clear would cut the newer one.
"""
import asyncio
from array import array

import helpers_s6_ack as H
from echo_sync.controlled_media import HEARING_SECONDS
from echo_sync.native_media_socket import NativeMediaSocket

ANSWER = 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией. Чем больше масса, тем сильнее инерция.'
RATE = 24000
CLEAR = 'output_audio_buffer.clear'


def pcm_of(voiced_ms, silence_ms=0):
    samples = [6000 if (i // 40) % 2 == 0 else -6000 for i in range(RATE * voiced_ms // 1000)]
    return array('h', samples + [0] * (RATE * silence_ms // 1000)).tobytes()


class Controller:
    """Authorizes the cue for its first ``allowed`` checks (``_play`` checks before every frame and before response.done)."""

    def __init__(self, allowed):
        self.allowed, self.checks, self.reports = allowed, 0, []

    def authorized(self, cue):
        self.checks += 1
        return self.checks <= self.allowed

    def cue_started(self, cue, *, voiced_seconds=None):
        self.reports.append('started')

    def playback_done(self, cue, *, now, voiced_until=None):
        self.reports.append('done')


def speak(controller, pcm, *, emit=None, during=None):
    """Run ``_speak`` for one cue; ``during(socket)`` runs once the first audio frame is out. Returns the frame types sent."""
    frames = []

    async def run():
        async def record(frame):
            frames.append(frame['type'])
            if emit:
                await emit(frame)

        async def synthesize(text, end=None):
            return pcm

        socket = NativeMediaSocket(controller, record, None, None, synthesize)
        task = asyncio.create_task(socket._speak({'text': 'тест'}, socket.audio_generation))
        if during:
            while 'response.audio.delta' not in frames and not task.done():
                await asyncio.sleep(0.005)
            during(socket)
        await task

    asyncio.run(run())
    return frames


def test_a_cue_made_unauthorized_after_its_first_frame_clears_the_phone():
    controller = Controller(allowed=1)                       # the cursor moved on right after the first frame; nothing replaces the cue
    frames = speak(controller, pcm_of(300))
    assert frames[:3] == ['response.created', 'response.audio_transcript.delta', 'response.audio.delta'], frames
    assert frames[-1] == CLEAR and frames.count(CLEAR) == 1, f'the phone was left holding an open response: {frames}'
    assert 'response.done' not in frames and controller.reports == ['started']


def test_a_cue_made_unauthorized_before_its_end_was_announced_clears_the_phone():
    pcm = pcm_of(200)
    controller = Controller(allowed=len(pcm) // 960)          # every frame went out; response.done is refused
    frames = speak(controller, pcm)
    assert frames.count('response.audio.delta') == len(pcm) // 960
    assert frames[-1] == CLEAR and 'response.done' not in frames, frames


def test_a_cue_that_never_started_sends_nothing():
    frames = speak(Controller(allowed=0), pcm_of(300))
    assert frames == [], 'nothing reached the phone: there is nothing to clear'


def test_a_finished_cue_sends_no_clear():
    frames = speak(Controller(allowed=10 ** 6), pcm_of(300))
    assert frames[-1] == 'response.done' and CLEAR not in frames


def test_a_superseded_cue_never_clears_the_one_that_replaced_it():
    """A newer generation owns the phone's audio: it has cleared the old cue (or its own response will end the turn)."""
    def supersede(socket):
        socket.audio_generation += 1
    frames = speak(Controller(allowed=10 ** 6), pcm_of(300), during=supersede)
    assert 'response.audio.delta' in frames and CLEAR not in frames and 'response.done' not in frames, frames


def test_a_failed_write_after_the_first_frame_clears_the_phone_before_the_retry():
    audio = []

    async def flaky(frame):
        if frame['type'] == 'response.audio.delta':
            audio.append(frame)
            if len(audio) == 3:
                raise ConnectionError('write failed')          # once: the transport tries the cue one more time

    frames = speak(Controller(allowed=10 ** 6), pcm_of(300), emit=flaky)
    assert len(audio) > 3, 'precondition: the third audio frame could not be written, the retry went on'
    first, retry = frames.index('response.created'), frames.index('response.created', 1)
    assert CLEAR in frames[first:retry], f'the half-sent response was left open before the retry: {frames}'
    assert frames[-1] == 'response.done', 'the retry is played to its end'


def test_a_failure_after_the_response_was_done_does_not_clear_it():
    """response.done closed the response: what the phone still has buffered of it must play out."""
    class Failing(Controller):
        def playback_done(self, cue, *, now, voiced_until=None):
            raise RuntimeError('the controller could not take the report')

    frames = speak(Failing(allowed=10 ** 6), pcm_of(100))
    assert 'response.done' in frames, 'precondition: the response was done before the report failed'
    assert CLEAR not in frames, frames               # (the transport tries the cue once more, then speaks its diagnostic)


def test_the_last_portion_confirmed_while_its_repeat_plays_leaves_the_phone_listening(tmp_path):
    """The race of §1.4.6 with the real controller: the listener's repeat of the LAST portion is announced, the cloud is slow, the silence
    timer repeats the portion, and the late final confirms it while that repeat plays. The answer is complete: no cue replaces the repeat,
    so the phone must be told to end its turn, or its microphone stays closed."""
    async def run():
        wire = H.Wire(tmp_path / 'race')
        long = []                                                         # the repeat of the last portion lasts ~1 s

        async def synthesize(text, end=None):
            wire.synthesized.append(text)
            return pcm_of(900, 120) if long else pcm_of(60)

        wire.socket.synthesize = synthesize
        try:
            await wire.begin(ANSWER)
            while wire.index < len(wire.chunks) - 1:
                await wire.user(wire.chunks[wire.index])
            last = wire.chunks[-1]
            assert wire.synthesized[-1] == last, 'precondition: the last portion has been played'
            long.append(True)
            wire.skew += 1.0
            await wire.socket.provider(H.created('late', 'user', ''))     # the listener repeats it; the cloud's final is slow
            synthesized = len(wire.synthesized)
            for _ in range(40):                                           # ... so the silence timer repeats the portion
                wire.skew += 0.5
                await wire.socket.tick()
                await asyncio.sleep(0.01)
                if len(wire.synthesized) > synthesized:
                    break
            assert wire.synthesized[synthesized:] == [last], 'precondition: the auto-repeat of the last portion was started'
            frames = wire.audio_frames
            for _ in range(300):
                if wire.audio_frames >= frames + 3:
                    break
                await asyncio.sleep(0.01)
            assert wire.audio_frames >= frames + 3 and not wire.socket.audio.done(), 'precondition: the repeat is playing'
            cleared = wire.cleared()
            await wire.socket.provider(H.done('late', 'user', last))       # the late final: the last portion is confirmed
            await wire.settle(timeout=3.0)
            kinds = [f['type'] for f in wire.sent]
            return wire.controller.state()['completed'], wire.cleared() - cleared, kinds[-1], wire.synthesized[synthesized:]
        finally:
            await wire.close()

    completed, cleared, last_frame, spoken_after = asyncio.run(run())
    assert completed and len(spoken_after) == 1, 'precondition: the answer is complete and nothing else is spoken'
    assert cleared == 1 and last_frame == CLEAR, f'the abandoned repeat left the phone deaf (clears: {cleared}, last frame: {last_frame})'
