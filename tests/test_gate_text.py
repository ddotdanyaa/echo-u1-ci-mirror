"""w8-admission: «подсказывать или молчать» по тексту уха до модели (echo_sync/gate_text.py). Только код, модель не вызывается.

Набор brain_eval_n2.json (544 строки, r05-admission). Метка набора: silent -> «talk» правильно; answer или mark -> «talk» это ошибочное молчание;
silent -> «question» это ошибочная подсказка. Строки ambiguous терпят оба. Правила подбирались только по dev; holdout меряется, но не держит тест
(отчёт cloud_context/reports/w8-admission.md)."""
import json,pathlib,time

import pytest

try:
    from echo_sync.gate_text import QUESTION,TALK,UNKNOWN,decide
except ImportError:
    QUESTION=TALK=UNKNOWN=decide=None

CORPUS=pathlib.Path(__file__).resolve().parent/'fixtures'/'brain_eval_n2.json'
ROWS=json.loads(CORPUS.read_text(encoding='utf-8'))['rows']      # P03: the corpus lives in the repo (tests/fixtures); a missing file raises here, the guard never skips
DEV=[r for r in ROWS if r['split']=='dev']

def _ctx(r):return [{'text':c['text'],'kind':c['kind']} for c in r['context']]
def _gold(r):
    e=r['expect'];ok=set(e.get('acceptable') or [e['action']])
    return ok
def _errors(rows):
    silence=[];prompt=[]
    for r in rows:
        v=decide(r['text'],_ctx(r))
        ok=_gold(r)
        if v.kind==TALK and 'silent' not in ok:silence.append((r['id'],r['text'],v.reason))
        if v.kind==QUESTION and 'answer' not in ok:prompt.append((r['id'],r['text'],v.reason))
    return silence,prompt

def test_corpus_is_there():
    assert len(ROWS)==544 and len(DEV)==404

def test_dev_no_false_silence():
    """Ошибочное молчание хуже: ни одной строки с ответом или командой гейт не глушит."""
    assert _errors(DEV)[0]==[]

def test_dev_no_false_prompt():
    assert _errors(DEV)[1]==[]

def test_dev_saves_requests():
    """Гейт не пустой: на dev он снимает заметную долю запросов к модели на строках, где правильно молчать, и сам решает часть вопросов."""
    silent=[r for r in DEV if _gold(r)=={'silent'}];answer=[r for r in DEV if _gold(r)=={'answer'}]
    talk=sum(decide(r['text'],_ctx(r)).kind==TALK for r in silent)
    asked=sum(decide(r['text'],_ctx(r)).kind==QUESTION for r in answer)
    assert talk>=0.4*len(silent),(talk,len(silent))
    assert asked>=0.3*len(answer),(asked,len(answer))

def test_fast_enough():
    """Единицы мс: среднее на строку набора меньше 2 мс, худшая меньше 10 мс (облако, не ноутбук)."""
    decide('прогрев',[])
    worst=0.0;t0=time.perf_counter()
    for r in ROWS:
        a=time.perf_counter();decide(r['text'],_ctx(r));worst=max(worst,time.perf_counter()-a)
    mean=(time.perf_counter()-t0)/len(ROWS)
    assert mean<0.002 and worst<0.010,(mean,worst)

# Сцена владельца своими словами (не строки набора): друг, шум перемены, могут молчать, могут закидывать вопросами, могут подойти другие.
SCENE=[
    ('Слушай, а в каком году Гагарин полетел в космос?',[],QUESTION,'друг спросил'),
    ('Сколько будет девятнадцать умножить на три?',[{'text':'Ну что, готов?','kind':'speech'}],QUESTION,'друг спросил: счёт'),
    ('Что такое дефлятор?',[],QUESTION,'определение'),
    ('Я вчера до двух ночи сидел над курсовой, глаза слипаются.',[],TALK,'болтовня'),
    ('Короче, мы потом пошли в кино, а там все места заняты были.',[],TALK,'болтовня'),
    ('Миша, ты зарядку мою не видел?',[],TALK,'реплика другому по имени: молчим без модели (N23, E08)'),
    ('А вы во сколько завтра выезжаете?',[],TALK,'вопрос человеку о его делах'),
    ('Ты знаешь, почему небо голубое?',[],'not talk','знаешь + почему: может быть вопрос к суфлёру'),
    ('Вы можете назвать столицу Франции?',[],'not talk','экзамен во втором лице'),
    ('Миша, ты зарядку мою не видел?',[],'not question','реплика другому: не подсказка'),
    ('Вы сами-то как думаете, стоит ли туда ехать?',[],'not question','личный вопрос'),
    ('А ты как к этому относишься?',[],'not question','мнение говорящего'),
    ('Ну и кто так делает вообще?',[],'not question','риторика'),
    ('Нет, ты не прав, всё было по-другому, я там был.',[],'not question','спор между людьми'),
    ('Нет, это неверно.',[{'text':'Сколько планет в Солнечной системе?','kind':'speech'},{'text':'Девять планет.','kind':'answer'}],'not talk','спор с подсказкой: модель'),
    ('Точно?',[{'text':'Столица Австралии?','kind':'speech'},{'text':'Сидней.','kind':'answer'}],'not talk','сомнение в ответе: модель'),
    ('Мне кажется, там было восемь.',[{'text':'Сколько планет?','kind':'speech'},{'text':'Девять.','kind':'answer'}],'not talk','поправка числом'),
    ('Ну вот, скажу я вам, в общем, такая история, мы с ребятами вчера в поход ходили, промокли насквозь, а потом поспорили, а сколько вообще километров от Москвы до Питера?',[],'not talk','вопрос после вступления'),
    ('ну это самое мы с ребятами вчера поспорили в каком году основали москву',[],'not talk','вопрос после вступления, текст уха'),
    ('Сколько будет девятнадцать умножить на три?',[{'text':'Сколько будет девятнадцать умножить на три?','kind':'speech'}],QUESTION,'сам повторил вопрос (E80)'),
    ('Скажите, а что такое ВВП?',[{'text':'Привет, Саш.','kind':'speech'},{'text':'Здорово.','kind':'speech'}],QUESTION,'подошёл другой и спросил'),
    ('Стоп.',[{'text':'Что такое ВВП?','kind':'speech'},{'text':'ВВП — это стоимость всего произведённого.','kind':'answer'}],'not talk','команда: дело арбитра'),
    ('Повтори.',[],'not talk','команда'),
    ('Эээ, ммм, ну это.',[],TALK,'неразборчивое'),
    ('А что такое ВВП?',[{'text':'Лена, объясни Пете про экономику.','kind':'speech'}],'not question','вопрос после обращения к другому: решает модель'),
    # Свои трудные: вопрос без вопросительного слова и знака, счёт, длинная команда, спор с ответом без слов сомнения.
    ('Мне нужна формула площади круга.',[],'not talk','просьба утверждением'),
    ('Хочу узнать год основания Казани.',[],'not talk','просьба утверждением'),
    ('Пятнадцать процентов от двух тысяч.',[],'not talk','счёт без вопроса'),
    ('Корень из ста сорока четырёх.',[],'not talk','счёт без вопроса'),
    ('Подожди, я не про это сейчас говорю, давай вернёмся к налогам и сборам.',[],'not talk','длинная команда'),
    ('Это не Сидней, столица у них Канберра, я точно помню.',[{'text':'Столица Австралии?','kind':'speech'},{'text':'Сидней.','kind':'answer'}],'not talk','поправка ответа'),
    ('В тысяча девятьсот шестьдесят первом году полетел.',[{'text':'Когда полетел Гагарин?','kind':'speech'}],'not talk','ответил другой (E81): модель'),
    ('Сколько будет девятнадцать умножить на три',[],QUESTION,'текст уха без знака'),
    ('Так, вопрос такой: что изучает эконометрика?',[],QUESTION,'вопрос после двоеточия'),
    ('Мы вчера с Петей полдня спорили, так и не договорились: сколько костей у взрослого человека?',[],QUESTION,'вопрос после вступления'),
    ('Мы вчера с Петей полдня спорили, так и не договорились, кто у нас будет дежурить.',[],'not question','своё дело'),
    # E08: the head of a doubt is no name («Правда, ты уверена?» after an answer in play is the doubt of it, the model's, not a remark to a person)
    ('Правда, ты уверена?',[{'text':'Сколько планет?','kind':'speech'},{'text':'Девять.','kind':'answer'}],'not talk','правда в начале: сомнение, не имя'),
    ('Неужели, ты ошиблась?',[{'text':'Сколько планет?','kind':'speech'},{'text':'Девять.','kind':'answer'}],'not talk','неужели в начале: сомнение, не имя'),
    ('Разве, ты не ошиблась?',[{'text':'Сколько планет?','kind':'speech'},{'text':'Девять.','kind':'answer'}],'not talk','разве в начале: сомнение, не имя'),
]

@pytest.mark.parametrize('text,ctx,want,why',SCENE,ids=[f'{i}:{s[3]}' for i,s in enumerate(SCENE)])
def test_scene(text,ctx,want,why):
    kind=decide(text,ctx).kind
    if want.startswith('not '):assert kind!=want[4:],(why,kind)
    else:assert kind==want,(why,kind)

def test_someone_answered_first():
    """E81, N28: вопрос, на который уже ответил человек, а затем его повторили одним словом сомнения: модель, не молчание; сам ответ человека: болтовня."""
    ctx=[{'text':'В каком году основали Петербург?','kind':'speech'}]
    assert decide('В тысяча семьсот третьем, по-моему, Пётр основал.',ctx).kind!=QUESTION
    assert decide('В тысяча семьсот третьем, по-моему, Пётр основал.',ctx).kind!=TALK  # число после вопроса: может быть ответ другого, может быть проверка; модель
    assert decide('В тысяча семьсот третьем, по-моему, Пётр основал.',ctx).reason

def test_verdict_has_reason():
    v=decide('Привет, как дела у тебя, нормально всё?',[])
    assert v.kind in (TALK,QUESTION,UNKNOWN) and isinstance(v.reason,str) and v.reason

def test_there_is_no_key_for_the_gate():
    from echo_sync.settings import resolve as normalize_settings
    assert 'gate_text' not in normalize_settings({}) and 'gate_text' not in normalize_settings({'gate_text':'on'})      # a rule of the judge (gate_talk), not a switch

def test_talk_to_one_person_or_the_room_is_always_on_and_the_rest_waits_for_the_flag():
    """P03: a question to «ты» or a name, and an invitation to ask, need no flag; every other «talk» (a statement, noise, a question to «вы») is the job's to judge, the judge row keeps quiet only the first."""
    from echo_sync.gate_text import talk_without_flag
    for said,reason,free in (('Слушай, ты домашку сделал?','to_person',True),('Миша, ты зарядку не видел?','to_person',True),('Ну что, давайте задавайте любой вопрос','invitation',True),
                             ('Какой у вас стаж работы?','to_person',False),('Вчера был дождь и мы остались дома','statement',False)):
        verdict=decide(said,[])
        assert verdict.kind==TALK and verdict.reason==reason and talk_without_flag(said,verdict) is free,(said,verdict)
