"""Pure text helpers shared by the portioner, the turn classifier and the engine.

Everything here is deterministic and free of I/O. Words are the Unicode words of
``WORDS``; ``normalize`` is the one comparison form used for acknowledgements.
"""
from __future__ import annotations

import collections
import functools
import logging
import re
import threading
import unicodedata

from .user_intents import HESITATION_WORDS

logger = logging.getLogger('echo-sync')

WORDS = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.UNICODE)
_PARTS = re.compile(r"[-’']")


def normalize(text):
    return ' '.join(WORDS.findall(unicodedata.normalize('NFKC', str(text or '')).casefold().replace('ё', 'е')))


def destutter(text):
    """h27: a stammer the cloud wrote down: «Ч-что такое финансы» is «что такое финансы» (the call of 16:06: no question, no answer). A doubled word («то-то», «еле-еле») stays."""
    return re.sub(r'\b([а-яё]{1,2})-(?=\1[а-яё])', '', str(text), flags=re.I)


def norm_words(text):
    return normalize(text).split()


def compact_spoken_definition(text):
    """Omit an optional initial Russian copula in paraphrased spoken prose.

    Not for verbatim/source quotations. Only the word after an initial dash
    is omitted; negation, quantities, the subject and predicate stay intact.
    An unfinished token is retained until its following space is received.
    """
    text=str(text)
    if text.lstrip().startswith(('«','“','"',"'")):return text
    return re.sub(r'^([^\n.!?—]{1,80}—\s*)это\s+',r'\1',text,count=1,flags=re.I)


def definition_body(text,question):
    """Elide only an exact echoed subject in an explicit definition question.

    Holds a growing multiword subject until the predicate arrives. No fuzzy
    matching or fact substitution; quoted/nondefinition text stays intact.
    """
    text=str(text).strip()
    if text.startswith(('«','“','"',"'")):return text
    query=re.match(r'^\s*(?:а\s+)?что\s+такое\s+(.+?)\s*[?!.]*\s*$',str(question),re.I)
    if not query:return text
    expected=norm_words(query.group(1));heard=norm_words(text)
    if not expected or not heard:return text
    expected_text=' '.join(expected);heard_text=' '.join(heard)
    if expected_text.startswith(heard_text):return ''
    count=len(expected);matches=list(WORDS.finditer(text))
    if heard[:count]!=expected or len(matches)<=count:return text
    gap=text[matches[count-1].end():matches[count].start()]
    copula=heard[count]=='это'
    if not copula and not any(c in gap for c in ':—–') and not re.search(r'\s-\s',gap):return text
    first=count+1 if copula else count
    if len(matches)<=first:return ''
    return text[matches[first].start():]


def _words(text):
    return frozenset(normalize(text).split())


# --- Russian stems -----------------------------------------------------------

_stem_lock = threading.Lock()  # a Snowball stemmer object keeps per-call state
_stemmer = None
_stemmer_missing = False


def _get_stemmer():
    global _stemmer, _stemmer_missing
    if _stemmer is None and not _stemmer_missing:
        try:
            import snowballstemmer
            _stemmer = snowballstemmer.stemmer('russian')
        except Exception:
            _stemmer_missing = True
            logger.warning('snowballstemmer is not installed; stem matching falls back to exact words')
    return _stemmer


@functools.lru_cache(maxsize=65536)
def stem(word):
    with _stem_lock:
        stemmer = _get_stemmer()
        return stemmer.stemWord(word) if stemmer else word


def stems(words):
    """Stems of normalized words. A hyphenated compound is compared part by part."""
    return [stem(part) for word in words for part in _PARTS.split(word) if part]


# --- syllables ---------------------------------------------------------------

_RUNS = re.compile(r'\d+|[^\W\d_]+')
_VOWELS = frozenset('аеёиоуыэюя' + 'aeiouy')
_AFTER_NUMBER = re.compile(r'\s?[%°₽$€£¥]')
_BEFORE_NUMBER = re.compile(r'[$€₽£№§]\s?$')


def _letter_syllables(run):
    vowels = sum(1 for c in run.casefold() if c in _VOWELS)
    n = len(run)
    if n >= 2 and run.isupper():
        # An ALL-CAPS abbreviation: spelled by letters (ВВП, УК, РФ) unless it
        # clearly reads as a word (НАТО, ГОСТ, ЕГЭ).
        return n if n <= 2 or vowels == 0 or vowels * 4 < n else vowels
    if vowels == 0:
        return 1 if n >= 2 else 0  # a lone consonant (в, к, с) leans on the next word
    return vowels


def _digit_syllables(run):
    return max(1, round(2.2 * len(run)))  # spoken numbers: 15 ~ 4, 228 ~ 7, 2026 ~ 9


def word_syllables(word):
    """Syllables of one word: vowels, ALL-CAPS abbreviations by letters, digits as a rough estimate."""
    return sum(_digit_syllables(run) if run.isdigit() else _letter_syllables(run) for run in _RUNS.findall(word))


def symbol_syllables(text, start, end):
    """Extra syllables for the spoken '%', '°' or a currency sign after a number and a currency sign or '№' before it."""
    extra = 3 if _AFTER_NUMBER.match(text, end) else 0
    if _BEFORE_NUMBER.search(text[max(0, start - 2):start]):
        extra += 2
    return extra


def syllables(text):
    text = str(text or '')
    total = 0
    for match in WORDS.finditer(text):
        word = match.group()
        total += word_syllables(word)
        if any(c.isdigit() for c in word):
            total += symbol_syllables(text, match.start(), match.end())
    return total


# --- word classes -------------------------------------------------------------

PREPOSITIONS = _words(
    'в во на с со к ко по о об обо от ото из изо за для до при про над под подо перед передо пред между через '
    'сквозь без безо у ради около возле вокруг среди после кроме вместо против напротив посреди внутри вне вдоль '
    'мимо благодаря согласно относительно помимо спустя ввиду насчёт из-за из-под')
CONJUNCTIONS = _words(
    'и а но да или либо ни что чтобы чтоб как когда если хотя пока потому поскольку так также зато однако '
    'причём притом будто словно чем нежели едва пусть пускай где куда откуда зачем почему отчего ибо')
PARTICLES = _words('не ни бы ли же ведь вот вон даже лишь только именно уж хоть разве неужели мол давай давайте то')
# R21-09: the same for English (a question may be asked in English): «recording a call without | the consent», «wrote War and Peace in | the sixties».
# Latin letters only, so no Russian word is ever one of them. Not part of FUNCTION_WORDS (the utterance logic of ControlledMedia reads that one): the
# portioner and the first cue add them themselves.
LATIN_FUNCTION_WORDS = _words(
    'a an the of in on at by for with without from to into onto about as and or but nor if that than then so such this these those it its their '
    'his her our your my per via over under between through during after before against among within upon not no '
    'below above across along around near beyond behind beside toward towards until unless while when where whether because')
# A portion must not end on one of these: the listener would be left with half a phrase.
FUNCTION_WORDS = PREPOSITIONS | CONJUNCTIONS | PARTICLES
# "в течение", "в связи с", "с точки зрения": the noun is part of the preposition.
LOCUTION_TAILS = _words(
    'течение связи целях качестве случае отношении рамках результате ходе мере счёт области точки зрения '
    'основании основе помощью сравнению соответствии пределах течении отличие зависимости направлении силу пользу причине')
# W1F-A: words that need the word after them, their HEAD, the way a preposition does - a portion that ends on one leaves half a
# phrase («У Меркурия почти», «Сапсан — самый», «масса — это,»). Unlike FUNCTION_WORDS they are no hard glue of the planner (the
# syllable bounds win, portioner._head_marks), and punctuation after one frees it («Нет, звук…»), except after a copula.
DEGREE_WORDS = _words('почти более менее очень совсем слишком чуть примерно приблизительно весьма крайне довольно наиболее наименее')
EXISTENTIALS = _words('нет есть')
COPULAS = _words('это является являются представляет представляют')
HEAD_DETERMINERS = _words(
    'самый самая самое самые самого самой самому самым самом самых самую такой такая такое такие такого такому таким таком '
    'таких такую этот эта эти этого этой этому этим этом этих эту который которая которое которые которого которой которому '
    'которым котором которых которую')
LATIN_COPULAS = _words('is are was were be been am will would can could may might should must does did has have had')   # R21-09: «The speed of light is | about …»
MODALS = _words('нельзя можно нужно надо необходимо следует должен должна должно должны')      # R21-07: «нельзя | оставлять», «нужно | охлаждать»
NEEDS_HEAD = DEGREE_WORDS | EXISTENTIALS | COPULAS | HEAD_DETERMINERS | LATIN_COPULAS | MODALS
# Words that say nothing about the topic: never evidence that an utterance is an attempt at a portion.
STOPWORDS = FUNCTION_WORDS | _words(
    'я ты он она оно мы вы они мне тебе ему ей нам вам им меня тебя его её нас вас их мой моя моё мои твой наш '
    'наша наше наши ваш ваша ваше ваши свой своя своё свои это этот эта эти тот та те такой такая такое такие '
    'весь вся всё все всех всем всего себя себе собой есть быть был была было были будет будут можно нужно надо '
    'очень тоже ещё уже тут там здесь сейчас теперь потом тогда да нет ну ага угу')

# The stock iPhone client (Conduit) handles these WHOLE utterances itself and never sends them to the
# server. "Stop" silences the voice, "End" closes the entire voice session. A portion the user has to
# repeat aloud must therefore never be exactly one of them: the portioner merges it with a neighbour.
CONDUIT_STOP_PHRASES = ('стоп', 'хватит', 'замолчи', 'тише')
CONDUIT_END_PHRASES = ('пока', 'до свидания', 'закончить разговор', 'это всё')
CONDUIT_LOCAL_PHRASES = frozenset(normalize(phrase) for phrase in CONDUIT_STOP_PHRASES + CONDUIT_END_PHRASES)
# The same phrase with a filler before or after it («Ну, пока.», «Стоп, пожалуйста.») or said twice («Стоп, стоп.») is
# as good as the bare phrase for the listener who has to repeat it aloud: it is not certain that the phone lets it through.
PHONE_PHRASE_FILLERS = frozenset(normalize(word) for word in
                                 'ну так вот итак ладно хорошо окей ок пожалуйста же уж да ага угу все'.split())


def phone_phrase(text):
    """The Stop/End phrase (normalized) that ``text`` is, or essentially is (a filler around it, or the phrase said
    twice or more in a row), else ``None``. A phrase inside a longer sentence («Пока не поздно») is not one."""
    words = normalize(text).split()
    for phrase in sorted(CONDUIT_LOCAL_PHRASES):
        part = phrase.split()
        size = len(part)
        for start in range(len(words) - size + 1):
            if words[start:start + size] != part:
                continue
            end = start + size
            while words[end:end + size] == part:       # said twice or more in a row
                end += size
            if all(word in PHONE_PHRASE_FILLERS for word in words[:start] + words[end:]):
                return phrase
    return None


def is_phone_phrase(text):
    return phone_phrase(text) is not None

UNIT_EXACT = _words(
    'г гг кг км м см мм л мл т ч мин сек шт чел руб коп тыс млн млрд трлн проц га вт квт мвт гц кб мб гб тб раз раза '
    'января февраля марта апреля мая июня июля августа сентября октября ноября декабря '
    'час часа часов часу часы день дня дню днём дне дни дней лет век века веке веку веком веков веках')
UNIT_PREFIXES = (
    'год', 'месяц', 'недел', 'минут', 'секунд', 'процент', 'рубл', 'копе', 'тысяч', 'миллион', 'миллиард', 'триллион',
    'доллар', 'евро', 'килограмм', 'грамм', 'тонн', 'километр', 'метр', 'литр', 'градус', 'штук', 'человек', 'балл',
    'единиц', 'страниц', 'пункт', 'килокалор',
    # units a voice answer uses that the first lexicon missed («250 миллилитров», «10 ватт», «10 суток», «2,5 гигабайта»)
    'миллилитр', 'миллиграмм', 'сантиметр', 'миллиметр', 'дециметр', 'гектар', 'центнер', 'дюйм', 'килобайт', 'мегабайт',
    'гигабайт', 'терабайт', 'байт', 'ватт', 'киловатт', 'мегаватт', 'вольт', 'ампер', 'герц', 'килогерц', 'мегагерц',
    'гигагерц', 'ньютон', 'джоул', 'паскал', 'калори', 'сут', 'оборот', 'мегапиксел')
# A number written in words, every form a transcript can hold (cases of the cardinals), ё folded into е.
NUMBER_WORDS = _words(
    'ноль нуль ноля нуля один одна одно одни одного одной одному одним одном одну два две двух двум двумя '
    'три трёх трём тремя четыре четырёх четырём четырьмя пять пяти пятью шесть шести шестью семь семи семью '
    'восемь восьми восемью девять девяти девятью десять десяти десятью одиннадцать одиннадцати одиннадцатью '
    'двенадцать двенадцати двенадцатью тринадцать тринадцати тринадцатью четырнадцать четырнадцати четырнадцатью '
    'пятнадцать пятнадцати пятнадцатью шестнадцать шестнадцати шестнадцатью семнадцать семнадцати семнадцатью '
    'восемнадцать восемнадцати восемнадцатью девятнадцать девятнадцати девятнадцатью двадцать двадцати двадцатью '
    'тридцать тридцати тридцатью сорок сорока пятьдесят пятидесяти пятьюдесятью шестьдесят шестидесяти шестьюдесятью '
    'семьдесят семидесяти семьюдесятью восемьдесят восьмидесяти восемьюдесятью девяносто девяноста '
    'сто ста двести двухсот двумстам двумястами триста трёхсот трёмстам тремястами четыреста четырёхсот четырёмстам '
    'четырьмястами пятьсот пятисот пятистам пятьюстами шестьсот шестисот шестистам шестьюстами семьсот семисот '
    'семистам семьюстами восемьсот восьмисот восьмистам восемьюстами девятьсот девятисот девятистам девятьюстами '
    'полтора полторы полутора полтораста')
# Abbreviations whose period is not the end of a sentence even when a capital letter follows («тыс. Человек» is rare;
# «и т. д. Затем» is not): the planner neither takes a sentence break there nor lets a cue end there.
ABBREVIATIONS = _words('тыс млн млрд трлн руб коп проф акад стр напр т д е п н э г гг в вв')
SCALE_WORDS = _words('тыс тысяча тысячи тысяч млн миллион миллиона миллионов млрд миллиард миллиарда миллиардов трлн '
                     'триллион триллиона триллионов')
_LABEL = re.compile(
    r'^(?:стать(?:я|и|е|ю|ей)|ст|пункт(?:а|у|ом|е|ы|ов)?|п|подпункт(?:а|у|ом|е)?|част(?:ь|и|ью)|ч|глав(?:а|ы|е|у|ой)|'
    r'раздел(?:а|у|ом|е|ы)?|параграф(?:а|у|ом|е)?|номер(?:а|у|ом|е)?|страниц(?:а|ы|е|у|ей)|стр|рисун(?:ок|ка|ку|ком|ке)|'
    r'рис|таблиц(?:а|ы|е|у|ей)|табл|приложени(?:е|я|ю|ем|и)|пример(?:а|у|ом|е)?|схем(?:а|ы|е|у|ой)|'
    r'график(?:а|у|ом|е)?|формул(?:а|ы|е|у|ой)|закон(?:а|у|ом|е)?|гост)$')


def is_unit(norm):
    return norm in UNIT_EXACT or norm.startswith(UNIT_PREFIXES)


def is_label(norm):
    return bool(_LABEL.match(norm))


# What the model says before the answer while it "works": «Сейчас проверю.», «Понял, сейчас быстро проверю и скажу.»,
# «Секунду, сейчас найду информацию.», «Хороший вопрос.», «Один момент.», «Подождите секунду.», «Хмм, дайте проверить.».
# Words that open such a sentence or fill the pause (a hesitation sound is one of them: the list the classifier skips):
_HESITATION='|'.join(sorted((re.escape(word) for word in HESITATION_WORDS),key=len,reverse=True))
_ACK=(rf'(?:да|хорошо|ладно|так|ну|итак|понял|поняла|понятно|ясно|принято|принял|окей|ок|конечно|разумеется|ага|угу|спасибо|'
      rf'{_HESITATION})')
_PAUSE=r'(?:(?:одну\s+)?(?:секунду|секундочку|минуту|минутку|минуточку)|(?:один\s+)?момент)'
# W1F-A: «Понял, подождите, слушаю.»: a «подождите» between the acknowledgement and the stall opens it like a pause does
_LEAD=rf'(?:{_ACK}|{_PAUSE}|подожд(?:и|ите))'
_HURRY=r'(?:(?:быстро|сразу|ещё\s+раз|еще\s+раз|внимательно|тут\s+же|мигом)\s+)'
# «разложу (это) (по полочкам)», «объясню»: the promise of an explanation, not the explanation (W1F-A, w1_07 steps 3-4)
_EXPLAIN=r'(?:объясню|разложу|поясню|разберу)(?:\s+(?:это|всё|все))?(?:\s+по\s+полочкам)?'
_PROCESS_PREFIX=re.compile(
    rf'^(?:{_LEAD}[,\s]+)*(?:давай(?:те)?\s+)?(?:я\s+)?(?:сейчас[,\s]+)?{_HURRY}?'
    r'(?:(?:уточню|уточняю|проверю|проверяю|разберусь|ищу|сверю|сравню|сравниваю)(?=\W|$)'
    r'|(?:подожду|жду|ожидаю)\s+(?:проверк\w*|результат\w*|ответ\w*|данн\w*|источник\w*)(?=\W|$)'
    r'|(?:гермес|hermes)\s+(?:вернулся|ответил)(?=\W|$)'
    # Stalling and praise («Сейчас гляну.», «Посмотрю и скажу.», «Секунду.», «Понял.», «Давайте разберёмся.», «Хороший вопрос.»):
    # only when it is the WHOLE sentence, never the start of a real one («Давайте разберёмся, что такое масса.»,
    # «Скажу честно: ...», «Понятно, что вода кипит.»).
    rf'|(?:(?:гляну|посмотрю|посмотрим|найду|скажу|отвечу|подумаю|вспомню|расскажу|отвечаю)(?:\s+и\s+(?:скажу|отвечу|расскажу|сообщу))?'
    rf'|{_PAUSE}|(?:понял|поняла|понятно|ясно|принято|принял)|{_HESITATION}|подожд(?:и|ите)(?:\s+{_PAUSE})?'
    rf'|слушаю(?:\s+(?:вас|тебя))?|{_EXPLAIN}'
    r'|дайте(?:[-\u2011]ка)?\s+(?:мне\s+)?(?:подумать|проверить|секунду|минуту)'
    r'|давайте\s+(?:разберёмся|разберемся|посмотрим|подумаем|(?:разложим|разберём|разберем)(?:\s+(?:это|всё|все))?(?:\s+по\s+полочкам)?)'
    r'|(?:очень\s+|довольно\s+)?(?:хороший|интересный|отличный|любопытный|непростой|сложный|важный)\s+вопрос)'
    r'(?=\s*(?:[.!?…]|$)))'
    # «сейчас» makes the verb an announcement for the rest of the sentence: «Секунду, сейчас найду информацию.»
    rf'|^(?:{_LEAD}[,\s]+)*(?:я\s+)?сейчас\s+{_HURRY}?(?:гляну|посмотрю|найду|скажу|отвечу|подумаю|вспомню|объясню|разложу|поясню)'
    r'(?=\W|$)',re.I)

# c25-b case 7: «Принял, посмотрю в базе.», «Смотрю в кодексе.», «Поищу в источниках.»: the place where the cloud looks, and nothing after it in the sentence, is the same announcement
_LOOK_WHERE=re.compile(
    rf'^(?:{_LEAD}[,\s]+)*(?:я\s+)?(?:сейчас\s+)?{_HURRY}?(?:посмотрю|гляну|смотрю|поищу|погляжу|проверю|уточню|найду)\s+(?:в|во|по|на)\s+(?:\w+\s+){{0,2}}?'
    r'(?:баз\w*|интернет\w*|источник\w*|кодекс\w*|закон\w*|документ\w*|справочник\w*|сет[иь]|поиск\w*|материал\w*|памят\w*|записях|заметк\w*)(?=\s*(?:[.!?…]|$))',re.I)

# «Хороший вопрос, ставка налога …»: praise before a comma or a dash is a preface, never the answer (the lookup case of 2 Nov, where
# «Хороший вопрос,» was dictated as the first portion). Only the praise and its comma go; the rest of the sentence stays.
_PRAISE_LEAD=re.compile(
    rf'^(?:(?:{_ACK})[,\s]+)*(?:очень\s+|довольно\s+)?(?:хороший|интересный|отличный|любопытный|непростой|сложный|важный|правильный|'
    r'классный|замечательный)\s+вопрос\s*[,—–-]\s*',re.I)
# «Привет!», «Здравствуйте!», «Чем могу помочь?» as a whole sentence at the start: a chat assistant's greeting, never a hint.
_CHAT_SENTENCE=re.compile(
    r'^(?:привет|здравствуйте|здравствуй|добрый\s+(?:день|вечер)|доброе\s+утро|чем\s+(?:я\s+)?могу\s+(?:вам\s+|тебе\s+)?помочь|'
    r'рад\s+помочь|с\s+удовольствием)\s*[.!?…]+\s*',re.I)
# W1F-A: a discourse acknowledgement before the answer («А, понял — Вторая началась…», «Ага.», «Угу,», «Понятно,», «Хорошо,», «Ясно —»,
# «Спасибо, понял,») is scaffolding like the praise lead (sc03: «А, понял —» was the first portion, the year came in portion 2).
# Never a predicate that opens a clause («Понятно, что…», «Хорошо, когда…»), never a word defined after a dash («Понял — это прошедшее время
# глагола.»). «Да» is an answer, not an acknowledgement. (An acknowledgement that is the WHOLE sentence - «Ага.», «Хорошо, спасибо.» - is not
# this lead's business: it is a sentence about the cloud's own state, ``_announces``, F3. «Согласен», «принял», «слышал» are NOT leads: «Согласен, если
# график известен заранее» is a stance, and cutting «Согласен,» turns an agreement into a bare condition - F3 fix round 1.)
_ACK_WORD=r'(?:ага|угу|понял|поняла|понятно|ясно|хорошо|ладно|окей|ок|принято|спасибо)'
_ACK_LEAD=re.compile(
    rf'^(?:а\s*,\s*)?{_ACK_WORD}(?:\s*,\s*{_ACK_WORD})*\s*(?:[,.!…]|[—–-](?!\s*это\b))+\s*'
    rf'(?=\S)(?!(?:что|как|когда|если|чтобы|где|куда|откуда|почему|зачем|ли)\b)(?!(?:{_ACK_WORD}[\s,.!…—–-]*)+$)',re.I)

# R21-12: «Конечно. «Евгения Онегина» написал Александр Пушкин.»: to a question that asks for a name, a number or a reason, «Конечно.» answers nothing and
# is no first portion. To a yes/no question it is the answer («Можно ли?» - «Конечно.»), so only a question with an interrogative word of its own strips it.
_AFFIRM_LEAD=re.compile(r'^(?:конечно|разумеется|безусловно|естественно|несомненно)\s*[,.!…]+\s*(?=\S)',re.I)
_WH_FIRST=re.compile(r'^\s*(?:а\s+|и\s+)?(?:кто|что|где|когда|почему|зачем|как|сколько|какой|какая|какое|какие|каков|чей|куда|откуда|который|которая)(?!\w)',re.I)

def _asks_a_word_first(question):
    return bool(_WH_FIRST.match(question)) and not re.search(r'(?<!\w)ли(?!\w)',question,re.I)

# --- F3: the cloud's sentences about its own actions -------------------------------------------------------------------------------------------
# The owner's call of 3 Nov 09:55: the model asks the client for a search for many turns (13 of 32) and says what it is doing while it waits -
# «Сейчас коротко сформулирую.» (cued twice, the owner repeated it), «Понял, гляну детали статьи.», «Слышу твою оценку, сейчас кратко отвечу на
# это.» - and the filter above knew a list of phrases. The class: a LEADING sentence that only announces the answer - its predicate a
# 1st-person-singular non-past verb of the act of answering (``ACT_LEMMAS``, both aspects; or an acknowledgement) - and adds nothing: no number the
# question does not have, no negation, no clause of its own (что, чтобы, если ...), no quotation, no noun but the act's own object
# (``META_NOUNS``: формулировка, дата, детали, оценка ...) or a word of the question, no pronoun but «это», «вам», «тебя». Judged by pymorphy3 (person,
# number, tense, part of speech); the lists are the CLOSED classes of the language (acknowledgements, manner adverbs, the nouns that name the act's
# product), never the sentences of one call. A leading sentence like that is stripped from the start of an answer; a reply made only of them is not an
# answer. «Я работаю бухгалтером», «Я считаю, что …», «Скажу честно: …», «Отвечаю на ваш вопрос: …» are content and stay.
_ACT_GROUPS=(
    'сформулировать формулировать', 'уточнить уточнять', 'глянуть глядеть поглядеть', 'проверить проверять', 'перепроверить перепроверять',
    'посмотреть смотреть', 'сказать говорить', 'ответить отвечать', 'объяснить объяснять', 'пояснить пояснять', 'рассказать рассказывать',
    'поискать искать', 'найти находить', 'отыскать отыскивать', 'подумать думать', 'обдумать обдумывать', 'подстроиться подстраиваться',
    'вспомнить вспоминать', 'разобраться разбираться', 'разобрать разбирать', 'посчитать', 'подсчитать', 'пересчитать', 'вычислить',
    'рассчитать', 'прикинуть', 'перевести', 'подсказать подсказывать', 'сообщить сообщать', 'назвать называть', 'изложить излагать',
    'описать описывать', 'повторить повторять', 'вернуться возвращаться', 'продолжить продолжать', 'начать начинать', 'подготовить готовить',
    'подобрать подбирать', 'выяснить выяснять', 'узнать узнавать', 'сверить сверять', 'свериться', 'перефразировать', 'упростить упрощать',
    'сократить сокращать', 'дать', 'проанализировать анализировать', 'исправиться', 'заглянуть заглядывать', 'прочитать прочесть перечитать')
# Verbs that acknowledge the listener («Слышу твою оценку», «Принимаю», «Учту»), and the verbs that only carry another one («Буду отвечать коротко»).
_ACK_VERB_GROUPS=(
    'слышать', 'понимать понять', 'видеть', 'принимать принять', 'соглашаться согласиться', 'учесть учитывать', 'запомнить запоминать',
    'благодарить поблагодарить', 'извиняться извиниться')
_LINK_GROUPS=('быть', 'мочь смочь', 'хотеть', 'постараться стараться', 'попробовать пробовать', 'собираться')
ACT_LEMMAS=_words(' '.join(_ACT_GROUPS))
ACK_VERB_LEMMAS=_words(' '.join(_ACK_VERB_GROUPS))
LINK_LEMMAS=_words(' '.join(_LINK_GROUPS))
# lemma -> the first lemma of its group: «подготовите» in a question and «подготовлю» in an answer are the same predicate
_ASPECT_KEY={lemma:normalize(group).split()[0] for group in _ACT_GROUPS+_ACK_VERB_GROUPS+_LINK_GROUPS for lemma in normalize(group).split()}
# Acknowledgements as words («Понял», «Угу», «Хорошо», «Спасибо»; «Согласен», «принял», «слышал» only as a whole sentence). «Да» is NOT one: it
# is an answer like «нет», and «Думаю, да.» is the answer, not a stall - F3 fix round 1. Nor «Конечно», «Верно».
ACK_WORDS=_words('понял поняла понятно ясно угу ага хорошо ладно окей ок принято принял приняла услышал услышала слышал слышала спасибо согласен согласна')
FILLER_WORDS=_words('ну так итак вот же уж ещё тоже также тут тогда теперь сейчас щас потом затем сразу сначала и а то значит')|HESITATION_WORDS
PAUSE_WORDS=_words('секунду секундочку минуту минутку минуточку момент подожди подождите погоди погодите постой постойте')
# How the act is done: not what is said («честно», «прямо» take a stand and are content).
DELIVERY_WORDS=_words(
    'коротко кратко быстро подробно подробнее просто четко аккуратно внимательно заново снова ровно раз короче кратче проще яснее точнее быстрее '
    'ровнее понятнее четче вкратце иначе по-другому по-простому покороче попроще получше')
CLAUSE_WORDS=_words('что чтобы чтоб как когда где куда откуда почему зачем если пока хотя потому поскольку ли кто чей сколько либо или')
CLAUSE_LEMMAS=_words('который какой каков чей кто сколько')
NEGATION_WORDS=_words('не ни нет никто ничего никогда нигде никак никуда нельзя')
DEMONSTRATIVES=_words('это этого этому этим этом то того тому тем том всё все всем всего себя себе')
ADDRESSEE_DAT=_words('вам тебе')
ADDRESSEE_ACC=_words('вас тебя')
# The nouns that name the product of the act or the slot the answer fills («Уточню дату», «Проверю цифры», «Подберу формулировку», «Слышу твою
# оценку», «по делу», «детали статьи»). «вопрос» is NOT one: «Отвечаю на ваш вопрос: …» is a pinned sentence that stays; nor a document, a source, a text,
# a code: «Посмотрю документы.» to «Что вы сделаете первым делом?» is an answer.
META_NOUNS=_words(
    'ответ формулировка вариант версия суть существо дело деталь подробность нюанс информация данные сведение дата год число цифра значение название '
    'имя номер термин определение объяснение пояснение описание оценка мнение замечание просьба критика пожелание тема момент секунда минута мысль '
    'статья '
    # c7-meta round 2: «Сделаю пример понятным», «добавлю наглядный пример», «Разложу по шагам» - the example, its steps are the product
    # of the act, as the wording is
    'пример шаг')
# The adjectives that say how the product of the act is («Дам краткий ответ», «Подберу точную формулировку»); a pronominal one («твою», «эту», «любой»)
# and the question's own are allowed too. Any other is a claim, or a noun in disguise: «Найду производную по определению.» stays.
META_ADJECTIVES=_words('краткий короткий точный полный подробный нужный верный правильный окончательный ясный четкий понятный простой быстрый необходимый конкретный общий '
                       'наглядный')                 # c7-meta round 2: «добавлю наглядный пример»
_ACK_ONLY_WORDS=ACK_WORDS|FILLER_WORDS|PAUSE_WORDS|ADDRESSEE_DAT|ADDRESSEE_ACC|frozenset({'я','один','одну'})
_MAX_ANNOUNCEMENT_WORDS=16
_QUOTE_OR_SYMBOL=re.compile(r'[«»“”„"%№§$€₽°#@=+*<>/\\]')
_SENTENCE_END=re.compile(r'(?<!\d)[.!?…]+(?!\d)|\n')
_DIGIT_SENTENCE_END=re.compile(r'(?<=\d)[.!?…]+(?=\s+[А-ЯЁ]|\s*$)')
# Where an announcement ends inside its sentence and the content begins: «Скажу так: …», «Скажу так — …».
_ANNOUNCE_BREAK=re.compile(r':(?=\s|$)|\s[—–-]\s')
_Facts=collections.namedtuple('_Facts','known act ack link infn clause number noun noun_lemmas adj apro keys promise doing verb')
# c8b (the owner's call of 3 Nov 20:10: «Сверяю формулировку пятнадцатой статьи НК РФ.» cued twice): an abbreviation in capitals (НК, РФ, ФНС) right
# after the act's object or a word of the question names where that object is (``_announces``): «статьи НК РФ» is the question's own article.
_ABBREVIATION=re.compile(r'^[А-ЯЁA-Z]{2,5}$')


def _morph():
    """The shared pymorphy3 module of ru_alignment (its analyzer and lock), or ``None`` when it is not there: the class is then off and the
    phrase filter above is all there is."""
    try:
        from . import ru_alignment as ru
        ru._lemma('да')                                   # builds the shared analyzer behind its lock
        return ru if ru._MORPH is not None else None
    except Exception:
        return None


@functools.lru_cache(maxsize=32768)
def _facts(word):
    """What pymorphy3 says of one normalized word, as far as the class needs it."""
    ru=_morph()
    try:
        with ru._LOCK:
            known=ru._MORPH.word_is_known(word)
            parses=ru._MORPH.parse(word)
    except Exception:
        # A character pymorphy3 cannot describe (a Tangut letter: unicodedata.name fails) must never raise into the wire reader: the word is
        # nothing the class knows, so a sentence with it is content.
        return _Facts(False,False,False,False,False,False,False,False,frozenset(),'',False,frozenset(),False,False,False)
    act=ack=link=infn=clause=promise=doing=False
    nouns=set();keys=set()
    for parse in parses:
        tag,lemma=parse.tag,parse.normal_form.replace('ё','е')
        if parse is parses[0] or parse.score>=0.15:keys.add(_ASPECT_KEY.get(lemma,lemma))
        if tag.POS=='VERB' and tag.person=='1per' and tag.number=='sing' and tag.tense in ('pres','futr') and tag.mood=='indc':
            act|=lemma in ACT_LEMMAS;ack|=lemma in ACK_VERB_LEMMAS;link|=lemma in LINK_LEMMAS
            # c7-meta round 2 (W4: «Сделаю пример понятным», «добавлю наглядный пример», «Секунду, подниму статью»): any 1st-person-singular
            # PERFECTIVE FUTURE is the form of a promise; the sentence is one only under every other condition of ``_announces``
            promise|=parse is parses[0] and tag.aspect=='perf' and tag.tense=='futr'
            # c8b: and any 1st-person-singular PRESENT («Сверяю …», «Изучаю …»): the act going on now, under the stricter conditions of ``_announces``
            doing|=parse is parses[0] and tag.tense=='pres'
        elif tag.POS=='INFN':infn|=lemma in ACT_LEMMAS
        elif tag.POS=='NOUN':nouns.add(lemma)
        clause|=lemma in CLAUSE_LEMMAS
    top=parses[0].tag
    adjective=top.POS=='ADJF' and 'Anum' not in top
    return _Facts(known,act,ack,link,infn,clause,top.POS=='NUMR' or 'Anum' in top,top.POS=='NOUN',frozenset(nouns),
                  parses[0].normal_form.replace('ё','е') if adjective else '','Apro' in top,frozenset(keys-META_NOUNS),promise,doing,
                  top.POS in ('VERB','INFN'))


# Words that never make a sentence "repeat the question": prepositions, demonstratives, the addressee, fillers, pauses, manner adverbs, numbers.
_NOT_CONTENT=PREPOSITIONS|DEMONSTRATIVES|ADDRESSEE_DAT|ADDRESSEE_ACC|FILLER_WORDS|PAUSE_WORDS|DELIVERY_WORDS|frozenset({'я','один','одну'})


def _is_number(word,facts):
    return any(c.isdigit() for c in word) or word in NUMBER_WORDS or facts.number


@functools.lru_cache(maxsize=512)
def _question_facts(question):
    """``(stems of the question's content words, its numbers, the lemma keys of its content words)``. A number of the question is no news in an
    announcement («Сейчас вспоминаю статью 218» to «статья 218»); a word of the question that the sentence repeats - its predicate (or the aspect pair
    of it), a noun, an adjective - makes the sentence an ANSWER (F3 fix round 1: «Да, подготовлю отчёт к понедельнику» to «Вы подготовите отчёт к
    понедельнику?» is not a stall)."""
    words=norm_words(question)
    keys=set()
    for w in words:
        if w in STOPWORDS or w in _NOT_CONTENT or len(w)<3:continue
        f=_facts(w)
        if not _is_number(w,f):keys|=f.keys
    return (frozenset(stems(w for w in words if w not in STOPWORDS and (len(w)>2 or w.isdigit()))),
            frozenset(w for w in words if w in NUMBER_WORDS or any(c.isdigit() for c in w)),frozenset(keys))


def _announces(head,complete,colon,question):
    """Does ``head`` - the words up to the end of a sentence, a colon or a dash - only announce the answer (see the block above)? ``complete``:
    the sentence has ended; if not, the word it ends on may still grow and is judged only when pymorphy3 knows it. ``colon``: ``head`` is cut
    from its sentence by a colon or a dash: the content is after it, and only a real act of answering is announced so («Скажу так: …»)."""
    ru=_morph()
    if ru is None or _QUOTE_OR_SYMBOL.search(head):return False
    raw=[match.group() for match in WORDS.finditer(head)]
    words=[normalize(word) for word in raw]
    if not words or len(words)>_MAX_ANNOUNCEMENT_WORDS:return False
    if not complete and head[-1:].isalnum() and not _facts(words[-1]).known:words.pop()
    if not words:return False
    facts=[_facts(w) for w in words]
    qstems,qnums,qkeys=_question_facts(question)
    # c8b: the topic named after «про» / «о» / «насчёт» - the question's own words and numbers («Понял, смотрю про семьдесят первый счёт.» to
    # «… семьдесят первый счёт, это что?») - says what the act is about, nothing of the answer: such words never make it one
    topic=_topic_phrase(words,facts,qkeys,qnums,qstems)
    if qkeys and any(f.keys&qkeys for i,(w,f) in enumerate(zip(words,facts))
                     if i not in topic and w not in _NOT_CONTENT and not _is_number(w,f)):return False   # it ANSWERS the question
    if not colon and any(w in ACK_WORDS for w in words) and all(w in _ACK_ONLY_WORDS for w in words):return True   # «Хорошо, спасибо.»
    if not colon and _acks_the_question(words):return True       # c7-meta: «Да, понял вопрос», also before its sentence has ended
    infn=any(f.infn for f in facts)
    pred=act=False
    # c7-meta round 2: a perfective future of any verb is the act's predicate too, never in reply to what the listener will do or plans
    promising=any(f.promise for f in facts) and _asked_of_you(str(question or ''))!='will'
    # c8b: a 1st-person-singular present of ANY verb is the predicate too, never in reply to what the listener does or will do; it announces only
    # with an object of the act (``META_NOUNS``) and no number (a choice: «Рекомендую второй вариант.»)
    doing=any(f.doing for f in facts) and _asked_of_you(str(question or '')) is None
    generic=False                       # the predicate is only such a present: an object of the act is needed, a number makes it content
    meta=False                          # an object of the act has been named
    reference=False                     # the word before names the object (a meta noun, or an abbreviation after one)
    after_ack=after_prep=False          # the word before was an acknowledgement («Слышу тебя»), or a preposition (no pronoun of a person follows it)
    for i,(w,f) in enumerate(zip(words,facts)):
        names,reference=reference,False
        nxt=facts[i+1] if i+1<len(words) else None
        if w in NEGATION_WORDS:return False
        if w in CLAUSE_WORDS or f.clause:
            if w=='как' and nxt is not None and nxt.infn:continue                      # «подумаю, как отвечать»
            return False
        if w in ('один','одну') and i+1<len(words) and words[i+1] in PAUSE_WORDS:continue   # «одну секунду»
        if i in topic:after_ack=after_prep=False;continue                               # c8b: «про семьдесят первый счёт»
        if _is_number(w,f):
            if generic:return False
            if w in qnums or stem(w) in qstems:after_ack=after_prep=False;continue
            return False
        if f.act or f.ack or (f.link and infn) or (promising and f.promise and not pred):
            pred=True;act=act or f.act or f.link or f.promise;generic=False;after_ack=f.ack;after_prep=False;continue
        if doing and f.doing and not pred:
            pred=generic=True;after_ack=after_prep=False;continue
        if f.infn:after_ack=after_prep=False;continue
        if w in ACK_WORDS:after_ack=True;after_prep=False;continue
        # c7-meta (w3_07): «Да, понял вопрос, сейчас проверю формулировку.» - «да» before an acknowledgement opens it (alone, «Да, хорошо.» is
        # still the answer: only a predicate of the act makes the sentence an announcement), and «вопрос» right after one is what was understood
        if w=='да' and not pred and i+1<len(words) and words[i+1] in ACK_WORDS:continue
        if after_ack and 'вопрос' in f.noun_lemmas:after_ack=after_prep=False;continue
        if w in FILLER_WORDS or w in PAUSE_WORDS or w=='я':after_ack=after_prep=False;continue
        if w in DELIVERY_WORDS:after_ack=after_prep=False;continue
        if not pred:return False                      # before the predicate: acknowledgements, «сейчас», «коротко», «я» - nothing else
        if w in PREPOSITIONS:after_ack=False;after_prep=True;continue
        if w in DEMONSTRATIVES:after_ack=after_prep=False;continue
        if (w in ADDRESSEE_DAT and not after_prep) or (w in ADDRESSEE_ACC and after_ack):after_ack=after_prep=False;continue
        if f.noun and f.noun_lemmas&META_NOUNS:meta=reference=True;after_ack=after_prep=False;continue
        if f.adj and (f.apro or f.adj in META_ADJECTIVES):after_ack=after_prep=False;continue
        if names and _ABBREVIATION.match(raw[i]):reference=True;after_ack=after_prep=False;continue   # c8b: «статьи НК РФ»
        return False
    if generic and not meta:return False
    return act if colon else pred


_TOPIC_PREPOSITIONS=_words('про о об обо насчет')


def _topic_phrase(words,facts,qkeys,qnums,qstems):
    """c8b: the indices of the words after a topic preposition («про», «о», «насчёт») that are all the question's own (its content words, its
    numbers) up to the end of the sentence: the topic the act is about. Empty when anything else is said there."""
    for i,w in enumerate(words):
        if w not in _TOPIC_PREPOSITIONS:continue
        rest=range(i+1,len(words))
        if rest and all((_is_number(words[k],facts[k]) and (words[k] in qnums or stem(words[k]) in qstems)) or bool(facts[k].keys&qkeys)
                        for k in rest):
            return frozenset(rest)
    return frozenset()


def _repeats_the_verb(words,facts,qkeys):
    """c8b: does the sentence say a verb of the question again (its aspect pair included: «сверите» / «сверю»)?"""
    return bool(qkeys) and any(f.verb and f.keys&qkeys for w,f in zip(words,facts) if w not in _NOT_CONTENT and not _is_number(w,f))


_QUESTION_LEADS=_words('да так ну а итак')


def _acks_the_question(words):
    """c7-meta (w3_07): «Да, понял вопрос», «Понял вопрос, спасибо», «Ага, ясно, вопрос»: an acknowledgement of the question itself - leads,
    acknowledgement words, then «вопрос», then nothing but acknowledgement words. Never the answer, however it goes on."""
    k=0
    while k<len(words) and words[k] in _QUESTION_LEADS:k+=1
    if k>=len(words) or words[k] not in ACK_WORDS:return False
    while k<len(words) and words[k] in ACK_WORDS:k+=1
    if k>=len(words) or 'вопрос' not in _facts(words[k]).noun_lemmas:return False
    return all(w in _ACK_ONLY_WORDS for w in words[k+1:])


# --- c7-meta: the cloud talking about itself and its prompting ------------------------------------------------------------------------------
# The live run of 3 Nov (20261103-164741): a remark to the prompter that was taken for a question got the model's reply about its own work
# cued - «Если я начну подсказывать слишком рано,», «Ой, понимаю, со стороны может звучать рвано.», «Мне лучше делать паузу и не болтать
# лишнего,». The class: a sentence with a 1st-person-singular reference (я / мне / меня / мной, or a 1st-person-singular verb) and a lemma of
# the prompter's work (``SELF_WORK_LEMMAS``; or a verb of speaking with a word of its pace, ``SELF_SPEECH_LEMMAS`` + ``SELF_PACE_LEMMAS``),
# in reply to a question that addresses the prompter (ты / тебе / a 2nd-person-singular verb) or to none: the listener's interlocutor says «вы»
# and asks about the listener («Вы говорите по-английски?» -> «Да, я говорю по-английски свободно.» is content). Such a sentence is no answer,
# and a question back to the listener after it («Скажи, как тебе комфортнее …?») is none either. «Я выбрал эту профессию, потому что …»,
# «Я работаю бухгалтером», «Я быстро учусь» name no work of the prompter's and stay.
SELF_WORK_LEMMAS=_words('подсказывать подсказать подсказка суфлировать суфлер пауза болтать звучать')
SELF_SPEECH_LEMMAS=_words('говорить сказать отвечать ответить произносить диктовать')
SELF_PACE_LEMMAS=_words('медленно медленный быстро быстрый рвано рваный рано ранний поздно поздний долго долгий слово')
_ME=_words('я мне меня мной мною')
_YOU_SINGULAR=_words('ты тебя тебе тобой тобою твой твоя твое твои твоего твоей твоему твоим твоих твою')
_MAX_SELF_TALK_WORDS=30


@functools.lru_cache(maxsize=32768)
def _person(word):
    """``(1st person singular verb, 2nd person singular verb, lemmas, an imperative singular, 2nd person plural verb, 1st person plural verb)`` of one normalized word, by
    pymorphy3's best reading."""
    ru=_morph()
    try:
        with ru._LOCK:parses=ru._MORPH.parse(word)
    except Exception:
        return False,False,frozenset(),False,False,False
    top=parses[0].tag
    verb=top.POS=='VERB' and top.number=='sing'
    lemmas=frozenset(p.normal_form.replace('ё','е') for p in parses if p is parses[0] or p.score>=0.15)
    plural=top.POS=='VERB' and top.number=='plur'
    return verb and top.person=='1per',verb and top.person=='2per',lemmas,verb and top.mood=='impr',plural and top.person=='2per',plural and top.person=='1per'


_THE_TWO_OF_US=_ME|_YOU_SINGULAR|_words('вы вас вам вами мы нас нам нами')
_ONESELF=_words('себе себя')
_YOU_ALL=_YOU_SINGULAR|_words('вы вас вам вами ваш ваша ваше ваши вашего вашей вашему вашим ваших вашу')
_WE_AND_ME=_ME|_words('мы нас нам нами')


# G3 (rule 4): the cloud's own first-person CONTENT - an interview, a presentation («Я пять лет работал главным бухгалтером») - is an answer. Talk about
# the assistant itself is not: a promise (a 1st-person future: «попробую», «посмотрю»), a word of its work or of what it can do, or no noun at all
# («Здорово, надеюсь, понравилось.»).
_ASSISTANT_TALK=_words('помогать помочь вопрос ответ ответить отвечать ассистент помощник модель искусственный интеллект слышать услышать понимать '
                       'понять знать мочь уметь готовый смотреть посмотреть искать проверять уточнять думать')


def talks_about_itself(sentence):
    """Is ``sentence`` said between the cloud and the listener, or about the cloud? It speaks to them («ты», «вы», a 2nd-person verb, an imperative), or it
    speaks in the first person (a pronoun, a verb) without content of its own (see ``_ASSISTANT_TALK``). With no analyzer: any pronoun of the two."""
    words=[normalize(match.group()) for match in WORDS.finditer(str(sentence))]
    if any(word in _YOU_ALL for word in words):return True
    ru=_morph()
    if ru is None:return any(word in _THE_TWO_OF_US for word in words)
    first=any(word in _WE_AND_ME for word in words);lemmas=set();named=False
    for word in words:
        try:
            with ru._LOCK:parse=ru._MORPH.parse(word)[0]
        except Exception:return True
        top=parse.tag
        if top.POS=='VERB':
            if top.person=='2per' or top.mood=='impr':return True
            if top.person=='1per':
                if top.tense=='futr':return True
                first=True
        named=named or (top.POS=='NOUN' and word not in STOPWORDS)
        lemmas.add(parse.normal_form.replace('ё','е'))
    return first and (not named or bool(lemmas&(_ASSISTANT_TALK|SELF_WORK_LEMMAS)))


def _said_to_a_person(question):
    """Is ``question`` said to somebody («ты», «вы», a 2nd-person verb, «о себе»)? Then the answer is that person's own: an interview, a presentation of oneself. Its last sentence of
    two words or more decides: what stands in front of that may be a remark to the prompter («… значит медленно пока реагируешь. Хорошо. Пять умножить на пять»)."""
    sentences=[norm_words(part) for part in re.split(r'[.!?…]+',str(question))]
    words=next((found for found in reversed(sentences) if len(found)>=2),norm_words(question))
    if any(word in _YOU_ALL or word in _ONESELF for word in words):return True
    return _morph() is not None and any(_person(word)[1] or _person(word)[4] for word in words)


def _said_to_the_listener(sentence):
    """Is ``sentence`` said to the one who repeats it («ты», a 2nd-person-singular verb, «давай», an order with nothing of its own)? He would never say that to his examiner. An order
    that names what to do is how a procedure is told («Раздели обе части на два.»), as in the plural."""
    words=[normalize(match.group()) for match in WORDS.finditer(str(sentence))]
    if any(word in _YOU_SINGULAR or word=='давай' for word in words):return True
    if _morph() is None:return False
    return any(_person(word)[1] for word in words) or (any(_person(word)[3] for word in words) and not _names_something(words))


def _names_something(words):
    """Is a noun among ``words`` that is no word of the talk between the cloud and the listener (``_ASSISTANT_TALK``)?"""
    ru=_morph()
    for word in words:
        with ru._LOCK:parse=ru._MORPH.parse(word)[0]
        if parse.tag.POS=='NOUN' and word not in STOPWORDS and parse.normal_form.replace('ё','е') not in _ASSISTANT_TALK:return True
    return False


def _speaks_for_itself(sentence):
    """Is ``sentence`` in the first person (a pronoun, a verb)?"""
    words=[normalize(match.group()) for match in WORDS.finditer(str(sentence))]
    if any(word in _WE_AND_ME for word in words):return True
    return _morph() is not None and any(_person(word)[0] or _person(word)[5] for word in words)


def about_itself(sentence,question):
    """H2 rule 7: the one detector of a sentence of the producer that is no portion: ``talks_about_itself``, where that cannot be the listener's own content. What is said to the
    listener («тебя», «хочешь», «давай») goes. First-person content stays where the question is said to a person: the answer is that person's («Я быстро учусь.»). An instruction
    in the plural stays: it is how a procedure is told («Подайте декларацию.»), and the listener can say it; anything else in the first person is the producer talking. A question
    back goes too («Что ещё разобрать?»: a job is told to ask none, an admission does not count one), unless the question is said to a person: then the listener asks it."""
    if str(sentence).rstrip().endswith('?'):return not _said_to_a_person(question)
    if not talks_about_itself(sentence):return False
    return _said_to_the_listener(sentence) or (not _said_to_a_person(question) and _speaks_for_itself(sentence))


def _to_the_prompter(question):
    words=norm_words(question)
    return not words or any(w in _YOU_SINGULAR or _person(w)[1] for w in words)


def _self_talk(sentence,question):
    """Is ``sentence`` the cloud talking about itself and its prompting (see the block above)?"""
    if _morph() is None or not _to_the_prompter(question):return False
    words=[normalize(match.group()) for match in WORDS.finditer(sentence)]
    if not words or len(words)>_MAX_SELF_TALK_WORDS:return False
    rows=[_person(w) for w in words]
    if not any(w in _ME for w in words) and not any(row[0] for row in rows):return False
    lemmas=frozenset().union(*(row[2] for row in rows))
    return bool(lemmas&SELF_WORK_LEMMAS) or bool(lemmas&SELF_SPEECH_LEMMAS and lemmas&SELF_PACE_LEMMAS)


def _leading_end(text,is_it):
    """Where the leading sentence of ``text`` ends if ``is_it(sentence, its mark or None)`` says it is of the kind (the cloud talking about itself, ``_self_talk``;
    a question back to the listener, ``_ask_back``): the ONE reading of such a leading sentence; ``-1`` while it has not ended; else ``None``."""
    stop=_SENTENCE_END.search(text)
    if not is_it(text[:stop.start()] if stop else text,stop.group() if stop else None):return None
    return stop.end() if stop else -1


# --- c7-meta round 2: the promise of an answer, by its form ------------------------------------------------------------------------------
# W4 (oral exam, 3 Nov): «Сделаю пример понятным и коротким.», «добавлю наглядный пример.», «Секунду, подниму статью…» were cued - verbs no
# lemma list had. Any 1st-person-singular PERFECTIVE FUTURE verb is now the predicate of an announcement (``_Facts.promise``) under every other
# condition of ``_announces``: nothing but the act's own objects (``META_NOUNS``: пример, статья, формулировка …; ``META_ADJECTIVES``), no
# number, no negation, no clause, no content word of the question. Never in reply to what the listener will do or plans («Что вы сделаете
# первым делом?», «Какие у вас планы?»: a 2nd-person future verb that is no imperative, or a word of plans).
_PLAN_LEMMAS=_words('план планировать собираться будущее цель намереваться')


@functools.lru_cache(maxsize=512)
def _asked_of_you(question):
    """c7-meta round 2 / c8b: what the question asks of the listener, from one reading of its words: ``'will'`` (what the listener will do or plans: a 2nd-person FUTURE verb that is no imperative, «будете»,
    or a word of plans: «Что вы сделаете первым делом?», «Какие у вас планы?»), ``'does'`` (what the listener does now: a 2nd-person PRESENT verb that is no imperative: «Кем вы работаете?», «Вы сверите отчёт?» is
    'will'), ``None`` (neither: «Объясните …», «Приведите …» read as 2nd-person too, but an imperative reading makes them the request)."""
    ru=_morph()
    does=False
    for word in norm_words(question):
        try:
            with ru._LOCK:parses=ru._MORPH.parse(word)
        except Exception:
            continue
        tag=parses[0].tag
        imperative=any(p.tag.mood=='impr' for p in parses)
        if (tag.POS=='VERB' and tag.person=='2per' and tag.tense=='futr' and not imperative) or word in ('будете','будешь'):return 'will'
        if any(p.normal_form.replace('ё','е') in _PLAN_LEMMAS for p in parses[:2]):return 'will'
        does=does or (tag.POS=='VERB' and tag.person=='2per' and tag.tense=='pres' and not imperative)
    return 'does' if does else None


def _answers_by_its_verb(sentence,question):
    """c8b: does ``sentence`` say a verb of ``question`` again (then it answers, whatever phrase it begins with: «Сверю отчёт до пятницы.»)?"""
    if not question or _morph() is None:return False
    words=[normalize(match.group()) for match in WORDS.finditer(sentence)]
    return _repeats_the_verb(words,[_facts(w) for w in words],_question_facts(question)[2])


def _announcement_end(text,question):
    """Where the leading sentence of ``text`` ends if it only announces the answer; ``None`` if it does not; ``-1`` if it does as far as it has
    come and has not ended (it is withheld, like every procedural sentence, until its end arrives)."""
    stop=_SENTENCE_END.search(text)
    first=text[:stop.start()] if stop else text
    cut=_ANNOUNCE_BREAK.search(first)
    if cut and _announces(first[:cut.start()],True,True,question):return cut.end()
    if _announces(first,stop is not None,False,question):return stop.end() if stop else -1
    return None


# --- c10-clarify: a question back to the LISTENER is no answer ----------------------------------------------------------------------------
# Live: «Можешь чуть точнее?» was cued as an early first cue (w3_02), «Какой именно?» (w4_04), «Если нужен другой кодекс или юрисдикция, уточни,
# пожалуйста, страну или документ.» (owner call 20:10) - the listener would repeat it to the examiner. A sentence that asks the LISTENER something
# is the cloud's talk with the prompter's user, like its self-talk: dropped. By form, not by a phrase list: (a) a BARE clarifier - «Какой
# именно?», «Что именно?», «В каком смысле?» - a question whose every word is an interrogative or a filler (no content word of any topic);
# (b) a 2nd-person ask: «уточни(те)», «поясни(те)», «переформулируй(те)» anywhere in a short sentence; «скажи(те)», «дай(те)», «назови(те)» …
# with a «?» or with context as its object («дай контекст»); «имеешь/имеете в виду»; a request «можешь / можете / сможешь / не мог бы ты(вы)»
# that is a question; any «?» sentence in the ты-form (the examiner is «вы» - the ты-form is the prompter talking to its listener). Kept: a
# question form inside content («Почему небо голубое? Потому что …»), the 1st and 3rd person («Могу уточнить», «Уточню»), a вы-form that is no
# ask («Хорошо, а у вас как дела?», «Рад вас видеть.»), a how-to imperative that asks for no context («Укажите в заявлении ИНН.»).
_ASK_BARE=_words('а ну вопрос какой какая какое какие какую каком каких какого какому что чего чем именно конкретно точнее поточнее подробнее подробней еще '
                 'в о об про смысле плане случае речь идет')
_ASK_STRONG=_words('уточни уточните поясни поясните конкретизируй конкретизируйте переформулируй переформулируйте перефразируй перефразируйте')
_ASK_TY=_words('скажи подскажи дай назови укажи пришли напиши сообщи приведи')
_ASK_VY=_words('скажите подскажите дайте назовите укажите пришлите напишите сообщите приведите')
_ASK_MODAL=_words('можешь можете сможешь сможете')
_ASK_CONTEXT=('контекст','детал','подробност','подробнее','подробней','точнее','уточнени','конкретн')
_ASK_TY_OBJECTS=('номер','тему','тема','документ','страну','юрисдикци')
_MAX_ASK_WORDS=16


def _ask_back(words,mark):
    """Does the sentence of ``words`` ask the listener something? ``mark``: its end («?», «.» …), or ``None`` while it has not ended (then it is
    judged by its lead and ``True`` means «withhold it»; a lead that is yet only a lead of content is not)."""
    if not words:return False
    ended=mark is not None
    question=ended and '?' in mark
    if all(word in _ASK_BARE for word in words):return question or not ended
    short=len(words)<=_MAX_ASK_WORDS or not ended
    if any(word in _ASK_STRONG for word in words):return short
    if 'виду' in words and ('имеешь' in words or 'имеете' in words):return True
    if any(word in _ASK_MODAL for word in words[:3]) or ('бы' in words and any(word in ('мог','могли') for word in words) and
                                                         ('ты' in words or 'вы' in words)):return question or not ended
    ty=any(word in _YOU_SINGULAR for word in words)
    if not ended:return ty or words[0] in _ASK_TY
    weak=[word for word in words if word in _ASK_TY or word in _ASK_VY]
    if weak and short:
        if question or any(word.startswith(_ASK_CONTEXT) for word in words):return True
        if any(word in _ASK_TY for word in weak) and any(word.startswith(_ASK_TY_OBJECTS) for word in words):return True
    return question and (ty or any(_person(word)[1] for word in words))


def strip_process_prefix(text,question='',digits=False):
    """Remove explicit procedural preambles, never an arbitrary 'сейчас/да'.

    A partial procedural sentence stays withheld until its boundary arrives.
    Quoted source text, factual time statements and negations are unchanged.
    This edits speech before delivery; raw source remains in opt-in evidence.

    F3: besides the phrases above, a leading sentence that only announces the answer is stripped - the cloud talking about its own actions
    («Сейчас коротко сформулирую.», «Понял, гляну детали статьи.») or an acknowledgement («Хорошо, спасибо.»); see ``_announces``. ``question``
    (what was asked) makes its own words harmless in such a sentence («гляну детали статьи» to «двадцать первая статья налогового кодекса»); without
    it only the act's own objects are. A reply that is nothing else is not an answer: ``''``. ``digits`` (H2): a first sentence that ends in digits is a sentence of its own
    (``_drop_break``): «Ответ 25. Хочешь ещё пример?» is no question back as a whole.
    """
    text=str(text).strip();question=str(question or '')
    if digits:
        ending,stop=_DIGIT_SENTENCE_END.search(text),_SENTENCE_END.search(text)
        if ending and (stop is None or ending.start()<stop.start()):
            head=strip_process_prefix(text[:ending.end()],question)
            return head+text[ending.end():] if head else strip_process_prefix(text[ending.end():],question,digits=True)
    talked=False                        # c7-meta: a sentence about the cloud's own prompting has been stripped
    while text:
        if talked:
            # what follows it is withheld until its sentence ends; a question back to the listener («Скажи, как тебе комфортнее …?») goes too
            stop=_SENTENCE_END.search(text)
            if stop is None:return ''
            if '?' in stop.group():
                text=text[stop.end():].lstrip()
                continue
        lead=_CHAT_SENTENCE.match(text) or _PRAISE_LEAD.match(text) or _ACK_LEAD.match(text) or (_asks_a_word_first(question) and _AFFIRM_LEAD.match(text))
        if lead:
            text=text[lead.end():].lstrip()
            continue
        match=_PROCESS_PREFIX.match(text) or _LOOK_WHERE.match(text)
        stop=_SENTENCE_END.search(text)
        if match and _answers_by_its_verb(text[:stop.start()] if stop else text,question):match=None
        if match:
            end=re.search(r'[.!?…:\n]',text[match.end():])
            if not end:return ''
            text=text[match.end()+end.end():].lstrip()
            continue
        end=_announcement_end(text,question)
        if end is None:
            end=_leading_end(text,lambda sentence,mark:_self_talk(sentence,question))
            if end is not None:talked=True
            else:
                end=_leading_end(text,lambda sentence,mark:_ask_back(norm_words(sentence),mark))      # c10-clarify: a question back to the listener goes like the self-talk
                if end is None:return text
        if end<0:return ''
        text=text[end:].lstrip()
    return ''


def _drop_break(text,at=0,digits=False):
    """The next sentence end of ``text`` from ``at`` for ``drop_process_sentences``: the period of an abbreviation («до н. э.», «и т. д.»,
    «1147 г.») is none, as for the planner (``ABBREVIATIONS``) - «э.» alone would strip to nothing as a hesitation and the answer would lose
    its last word (integ10, s6 abbreviation-06). ``digits`` (H2, the text channel writes numbers in digits): a mark after a digit ends a sentence too when a sentence or nothing
    follows («25. Понял тебя, …»: else that is one sentence, and the answer goes with the talk or the talk with the answer)."""
    while True:
        stop=_SENTENCE_END.search(text,at)
        ending=_DIGIT_SENTENCE_END.search(text,at) if digits else None
        if ending and (stop is None or ending.start()<stop.start()):return ending
        if stop is None or stop.group()!='.':return stop
        word=re.search(r'(\w+)$',text[:stop.start()])
        if not word or word.group(1).lower().replace('ё','е') not in ABBREVIATIONS:return stop
        at=stop.end()


def drop_process_sentences(text,question='',final=False,talk=False):
    """c7-meta (w3_07: «сейчас проверю формулировку.» was a later portion): ``text`` without the sentences AFTER its first that are about the
    cloud's own work - the very class ``strip_process_prefix`` strips at the start (a stall, an announcement, an acknowledgement, the cloud
    talking about its prompting) and, ``talk`` (H2 rule 7, the text channel on, for either source), those that talk about the producer or to the listener
    (``about_itself``: «Понял тебя, буду реагировать быстрее», «Давай ещё вопрос»), and those said FIRST too: the answer starts after them, and nothing is left of a text that is only
    that (a growing first sentence is withheld the same way). The sentence still being written is withheld while it could still become one (it is only leads so far, as
    ``first_useful._stall_pending`` judges: with a verb of the act after it, it would be one), so what is published from a shorter text is
    always the start of what a longer one gives. ``final``: nothing more will come - the last sentence is judged as it is, never withheld
    (integ10: a segment cut inside a word, «… свет. Поэт», must not end the answer at «свет.»)."""
    text=str(text);question=str(question or '')
    itself=(lambda sentence:about_itself(sentence,question)) if talk else (lambda sentence:False)
    first=_drop_break(text,digits=talk)
    while first is not None and itself(text[:first.end()]):
        text=text[first.end():].lstrip();first=_drop_break(text,digits=talk)
    if first is None:
        body=text.strip()
        if not body:return text
        if final:return '' if itself(body) else text
        return '' if itself(body) or itself(body.rsplit(None,1)[0]) else text
    out,at=[text[:first.end()]],first.end()
    while at<len(text):
        stop=_drop_break(text,at,talk)
        if stop is None:
            rest=text[at:]
            body=rest.strip()
            if not body:break
            if final:
                if strip_process_prefix(body,question) and not itself(body):out.append(rest)
                break
            growing=body[-1].isalnum()                     # its last word may still grow: judge the sentence without it too
            shorter=body.rsplit(None,1)[0] if growing and len(body.split())>1 else ('' if growing else body)
            if (not strip_process_prefix(body,question) or not strip_process_prefix(body+' проверю.',question)
                    or not strip_process_prefix((shorter+' проверю.').strip(),question) or itself(body) or (shorter and itself(shorter))):
                break
            out.append(rest)
            break
        sentence=text[at:stop.end()]
        if sentence.strip() and (not strip_process_prefix(sentence,question) or itself(sentence)):
            at=stop.end()
            continue
        out.append(sentence)
        at=stop.end()
    kept=''.join(out)
    return kept if kept==text else kept.rstrip()


# g21-brain, ONE rule for the run-up of the model («Да, сравню и отвечу кратко», «Секунду, проверю и скажу точно») and for the confirmation of a repeat («Да, верно»):
# ``fast_text`` had a second copy of the lists (_run_up / _confirmation / _may_be_lead / spoken_text) beside ``strip_process_prefix``; it is this function now. A run-up is the
# stall of ``strip_process_prefix``; a confirmation is a leading sentence of ONLY confirming words with one of the core («Да, это верно.»): it goes with an answer after it, a text that
# is nothing else stays whole once it is final (a bare «Да, верно.» may be the answer) and is held before. The start is held while it may still become one.
_LEAD_WORDS=frozenset('да хорошо ладно так ну итак окей ага угу конечно'.split())
_STALL_STEMS=('сейчас','секунд','минут','подожд','погод','давай','сравн','провер','уточн','отвеч','скаж','посмотр','подума','найд','смотр','момент')
_CONFIRM_WORDS=frozenset('да верно правильно точно именно совершенно абсолютно всё все это так вы ты правы прав согласен согласна действительно разумеется'.split())
_CONFIRM_CORE=frozenset('верно правильно точно именно правы прав согласен согласна действительно'.split())
_LEAD_TOKEN=re.compile(r'[а-яёa-z]+',re.I)
LEAD_HOLD_CHARS=70                     # a run-up is short: a start longer than this without an end is an answer


def _confirms(sentence):
    words=[word.lower() for word in _LEAD_TOKEN.findall(sentence)]
    return bool(words) and all(word in _CONFIRM_WORDS for word in words) and any(word in _CONFIRM_CORE for word in words)


def _lead_pending(text):
    """The start of ``text`` (no end of a sentence yet) may still turn out a run-up or a confirmation."""
    if len(text)>LEAD_HOLD_CHARS:return False
    for match in _LEAD_TOKEN.finditer(text):
        word,last=match.group().lower(),match.end()==len(text)
        if word in _LEAD_WORDS and not last:continue
        if last:return any(stem.startswith(word) or word.startswith(stem) for stem in _STALL_STEMS) or any(w.startswith(word) for w in _CONFIRM_WORDS|_LEAD_WORDS)
        if word in _CONFIRM_WORDS:continue
        return word.startswith(_STALL_STEMS)
    return True


def spoken_lead(raw,question='',final=False):
    """What of the model's text ``raw`` may be said: the leading run-ups, announcements and confirmations cut
    (``strip_process_prefix``). Growing ``raw`` only grows the result (a held start is the empty string). ``final``: ``raw`` is all there is."""
    text=str(raw).lstrip()
    while text:
        stop=_drop_break(text)
        if stop is None and not final and _lead_pending(text):return ''
        if stop is not None:
            head,rest=text[:stop.end()],text[stop.end():].lstrip()
            if _confirms(head):
                if not rest:return '' if not final else head.strip()
                text=rest
                continue
        cut=strip_process_prefix(text,question)
        if cut==text:break
        text=cut
    return text      # the later sentences of the cloud's own work are NOT dropped here (the fast text's old rule did not: its pieces keep reading as they were; 8 tests of test_h1_fast_text hold it)


# the words that make a piece a condition of the question: the ONE table (``classifier.question_part`` reads the same words for a head condition that has no number)
MARKER_BASE = (r'бер[её]м|возьм[её]м|допустим|предположим|пусть|исходим|учти|учтите|при\s+условии|с\s+уч[её]том|без|для|при|в\s+случае|по\s+ставке|по\s+условию|'
               r'ставка|срок|сумма|период|оборот|доход')
