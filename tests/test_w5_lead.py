"""W5-lead: the beginning of an answer from the words of the question itself (``question_lead``), and its splice with BRAIN's text."""
import csv,pathlib
import pytest
from echo_sync.question_lead import lead,splice,enabled,lead_for_call,trace_row

TABLE=pathlib.Path(__file__).parent/'fixtures'/'question_lead_table.tsv'

def _rows():
    with TABLE.open(encoding='utf-8') as f:
        return [row for row in csv.DictReader(f,delimiter='\t')]

def test_owner_example_needs_the_cloud_for_its_number():
    asked='что такое 15-я статья налогового кодекса'
    assert lead(asked) is None                                          # a number from the ear alone never goes into a lead
    got=lead(asked,cloud='Что такое 15-я статья Налогового кодекса?')
    assert got.text=='15-я статья налогового кодекса —' and got.stretch=='15-я статья налогового кодекса, налогового кодекса —'
    assert lead(asked,cloud='Что такое 16-я статья налогового кодекса?') is None   # two witnesses disagree: silence

def test_forms_are_the_questions_own():
    assert lead('когда началась первая мировая война').text=='Первая мировая война началась'
    assert lead('в каком году была основана москва').text=='Москва была основана в'
    assert lead('чем отличается налог от сбора').text=='Налог отличается от сбора'
    assert lead('почему небо голубое').text=='Небо голубое'
    assert lead('как называется столица франции').text=='Столица франции называется'
    assert lead('какова ставка ндс').text=='Ставка НДС составляет'

@pytest.mark.parametrize('asked',['ты придёшь завтра','правда ли что земля круглая','назови столицу франции','как дела',
    'маша, когда началась война','а ты уверен что это так','почему ты так думаешь','что такое','когда','сколько тебе лет',
    'когда началась война и почему','что такое случилось'])
def test_no_lead(asked):
    assert lead(asked) is None

def test_negation_needs_the_cloud():
    assert lead('почему не работает интернет') is None
    assert lead('почему не работает интернет',cloud='Почему не работает интернет?').text=='Интернет не работает'

def test_flag_is_off_by_default():
    assert not enabled({}) and not enabled(None) and enabled({'lead_cue':'on'})
    assert lead_for_call({},'что такое инфляция') is None
    assert lead_for_call({'lead_cue':'on'},'что такое инфляция').text=='Инфляция —'

def test_splice_continues_without_repeat():
    s=splice('Первая мировая война началась','Первая мировая война началась 28 июля 1914 года.',final=True)
    assert s.mode=='continue' and s.rest=='28 июля 1914 года.'
    s=splice('15-я статья налогового кодекса —','Статья 15 НК РФ — это местные налоги и сборы.',final=True)
    assert s.mode=='rebuild' and s.rest=='это местные налоги и сборы.'
    s=splice('Инфляция —','Рост цен на товары и услуги.',final=True)
    assert s.mode=='apart' and s.rest=='Рост цен на товары и услуги.'
    s=splice('Инфляция —','Не могу ответить.',final=True)
    assert s.mode=='refused'
    assert splice('Первая мировая война началась','Первая мировая',final=False).mode=='pending'

def test_trace_row_is_not_the_first_useful_help():
    row=trace_row(lead('что такое инфляция'),at=1.5)
    assert row['event']=='lead_cue' and 'first_useful' not in row and row['text']=='Инфляция —'

def test_table_has_300_rows_and_every_row_holds():
    rows=_rows()
    assert len(rows)>=300
    bad=[]
    for row in rows:
        got=lead(row['question'],cloud=row['cloud'] or None)
        text=got.text if got else '-'
        if text!=row['lead']:bad.append((row['id'],row['question'],row['lead'],text));continue
        if row['answer']:
            s=splice(text,row['answer'],final=True)
            if (s.mode,s.rest)!=(row['mode'],row['rest']):bad.append((row['id'],row['answer'],row['mode'],row['rest'],s.mode,s.rest))
    assert not bad,bad[:20]

def test_splice_decided_while_streaming_never_changes():
    """A decision made on a growing answer is the decision on the whole answer: what was cued is never contradicted."""
    bad=[]
    for row in _rows():
        if not row['answer']:continue
        whole=splice(row['lead'],row['answer'],final=True)
        for end in range(1,len(row['answer'])):
            s=splice(row['lead'],row['answer'][:end],final=False)
            if s.mode=='pending':continue
            if s.mode!=whole.mode or not whole.rest.startswith(s.rest.strip()):bad.append((row['id'],end,s,whole));break
    assert not bad,bad[:10]
