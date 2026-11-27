"""U119: what one server cannot do because of what the iPhone client (Conduit) sends and takes. Each test pins a fact of the code that the
audit table lane_reports/reports/u119_iphone_audit.md cites as 'доказано'. No phone, no model: the transport is driven with fake frames."""
import asyncio
import base64
import json

import pytest

from echo_sync import voice_boost
from echo_sync.call_trace import PCM_BYTES_PER_SECOND, CallTrace
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import INPUT_BYTES_PER_SECOND, NativeMediaSocket

READY = {'type': 'response.done', 'response': {'status': 'completed', 'output': []}}


class Source:
    def __init__(self):self.frames=[]
    async def send(self,kind,payload=b''):self.frames.append((kind,payload))
    async def close(self):pass


def b64(pcm):return base64.b64encode(pcm).decode()


def wire_of(tmp_path):
    sent=[];source=Source()
    async def emit(x):sent.append(x)
    async def connect():return source
    wire=NativeMediaSocket(ControlledMedia(tmp_path/'s.db',session_id='s'),emit,connect,lambda _:None,lambda _:None)
    wire.source=source;wire.ready=True
    return wire,source,sent


def test_one_mixed_mono_stream_is_all_the_server_gets_no_far_end_reference(tmp_path):
    """Mechanism: echo cancellation on the server. The only audio the transport takes is the ``audio`` of input_audio_buffer.append, forwarded as ONE
    'P' frame. A second stream the phone might attach (the speaker signal, a channel) is not read: the server has no reference to subtract."""
    async def run():
        wire,source,_=wire_of(tmp_path)
        mic=bytes(range(200))*10      # 2000 bytes, an arbitrary s16 mono packet
        await wire.client({'type':'input_audio_buffer.append','audio':b64(mic),'reference':b64(b'\x01\x02'*1000),'channels':2,'far_end':b64(b'\x03\x04'*1000)})
        assert source.frames==[('P',mic)]      # exactly the mic bytes, nothing of the extra fields, no second kind of frame
        assert wire.input_bytes==len(mic)
        await wire.close()
    asyncio.run(run())


def test_the_wire_takes_only_24khz_s16_mono_shaped_packets_up_to_two_seconds(tmp_path):
    """Mechanism: the media format and the packet limit are the phone's contract. 48,000 bytes a second (24 kHz x 2 bytes x 1 channel); an odd length
    (not whole s16 samples) or more than 96,000 bytes (2 s) is refused with an error and never forwarded - the server cannot ask for another format."""
    assert INPUT_BYTES_PER_SECOND==PCM_BYTES_PER_SECOND==24000*2*1
    async def run():
        wire,source,sent=wire_of(tmp_path)
        for pcm in (b'\0'*3,b'\0'*96002):await wire.client({'type':'input_audio_buffer.append','audio':b64(pcm)})
        assert not source.frames and [x['error']['code'] for x in sent if x.get('type')=='error']==['controlled_invalid_pcm']*2
        await wire.client({'type':'input_audio_buffer.append','audio':b64(b'\0'*96000)})      # the edge: 2.0 s is taken
        assert len(source.frames)==1
        await wire.close()
    asyncio.run(run())


def test_the_server_has_no_message_that_configures_the_phones_audio_session(tmp_path):
    """Mechanism: duplex, echo cancellation, route, ducking and volume of the phone live in the client (Conduit's route policy and audio session).
    The server's answer to the handshake carries only an empty ``tools`` list; no audio-session field exists in what it sends, so the gate that
    drops the microphone while a cue plays cannot be switched from here."""
    async def run():
        wire,_,sent=wire_of(tmp_path)
        await wire.client({'type':'session.update','session':{'turn_detection':None,'input_audio_noise_reduction':{'type':'near_field'}}})
        assert sent==[{'type':'session.updated','session':{'tools':[]}}]      # the client's requested settings are not echoed or acted on
        await wire.close()
    asyncio.run(run())


def run_call(*, mic_during_cue, idle_packets=True, zeros=True):
    """A CallTrace with no file: 10 s of listening, one cue of 3 s, 10 s more. ``mic_during_cue``: the phone goes on sending while the cue plays."""
    now=[1000.0]
    trace=CallTrace(None,'u119',clock=lambda:now[0]);trace.open(source='phone');trace.frame(READY)
    pcm=b64((b'\0\0' if zeros else b'\x10\x27')*2400)      # 100 ms
    def listen(seconds):
        for _ in range(round(seconds*10)):
            now[0]+=0.1
            if idle_packets:trace.mic({'type':'input_audio_buffer.append','audio':pcm})
            else:now[0]+=0
    def cue(seconds):
        trace.frame({'type':'response.created','response':{'id':'r'}})
        for k in range(round(seconds/0.02)):
            trace.frame({'type':'response.audio.delta','response_id':'r','delta':'AAAA'});now[0]+=0.02
            if mic_during_cue and k%5==4:trace.mic({'type':'input_audio_buffer.append','audio':pcm})
        trace.frame({'type':'response.done','response':{'id':'r','status':'completed'}})
    listen(10);cue(3);listen(10)
    return trace.close(elapsed_ms=1)


def test_the_server_sees_half_duplex_only_as_missing_packets_it_cannot_cause_or_cure():
    """Mechanism: barge-in / hearing the speaker while the cue plays. A phone that drops its microphone while the cue plays leaves the server a gap:
    the meter measures it (coverage ~0, verdict half) but that is all - it is the same evidence the owner's call 08:41 gave (U52)."""
    half=run_call(mic_during_cue=False)
    assert half['duplex']=='half' and half['mic_missing_cue_s']>=2.9
    full=run_call(mic_during_cue=True)
    assert full['duplex']=='full' and full['mic_missing_cue_s']<0.1


def test_packets_count_as_a_live_microphone_whatever_is_in_them():
    """Mechanism: hold / mute / phone-side silence. The meter counts packet LENGTHS (call_trace.CallTrace.mic: 'the audio is never decoded'), so a phone
    that keeps sending digital silence (muted, on hold) is 'full' duplex exactly like a phone that sends the owner's voice: from the stream alone
    the server cannot tell a muted microphone from a quiet room."""
    muted=run_call(mic_during_cue=True,zeros=True)
    voiced=run_call(mic_during_cue=True,zeros=False)
    assert muted['duplex']==voiced['duplex']=='full'
    assert muted['mic_missing_cue_s']==voiced['mic_missing_cue_s']


def test_a_phone_that_sends_nothing_at_all_is_unknown_not_half():
    """Mechanism: hold / app suspended / muted at the client by not sending. No packets in the quiet either: the server says 'unknown' (a muted phone
    measures nothing); it cannot name the cause (hold, mute, background, lost network)."""
    summary=run_call(mic_during_cue=False,idle_packets=False)
    assert summary['duplex']=='unknown'


def test_the_server_scales_only_its_own_outgoing_pcm_it_has_no_hand_on_the_phones_volume():
    """Mechanism: volume / ducking. The one volume lever in the server is voice_boost on the cue's PCM (before it is sent); length and format stay,
    the limiter keeps it from clipping. What the iPhone then does with it (ducking, route, system volume) is outside the protocol."""
    import array,math
    pcm=array.array('h',[int(1500*math.sin(i/6.0)) for i in range(4800)]).tobytes()
    assert b''.join(voice_boost.boost_frames(pcm))==pcm      # the defaults send the bytes untouched
    low,high=(b''.join(voice_boost.boost_frames(pcm,gain=g)) for g in (1.5,3.0))
    peak=lambda data:max(abs(x) for x in array.array('h',data))
    assert len(low)==len(high)==len(pcm)
    assert peak(high)>peak(low)>0 and peak(high)<=voice_boost.CEIL      # a louder cue is a louder PCM, never past the ceiling
