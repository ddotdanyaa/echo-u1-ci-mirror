"""Production PCM-frame authorization and stale-generation guard, synthetic PCM only."""
import asyncio

from playback_wire_slice import PlaybackWire


class Wire(PlaybackWire):
    def __init__(self, on_emit=None):
        self.send_lock=asyncio.Lock()
        self.closed=False
        self.audio_generation=3
        self.voice_gain=None
        self.voice_presence=None
        self.cloud_witness=None
        self.gate_cues=[]
        self.events=[]
        self.on_emit=on_emit

    def _cue_to_gate(self,pcm):
        self.gate_cues.append(len(pcm))

    async def emit(self,event):
        self.events.append(event)
        if self.on_emit is not None:
            self.on_emit(event)

    async def _send(self,event):
        self.events.append(event)


def packet(frames=3):
    # Silent, synthetic S16 mono, 960 bytes per audio frame.
    return b"\0"*(960*frames)


def types(w):
    return [e["type"] for e in w.events]


def play(w,authorized=lambda:True,**kw):
    return asyncio.run(w._play(packet(), "Синтетическая подсказка",3,authorized,**kw))


def test_valid_cue_generates_exactly_one_completed_response():
    w=Wire()
    played=[]
    started=[]
    abandoned=[]
    assert play(w,played=played.append,started=started.append,
                abandoned=lambda *a:abandoned.append(a)) is True
    assert types(w).count("response.created")==1
    assert types(w).count("response.audio.delta")==3
    assert types(w).count("response.done")==1
    assert not any(x=="output_audio_buffer.clear" for x in types(w))
    assert len(played)==1 and len(started)==1 and not abandoned


def test_invalid_before_any_pcm_does_not_create_a_phone_response():
    w=Wire()
    assert play(w,authorized=lambda:False) is False
    assert w.events==[]
    assert w.gate_cues==[]


def test_question_superseded_during_stream_sends_no_more_pcm():
    def supersede(event):
        if event["type"]=="response.audio.delta":
            w.audio_generation=4
    w=Wire(on_emit=supersede)
    abandoned=[]
    assert play(w,abandoned=lambda *a:abandoned.append(a)) is False
    assert types(w).count("response.audio.delta")==1
    assert "response.done" not in types(w)
    assert len(abandoned)==1 and abandoned[0][2]=="superseded"


def test_controller_revokes_authority_after_first_packet():
    state={"current":True}
    def revoke(event):
        if event["type"]=="response.audio.delta":
            state["current"]=False
    w=Wire(on_emit=revoke)
    abandoned=[]
    assert play(w,authorized=lambda:state["current"],
                abandoned=lambda *a:abandoned.append(a)) is False
    assert types(w).count("response.audio.delta")==1
    assert "response.done" not in types(w)
    assert types(w).count("output_audio_buffer.clear")==1
    assert len(abandoned)==1 and abandoned[0][2]=="unauthorized"


def test_closing_transport_during_stream_never_completes_stale_audio():
    def close(event):
        if event["type"]=="response.audio.delta":
            w.closed=True
    w=Wire(on_emit=close)
    assert play(w) is False
    assert types(w).count("response.audio.delta")==1
    assert "response.done" not in types(w)


def test_revoked_at_final_boundary_does_not_complete_audio():
    counter={"n":0}
    def authorize():
        counter["n"]+=1
        return counter["n"]<=3
    w=Wire()
    assert play(w,authorized=authorize) is False
    assert types(w).count("response.audio.delta")==3
    assert "response.done" not in types(w)
    assert types(w).count("output_audio_buffer.clear")==1
