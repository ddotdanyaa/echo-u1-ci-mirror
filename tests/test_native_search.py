"""Subscription-only selective retrieval, source persistence and fail-closed output."""
import tempfile
from pathlib import Path
from types import SimpleNamespace as S
import unittest

from echo_sync.generator import PrivateCodexGenerator
from echo_sync.engine import EchoEngine
from engine_say import engine_reply

URL='https://developer.apple.com/documentation/avfaudio/avaudiosession'


def search_events(*, cited=True, searched=True, url=URL):
    events=[]
    if searched:events.append(S(type='response.web_search_call.completed',item_id='search1'))
    if cited:events.append(S(type='response.output_text.annotation.added',output_index=1,content_index=0,annotation={'type':'url_citation','url':url,'title':'Primary source'}))
    events.extend([S(type='response.output_text.done',output_index=1,content_index=0,text='Подтверждённый ответ.\ue200cite\ue202turn0search0\ue201'),
                   S(type='response.completed',response=S(output=[],status='completed'))])
    return events


class NativeSearchTests(unittest.TestCase):
    def test_spoken_verification_commands_route_without_question_mark_but_expected_quote_wins(self):
        from echo_sync.classifier import analyze
        for text in ('Проверь факт','Найди официальный источник','Поищи актуальную ставку'):
            self.assertEqual(analyze(text,None,[]).kind,'question')
        state={'chunks':['Проверь дату источника'],'chunk_index':0,'completed':False,'pending_turn':None}
        self.assertEqual(analyze('Проверь дату источника',state,[]).kind,'ack')
        self.assertIn(analyze('Проверь дату',state,[]).kind,('replay','silent'))

    def invoke(self,question,events=None,history=None):
        self.requests=[];self.closed=False
        owner=self
        class Stream:
            def __iter__(self):return iter(search_events() if events is None else events)
            def close(self):owner.closed=True
        class Client:
            def __init__(self,**kwargs):
                self.responses=self
                owner.assertEqual(kwargs['base_url'],'https://chatgpt.com/backend-api/codex')
                owner.assertEqual(kwargs['max_retries'],0)
            def create(self,**kwargs):owner.requests.append(kwargs);return Stream()
            def close(self):pass
        gen=PrivateCodexGenerator(resolve=lambda:{'api_key':'a.b.c','base_url':'https://chatgpt.com/backend-api/codex'},
                                 headers=lambda *a,**kw:{},client_factory=Client)
        return gen(question,history or [],'',{},'offline')

    def test_explicit_verification_uses_only_native_web_tool_in_one_request(self):
        answer=self.invoke('Проверь по официальному источнику назначение режима voiceChat')
        self.assertEqual(self.requests[0]['tools'],[{'type':'web_search'}])
        self.assertNotIn('tool_choice',self.requests[0])
        self.assertEqual(len(self.requests),1)
        self.assertEqual(str(answer),'Подтверждённый ответ.')
        self.assertEqual(answer.sources[0]['url'],URL)
        self.assertEqual(answer.retrieval_status,'source_backed')
        self.assertTrue(self.closed)

    def test_stable_definitions_do_not_get_tools(self):
        for question in ('Что такое фотосинтез?','Что такое налог?','Как рассчитать процент от числа?'):
            with self.subTest(question=question):
                self.invoke(question)
                self.assertNotIn('tools',self.requests[0])

    def test_fresh_numbers_and_law_articles_use_verification(self):
        for question in ('Какая сейчас ключевая ставка?','Какой размер штрафа?',
                         'Что устанавливает статья 15 Налогового кодекса?', 'Какие последние новости?'):
            with self.subTest(question=question):
                self.invoke(question)
                self.assertIn('tools',self.requests[0])

    def test_phone_ordinal_article_query_requires_search(self):
        self.invoke('15-я статья налогового кодекса')
        self.assertIn('tools',self.requests[0])

    def test_short_followup_inherits_time_sensitive_context(self):
        self.invoke('Почему?',history=[{'question':'Какая сейчас ставка?','answer':'Предыдущий ответ.'}])
        self.assertIn('tools',self.requests[0])

    def test_declared_but_unexecuted_or_uncited_search_is_not_a_verified_answer(self):
        for cited,searched in ((True,False),(False,True),(False,False)):
            with self.subTest(cited=cited,searched=searched):
                answer=self.invoke('Проверь актуальную ставку',search_events(cited=cited,searched=searched))
                self.assertEqual(answer.retrieval_status,'unavailable')
                self.assertNotIn('Подтверждённый ответ',str(answer))
                self.assertEqual(answer.sources,())
                self.assertEqual(len(self.requests),1)

    def test_private_or_credential_citation_urls_are_not_retained(self):
        for url in ('http://127.0.0.1/private','https://user:secret@example.com/a','https://localhost/a',
                    'https://localhost./a','https://@example.com/a','https://2130706433/a'):
            with self.subTest(url=url):
                answer=self.invoke('Проверь факт',search_events(url=url))
                self.assertEqual(answer.retrieval_status,'unavailable')
                self.assertEqual(answer.sources,())

    def test_settled_output_items_can_supply_search_status_and_annotations(self):
        events=[S(type='response.output_item.done',item={'type':'web_search_call','status':'completed'}),
                S(type='response.output_item.done',output_index=1,item={'type':'message','content':[
                    {'type':'output_text','text':'Ответ по источнику.','annotations':[
                        {'type':'url_citation','url':URL,'title':'Primary'}]}]}),
                S(type='response.output_text.done',output_index=1,content_index=0,text='Ответ по источнику.'),
                S(type='response.completed',response=S(output=[],status='completed'))]
        answer=self.invoke('Проверь факт',events)
        self.assertEqual(answer.retrieval_status,'source_backed')
        self.assertEqual(answer.sources[0]['url'],URL)

    def test_correction_and_chained_followups_keep_verification(self):
        for status in ('source_backed','unavailable'):
            history=[{'question':'Какая сейчас ставка?','answer':'Ответ.', 'retrieval_status':status},
                     {'question':'Почему?','answer':'Уточнение.', 'retrieval_status':status}]
            for question in ('Почему?','Исправь, я спрашивал про США','Нет, я имел в виду другую страну'):
                with self.subTest(status=status,question=question):
                    self.invoke(question,history=history)
                    self.assertIn('tools',self.requests[0])
            self.invoke('Что такое фотосинтез?',history=history)
            self.assertNotIn('tools',self.requests[0])

    def test_discarded_message_citation_cannot_back_final_answer(self):
        events=search_events()
        events[1].item_id='discarded'
        events[2].item_id='discarded'
        events[-1]=S(type='response.completed',response={'status':'completed','output':[
            {'type':'message','id':'final','content':[{'type':'output_text','text':'Unsupported final assertion.','annotations':[]}]}]})
        answer=self.invoke('Проверь факт',events)
        self.assertEqual(answer.retrieval_status,'unavailable')
        self.assertEqual(answer.sources,())

    def test_terminal_only_citation_belongs_to_selected_message(self):
        events=[S(type='response.completed',response={'status':'completed','output':[
            {'type':'web_search_call','status':'completed'},
            {'type':'message','id':'final','content':[{'type':'output_text','text':'Ответ.',
                'annotations':[{'type':'url_citation','url':URL,'title':'Primary'}]}]}]})]
        answer=self.invoke('Проверь факт',events)
        self.assertEqual(answer.retrieval_status,'source_backed')

    def test_part_citation_cannot_attach_to_other_content(self):
        events=search_events()
        events[1].content_index=1
        answer=self.invoke('Проверь факт',events)
        self.assertEqual(answer.retrieval_status,'unavailable')

    def test_engine_correction_preserves_verification_for_pending_and_completed_question(self):
        import threading
        for pending in (False,True):
            with self.subTest(pending=pending), tempfile.TemporaryDirectory() as td:
                entered=threading.Event();release=threading.Event();calls=[]
                def generate(question,history,*args):
                    calls.append((question,history))
                    if len(calls)==1 and pending:
                        entered.set();release.wait(5)
                    return self.invoke(question,history=history)
                e=EchoEngine(Path(td)/'state.db',generate)
                def first():
                    engine_reply(e, session_id='s',turn_id='q',text='Какая сейчас ставка?',request={},model='offline')
                if pending:
                    worker=threading.Thread(target=first);worker.start()
                    self.assertTrue(entered.wait(2))
                else:first()
                try:
                    engine_reply(e, session_id='s',turn_id='repair',text='Исправь, я спрашивал про США',request={},model='offline')
                    self.assertIn('tools',self.requests[0])
                    self.assertEqual(e.state('s')['retrieval_status'],'source_backed')
                finally:
                    release.set()
                    if pending:worker.join(5);self.assertFalse(worker.is_alive())

    def test_stop_keeps_the_paused_answer_with_its_provenance_and_history(self):
        # CL2, ruling 1: «стоп» pauses the answer instead of clearing it, so its sources stay with it.
        answer=self.invoke('Проверь факт')
        with tempfile.TemporaryDirectory() as td:
            e=EchoEngine(Path(td)/'state.db',lambda *args:answer)
            engine_reply(e, session_id='s',turn_id='q',text='Проверь факт',request={},model='offline')
            engine_reply(e, session_id='s',turn_id='stop',text='Стоп',request={},model='offline')
            state=e.state('s')
            self.assertTrue(state['paused'])
            self.assertEqual(state['answer'],str(answer).strip())
            self.assertEqual(state['sources'][0]['url'],URL)
            self.assertEqual(state['retrieval_status'],'source_backed')
            self.assertEqual(state['history'][-1]['sources'][0]['url'],URL)

    def test_a_new_question_clears_the_current_provenance_but_keeps_history(self):
        answer=self.invoke('Проверь факт')
        with tempfile.TemporaryDirectory() as td:
            e=EchoEngine(Path(td)/'state.db',lambda *args:answer)
            engine_reply(e, session_id='s',turn_id='q',text='Проверь факт',request={},model='offline')
            e.retire('s','new_question')
            state=e.state('s')
            self.assertEqual(state['answer'],'')
            self.assertFalse(state.get('sources'))
            self.assertNotIn('retrieval_status',state)
            self.assertEqual(state['history'][-1]['sources'][0]['url'],URL)

    def test_sources_persist_with_answer_and_ack_never_generates_again(self):
        answer=self.invoke('Проверь факт')
        with tempfile.TemporaryDirectory() as td:
            calls=[]
            def generate(*args):calls.append(1);return answer
            path=Path(td)/'state.db';e=EchoEngine(path,generate)
            engine_reply(e, session_id='s',turn_id='q',text='Проверь факт',request={},model='offline')
            before=e.state('s');self.assertEqual(before['sources'][0]['url'],URL)
            current=before['chunks'][0]
            engine_reply(e, session_id='s',turn_id='ack',text=current,request={},model='offline')
            restored=EchoEngine(path,generate).state('s')
            self.assertEqual(restored['sources'],before['sources'])
            self.assertEqual(restored['retrieval_status'],'source_backed')
            self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
