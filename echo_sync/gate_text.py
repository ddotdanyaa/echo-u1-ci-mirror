"""w8-admission (N22-N28, N32, E08, E20, E72, E80, E81, R05): «подсказывать или молчать» по тексту уха до модели. Чистый модуль, без I/O.

``decide(text, context)`` -> ``Verdict(kind, reason)`` за доли миллисекунды:
  ``talk``     молчать без запроса к модели: болтовня, замечание, спор между людьми, шум. Запрос BRAIN не тратится.
  ``question`` вопрос к суфлёру о знании (год, число, определение, столица, закон, счёт), без адресата-человека: решение принято, BRAIN нужен
               только за ответом; отправлять сразу, не ждать вердикта «—».
  ``unknown``  всё остальное: BRAIN как сейчас (вопрос другому, личный вопрос, риторика, сомнение в ответе, команда, короткая тема, другой язык).
Цена ошибок разная: ошибочное молчание (``talk`` на вопросе) хуже, поэтому ``talk`` дают только реплики без единого признака вопроса, просьбы,
команды или сомнения, а после ответа «в игре» ещё строже. ``question`` не дают, если в вопросе есть второй человек (ты, вы, ваш), мы/это/он
(свой опыт, свои дела), обращение по имени в нём или в предыдущей реплике. ``context``: прежние реплики, старые первыми, словари
``{'text', 'kind'}``, kind ``speech`` (кто-то сказал) или ``answer`` (сказала подсказка). Ключа нет: строка судьи ``gate_talk`` (M1) молчит только на «talk» о человеке (``ALWAYS_TALK``: вопрос человеку, приглашение задавать вопросы); остальное «talk» (замечание, шум, вопрос к «вы») судит работа."""
from __future__ import annotations

import re
from collections import namedtuple

from .textutil import normalize

TALK='talk';QUESTION='question';UNKNOWN='unknown'
Verdict=namedtuple('Verdict','kind reason')

# P03 (U47, G7, P21): the «talk» that needs no flag, because the words are said to ONE person or to the room: a question put to a person by «ты» or by name (``to_person`` that ``addressed_to_you``), or an invitation to ask
# (``invitation``). The talk that weighs the whole of what was said (``statement``, ``noise``, ``self_answered``) and the questions to «вы» («Какой у вас гарантийный срок?»: the other side of the table may be who the owner asks
# through us) stay behind the flag: the call measure U42 (answers 16 / silences 47 / timeouts 6 against 14 / 45 / 4) says the broad gate is not yet a gain.
ALWAYS_TALK=('to_person','invitation')

def addressed_to_you(text):
    """The words name one person: «ты» in any form, or a name at the head («Лена, …»)."""
    # The judge may classify the last spoken act as addressed to another
    # person even when the act begins after an earlier sentence.
    return _vocative(text) or _vocative(_last_sentence(text)) or any(w in _YOU_ONE for w in _words(text))

def talk_without_flag(text,verdict):
    """Is this «talk» one that acts with the flag off?"""
    return verdict.kind==TALK and (verdict.reason=='invitation' or (verdict.reason=='to_person' and addressed_to_you(text)))

def _set(words):return frozenset(normalize(words).split())
_YOU_ONE=_set('ты тебя тебе тобой твой твоя твое твои твоего твоей твоих думаешь считаешь помнишь знаешь согласен согласна')
_W=re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*")
_LATIN=re.compile(r'[a-zA-Z]{2,}')
_SENT=re.compile(r'(?<=[.!?…])\s+')
_CLAUSE=re.compile(r'[,;:—–()«»"]|\s-\s')
# Шум и заминки: реплика только из них ничего не спрашивает.
_NOISE=_set('э ээ эээ ээээ эм м мм ммм мммм хм хмм а аа ааа о ох ах ой ну вот это как бы самое в общем типа короче кароч эта тово ля та да дам '
            'там ага угу ладно хорошо понятно ясно ок окей спасибо именно хе ха неразборчиво и вообще же тут')
# Слова вопроса. «как», «что», «когда», «чем» в начале клаузы или в тексте без знаков (ухо), остальные везде.
_QW=_set('сколько скольких скольким каков какова каково каковы какой какая какое какие какого какому каком какую каким какими каких '
         'почему зачем отчего откуда кого кому кем ком чей чья чье чьи ли разве неужели чему '
         'whats what who when where why how')
_SOFT_QW=_set('как что когда чем')
# Слова, что бывают и вопросом, и союзным словом: «всем, кто пришёл», «совещание, где», «фильм, который». Союзное — только после запятой за
# указательным словом или существительным; в тексте уха и в начале реплики это вопрос.
_REL=_set('кто где куда который которая которое которые которого которой которых котором которому которую')
_DEMONSTR=_set('все всем всех тем те тех тот того та ту там туда тогда тому той')
_NOUN_END=('ка','ция','ние','тие','ство','ия','ие','та','ок','ор','ер','ал','ет','ам','ах','ом','ой','ии','ей')
_SOFT_OK={'как':_set('бы всегда обычно раз будто и правило минимум максимум известно ни'),'когда':_set('я мы ты вы он она они все'),'что':_set('ли'),'чем':frozenset()}
# Просьбы к суфлёру и вспоминание вслух (всегда), команды (дело арбитра; в короткой реплике), сомнение и спор: любое снимает «talk».
_IMPER=_set('подскажи подскажите скажи скажите назови назовите напомни напомните дай дайте расскажи расскажите объясни объясните приведи приведите '
            'покажи покажите посчитай посчитайте сосчитай подсчитай сформулируй сформулируйте определи определите переведи переведите уточни уточните '
            'проверь проверьте найди найдите поищи поищите сравни сравните перечисли перечислите опиши опишите раскрой раскройте продиктуй прочитай '
            'процитируй вычисли вычислите реши решите помоги помогите')
_CMD=_set('стоп стой стойте хватит достаточно тише дальше назад подожди подождите погоди погодите помолчи помолчите замолчи замолчите останови '
          'остановись остановитесь продолжай продолжайте продолжи продолжите вернись вернитесь')
_CMD_STEMS=('повтор','следующ')
_STEMS=('вопрос','спрос','спраш','интересн','забыл','вылетел','вспомн','помни','помню','ошиб','неверн','неправ','сомнев','странн','путаешь','путаете',
        'перепута','кажется','серьезн','вряд','ерунд','чушь','бред','другой','другая','другое','другие','другую','другого','другом','иначе','верно','верн')
_DOUBT=_set('нет ой ли ладно по-моему по-твоему по-вашему уверен уверена уверены точно правда вроде разве неужели')
_DOUBT_PHRASES=('не так','не то','еще раз','может быть','не может','да ладно','не знаю','на чем','не совсем')
# «что», «как» после глагола речи или мысли и запятой вводят пересказ, не вопрос; «чем» после сравнения.
_TOLD=('говор','сказ','рассказ','читал','слыш','видел','увидел','дума','счита','знаю','знал','понял','понима','писал','обеща','решил','жаль','рад',
       'ясно','видно','понятно','главное','заметил','помню')
_COMPARE=_set('лучше хуже больше меньше раньше позже быстрее медленнее дороже дешевле выше ниже дольше скорее')
_YOU=_set('ты тебя тебе тобой твой твоя твое твои твоего твоей твоих вы вас вам вами ваш ваша ваше ваши вашего вашей ваших сам сама сами '
          'себя себе собой лично думаешь думаете считаешь считаете помнишь помните знаешь знаете согласен согласна согласны')
_OURS=_set('мы нас нам нами наш наша наше наши нашего нашей наших это этот эта эти этого этой этих он она они его ее их ему ей им него нее них '
           'кто-нибудь кто-то кто-либо мой моя мое мои мою моего моей')
_NUM=re.compile(r'\d|\b(?:ноль|один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|\w+надцать|двадцать|тридцать|сорок|пятьдесят|'
                r'шестьдесят|семьдесят|восемьдесят|девяносто|сто|двести|триста|\w+сот|тысяч\w*|миллион\w*|половин\w*|процент\w*)\b')
_STARTERS=_set('слушай слушайте итак значит ну да нет так хорошо ладно спасибо привет коллеги ребята друзья смотри смотрите кстати короче '
               'вот а и но простите извините скажите скажи подскажи подскажите знаешь знаете представим представьте понимаешь допустим '
               'кажется хм ой ох ах ага угу окей ок алло пожалуйста минуточку секунду погоди подожди стоп стой')
# Вопрос о знании: по нему решает код. Порядок слов вопроса.
_MEASURE='лет|года|год|веков|века|дней|дня|суток|часов|часа|минут|секунд|километров|метров|сантиметров|градусов|процентов|рублей|ног|лап|хромосом|цифр|'\
         'планет|бит|байт|костей|зубов|букв|звуков|материков|океанов|граммов|килограммов|литров|сторон|углов|элементов|штатов|стран|человек|раз'
_KNOW=re.compile(r'\b(?:в|во|при|до|после|с|к|на|от|из)\s+(?:каком|какой|каких|котором)\s+(?:году|веке|месяце|городе|стране|температуре|числе)\b|'
                 r'\bкакого\s+числа\b|\bсколько\s+будет\b|\bсколько\s+(?:\w+\s+){0,2}(?:'+_MEASURE+r')\b|'
                 r'\bчто\s+(?:такое|значит|означает|обозначает|показывает|изучает|говорит\s+(?:статья|закон)|гласит)\b|'
                 r'\bчему\s+(?:равн\w*|учит)\b|\bкак\s+(?:называется|называют|называлась|звали|переводится|будет\s+(?:\w+\s+)?по-\w+|расшифровывается|'
                 r'посчитать|вычислить|найти\s+площадь|формулируется)\b|'
                 r'\bкто\s+(?:написал|изобрел|открыл|такой|такая|такие|правил|автор|основал|сочинил|нарисовал|создал|первым|первый|открыл)\b|'
                 r'\bкогда\s+(?:началась|начался|началось|закончилась|закончился|закончилось|кончилась|была|был|было|пала|отменили|основан\w*|произошл\w*|'
                 r'родился|родилась|умер|умерла|изобрели|открыли|появил\w*|крестили|запустили|построили|образовал\w*|распал\w*|вышел|вышла|состоял\w*)\b|'
                 r'\b(?:какая|какой|каков|какова)\s+(?:\w+\s+)?(?:столица|формула|планета|река|гора|озеро|страна|химическая|самая|самый|единица|скорость|'
                 r'площадь|температура|масса|плотность|элемент)\b|\bстолица\s+\w+|\bчем\s+отличается\b|\bв\s+чем\s+(?:разница|отличие|суть|смысл)\b|'
                 r'\bчто\s+больше\b|\bэто\s+что$|\bкто\s+это$|\bиз\s+каких\b|\bчем\s+(?:\w+\s+){1,3}отлича\w*|\bкак\s+фамилия\b|\b(?:\w+\s+)?(?:умножить|разделить|поделить)\s+на\b|\b\w+\s+(?:плюс|минус)\s+\w+')
_ASK_VERB=re.compile(r'^(?:(?:а|ну|так|слушай|слушайте|пожалуйста)\s+)*(?:подскажи|подскажите|напомни|напомните|назови|назовите|скажи|скажите|'
                     r'объясни|объясните|расскажи|расскажите|сформулируй|сформулируйте|приведи|приведите|покажи|покажите|дай|дайте|переведи|переведите|'
                     r'посчитай|посчитайте)\b')
_KNOW_NOUN=re.compile(r'\b(?:определение|определения|формулу|формула|год|дату|число|значение|перевод|автора|фамилию|столицу|пример|закон|теорему|'
                      r'правило|ставку|площадь|скорость)\b')
# Вопрос утверждением: «мне нужна формула», «хочу узнать год»; счёт без знака: «пятнадцать процентов от двух тысяч», «корень из ста».
_WANT=re.compile(r'\b(?:узна\w*|понять|выясн\w*|уточн\w*)\b|\b(?:нужн\w*|надо|хочу|хотел\w*|хотелось)\b.*\b(?:знать|формул\w*|определени\w*|год\w*|дат\w*|столиц\w*|ответ\w*|правил\w*|закон\w*|цифр\w*|числ\w*)\b')
_SUM=re.compile(r'\bпроцент\w*\s+от\b|\bкор(?:ень|ня)\b|\bв\s+квадрате\b|\bв\s+степени\b|\bумнож\w*|\bраздел\w*\s+на\b|\bплюс\b|\bминус\b')
_FILL_AFTER=_set('там это вообще же а ну то так вот')

def _words(text):return normalize(text).split()

def _soft_blocks(text):
    """«как», «что», «когда», «чем» спрашивают в начале клаузы; в тексте уха без знаков их место не видно, тогда всегда."""
    plain=not re.search(r'[,.!?;:—–]',text);prev=[]
    for clause in _CLAUSE.split(re.sub(r'[.!?…]+',',',text)):
        ws=_words(clause)
        if not ws:continue
        for i,w in enumerate(ws):
            if w in _REL:
                if plain or i or not prev or not (w.startswith('котор') or prev[-1] in _DEMONSTR or prev[-1].endswith(_NOUN_END)):return True
                continue
            if w not in _SOFT_QW:continue
            nxt=ws[i+1] if i+1<len(ws) else ''
            if nxt in _SOFT_OK[w] or (w=='как' and i and ws[i-1]=='так') or (w=='что' and i and ws[i-1] in ('потому','то','так','ну')):continue
            if w=='что' and i==1 and ws[0]=='ну':continue
            if plain or i==0 or all(x in _STARTERS for x in ws[:i]):
                if not plain and i==0 and prev and ((w in ('что','как') and prev[-1].startswith(_TOLD)) or (w=='чем' and prev[-1] in _COMPARE)):continue
                return True
        prev=ws
    return False

_REMARK_ADJ=_set('хороший интересный сложный отличный правильный трудный непростой хитрый отдельный странный')

def _blocks(ws,joined,text=''):
    short=len(ws)<=7
    for i,w in enumerate(ws):
        if w=='правда' and i and re.search(r',\s*правда\s*,',text,re.I):continue      # «Суп удался, правда, соли не хватило»: уступка
        if w=='вопрос' and ((i and ws[i-1] in _REMARK_ADJ) or (i+1<len(ws) and ws[i+1] in _REMARK_ADJ|{'конечно'})):continue
        if w in _QW or w in _IMPER or w in _DOUBT or w.startswith(_STEMS) or (short and (w in _CMD or w.startswith(_CMD_STEMS))):return w
    for p in _DOUBT_PHRASES:
        if f' {p} ' in f' {joined} ':return p
    return None

def _answer_in_play(context):return any(c.get('kind')=='answer' for c in list(context)[-2:])

def _asked_before(context):
    """Последняя чужая реплика спрашивала: эта может быть ответом человека (E81) или уточнением, решает модель."""
    for c in reversed(list(context)):
        if c.get('kind')=='answer':return False
        t=str(c.get('text') or '')
        return t.rstrip().endswith('?') or bool(_KNOW.search(' '.join(_words(t))))
    return False

_HEAD_ADVERBS=_set('сейчас теперь вообще тогда потом сначала далее дальше ещё еще вчера сегодня завтра утром вечером днем ночью например кстати конечно допустим впрочем')      # g38: an adverb at the head is no name («Сейчас, подожди, …?» was silenced as to_person)

def _vocative(text):
    """«Лена, …», «Серёж, а …»: обращение по имени в начале; слова-зачины не имена."""
    m=re.match(r'\s*([А-ЯЁ][а-яё]+)\s*,',str(text or ''))
    if not m:return False
    w=normalize(m.group(1))     # «Проходите,», «Отлично,», «Здравствуйте,»: глагол или наречие, не имя
    return w not in _STARTERS and w not in _HEAD_ADVERBS and w not in _IMPER and w not in _CMD and not w.endswith(('ите','йте','ть','ться','ся','сь','ешь','ем','ет','ют','ут','ат','ят','о'))

def _last_sentence(text):
    parts=[p for p in _SENT.split(text.strip()) if _words(p)]
    return parts[-1] if parts else text


_ROOM_HEAD=re.compile(r'\s*(коллеги|ребята|друзья)\s*,',re.I)      # E41: said to the room: «Коллеги,» is no name for ``_vocative`` (a starter), yet it is no word to the listener either

def public_address_allowed(text):
    """Whether an untrusted ASR utterance may be disclosed to public search.

    This is a recipient-specific restriction, not the permission to search.
    A speaker/recipient ambiguity must not be overcome by extracting an
    apparently harmless question from the original speech.
    """
    text=str(text or '').strip()
    if not text:return False
    parts=[part.strip() for part in _SENT.split(text) if part.strip()]
    # A name without a comma is common in ASR. Only treat it as a recipient
    # when it precedes a question form or direct request, not an arbitrary
    # noun phrase. A later speech act has the very same protection.
    question_head=re.compile(
        r'^([А-ЯЁ][а-яё]{2,})\s+(?:а\s+)?'
        r'(?:сколько|когда|почему|зачем|где|куда|какой|какая|какие|что|'
        r'объясни|подскажи|расскажи|напомни|скажи|назови|проверь|покажи)\b',
        re.I)
    standalone_name=re.compile(r'^([А-ЯЁ][а-яё]{2,})[?!.…]$',re.I)
    for i,part in enumerate(parts):
        if _vocative(part) or _ROOM_HEAD.match(part):
            return False
        head=question_head.match(part)
        if head and _vocative(head.group(1).capitalize()+','):
            return False
        # "Лена? Сколько будет..." is a named handoff even though
        # punctuation separated the bare name from the factual question.
        bare=standalone_name.match(part)
        if bare and i+1<len(parts) and _vocative(bare.group(1).capitalize()+','):
            return False
    return True


_RECALL=re.compile(r'\b(?:вылетело|забыл|забыла|запамятовал\w*|подзабыл\w*|не\s+помню|не\s+вспомню)\b')
_THIRD=_set('он она они его ее их ему ей им него нее них')
_EXPLAIN=_set('объясни объясните расскажи расскажите подскажи подскажите скажи скажите покажи покажите напомни напомните назови назовите')
_EN_ASK=re.compile(r'^(?:what|who|when|which|where|how\s+many|how\s+much)\b',re.I)
_EN_ME=re.compile(r'\b(?:you|your|we|our|us|i|my|me)\b',re.I)

def _english(text):
    """Вопрос о знании по-английски: «What is the capital of Canada?», без you/we/I."""
    t=text.strip()
    return 'knowledge_question_en' if t.endswith('?') and _EN_ASK.match(t) and not _EN_ME.search(t) and len(_SENT.split(t))==1 else None

def _question(text,context):
    """N22: вопрос о знании к суфлёру. Вопрос — последнее предложение (после последнего двоеточия в нём: «Вопрос такой: …»)."""
    last=_last_sentence(text);plain=not re.search(r'[.!?…]',text);lw=_words(last);joined=' '.join(lw)
    if not (last.rstrip().endswith('?') or plain or _ASK_VERB.search(joined) or _RECALL.search(joined)):return None
    if _vocative(last):return None
    for c in list(context)[-2:]:   # «Лена, объясни Пете …»: следующий вопрос, скорее всего, к ней
        if c.get('kind')!='answer' and _vocative(c.get('text')) and any(w in _EXPLAIN for w in _words(c.get('text'))):return None
    seg=last.rsplit(':',1)[-1] if ':' in last and _words(last.rsplit(':',1)[-1]) else last
    sj=' '.join(w for w in _words(seg) if w not in ('там','вообще','же','вот'))
    m=_KNOW.search(sj)
    if m:
        rest=[w for w in sj[m.end():].split() if w not in _FILL_AFTER]
        if not rest and not re.search(r'сколько|умножить|разделить|поделить|плюс|минус|столица|это',m.group(0)):return None
        sw=sj.split()
        if plain:   # ухо без знаков: свой опыт ищем в вопросе и в трёх словах перед ним
            sw=sj[:m.start()].split()[-3:]+sj[m.start():].split()
        ours=_OURS-(_THIRD if _answer_in_play(context) else frozenset())-(_set('это') if 'это' in m.group(0) else frozenset())
        if any(w in _YOU for w in _words(seg)) or any(w in ours for w in sw):return None
        if any(w in ('разве','неужели','ведь') for w in lw):return None
        return 'knowledge_question'
    if _ASK_VERB.search(joined) and _KNOW_NOUN.search(joined) and not any(w in _YOU or w in _OURS for w in lw):return 'knowledge_request'
    return None

_PERSON_BLOCK=('зна','помни','помню','можешь','можете','мог','объясн','определ','доказ','обоснов','сформул','рассказ','расскаж','назов','назва',
               'перечисл','сравн','вычисл','посчита','подсчита','реш','найд','найти','ответ','скаж','сказа','подскаж','напомн','перевед','перевест',
               'слышал','курсе','поня','понима','читал','изуча','учил','проход','дума','счита','уверен','точно','правда','разве','неужели','серьезн','ошиб',
               'верн','вопрос','почему','зачем','отчего','сколько','чему','формул','закон','определени')

# f1-question (n1_02: «…Давайте сразу по делу, э-э, испытательный срок для главного бухгалтера,» | «какой максимум»): облако режет вопрос на финалы, голова вопроса не болтовня.
# Реплика, оборванная на запятой или тире; «по делу», «к делу», «перейдём к» («по существу» нет: «ничего по существу не сказал»): за ними идёт вопрос; одна клауза без глагола: тема («испытательный срок для главного бухгалтера»).
_CUT_END=re.compile(r'[,;:—–-]\s*$')
_TO_POINT=re.compile(r'\b(?:по|к)\s+делу\b|\bперейд\w*\s+к\b|\bк\s+вопросу\b')
_VERB_POS=frozenset({'VERB','INFN','PRTS','GRND','PRED'})
_MORPH=[]

def _verbless(ws):
    """Ни одного глагола, краткого причастия, деепричастия, предикатива; без анализатора ``False`` (решает прежнее правило)."""
    try:
        if not _MORPH:
            import pymorphy3      # noqa: PLC0415
            _MORPH.append(pymorphy3.MorphAnalyzer())
        return not any(_MORPH[0].parse(w)[0].tag.POS in _VERB_POS for w in ws)
    except Exception:             # noqa: BLE001
        return False

def _question_head(text,ws):
    """Голова вопроса, а не болтовня: оборвана на знаке, зовёт к делу, или вся она одна безглагольная тема из трёх-восьми слов."""
    if _CUT_END.search(text) or _TO_POINT.search(' '.join(ws)):return True
    return not re.search(r'[,.!?…;:—–]\s*\S',text) and 3<=len(ws)<=8 and _verbless(ws)

def _statement(text,context,ws):
    """Повествование без признаков вопроса, просьбы, команды, сомнения: болтовня, замечание, спор между людьми. Причина «talk» или ``None``."""
    joined=' '.join(ws)
    if _question_head(text,ws):return None
    if _KNOW_NOUN.search(joined) and len(ws)<=10 or _WANT.search(joined) or _SUM.search(joined):return None
    if ws[0] in _CMD or ws[0].startswith(_CMD_STEMS):return None
    if _blocks(ws,joined,text) or _soft_blocks(text) or _KNOW.search(joined) or len(ws)<5:return None
    if _answer_in_play(context) and (len(ws)<6 or _NUM.search(joined) or any(w in _YOU or w in ('не','нет','ни') for w in ws)):return None
    if _asked_before(context) and (len(ws)<8 or _NUM.search(joined)):return None
    return 'statement'

def _to_person(text,context,ws):
    """N23, N32, E08: вопрос человеку о нём самом или о делах (ты, вы, ваш, обращение по имени, «кто-нибудь»), без знания, просьбы,
    сомнения и глаголов «знаешь, можешь, объясни»: молчать. После ответа «в игре» не судим: «Ты уверена?» значит ответу."""
    if _answer_in_play(context):return None
    joined=' '.join(ws)
    if _KNOW.search(joined) or _KNOW_NOUN.search(joined) or _NUM.search(joined):return None
    if any(w in _IMPER or (w.startswith(_PERSON_BLOCK) and not (w=='сколько' and i and ws[i-1]=='во')) for i,w in enumerate(ws)):return None
    if not (any(w in _YOU for w in ws) or _vocative(text) or any(w.startswith(('кто-нибудь','кого-нибудь','кто-то')) for w in ws)):return None
    return 'to_person'

def _self_answered(text,context,ws):
    """Риторика, на которую говорящий сам ответил: «И что мы видим на графике? Мы видим рост выручки.» Вопрос без знания, хвост — повествование."""
    parts=[p for p in _SENT.split(text.strip()) if _words(p)]
    if len(parts)<2 or parts[-1].rstrip().endswith('?'):return None
    asked=' '.join(_words(' '.join(p for p in parts if '?' in p)))
    if _KNOW.search(asked) or _KNOW_NOUN.search(asked) or any(w in _IMPER for w in asked.split()):return None
    if any(w in _set('сколько когда где куда откуда какой какая какое какие какого каком какую каких') for w in asked.split()):return None
    tail=' '.join(p for p in parts if '?' not in p);tw=_words(tail)
    return 'self_answered' if _statement(tail,context,tw) else None

# U47 («Ну что, давайте задавайте любой вопрос»): приглашение аудитории задавать вопросы — не вопрос суфлёру. Класс по строению: глагол «задавать/спрашивать»
# в повелительном наклонении во множественном числе (обращение к слушателям) или «есть вопросы», «у кого вопрос», «кто хочет спросить»; без слов о знании. Знание в тексте: решает ``_question`` раньше.
_INVITE=re.compile(r'\b(?:задава[йю]те|задайте|спрашивайте|спросите)\b|\b(?:у\s+кого\s+(?:есть\s+)?вопрос\w*|есть\s+(?:ли\s+)?вопрос\w*|кто\s+(?:хочет|готов)\s+(?:задать|спросить)|кто\s+что\s+хочет\s+спросить)\b')
INVITE_MAX_WORDS=14      # длиннее — это рассказ, в котором приглашение лишь часть

def _invitation(text,ws):
    """U47: приглашение задавать вопросы. Причина «invitation» или ``None``."""
    return 'invitation' if len(ws)<=INVITE_MAX_WORDS and not _NUM.search(' '.join(ws)) and _INVITE.search(' '.join(ws)) else None

def decide(text,context=()):
    """Вердикт по тексту реплики и прежним репликам; не бросает, на пустом ``unknown``."""
    text=str(text or '').strip();context=[c for c in (context or ()) if isinstance(c,dict)]
    ws=_words(text)
    if not ws:return Verdict(UNKNOWN,'empty')
    # E41: a factual question explicitly addressed to a named third person
    # in ONE sentence is not a prompt. Do not silence a later new question
    # after a dialogue transition (see corpus b2_LP_014 / b2_LP_015).
    if _vocative(text) and text.rstrip().endswith('?') and len(_SENT.split(text)) == 1:
        return Verdict(TALK,'to_person')
    # E41: the final sentence can itself explicitly address a third person.
    # Limit the decision to that sentence: an earlier vocative must not
    # automatically suppress a later, potentially assistant-directed question.
    last = _last_sentence(text)
    if last != text and _vocative(last) and last.rstrip().endswith('?'):
        return Verdict(TALK,'to_person')
    if _LATIN.search(text):
        reason=_english(text)
        return Verdict(QUESTION,reason) if reason else Verdict(UNKNOWN,'other_language')
    reason=_question(text,context)
    if reason:return Verdict(QUESTION,reason)
    reason=_invitation(text,ws)
    if reason:return Verdict(TALK,reason)
    if '?' in text:
        reason=_to_person(text,context,ws) or _self_answered(text,context,ws)
        return Verdict(TALK,reason) if reason else Verdict(UNKNOWN,'asks')
    parts=[p for w in ws for p in w.split('-')]
    if all(p in _NOISE for p in parts) and not _answer_in_play(context):return Verdict(TALK,'noise')
    reason=_statement(text,context,ws)
    return Verdict(TALK,reason) if reason else Verdict(UNKNOWN,'no_evidence')
