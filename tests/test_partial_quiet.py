"""Conduit's3s user-quiet fallback is an observation, never a fake ACK."""
import asyncio
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket

def event(tid,role,text,final=True):
 return {'type':'turn.done' if final else 'turn.created','turn':{'id':tid,'role':role,'transcript':text}}

def ready(tmp_path):
 c=ControlledMedia(tmp_path/'s.db',session_id='s',settings={'words_per_portion':3,'repeat_seconds':3})      # the silence of this scene is 3 s (the default is the settings' 6 s since timers: one repeat_seconds value)
 c.provider(event('q','user','Почему меняются времена года?'))
 c.grounding(c.epoch,[{'url':'https://example.org','text':'source'}])
 c.provider(event('a','assistant',c.answer_marker+'Наклон земной оси меняет освещение полушарий.'))
 return c

def test_partial_quiet_rearms_current_without_consuming_partial_or_forging_final(tmp_path):
 c=ready(tmp_path);c.speech_started();c.provider(event('u','user','Наклон',False))
 observed=c.partial_quiet(now=10)
 assert observed['text']=='Наклон' and c.state()['chunk_index']==0
 assert c.ledger.snapshot('u')['final'] is False and 'u' not in c.seen
 assert c.tick(now=12)==[]
 assert c.tick(now=13)[0]['text']=='Наклон земной оси'
 assert c.provider(event('u','user','Наклон земной оси'))[0]['text']=='меняет освещение полушарий.'

def test_quiet_observation_cannot_authorize_full_ack_or_new_question(tmp_path):
 c=ready(tmp_path);c.speech_started();c.provider(event('u','user','Наклон земной оси',False))
 assert c.partial_quiet(now=10) is None and c.state()['chunk_index']==0
 c.provider(event('other','user','Что такое фотосинтез?',False))
 assert c.partial_quiet(now=20) is None and c.state()['chunk_index']==0

def test_socket_quiet_receipt_is_explicit_and_resumed_speech_freezes_repetition(tmp_path):
 async def run():
  c=ready(tmp_path);sent=[];clock=[0]
  async def emit(x):sent.append(x)
  wire=NativeMediaSocket(c,emit,None,None,None,clock=lambda:clock[0]);wire.ready=True
  await wire.provider(event('u','user','Наклон',False));clock[0]=3.1;await wire.tick()
  observations=[x for x in sent if x['type']=='conversation.item.input_audio_transcription.completed']
  assert observations[-1]['echo_boundary']=='adapter_partial_quiet'
  assert c.state()['chunk_index']==0 and not c.ledger.snapshot('u')['final']
  await wire.provider({'type':'turn.delta','turn_id':'u','delta':' земной'})
  assert c.hearing and c.repeat_at is None
  await wire.close()
 asyncio.run(run())
