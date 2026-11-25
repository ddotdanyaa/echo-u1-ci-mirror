"""U20-S5 (modes: the key ``order_guard`` is gone): an honest refusal is ALWAYS said (the always-answer rule). The guard that could keep it silent (O1-O4 of OrderLedger, ``on``) lost the honest line on an unknown
question in the «cloud is deaf» scene (REPORT_ONE 3.03), and its default was «shadow» (said, only logged): the rule is what the default did. No setting reads it; the controller has no ``refusal_allowed``."""
import asyncio
import logging
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.settings import DEFAULTS


def _turn(tid,role,text):return {'type':'turn.done','turn':{'id':tid,'role':role,'transcript':text}}


def _played(tmp_path,name='a'):
    c=ControlledMedia(tmp_path/f'{name}.db',session_id='s',settings={'words_per_portion':3})
    c.provider(_turn('u','user','Почему меняются времена года?'));c.grounding(c.epoch,[{'url':'https://example.org','text':'source'}])
    cue=c.provider(_turn('a','assistant',getattr(c,'answer_marker','')+'Наклон земной оси меняет освещение.'))[0]
    c.cue_started(cue)      # X-CUE began -> the answer of this epoch is played
    return c,cue


def test_no_key_and_no_guard_in_the_controller(tmp_path):
    assert 'order_guard' not in DEFAULTS
    c,_=_played(tmp_path)
    assert not hasattr(c,'refusal_allowed') and not hasattr(c,'order_guard')


def _wire(controller):
    frames=[]
    class Phrases:
        def get(self,key):return b'\x01\0'*480
    async def emit(f):frames.append(f)
    return NativeMediaSocket(controller,emit,None,None,None,diagnostic_audio=Phrases()),frames


def test_wire_an_unanswered_refusal_after_a_played_cue_is_spoken_once(tmp_path,caplog):
    caplog.set_level(logging.INFO)
    async def run():
        c,cue=_played(tmp_path)
        wire,frames=_wire(c)
        await wire.actions([{'type':'unanswered','epoch':cue['epoch'],'reason':'no_usable_text'}])
        await wire.finish_diagnostic()
    asyncio.run(run())
    assert 'diagnostic=spoken' in caplog.text and 'diagnostic=order_guard' not in caplog.text


def test_wire_local_unknown_after_a_played_cue_is_spoken(tmp_path,caplog):
    caplog.set_level(logging.INFO)
    async def run():
        c,cue=_played(tmp_path)
        wire,frames=_wire(c)
        async def synth(text, end=None):return b'\xff\x3f'*4800
        wire.synthesize=synth
        c.published='';c.local_answer=False      # the cue has played; the moot rule (an answer that sounds) is not what this test is about
        await wire._local_unknown({'epoch':cue['epoch'],'qid':'q'})
        await asyncio.sleep(.2);await wire.finish_diagnostic()
    asyncio.run(run())
    assert 'local answer=none reason=no_local_source' in caplog.text
