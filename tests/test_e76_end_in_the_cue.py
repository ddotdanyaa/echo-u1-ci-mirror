"""E76: which cue carries ``end``. Only the cue of the LAST portion of an answer (its stream closed), and only with ``end_intonation`` on.
Pins ControlledMedia._cue, the setting, and how the transport hands the mark to the synthesizer. No network, no TTS."""
import asyncio
import inspect
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

from echo_sync.controlled_host import EndVoice, render_cue_pcm
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.settings import CALL_SETTINGS, resolve

HOST_KWARGS = dict(source_delivery='delegation', session_context_fallback=True, lookup_policy='required',
                   first_useful_gate=True, coalesce_seconds=3.2, quiet_reopen=True)


def state(**over):
    base = {'revision': 1, 'chunks': ['Спад производства привёл', 'к росту цен.'], 'chunk_index': 0, 'completed': False,
            'streaming': False, 'stream_waiting_next': False, 'pending_turn': None}
    base.update(over)
    return base


class EndInTheCue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def controller(self, **settings):
        return ControlledMedia(Path(self.tmp.name) / 'controlled-state.sqlite3', session_id='native-probe-' + '0' * 32,
                               settings={**CALL_SETTINGS, **settings}, **HOST_KWARGS)

    def cue(self, controller, st, text='x'):
        with patch.object(ControlledMedia, 'state', return_value=st):
            return controller._cue(text)[0]

    def test_the_setting_is_off_by_default_and_takes_only_its_two_values(self):
        self.assertEqual(resolve(None)['end_intonation'], 'off')
        self.assertEqual(resolve({'end_intonation': 'fall'})['end_intonation'], 'fall')
        for bad in ('on', 'rise', True, 1, None, ''):
            with self.subTest(bad=bad):
                self.assertEqual(resolve({'end_intonation': bad})['end_intonation'], 'off')

    def test_off_no_cue_carries_end(self):
        c = self.controller()
        self.assertNotIn('end', self.cue(c, state(chunk_index=1)))
        self.assertNotIn('end', self.cue(c, state(chunk_index=0)))

    def test_on_only_the_last_portion_carries_end(self):
        c = self.controller(end_intonation='fall')
        self.assertNotIn('end', self.cue(c, state(chunk_index=0)))              # a middle portion is spoken as before
        self.assertEqual(self.cue(c, state(chunk_index=1))['end'], 'fall')      # the last portion of a closed answer

    def test_a_stream_that_may_still_grow_has_no_last_portion_yet(self):
        c = self.controller(end_intonation='fall')
        self.assertNotIn('end', self.cue(c, state(chunk_index=1, streaming=True)))

    def test_the_repeat_of_a_finished_answer_is_its_last_portion_again(self):
        st = state(chunk_index=2, completed=True, replay_last=1)
        self.assertEqual(self.cue(self.controller(end_intonation='fall'), st)['end'], 'fall')
        self.assertNotIn('end', self.cue(self.controller(), st))

    def test_the_cue_keeps_every_other_key(self):
        c = self.controller()
        off = self.cue(c, state(chunk_index=1))
        c.settings = {**c.settings, 'end_intonation': 'fall'}
        on = self.cue(c, state(chunk_index=1))
        self.assertEqual({k: v for k, v in on.items() if k != 'end'}, off)


def pcm_of(voice_ms, silence_ms):
    voiced = array('h', [4000 if (i // 40) % 2 else -4000 for i in range(24 * voice_ms)]).tobytes()
    return voiced + bytes(24 * 2 * silence_ms)


class Recorder:
    def authorized(self, cue):
        return True

    def cue_started(self, cue, *, voiced_seconds=None):
        pass

    def playback_done(self, cue, *, now, voiced_until=None):
        pass


def speak_through_the_socket(cue):
    """NativeMediaSocket._speak with a synthesizer that records how it was called."""
    seen = []

    async def synthesize(text, **kwargs):
        seen.append((text, kwargs))
        return pcm_of(100, 100)

    async def run():
        async def emit(frame):
            pass
        socket = NativeMediaSocket(Recorder(), emit, None, None, synthesize)
        await socket._speak(cue, socket.audio_generation)
    asyncio.run(run())
    return seen


class EndToTheSynthesizer(unittest.TestCase):
    def test_the_synthesizer_is_called_with_end_only_when_the_cue_has_it(self):
        self.assertEqual(speak_through_the_socket({'text': 'тест'}), [('тест', {})])                 # exactly the call of before
        self.assertEqual(speak_through_the_socket({'text': 'тест', 'end': 'fall'}), [('тест', {'end': 'fall'})])

    def test_render_cue_pcm_keeps_its_signature_and_the_worker_gets_the_end(self):
        params = inspect.signature(render_cue_pcm).parameters       # c23: the laptop's c20 added keyword-only ``speech`` (default False); the positional call is the same
        self.assertEqual([n for n, p in params.items() if p.kind is not p.KEYWORD_ONLY], ['worker', 'text', 'directory'])
        self.assertTrue(all(p.default is not p.empty for p in params.values() if p.kind is p.KEYWORD_ONLY))

        class Worker:
            def __init__(self):
                self.seen = []

            def synthesize(self, text, path, end=None):
                self.seen.append((text, end))
                return path
        worker = Worker()
        EndVoice(worker, 'fall').synthesize('к росту цен.', 'x.wav')
        self.assertEqual(worker.seen, [('к росту цен.', 'fall')])


if __name__ == '__main__':
    unittest.main()
