import pytest
from echo_sync.classifier import analyze,QUESTION,ACK,QUIET
from echo_sync.generator import route_need
from echo_sync.ru_alignment import match_current

@pytest.mark.parametrize('text',['Восемнадцатая статья Налогового кодекса','Статья восемнадцатая Налогового кодекса РФ','Статья 25.1 НК РФ'])
def test_bare_spoken_reference_is_a_question_without_rewriting_it(text):
 decision=analyze(text,None,[],{})
 assert decision.kind==QUESTION
 assert decision.question==text

def test_narrative_article_mention_is_not_a_new_question():
 assert analyze('Восемнадцатая статья Налогового кодекса предусматривает особый порядок',None,[]).kind==QUIET

@pytest.mark.parametrize('text',['Восемнадцатая статья Налогового кодекса','Что устанавливает восемнадцатая статья НК РФ'])
def test_law_reference_verification_does_not_depend_on_digit_asr(text):assert route_need(text)

def test_journal_article_does_not_force_legal_search():assert not route_need('Что такое статья в журнале?')

def test_ordinal_reference_ack_keeps_semantics():
 assert match_current('статья восемнадцатая НК РФ','статья 18 НК РФ')=='ack'
 assert match_current('статья девятнадцатая НК РФ','статья 18 НК РФ')!='ack'
 assert match_current('не статья восемнадцатая НК РФ','статья 18 НК РФ')!='ack'
 assert match_current('первый раз','один раз')!='ack'


def test_new_common_why_question_does_not_inherit_old_legal_lookup():
    history=[{'question':'Что устанавливает статья 218 ГК РФ?','retrieval_status':'source_backed'}]
    assert not route_need('Почему металлическая ложка кажется холоднее деревянной?',history)
    assert not route_need('Почему Земля вращается?',history)
    assert route_need('Почему?',history)
    assert route_need('А почему так?',history)
    assert route_need('Исправь, я спрашивал про США',history)
