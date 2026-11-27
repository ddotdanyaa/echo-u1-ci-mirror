"""U20-S5: the refusal gate. ``order_guard`` off | shadow (logs the violated order, speaks) | on (a forbidden refusal is not spoken)."""
import asyncio
import logging
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.settings import resolve
from echo_sync.reserve_text import REFUSAL


def _turn(tid,role,text):return {'type':'turn.done','turn':{'id':tid,'role':role,'transcript':text}}


def _played(tmp_path,mode):
    c=ControlledMedia(tmp_path/f'{mode}.db',session_id='s',settings={'words_per_portion':3,'order_guard':mode})      # one call per db: the same final again in one session is a reconnect (U91), not a second question
    c.provider(_turn('u','user','Почему меняются времена года?'));c.grounding(c.epoch,[{'url':'https://example.org','text':'source'}])
    cue=c.provider(_turn('a','assistant',getattr(c,'answer_marker','')+'Наклон земной оси меняет освещение.'))[0]
    c.cue_started(cue)      # X-CUE began -> the answer of this epoch is played
    return c,cue


def test_setting_default_is_shadow_and_bad_value_falls_back():
    assert resolve({})['order_guard']=='shadow'
    assert resolve({'order_guard':'on'})['order_guard']=='on'
    assert resolve({'order_guard':'nonsense'})['order_guard']=='shadow'


def test_played_comes_from_the_began_event_and_the_gate_follows_the_mode(tmp_path,caplog):
    caplog.set_level(logging.INFO)
    c,cue=_played(tmp_path,'on')
    assert c.refusal_allowed(cue['epoch'])is False
    assert 'order_violation rule=O1' in caplog.text and 'guard=on' in caplog.text
    c,cue=_played(tmp_path,'shadow')
    assert c.refusal_allowed(cue['epoch'])is True       # shadow speaks, only logs
    c,cue=_played(tmp_path,'off')
    assert c.refusal_allowed(cue['epoch'])is True


def test_a_refusal_before_any_cue_is_allowed_once_then_O2(tmp_path):
    c=ControlledMedia(tmp_path/'s.db',session_id='s',settings={'order_guard':'on'})
    assert c.refusal_allowed(c.epoch)is True
    assert c.refusal_allowed(c.epoch)is False           # a second phrase for one epoch (D6)


def test_provisional_refusal_text_is_noted_and_the_answer_after_it_is_not_a_violation(tmp_path):
    c=ControlledMedia(tmp_path/'s.db',session_id='s',settings={'order_guard':'on'})
    assert c.refusal_allowed(c.epoch,provisional=True)is True
    c.order.play(c.epoch)
    assert c.order.violations==[]


def _wire(controller,errors_seen):
    frames=[]
    class Phrases:
        def get(self,key):return b'\x01\0'*480
    async def emit(f):frames.append(f)
    return NativeMediaSocket(controller,emit,None,None,None,diagnostic_audio=Phrases()),frames


def _unanswered(tmp_path,mode,caplog):
    caplog.set_level(logging.INFO)
    async def run():
        c,cue=_played(tmp_path,mode)
        wire,frames=_wire(c,None)
        await wire.actions([{'type':'unanswered','epoch':cue['epoch'],'reason':'no_usable_text'}])
        await wire.finish_diagnostic()
        return frames
    frames=asyncio.run(run())
    return sum(1 for f in frames if f['type']=='response.done'),caplog.text


def test_wire_on_an_unanswered_refusal_after_a_played_cue_is_silent(tmp_path,caplog):
    done,text=_unanswered(tmp_path,'on',caplog)
    assert done==0 and 'diagnostic=spoken' not in text and 'diagnostic=order_guard' in text


def _local_unknown(tmp_path,mode):
    async def run():
        c,cue=_played(tmp_path,mode)
        wire,frames=_wire(c,None)
        async def synth(text):return b'\xff\x3f'*4800
        wire.synthesize=synth
        c.published='';c.local_answer=False      # the cue has played; the moot rule (an answer that sounds) is not what this test is about
        await wire._local_unknown({'epoch':cue['epoch'],'qid':'q'})
        await asyncio.sleep(.2);await wire.finish_diagnostic()
        return sum(1 for f in frames if f['type']=='response.done')
    return asyncio.run(run())


def test_wire_on_local_unknown_after_a_played_cue_says_nothing(tmp_path):
    assert _local_unknown(tmp_path,'on')==0
    assert _local_unknown(tmp_path,'shadow')==1


def test_wire_shadow_speaks_exactly_one(tmp_path,caplog):
    done,text=_unanswered(tmp_path,'shadow',caplog)
    assert done==1 and 'diagnostic=spoken' in text and 'order_violation rule=O1' in text


def test_fast_refusal_text_is_swallowed_only_in_on(tmp_path):
    for mode,expect in (('on',[]),('shadow',None)):
        c,cue=_played(tmp_path,mode)
        c.fast_on=True;c.fast_done=False;c.fast_asked=('q','t');c.question_id='q';c.local_answer=False
        keep,actions=c._fast_fed('t','q','text',REFUSAL)
        if expect==[]:assert keep is True and actions==[]
