"""Current-chunk RU alignment using razdel, pymorphy3 and RapidFuzz.

Locality is restricted to the issued chunk, following the bounded alignment
seam studied in Open Prompter 894ae79c9ce8cbf47f6d046cf9f109d3201d17d1.
Its ASCII phonetic encoder/thresholds are deliberately not ported to Russian.
Third-party implementations are imported, with their installed MIT notices.
Fuzzy distance can request a repeat; only identical canonical sequences ACK - except, for a portion of 5 atoms or more, one
word that states nothing left out or changed (F1, ``_lenient``), and a repeat that starts with the end of the confirmed text
(``_after_confirmed``).

What counts as "the same words" (WAVE 2 / Task A): case, punctuation runs, ё/е, a hyphen, a space or a merge between
the same letters («что-то» / «что то» / «чтото», «чтобы» / «что бы»), hesitation sounds and listed fillers around or
inside what was heard (never inside the expected portion), and numbers written with digits or spoken in words for every
magnitude, with years, centuries and dates as ordinals (``ru_numbers``). What never counts as the same: a different
number, a sign or unit, an added or dropped «не»/«ни», another word.

A number and its unit (WAVE 2 / Task U): right after a number the written sign or abbreviation and the words that say it are
one unit, in every case of the noun - «100 °C» / «сто градусов Цельсия», «500 ₽» / «пятьсот рублей», «$30» / «тридцать
долларов», «20 м/с» / «двадцать метров в секунду», «5 с» / «пять секунд» (``_units``). A different unit stays a different unit
(°, °C and °F are three), and without a number nothing is merged.

A decimal said the way a person says it (WAVE 2 / Task E2): «тридцать шесть и шесть десятых градуса Цельсия» is 36,6 (``ru_numbers``), and the
colloquial «тридцать шесть и шесть» is too, but only where the portion itself holds that very decimal (``_colloquial_decimals``).
"""
from __future__ import annotations
import functools
import os
import re
import threading
import unicodedata
from collections import namedtuple
from decimal import Decimal
from . import ru_numbers as numbers
from .ack_semantics import _dash_is_semantic
from .ru_numbers import Item

_LOCK=threading.RLock()
_MORPH=None
_SMALL=('ноль один два три четыре пять шесть семь восемь девять десять одиннадцать '
        'двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать').split()
_NUMBERS={word:i for i,word in enumerate(_SMALL)}
_NUMBERS['нуль']=0
_NUMBERS.update(dict(zip('двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто'.split(),range(20,100,10))))
_NUMBERS.update(dict(zip('сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот'.split(),range(100,1000,100))))
_ORDINALS=dict(zip(('нулевой первый второй третий четвертый пятый шестой седьмой восьмой девятый десятый '
                 'одиннадцатый двенадцатый тринадцатый четырнадцатый пятнадцатый шестнадцатый '
                 'семнадцатый восемнадцатый девятнадцатый').split(),range(20)))
_ORDINALS.update(dict(zip('двадцатый тридцатый сороковой пятидесятый шестидесятый семидесятый восьмидесятый девяностый'.split(),range(20,100,10))))
_ORDINALS.update(dict(zip('сотый двухсотый трехсотый четырехсотый пятисотый шестисотый семисотый восьмисотый девятисотый'.split(),range(100,1000,100))))
_ORDINALS.update({'тысячный':1000,'двухтысячный':2000})
_UNITS={'процент':'%','промилле':'‰','килограмм':'kg','кг':'kg','грамм':'g','г':'g',
        'миллиграмм':'mg','мг':'mg','километр':'km','км':'km','метр':'m','м':'m',
        'сантиметр':'cm','см':'cm','миллиметр':'mm','мм':'mm',
        'плюс':'+','минус':'−'}
# Abbreviations that are units only right after a number: «5 мин» = «пять минут», «3 л» = «три литра».
# «см» is here, not in _UNITS: pymorphy3 takes it for the imperative «смотри» (lemma «смотреть»), so the lemma lookup never found it.
_ABBREVIATIONS={'мин':'минута','сек':'секунда','ч':'час','л':'литр','мл':'миллилитр','т':'тонна','шт':'штука',
                'руб':'рубль','коп':'копейка','см':'cm'}
_MARKS={'%':'%','‰':'‰','+':'+','−':'−','*':'×','×':'×','/':'÷','÷':'÷',
        '=':'=','<':'<','>':'>','≤':'≤','≥':'≥','^':'^','№':'номер','§':'§'}
# Punctuation an ASR adds or drops freely. Brackets, slashes, operators and the like are NOT here: they change meaning.
_IGNORABLE=frozenset('.,!?;:«»"\'…“”„‟‘’‚‛‹›ʼʻ´`¡¿‼⁇⁈⁉')
_ORDINAL_DIGITS=re.compile(r'(\d+)-(?:я|й|е|го|му|ой|ая|ый|ое|ые|их|ым|ом|м)')
# C7-B: «в 1990-х», «20-х годов» are decades (ordinals); «2-х», «3-х» are «двух», «трёх» (cardinals) and stay protected literals.
_DECADE_DIGITS=re.compile(r'([1-9]\d+)-х')
# A minus glued to a plain number: razdel splits «-5» only at the start of a text and after punctuation; after a word («было −5 °C»)
# it is one token, which would be a protected literal that «минус пять» can never equal.
_SIGNED=re.compile(r'([-−])(\d+(?:[.,]\d+)?)')
_HYPHEN=re.compile('[-‐‑]')
# Hesitation sounds: «э», «эм», «мм», «хм», «э-э», «м-м». A bare «м» is a metre, not a hesitation.
_HESITATION=re.compile(r'(?:э+|э+м+|м{2,}|ы+|х+м+|г+м+|[эмыау](?:[-‐‑][эмыау])+)')
_NUMBER_FILLERS=frozenset({'ну','вот'})
_ROMAN=re.compile(r'[ivxlcdm]+')
# Connectors a portion may start with and that may be left out when it is repeated («и движется», «а млекопитающее», «вот почему»):
# the ASR drops such short words as often as a speaker does. «хорошо», «так», «ладно» are words, not connectors.
_OPTIONAL_LEADING=frozenset({'и','а','ну','вот','э','эм'})

# U16: «XIII–XV веках», «1941–1945 годах», «3–4» are written ranges. razdel keeps such a range as ONE token, which can never be
# the words said. Ranges are the owner's rule, always on (no key, no switch): INT–INT and ROMAN–ROMAN are split around a
# protected '~' atom and the ends before a plural «веках»/«годах» are ordinals (``ru_numbers.range_end_ordinal``).
_RANGE_DASHES='-–—−‐‑'
_RANGE_SPLIT=re.compile(r'((?:0|[1-9]\d*)|[ivxlcdm]+)['+_RANGE_DASHES+r']((?:0|[1-9]\d*)|[ivxlcdm]+)')

Atom=namedtuple('Atom','atom surface kind')   # kind: 'w' word, 'u' unit, 'n' number, 'p' protected literal / symbol


@functools.lru_cache(maxsize=8192)
def _lemma(word):
    global _MORPH
    import pymorphy3
    with _LOCK:
        if _MORPH is None:
            _MORPH=pymorphy3.MorphAnalyzer()
        try:
            return _MORPH.parse(word)[0].normal_form.replace('ё','е')
        except Exception:
            # A character pymorphy3 cannot describe (a Tangut letter makes unicodedata.name fail) is its own lemma;
            # a transcript must never be able to raise inside the wire reader.
            return word.replace('ё','е')


# -- tokens -> items ----------------------------------------------------------------------------------------------------

def _digit_item(word):
    if re.fullmatch(r'(?:0|[1-9]\d*)',word):
        return Item('digits',Decimal(word),word)
    if re.fullmatch(r'(?:0|[1-9]\d*)[,.]\d+',word):
        return Item('digits',Decimal(word.replace(',','.')),word)
    # Preserve unsupported dates, IDs, fractions or mixed forms as protected literal tokens.
    # Decimal comma/dot alone are equivalent.
    value=word.replace(',','.') if re.fullmatch(r'\d+[,.]\d+',word) else word
    return Item('lit','#'+value,word)


def _word_item(word,prior):
    lemma=_lemma(word)
    previous=prior[-1] if prior else None
    after_number=previous is not None and previous.kind in ('digits','card','half')
    if word in numbers.FRACTIONS:
        return Item('frac',numbers.FRACTIONS[word],word)
    if lemma in _NUMBERS:return Item('card',_NUMBERS[lemma],word)
    if lemma in _ORDINALS:return Item('ord',_ORDINALS[lemma],word)
    if lemma=='полтора':return Item('half',Decimal('1.5'),word)
    scale=numbers.SCALES.get(lemma)
    if scale is None and after_number:scale=numbers.SCALE_ABBREVIATIONS.get(word)
    if scale is not None:
        after_half=len(prior)>=2 and prior[-2].surface=='с' and prior[-1].surface in numbers.HALF_WORDS
        # «тысячи людей» is not a number, «пять тысяч» and «тысяча человек» are.
        if after_number or after_half or word in numbers.SINGULAR_SCALES:
            return Item('scale',scale,word)
    if _ROMAN.fullmatch(word):
        value=numbers.roman_value(word)
        if value is not None:return Item('roman',(value,lemma),word)
    mapped=(_ABBREVIATIONS.get(word) if after_number else None) or _UNITS.get(lemma)
    if mapped:return Item('unit',mapped,word)
    return Item('word',lemma,word)


def _word_items(word,prior):
    parts=[part for part in _HYPHEN.split(word) if part]
    if len(parts)>1 and all(len(part)==1 for part in parts) and not _HESITATION.fullmatch(word):
        # «x-y» is an operation between two operands, not one word; keep the minus.
        out=[]
        for index,part in enumerate(parts):
            if index:out.append(Item('lit','−','-'))
            out.append(_word_item(part,prior+out))
        return out
    return [_word_item(word,prior)]


def _filler(word):
    """A sound or a word said while a number is being found. Not «мм» (a unit), which is a hesitation only away from a number."""
    return word in _NUMBER_FILLERS or (bool(_HESITATION.fullmatch(word)) and not set(word)<={'м'})


def _inside_a_number(tokens,at,prior):
    """H5 item 4 (class 18, n1_01 step 17): is the filler ``tokens[at]`` said inside a number? A number stands before it and goes on after it: «сто сорок… э-э… четыре тысячи» is one number."""
    if not prior or prior[-1].kind not in ('card','digits','scale') or not _filler(tokens[at].text):return False
    for token in tokens[at+1:]:
        word=token.text
        if all(ch in _IGNORABLE for ch in word) or _filler(word):continue
        return word.isdigit() or _word_item(word,prior).kind in ('card','ord','scale')
    return False


def _range_items(word,following):
    """``[first, '~', last]`` items for the token ``word`` when it is a written range, else None. Numbers: both ends digits.
    Roman numerals: both ends well formed, and only before a century word («XIII–XV веках»), never a loose «x-y»."""
    match=_RANGE_SPLIT.fullmatch(word)
    if not match:return None
    first,last=match.groups()
    if first.isdigit()!=last.isdigit():return None
    mark=Item('lit','~',word[len(first)])
    if first.isdigit():return [_digit_item(first),mark,_digit_item(last)]
    if following not in numbers.CENTURY_FORMS or numbers.roman_value(first) is None or numbers.roman_value(last) is None:return None
    return [_word_item(first,[]),mark,_word_item(last,[])]


def _range_value(item):
    """The integer an end of a range stands for (digits as written, a Roman numeral), else None."""
    if item.kind=='digits' and item.surface.isdigit():return int(item.value)
    if item.kind=='roman':return item.value[0]
    return None


def _is_range_mark(item):
    return item.kind=='lit' and item.value=='~'


def _adjacent_romans(items,i):
    """True when ``items[i]`` is the first of two Roman numerals joined by the range mark."""
    return i+2<len(items) and items[i].kind=='roman' and _is_range_mark(items[i+1]) and items[i+2].kind=='roman'


def _range_pair(items,i):
    """True when ``items[i]`` starts «first ~ last <plural word>» whose last end is an ordinal before that word."""
    if i<0 or i+3>=len(items) or not _is_range_mark(items[i+1]):return False
    first,last,word=items[i],items[i+2],items[i+3]
    if first.kind!=last.kind or first.kind not in ('digits','roman') or word.kind!='word':return False
    a,b=_range_value(first),_range_value(last)
    if a is None or b is None:return False
    if first.kind=='roman' and not 1<=a<=39:return False
    return numbers.range_end_ordinal(b,word.surface)


def _read_number(items,index):
    """``numbers.read_number``, except that the two ends of a range read as ordinals."""
    if _range_pair(items,index) or _range_pair(items,index-2):
        return numbers.Read('#ord:%d'%_range_value(items[index]),index+1)
    return numbers.read_number(items,index)


def _items(text):
    from razdel import tokenize
    items=[]
    tokens=list(tokenize(text))
    for at,token in enumerate(tokens):
        word=token.text
        if _inside_a_number(tokens,at,items):continue
        ordinal=_ORDINAL_DIGITS.fullmatch(word) or _DECADE_DIGITS.fullmatch(word)
        pair=_range_items(word,tokens[at+1].text if at+1<len(tokens) else '')
        if pair:
            items.extend(pair)
        elif ordinal:
            items.append(Item('lit','#ord:'+ordinal.group(1),word))
        elif word in '-–—':
            if _dash_is_semantic(text,token.start):items.append(Item('lit','−',word))
        elif word in _MARKS:
            items.append(Item('lit',_MARKS[word],word))
        elif word==':' and re.search(r'\d\s*$',text[:token.start]) and re.match(r'\s*\d',text[token.stop:]):
            items.append(Item('lit','!ratio:',word))
        elif _SIGNED.fullmatch(word):
            sign,digits=_SIGNED.fullmatch(word).groups()
            items.extend((Item('lit','−',sign),_digit_item(digits)))
        elif any(ch.isdigit() for ch in word):
            items.append(_digit_item(word))
        elif any(ch.isalpha() for ch in word):
            items.extend(_word_items(word,items))
        elif not all(ch in _IGNORABLE for ch in word):
            items.append(Item('lit','!symbol:'+word,word))
    return _zero_groups(_scales_before_numbers(items))


def _zero_groups(items):
    """H5 item 4: the recognizer's way with «144 000» read by groups: «сто сорок четыре ноль ноль ноль». Three zeros after a number, and no more of them, are its thousands."""
    zero=lambda item:item.kind=='card' and item.value==0
    out=[];k=0
    while k<len(items):
        if k and items[k-1].kind in ('card','digits') and items[k-1].value and all(zero(item) for item in items[k:k+3]) and len(items[k:k+3])==3 and not (k+3<len(items) and items[k+3].kind=='card'):
            out.append(Item('scale',1000,' '.join(item.surface for item in items[k:k+3])));k+=3
        else:
            out.append(items[k]);k+=1
    return out


def _scales_before_numbers(items):
    """C7-B: a scale word in any case followed by a number word is the scale of that number - «до тысячи восемьсот пятьдесят шестого»
    is 1856, «к тысяче девятисотому году» 1900, «с тысячей двумястами» 1200. With no number word after it («тысячи людей», «о тысячах»)
    it stays the word it is; a different number after it is still a different number (``ru_numbers`` reads the run)."""
    out=list(items)
    for k in range(len(out)-1):
        item=out[k]
        if item.kind=='word' and item.value in numbers.SCALES and out[k+1].kind in ('card','ord'):
            out[k]=Item('scale',numbers.SCALES[item.value],item.surface)
    return out


# -- items -> atoms ------------------------------------------------------------------------------------------------------

def _protected(item):
    names={'card':'number','ord':'ordinal','scale':'scale','half':'half','frac':'fraction'}
    return Atom('!spoken:'+names.get(item.kind,item.kind)+':'+str(item.value),item.surface,'p')


def _plain(item):
    """An item that is not part of a number, as an atom."""
    if item.kind=='word':return Atom(item.value,item.surface,'w')
    if item.kind=='unit':return Atom(item.value,item.surface,'u')
    if item.kind=='lit':return Atom(item.value,item.surface,'p')
    if item.kind=='roman':return Atom(item.value[1],item.surface,'w')
    if item.kind=='frac':
        lemma=_lemma(item.surface)      # «десятых» outside a decimal is the ordinal it always was
        return Atom('#ord:%d'%_ORDINALS[lemma],item.surface,'n') if lemma in _ORDINALS else Atom(_UNITS.get(lemma,lemma),item.surface,'w')
    return _protected(item)


@functools.lru_cache(maxsize=2048)
def _atoms(text):
    # Compatibility folding would turn 1² into 12 and destroy math semantics.
    text=numbers.merge_digit_groups(unicodedata.normalize('NFC',text).casefold().replace('ё','е'))
    items=_items(text)
    atoms=[];index=0
    while index<len(items):
        read=_read_number(items,index)
        if read is None:
            atoms.append(_plain(items[index]));index+=1
        elif isinstance(read,numbers.Fail):
            # Two arbitrary spoken numbers are never summed: "пять шесть" must never become "11".
            atoms.extend(_protected(item) for item in items[index:read.end]);index=read.end
        else:
            atoms.append(Atom(read.atom,' '.join(item.surface for item in items[index:read.end]),'n'));index=read.end
    # A numbered reference is the same in natural speech: "статья 18" /
    # "статья восемнадцатая". Keep ordinal/cardinal distinction elsewhere.
    labels={'статья','пункт','глава','раздел','счет'}
    for i,value in enumerate(atoms):
        if value.atom.startswith('#ord:') and ((i and atoms[i-1].atom in labels) or (i+1<len(atoms) and atoms[i+1].atom in labels)):
            atoms[i]=value._replace(atom='#'+value.atom.removeprefix('#ord:'))
        # G3: «988-го года» is what the digits «988 года» are (ru_numbers._ordinal_context: an ordinal only from 1000 there).
        elif value.atom.startswith('#ord:') and i+1<len(atoms) and atoms[i+1].surface=='года' and 100<=int(value.atom[5:])<1000:
            atoms[i]=value._replace(atom='#'+value.atom[5:])
    return tuple(atoms)


def _canonical(text,fillers=(),detail=False):
    """The comparison form of a text: a tuple of atoms (strings), or with ``detail`` the ``Atom`` tuples.

    ``fillers`` (legacy, plain atoms only) strips leading atoms; ``match_current`` does its own, finer, stripping.
    """
    atoms=_atoms(text)
    if detail:return atoms
    result=[value.atom for value in atoms]
    while result and result[0] in fillers:result.pop(0)
    return tuple(result)


# -- units after a number --------------------------------------------------------------------------------------------------
# «при 100 °C» is repeated «при ста градусах Цельсия», «500 ₽» «пятьсот рублей», «$30» «тридцать долларов», «20 м/с» «двадцать
# метров в секунду». Directly after a number (a currency sign: directly in front of one) the written sign and the words that say it
# are ONE unit atom; a noun is its lemma, so every case of it is the same unit. Only there: «в рублях» and «в ₽» stay what they were,
# and two units never become one (°, °C and °F; ₽, $ and €; «км/ч» and «км»). Units that were unambiguous already («km», «%»,
# «минута»…) keep their atom; only a unit the word-level tables could not read gets one.
_CYRILLIC_S=chr(0x441)      # the Cyrillic «с» (U+0441): seconds, and the «С» typed in «°С»; the Latin «c» looks the same and is another letter
_CURRENCY=frozenset('$€₽')
# «км/ч», «м/с», «м/мин» and «километров в час», «метров в секунду»: the unit by the word or the abbreviation of the time.
_PER={'час':('ч','час'),'секунда':(_CYRILLIC_S,'сек','секунда'),'минута':('мин','минута')}


def _unit_phrases():
    """``(atom, words)``: the run of lemmas and written forms that says a unit, longest first."""
    rows=[]
    for atom,scale,letter in (('°c','цельсий','c'),('°f','фаренгейт','f')):
        rows+=[(atom,('градус',scale)),(atom,('градус','по',scale)),(atom,('°'+letter,)),(atom,('°',letter))]
    rows+=[('°c',('°'+_CYRILLIC_S,)),('°c',('℃',)),('°f',('℉',)),('°',('градус',)),('°',('°',))]
    rows+=[('₽',('рубль',)),('₽',('руб',)),('₽',('₽',)),('$',('доллар',)),('$',('$',)),('€',('евро',)),('€',('€',))]
    # the time units by their abbreviation too: the word-level table reads «5 мин» but not «5 тыс. мин», and «с» not at all
    # («5 с половиной» has to stay a number first); «часах» / «часами» are «часы» (the watch) for pymorphy3
    for per,names in _PER.items():rows+=[(per,(name,)) for name in names]
    rows+=[('час',('часах',)),('час',('часами',))]
    for base in ('km','m','cm','mm'):
        for separator in ('÷','в'):
            for per,names in _PER.items():rows+=[(base+'/'+per,(base,separator,name)) for name in names]
    return tuple(sorted(rows,key=lambda row:-len(row[1])))


_UNIT_PHRASES=_unit_phrases()


def _is_quantity(atom):
    """A cardinal or decimal number (not an ordinal: «пятый градус» is not five degrees)."""
    return atom.kind=='n' and atom.atom.startswith('#') and not atom.atom.startswith('#ord:')


def _unit_at(atoms,i):
    """``(unit atom, end)`` for the unit that starts at ``atoms[i]`` (longest first), else ``None``."""
    for unit,words in _UNIT_PHRASES:
        end=i+len(words)
        if end<=len(atoms) and all(a.kind!='n' and (a.atom==word or a.surface==word) for a,word in zip(atoms[i:end],words)):
            return unit,end
    return None


def _units(atoms):
    """``atoms`` with the unit that stands right after a number as one ``u`` atom, and a currency sign in front of its number
    moved behind it («$30» is said «тридцать долларов»)."""
    out=[];i=0
    while i<len(atoms):
        atom=atoms[i]
        if _is_quantity(atom):
            out.append(atom);i+=1
            found=_unit_at(atoms,i)
            if found:
                unit,end=found
                out.append(Atom(unit,' '.join(a.surface for a in atoms[i:end]),'u'));i=end
        elif atom.kind=='p' and atom.surface in _CURRENCY and i+1<len(atoms) and _is_quantity(atoms[i+1]):
            out.extend((atoms[i+1],Atom(atom.surface,atom.surface,'u')));i+=2
        else:
            out.append(atom);i+=1
    return tuple(out)


# -- comparison ----------------------------------------------------------------------------------------------------------

def _hesitation(atoms,i):
    atom=atoms[i]
    if atom.kind not in ('w','u') or not _HESITATION.fullmatch(atom.surface):return False
    # «5 мм» is millimetres: a hesitation sound made of «м» right after a number is a unit.
    return not (set(atom.surface)<={'м'} and i and atoms[i-1].kind=='n')


def _without_hesitations(atoms):
    return tuple(atom for i,atom in enumerate(atoms) if not _hesitation(atoms,i))


def _glue(atoms):
    """The words with their boundaries (and hyphens) taken away; numbers, units and symbols stay protected separators."""
    out,run=[],[]
    for atom in atoms:
        if atom.kind=='w':
            run.append(''.join(ch for ch in atom.surface if ch.isalnum()))
        else:
            if run:out.append(''.join(run));run=[]
            out.append(atom.atom)
    if run:out.append(''.join(run))
    return tuple(out)


def _variants(atoms,allowed):
    """What was heard without its hesitations and with 0..all of the fillers at both ends, least stripped first.

    The portion itself is never stripped: a portion that starts with «хорошо» or «так» has to be said with it.
    """
    kept=_without_hesitations(atoms)
    lead=0
    while lead<min(len(kept),8) and kept[lead].kind=='w' and kept[lead].surface in allowed:lead+=1
    trail=0
    while trail<min(len(kept)-lead,8) and kept[len(kept)-1-trail].kind=='w' and kept[len(kept)-1-trail].surface in allowed:trail+=1
    return [kept[i:len(kept)-j] for i in range(lead+1) for j in range(trail+1) if i+j<len(kept)]


@functools.lru_cache(maxsize=8192)
def _tense(word):
    """'past' / 'pres' / 'futr' for a verb form (or participle), else ``None``; never raises."""
    _lemma(word)      # the shared analyzer is created under the lock in _lemma
    with _LOCK:
        try:
            return _MORPH.parse(word)[0].tag.tense
        except Exception:
            return None


def _tense_flipped(pairs):
    """Same lemmas word for word, but a verb in another tense: «был принят» is not «будет принят».

    The lemma comparison accepts any inflection of a word (cases, numbers); that must not extend to a fact that
    changes with the tense. Only differing surfaces are looked at, and only when both forms have a tense.
    """
    for x,y in pairs:
        if x.kind==y.kind=='w' and x.surface!=y.surface:
            first,second=_tense(x.surface),_tense(y.surface)
            if first and second and first!=second:return True
    return False


def _close(a,b,distance):
    """Is ``a`` an attempt at ``b``: a part of it, or mostly it?"""
    if len(a)>len(b)+3:return False
    if len(a)<len(b) and any(a==b[i:i+len(a)] for i in range(len(b)-len(a)+1)):
        return True
    if distance.normalized_similarity(a,b)>=0.6:return True
    return len(a)==len(b) and all(x==y or (min(len(x),len(y))>=8 and not x.startswith(('#','!'))
                   and not y.startswith(('#','!')) and distance.distance(x,y,score_cutoff=1)<=1) for x,y in zip(a,b))


def _is_filler(atom,allowed):
    return atom.kind=='w' and atom.surface in allowed


def _cover(heard,expected,allowed):
    """The aligned ``(heard atom, expected atom)`` pairs when ``expected`` is all of ``heard`` once its hesitation sounds
    (anywhere) and the fillers at its two ends are left out; else ``None``.

    The expected atoms are matched in order; every heard atom that matches none must be a filler in the leading or the
    trailing run. A filler the portion itself asks for is matched, not skipped («Хорошо ну проводит» for «Хорошо проводит»).
    """
    kept=_without_hesitations(heard)
    n=len(kept)
    lead=0
    while lead<n and _is_filler(kept[lead],allowed):lead+=1
    trail=0
    while trail<n-lead and _is_filler(kept[n-1-trail],allowed):trail+=1
    pairs,matched=[],0
    for i,atom in enumerate(kept):
        if matched<len(expected) and atom.atom==expected[matched].atom:
            pairs.append((atom,expected[matched]));matched+=1
        elif i>=lead and i<n-trail:
            return None
    return pairs if matched==len(expected) else None


def _expected_variants(written,allowed):
    """The portion, and the portion without the connectors it starts with («и», «а», «ну», «вот», «э»)."""
    skip=0
    while skip<min(len(written)-1,3) and written[skip].kind=='w' and written[skip].surface in _OPTIONAL_LEADING             and written[skip].surface in allowed:skip+=1
    return [written[k:] for k in range(skip+1)]


_INTEGER_ATOM=re.compile(r'#\d+')
_DECIMAL_ATOM=re.compile(r'#\d+\.\d+')


def _colloquial_decimals(said,written):
    """The heard atoms with each colloquial decimal read as ONE number: «тридцать шесть и шесть» (``#36``, ``и``, ``#6``) is ``#36.6`` where, and
    only where, the portion itself holds ``#36.6`` (Task E2, ruling 5). Anywhere else «пять и шесть» is two numbers and a conjunction, and a
    number with a fraction word («и шесть десятых») never gets here: ``ru_numbers`` has read it already. ``None`` when nothing was changed."""
    decimals={atom.atom for atom in written if atom.kind=='n' and _DECIMAL_ATOM.fullmatch(atom.atom)}
    if not decimals:return None
    dotted={atom.atom for atom in written if atom.kind=='n' and _DECIMAL_ATOM.fullmatch(atom.atom) and '.' in atom.surface}      # c24 P19: a number written with a dot (an article, a section), never «36,6»: that one keeps ruling 5 (only «N и M»)
    out,i,changed=[],0,False
    while i<len(said):
        if (i+2<len(said) and said[i].kind=='n' and _INTEGER_ATOM.fullmatch(said[i].atom) and said[i+1].kind=='w' and said[i+1].atom==numbers.AND_WORD
                and said[i+2].kind=='n' and _INTEGER_ATOM.fullmatch(said[i+2].atom)):
            joined='#%s.%s'%(said[i].atom[1:],said[i+2].atom[1:])
            if joined in decimals:
                out.append(Atom(joined,' '.join(atom.surface for atom in said[i:i+3]),'n'));i+=3;changed=True;continue
        number=_number_said_in_two(said,i,dotted) if dotted else None      # c24 P19: «триста сорок шесть [точка] двенадцать» of «Статья 346.12»
        if number is not None:
            out.append(number[0]);i=number[1];changed=True;continue
        out.append(said[i]);i+=1
    return tuple(out) if changed else None


_POINT_WORDS=frozenset(('точка','дробь','запятая'))
_NUMBER_PIECE=lambda atom:(atom.kind=='n' and _INTEGER_ATOM.fullmatch(atom.atom)) or atom.atom.startswith('!spoken:number:')


def _number_said_in_two(said,i,decimals):
    """c24 P19 (half_hour seeds 0, 8): a number with a point the way an article's is said, the whole part and the part after the point as two numbers,
    with «точка»/«дробь»/«запятая» between or nothing («триста сорок шесть двенадцать», which ``ru_numbers`` refuses to sum and keeps as protected words).
    ``(Atom, the index after it)`` only when the two read as exactly a decimal the portion holds; else None."""
    j=i
    while j<len(said) and _NUMBER_PIECE(said[j]):j+=1
    run=said[i:j]
    if not run:return None
    tail=None
    if j+1<len(said) and said[j].atom in _POINT_WORDS:
        k=j+1
        while k<len(said) and _NUMBER_PIECE(said[k]):k+=1
        tail=(said[j+1:k],k)
    splits=[(run,tail[0],tail[1],said[i:tail[1]])] if tail and tail[0] else []
    splits+=[(run[:cut],run[cut:],j,run) for cut in range(1,len(run))]
    for left,right,end,whole in splits:
        a,b=_one_integer(left),_one_integer(right)
        if a is not None and b is not None and '#%s.%s'%(a,b) in decimals:
            return Atom('#%s.%s'%(a,b),' '.join(atom.surface for atom in whole),'n'),end
    return None


def _one_integer(atoms):
    """The digits of ``atoms`` read as ONE whole number, else None."""
    read=_atoms(' '.join(atom.surface for atom in atoms))
    return read[0].atom[1:] if len(read)==1 and read[0].kind=='n' and _INTEGER_ATOM.fullmatch(read[0].atom) else None


def _judge(spoken,written,allowed,distance):
    """``ack`` / ``attempt`` / ``None`` for the atoms heard (``spoken``) against the atoms of the portion (``written``)."""
    b=tuple(atom.atom for atom in written)
    variants=[variant for variant in _variants(spoken,allowed) if variant]
    for goal in _expected_variants(written,allowed):
        wanted=tuple(atom.atom for atom in goal)
        glued=_glue(goal)
        pairs=_cover(spoken,goal,allowed)
        if pairs is not None and not _tense_flipped(pairs):return 'ack'
        for variant in variants:
            a=tuple(atom.atom for atom in variant)
            if _glue(variant)==glued:return 'ack'                 # the same letters: the same tense
            if len(a)==2*len(wanted) and a[:len(wanted)]==wanted and a[len(wanted):]==wanted:return 'ack'
    for variant in dict.fromkeys((variants[0],variants[-1])) if variants else ():
        if _close(tuple(atom.atom for atom in variant),b,distance):return 'attempt'
    return None


# -- F1: a meaning-sized portion, repeated the way a person repeats it ---------------------------------------------------------------
# From LENIENT_MIN_WORDS atoms on, a repeat may leave out or change ONE word that states nothing (two from 8 atoms on): a particle, a
# conjunction or a manner adverb («Крещение Руси (традиционно) относят к 988 году»), and a discourse word added («это же статья»). An adjective
# is never left out (candidate 8 audit, ruling A: «Прибыль определяется …» for «Чистая прибыль определяется …», «Номинальная процентная ставка»,
# «Реальная доходность», «Переменные затраты» - the adjective that agrees with its noun is a part of the term, and «чистая» / «валовая» /
# «средняя» are different things; only particles, conjunctions, manner adverbs and fillers may go). A number, unit or symbol, a noun, verb, pronoun, preposition,
# a negation, a word of time, condition, choice or restriction is key and is never left out, added or changed (R2a: another number,
# negation, subject, time or condition never confirms). A shorter portion is confirmed word for word, as before.
LENIENT_MIN_WORDS=5
_KEY_WORDS=frozenset((
    'не ни нет никогда нигде никуда ниоткуда никак никто ничто ничего никого никому ничем нисколько ничуть '   # negation
    'если раз хотя чтобы пока когда как бы будто словно ли или либо иначе разве неужели '                       # condition, time, choice
    'только лишь даже почти около примерно приблизительно едва чуть всего уже еще всегда иногда часто редко '   # restriction, degree, time
    'сейчас теперь сегодня вчера завтра раньше позже потом затем тогда сразу снова опять давно недавно скоро '
    'больше меньше более менее '
    'сколько почему зачем где куда откуда насколько что кто сначала сперва точно').split())   # w8-repeat: a question word left out is a different question
# Added words that state nothing: a repeat may hold one where the portion has none.
_DISCOURSE=frozenset('же ведь вот вон именно вовсе вообще просто тоже также и а но это ну мол собственно конечно обычно традиционно'.split())


@functools.lru_cache(maxsize=8192)
def _word_class(surface):
    """'loose' (a particle, conjunction, interjection or manner adverb), 'adjective' (attributive, not a pronoun) or 'key'."""
    if surface in _KEY_WORDS:return 'key'
    _lemma(surface)
    with _LOCK:
        try:parses=_MORPH.parse(surface)
        except Exception:return 'key'
    if not parses:return 'key'
    tag=parses[0].tag
    lemma=parses[0].normal_form.replace('ё','е')
    # «неверный», «неправильно», «невозможный»: a negation inside the word is a negation (but «небесный», «нефтяной» are not)
    with _LOCK:
        negated=lemma.startswith('не') and len(lemma)>4 and _MORPH.word_is_known(lemma[2:])
    if negated:return 'key'
    if tag.POS in ('PRCL','CONJ','INTJ'):return 'loose'
    # «ночью», «летом», «днём» are adverbs and nouns: a time, never loose
    if tag.POS=='ADVB' and not any(parse.tag.POS=='NOUN' for parse in parses):return 'loose'
    if tag.POS in ('ADJF','PRTF') and 'Apro' not in tag and 'Anum' not in tag:return 'adjective'
    return 'key'


def _atom_class(atom):
    return _word_class(atom.surface) if atom.kind=='w' else 'key'


def _align(a,b):
    """The longest common subsequence of two atom tuples (by atom): its ``(i, j)`` index pairs, in order."""
    n,m=len(a),len(b)
    table=[[0]*(m+1) for _ in range(n+1)]
    for i in range(n-1,-1,-1):
        for j in range(m-1,-1,-1):
            table[i][j]=table[i+1][j+1]+1 if a[i].atom==b[j].atom else max(table[i+1][j],table[i][j+1])
    pairs,i,j=[],0,0
    while i<n and j<m:
        if a[i].atom==b[j].atom:pairs.append((i,j));i+=1;j+=1
        elif table[i+1][j]>=table[i][j+1]:i+=1
        else:j+=1
    return pairs


def _lenient(spoken,written,allowed):
    """F1: does ``spoken`` confirm a portion of LENIENT_MIN_WORDS atoms or more with only non-key words left out, added or changed?"""
    if len(written)<LENIENT_MIN_WORDS:return False
    budget=1 if len(written)<8 else 2
    for variant in _variants(spoken,allowed):
        pairs=_align(variant,written)
        if not variant or not pairs or _tense_flipped([(variant[i],written[j]) for i,j in pairs]):continue
        edits=adjectives=0;fine=True
        bounds=[(-1,-1)]+pairs+[(len(variant),len(written))]
        for (i0,j0),(i1,j1) in zip(bounds,bounds[1:]):
            added,dropped=variant[i0+1:i1],written[j0+1:j1]
            if not added and not dropped:continue
            edits+=1
            if len(added)>1 or len(dropped)>1:fine=False;break
            if added and dropped:                       # a word changed: a loose word for a loose word («традиционно» -> «обычно»)
                fine=_atom_class(added[0])==_atom_class(dropped[0])=='loose'
            elif dropped:                               # a word left out: only a loose one (ruling A: never an adjective, a part of the term)
                kind=_atom_class(dropped[0]);adjectives+=kind=='adjective';fine=kind=='loose'
            else:                                       # a word added: only one that states nothing
                fine=added[0].kind=='w' and added[0].surface in _DISCOURSE
            if not fine:break
        if fine and 0<edits<=budget and adjectives<=1:return True
    return False


def _after_confirmed(spoken,written,before,allowed,distance):
    """F1: what was heard starts with the end of the text already confirmed and goes on with the whole waiting portion («централизованно
    по плану» while «по плану,» waits): the waiting portion is confirmed. The rest has to confirm it by the usual rules."""
    kept=_without_hesitations(spoken)
    lead=0
    while lead<len(kept) and _is_filler(kept[lead],allowed):lead+=1
    kept=kept[lead:]
    for k in range(min(len(before),len(kept)-1,12),0,-1):
        if tuple(atom.atom for atom in kept[:k])==tuple(atom.atom for atom in before[-k:]):
            rest=kept[k:]
            if _judge(rest,written,allowed,distance)=='ack' or _lenient(rest,written,allowed):return True
    return False


# -- w8-repeat: a word the recogniser garbled into a non-word ---------------------------------------------------------------------------
# «рахоты» for «работы»: the ear writes a sound-alike that is no Russian word at all. It cannot be another word of the speaker's, so it is
# read as the portion's word it is nearest to: ONE such word (two from 8 atoms on), the portion's word of 6 letters or more, one edit per
# 5 letters (at least one). A number, a unit, a symbol never; a heard word that IS a word (another day, another case, another noun) never.
GARBLE_MIN_LETTERS=6
GARBLE_EDITS_PER=5


def _known_word(surface):
    _lemma(surface)
    with _LOCK:
        try:return bool(_MORPH.word_is_known(surface))
        except Exception:return True


def _without_s(atoms):
    """The atoms without the one-letter «с»: the ear swallows it («с того места» -> «того места») or invents it («есть с спасибо»)."""
    return tuple(atom for atom in atoms if not (atom.kind=='w' and atom.surface=='с'))


def _heal(spoken,written):
    """``spoken`` with each garbled non-word put back as the portion's word it garbles, or ``None`` when there is none to put back."""
    try:from rapidfuzz.distance import Levenshtein
    except ImportError:return None
    have={atom.atom for atom in spoken}
    free=[atom for atom in written if atom.kind=='w' and len(atom.surface)>=GARBLE_MIN_LETTERS and atom.atom not in have]
    budget=1 if len(written)<8 else 2
    out,healed=[],0
    for atom in spoken:
        if atom.kind=='w' and healed<budget and len(atom.surface)>=GARBLE_MIN_LETTERS-1 and not _known_word(atom.surface):
            near=[(Levenshtein.distance(atom.surface,w.surface),w) for w in free if abs(len(w.surface)-len(atom.surface))<=1]
            best=sorted(((d,w) for d,w in near if 0<d<=max(1,len(w.surface)//GARBLE_EDITS_PER)),key=lambda x:x[0])
            if best and (len(best)==1 or best[0][0]<best[1][0]):
                word=best[0][1]
                out.append(Atom(word.atom,atom.surface,'w'));free.remove(word);healed+=1;continue
        out.append(atom)
    return tuple(out) if healed else None


# -- g7: an abbreviation of the portion said as the voice says it: by its letters («РФ» - «эр эф»), or the common ones in full ----------------
_LETTER_NAMES={'а':'а','б':'бэ|бе','в':'вэ|ве','г':'гэ|ге','д':'дэ|де','е':'е','ж':'жэ|же','з':'зэ|зе','и':'и','к':'ка','л':'эл|эль','м':'эм','н':'эн',
               'о':'о','п':'пэ|пе','р':'эр','с':'эс','т':'тэ|те','у':'у','ф':'эф','х':'ха','ц':'цэ|це','ч':'че','ш':'ша','щ':'ща','э':'э','ю':'ю','я':'я'}
_IN_FULL={'рф':r'российск\w*\s+федераци\w*','нк':r'налогов\w*\s+кодекс\w*','гк':r'гражданск\w*\s+кодекс\w*','тк':r'трудов\w*\s+кодекс\w*',
          'ндс':r'налог\w*\s+на\s+добавленн\w*\s+стоимост\w*','ндфл':r'налог\w*\s+на\s+доходы\s+физических\s+лиц'}

_SHORT_FORMS={'п':'пункт','пп':'подпункт','ст':'статья','ч':'часть','гл':'глава'}       # before a number only: «п. 2», «ст. 15»


def _short_forms_in_full(expected):
    """g7: ``expected`` with «п.», «пп.», «ст.», «ч.», «гл.» before a number written as the words the voice says («П. 2 ст. 15» - «пункт 2 статья 15»)."""
    return re.sub(r'(?<![\w])(пп|п|ст|ч|гл)\.\s*(?=\d)',lambda m:_SHORT_FORMS[m.group(1).casefold()]+' ',expected,flags=re.I)


def _abbreviations_as_written(heard,expected):
    """``heard`` with each ALL-CAPS abbreviation of ``expected`` that was said by its letters or in full written as the portion writes it; only the
    portion's own abbreviations, letter for letter in their order: «гэ ка» is never «НК»."""
    out=heard
    for word in dict.fromkeys(re.findall(r'(?<![\w])[А-ЯЁ]{2,5}(?![\w])',expected)):
        low=word.casefold().replace('ё','е')
        if not all(ch in _LETTER_NAMES for ch in low):continue
        spelled=r'\s*'.join('(?:'+_LETTER_NAMES[ch]+')' for ch in low)
        out=re.sub(r'(?<![\w])'+spelled+r'(?![\w])',low,out,flags=re.I)
        if low in _IN_FULL:out=re.sub(r'(?<![\w])'+_IN_FULL[low]+r'(?![\w])',low,out,flags=re.I)
    return out


_NEGATIONS=frozenset(('не','ни','нет','без','да'))
_NEVER_BEGUN=_NEGATIONS|_KEY_WORDS      # «не Нет» is no begun «нет», «не не» no stammer of «не»: a word that turns the meaning is never a stammer (a single word)


def without_repeats(heard,expected):
    """g7: the words heard without their stammer, or ``None``: a word or up to six words said twice in a row («статья статья», «сто шестьдесят восемь
    сто шестьдесят восемь», «сто шестьдесят сто шестьдесят восемь»), a word begun and said again («ст статья»). Never where the portion itself says
    words twice in a row; a begun word is never one of the portion's own words."""
    def bare(word):return word.casefold().replace('ё','е').strip('.,;:!?—–-«»"()…')
    words=[w for w in str(heard).split() if bare(w)];said=[bare(w) for w in words];own=[bare(w) for w in str(expected).split() if bare(w)]
    if any(own[i:i+k]==own[i+k:i+2*k] for k in range(1,7) for i in range(len(own)-2*k+1)):return None
    out,i=[],0
    while i<len(words):
        k=next((k for k in range(6,0,-1) if i+2*k<=len(said) and said[i:i+k]==said[i+k:i+2*k] and not (_NEVER_BEGUN if k==1 else _NEGATIONS).intersection(said[i:i+k])),0)      # r07: the count of «не» never changes
        if k:i+=k;continue
        if i+1<len(said) and 2<=len(said[i])<len(said[i+1]) and said[i+1].startswith(said[i]) and said[i] not in own and said[i] not in _NEVER_BEGUN:i+=1;continue
        out.append(words[i]);i+=1
    return ' '.join(out) if out and len(out)<len(words) else None


_without_stammer=without_repeats


_RANGE_JOINTS=frozenset(('по','до','и','или'))
_RANGE_FROM=frozenset(('с','со','от'))
_RANGE_WORD=re.compile(r'(?<![\w])'+_RANGE_SPLIT.pattern+r'(?![\w])',re.I)


def _end_value(atom):
    """U16: ``(value, ordinal)`` of an atom that can be one end of a range as it is heard (an ordinal, a number, two numbers side by side, a Roman numeral the ear wrote), else None."""
    name=atom.atom
    for prefix,ordinal in (('#ord:',True),('!spoken:ordinal:',True),('!spoken:number:',False)):
        if name.startswith(prefix) and name[len(prefix):].isdigit():return int(name[len(prefix):]),ordinal
    if name[:1]=='#' and name[1:].isdigit():return int(name[1:]),True      # digits as the ear wrote them are neutral
    if atom.kind=='w' and _ROMAN.fullmatch(name) and numbers.roman_value(name) is not None:return numbers.roman_value(name),True
    return None


def _is_end(atom,end):
    """Is ``atom`` the end ``end`` (an atom of the portion's range) said: the same value, an ordinal where the portion writes an ordinal."""
    found,wanted=_end_value(atom),_end_value(end)
    return found is not None and found[0]==wanted[0] and (found[1] or not wanted[1])


def spoken_as_written(heard,expected):
    """U16: ``heard`` with each range the portion writes («XIII–XV веках», «1941–1945») that was said as its two ends («тринадцатом по пятнадцатом»,
    «тринадцатом пятнадцатом», «с пяти до семи», the numerals written apart) written as the range, or ``heard`` itself. Both ends must be the portion's own
    values, in its order, as ordinals where it writes ordinals; the joint between them is optional (the ear drops «по»)."""
    if not isinstance(heard,str) or not isinstance(expected,str):return heard
    try:
        own=_atoms(expected)
        ranges=[(own[k-1],own[k+1],''.join(a.surface for a in own[k-1:k+2]),own[k-2].atom if k>=2 else '',own[k+2] if k+2<len(own) else None)
                for k in range(1,len(own)-1) if own[k].atom=='~' and own[k-1].kind=='n' and own[k+1].kind=='n']
        if not ranges:return heard
        said=list(_atoms(heard));out=[];i=0;changed=False
        while i<len(said):
            hit,span=None,0
            for r in ranges:
                if i+1<len(said) and _is_end(said[i],r[0]) and _is_end(said[i+1],r[1]):hit,span=r,2
                elif i+2<len(said) and _is_end(said[i],r[0]) and said[i+1].kind=='w' and said[i+1].atom in _RANGE_JOINTS and _is_end(said[i+2],r[1]):hit,span=r,3
                if hit:break
            if hit is None:
                out.append(said[i].surface);i+=1;continue
            if out and said[i-1].atom in _RANGE_FROM and hit[3] not in _RANGE_FROM:out.pop()
            out.append(hit[2]);i+=span;changed=True
            # The word after the range is the portion's own form of it («века» said, «веках» written), or the range would not be read as a range.
            if hit[4] is not None and hit[4].kind=='w' and i<len(said) and said[i].kind=='w' and said[i].atom==hit[4].atom:out.append(hit[4].surface);i+=1
        return ' '.join(out) if changed else heard
    except Exception:
        return heard


def unit_start(text,pos):
    """U16: where the unit that ``pos`` falls in begins: a written range («XIII–XV», «1941–1945») is never cut in the middle, so a position inside one
    is the start of it. Any other position is ``pos``."""
    if isinstance(text,str):
        for match in _RANGE_WORD.finditer(text):
            first,last=match.groups()
            if first.isdigit()!=last.isdigit() or (not first.isdigit() and (numbers.roman_value(first.casefold()) is None or numbers.roman_value(last.casefold()) is None)):continue
            if match.start()<pos<match.end():return match.start()
    return pos


# U53: the LAST word of a portion the ear cut («воинский у» for «воинский устав», «гла» for «глав») or got a letter wrong («написывал» for «описывал»)
# is the portion's word when everything before it is said. Not a number, not «не»; a head needs the word before it said (``_judge`` over the whole portion).
LAST_WORD_SIMILAR=0.8
LAST_WORD_MIN_LETTERS=5
LAST_HEAD_MIN_LETTERS=4


def _last_word_as_written(spoken,written):
    """``spoken`` with its last word put back as the portion's last word when the ear cut it or got it wrong (see above), else None."""
    from rapidfuzz.distance import Indel
    if len(spoken)<2 or len(written)<2:return None
    heard,wanted=spoken[-1],written[-1]
    if heard.kind!='w' or wanted.kind!='w' or heard.atom==wanted.atom or wanted.atom in ('не','ни') or any(not ch.isalpha() for ch in heard.surface+wanted.surface):return None
    a,b=heard.surface,wanted.surface
    head=len(b)>=LAST_HEAD_MIN_LETTERS and len(a)<len(b) and b.startswith(a) and spoken[-2].atom==written[-2].atom
    near=len(b)>=LAST_WORD_MIN_LETTERS and Indel.normalized_similarity(a,b)>=LAST_WORD_SIMILAR
    return spoken[:-1]+(wanted,) if head or near else None


def match_current(heard,expected,fillers=(),before=None,lenient=True,garble=False):
    """Return ack/attempt/None. No forward search, skipping, cursor or I/O.

    ``before``: the text of the answer the listener has already confirmed (F1: a repeat may start with its end). ``lenient``: False holds a repeat to
    every word of the portion (G3: where the words go on after it, a word left out may be the one that was changed)."""
    if not isinstance(heard,str) or not isinstance(expected,str) or max(len(heard),len(expected))>4000:
        return None
    try:
        from rapidfuzz.distance import Levenshtein
        allowed=frozenset(str(w).casefold().replace('ё','е') for w in fillers)
        # Hesitations are left out of what was heard FIRST: «сто э градусов Цельсия» is a number followed by its unit. The portion
        # keeps its own, so a hesitation inside it still has to be said.
        said=_without_hesitations(_canonical(heard,(),True))
        spoken=_units(said)
        written=_units(_canonical(expected,(),True))
        b=tuple(atom.atom for atom in written)
        if not spoken or not b or max(len(spoken),len(b))>80:return None
        verdict=_judge(spoken,written,allowed,Levenshtein)
        if verdict=='ack' or (lenient and _lenient(spoken,written,allowed)):return 'ack'
        restored=_last_word_as_written(spoken,written)
        if restored is not None and _judge(restored,written,allowed,Levenshtein)=='ack':return 'ack'      # U53
        written_as=_abbreviations_as_written(heard,expected)
        if written_as!=heard and match_current(written_as,expected,fillers,before,lenient,garble)=='ack':return 'ack'
        ranged=spoken_as_written(heard,expected)
        if ranged!=heard and match_current(ranged,expected,fillers,before,lenient,garble)=='ack':return 'ack'
        in_full=_short_forms_in_full(expected)
        if in_full!=expected and match_current(heard,in_full,fillers,before,lenient,garble)=='ack':return 'ack'
        smooth=_without_stammer(heard,expected)
        if smooth is not None and match_current(smooth,expected,fillers,before,lenient,garble)=='ack':return 'ack'
        if garble:
            healed=_heal(spoken,written)
            if healed is not None and (_judge(healed,written,allowed,Levenshtein)=='ack' or (lenient and _lenient(healed,written,allowed))):return 'ack'
            bare_spoken,bare_written=_without_s(healed or spoken),_without_s(written)
            if (len(bare_spoken)!=len(healed or spoken) or len(bare_written)!=len(written)) and len(bare_written)>=3 \
                    and (_judge(bare_spoken,bare_written,allowed,Levenshtein)=='ack' or (lenient and _lenient(bare_spoken,bare_written,allowed))):return 'ack'
        if isinstance(before,str) and before.strip() and len(before)<=4000:
            confirmed=_units(_canonical(before,(),True))
            if confirmed and _after_confirmed(spoken,written,confirmed,allowed,Levenshtein):return 'ack'
        # «тридцать шесть и шесть градусов Цельсия» for a portion that holds 36,6: one more way to read what was heard, tried only when the
        # words as they stand do not already confirm the portion (a portion is always its own repeat), and only for that very decimal.
        colloquial=_colloquial_decimals(said,written)
        if colloquial is not None:
            again=_judge(_units(colloquial),written,allowed,Levenshtein)
            return again if again=='ack' else (verdict or again)
        return verdict
    except ImportError:
        # An incomplete dependency install never enables a permissive matcher.
        return None


def whole_portions(words,chunks,fillers=()):
    """U60: the portions of ``chunks`` (in order) that ``words`` say whole, word for word, to its very end, or None: reading beyond the portion on the page is reading the next ones, and the cursor
    goes after the last of them. Each is judged strict (``lenient=False``): a word, a number or a «не» of its own is no such portion."""
    out,at=[],0
    for chunk in chunks:
        if at>=len(words):break
        size=len(str(chunk).split())
        for length in sorted(range(max(1,size-3),size+4),key=lambda n:abs(n-size)):
            if at+length<=len(words) and match_current(' '.join(words[at:at+length]),chunk,fillers,lenient=False)=='ack':
                out.append(chunk);at+=length;break
        else:return None
    return out if out and at>=len(words) else None


# -- G6 (WAVE16): where a stumble stopped ---------------------------------------------------------------------------------------------
# The listener said a part of the portion and stopped: the cue begins with the very word they stopped before. What the ear wrote is aligned to a head of
# the portion by the cost of its edits (Levenshtein on words): a word swallowed (the ear's or the speaker's), a word of their own in the place of the
# portion's, an added word, each costs one; the same word in another case, a garbled word («язательный» of «обязательный»), the head of a word cut off,
# numbers by value whatever way they are said cost nothing or little; a hesitation, a filler, a stutter («об-об общие»), a word said twice almost nothing.
# The place is after the last word of the portion the alignment reached. A number or a «не»/«ни» the listener did not say as written (left out, another
# value, one too many) is where the cue begins, before anything after it: a wrong figure is never passed over. No start (a question, other words, the
# whole portion) is None.
_RESUME_CHEAP=frozenset('ну вот это типа короче значит вообще собственно именно просто реально конкретно как там его самое блин сейчас щас секунду секундочку так ой ага да ладно сказать скажем'.split())
_RESUME_BLANK=re.compile(r'(?:^|\s)(?:не\s+(?:помню|знаю|могу|вспомню)|забыл\w*|как\s+(?:там|же|его)|дальше\s+не)(?=\s|$).*$')
_RESUME_STUTTER=re.compile(r'(?<![\w-])(\w{1,4})(?:[-‐‑]\1)+(?![\w-])')      # «по-по», «е-е-е»: a stutter the ear wrote with hyphens
_RESUME_STUTTER_HEAD=re.compile(r'(?<![\w-])(\w{1,4})(?:[-‐‑]\1)+[-‐‑](?=\1\w)')      # «м-м-материально-вещественной»: the stutter hyphened to the word it stumbles on is no part of the word (else the word said whole reads as a garbled one: cued again)
_RESUME_OPEN='«"„“‘\'([{$€₽−-'


def _resume_value(atom):
    """A number by its value alone: «первым» and «1», «пятнадцать» of a run the reader would not sum («пятнадцать первым») and «15», «20,» of a list and «20»."""
    return re.sub(r'^(?:#ord:|!spoken:(?:number|ordinal):)','#',atom.atom).rstrip(',.') if atom.kind in ('n','p') else atom.atom


def _resume_atoms(text):
    """The atoms of ``text`` as ``match_current`` reads them, brackets and the like left out; «с»/«со» after a number is the preposition here (the ear writes
    «трёх со дня», the portion «51: с расчётного»): seconds are said as a word."""
    atoms=_units(_without_hesitations(_canonical(text,(),True)))
    return tuple(Atom('с',atom.surface,'w') if atom.kind=='u' and atom.surface in ('с','со') else atom for atom in atoms if not atom.atom.startswith('!symbol:'))


def _protected_atom(atom):
    """A number (in a run the reader would not sum too: «ноль, десять»), a scale word, a unit, a sign, «не»/«ни»: matched by value or not at all."""
    return atom.kind in ('n','u') or atom.atom.startswith('!spoken:') or atom.atom in ('не','ни','тысяча','миллион','миллиард','рубль','копейка','доллар','евро') or (atom.kind=='p' and not atom.atom.startswith('!'))


def _resume_like(heard,own):
    """0 the same, 0.3 the same word misheard (another ending, a garbled or a lost head), None another word. Numbers and «не» only by value."""
    if _resume_value(heard)==_resume_value(own):return 0.0
    a,b=heard.surface,own.surface
    if (own.kind=='u' or own.atom in ('рубль','копейка','доллар')) and heard.kind=='w' and b.isalpha() and len(os.path.commonprefix((a,b)))>=max(4,min(6,len(b)-1)):
        return 0.3      # «процентове» of «процентов», «плюса» of «плюс»: the unit's word misheard, never another unit
    if _protected_atom(heard) or _protected_atom(own) or heard.kind!='w' or own.kind!='w':return None
    if len(a)>=5 and b.endswith(a) and len(b)-len(a)<=3:return 0.3      # the head lost («конных» of «законных», «звание» of «название»): the ear's, whatever word it makes
    if _known_word(a) and _lemma(a)!=_lemma(b):return None      # «налоговые» is not «налога»: a word of the language with another lemma is another word
    if min(len(a),len(b))==3 and abs(len(a)-len(b))==1 and (a.startswith(b) or b.startswith(a)):return 0.3      # «всеу» of «все»
    if min(len(a),len(b))<4:return None
    from rapidfuzz.distance import Levenshtein
    if Levenshtein.distance(a,b)==1 and a[:2]==b[:2]:return 0.3        # «еслу» of «если»
    common=len(os.path.commonprefix((a,b)))
    if common>=4 and common>=min(len(a),len(b))-2:return 0.3        # another case, another ending
    return 0.3 if len(a)>=5 and Levenshtein.normalized_similarity(a,b)>=0.75 else None


def _may_grow(heard,own):
    """A number not finished: «девятьсот» of 988, «тысяча» of 1941."""
    a,b=_resume_value(heard),_resume_value(own)
    if not (a.startswith('#') and b.startswith('#') and a[1:].isdigit() and b[1:].isdigit()):return False
    x,y=a[1:],b[1:]
    if int(x)>=int(y):return False
    if len(x)==len(y) and y.startswith(x.rstrip('0')):return True
    return int(x)%1000==0 and int(x)<int(y)<int(x)+1000


def _cheap(atoms,i,own):
    """An added word that costs almost nothing: a filler the portion does not have, a stutter (the head of the next word), a word said twice."""
    atom=atoms[i]
    if atom.kind=='w' and atom.surface in _RESUME_CHEAP and atom.surface not in own:return True      # «это» is a filler when the portion has «этим», not «это»
    if i and _resume_value(atoms[i-1])==_resume_value(atom):return True
    nxt=next((later.surface for later in atoms[i+1:] if later.surface!=atom.surface),'')
    parts=[part for part in _HYPHEN.split(atom.surface) if part]
    return atom.kind in ('w','n','p') and atom.surface.isalpha() and bool(nxt) and bool(parts) and all(nxt.startswith(part) and len(part)<len(nxt) for part in parts)


RESUME_HEAD_SKIP=0.4
RESUME_HIT=0.6      # a word of the portion said is worth this much: the ear's lost head words («после сброса») are not cheaper than the words that follow them


def _cut_off(heard,own):
    """F11: the last word heard is the head of the portion's word, cut off («установ» of «установления»): the word they are on, not a word said. A word of its own
    («на» of «налога») is a word said."""
    a,b=heard.surface,own.surface
    if heard.kind!='w' or own.kind!='w' or len(b)-len(a)<2 or len(a)<2 or not b.startswith(a):return False
    return len(a)>=3 and (not _known_word(a) or len(b)-len(a)>=3)


_RESUME_ASKS=frozenset('что как какой какая какое какие почему зачем где когда сколько кто ли чем чего куда откуда'.split())


def _late_start(said,own,hits,before):
    """A retelling that lost the head of the portion («приняты деньги» of «Также от кого приняты деньги…»): the place stands on two words of the portion said in a row, or one
    word of five letters and more the portion has once, after nothing but fillers. A question word of the listener's own before them is a question, not a start."""
    if any(said[i].surface in _RESUME_ASKS for i in range(hits[0][0])):return False
    run=all(b[0]==a[0]+1 and b[1]==a[1]+1 for a,b in zip(hits,hits[1:]))
    if len(hits)>=2 and run:return True
    atom=own[hits[0][1]]
    return len(hits)==1 and not before and len(atom.surface)>=5 and sum(1 for other in own if other.atom==atom.atom)==1


def resume_word(heard,portion):
    """``(the rest of the portion from the word the listener stopped before, whether words were said twice)``, or None when ``heard`` is no start of ``portion``.
    One rule, R07's (``tests/helpers_r07_tail``: never a cue after a word not said right): only the noise of the ear and of a stall is forgiven (another
    ending, a garbled or cut word, a lost head of a word, a stutter, a filler, a word said again, the portion's opening «и»/«а»); a word left out, one of
    their own or another order is no start (None), nor is a retelling."""
    if not isinstance(heard,str) or not isinstance(portion,str) or not heard.strip() or max(len(heard),len(portion))>2000:return None
    try:
        folded=heard.casefold().replace('ё','е')
        heard=_RESUME_STUTTER.sub(lambda hit:' '.join(_HYPHEN.split(hit.group())),_RESUME_BLANK.sub('',_RESUME_STUTTER_HEAD.sub('',folded)))
        heard=re.sub(r'(?<![\d\s])(\d+)(?:\s+\1)+(?!\d)',lambda hit:hit.group(1) if hit.group() not in portion else hit.group(),' '+heard)      # «430 430»: one number said twice, not 430 430
        said,own=_resume_atoms(heard),_resume_atoms(portion)
        if not said or len(own)<2 or max(len(said),len(own))>80:return None
        words={atom.surface for atom in own}
        cheap=[_cheap(said,i,words) for i in range(len(said))]
        n,m=len(said),len(own)
        INF=(1e9,0)
        best=[[INF]*(m+1) for _ in range(n+1)];step=[[None]*(m+1) for _ in range(n+1)]
        best[0][0]=(0.0,0)
        for i in range(n+1):
            for j in range(m+1):
                cost,hits=best[i][j]
                if cost>=1e9:continue
                moves=[]
                if j<m:moves.append((i,j+1,RESUME_HEAD_SKIP if not hits and not _protected_atom(own[j]) else 1.0,0,'skip'))      # the head of the portion left out by a retelling costs less than a word left out inside
                if i<n:moves.append((i+1,j,0.25 if cheap[i] else 1.0,0,'add'))
                if i<n and j<m:
                    like=None if i==n-1 and _cut_off(said[i],own[j]) else _resume_like(said[i],own[j])
                    if like is not None:moves.append((i+1,j+1,like-RESUME_HIT*(2 if own[j].kind=='w' and len(own[j].surface)>=6 else 1),1,'same'))      # a long word of the portion is worth two skipped
                    elif i==n-1 and (_may_grow(said[i],own[j]) or _cut_off(said[i],own[j])):moves.append((i+1,j+1,0.3-RESUME_HIT,1,'cut'))
                    elif said[i].kind=='w' and own[j].kind=='w' and not _protected_atom(said[i]) and not _protected_atom(own[j]):
                        moves.append((i+1,j+1,1.0,0,'other'))
                    else:moves.append((i+1,j+1,1.0,0,'wrong'))
                for a,b,c,h,kind in moves:
                    key=(cost+c,hits+h)
                    if (key[0],-key[1])<(best[a][b][0],-best[a][b][1]):best[a][b]=key;step[a][b]=(i,j,kind)
        end=min(range(m+1),key=lambda j:(best[n][j][0],-best[n][j][1],-j))
        path=[];i,j=n,end
        while (i,j)!=(0,0):
            pi,pj,kind=step[i][j];path.append((pi,pj,kind));i,j=pi,pj
        path.reverse()
        hits=[(i,j,kind) for i,j,kind in path if kind in ('same','cut')]
        content=sum(1 for i in range(n) if not cheap[i])
        before=[i for i,j,kind in path if kind=='add' and hits and i<hits[0][0] and not cheap[i]]
        if not hits or 2*len(hits)<content or len(before)>2 or (hits[0][1]>2 and not _late_start(said,own,hits,before)) \
                or (len(hits)==1 and content>1 and hits[0][1]>0 and not (content==2 and hits[0][1]==1 and hits[0][0]==n-1)):      # one word of the portion after one of its own: the ear's word for the portion's first
            # no start by the alignment: a retelling may still end on the portion's own words, in a row, found once (``_anchored``), when half of what was said is the portion's
            if any(atom.surface in _RESUME_ASKS for atom in said):return None
            at=_anchored(said,own,cheap,path,[(-1,-1,'')],0)
            run=sum(1 for i in range(n) if i>=n-4 and _resume_value(said[i]) in {_resume_value(atom) for atom in own[:at]})
            return _rest(portion,own,at,said,cheap,path) if at and 2*(run+sum(1 for i,j,kind in hits if i<n-4))>=content else None
        at=hits[-1][1]+(0 if hits[-1][2]=='cut' or (hits[-1][0]==n-1 and _resume_like(said[-1],own[hits[-1][1]])) else 1)      # R07: the last word heard otherwise («росии») is the word they are on: it is cued again
        if any(kind=='skip' and _protected_atom(own[j]) for i,j,kind in path[:path.index(hits[0])]):return None      # a start past a number or a «не» of the head is no start: the whole portion
        last=path.index(hits[-1])
        if len(hits)>1 and last and path[last-1][2]=='skip' and len(own[hits[-1][1]].surface)==1:
            at=next(j for i,j,kind in reversed(path[:last]) if kind!='skip')+1 if any(kind!='skip' for i,j,kind in path[:last]) else 0      # «…деятельности и» for «…деятельности государства и»: the ear adds «и», «а», «в»; a word said again is better than a word passed over
        first=path.index(hits[0])
        if any(kind=='skip' and own[j].atom not in _OPTIONAL_LEADING for i,j,kind in path[:first]) or any(kind in ('other','wrong') or (kind=='skip' and j<at) or (kind=='add' and not cheap[i]
               and _resume_value(said[i]) not in {_resume_value(atom) for atom in own[:j]}) for i,j,kind in path):return None
        return _rest(portion,own,at,said,cheap,path)
    except ImportError:
        return None


def _rest(portion,own,at,said,cheap,path):
    """``(the portion from its atom ``at``, whether words were said twice)``, or None when ``at`` is its start or its end."""
    if not 0<at<len(own):return None
    twice=any(kind in ('add','other') and ((cheap[i] and i and _resume_value(said[i-1])==_resume_value(said[i])) or _resume_value(said[i]) in {_resume_value(own[k]) for k in range(at)}) for i,j,kind in path)
    text=numbers.merge_digit_groups(unicodedata.normalize('NFC',portion).casefold().replace('ё','е'))
    if len(text)!=len(portion):text=portion.casefold().replace('ё','е')
    spot=0;start=None
    for index,atom in enumerate(own):
        for piece in atom.surface.split():
            found=re.compile(r'[\s-]*'.join(map(re.escape,piece))).search(text,spot)
            if found is None:return None
            if start is None and index==at:start=found.start()
            spot=found.end()
        if index==at:break
    if start is None or start>=len(portion):return None
    while start and not portion[start-1].isspace() and (portion[start-1] in _RESUME_OPEN or portion[start-1].isalnum()):start-=1      # the whole word: «B2», never «2»
    return portion[start:],twice


def _anchored(said,own,cheap,path,hits,at):
    """A retelling that left out words inside (``at``: where the alignment stopped): the last two to four words heard, all the portion's, in a row, a word of four letters
    and more among them, found once in the portion after ``at``, with no number, unit or «не» passed over in between nor said otherwise after the alignment's last word:
    the place is after them («…вещь на них не» of «…случаев на производстве, налоговое законодательство на них не»)."""
    n=len(said);values=[_resume_value(atom) for atom in own];last=hits[-1][0]
    for size in (4,3,2):
        if n-size<0 or any(cheap[n-size:]):continue
        run=[_resume_value(atom) for atom in said[n-size:]]
        spots=[p for p in range(len(own)-size+1) if values[p:p+size]==run]
        if len(spots)!=1 or spots[0]+size<=at or not (size>=3 or any(atom.kind=='w' and len(atom.surface)>=4 for atom in said[n-size:])):continue
        if any(_protected_atom(atom) for atom in own[at:spots[0]]) or any(_protected_atom(said[i]) and not cheap[i] for i in range(last+1,n-size)):continue
        return spots[0]+size
    return at
