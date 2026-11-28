"""The installed LocalLive wire must not fall back to a text model or raw audio."""
import asyncio
import base64
import json
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.controlled_media import ControlledMedia

import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


class Source:
    def __init__(self):self.frames=[];self.closed=False
    async def send(self,kind,payload=b''):self.frames.append((kind,payload))
    async def close(self):self.closed=True


def test_lookup_failure_diagnostic_exposes_type_without_private_error_text(tmp_path):
    async def run():
        sent=[]
        async def emit(x):sent.append(x)
        async def lookup(_):raise TimeoutError('private token and question must not be emitted')
        c=ControlledMedia(tmp_path/'s.db',session_id='s')
        c.provider({'type':'turn.done','turn':{'id':'u','role':'user','transcript':'Что такое инерция?'}})
        wire=NativeMediaSocket(c,emit,lambda:None,lookup,lambda _:None,diagnostics=True)
        await wire._lookup({'epoch':c.epoch,'question':c.question_text})
        assert {'type':'conduit.echo.stage','stage':'lookup_failure','error_type':'TimeoutError'} in sent
        assert 'private token' not in json.dumps(sent)
        assert any(x.get('error',{}).get('code')=='controlled_sources_unavailable' for x in sent)
        await wire.close()
    asyncio.run(run())

def test_readiness_follows_native_hermes_marker_without_text_model(tmp_path):
    async def run():
        sent=[];source=Source();made=[]
        async def emit(frame):sent.append(frame)
        async def connect():made.append(True);return source
        wire=NativeMediaSocket(ControlledMedia(tmp_path/'s.db',session_id='s'),emit,connect,lambda _:None,lambda _:None)
        await wire.client({'type':'session.update','session':{}})
        assert made==[True] and sent[-1]['type']=='session.updated'
        marker='conduit-ready-test'
        await wire.client({'type':'response.create','response':{'conversation':'none','input':[{'content':[{'text':marker}]}]}})
        assert sent[-1]['type']=='conduit.turn' and sent[-1]['text']==marker
        await wire.client({'type':'input_audio_buffer.append','audio':base64.b64encode(b'\0'*960).decode()})
        assert not source.frames
        await wire.client({'type':'conduit.turn.done','turn_id':sent[-1]['turn_id']})
        assert wire.ready and sent[-1]['type']=='response.done'
        await wire.client({'type':'input_audio_buffer.append','audio':base64.b64encode(b'\0'*960).decode()})
        assert source.frames==[('P',b'\0'*960)]*2      # U76 on purpose: the packet before ready is kept and goes first, then the one after
        await wire.close();assert source.closed
    asyncio.run(run())

def test_bad_or_oversized_pcm_and_unknown_agent_work_are_not_forwarded(tmp_path):
    async def run():
        sent=[];source=Source()
        async def emit(x):sent.append(x)
        async def connect():return source
        wire=NativeMediaSocket(ControlledMedia(tmp_path/'s.db',session_id='s'),emit,connect,lambda _:None,lambda _:None)
        wire.source=source;wire.ready=True
        for audio in ('not-base64!',base64.b64encode(b'odd').decode(),base64.b64encode(b'\0'*100000).decode()):
            await wire.client({'type':'input_audio_buffer.append','audio':audio})
        await wire.client({'type':'conduit.agent','instructions':'Run a separate text agent'})
        assert not source.frames
        assert sum(x['type']=='error' for x in sent)==3
        await wire.close()
    asyncio.run(run())

def test_failure_to_prepare_upstream_cannot_claim_ready(tmp_path):
    async def run():
        sent=[]
        async def emit(x):sent.append(x)
        async def connect():raise RuntimeError('provider unavailable')
        wire=NativeMediaSocket(ControlledMedia(tmp_path/'s.db',session_id='s'),emit,connect,lambda _:None,lambda _:None)
        await wire.client({'type':'session.update'})
        assert not wire.ready and not any(x['type']=='session.updated' for x in sent)
        assert sent[-1]['error']['code']=='controlled_upstream_unavailable'
        await wire.close()
    asyncio.run(run())

def test_cancel_discards_already_synthesizing_stale_audio(tmp_path):
    async def run():
        sent=[];started=asyncio.Event();finish=asyncio.Event()
        async def emit(x):sent.append(x)
        async def synth(text, end=None):started.set();await finish.wait();return b'\0'*960
        c=ControlledMedia(tmp_path/'s.db',session_id='s',settings={'words_per_portion':3})
        async def connect():return Source()
        wire=NativeMediaSocket(c,emit,connect,lambda _:None,synth);wire.ready=True
        def turn(tid,role,text):return {'type':'turn.done','turn':{'id':tid,'role':role,'transcript':text}}
        c.provider(turn('u','user','Почему меняются времена года?'));c.grounding(c.epoch,[{'url':'https://example.org','text':'source'}])
        cue=c.provider(turn('a','assistant',getattr(c,'answer_marker','')+'Наклон земной оси меняет освещение.'))[0]
        await wire.actions([cue]);await started.wait()
        await wire.actions(c.speech_started());finish.set();await asyncio.sleep(.01)
        assert not any(x['type']=='response.audio.delta' for x in sent)
        assert any(x['type']=='output_audio_buffer.clear' for x in sent)
        await wire.close()
    asyncio.run(run())

def test_source_lookup_is_once_per_question_and_repeat_does_not_search(tmp_path):
    async def run():
        sent=[];queries=[];source=Source()
        async def emit(x):sent.append(x)
        async def connect():return source
        async def lookup(q):queries.append(q);return [{'url':'https://example.org','text':'source'}]
        async def synth(t, end=None):return b'\0'*960
        c=ControlledMedia(tmp_path/'s.db',session_id='s')
        wire=NativeMediaSocket(c,emit,connect,lookup,synth);wire.ready=True;wire.source=source
        question={'type':'turn.done','turn':{'id':'u','role':'user','transcript':'Что такое инерция?'}}
        await wire.provider(question);await wire.provider(question);await asyncio.sleep(.01)
        assert len(queries)==1
        assert source.frames[0][0]=='E' and 'инерция' in json.loads(source.frames[0][1])['content'][0]['text']
        assert not any(x['type']=='response.audio.delta' for x in sent)
        await wire.close()
    asyncio.run(run())

def test_actual_user_final_is_saved_in_phone_transcript_once(tmp_path):
    async def run():
        sent=[]
        async def emit(x):sent.append(x)
        async def connect():return Source()
        c=ControlledMedia(tmp_path/'s.db',session_id='s')
        wire=NativeMediaSocket(c,emit,connect,lambda _:[],lambda _:b'');wire.ready=True
        turn={'type':'turn.done','turn':{'id':'u','role':'user','transcript':'Теперь начнём занятие.'}}
        await wire.provider(turn);await wire.provider(turn)
        final=[x for x in sent if x['type']=='conversation.item.input_audio_transcription.completed']
        assert len(final)==1 and final[0]['transcript']=='Теперь начнём занятие.'
        await wire.close()
    asyncio.run(run())

def test_grounding_reuses_codex_500_utf8_byte_quiet_context_contract():
    from echo_sync.native_media_socket import context_frames
    action={'epoch':7,'question':'Почему '+('сложный вопрос 🧠 '*90),
            'sources':[{'url':'https://example.org','text':'Факты и определения. '*180}],
            'marker':'[ECHO:test]'}
    frames=context_frames(action)
    assert len(frames)>3
    assert all(len(frame['content'][0]['text'].encode('utf-8'))<=500 for frame in frames)
    assert all(frame['channel']=='commentary' for frame in frames[:-1])
    assert frames[-1]['channel']=='speakable' and action['marker'] in frames[-1]['content'][0]['text']
    # Unlike a split speakable request, there is exactly one response trigger.
    restored=''.join(frame['content'][0]['text'] for frame in frames[:-1])
    assert action['question'] in restored and action['sources'][0]['text'] in restored

def test_native_delegation_reply_uses_the_original_provider_item_id():
    from echo_sync.native_media_socket import context_frames
    frames=context_frames({'epoch':1,'question':'Что такое инерция?','sources':[{'url':'https://example.org','text':'data'}],
                           'delegation_id':'provider-item-1','marker':'unused'})
    assert all(x['type']=='delegation.context.append' and x['delegation_item_id']=='provider-item-1' for x in frames)
    assert sum(x['channel']=='speakable' for x in frames)==1
    assert all(len(x['content'][0]['text'].encode())<=500 for x in frames)
    assert 'unused' not in frames[-1]['content'][0]['text']

def test_delegation_result_is_actual_speakable_evidence_not_a_progress_commit():
    from echo_sync.native_media_socket import context_frames
    source='Свойство тела сохранять состояние движения. '*50
    frames=context_frames({'epoch':1,'question':'Что такое инерция?','sources':[{'url':'https://example.org','text':source}],
                           'delegation_id':'provider-item-1','marker':'unused'})
    assert all(x['channel']=='speakable' for x in frames)
    joined=''.join(x['content'][0]['text'] for x in frames)
    assert source in joined and 'Проверка выполнена' not in joined and 'unused' not in joined

def test_trace_stages_go_to_the_call_trace_without_diagnostics(tmp_path):
    """U07-S4: ``trace_note`` gets the TRACE_STAGES (and only those) even when the phone is sent no diagnostics."""
    async def run():
        sent=[];noted=[]
        async def emit(x):sent.append(x)
        c=ControlledMedia(tmp_path/'s.db',session_id='s')
        wire=NativeMediaSocket(c,emit,lambda:None,lambda _:[],lambda _:None)
        wire.trace_note=lambda ev,**f:noted.append((ev,f))
        await wire._observe('synthesis_start',number=1);await wire._observe('content_route',route='x')
        assert noted==[('stage',{'name':'synthesis_start','number':1})] and sent==[]
        wire.trace_note=lambda ev,**f:1/0
        await wire._observe('synthesis_end',number=1)      # a failing trace never touches the call
        await wire.close()
    asyncio.run(run())

