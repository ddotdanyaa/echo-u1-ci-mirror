"""Subscription frameless turn IDs must survive interleaved live speech."""
from echo_sync.voice_turns import FramelessTurns

def created(tid,role,text,start=0):
 return {'type':'turn.created','turn':{'id':tid,'role':role,'transcript':text,'start_ms':start,'end_ms':start+100}}

def delta(tid,text,start,end):
 return {'type':'turn.delta','turn_id':tid,'delta':text,'start_ms':start,'end_ms':end}

def done(tid,role,text,start=0):
 return {'type':'turn.done','turn':{'id':tid,'role':role,'transcript':text,'start_ms':start,'end_ms':start+1000}}

def test_interleaved_output_does_not_become_part_of_new_user_question():
 f=FramelessTurns();f.apply(created('u1','user','Теперь',1000));f.apply(delta('u1',' экономика',1200,2000))
 f.apply(created('a1','assistant','Совокупность',2100));f.apply(created('u2','user','Чем',2200))
 f.apply(delta('a1',' отношений',2200,2400));f.apply(delta('u2',' доход отличается от прибыли',2500,4000))
 assert f.latest_user()['text']=='Чем доход отличается от прибыли'
 assert f.snapshot('u1')['text']=='Теперь экономика'
 assert f.snapshot('a1')['text']=='Совокупность отношений'

def test_final_snapshot_deduplicates_turn_and_overwrites_partial_asr():
 f=FramelessTurns();f.apply(created('u','user','Инер'))
 f.apply(delta('u','ция',100,300));event=done('u','user','Инерция.')
 assert f.apply(event)['final'] is True
 assert f.apply(event) is None
 assert f.latest_user()['text']=='Инерция.'

def test_old_final_cannot_replace_latest_partial_user_turn():
 f=FramelessTurns();f.apply(created('old','user','Повтори',1000));f.apply(created('new','user','Новый вопрос',3000))
 f.apply(done('old','user','Повтори, я не расслышал.',1000))
 assert f.latest_user()['id']=='new'
 assert f.latest_user(require_final=True) is None

def test_replayed_delta_does_not_duplicate_but_repeated_words_can_exist():
 f=FramelessTurns();f.apply(created('u','user','Нет'))
 frame=delta('u',' нет',100,200);f.apply(frame);assert f.apply(frame) is None
 f.apply(delta('u',' нет',300,400))
 assert f.latest_user()['text']=='Нет нет нет'

def test_unrecognised_role_and_unknown_delta_cannot_invent_a_user():
 f=FramelessTurns();assert f.apply(delta('missing','старый ответ',0,100)) is None
 assert f.apply(created('x','tool','Секрет')) is None
 assert f.latest_user() is None

def test_revised_user_final_updates_the_turn_and_a_change_of_role_is_a_conflict():
 # WAVE 2 / Task B (DEF-STATE-03): a second, different final of a USER turn is a refined transcript of the same speech. The turn is
 # updated and stays eligible (a permanent conflict muted the call); its owner acts once per turn id, so it is still not a new ack.
 f=FramelessTurns();f.apply(done('u','user','15 процентов'))
 f.apply(done('u','user','50 процентов'))
 assert f.snapshot('u')['valid'] and f.snapshot('u')['text']=='50 процентов' and f.snapshot('u')['revisions']==1
 f.apply(done('r','user','раз'));f.apply(done('r','assistant','раз'))
 assert f.snapshot('r')['conflicted'] and not f.snapshot('r')['valid']

def test_bounded_history_and_oversized_partial_are_not_eligible():
 f=FramelessTurns(max_turns=2,max_chars=20)
 for i in range(4):f.apply(created(str(i),'user','Текст',i*1000))
 assert len(f.history())==2 and f.latest_user()['id']=='3'
 f.apply(delta('3','x'*50,3100,3200));assert not f.latest_user()['valid']
 f.apply(done('3','user','Текст.',3000));assert f.latest_user()['valid']

def test_transcript_events_are_not_appended_a_second_time():
 f=FramelessTurns();f.apply(created('u','user','Чем'))
 f.apply({'type':'input_transcript.added','item':{'id':'one-fragment','text':'Чем'}})
 assert f.latest_user()['text']=='Чем'

def test_malformed_provider_frames_do_not_destroy_the_turn_map():
 f=FramelessTurns();f.apply(created('u','user','Вопрос',1000))
 for event in (None,[],{'type':'turn.delta','turn_id':[],'delta':'x'},
               {'type':'turn.created','turn':{'id':'bad','role':[],'transcript':'x'}},
               created('bad-clock','user','x',float('nan'))):
  assert f.apply(event) is None
 assert f.latest_user()['id']=='u'
