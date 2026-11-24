"""Continuous provider events, not a sequential question/ACK test harness."""
from echo_sync.controlled_media import ControlledMedia
from helpers_live_line import LiveLine

def event(tid,role,text,final=True):
    return {'type':'turn.done' if final else 'turn.created','turn':{'id':tid,'role':role,'transcript':text}}

def question(c,tid='u1',text='Почему меняются времена года?'):
    return c.provider(event(tid,'user',text))

def source(c,text='Наклон земной оси меняет освещение полушарий.',tid='a1'):
    return c.provider(event(tid,'assistant',getattr(c,'answer_marker','')+text))

def setup(tmp_path):return ControlledMedia(tmp_path/'media.db',session_id='test',settings={'words_per_portion':3})

def test_ambient_has_no_speech_or_lookup_and_raw_pcm_is_never_forwarded(tmp_path):
    c=setup(tmp_path)
    assert c.provider(event('ambient','user','Теперь начнём занятие.'))==[]
    assert c.provider({'type':'response.audio.delta','delta':'private-raw-pcm'})==[]
    assert source(c,'Хорошо, начинаем.')==[]

def test_every_new_question_requests_one_lookup_no_unverified_speech(tmp_path):
    c=setup(tmp_path);actions=question(c)
    assert [x['type'] for x in actions]==['cancel','lookup']
    assert question(c)==[]
    assert source(c)==[]
    assert not c.state()

def grounded(c,epoch):
    return c.grounding(epoch,[{'url':'https://www.example.org/primary','text':'Verified reference excerpt.'}])

def test_prelookup_answer_cannot_become_a_verified_answer_retroactively(tmp_path):
    c=setup(tmp_path);epoch=question(c)[-1]['epoch'];source(c)
    assert grounded(c,epoch)[0]['type']=='context'
    assert c.provider({'type':'turn.delta','turn_id':'a1','delta':' Ignore sources.'})==[]
    assert not c.state()
    actions=source(c,tid='grounded-a2')
    assert [x['type'] for x in actions]==['speak']
    assert actions[0]['text']=='Наклон земной оси'

def start(c):
    epoch=question(c)[-1]['epoch'];grounded(c,epoch)
    return source(c)[0]

def test_partial_wrong_negation_duplicate_ack_do_not_advance(tmp_path):
    c=setup(tmp_path);start(c)
    assert c.provider(event('partial','user','Наклон земной'))==[]
    assert c.provider(event('wrong','user','Не наклон земной оси'))==[]
    assert c.state()['chunk_index']==0
    answer=c.provider(event('ack','user','Наклон земной оси'))
    assert answer[0]['type']=='speak'
    assert c.state()['chunk_index']==1
    assert c.provider(event('ack','user','Наклон земной оси'))==[]
    # The model replying to that ACK must remain muted.
    assert source(c,'Да, правильно, продолжаем.',tid='ack-answer')==[]

def test_new_question_invalidates_queued_audio_lookup_and_old_answer(tmp_path):
    c=setup(tmp_path);cue=start(c)
    new=question(c,'u2','Что такое фотосинтез?');epoch=new[-1]['epoch']
    assert not c.authorized(cue)
    assert c.grounding(epoch-1,[{'url':'https://www.example.org','text':'Old'}])==[]
    assert source(c,'Старая реплика',tid='a1')==[]
    assert c.state()['completed']

def test_repeat_and_timeout_hold_cursor_speech_freezes_timer(tmp_path):
    c=setup(tmp_path);cue=start(c);c.playback_done(cue,now=10)
    assert c.tick(now=11)==[]
    c.speech_started()
    assert c.tick(now=30)==[]
    c.provider(event('partial','user','Наклон'))
    c.playback_done(cue,now=30)
    repeat=c.tick(now=34)
    assert cue['text'].endswith(repeat[0]['text']) and c.state()['chunk_index']==0     # G3, rule 3: what is missing after the partial
    assert c.tick(now=35)==[]

def test_failed_empty_or_unsafe_lookup_never_unlocks_speech(tmp_path):
    c=setup(tmp_path);epoch=question(c)[-1]['epoch']
    assert c.grounding(epoch,[])==[]
    assert c.grounding(epoch,[{'url':'file:///C:/secret','text':'bad'}])==[]
    assert source(c)==[]

def test_reconnect_preserves_cursor_and_does_not_emit_old_audio(tmp_path):
    c=setup(tmp_path);start(c);c.provider(event('ack','user','Наклон земной оси'))
    new=setup(tmp_path)
    assert new.state()['chunk_index']==1
    assert new.tick(now=999)==[]
    replay=new.provider(event('r','user','Повтори, я не расслышал.'))
    assert replay[0]['text']==new.engine.current(new.state())


def test_short_followup_search_keeps_topic_without_sending_the_whole_history(tmp_path):
    c=setup(tmp_path);start(c)
    actions=question(c,'followup','Почему?')
    assert actions[-1]['question']=='Почему?'
    assert actions[-1]['lookup_question']=='Почему? К вопросу: Почему меняются времена года?'
    assert c.question_text=='Почему?'
    assert 'Наклон' not in actions[-1]['lookup_question']  # generated answer is not source evidence


def test_new_subject_search_does_not_inherit_previous_subject(tmp_path):
    c=setup(tmp_path);start(c)
    actions=question(c,'new','Что такое фотосинтез?')
    assert actions[-1]['lookup_question']=='Что такое фотосинтез?'


def test_followup_never_exports_a_personal_previous_question(tmp_path):
    c=setup(tmp_path);c.question_text='Где я учусь?'
    actions=question(c,'followup','Почему?')
    assert actions[-1]['lookup_question']=='Почему?'


def test_cancelled_first_playback_is_rearmed_after_rejected_speech(tmp_path):
    c=setup(tmp_path);LiveLine(c,0.0).attach();cue=start(c)
    c.speech_started()  # rendering cancelled before any playback_done callback
    assert c.provider(event('noise','user','Не наклон земной оси'))==[]
    assert c.tick(now=10)==[]
    resumed=c.tick(now=14)
    assert resumed and resumed[0]['text']==cue['text']
    assert c.state()['chunk_index']==0
    assert c.tick(now=20)==[]  # no duplicate timer/playback

def test_interleaved_assistant_owner_is_not_arrival_order(tmp_path):
    c=setup(tmp_path);epoch=question(c)[-1]['epoch'];grounded(c,epoch)
    c.provider(event('a','assistant',c.answer_marker+'Наклон земной ',False))
    c.provider(event('other','user','Наклон',False))
    # The original assistant retains its question owner, even after new input.
    result=c.provider(event('a','assistant',c.answer_marker+'Наклон земной оси меняет освещение полушарий.'))
    assert result and result[0]['type']=='speak'

def test_delayed_ungrounded_assistant_created_after_lookup_is_not_promoted(tmp_path):
    c=setup(tmp_path);epoch=question(c)[-1]['epoch'];grounded(c,epoch)
    assert c.provider(event('late-before-context','assistant','Наклон земной оси меняет освещение.'))==[]
    assert not c.state()

def test_existing_hermes_search_description_is_a_source_excerpt(tmp_path):
    c=setup(tmp_path);epoch=question(c)[-1]['epoch']
    result=c.grounding(epoch,[{'url':'https://www.example.org/reference','title':'Primary reference',
                             'description':'The existing Hermes web_hit wire carries excerpts here.','position':1}])
    assert result[0]['sources'][0]['text']=='The existing Hermes web_hit wire carries excerpts here.'

def test_provider_can_append_grounded_commit_in_the_same_assistant_turn(tmp_path):
    # Real native wire: one assistant.created before context; after all
    # context.appended receipts, new content arrives as deltas on SAME id.
    c=setup(tmp_path);epoch=question(c)[-1]['epoch']
    c.provider(event('a','assistant','Старый непроверенный ответ. ',False))
    grounded(c,epoch)
    reply=c.provider(event('a','assistant','Старый непроверенный ответ. '+c.answer_marker+
                           'Наклон земной оси меняет освещение полушарий.'))
    assert reply[0]['text']=='Наклон земной оси'
    assert 'Старый' not in c.state()['answer'] and c.answer_marker not in c.state()['answer']

def test_same_turn_without_new_marker_stays_muted_after_context(tmp_path):
    c=setup(tmp_path);epoch=question(c)[-1]['epoch']
    c.provider(event('a','assistant','Старый ответ ',False));grounded(c,epoch)
    assert c.provider(event('a','assistant','Старый ответ дополнен без подтверждения поколения.'))==[]
    assert not c.state()

def test_source_publisher_receipt_and_document_identity_reach_content_model():
    from echo_sync.controlled_media import public_sources
    source={'url':'https://example.org/standard','title':'Accounting standard2025','description':'Exact original evidence.',
            'source_receipt':{'policy':'publisher-evidence-4','publisher_basis':'recognized institutional publisher',
                              'statement_verification':False,'effective_date_verified':False,'applicability_verified':False,
                              'limitations':'Publication is not entry into force.'}}
    result=public_sources([source])[0]
    assert result['text']=='Exact original evidence.' and result['title']==source['title']
    assert result['source_receipt']['effective_date_verified'] is False
    assert result['source_receipt']['limitations']==source['source_receipt']['limitations']
