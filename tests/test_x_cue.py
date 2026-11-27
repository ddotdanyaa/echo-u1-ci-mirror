"""X-CUE: one source of a cue's life (began|done|cut|abandoned); each cue that began ends exactly once."""
import asyncio
import time
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.controlled_media import ControlledMedia


class Source:
    async def send(self,kind,payload=b''):pass
    async def close(self):pass


def _turn(tid,role,text):return {'type':'turn.done','turn':{'id':tid,'role':role,'transcript':text}}


def _cue(c):
    c.provider(_turn('u','user','Почему меняются времена года?'));c.grounding(c.epoch,[{'url':'https://example.org','text':'source'}])
    return c.provider(_turn('a','assistant',getattr(c,'answer_marker','')+'Наклон земной оси меняет освещение.'))[0]


def test_first_end_wins_and_both_sides_share_the_clock(tmp_path):
    c=ControlledMedia(tmp_path/'s.db',session_id='s',settings={'words_per_portion':3})
    assert c.clock is time.monotonic
    seen=[];c.subscribe_cue(lambda k,cue,at,num:seen.append((k,at,num)))
    cue=_cue(c)
    assert c._cue_event('began',cue,1.0)
    assert not c._cue_event('began',cue,1.1)         # the same cue sent again has begun once
    assert c._cue_event('done',cue,2.0)
    assert not c._cue_event('cut',cue,3.0) and not c.cue_abandoned(cue,at=3.0)
    assert [k for k,_,_ in seen]==['began','done']
    c.subscribe_cue(lambda *a:1/0)                   # a failing listener costs nothing
    assert c._cue_event('began',cue,4.0)
    c._cancelled()
    assert [k for k,_,_ in seen]==['began','done','began','cut']


def test_socket_cue_a_done_b_superseded_c_cancelled_by_epoch(tmp_path):
    async def run():
        sent=[];gate=asyncio.Event()
        async def emit(x):sent.append(x)
        async def synth(text, end=None):return b'\x01\0'*4800       # 0.2 s at 24k mono 16-bit: several 960-byte frames
        c=ControlledMedia(tmp_path/'s.db',session_id='s',settings={'words_per_portion':3})
        async def connect():return Source()
        wire=NativeMediaSocket(c,emit,connect,lambda _:None,synth);wire.ready=True
        events=[];c.subscribe_cue(lambda k,cue,at,num:events.append((k,cue.get('text'),at,num)))
        cue=_cue(c)
        # A: plays to the end
        await wire._play(b'\x01\0'*480,'A',wire.audio_generation,lambda:True,lambda b:c.playback_done(cue,now=b),lambda b:c.cue_started(cue),
                         lambda b,o,w,at:c.cue_abandoned(cue,at=at,opened=o,why=w))
        # B: superseded mid-play by a newer generation
        gen=wire.audio_generation
        async def bump():
            await asyncio.sleep(.01);wire.audio_generation+=1
        task=asyncio.create_task(bump())
        r=await wire._play(b'\x01\0'*48000,'B',gen,lambda:True,None,lambda b:c.cue_started(cue),
                           lambda b,o,w,at:c.cue_abandoned(cue,at=at,opened=o,why=w))
        await task;assert r is False
        # C: cancelled by an epoch bump (unauthorized after its first frame)
        alive=[True]
        async def kill():
            await asyncio.sleep(.01);alive[0]=False;c._new_epoch('t');c._cancelled()
        task=asyncio.create_task(kill())
        r=await wire._play(b'\x01\0'*48000,'C',wire.audio_generation,lambda:alive[0],None,lambda b:c.cue_started(cue),
                           lambda b,o,w,at:c.cue_abandoned(cue,at=at,opened=o,why=w))
        await task;assert r is False
        return events,sent
    events,sent=asyncio.run(run())
    kinds=[(k,n.get('why')) for k,_,_,n in events]
    assert [k for k,_ in kinds]==['began','done','began','abandoned','began','cut'] or [k for k,_ in kinds]==['began','done','began','abandoned','began','abandoned']
    assert kinds[3]==('abandoned','superseded')
    assert all(isinstance(at,float) for _,_,at,_ in events)
    assert sum(1 for x in sent if x['type']=='response.done')==1       # the phone frames: only A completed
