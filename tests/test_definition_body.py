"""First cue is a definition's content, not its copied question/copula."""
import pytest
from echo_sync.textutil import definition_body

@pytest.mark.parametrize('text',[
 'Инерция — это свойство тела сохранять движение.',
 'Инерция — свойство тела сохранять движение.',
 'Инерция это свойство тела сохранять движение.',
])
def test_definition_omits_only_its_exact_question_subject_and_optional_copula(text):
 assert definition_body(text,'Что такое инерция?')=='свойство тела сохранять движение.'

def test_long_subject_cannot_be_published_while_its_definition_opener_is_still_growing():
 q='Что такое финансовая система Российской Федерации?'
 for prefix in ('Финансовая','Финансовая система','Финансовая система Российской Федерации — это'):
  assert definition_body(prefix,q)==''
 assert definition_body('Финансовая система Российской Федерации — это совокупность отношений.',q)=='совокупность отношений.'

def test_negation_numbers_and_units_in_predicate_remain_exact():
 text='Тест — это не 15 процентов, а 50 процентов.'
 assert definition_body(text,'Что такое тест?')=='не 15 процентов, а 50 процентов.'

def test_source_quotation_nondefinition_and_different_subject_are_not_rewritten():
 assert definition_body('«Инерция — это свойство».','Что такое инерция?')=='«Инерция — это свойство».'
 assert definition_body('Инерция — это свойство.','Процитируй определение инерции.')=='Инерция — это свойство.'
 assert definition_body('Масса — это величина.','Что такое инерция?')=='Масса — это величина.'

def test_content_first_answer_does_not_wait_for_the_question_term():
 assert definition_body('Свойство тела сохранять движение.','Что такое инерция?')=='Свойство тела сохранять движение.'
