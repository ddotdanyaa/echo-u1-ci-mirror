"""Conservative first-cue scaffold filter, not a factual/semantic guarantee.

Uses the existing portioner and pymorphy3 token analysis. Never changes
numbers, negations, quotations or a committed prefix. No clock-based guess
that another 300ms makes a statement useful.

``first_cue`` is what the phone speaks first (WAVE 2 L2): a short unit of 2-4 words (5 to keep a term, a number with its
unit or a negation whole), released as soon as the word after it is known. It prefers a cue that says more than the
question, but never waits for one beyond the word budget: a wait no further word can end is silence for the listener.
"""
import re
from .classifier import IMPERATIVE
from .portioner import CUE_MAX_WORDS, MEANING_EARLY_WORDS, cue_cuts, first_clause, first_window, meaning_cuts, portion_size, portions
from .settings import CALL_SETTINGS, resolve
from .textutil import LATIN_FUNCTION_WORDS,PREPOSITIONS,STOPWORDS,WORDS,is_label,is_phone_phrase,norm_words,normalize,stems,strip_process_prefix
from .ru_alignment import _canonical,_lemma
from .ru_numbers import CENTURY_WORDS,MONTH_WORDS,YEAR_WORDS

# «ГК РФ» is «Гражданский кодекс Российской Федерации»: a cue that spells the code out and a question that abbreviates it
# (or the other way round) say the same thing.
_REFERENCE_ALIASES={'гк':('гражданский','кодекс'),'нк':('налоговый','кодекс'),
    'тк':('трудовой','кодекс'),'ук':('уголовный','кодекс'),'ск':('семейный','кодекс'),
    'рф':('российский','федерация')}

def _reference_key(text):
    # R21-10: «ГК РФ» and «Гражданский кодекс» are one reference: the country after the code is no part of its name
    return tuple(part for atom in _canonical(text,()) for part in _REFERENCE_ALIASES.get(atom,(atom,)) if part not in ('российский','федерация'))

# W1F-A: what an article «устанавливает» the answer may say it «закрепляет», «регулирует», «гласит» … - one class of reference verbs.
_REFERENCE_VERBS=(r'(?:устанавливает|закрепляет|регулирует|определяет|предусматривает|гласит|говорит|содержит|описывает|гарантирует|запрещает|разрешает|'
                  r'обязывает|касается|раскрывает|фиксирует)')
def compact_opening(text,question,settings=None):
    if text.startswith(('«','“','"',"'")):return text
    if re.match(r'\s*(?:а\s+)?почему\b',question,re.I):
        text=re.sub(r'^потому\s+что\s+','',text,flags=re.I)
    if re.match(r'\s*(?:а\s+)?как\s+называ',question,re.I):
        # Hold the scaffolding until its following word exists; exact join
        # across acoustic segments happens before this transformation.
        if re.fullmatch(r'(?:это\s+)?называется\s*',text,re.I):return ''
        text=re.sub(r'^(?:это\s+)?называется\s+','',text,flags=re.I)
    # R21-10: «Что устанавливает / говорит / гарантирует статья N …?», «О чём статья N?», «Что такое статья N?», «Что говорится в статье N?»
    query=re.fullmatch(r'\s*(?:что\s+'+_REFERENCE_VERBS+r'|о\s+чём|о\s+чем|что\s+такое|что\s+говорится\s+в|что\s+написано\s+в|что\s+в)\s+((?:статья|статье)\b.+?)[?!.\s]*',question,re.I)
    if not query:query=re.search(r'(?<!\w)((?:статья|статью|статье|статьи)\s+\d+(?:\s+[^\W\d]+){1,4})[?!.\s]*$',question,re.I)      # c25-b case 6: «Статья 58 НК?», «Расскажи про статью 58 НК»
    if query:
        try:body=_reference_body(text,_reference_key(re.sub(r'(?i)^стать(?:ю|е|и)\b','статья',query[1])))
        except ImportError:body=None
        if body is not None:return body.lstrip()
        if re.match(r'\s*статья\b',text,re.I):return text.lstrip()      # g1-ladder L0: «Статья 80 — налоговая декларация.»: the article's title is the answer, «налоговая» no restatement of «НК»
    return elide_restated_head(text.lstrip(),question,settings)

def _reference_body(text,key):
    """The answer after its echo of the question's reference («Статья 421 ГК РФ закрепляет …» -> «…»): any reference verb, the same
    article, number and code only (a negated or another article is no echo). '' while that echo is still arriving: its first words are
    the question's own and the verb after them decides, so they are never published as a restatement and then contradicted (a long
    reference, word by word, was cued «Статья 421» and then corrected «Поправка: принцип …»). None: not an echo of the reference."""
    echoed=re.match(r'^(статья\b.{1,120}?)\s+'+_REFERENCE_VERBS+r'(?:[,\s:]+|$)',text,re.I)
    if echoed and _reference_key(echoed[1])==key:return re.sub(r'^что\s+','',text[echoed.end():],flags=re.I)
    dashed=re.match(r'^(статья\b.{1,120}?)\s*(?:[—–:]|\s-)\s+(?=\w)',text,re.I)      # c25-b case 6: «Статья 58 Налогового кодекса — порядок уплаты …»: the content first
    if dashed and _reference_key(dashed[1])==key:return text[dashed.end():]
    words=list(WORDS.finditer(text))
    head=text[:words[-1].start()] if words and text[-1:].isalnum() else text     # its last word may still be growing
    if re.match(r'\s*статья\b',head,re.I):
        so_far=_reference_key(head)
        if so_far and so_far==key[:len(so_far)]:return ''
    return None

def elide_restated_head(text,question,settings=None):
    """W1F-A (b), zero delay: an answer whose first clause only restates the question up to its first new unit («Первая мировая
    началась | в 1914 году.» to «В каком году началась Первая мировая война?») starts at that unit, its preposition or «не» kept -
    instead of the restatement that first_cue would otherwise speak. Only when that unit is already complete in the same clause, and
    only on a clause no longer than the first-cue window: the restatement could not have been spoken before the clause ended, and the
    decision, made on the clause alone, never changes afterwards (a published cue is never contradicted). Otherwise ``text`` as it is:
    the restatement stays the never-silent fallback."""
    if not text or text.startswith(('«','“','"',"'")):return text
    settings=CALL_SETTINGS if settings is None else settings      # the call's own profile (settings.CALL_SETTINGS): the one copy
    clause,needed=first_clause(text,settings)
    if clause is None or len(WORDS.findall(clause))>needed:return text
    seen,cuts,_,_=cue_cuts(clause,settings,final=False)
    shaped=[cut for cut in cuts if not cut.fragment]
    if not shaped or any(not _adds_nothing(seen[:cut.end],question,settings) for cut in shaped):return text
    words=list(WORDS.finditer(clause))
    new=next((k for k,word in enumerate(words) if not _adds_nothing(clause[:word.end()],question,settings)),None)
    if new is None:return text
    start=new
    while start and normalize(words[start-1].group()) in PREPOSITIONS|{'не','ни'}:start-=1
    if start<2:return text                                  # a restated head of two words at least
    unit,cuts,_,_=cue_cuts(clause[words[start].start():],settings,final=False)
    if not any(cut.ready and not (cut.fragment or cut.dangling or cut.heavy) and not _adds_nothing(unit[:cut.end],question,settings)
               for cut in cuts):
        return text                                         # the new unit is not complete yet: the restatement stays
    return text[words[start].start():]

# «Нет.», «Да.», «Не рыба.» answer a yes/no question although every other word is the question's own.
_ANSWER_WORDS=frozenset({'да','нет','не','ни'})
# «Чай или кофе?» is answered «Кофе.», «Правда ли, что Земля круглая?» is answered «Правда, Земля круглая.»: the answer is
# made of the question's own words. Only a cue that also repeats the interrogative particle is the question read back.
_ASKING=frozenset({'ли','или'})
ROOT_LETTERS=5      # H5 item 5: two words that begin alike this far are one word of a question: «максимальный», «максимум»

def _adds_nothing(cue,question,settings,roots=False):
    """True for a cue that only repeats the question back, or is nothing but function words and fillers. ``roots`` (H5 item 5: a first portion
    that is the whole answer, or a patient one): the root as well, ``ROOT_LETTERS`` letters: «Максимальный испытательный срок» to «… какой максимум» is the
    question read back in other forms (n1_02 step 1), a stem cannot tell. A choice is answered in its own words.

    Compared by Russian stem («инерции» echoes «инерция»). A number, a negation and да/нет are content:
    they are what a «сколько»/«когда»/«правда ли» answer is about. For a choice («…или…?») or yes/no («…ли…?») question
    the words of the question are the answer too (a short «Нужно.» is not a function word there), so only a cue that
    repeats «ли»/«или» as well is the question read back. Lexical only, so it needs no analyzer.
    """
    fillers=frozenset(word for phrase in resolve(settings)['fillers'] for word in phrase.split())
    choice=bool(_ASKING.intersection(norm_words(question)))
    ignored=(fillers if choice else STOPWORDS|LATIN_FUNCTION_WORDS|fillers)-_ANSWER_WORDS
    content=lambda value:stems(part for word in norm_words(value) for part in _REFERENCE_ALIASES.get(word,(word,))
                               if part not in ignored)
    asked=set(content(question))
    heard=content(cue)
    if all(stem in asked for stem in heard):
        if not heard:return True                                # nothing but function words and fillers
        if not choice or _ASKING.intersection(norm_words(cue)):return True
    if not roots or choice:return False                         # a word the question does not have: that is the answer
    root_of={word[:ROOT_LETTERS] for word in norm_words(question)}
    return all(word[:ROOT_LETTERS] in root_of for word in norm_words(cue) if word not in ignored)

def _first_new(text,question,settings):
    """H5 item 5: the whole answer is known and no place of the window says anything new: the portions of the answer, joined up to the first that does. None: nothing in it is new."""
    end=0
    try:
        for part in portions(text,settings,spoken=True):
            end=text.index(part,end)+len(part)
            if not _adds_nothing(text[:end],question,settings,roots=True):return text[:end]
    except Exception:
        return None
    return None

# Interrogative words (and the stems of their inflected forms). One that opens a clause after a comma introduces a subordinate clause
# («Вы понимаете, что это важно?», «Ты знаешь, где вокзал?») and asks nothing itself.
_WH=frozenset({'что','чего','чему','чем','чём','кто','кого','кому','кем','ком','когда','где','куда','откуда','почему','зачем',
               'отчего','как'})
_WH_STEMS=('какой','какая','какое','какие','каков','какого','какому','каким','каком','какую','каких','какими','котор','скольк',
           'чей','чья','чьё','чье','чьи','чьег','чьем','чьим','чьих')

def _yes_no(question):
    """A yes/no question asked by intonation only (no «ли», no interrogative word of its own): «Вы понимаете, что это важно?»,
    «Сообщите?». Its own words are the reply («Понимаю.», «Сообщу.»)."""
    return '?' in str(question or '') and not _asks_a_word(question)

def _asks_a_word(question):
    """Has the question an interrogative word of its own, not one that opens a subordinate clause?"""
    for n,clause in enumerate(re.split(r'[,;:—–]',str(question or '').casefold())):
        for k,word in enumerate(re.findall(r'\w+',clause)):
            if n and not k:continue                       # it opens a subordinate clause
            if word in _WH or word.startswith(_WH_STEMS):return True
    return False

def asks_for_more(question):
    """H6 item 1: does the question ask for what a bare yes or no does not give: an interrogative word of its own, or an order («назови»)?"""
    return _asks_a_word(question) or bool(IMPERATIVE.search(str(question or '')))

# C7-A: what a «какой …» question asks for when it asks for a number (stems): «в каком году», «какого числа», «какой процент», «какая
# ставка», «какая сумма», «с какого возраста», «в каком веке». «Какой налог» or «какая столица» ask for a name.
_NUMBER_NOUNS=('год','числ','дат','процент','ставк','сумм','размер','возраст','век','цен','стоимост','курс','количеств','температур',
               'скорост','высот','длин','глубин','площад','масс','срок','пошлин','штраф','зарплат','пенси','тираж','численност','час',
               # R21-04: «какой рост / вес / объём …»: a word that only BEGINS like «рост» or «вес» («ростбиф», «весна») is none of them
               'ширин','толщин','плотност','мощност','частот','давлен','напряжен','расстоян','длительност','вместимост','ёмкост','емкост','пробег','расход')
_NUMBER_NOUNS_EXACT=frozenset('рост роста росте вес веса весе объём объем объёма объема диаметр диаметра диаметре доход дохода оклад оклада тариф тарифа лимит лимита'.split())
_DATE_NOUNS=('год','числ','дат','век','месяц','день','дня')

def asks_for_number(question):
    """C7-A: does ``question`` ask for a number or a date? Read on the question text: the FIRST interrogative of one of its sentences is
    «когда», «сколько» (any form), «как долго», or a «какой» / «который» form with a quantity noun right after it («в каком году», «какой
    процент», «какая ставка НДС»). An interrogative after another one opens a subordinate clause and asks nothing itself («Что делать,
    когда болит голова?»); a preamble sentence before the question («Что же я хотел спросить? Когда …») does not hide it."""
    text=str(question or '').casefold().replace('ё','е')
    for sentence in re.split(r'[.!?…]+',text):
        found=re.findall(r'\w+',sentence)
        for k,word in enumerate(found):
            if not (word in _WH or word.startswith(_WH_STEMS)):continue
            if word=='когда' or word.startswith('скольк'):return True
            if word=='как':
                if found[k+1:k+2]==['долго']:return True
            elif word.startswith(('как','котор')) and any(w.startswith(_NUMBER_NOUNS) or w in _NUMBER_NOUNS_EXACT for w in found[k+1:k+3]):
                return True
            break                                          # the first interrogative of the sentence decides it
    return _asks_in_english(text)

# R21-09: the same for an English question (a call is not only in Russian): «When …», «How many / much / long …», «What year / date …».
_ENGLISH_NUMBER=re.compile(r'^\s*(?:and\s+|so\s+)?(?:when\b|how\s+(?:many|much|long|old|far|often|big|tall|high|fast)\b|which\s+year\b|'
                           r'what\s+(?:year|date|time|day|century|percentage|price|temperature|speed|size|age)\b|'
                           r'what\s+(?:is|was|are|were)\s+the\s+(?:speed|price|cost|temperature|rate|size|height|length|population|distance|age|number|'
                           r'percentage|amount|date|year|weight|width|depth|area|volume)\b)',re.I)

def _asks_in_english(text):
    return not re.search(r'[а-яё]',text) and any(_ENGLISH_NUMBER.match(sentence) for sentence in re.split(r'[.!?…]+',text))

def asks_for_date(question):
    """R21-04: does ``question`` ask for a DATE (when, which year / century / day / date, from which year), not for a quantity? Read as ``asks_for_number``
    reads it: the first interrogative of a sentence decides. A date is any number of the answer that is not in the question; a quantity is one that is not a
    date or the number of an article."""
    text=str(question or '').casefold().replace('ё','е')
    for sentence in re.split(r'[.!?…]+',text):
        found=re.findall(r'\w+',sentence)
        for k,word in enumerate(found):
            if not (word in _WH or word.startswith(_WH_STEMS)):continue
            if word=='когда':return True
            if word.startswith(('как','котор')):return any(w.startswith(_DATE_NOUNS) for w in found[k+1:k+3])
            break
    return bool(re.match(r'\s*(?:and\s+|so\s+)?(?:when\b|which\s+year\b|what\s+(?:year|date|day|century)\b)',text,re.I))

# R21-10: «Статья 20 Гражданского кодекса», «Статья 115» - the header of a reference is what the question named, the content is what the article says.
_REFERENCE_HEADER=re.compile(r'(?i:статья|ст\.|пункт|п\.|часть|глава|раздел)\s+\d[\d.\-]*(?:\s+(?:[А-ЯЁA-Z]\w*|(?i:кодекса|закона|федерации|российской)))*(?:\s+(?i:'+_REFERENCE_VERBS+r'))?[,.:]?')

def _reference_header(candidate):
    return bool(_REFERENCE_HEADER.fullmatch(str(candidate).strip()))

_DATE_WORDS=frozenset(MONTH_WORDS|CENTURY_WORDS|YEAR_WORDS|{'года'})

def _numbers(text,dates=True):
    """The numbers ``text`` states, as alignment atoms: digits, spoken cardinals, spoken ordinals from 10 on or before a date word. A
    small spoken ordinal is mostly a name («Пётр Первый», «Вторая мировая»), not the number asked for. ``dates=False`` (R21-04): a number that
    dates something - an ordinal or a number before a month or a year word («с 1 января», «с 2019 года»), a year after a month - or labels a
    reference («статья 115», «пункт 3», «закон номер 2300») is not a quantity."""
    try:
        atoms=_canonical(text,(),True)
    except ImportError:
        return set(re.findall(r'\d+',text))
    out=set()
    for k,atom in enumerate(atoms):
        if not atom.atom.startswith(('#','!spoken:')):continue
        if not dates:
            before=atoms[k-1].surface.casefold() if k else '';after=atoms[k+1].surface.casefold() if k+1<len(atoms) else ''
            if atom.atom.startswith('#ord:') or (after in _DATE_WORDS and not (after=='года' and _below(atom.atom,1000))) or before in MONTH_WORDS or is_label(normalize(before)):continue      # c22-reviewfix: «2 года» is a count, «года» dates from 1000 (ru_numbers.YEAR_WORDS)
        if atom.atom.startswith('#ord:') and not any(ch.isdigit() for ch in atom.surface):
            following=atoms[k+1].surface if k+1<len(atoms) else ''
            if int(atom.atom[5:])<10 and following not in _DATE_WORDS:continue
        out.add(atom.atom)
    return out

def _below(atom,limit):
    """The cardinal ``atom`` ('#2') is a number under ``limit``; a spoken or odd atom is not known to be."""
    return bool(re.fullmatch(r'#\d+',atom)) and int(atom[1:])<limit

# c22-reviewfix: the words that make a number a date or a time when they stand after it («в 1799 году», «в 10 часов», «через 3 дня»)
_WHEN_WORDS=frozenset(_DATE_WORDS|{'г','гг','годы','годах','годов','час','часа','часов','минут','минуты','утра','вечера','ночи','дня','дней','день',
                                   'недели','недель','неделю','месяца','месяцев','месяц','лет'})

def _dated(text):
    """c22-reviewfix: the numbers of ``text`` that say WHEN: an ordinal or a year of digits, a number before a date or time word or after a month
    («в 1799 году», «в октябре 1853», «через 3 дня»). «Автор 14 поэм», «Армия в 600 тысяч человек» say no when."""
    try:
        atoms=_canonical(text,(),True)
    except ImportError:
        return set(re.findall(r'\b1\d{3}\b|\b20\d{2}\b',text))
    out=set()
    for k,atom in enumerate(atoms):
        if not atom.atom.startswith(('#','!spoken:')):continue
        before=atoms[k-1].surface.casefold() if k else '';after=atoms[k+1].surface.casefold().rstrip('.') if k+1<len(atoms) else ''
        year=bool(re.fullmatch(r'#\d+',atom.atom)) and 1000<=int(atom.atom[1:])<=2100 and atom.surface.isdigit()
        if atom.atom.startswith('#ord:') or year or after in _WHEN_WORDS or before in MONTH_WORDS:out.add(atom.atom)
    return out

def says_a_number(cue,question):
    """C7-A: ``cue`` states a number the question does not have."""
    return bool(_numbers(cue)-_numbers(question))

def says_the_number_asked(cue,question):
    """R21-04: ``cue`` states a number of the KIND the question asks for. A question for a date takes any number it does not have; a question for a quantity
    («сколько», «какой размер / ставка / рост») takes a quantity only: «Размер МРОТ с 1 января» has a number and not the amount, «Статья 115 Трудового
    кодекса» has one and not the days. (``says_a_number`` stays what it was: it is the engine's guard against a number made up.)"""
    return bool(_numbers(cue,asks_for_date(question))-_numbers(question,True))

def _complete_reply(text,question,settings,*,final,last):
    """Coordinator's addition to F1 round 2: a reply that is over (``final``, or the producer's turn is over with its sentence closed)
    and adds nothing against a yes/no question asked by intonation is the answer in the question's own words («Вы понимаете…?» ->
    «Понимаю.», «Сообщите?» -> «Сообщу.»): it is cued. The «new information» gate only decides how far a first portion is extended
    while more text is coming. Still no reply: fillers alone, the question read back with «ли» / «или», the term of a wh-question."""
    text=str(text or '').strip()
    if not text or not (final or (last and text[-1] in '.!?…')) or not _yes_no(question):return False
    words=norm_words(text)
    if _ASKING.intersection(words):return False
    fillers=frozenset(word for phrase in resolve(settings)['fillers'] for word in phrase.split())
    return any(word not in fillers for word in words)

def _stall_pending(text,question=''):
    """True while ``text`` is only the beginning of a stalling sentence («Понял, сейчас быстро…»): its verb has not come
    yet, so it is neither known to be a stall nor an answer. The very regex that strips a whole stall decides."""
    probe='подумаю' if 'провер' in str(question).casefold() else 'проверю'     # the probe verb must not be a word of the question (F3 round 1)
    return not strip_process_prefix(text.rstrip()+' '+probe+'.',question)

def first_cue(text,question,settings,*,final,last,max_words=CUE_MAX_WORDS,patient=False):
    """The first thing the listener is asked to repeat: a short, speakable unit, released as soon as it exists.

    2-4 words (a 5th only to keep a term, a number with its unit or «не» + word together), about five syllables, never
    torn from the unit it belongs to (``portioner.cue_cuts`` finds the places), available as soon as the word after it is
    known - no waiting for punctuation, no waiting for a second portion. The earliest well-shaped cut that says more than
    the question wins; otherwise, once no further word can improve on it, the cheapest one that does; an opening that only
    restates the question for longer than a cue may be (nothing short says more) is cued as that restatement, because
    waiting for the first new word is waiting in silence. Never a phone phrase, never a stall.

    W1F-A: the cue does not end on a word that needs its head when the head has already arrived (it takes the head along on the
    same delta), and it is lengthened to the first clause or sentence punctuation that has already arrived (4 words, 12 syllables
    at most). Neither ever waits for a word that has not arrived: then the cue is the one of before, at the moment of before.

    ``final``: the text is the end of the answer. ``last``: the producer's turn is over, but a segment can stop in the middle
    of a word and the next one go on, so unless ``final`` the last word is NOT known to be whole and is kept out of the cue
    (a word cut in half is never spoken); waiting is silence, so no further word is waited for. ``patient``: the text channel's: its next
    word is a moment away (190 chars/s), so the first portion may wait for what is new (H5 item 5).
    """
    text=str(text or '').lstrip()
    if not text:return None
    if resolve(settings)['portion_mode']=='meaning':
        cue=_first_meaning(text,question,settings,final=final,last=last,patient=patient)
        return _close_open_end(text,cue,question,settings,final=final,last=last)
    # a complete reply's last word is whole: its sentence mark came after it and nothing follows (_complete_reply)
    answered=_complete_reply(text,question,settings,final=final,last=last);final=final or answered
    text,cuts,complete,closed=cue_cuts(text,settings,final=final,max_words=max_words)
    if not final and _stall_pending(text,question):return None      # the text WITHOUT a word that may still be growing
    if is_phone_phrase(text):return None                   # «Закончить разговор.» is not to be spoken, nor is its first word
    echoes,costly,dangling=[],[],[]
    # A lone short word is a last resort, spoken only at the true end of a text that says something: a word of a sentence that
    # is nothing but the question read back («Чай» out of «Чай или кофе.») is not an answer.
    fragments=(final and not _adds_nothing(text.strip(),question,settings)) or answered
    # W1F-A: a cut that ends on a word that needs its head («У Меркурия почти») is never the cue while the text holds a better one.
    # Where it WOULD have been the cue, a cut that takes the head along and has just become possible («…плотной атмосферы ») stands
    # in for it at once (a 'head' closure), so the head costs no wait of its own.
    replacing=None                                         # the dangling cue that would have been spoken here before W1F-A
    for k,cut in enumerate(cuts):
        candidate=text[:cut.end].strip()
        if replacing is not None and not cut.dangling:
            # The place right after the head stands in for the dangling cue now, or that cue is spoken as it was: never a wait.
            fine=(cut.ready and not cut.fragment and not cut.heavy and not is_phone_phrase(candidate)
                  and strip_process_prefix(candidate,question) and not _adds_nothing(candidate,question,settings))
            return _closed(text,cuts,k,max_words) if fine else replacing
        if (cut.fragment and not fragments) or is_phone_phrase(candidate) or not strip_process_prefix(candidate,question):continue
        if cut.dangling:
            says=not _adds_nothing(candidate,question,settings)
            dangling.append((not says,cut,candidate))
            if replacing is None and says and cut.ready:replacing=candidate
            continue
        # A 'punct' closure is a cue of its own only from two words on («около 70 тыс. человек,»): one word alone waits for the word
        # after it, as before, so that a last word is not left alone at the end of its sentence («Электрокардиограмма,» | «ЭКГ.»).
        # A 'head' closure only ever stands in for a dangling cue (above).
        if cut.closure=='head' or (cut.closure=='punct' and cut.words<2):continue
        if _adds_nothing(candidate,question,settings):
            echoes.append((cut,candidate));continue
        if cut.ready:return _closed(text,cuts,k,max_words)
        costly.append((cut,candidate))
    if replacing is not None:return replacing              # the head is not there yet: the cue of before, at the moment of before
    if not (complete or closed or last or final):return None
    cheapest=lambda rows:min(rows,key=lambda row:(row[0].cost,-row[0].words))[1]
    if costly:return _closed(text,cuts,cuts.index(min(costly,key=lambda row:(row[0].cost,-row[0].words))[0]),max_words)
    # a restatement is cued in its own words: the 5-word case that only exists to keep a unit whole is for a cue with content
    echoes=[row for row in echoes if row[0].words<=max_words] or echoes
    # Only the question read back fits: fine while more could follow (the answer is not known to be an echo), not when the
    # text is over and every word of it is the question's own. A provider-final segment that may still go on («…в 1914 » + «году.»)
    # waits for the end of the answer (the grace flush, final) while its cue window is open: its next words may let the restated
    # head be elided (elide_restated_head), and a restatement spoken now would then be contradicted (W1F-A).
    over=(final or last) and _adds_nothing(text.strip(),question,settings) and not answered
    if echoes and (complete or final) and not over:
        return cheapest(echoes)
    # Never silent: when no other place fits the word budget, a cut that leaves its head behind is still spoken, as before W1F-A.
    if dangling and (complete or final) and not over:
        return min(dangling,key=lambda row:(row[0],row[1].cost,-row[1].words))[2]
    return None


# R21-05: a question with a condition («Можно ли вернуть товар, если прошло десять дней?», «Если температура ниже нуля, вода замёрзнет?»). Its answer may
# turn on that condition, so the bare verdict is no gist: the first portion takes in the clause that qualifies it.
_CONDITION=re.compile(r'(?<!\w)(?:если|в\s+случае|при\s+условии|при\s+наличии|при\s+отсутствии|в\s+том\s+случае|допустим|предположим|if|in\s+case)(?!\w)',re.I)
_VERDICTS=frozenset('да нет можно нельзя конечно верно неверно правильно неправильно именно точно обязательно разумеется безусловно естественно yes no sure correct'.split())

def asks_with_condition(question):
    """R21-05: does ``question`` state a condition of its own («если», «в случае», «при условии» …)?"""
    return bool(_CONDITION.search(str(question or '')))

def bare_verdict(cue):
    """R21-05: ``cue`` is nothing but a verdict («Да.», «Нет,», «Конечно, да.», «Можно.»): up to three words, all of them answer words."""
    found=norm_words(cue)
    return 1<=len(found)<=3 and all(word in _VERDICTS for word in found)

def _qualifier(rest,settings,*,final,last):
    """R21-05: the part of ``rest`` (what follows a bare verdict) that qualifies it, or None while it has not arrived. The whole next sentence when it is closed and
    fits the number window (12 words: «Нет. Без чека товар можно вернуть только в течение семи дней.»); a clause with its own predicate as soon as its comma has
    arrived (the verdict then goes on as «Да. Консульство выдаст свидетельство на возвращение,»); the cheapest place of the window once nothing can be added."""
    text,cuts,complete=meaning_cuts(rest,settings,final=final,number=True)
    rows=[(cut,text[:cut.end].strip()) for cut in cuts if not is_phone_phrase(text[:cut.end]) and strip_process_prefix(text[:cut.end])]
    whole=[row for row in rows if row[0].sentence]
    if whole:return whole[0][1]
    clauses=[row for row in rows if row[1][-1:] in ',;:' and row[0].verb and row[0].words>=3 and not row[0].torn]
    if clauses:return clauses[0][1]
    if not (complete or last or final):return None
    loose=[row for row in rows if not row[0].torn and row[0].verb] or [row for row in rows if not row[0].torn] or rows
    return min(loose,key=lambda row:(row[0].cost,-row[0].words))[1] if loose else None

def _first_meaning(text,question,settings,*,final,last,patient=False):
    """R21-05: the first meaning portion (``_first_meaning_core``); but never a bare verdict for a question that states a condition. «Да.» may go on as
    «Да, но только при …» or «Да, если …»: the portion takes in what qualifies it (``_qualifier``: the next clause or sentence), so the listener never repeats a
    verdict that the next words take back. It waits for that while the answer is still arriving; an answer that is nothing but the verdict is spoken as soon as
    it is over."""
    cue=_first_meaning_core(text,question,settings,final=final,last=last,patient=patient)
    if cue:cue=_finish_thought(text,cue,question,settings,final=final,last=last)
    if not cue or not bare_verdict(cue) or not asks_with_condition(question):return cue
    rest=text[len(cue):]
    if not rest.strip():return cue if final or last else None
    more=_qualifier(rest.lstrip(),settings,final=final,last=last)
    if not more:return cue if final or last else None
    return text[:len(text)-len(rest.lstrip())+len(more)]

FINISH_WORDS = 4      # G15: a first portion that stops this many words (prepositions not counted) short of its sentence's end takes them along

_CLOSES_A_THOUGHT=',;:.!?…'      # c20-first-cue: the marks that end a thought at the end of a first portion (a dash does not: it stands inside one)

def _portion_cap(question,settings,text=None):
    """The word cap of a first portion: ``portioner.first_window(number=True)`` (12) for a question that asks for a number or a date,
    else the profile's documented ``max_words`` (PRESETS['meaning']: 9). c22-reviewfix: the wider cap is there to reach the number; a
    ``text`` given that holds no number asked has the cap of before (review 4a91807: a 10-11 word cue with no number in it)."""
    if not asks_for_number(question):return resolve(settings)['max_words']
    if text is not None and not says_the_number_asked(text,question):return resolve(settings)['max_words']
    return first_window(settings,number=True)[0]

def _portion_cap_holds(body,question,settings):
    """c20-first-cue: G15's ceiling. ``body`` (the cue lengthened to the end of its sentence) is still a portion the listener can be
    asked to repeat: the profile's documented word cap (settings PRESETS['meaning']: ``max_words`` = 9), and for a question that asks
    for a number or a date the wider first window the planner itself uses (``portioner.first_window``: 12 words). Counted on the
    planner's own scale (``portioner.portion_size``), so the cue and its ceiling are weighed alike.

    Past that cap the sentence is no portion: G15 does not apply to it and the cue stays where ``meaning_cuts`` put it, inside the
    window (live level2-c of 06.11 11:07 failed its NDS step on ``above_hard_cap``: «22 процента — основная ставка НДС с 1 января 2026
    года.», 10 words against 9). G15 keeps its cases, which are 9 words and fewer («ПКО КО-1 — приходный кассовый ордер, по нему
    принимают наличные.»).

    The WORD cap is the firm rule and the only one here: a syllable count is an estimate that a term written in digits inflates
    («Указание Банка России 3210-У о порядке ведения кассовых операций.» is 9 words and over 26 estimated syllables, and it is the
    portion the owner asked for on 06.11), the same reading the stand's checker writes down (voice_probe_checks: «the WORD cap is the
    firm rule»)."""
    return portion_size(body)[0]<=_portion_cap(question,settings,body)

def _leaves_a_stub(probe,end):
    """U144: does a cue ending at ``end`` leave one or two words of its sentence behind, the sentence's end being known? Those words would be a portion of their own (no portion is two words but the tail of an answer)."""
    rest=probe[end:]
    stop=re.search(r'[.!?…]',rest)
    return bool(stop) and 1<=len(WORDS.findall(rest[:stop.start()]))<=2

def _clause_inside_cap(text,cue,question,settings,*,final,last):
    """c20-first-cue: the sentence is longer than a portion may be, so G15 cannot finish it - but the portion still ends where a thought
    ends. The LAST place of the first window (``portioner.meaning_cuts``) that closes a clause or a sentence, tears no phrase, holds the
    cap and is longer than the cue ``_first_meaning_core`` chose: «Курс падает, когда за границу уходит больше валюты,» instead of
    «Курс падает, когда за границу уходит больше» (r21 why-214, the cue of d479d73). Only text that has already arrived is looked at, so
    this costs no wait; where no such place exists the cue stays as it was, because a dash is no end of a thought («22 процента —
    основная ставка НДС» goes as it is, never «22 процента —»)."""
    probe,cuts,_=meaning_cuts(text,settings,final=final,number=asks_for_number(question))
    best=cue
    for cut in cuts:
        candidate=probe[:cut.end].strip()
        if len(candidate)<=len(best) or cut.torn or candidate[-1:] not in _CLOSES_A_THOUGHT:continue
        if _leaves_a_stub(probe,cut.end):continue      # U144
        # c22-reviewfix: a candidate with no number asked has the window of before (``first_window``: 8), as the core's own rule
        cap=_portion_cap(question,settings) if not asks_for_number(question) or says_the_number_asked(candidate,question) else first_window(settings)[0]
        if portion_size(candidate)[0]>cap or is_phone_phrase(candidate) or not strip_process_prefix(candidate,question):continue
        if _contrast_follows(probe,cut,candidate):continue      # c22-reviewfix (R21-07): never the negated half of «не X, а Y»
        best=candidate
    return best

def _finish_thought(text,cue,question='',settings=CALL_SETTINGS,*,final,last):      # c22-merge: fix-c20's callers pass neither: the call's profile
    """G15: the first portion ends on a finished thought. ``cue`` (a prefix of ``text``) that would stop 1-4 words short of the end of its
    sentence («ПКО КО-1 — приходный кассовый ордер, | по нему принимают наличные.», «Указание Банка России 3210-У | о порядке ведения
    кассовых операций.») is lengthened to that sentence end - the listener repeats one thought, not a head and a tail that waits for a
    confirmation. While the sentence is still arriving and fewer than that many words are known after the cue, the portion waits for its end
    (at most FINISH_WORDS words, a moment of the text channel); a tail longer than that is none of this rule's: the cue stays. Numbers and
    negations are never touched: only text that is already there is added.

    c20-first-cue: bounded by ``_portion_cap_holds``. A sentence end past the word cap of a portion is none of this rule's either -
    neither as a lengthening nor as a wait: the cue goes as ``meaning_cuts`` planned it, inside the cap. And a cue that already holds
    the number the question asked for is finished by C7-A's own measure: G15 leaves it alone."""
    if not text.startswith(cue):return cue
    # c20-first-cue (C7-A): the question asked for a number or a date and the cue states it: that IS the gist, and what follows is a
    # SECOND number the listener would have to repeat («Крымская война началась в октябре 1853 года | и продлилась до 1856-го.»,
    # «Крещение Руси обычно датируют 988-ым годом | при князе Владимире.»: the cues of the live run 20261103-164741). Neither
    # lengthened nor waited for: the first portion is over.
    # c22-merge: but not a number with a qualifier after it (R21-04, fix-c20): «269 000 рублей | без одной операции.», «Восемь планет, | не считая
    # карликовых» - the qualifier is part of the number said, and G15 finishes it inside the cap. A next word not yet whole is not known: G15 decides.
    # c22-reviewfix: and only the number ASKED (review 4a91807): a side number before it («Автор 14 поэм родился | в 1799 году.», «Обычно 13
    # процентов, | но для нерезидентов 30 процентов.») or a number torn from its unit or its second number («Размер кровати 160 | на 200
    # сантиметров.») is no answer: G15 goes on to the end of the sentence inside the cap, however many words that takes.
    owed=asks_for_number(question) and (_side_number(text,cue,question) or _torn_number(text,cue))
    if (asks_for_number(question) and says_the_number_asked(cue,question) and not owed and _qualifier_known_not_next(text,cue)
            and not set(norm_words(cue))&_NUMBER_QUALIFIERS):return cue      # «Восемь планет, не считая карликовых: | Меркурий, Венера, Земля, Марс.»: the qualifier is said, its list too
    rest=text[len(cue):]
    if not rest.strip():return cue if final or last or cue[-1:] in '.!?…' else None
    try:
        from razdel import sentenize
        spans=[(s.start,s.stop) for s in sentenize(text)]
    except ImportError:return cue
    n=len(cue)
    owner=next(((a,b) for a,b in spans if a<n<b),None)
    if owner is None:return cue                         # the cue ends a sentence
    body=text[:owner[1]]
    # the sentence is closed when text goes on after it, or it ends in a mark that is not the point inside a number
    closed=owner[1]<len(text.rstrip()) or (text.rstrip()[-1:] in '.!?…' and not re.search(r'\d[.,]$',text.rstrip()))
    counted=lambda part:[w for w in WORDS.findall(part) if normalize(w) not in PREPOSITIONS]
    seen=body[n:]
    if not _portion_cap_holds(body,question,settings):     # c20-first-cue: the thought is longer than a portion may be (9 words, 12 for a number or a date)
        return _clause_inside_cap(text,cue,question,settings,final=final,last=last)
    if not closed and not (final or last):
        if text[-1:].isalnum() and seen:                # the last word may still be growing
            seen=seen[:max(m.start() for m in WORDS.finditer(seen))] if WORDS.search(seen) else ''
        # c20-first-cue: and never a wait for a sentence end with no room left under the cap: it could only come past it
        # c22-merge: a body that already ends on its sentence mark needs no more words, only the sign that the mark is no point of a number
        # («дебет 70, кредит 76.» of 9 words waits for the next character, not for a tenth word)
        if (owed or len(counted(seen))<=FINISH_WORDS) and (portion_size(body)[0]<_portion_cap(question,settings) or body.rstrip()[-1:] in '.!?…'):return None
        return _clause_inside_cap(text,cue,question,settings,final=final,last=last)
    # c20-first-cue: a sentence END, not the ragged end of a segment. ``last`` alone (the producer's turn is over) is no sentence mark:
    # the text may go on in the next segment and its last word may be cut in half («…между ни» + «ми почти не пропускают тепло.»), and
    # a word cut in half is never spoken. Without ``closed`` or ``final`` there is nothing to finish the thought with.
    return body.strip() if (closed or final) and (1<=len(counted(seen))<=FINISH_WORDS or (owed and counted(seen))) else cue

_CONTRAST=frozenset(('но','а','однако','зато'))
_GLUE=frozenset(('на',))      # «N на M», «на кубический метр»; not «x» of a product («9 дней x 2 человека»: w3 scenes n2_d01, n2_d09)

def _sentence_rest(text,cue):
    """What follows ``cue`` up to the end of its sentence, as far as it has arrived."""
    rest=text[len(cue):]
    end=re.search(r'[.!?…](?=\s|$)',rest)
    while end and re.search(r'\d[.,]$',rest[:end.end()]) and rest[end.end():end.end()+1].isdigit():end=re.search(r'[.!?…](?=\s|$)',rest[end.end():])
    return rest[:end.end()] if end else rest

def _side_number(text,cue,question):
    """c22-reviewfix: the number of ``cue`` is not the number asked and the rest of its sentence holds it. A date question: the cue says no
    WHEN (``_dated``) and the rest does («Автор 14 поэм родился | в 1799 году.»). A quantity question: a contrast follows the cue and the rest
    holds another quantity («Обычно 13 процентов, | но для нерезидентов 30 процентов.»). C7-A's second date («в октябре 1853 года | и продлилась
    до 1856-го») is none of this: the cue says when."""
    rest=_sentence_rest(text,cue)
    if not rest.strip():return False
    if asks_for_date(question):
        return bool(_numbers(cue)-_numbers(question)) and not _dated(cue)-_numbers(question) and bool(_dated(rest)-_numbers(question))
    after=WORDS.match(rest.lstrip(' ,;:—–'))
    return bool(after) and normalize(after.group()) in _CONTRAST and bool(_numbers(rest,False)-_numbers(question,True)-_numbers(cue,False))

def _torn_number(text,cue):
    """c22-reviewfix: ``cue`` ends on a number or on the unit right after it, and the next word glues a second number or a unit to it
    («Размер кровати 160 | на 200 сантиметров.», «1000 килограммов | на кубический метр», «120 | на 80»): the planner has no glue for these."""
    body=cue.rstrip()
    if not body or not body[-1].isalnum():return False
    after=WORDS.match(text[len(cue):].lstrip())
    if not after or normalize(after.group()) not in _GLUE:return False
    tail=WORDS.findall(body)[-3:]
    return bool(_numbers(' '.join(tail)))

# c22-merge: a first cue never ends where its thought is still open: a dash, a preposition or a conjunction. «да», «так», «также», «пока»,
# «где» … are left out: they end a thought as often as they open one («Да,», «Это не так,»).
_OPEN_CONJ=frozenset('и а но или либо ни что чтобы чтоб как когда если хотя потому поскольку зато однако причём причем притом будто словно чем нежели едва пусть пускай ибо'.split())
_DASH=re.compile(r'\s*[—–-]\s*$')

def open_end(cue):
    """c22-merge: 'dash', 'preposition', 'conjunction' or '' - what leaves the thought open at the end of ``cue``. A cue that ends its sentence
    («В момент операции или сразу после.», «Через функции И и ИЛИ.») is closed whatever its last word is."""
    body=str(cue or '').rstrip()
    if not body or body[-1] in '.!?…':return ''
    body=body.rstrip(',;:').rstrip()
    if _DASH.search(body):return 'dash'
    found=WORDS.findall(body)
    last=normalize(found[-1]) if found else ''
    return 'preposition' if last in PREPOSITIONS else 'conjunction' if last in _OPEN_CONJ or last.replace('ё','е') in _OPEN_CONJ else ''

def _trim_open_end(cue):
    """The cue without what leaves it open: the dash, the preposition or the conjunction at its end, as often as they stand there
    («Штраф двадцать процентов по статье 123 —» -> «Штраф двадцать процентов по статье 123»). '' when nothing is left."""
    while cue and open_end(cue):
        body=cue.rstrip().rstrip(',;:').rstrip()
        if _DASH.search(body):cue=_DASH.sub('',body);continue
        words=list(WORDS.finditer(body))
        cue=body[:words[-1].start()].rstrip() if words else ''
    return cue.rstrip(' —–-')

def _close_open_end(text,cue,question,settings,*,final,last):
    """c22-merge: whatever rule made the first cue (R21's early «dash after its own predicate», G15, the cheapest place of the window), it does
    not end on a dash, a preposition or a conjunction. The next clause is taken when it fits the cap of a first portion (``_portion_cap``: 9
    words, 12 for a number or a date) - «Активный счёт учитывает имущество, пассивный — источники его образования.»; while it is still arriving
    and may yet fit, the cue waits for it (only text that is known is ever spoken). Otherwise the cue is cut at the last place that closes the
    thought: before the dash, the preposition or the conjunction («Штраф двадцать процентов по статье 123», «Перераспределение стоимости на
    возвратной основе»). Nothing is lost: what is cut off is the start of the next portion."""
    if not cue or not open_end(cue) or not text.startswith(cue):return cue
    cap=_portion_cap(question,settings)
    for mark in re.finditer(r'[,;:.!?…]',text[len(cue):]):
        end=len(cue)+mark.end()
        if text[end:end+1].isdigit() and text[end-2:end-1].isdigit():continue          # «1,5», «3.14»: a mark inside a number
        candidate=text[:end].strip()
        if portion_size(candidate)[0]>cap:break
        if end==len(text.rstrip()) and not (final or last) and text[end-2:end-1].isdigit():return None     # «… 123.» may go on as «123.5»
        if open_end(candidate) or is_phone_phrase(candidate):continue
        return candidate
    else:
        if not (final or last) and portion_size(text)[0]<cap:return None              # the next clause may still come inside the cap
    trimmed=_trim_open_end(cue)
    return trimmed if len(WORDS.findall(trimmed))>=1 else cue

def _first_meaning_core(text,question,settings,*,final,last,patient=False):
    """F1: the first cue of a call in the meaning profile - the first meaning portion (portioner.meaning_cuts) that says something the
    question does not (a content word of its own, a number, a negation, да/нет: ``_adds_nothing``). Once no further word can add a place
    (or the producer's turn is over) the cheapest such place is chosen, by the planner's own costs; before that, a clause of
    MEANING_EARLY_WORDS words or more that says something is spoken as soon as its comma, semicolon or colon has arrived, when no
    earlier place is cheaper (the listener waits in silence meanwhile; a dash too once the clause has its own predicate - a dash
    without one stands between a subject and its predicate, «сумма внутренних углов — 360 градусов», and waits for the costs). A first
    clause that only restates the topic («Крещение Руси») therefore
    runs on to a boundary inside the window that says more («Крещение Руси традиционно относят к 988 году,»). A restatement is spoken
    only when nothing in the window says more without tearing a phrase; an answer that is nothing but the question read back stays
    silent, as before. H5 item 5: once the whole answer is known (``final``) or a moment away (``patient``), a portion that only repeats the question is no portion: it takes in the first word that is new."""
    # C7-A: a question for a number or a date - the first portion runs on (a wider window) until it states a number the question does not
    number=asks_for_number(question)
    text,cuts,complete=meaning_cuts(text,settings,final=final,number=number)
    # integ9: the question goes along (F3 round 1), so an answer in the question's own words («Понимаю.» to «Вы понимаете…?») is no stall
    if not final and _stall_pending(text,question):return None      # the text WITHOUT a word that may still be growing
    if is_phone_phrase(text):return None
    # A lone word out of a longer sentence is a last resort, spoken only at the true end of a text that says something (as before F1):
    # «свойство» of a segment cut at «свойство тела сохранять» waits, «Чай» of «Чай или кофе.» (the question read back) is never said.
    answered=_complete_reply(text,question,settings,final=final,last=last)
    lone=(final or answered) and (answered or not _adds_nothing(text.strip(),question,settings))
    rows=[]
    for cut in cuts:
        candidate=text[:cut.end].strip()
        if (candidate and not is_phone_phrase(candidate) and strip_process_prefix(candidate,question)
                and (cut.words>1 or cut.sentence or lone)):
            rows.append((cut,candidate,not _adds_nothing(candidate,question,settings,roots=final or patient) and not _reference_header(candidate)))
    if number:
        counted=[row for row in rows if says_the_number_asked(row[1],question)]
        if counted:
            # the number has arrived: the cheapest place that holds it (a phrase is never torn for it while another place holds it)
            if complete or last or final:
                pool=[row for row in counted if not row[0].torn] or counted
                return min(pool,key=lambda row:(row[0].cost,-row[0].words))[1]
            rows=counted                                  # early: only a clause that holds the number may go before the end
        elif not (complete or last or final):
            return None                                   # the number may still come inside the window: wait for it
        else:
            # no number in the window: the cue of before, chosen in the window of before
            words_cap,syllables_cap=first_window(settings)
            rows=[row for row in rows if row[0].words<=words_cap and row[0].syllables<=syllables_cap] or rows
    says=[row for row in rows if row[2]]
    if not (complete or last or final):
        # early: the first clause that says something, is long enough, ends at a comma, semicolon or colon - or at a dash after its own
        # predicate («Нет, звук распространяется только в среде —») - and is the cheapest place so far («Восемь планет, не считая
        # карликовых:», not «… карликовых: Меркурий,»)
        for k,(cut,candidate,says_more) in enumerate(rows):
            closes=candidate[-1] in ',;:' or (candidate[-1] in '—–' and cut.verb)
            if (says_more and closes and (cut.words>=MEANING_EARLY_WORDS or (number and cut.words>=3 and _no_qualifier_next(text,cut))) and not cut.torn
                    and not _contrast_follows(text,cut,candidate) and all(cut.cost<=other.cost for other,_,_ in rows[:k])):
                return candidate
        return None
    if not says and (final or patient):
        if not (final or last):return None                # the next word of the job
        new=_first_new(text,question,settings)
        if new:return new
    if not says:
        if (final or last) and _adds_nothing(text.strip(),question,settings) and not answered:return None   # the question read back
        rows=[row for row in rows if row[0].words>1 or final or answered]   # a lone word that says nothing only at the end, as before
    if not rows:return None
    # A phrase is never torn for the sake of new information: a restatement that keeps every phrase whole beats a cut that tears one
    # («… закрепляет принцип свободы» | «договора» is never the cue).
    whole=[row for row in rows if not row[0].torn]
    pool=[row for row in says if not row[0].torn] or whole or says or rows
    return min(pool,key=lambda row:(row[0].cost,-row[0].words))[1]


_QUALIFIERS=frozenset('не ни без кроме включая исключая считая только если при но а зато однако хотя'.split())

def _no_qualifier_next(text,cut):
    """R21-04: a short clause that holds the number asked («Москве больше 875 лет,») is spoken at its comma - but only once the word after the comma is known and
    is no qualifier of it («Восемь планет, не считая карликовых:» is not «Восемь планет,»)."""
    after=WORDS.match(text[cut.end:].lstrip(' ,;:—–'))
    return bool(after) and normalize(after.group()) not in _QUALIFIERS

_NUMBER_QUALIFIERS=frozenset('не ни без кроме включая исключая считая только'.split())      # c22-merge: what changes the number said before it («при князе Владимире» does not)

def _qualifier_known_not_next(text,cue):
    """c22-merge: the word after ``cue`` has arrived whole and is no qualifier of the number in it (``_NUMBER_QUALIFIERS``: «без», «не», «кроме», «считая» …)."""
    rest=text[len(cue):];after=WORDS.match(rest.lstrip(' ,;:—–'))
    if not after:return not rest.strip()
    if after.end()+len(rest)-len(rest.lstrip(' ,;:—–'))>=len(rest) and text[-1:].isalnum():return False      # the last word may still be growing
    return normalize(after.group()) not in _NUMBER_QUALIFIERS

def _contrast_follows(text,cut,candidate):
    """R21-07: ``candidate`` is the first half of «не X, а Y» (a negation in it, «а» / «но» right after its comma): the contrast is part of what it says."""
    after=WORDS.match(text[cut.end:].lstrip(' ,;:—–'))
    return bool(after) and normalize(after.group()) in ('а','но','зато','однако') and any(word in ('не','ни') for word in norm_words(candidate))

def _closed(text,cuts,k,max_words):
    """W1F-A (a): the chosen cue closes at clause or sentence punctuation that has ALREADY arrived inside the word budget
    («Прививка тренирует» -> «Прививка тренирует иммунитет:»). Zero delay: only places that exist in this text are looked at."""
    cut=cuts[k]
    if not cut.brk:
        for later in cuts[k+1:]:
            if not later.brk:continue
            candidate=text[:later.end].strip()
            if (later.words<=max_words and later.ready and not later.dangling and not later.fragment and not later.heavy
                    and not is_phone_phrase(candidate) and strip_process_prefix(candidate)):
                return candidate
            break                                       # only the FIRST punctuation: the cue never runs past a clause
    return text[:cut.end].strip()
