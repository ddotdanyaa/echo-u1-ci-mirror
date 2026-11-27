"""Word-boundary ASR fragmentation in explicit hearing repair commands."""
import pytest
from echo_sync.classifier import analyze,REPEAT,ACK

STATE={'chunks':['Наклон земной оси'],'chunk_index':0,'completed':False}
@pytest.mark.parametrize('text',['Повтори, я не расс лышал.','Пов тори, я не расслышал.','Повтори, я не ус лышал.'])
def test_fragmented_hearing_repair_remains_a_repeat(text):
 assert analyze(text,STATE,[],{'on_mismatch':'silent'}).kind==REPEAT

def test_word_folding_cannot_drop_new_content_or_numbers():
 assert analyze('Повтори, я не расслышал 15 процентов.',STATE,[],{'on_mismatch':'silent'}).kind!=REPEAT
 assert analyze('Повтори другое определение.',STATE,[],{'on_mismatch':'silent'}).kind!=REPEAT

def test_exact_expected_command_quotation_still_acknowledges_instead():
 s={'chunks':['Повтори я не расслышал'],'chunk_index':0,'completed':False}
 assert analyze('Повтори я не расслышал',s,[],{}).kind==ACK
