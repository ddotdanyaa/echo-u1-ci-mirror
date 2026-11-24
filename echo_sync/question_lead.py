"""W5-lead: the beginning of an answer made of the question's own words, without the model, on the ear's text.

The owner: «тебя спрашивают, что такое 15-я статья налогового кодекса? И ты подсказываешь: 15-я статья налогового кодекса, налогового
кодекса. Прям сразу». The listener starts speaking at once, while the substance is being prepared. ``lead`` reads a question and gives
that opening (``Lead``) or None; ``splice`` says how BRAIN's answer goes on after an opening already spoken.

Forms are never built, only moved: every word of a lead is a word of the question in the form the question had it. The subject of
«когда началась Первая мировая война» is already nominative and its verb already agrees with it, so «Первая мировая война началась» is
those two pieces swapped; the analyzer only checks that the piece is a nominative noun group and that the verb agrees with it. In any
doubt (a case the analyzer cannot confirm, a verb that does not agree, a personal or yes/no question, a command, small talk, a question to
someone else, a dispute, two questions at once) the result is None: a wrong form is worse than silence.

Numbers and «не»/«ни» go into a lead only with a second witness: the cloud's text of the same question must give the very same lead. A
cloud text that gives another lead (or none) vetoes any lead. Always with fast_text on (no key). A lead is not the first
useful help: ``trace_row`` is its own journal line and never a ``first_useful`` mark.
"""
import re
from collections import namedtuple
from .classifier import IMPERATIVE
from .first_useful import _NUMBER_NOUNS,_REFERENCE_ALIASES,_numbers,asks_for_number
from .ru_alignment import _LOCK,_canonical,_lemma
from . import ru_alignment as _ru
from .textutil import WORDS
from .abbrev_state import SPELLING

Lead=namedtuple('Lead','text kind words stretch witnessed')      # kind: define meaning differ when when_in where how how_much why who quality
Splice=namedtuple('Splice','mode rest')                          # mode: continue rebuild trim pending refused apart

MAX_WORDS=7          # a lead the listener can say in one breath; a longer restatement is not a lead
WINDOW=4             # how many words past the lead's length an answer may take to restate it in other order (``splice``)

_OPENERS=re.compile(r'^(?:а|ну|и|так|вот|слушай(?:те)?|скажи(?:те)?|подскажи(?:те)?|не\s+подскажете|не\s+скажете|пожалуйста|кстати|'
                    r'интересно|вопрос(?:\s+такой)?|следующий\s+вопрос)\b[\s,:]*')
_TAILS=re.compile(r'[\s,]*\b(?:пожалуйста|вообще|простыми\s+словами|кратко|коротко|если\s+коротко|в\s+двух\s+словах|вкратце)$')
_PERSONAL=frozenset('я ты вы мы меня мне мной тебя тебе тобой вас вам вами нас нам нами мой моя мое мои моего моей моих твой твоя твое '
                    'твои твоего твоей ваш ваша ваше ваши вашего вашей наш наша наше наши нашего нашей себя себе свой своя свое свои'.split())
# The people of one's own life: «когда приедет мама» is personal although no pronoun says so.
_KIN=frozenset('мама папа мать отец жена муж сын дочь дочка брат сестра бабушка дедушка тетя дядя начальник начальница шеф друг подруга '
               'сосед соседка ребенок дети внук внучка парень девушка'.split())
_ORDINAL=re.compile(r'\d+-(я|ая|й|ый|ой|ий|е|ое)')       # a written ordinal in the nominative: «15-я», «21-й», «3-е»
_DISPUTE=re.compile(r'\b(?:разве|неужели|уверен[аы]?|ошибаешься|ошибаетесь|докажи(?:те)?|серьезно|с\s+чего|неправильно|неправда|'
                    r'да\s+ладно|откуда\s+ты|кто\s+сказал|кто\s+тебе)\b')
_CHATTER=re.compile(r'^(?:как\s+(?:дела|жизнь|сам|сама|настроение|поживаешь|поживаете|погода|оно|так|же\s+так)|что\s+(?:нового|слышно|'
                    r'делаешь|делаете|случилось|происходит)|кто\s+(?:там|это|говорит|звонит))\b')
_ANOTHER=re.compile(r'\b(?:спроси(?:те)?|пусть\s+(?:он|она|они)|у\s+него|у\s+нее|а\s+(?:он|она|они)\b|он\s+знает|она\s+знает)')
_WH=frozenset('что кто когда где куда откуда почему зачем отчего как сколько чем каков какова каково каковы какой какая какое какие '
              'каком каких какую какого какому каким которая который которое которые чей чья чье чьи'.split())
_QUALITY=frozenset({'каков','какова','каково','каковы','какой','какая','какое','какие'})
_ANSWER_REFUSES=re.compile(r'^\s*(?:нет\b|не\s+(?:знаю|могу|уверен)|к\s+сожалению|извин|я\s+не\b|такой\s+\w+\s+нет|такого\s+\w+\s+нет|'
                           r'такой\s+\w+\s+не\s+существует|это\s+не\s+так|вопрос\s+некорректен)',re.I)
_GLUE=frozenset({'российский','федерация','такой','именно','—'})     # what a restatement may add around the lead's own words

# -- the analyzer ---------------------------------------------------------------------------------------------------------------------

def _parses(word):
    _lemma('а')                                     # the shared analyzer is made through its locked seam
    with _LOCK:return _ru._MORPH.parse(word)

def _tags(word):
    return [p.tag for p in _parses(word)]

def _abbreviation(low):
    return low in SPELLING or all('UNKN' in t or 'Abbr' in t for t in _tags(low))

def _feats(tag):
    """What a word agrees in: 'plur', or its gender in the singular (a noun of common gender agrees with both)."""
    grams=set(str(tag).replace(' ',',').split(','))
    if 'plur' in grams:return {'plur'}
    if 'ms-f' in grams:return {'masc','femn'}
    genders=grams&{'masc','femn','neut'}
    return genders or {'masc','femn','neut'}

def _nominal(tag,pos):
    return tag.POS in pos and tag.case=='nomn'

def _noun_group(low,whole=True):
    """A nominative noun group at the start of ``low``: ``(end, feats)``, the words it takes and what a predicate must agree with. Its
    adjectives agree with its head; after the head come its dependents (any oblique words, «и», prepositions, numbers). ``whole``: all of
    ``low`` must be that group. None when the analyzer cannot confirm a nominative group."""
    adjectives=[];k=0
    while k<len(low):
        word=low[k]
        ordinal=_ORDINAL.fullmatch(word)
        if ordinal:
            ending=ordinal[1]
            adjectives.append([{'femn'} if ending in ('я','ая') else {'masc'} if ending in ('й','ый','ой','ий') else {'neut','plur'}]);k+=1;continue
        tags=_tags(word)
        head=_abbreviation(word) or any(_nominal(t,{'NOUN'}) for t in tags)
        adjective=any(_nominal(t,{'ADJF','PRTF'}) for t in tags)
        following=_tags(low[k+1]) if k+1<len(low) else []
        noun_next=any(_nominal(t,{'NOUN'}) for t in following) or (k+1<len(low) and (_abbreviation(low[k+1]) or _ORDINAL.fullmatch(low[k+1])))
        attribute=any(_nominal(t,{'ADJF','PRTF','NOUN'}) for t in following)
        if adjective and (not head or noun_next) and not _abbreviation(word) and (noun_next or attribute):
            adjectives.append([_feats(t) for t in tags if _nominal(t,{'ADJF','PRTF'})]);k+=1;continue
        if not head and (not adjective or any('Apro' in t for t in tags)):return None     # «это», «всё»: a pronoun, not a thing
        if _abbreviation(word):feats={'masc','femn','neut','plur'}
        elif head:feats=set().union(*(_feats(t) for t in tags if _nominal(t,{'NOUN'})))
        else:feats=set().union(*(_feats(t) for t in tags if _nominal(t,{'ADJF','PRTF'})))     # «самозанятые»: an adjective used as a noun
        for options in adjectives:
            if not any(f&feats for f in options):return None
            feats&=set().union(*options)
        end=k+1
        while end<len(low) and _dependent(low[end]):end+=1
        if whole and end<len(low):return None
        return end,feats
    return None

def _dependent(word):
    if word in _WH or word in _PERSONAL:return False
    if word in ('и','от','для','в','на','по','из','у','о','об','при','с','со','к','до','между','за','над','под'):return True
    if _abbreviation(word) or any(ch.isdigit() for ch in word):return True
    first=_tags(word)[0]
    return first.POS not in {'VERB','INFN','PRTS','ADJS','GRND','PRED','CONJ','PRCL','INTJ','NPRO','ADVB'} or word in ('и',)

def _verb(word,feats,short=False):
    """Does ``word`` (a finite verb, or a short form with ``short``) agree with a subject of ``feats``?"""
    for tag in _tags(word):
        if short:
            if tag.POS in ('PRTS','ADJS') and _feats(tag)&feats:return True
            continue
        if tag.POS!='VERB' or tag.mood=='impr' or tag.person in ('1per','2per'):continue
        if tag.tense=='past':
            if _feats(tag)&feats:return True
        elif tag.number=='plur' and 'plur' in feats:return True
        elif tag.number=='sing' and feats-{'plur'}:return True
    return False

def _predicate(word,feats):
    """The predicate of a «почему» question said in the declarative order: «небо голубое», «кошки мурлычут»."""
    return _verb(word,feats) or _verb(word,feats,short=True) or any(_nominal(t,{'ADJF'}) and _feats(t)&feats for t in _tags(word))

# -- reading a question ---------------------------------------------------------------------------------------------------------------

def _clean(text):
    text=str(text or '').strip()
    sentences=[s for s in re.split(r'[.!?…]+',text) if WORDS.search(s)]
    if len(sentences)!=1:return None                                     # two questions (or a preamble): which one the answer takes is the model's
    text=sentences[0].strip()
    named=re.match(r'^\s*([^\W\d_]+)\s*,',text)
    if named and any('Name' in t for t in _tags(named[1].casefold())):return None       # «Маша, когда …»: asked of someone else
    low=text.casefold().replace('ё','е')
    while True:
        cut=_OPENERS.sub('',low,count=1)
        if cut==low:break
        text=text[len(text)-len(cut):] if len(cut)<=len(text) else text;low=cut
    tail=_TAILS.search(low)
    if tail:text=text[:tail.start()];low=low[:tail.start()]
    return text,low

def _refused(low,words):
    if not words or 'ли' in words or 'или' in words:return True         # yes/no and choice: the answer is not the question's head
    if _PERSONAL.intersection(words) or _KIN.intersection(_lemma(w) for w in words) or _DISPUTE.search(low) or _CHATTER.search(low) or _ANOTHER.search(low) or IMPERATIVE.search(low):return True
    if any(t.POS=='VERB' and (t.person in ('1per','2per') or t.mood=='impr') for w in words for t in _tags(w)[:1]):return True
    lead_in=3 if words[:2]==['в','каком'] else 2 if words[:2]==['в','чем'] else 1
    if lead_in==1 and words[0] not in _WH:return True                  # no interrogative word of its own, or not in front
    if words[0]=='как' and len(words)>1 and words[1] in ('такое','так','же'):return True
    if any(x in _WH for x in words[lead_in:]):return True               # a second interrogative: two questions, or a subordinate one
    return False

def _read(question):
    """``(kind, pieces, tail)``: the lead as pieces of the question (each a list of word indices) in the lead's order, or None."""
    cleaned=_clean(question)
    if cleaned is None:return None
    text,low=cleaned
    found=list(WORDS.finditer(text));words=[m.group().casefold().replace('ё','е') for m in found]
    if _refused(low,words):return None
    surfaces=[m.group() for m in found]
    n=len(words)
    def group(at,whole=True):
        got=_noun_group(words[at:],whole)
        return (at+got[0],got[1]) if got else None
    w=words
    if w[:2]==['что','такое'] or (w[:1]==['кто'] and w[1:2] and w[1] in ('такой','такая','такие','таков')):
        got=group(2)
        return ('define',[range(2,n)],' —',surfaces) if got else None
    if w[:2] in (['что','означает'],['что','значит'],['что','обозначает']):
        got=group(2)
        return ('meaning',[range(2,n),[1]],'',surfaces) if got and _verb(w[1],got[1]) else None
    if w[:1]==['чем'] and 'от' in w:
        at=w.index('от')
        if w[1] in ('отличается','отличаются'):
            got=_noun_group(w[2:at])
            ok=got and _verb(w[1],got[1]) and at+1<n and all(_dependent(x) for x in w[at+1:])
            return ('differ',[range(2,at),[1],range(at,n)],'',surfaces) if ok else None
        verb=next((k for k in range(2,at) if w[k] in ('отличается','отличаются')),None)
        if verb is None:return None
        got=_noun_group(w[1:verb])
        ok=got and _verb(w[verb],got[1]) and at==verb+1 and at+1<n and all(_dependent(x) for x in w[at+1:])
        return ('differ',[range(1,verb),[verb],range(at,n)],'',surfaces) if ok else None
    if w[:4]==['в','чем','разница','между'] and n>4:
        ok=all(_dependent(x) for x in w[4:])
        return ('differ',[range(2,n)],'',surfaces) if ok else None
    if w[0] in _QUALITY:
        got=group(1)
        if not got:return None
        if w[0] in ('каков','какова','каково','каковы') and not _verb_short_agrees(w[0],got[1]):return None
        if w[0] in ('какой','какая','какое','какие') and not any(_nominal(t,{'ADJF'}) and _feats(t)&got[1] for t in _tags(w[0])):return None
        head=next((x for x in w[1:got[0]] if any(_nominal(t,{'NOUN'}) for t in _tags(x))),'')
        if asks_for_number(question) and head.startswith(_NUMBER_NOUNS):     # «какая самая длинная река» asks for a name, not a length
            return ('quality',[range(1,n)],' составляют' if got[1]=={'plur'} else ' составляет',surfaces)
        return ('quality',[range(1,n)],' —',surfaces)
    kinds={'когда':'when','где':'where','как':'how','сколько':'how_much','почему':'why','отчего':'why','кто':'who'}
    start,tail,kind=1,'',kinds.get(w[0])
    if w[:3] in (['в','каком','году'],['в','каком','веке']):start,tail,kind=3,' в','when_in'
    if kind is None or start>=n:return None
    rest=range(start,n)
    negated=w[start]=='не'
    verb_at=start+1 if negated else start
    if kind=='who':
        if verb_at>=n or not _verb(w[verb_at],{'masc'}) or verb_at+1>=n:return None
        ok=all(_dependent(x) and not any(_nominal(t,{'NOUN'}) and t.case=='nomn' and len(_tags(x))==1 for t in _tags(x)) for x in w[verb_at+1:])
        return ('who',[range(verb_at+1,n),range(start,verb_at+1)],'',surfaces) if ok else None
    if verb_at<n and any(t.POS=='VERB' for t in _tags(w[verb_at])):
        if (_lemma(w[verb_at])=='быть' and verb_at+2<n and any(t.POS=='PRTS' for t in _tags(w[verb_at+1]))):
            got=group(verb_at+2)
            if got and _verb(w[verb_at],got[1]) and _verb(w[verb_at+1],got[1],short=True):
                return (kind,[range(verb_at+2,n),range(start,verb_at+2)],tail,surfaces)
            return None
        got=group(verb_at+1)
        if got and _verb(w[verb_at],got[1]):
            return (kind,[range(verb_at+1,n),range(start,verb_at+1)],tail,surfaces)
        return None
    if verb_at<n and any(t.POS in ('PRTS','ADJS') for t in _tags(w[verb_at])) and kind!='why':
        got=group(verb_at+1)               # «где похоронен Пушкин», «как устроен атом»: a short form in the verb's place
        if got and _verb(w[verb_at],got[1],short=True):
            return (kind,[range(verb_at+1,n),range(start,verb_at+1)],tail,surfaces)
        return None
    if kind=='why' and not negated:
        got=_noun_group(w[start:],whole=False)
        if got:
            end,feats=got
            end+=start
            # the group may have swallowed an adjective predicate («небо голубое»): give it back
            if end==n and end-start>1 and _predicate(w[n-1],feats) and _noun_group(w[start:n-1]):end=n-1
            if end<n and _predicate(w[end],feats) and n-end<=3:return ('why',[range(start,n)],'',surfaces)
    return None

def _verb_short_agrees(word,feats):
    return any(t.POS=='ADJS' and _feats(t)&feats for t in _tags(word))

def _render(read):
    kind,pieces,tail,surfaces=read
    order=[k for piece in pieces for k in piece]
    words=[SPELLING.get(surfaces[k].casefold(),surfaces[k]) for k in order]
    if not words or len(words)>MAX_WORDS:return None
    text=' '.join(words)
    text=text[0].upper()+text[1:]
    stretch=None
    if kind=='define' and len(words)>=3:
        lows=[x.casefold() for x in words]
        got=_noun_group(lows,whole=False)
        if got and len(words)-got[0]==0:
            head=next((k for k in range(len(lows)) if any(_nominal(t,{'NOUN'}) for t in _tags(lows[k]))),None)
            if head is not None and len(words)-head-1>=2:stretch=text+', '+' '.join(words[head+1:])+tail
    return text+tail,kind,len(words),stretch

def _key(text):
    return tuple(part for atom in _canonical(text,()) for part in _REFERENCE_ALIASES.get(atom,(atom,)) if atom!='—')

def _sensitive(text):
    """A number or a negation in the lead: it needs the second witness. A small spoken ordinal is a name («Первая мировая»), as
    ``first_useful._numbers`` reads it; digits always count."""
    return bool(_numbers(text)) or any(ch.isdigit() for ch in text) or bool({'не','ни'}&set(_canonical(text,())))

def _alone(question):
    try:read=_read(question)
    except ImportError:return None
    return _render(read) if read else None

def lead(question,*,cloud=None):
    """The opening of the answer to ``question`` (the ear's text) made of its own words, or None. ``cloud``: the cloud's text of the same
    question, the second witness: a number or «не» of the lead needs it, and when it is given it must give the same lead."""
    got=_alone(question)
    if got is None:return None
    text,kind,count,stretch=got
    witnessed=False
    if cloud is not None:
        other=_alone(cloud)
        if other is None or _key(other[0])!=_key(text):return None
        witnessed=True
    if _sensitive(text) and not witnessed:return None
    return Lead(text,kind,count,stretch,witnessed)

# -- the answer after a lead ---------------------------------------------------------------------------------------------------------

def _after(answer,end):
    return re.sub(r'^[\s,—–:\-]+','',answer[end:])

def splice(lead_text,answer,*,final=False):
    """How BRAIN's ``answer`` goes on after ``lead_text``, already spoken. ``continue``: the answer begins with the lead, the rest goes on
    with no word said twice. ``rebuild``: the answer opens with the lead's words in another order or form («Статья 15 НК РФ —» for «15-я
    статья налогового кодекса —»): that restatement is dropped. ``trim``: the answer begins with the lead's content but not with its
    trailing function word («в»): the common start is dropped (the listener has said one word the answer does not have). ``refused``: the
    answer refuses or says no: it is spoken whole and the lead stands abandoned. ``apart``: the answer starts elsewhere and is spoken
    whole after the lead. ``pending``: the answer so far may still become ``continue`` or ``rebuild``; nothing is decided yet."""
    answer=str(answer or '')
    lead_key=_key(lead_text.rstrip(' —'))
    words=list(WORDS.finditer(answer))
    if not final and words and answer[-1:].isalnum():words=words[:-1]          # the last word may still grow
    if not final and len(words)<3:return Splice('pending','')                # «Нет», «Не …»: a refusal is known from its third word
    if _ANSWER_REFUSES.match(answer):return Splice('refused',answer.strip())
    keys=[_key(answer[:m.end()]) for m in words[:len(lead_key)+WINDOW]]
    for k in range(len(keys)-1,-1,-1):
        if keys[k]==lead_key:return Splice('continue',_after(answer,words[k].end()))
    allowed=set(lead_key)|_GLUE
    best=None
    for k,key in enumerate(keys):
        if sorted(a for a in key if a not in _GLUE)==sorted(a for a in lead_key if a not in _GLUE) and set(key)<=allowed:best=k
    if best is not None and (final or len(words)>best+1):return Splice('rebuild',_after(answer,words[best].end()))
    if not final:
        so_far=keys[-1] if keys else ()
        first=words[0].group() if words else ''
        near=len(words)<len(lead_key)+WINDOW and (set(_key(first))&allowed or any(ch.isdigit() for ch in first))
        if so_far==lead_key[:len(so_far)] or near:return Splice('pending','')
    content=[a for a in lead_key if not _function(a)]
    for k,key in enumerate(keys):
        if key==lead_key[:len(key)] and len(key)<len(lead_key) and all(_function(a) for a in lead_key[len(key):]) and len(key)>=len(content):
            return Splice('trim',_after(answer,words[k].end()))
    if best is not None:return Splice('rebuild',_after(answer,words[best].end()))
    return Splice('apart',answer.strip())

def _function(atom):
    return atom in ('в','во','на','с','со','к','по','от','до','из','у','о','об','и','что','—','составлять','являться')

# -- the call --------------------------------------------------------------------------------------------------------------------------

def trace_row(got,*,at):
    """The journal line of a lead: its own event, never a ``first_useful`` mark (a lead is the question's words, not help)."""
    return {'event':'lead_cue','at':at,'kind':got.kind,'text':got.text,'words':got.words,'witnessed':got.witnessed}
