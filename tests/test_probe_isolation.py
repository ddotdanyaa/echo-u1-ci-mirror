from echo_sync.controlled_media import ControlledMedia
from echo_sync.controlled_host import controller_session_id

def turn(tid,role,text):return {'type':'turn.done','turn':{'id':tid,'role':role,'transcript':text}}

def make(path,sid='live-native-controlled-v1'):
    return ControlledMedia(path,session_id=sid,source_delivery='delegation',lookup_policy='required',quiet_reopen=True,settings={'words_per_portion':3})

def test_new_call_cannot_auto_repeat_or_ack_a_stale_unpresented_cue(tmp_path):
    path=tmp_path/'s.db';first=make(path)
    first.provider(turn('u','user','Что такое инерция?'))
    cue=first.provider(turn('a','assistant','Свойство тела сохранять состояние покоя.'))[0]
    reopened=make(path)
    assert reopened.provider(turn('noise','user','Так, проверка, работает'))==[]
    assert reopened.tick(now=100000)==[]
    assert reopened.provider(turn('unpresented','user',cue['text']))==[]
    assert reopened.state()['chunk_index']==0
    repeat=reopened.provider(turn('repeat','user','Повтори'))[0]
    assert repeat['text']==cue['text']
    assert reopened.provider(turn('ack','user',cue['text']))[0]['type']=='speak'
    assert reopened.state()['chunk_index']==1

def test_partial_speech_cannot_arm_an_old_cue_before_it_was_presented(tmp_path):
    path=tmp_path/'s.db';first=make(path)
    first.provider(turn('u','user','Что такое инерция?'))
    first.provider(turn('a','assistant','Свойство тела сохранять состояние покоя.'))
    reopened=make(path);reopened.speech_started()
    reopened.provider({'type':'turn.created','turn':{'id':'noise','role':'user','transcript':'Проверка'}})
    assert reopened.partial_quiet(now=10) is None
    assert reopened.tick(now=100)==[]

def test_synthetic_probe_never_changes_the_users_saved_cursor(tmp_path):
    path=tmp_path/'s.db';real=make(path)
    real.provider(turn('real','user','Почему меняются времена года?'))
    real.provider(turn('a','assistant','Наклон земной оси меняет освещение полушарий.'))
    before=real.state()
    sid=controller_session_id({'echo_trace':'1','echo_probe_id':'a'*32})
    assert sid!='live-native-controlled-v1'
    probe=make(path,sid)
    probe.provider(turn('probe','user','Что такое масса?'))
    probe.provider(turn('p','assistant','Мера инертности тела.'))
    assert real.state()==before

def test_probe_namespace_requires_trace_and_a_valid_identifier():
    assert controller_session_id({})=='live-native-controlled-user-v1'
    assert controller_session_id({'echo_probe_id':'a'*32})==controller_session_id({})
    assert controller_session_id({'echo_trace':'1','echo_probe_id':'../../private'}).startswith('native-probe-')
    assert controller_session_id({'echo_trace':'1'}).startswith('native-probe-')
    assert controller_session_id({'echo_trace':'1','echo_probe_id':'a'*32})!=controller_session_id({'echo_trace':'1','echo_probe_id':'b'*32})
