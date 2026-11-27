"""Early lookup prepares evidence only; matching final question authorizes use."""
import asyncio
import pytest
from echo_sync.native_prefetch import EarlyLookup


def test_stable_partial_is_prepared_and_matching_final_reuses_one_request():
    async def run():
        calls=[];events=[]
        async def fetch(q):calls.append(q);return [{'text':'evidence'}]
        async def trace(stage,**values):events.append((stage,values))
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('u','Что такое инерция',now=1)
        await e.tick(now=1.4);assert calls==[]
        await e.tick(now=1.6);await asyncio.sleep(0)
        assert len(calls)==1
        assert await e.resolve('u','Что такое инерция?')==[{'text':'evidence'}]
        assert len(calls)==1 and any(x[0]=='prefetch_adopted' for x in events)
        await e.close()
    asyncio.run(run())


@pytest.mark.parametrize('replacement',['Статья 87 НК РФ','Не является доходом','Статья 15 ТК РФ'])
def test_changed_number_negation_or_code_never_adopts_old_evidence(replacement):
    async def run():
        calls=[]
        async def fetch(q):calls.append(q);return [{'text':q}]
        async def trace(*args,**kwargs):pass
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('u','Статья 15 НК РФ',now=0);await e.tick(now=1);await asyncio.sleep(0)
        rows=await e.resolve('u',replacement)
        assert rows==[{'text':replacement}] and len(calls)==2
        await e.close()
    asyncio.run(run())


def test_partial_revisions_cannot_start_a_request_per_word():
    async def run():
        calls=[]
        async def fetch(q):calls.append(q);return []
        async def trace(*args,**kwargs):pass
        e=EarlyLookup(fetch,trace,enabled=True)
        for i,q in enumerate(['Что такое инерция','Что такое инерция тела','Что такое инерция тела в физике']):
            e.observe('u',q,now=i);await e.tick(now=i+.8);await asyncio.sleep(0)
        assert len(calls)==1
        await e.resolve('u','Что такое инерция тела в физике?')
        assert len(calls)==2
        await e.close()
    asyncio.run(run())


def test_same_words_from_another_user_turn_cannot_reuse_old_task():
    async def run():
        calls=[]
        async def fetch(q):calls.append(q);return []
        async def trace(*args,**kwargs):pass
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('old','Что такое инерция',now=0);await e.tick(now=1);await asyncio.sleep(0)
        await e.resolve('new','Что такое инерция')
        assert len(calls)==2
        await e.close()
    asyncio.run(run())


def test_disabled_baseline_never_starts_early():
    async def run():
        calls=[]
        async def fetch(q):calls.append(q);return []
        async def trace(*args,**kwargs):pass
        e=EarlyLookup(fetch,trace,enabled=False)
        e.observe('u','Что такое инерция',now=0);await e.tick(now=10)
        assert not calls
        await e.resolve('u','Что такое инерция');assert len(calls)==1
        await e.close()
    asyncio.run(run())


def test_closing_cancels_pending_speculation():
    async def run():
        cancelled=[]
        async def fetch(q):
            try:await asyncio.sleep(100)
            finally:cancelled.append(True)
        async def trace(*args,**kwargs):pass
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('u','Что такое инерция',now=0);await e.tick(now=1);await asyncio.sleep(0)
        await e.close();assert cancelled==[True]
    asyncio.run(run())


def test_real_wire_partial_starts_lookup_but_cannot_authorize_playback(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    from echo_sync.native_media_socket import NativeMediaSocket
    async def run():
        queries=[];sent=[];clock=[0]
        async def fetch(q):queries.append(q);return [{'url':'https://example.org','text':'source'}]
        async def emit(e):sent.append(e)
        c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation')
        w=NativeMediaSocket(c,emit,None,fetch,None,prefetch=True,clock=lambda:clock[0],diagnostics=True)
        w.ready=True
        await w.provider({'type':'turn.created','turn':{'id':'u','role':'user','transcript':'Что такое инерция'}})
        clock[0]=.6;await w.tick();await asyncio.sleep(0)
        assert queries==['Что такое инерция'] and c.question_id is None and not c.grounded
        assert not any(e['type']=='response.audio.delta' for e in sent)
        await w.provider({'type':'turn.done','turn':{'id':'u','role':'user','transcript':'Что такое инерция?'}})
        await asyncio.sleep(.01)
        assert len(queries)==1 and c.grounded
        assert any(e.get('stage')=='prefetch_adopted' for e in sent)
        await w.close()
    asyncio.run(run())


def test_private_partial_and_final_never_reach_public_lookup(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    from echo_sync.native_media_socket import NativeMediaSocket
    async def run():
        queries=[];clock=[0]
        async def fetch(q):queries.append(q);return []
        async def emit(e):pass
        c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation')
        w=NativeMediaSocket(c,emit,None,fetch,None,prefetch=True,clock=lambda:clock[0]);w.ready=True
        for kind in ('turn.created','turn.done'):
            await w.provider({'type':kind,'turn':{'id':'u','role':'user','transcript':'Как зовут моего преподавателя?'}})
            clock[0]+=1;await w.tick();await asyncio.sleep(.01)
        assert queries==[]
        await w.close()
    asyncio.run(run())


def test_cue_is_withheld_until_actual_question_final_then_released(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    from echo_sync.native_media_socket import NativeMediaSocket
    async def run():
        sent=[]
        async def emit(e):sent.append(e)
        async def synth(text):return b'\0'*960
        c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',settings={'words_per_portion':3})
        w=NativeMediaSocket(c,emit,None,None,synth,prefetch=True,diagnostics=True);w.ready=True
        upstream=[]
        class Source:                                   # the helper pipe: the result of the delegation goes up here
            async def send(self,kind,payload=b''):upstream.append((kind,payload))
            async def close(self):pass
        w.source=Source()
        await w.provider({'type':'turn.created','turn':{'id':'u','role':'user','transcript':'Что такое инерция?'}})
        # Controller-native delegation is allowed to start preparation.
        actions=c.provider({'type':'delegation.created','item':{'id':'d','target':'client','user_bidi_turn_id':'u'}})
        assert actions[-1]['type']=='lookup'
        # F3 round 1: the sources are ready before the question is final, but the RESULT of the delegation is sent only once it is (a partial
        # decides nothing); an answer the model gives before that is not the answer to the question.
        assert c.grounding(c.epoch,[{'url':'https://example.org','text':'source'}])==[] and not upstream
        await w.provider({'type':'turn.done','turn':{'id':'a','role':'assistant','transcript':'Свойство тела сохранять состояние покоя.'}})
        await asyncio.sleep(.03)
        assert not any(e['type']=='response.audio.delta' for e in sent) and not upstream
        await w.provider({'type':'turn.done','turn':{'id':'u','role':'user','transcript':'Что такое инерция?'}})
        await asyncio.sleep(.03)
        assert upstream and c.delivery_ready                    # the result went up at the final
        assert not any(e['type']=='response.audio.delta' for e in sent)
        await w.provider({'type':'turn.done','turn':{'id':'a2','role':'assistant','transcript':'Свойство тела сохранять состояние покоя.'}})
        await asyncio.sleep(.06)
        assert any(e['type']=='response.audio.delta' for e in sent)
        await w.close()
    asyncio.run(run())


def test_changed_final_same_provider_turn_retires_provisional_question(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation')
    c.provider({'type':'turn.created','turn':{'id':'u','role':'user','transcript':'Что устанавливает статья 15 НК РФ?'}})
    c.provider({'type':'delegation.created','item':{'id':'d','target':'client','user_bidi_turn_id':'u'}})
    old=c.epoch
    actions=c.provider({'type':'turn.done','turn':{'id':'u','role':'user','transcript':'Что устанавливает статья 87 НК РФ?'}})
    assert c.epoch>old and '87' in c.question_text
    assert actions[-1]['type']=='lookup' and '87' in actions[-1]['lookup_question']
    assert c.grounding(old,[{'url':'https://example.org','text':'wrong article'}])==[]


def test_confirmed_lookup_cannot_start_late_speculation():
    async def run():
        calls=[];finish=asyncio.Event()
        async def fetch(q):calls.append(q);await finish.wait();return []
        async def trace(*args,**kwargs):pass
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('u','Что такое инерция',now=0)
        actual=asyncio.create_task(e.resolve('u','Что такое инерция'));await asyncio.sleep(0)
        await e.tick(now=1);await asyncio.sleep(0)
        assert len(calls)==1
        finish.set();await actual;await e.close()
    asyncio.run(run())


def test_suspended_start_trace_cannot_relabel_another_question():
    async def run():
        entered=asyncio.Event();resume=asyncio.Event()
        async def fetch(q):return [{'text':q}]
        async def trace(stage,**kwargs):
            if stage=='speculation_started':entered.set();await resume.wait()
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('u','question A alpha',now=0)
        ticking=asyncio.create_task(e.tick(now=1));await entered.wait()
        e.observe('u','question B beta',now=1);resume.set();await ticking
        assert await e.resolve('u','question A alpha')==[{'text':'question A alpha'}]
        await e.close()
    asyncio.run(run())


def test_suspended_adoption_trace_awaits_its_captured_task():
    async def run():
        entered=asyncio.Event();resume=asyncio.Event()
        async def fetch(q):return [{'text':q}]
        async def trace(stage,**kwargs):
            if stage=='prefetch_adopted':entered.set();await resume.wait()
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('a','question A alpha',now=0);await e.tick(now=1);await asyncio.sleep(0)
        resolving=asyncio.create_task(e.resolve('a','question A alpha'));await entered.wait()
        e.observe('b','question B beta',now=2);await e.tick(now=3);await asyncio.sleep(0)
        resume.set();assert await resolving==[{'text':'question A alpha'}]
        await e.close()
    asyncio.run(run())


def test_personal_previous_topic_is_not_added_to_public_followup(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    c=ControlledMedia(tmp_path/'s.db',session_id='s')
    def heard(tid,text):return {'type':'turn.done','turn':{'id':tid,'role':'user','transcript':text}}
    c.provider(heard('u1','Что известно обо мне?'))
    actions=c.provider(heard('u2','Приведи пример'))
    assert actions[-1]['lookup_question']=='Приведи пример'


def test_close_cannot_start_fallback_from_an_adopted_cancelled_task():
    async def run():
        calls=[]
        async def fetch(q):calls.append(q);await asyncio.sleep(100)
        async def trace(*args,**kwargs):pass
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('u','Что такое инерция',now=0);await e.tick(now=1);await asyncio.sleep(0)
        resolving=asyncio.create_task(e.resolve('u','Что такое инерция'));await asyncio.sleep(0)
        await e.close();await asyncio.sleep(0)
        try:assert len(calls)==1
        finally:
            resolving.cancel();await asyncio.gather(resolving,return_exceptions=True)
    asyncio.run(run())


def test_input_turn_has_a_hard_two_request_budget():
    async def run():
        calls=[]
        async def fetch(q):calls.append(q);return [{'text':q}]
        async def trace(*args,**kwargs):pass
        e=EarlyLookup(fetch,trace,enabled=True)
        e.observe('u','Что такое инерция',now=0);await e.tick(now=1);await asyncio.sleep(0)
        await e.resolve('u','Что такое инерция тела?')
        with pytest.raises(RuntimeError):await e.resolve('u','А что такое ускорение?')
        assert len(calls)==2
        await e.close()
    asyncio.run(run())


def test_confirmed_question_can_receive_native_session_context_without_model_delegation(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    from echo_sync.native_media_socket import context_frames
    c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',session_context_fallback=True,settings={'words_per_portion':3})
    question='Почему меняются времена года?'
    c.provider({'type':'turn.done','turn':{'id':'u','role':'user','transcript':question}})
    action=c.grounding(c.epoch,[{'url':'https://example.org','text':'Наклон земной оси определяет смену сезонов: так меняются времена года.'}])[0]
    assert action['source_transport']=='session_context' and action['delegation_id'] is None
    frames=context_frames(action)
    assert all(f['type']=='session.context.append' for f in frames)
    joined=''.join(f['content'][0]['text'] for f in frames)
    assert question in joined and 'Наклон земной оси' in joined and action['marker'] not in joined
    assert c.delivery_sent(c.epoch,None)
    cue=c.provider({'type':'turn.done','turn':{'id':'a','role':'assistant','transcript':'Наклон земной оси меняет освещение полушарий.'}})[0]
    assert cue['text']=='Наклон земной оси' and c.authorized(cue)


def test_session_context_fallback_does_not_authorize_an_unconfirmed_question(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',session_context_fallback=True)
    c.provider({'type':'turn.created','turn':{'id':'u','role':'user','transcript':'Почему меняются времена года?'}})
    assert c.question_id is None
    assert c.grounding(c.epoch,[{'url':'https://example.org','text':'source'}])==[]
    assert not c.delivery_sent(c.epoch,None)


def test_session_context_does_not_relabel_preexisting_answer_as_new_sourced_content(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',session_context_fallback=True)
    def turn(tid,role,text,final=True):return {'type':'turn.done' if final else 'turn.created','turn':{'id':tid,'role':role,'transcript':text}}
    c.provider(turn('u','user','Почему меняются времена года?'))
    c.provider(turn('old','assistant','Солнце уходит',False))
    c.grounding(c.epoch,[{'url':'https://example.org','text':'Наклон земной оси определяет смену сезонов: так меняются времена года.'}])
    assert c.delivery_sent(c.epoch,None)
    assert c.provider(turn('old','assistant','Солнце уходит дальше от Земли.'))==[]
    assert c.state() is None


def test_required_lookup_policy_allows_stable_content_without_a_model_handoff(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',lookup_policy='required',settings={'words_per_portion':3})
    def turn(tid,role,text):return {'type':'turn.done','turn':{'id':tid,'role':role,'transcript':text}}
    actions=c.provider(turn('u','user','Почему металлическая ложка кажется холоднее деревянной?'))
    assert not any(a['type']=='lookup' for a in actions)
    assert c.provider(turn('a','assistant','Металл быстрее отводит тепло от кожи.'))[0]['text']=='Металл быстрее отводит'
    assert c.state()['retrieval_status']=='unverified'


def test_required_policy_still_requires_sources_for_law_and_does_not_prefetch_common_fact(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',lookup_policy='required')
    c.provider({'type':'turn.created','turn':{'id':'u','role':'user','transcript':'Что такое инерция?'}})
    assert c.prefetch_candidate() is None
    actions=c.provider({'type':'turn.done','turn':{'id':'v','role':'user','transcript':'Что устанавливает статья 218 ГК РФ?'}})
    assert actions[-1]['type']=='lookup'
    assert c.provider({'type':'turn.done','turn':{'id':'a','role':'assistant','transcript':'Непроверенная формулировка нормы.'}})==[]


def test_revised_direct_question_cannot_reuse_old_content_or_engine_turn_id(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    c=ControlledMedia(tmp_path/'s.db',session_id='s',source_delivery='delegation',lookup_policy='required',settings={'words_per_portion':3})
    def turn(tid,role,text,final=True):return {'type':'turn.done' if final else 'turn.created','turn':{'id':tid,'role':role,'transcript':text}}
    c.provider(turn('u','user','Что такое инерция?',False))
    c.provider({'type':'delegation.created','item':{'id':'d','target':'client','user_bidi_turn_id':'u'}})
    old=c.provider(turn('old','assistant','Инерция — свойство тела сохранять состояние покоя и равномерного ',False))[0]
    c.provider(turn('u','user','Что такое ускорение?'))
    assert not c.authorized(old)
    assert c.provider(turn('old','assistant','Инерция — свойство тела сохранять состояние покоя и равномерного движения.'))==[]
    c.provider(turn('new','assistant','Изменение скорости тела за единицу времени.'))
    assert c.state()['question']=='Что такое ускорение?'
    assert c.state()['answer'].startswith('Изменение скорости')
