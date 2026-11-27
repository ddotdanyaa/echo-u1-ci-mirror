import asyncio
import pytest
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_prefetch import EarlyLookup
from engine_say import engine_reply

def turn(tid,role,text,final=True):
    return {'type':'turn.done' if final else 'turn.created','turn':{'id':tid,'role':role,'transcript':text}}

def make(tmp_path,clock=None):
    return ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',lookup_policy='required',
        first_useful_gate=True,coalesce_seconds=.8,clock=clock,settings={'words_per_portion':3})

def test_echo_scaffold_is_dropped_and_the_first_short_unit_is_the_cue(tmp_path):
    # WAVE 2 / L2 (was: held until «проводит тепло», 5 words): «Потому что» is scaffolding and never spoken; the cue is the
    # first short unit of the real answer, out as soon as the word after it is whole.
    c=make(tmp_path)
    c.provider(turn('u','user','Почему металлическая ложка кажется холоднее деревянной?'))
    assert c.provider(turn('a','assistant','Потому что металл намного ',False))==[]          # the lookahead word is still missing
    cue=c.provider({'type':'turn.delta','turn_id':'a','delta':'лучше проводит тепло и забирает его у руки. '})[0]
    assert cue['text']=='металл намного' and not cue['text'].startswith('Потому что')
    assert c.state()['chunks'][0]==cue['text']
    assert c.provider(turn('ack','user',cue['text']))==[]
    assert c.state()['stream_waiting_next']                                                  # the rest has not been committed yet
    assert c.provider(turn('a','assistant','Потому что металл намного лучше проводит тепло и забирает его у руки.'))[0]['type']=='speak'
    assert c.state()['chunk_index']==1

def test_reference_echo_is_not_a_useful_first_cue(tmp_path):
    c=make(tmp_path)
    c.provider(turn('u','user','Что устанавливает статья 218 ГК РФ?'))
    c.provider({'type':'delegation.created','item':{'id':'d','target':'client','user_bidi_turn_id':'u'}})
    c.grounding(c.epoch,[{'url':'https://example.org','text':'source'}]);c.delivery_sent(c.epoch,'d')
    assert c.provider(turn('a','assistant','Статья 218 ГК РФ устанавливает ',False))==[]
    cue=c.provider({'type':'turn.delta','turn_id':'a','delta':'основания приобретения права собственности. '})[0]
    assert 'основания' in cue['text'] and len(cue['text'].split())<=6

def test_expanding_the_code_name_is_still_not_the_answer():
    from echo_sync.first_useful import useful
    assert not useful('Статья 218 Гражданского кодекса','Что устанавливает статья 218 ГК РФ?')

def test_reference_opening_is_elided_only_for_the_same_number_code_and_positive_predicate():
    from echo_sync.first_useful import compact_opening,first_prefix
    q='Что устанавливает статья 218-я Гражданского кодекса Российской Федерации?'
    body='Основания приобретения права собственности: создание вещи.'
    assert compact_opening('Статья 218 ГК РФ устанавливает '+body,q)==body
    for opening in ['Статья 219 ГК РФ устанавливает ','Статья 218 НК РФ устанавливает ','Статья 218 ГК РФ не устанавливает ']:
        assert compact_opening(opening+body,q)==opening+body
    assert first_prefix('Основания приобретения ',q,{'words_per_portion':3},final=False) is None
    prefix=first_prefix(body,q,{'words_per_portion':3},final=True)
    assert prefix=='Основания приобретения права собственности:'

@pytest.mark.parametrize('tail',[' газообразное',' газообразное?'])
def test_native_split_question_and_split_name_keep_one_answer_owner(tmp_path,tail):
    now=[0.0];c=make(tmp_path,lambda:now[0])
    head='Как называется переход вещества из твёрдого состояния сразу в'
    c.provider(turn('u1','user',head))
    assert c.provider(turn('a1','assistant','Это называется'))==[]
    now[0]=.3
    c.provider(turn('u2','user',tail,False))
    now[0]=1.2  # Final arrives later; segment START belongs to the short gap.
    c.provider(turn('u2','user',tail))
    result=c.provider(turn('a2','assistant',' сублимация.'))
    assert result and 'сублимация' in result[0]['text'].casefold()
    assert c.question_text==head+tail
    assert c.state()['answer'].casefold()=='сублимация.'

def test_coalescing_keeps_all_preceding_assistant_acoustic_fragments(tmp_path):
    now=[0.];c=make(tmp_path,lambda:now[0])
    c.provider(turn('u1','user','Как называется переход вещества из твёрдого состояния сразу в'))
    assert c.provider(turn('a1','assistant','Это назы'))==[]
    assert c.provider(turn('a2','assistant','вается'))==[]
    now[0]=.3;c.provider(turn('u2','user',' газообразное'))
    result=c.provider(turn('a3','assistant',' сублимация.'))
    assert result and result[0]['text'].casefold()=='сублимация.'

def test_delayed_cloud_tail_keeps_unissued_unfinished_answer_until_confirmation(tmp_path):
    now=[0.];c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',lookup_policy='required',
        first_useful_gate=True,coalesce_seconds=3.2,clock=lambda:now[0],settings={'words_per_portion':3})
    head='Как называется переход вещества из твёрдого состояния сразу в'
    c.provider(turn('u1','user',head))
    assert c.provider(turn('a1','assistant','Это сублимация — сразу из'))==[]
    now[0]=2.67;c.provider(turn('u2','user','газообразное',False))
    now[0]=3.5;c.provider(turn('u2','user','газообразное'))
    result=c.provider(turn('a2','assistant',' твёрдого в газообразное.'))
    assert result and 'сублимация' in result[0]['text'].casefold()
    assert c.question_text==head+' газообразное'

def test_negated_continuation_cannot_adopt_a_prepared_answer(tmp_path):
    now=[0.];c=make(tmp_path,lambda:now[0])
    c.provider(turn('u1','user','Как называется переход вещества в'))
    assert c.provider(turn('old','assistant','Это процесс',False))==[]
    now[0]=.2;c.provider(turn('u2','user','не газообразное'))
    assert c.provider(turn('old','assistant','Это процесс.'))==[]

@pytest.mark.parametrize('tail',['Повтори','Стоп','Почему?','Что такое масса?'])
def test_short_time_window_alone_cannot_join_a_command_or_new_question(tmp_path,tail):
    now=[0.];c=make(tmp_path,lambda:now[0])
    c.provider(turn('u1','user','Как называется переход вещества в'))
    now[0]=.1;c.provider(turn('u2','user',tail))
    assert c.question_text!='Как называется переход вещества в '+tail

def test_long_pause_does_not_join_unrelated_tail(tmp_path):
    now=[0.];c=make(tmp_path,lambda:now[0])
    c.provider(turn('u1','user','Как называется переход вещества в'))
    now[0]=3;c.provider(turn('u2','user','газообразное'))
    assert c.question_text=='Как называется переход вещества в'

def test_a_new_turn_after_an_issued_cue_cannot_rewrite_the_question(tmp_path):
    now=[0.];c=make(tmp_path,lambda:now[0])
    c.provider(turn('u1','user','Что такое движение?'))
    c.provider(turn('a','assistant','Изменение агрегатного состояния вещества.'))
    assert c.published
    now[0]=.1;c.provider(turn('u2','user','газообразное'))
    assert c.question_text=='Что такое движение?'

def test_unfinished_question_cannot_play_a_premature_wrong_name(tmp_path):
    now=[0.];c=make(tmp_path,lambda:now[0])
    c.provider(turn('u1','user','Как называется переход вещества в'))
    assert c.provider(turn('old','assistant','Плавление.'))==[]
    now[0]=.3;c.provider(turn('u2','user','газообразное'))
    assert c.provider(turn('old','assistant','Плавление.'))==[]
    cue=c.provider(turn('new','assistant','Сублимация.'))[0]
    assert cue['text']=='Сублимация.'

@pytest.mark.parametrize('text',['Не является доходом.','Скорость равна минус 15 метрам в секунду.'])
def test_usefulness_gate_keeps_negation_and_number_in_answer(tmp_path,text):
    c=make(tmp_path);c.provider(turn('u','user','Объясни этот случай?'))
    c.provider(turn('a','assistant',text))
    assert c.state()['answer']==text

def test_invalid_first_chunk_cannot_leak_a_cut_word(tmp_path):
    from echo_sync.engine import EchoEngine,SILENT
    from echo_sync.generator import StreamingAnswer
    e=EchoEngine(tmp_path/'s.db',lambda *args:StreamingAnswer('Графическая запись.',final=True,first_chunk='Граф'))
    assert engine_reply(e, session_id='s',turn_id='u',text='Что такое запись?',request={},model='test')==SILENT

@pytest.mark.parametrize('text',['Графическая  запись.','Графическая\nзапись.'])
def test_original_whitespace_cannot_cut_the_first_word(tmp_path,text):
    c=make(tmp_path);c.provider(turn('u','user','Что такое нотация?'))
    result=c.provider(turn('a','assistant',text))
    assert result and result[0]['text'].endswith('запись.')

def test_configured_abbreviation_has_a_real_source_to_spoken_mapping(tmp_path):
    c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',lookup_policy='required',first_useful_gate=True,
        settings={'words_per_portion':3,'abbreviations':{'ЭКГ':'электрокардиограмма'}})
    c.provider(turn('u','user','Как называется запись активности сердца?'))
    result=c.provider(turn('a','assistant','ЭКГ.'))
    assert result and result[0]['text']=='электрокардиограмма.'

@pytest.mark.parametrize('final,adopt',[
    ('Что устанавливает статья 218-я Гражданского кодекса?',True),
    ('Что устанавливает статья 219-я Гражданского кодекса?',False),
    ('Что НЕ устанавливает статья 218-я Гражданского кодекса?',False),
    ('Что устанавливает статья 218-я Налогового кодекса?',False),
    ('Что устанавливала статья 218-я Гражданского кодекса?',False),
])
def test_prefetch_normalizes_existing_ru_forms_but_never_protected_changes(final,adopt):
    async def run():
        calls=[];stages=[]
        async def fetch(q):calls.append(q);return [{'text':q}]
        async def trace(name,**kw):stages.append(name)
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('u','Что устанавливает статья двести восемнадцатая Гражданского кодекса',now=0)
        await e.tick(now=1);await asyncio.sleep(0)
        await e.resolve('u',final)
        assert ('prefetch_adopted' in stages)==adopt
        assert len(calls)==(1 if adopt else 2)
        await e.close()
    asyncio.run(run())

def test_prefetch_normalization_does_not_erase_roles_or_time():
    from echo_sync.native_prefetch import question_key
    assert question_key('Кто передал Ивану данные?')!=question_key('Кто передал Ивана данные?')
    assert question_key('Какая ставка действует сейчас?')!=question_key('Какая ставка действовала сейчас?')

def test_official_public_http_reference_is_not_dropped_after_existing_lookup():
    from echo_sync.controlled_media import public_sources
    row={'url':'http://pravo.gov.ru/example','description':'Public official excerpt.',
        'source_receipt':{'publisher_basis':'recognized institutional publisher'}}
    assert public_sources([row])[0]['url']==row['url']
    assert public_sources([{**row,'url':'http://127.0.0.1/private'}])==[]
    assert public_sources([{**row,'url':'http://user:secret@example.org/private'}])==[]
