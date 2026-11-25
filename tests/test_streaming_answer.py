"""Streaming must preserve the existing deterministic spoken-ACK contract."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from echo_sync.engine import EchoEngine,SILENT
from echo_sync.generator import StreamingAnswer
from engine_say import engine_reply

PREFIX='Первый второй третий'
FULL=PREFIX+' четвёртый пятый шестой седьмой восьмой девятый.'

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def setup(tmp_path,question='Что такое инерция?'):
 calls=[]
 def generate(*args):calls.append(args);return StreamingAnswer(PREFIX)
 engine=EchoEngine(tmp_path/'stream.db',generate,settings={'words_per_portion':3})
 reply=engine_reply(engine, session_id='s',turn_id='q',text=question,request={},model='Live-stream')
 return engine,calls,reply

def turn(engine,text,tid):
 return engine_reply(engine, session_id='s',turn_id=tid,text=text,request={},model='Live-stream')

def test_prefix_is_available_and_history_is_not_falsely_final(tmp_path):
 engine,calls,reply=setup(tmp_path)
 assert reply==PREFIX and len(calls)==1
 state=engine.state('s')
 assert state['streaming'] and not state['completed']
 assert state['history'][-1]['incomplete'] is True

def test_appending_does_not_reissue_or_replan_existing_cues(tmp_path):
 engine,_,_=setup(tmp_path);before=engine.state('s');rev=before['revision']
 assert engine.extend_answer(session_id='s',revision=rev,answer=FULL)==SILENT
 after=engine.state('s')
 assert after['chunks'][:len(before['chunks'])]==before['chunks']
 assert after['chunk_index']==before['chunk_index']
 assert after['answer']==FULL
 assert turn(engine,PREFIX,'ack')=='четвёртый пятый шестой'

def test_frontier_ack_waits_and_new_text_releases_exactly_once(tmp_path):
 engine,calls,_=setup(tmp_path);rev=engine.state('s')['revision']
 assert turn(engine,PREFIX,'ack')==SILENT
 assert engine.state('s')['stream_waiting_next']
 assert not engine.state('s')['completed']
 assert turn(engine,PREFIX,'duplicate-spoken')==SILENT
 assert engine.extend_answer(session_id='s',revision=rev,answer=FULL)=='четвёртый пятый шестой'
 assert engine.state('s')['chunk_index']==1
 assert engine.extend_answer(session_id='s',revision=rev,answer=FULL)==SILENT
 assert len(calls)==1

def test_partial_and_wrong_negation_do_not_authorize_next(tmp_path):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision']
 assert turn(engine,'Первый второй','partial')==SILENT
 assert turn(engine,'Не '+PREFIX,'wrong')==SILENT
 assert engine.extend_answer(session_id='s',revision=rev,answer=FULL)==SILENT
 assert engine.state('s')['chunk_index']==0

def test_frontier_repeat_replays_current_without_consuming_next(tmp_path):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision']
 turn(engine,PREFIX,'ack')
 assert turn(engine,'повтори','repeat')==PREFIX
 assert engine.state('s')['stream_waiting_next']
 assert engine.extend_answer(session_id='s',revision=rev,answer=FULL)=='четвёртый пятый шестой'

def test_final_without_new_words_finishes_only_after_ack(tmp_path):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision']
 assert engine.extend_answer(session_id='s',revision=rev,answer=PREFIX,final=True)==SILENT
 assert not engine.state('s')['streaming'] and not engine.state('s')['completed']
 assert 'incomplete' not in engine.state('s')['history'][-1]
 assert turn(engine,PREFIX,'ack')==SILENT
 assert engine.state('s')['completed']

def test_final_after_frontier_ack_closes_without_repeating(tmp_path):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision'];turn(engine,PREFIX,'ack')
 assert engine.extend_answer(session_id='s',revision=rev,answer=PREFIX,final=True)==SILENT
 assert engine.state('s')['completed']

def test_restart_retains_pending_ack_and_final_content(tmp_path):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision'];turn(engine,PREFIX,'ack')
 reloaded=EchoEngine(engine.path,lambda *args:pytest.fail('ACK cannot generate'))
 assert reloaded.extend_answer(session_id='s',revision=rev,answer=FULL,final=True)=='четвёртый пятый шестой'
 assert reloaded.state('s')['history'][-1]['answer']==FULL
 assert 'incomplete' not in reloaded.state('s')['history'][-1]

@pytest.mark.parametrize('action',['stop','new-question'])
def test_retired_stream_cannot_resume(tmp_path,action):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision']
 turn(engine,'стоп' if action=='stop' else 'Другой вопрос: почему светит Солнце?','retire')
 assert engine.extend_answer(session_id='s',revision=rev,answer=FULL,final=True) is None

def test_rewriting_prefix_and_reopening_final_are_rejected(tmp_path):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision'];before=engine.state('s')
 assert engine.extend_answer(session_id='s',revision=rev,answer='Другой ответ') is None
 assert engine.state('s')==before
 engine.extend_answer(session_id='s',revision=rev,answer=FULL,final=True)
 assert engine.extend_answer(session_id='s',revision=rev,answer=FULL,final=True)==SILENT
 assert engine.extend_answer(session_id='s',revision=rev,answer=FULL+' Дальше.') is None

def test_two_simultaneous_extensions_do_not_duplicate_release(tmp_path):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision'];turn(engine,PREFIX,'ack')
 with ThreadPoolExecutor(max_workers=2) as pool:
  replies=list(pool.map(lambda _:engine.extend_answer(session_id='s',revision=rev,answer=FULL),range(2)))
 assert replies.count('четвёртый пятый шестой')==1 and replies.count(SILENT)==1

def test_no_unverified_law_prefix_is_issued(tmp_path):
 # route 16.11: what may be published is cm-route's rule (``ControlledMedia._publishable``; the refusal through the real engine is pinned in test_g1_admit): the bare engine publishes what it is handed
 from echo_sync.controlled_media import ControlledMedia
 question='Что устанавливает статья 87 НК РФ?'
 assert not ControlledMedia._publishable(StreamingAnswer(PREFIX),question,())
 assert ControlledMedia._publishable(StreamingAnswer(PREFIX),'Что такое инерция?',())
 assert ControlledMedia._publishable(StreamingAnswer(PREFIX,[{'url':'u'}],retrieval_status='source_backed'),question,())
 assert ControlledMedia._publishable(StreamingAnswer(PREFIX,retrieval_status='local_reference'),question,())

def test_a_word_cannot_be_extended_after_it_was_issued(tmp_path):
 engine,_,_=setup(tmp_path);rev=engine.state('s')['revision']
 assert engine.extend_answer(session_id='s',revision=rev,answer=PREFIX+'ся дальше') is None

def test_partial_ack_merged_with_hearing_repeat_replays_current(tmp_path):
 engine,_,_=setup(tmp_path)
 engine.settings={}
 assert turn(engine,'Первый второй. Повтори, я не расслышал.','merged')==PREFIX
 assert engine.state('s')['chunk_index']==0
 assert not engine.state('s')['stream_waiting_next']

def test_unrelated_question_with_repeat_words_is_not_a_repeat_command(tmp_path):
 engine,calls,_=setup(tmp_path)
 turn(engine,'Почему первый закон Ньютона так называется? Повтори, я не расслышал.','different')
 assert len(calls)==2
