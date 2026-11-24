"""Provider-native delegation binds evidence to a question, not a spoken nonce."""
from echo_sync.controlled_media import ControlledMedia

Q='Почему меняются времена года?'
ANSWER='Наклон земной оси меняет освещение полушарий.'
# The text names the subject of Q (DEF-T-11: a row that shares no content word with the question is about something else).
SOURCES=[{'url':'https://example.org','description':'Наклон земной оси определяет смену сезонов: так меняются времена года.'}]
def turn(tid,role,text,final=True):
    return {'type':'turn.done' if final else 'turn.created','turn':{'id':tid,'role':role,'transcript':text}}
def delegate(user='u',did='d'):
    return {'type':'delegation.created','item':{'id':did,'type':'delegation','target':'client',
        'user_bidi_turn_id':user,'content':[{'type':'input_text','text':Q}]}}
def make(tmp_path):
    return ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',settings={'words_per_portion':3})

def test_answer_waits_for_the_correct_delegation_and_its_delivery(tmp_path):
    c=make(tmp_path);epoch=c.provider(turn('u','user',Q))[-1]['epoch']
    assert c.grounding(epoch,SOURCES)==[]
    assert c.provider(turn('a-before','assistant',ANSWER))==[]
    assert c.provider(delegate('another-user'))==[]
    context=c.provider(delegate())[0]
    assert context['delegation_id']=='d' and context['question']==Q
    assert c.provider(turn('a-before-send','assistant',ANSWER))==[]
    c.delivery_sent(epoch,'d')
    cue=c.provider(turn('a-after','assistant',ANSWER))[0]
    assert cue['text']=='Наклон земной оси' and c.authorized(cue)

def test_early_delegation_matches_only_its_later_user_final(tmp_path):
    c=make(tmp_path);c.provider(turn('u','user','Почему',False))
    assert c.provider(delegate())==[]
    epoch=c.provider(turn('u','user',Q))[-1]['epoch']
    context=c.grounding(epoch,SOURCES)[0]
    assert context['delegation_id']=='d'
    assert c.provider(delegate())==[]

def test_repeated_delegation_does_not_start_another_lookup(tmp_path):
    c=make(tmp_path);actions=c.provider(turn('u','user',Q));epoch=actions[-1]['epoch']
    assert c.provider(delegate())==[]
    assert c.grounding(epoch,SOURCES)[0]['delegation_id']=='d'
    assert c.provider(delegate())==[]
    assert c.grounding(epoch,SOURCES)==[]

def test_new_question_retires_old_tool_delivery_and_old_audio(tmp_path):
    c=make(tmp_path);epoch=c.provider(turn('u','user',Q))[-1]['epoch']
    c.provider(delegate());c.grounding(epoch,SOURCES)
    c.provider(turn('u2','user','Что такое фотосинтез?'))
    assert not c.delivery_sent(epoch,'d')
    assert c.provider(turn('a','assistant',ANSWER))==[]

def test_grounded_partial_full_ack_use_the_existing_cursor_without_tools(tmp_path):
    c=make(tmp_path);epoch=c.provider(turn('u','user',Q))[-1]['epoch']
    c.provider(delegate());c.grounding(epoch,SOURCES);c.delivery_sent(epoch,'d')
    first=c.provider(turn('a','assistant',ANSWER))[0]['text']
    assert c.provider(turn('partial','user','Наклон земной'))==[]
    assert c.provider(turn('negative','user','Не '+first))==[]
    result=c.provider(turn('ack','user',first))
    assert [x['type'] for x in result]==['speak'] and c.state()['chunk_index']==1
    assert c.provider(delegate('ack','not-a-question'))==[]

def test_delegation_is_a_real_question_boundary_even_without_user_turn_done(tmp_path):
    # Real failing call: user fragments -> delegation.created -> model waits
    # forever for a result; it never emits turn.done before that result.
    c=make(tmp_path);c.provider(turn('u','user',Q,False))
    actions=c.provider(delegate())
    assert [x['type'] for x in actions]==['cancel','lookup']
    assert c.user_boundaries['u']=='provider_delegation'
    assert c.ledger.snapshot('u')['final'] is False  # never forge provider ASR
    assert c.provider(turn('u','user',Q))==[]  # actual later final is idempotent

def test_an_ack_delegation_cannot_be_promoted_to_a_new_question(tmp_path):
    c=make(tmp_path);c.provider(turn('u','user',Q));c.provider(delegate());c.grounding(c.epoch,SOURCES);c.delivery_sent(c.epoch,'d')
    first=c.provider(turn('a','assistant',ANSWER))[0]['text']
    c.provider(turn('ack','user',first,False))
    assert c.provider(delegate('ack','wrong-tool'))==[]
    assert c.state()['chunk_index']==0

def test_same_assistant_turn_can_continue_after_its_real_tool_reply(tmp_path):
    c=make(tmp_path);epoch=c.provider(turn('u','user',Q))[-1]['epoch']
    c.provider(delegate());c.provider(turn('a','assistant',' Сейчас уточню.',False))
    c.grounding(epoch,SOURCES);c.delivery_sent(epoch,'d')
    cue=c.provider(turn('a','assistant',' Сейчас уточню. '+ANSWER))[0]
    assert cue['text']=='Наклон земной оси'
    assert c.state()['answer']==ANSWER

def test_process_only_partial_after_tool_return_stays_silent(tmp_path):
    c=make(tmp_path);epoch=c.provider(turn('u','user',Q))[-1]['epoch']
    c.provider(delegate());c.grounding(epoch,SOURCES);c.delivery_sent(epoch,'d')
    assert c.provider(turn('a','assistant','Сейчас уточню.',False))==[]
    cue=c.provider(turn('a','assistant','Сейчас уточню. '+ANSWER))[0]
    assert cue['text']=='Наклон земной оси'

def test_source_time_statement_and_negation_are_not_service_filler():
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix('Сейчас действует другая ставка.')=='Сейчас действует другая ставка.'
    assert strip_process_prefix('Не является доходом.')=='Не является доходом.'
    assert strip_process_prefix('«Сейчас уточню» — прямая речь.')=='«Сейчас уточню» — прямая речь.'
    assert strip_process_prefix('Я подожду проверку.')==''
    assert strip_process_prefix('Подожду проверку. '+ANSWER)==ANSWER

def test_tool_boundary_never_cuts_a_grammatical_definition_in_half(tmp_path):
    c=make(tmp_path);q='Что такое инерция?'
    epoch=c.provider(turn('u','user',q))[-1]['epoch'];c.provider(delegate())
    c.provider(turn('a','assistant','Свойство ',False))
    c.grounding(epoch,[{'url':'https://example.org','text':'Инерция — свойство тела сохранять состояние покоя.'}]);c.delivery_sent(epoch,'d')
    cue=c.provider(turn('a','assistant','Свойство тела сохранять состояние покоя.'))[0]
    assert cue['text'].startswith('Свойство')
    assert c.state()['answer']=='Свойство тела сохранять состояние покоя.'

def test_unchanged_pretool_content_is_not_replayed_as_a_new_answer(tmp_path):
    c=make(tmp_path);epoch=c.provider(turn('u','user',Q))[-1]['epoch'];c.provider(delegate())
    c.provider(turn('a','assistant',ANSWER,False));c.grounding(epoch,SOURCES);c.delivery_sent(epoch,'d')
    assert c.provider(turn('a','assistant',ANSWER))==[]


def test_waiting_for_search_data_never_becomes_an_audible_cue():
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix('Жду данных, чтобы точно ответить.')==''
    assert strip_process_prefix('Жду данных, чтобы точно ответить. '+ANSWER)==ANSWER
    assert strip_process_prefix('Ожидаю источники. '+ANSWER)==ANSWER
    assert strip_process_prefix('Жду ребёнка у школы.')=='Жду ребёнка у школы.'
    assert strip_process_prefix('«Жду данных» — слова автора.')=='«Жду данных» — слова автора.'


def test_native_assistant_segments_can_split_a_word_without_finalizing_the_answer(tmp_path):
    c=make(tmp_path)
    q='Как называется запись электрической активности головного мозга?'
    epoch=c.provider(turn('u','user',q))[-1]['epoch'];c.provider(delegate())
    c.grounding(epoch,[{'url':'https://example.org','text':'Электроэнцефалограмма — запись электрической активности мозга.'}])
    c.delivery_sent(epoch,'d')
    c.provider(turn('a1','assistant',' Электроэнцефалограмма. Граф'))
    first=c.state()
    assert not first or 'Граф' not in first['answer']
    c.provider(turn('a2','assistant','ическая запись электрической'))
    c.provider(turn('a3','assistant',' активности мозга с помощью электродов на коже головы.'))
    state=c.state()
    assert state['answer']=='Электроэнцефалограмма. Графическая запись электрической активности мозга с помощью электродов на коже головы.'
    assert not state['streaming']
    assert all(chunk!='Граф' for chunk in state['chunks'])


def test_a_second_overlapping_assistant_turn_cannot_replace_an_unfinished_turn(tmp_path):
    c=make(tmp_path);epoch=c.provider(turn('u','user',Q))[-1]['epoch'];c.provider(delegate())
    c.grounding(epoch,SOURCES);c.delivery_sent(epoch,'d')
    c.provider(turn('a1','assistant','Наклон земной оси меняет освещение ',False))
    before=c.published
    assert c.provider(turn('a2','assistant','Новый посторонний ответ.'))==[]
    assert c.published==before
