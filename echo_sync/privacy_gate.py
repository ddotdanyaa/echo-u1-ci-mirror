
import re



PERSONAL_QUERY=re.compile(r'\b(?:мой|моя|мо[её]|моего|моей|моих|моему|мо[её]м|мои)\b|\bу\s+меня\b|\b(?:что|где|когда|как|кому|зачем)\s+я\b|\bобо?\s+мне\b',re.I)
SEARCH_PERSONAL=re.compile(r'\b(?:моим|моими|мою|мне|меня|мной|нам|нас|нами|наш\w*)\b',re.I)
GENERAL_FIRST_PERSON=re.compile(r'\b(?:скажи|скажите|объясни|объясните|расскажи|расскажите|подскажи|подскажите|поясни|поясните|покажи|покажите|напомни|напомните|назови|назовите)\s+мне\b|\bмне\s+(?:интересно|любопытно)\b|\bменя\s+интересу\w+|\bнаш\w*\s+эр\w*|\bдо\s+н\.?\s*э\b',re.I)
FIRST_PERSON_CLAUSE=re.compile(r'\b(?:что|где|когда|как|кому|зачем|если|чтобы)\s+я\b[^,;:?!.]*',re.I)
FIRST_PERSON_WORDS=re.compile(r'\bу\s+меня\b|\bобо?\s+мне\b|\b(?:мне|меня|мной|мой|моя|мо[её]|моего|моей|моих|моему|мо[её]м|мои|моим|моими|мою|мною|моею)\b',re.I)
STILL_PERSONAL=re.compile(r'\b(?:я|мы|нам|нас|нами|наш\w*|сво[йеяёию]\w*|себе|себя)\b',re.I)

_I_AFTER_QUESTION = re.compile(r'\b(?:кто|что|где|когда|как|кому|кого|чем|чего|зачем|почему|сколько|куда|откуда|какой|какая|какое|какие|ли)\s+(?:же\s+|вообще\s+|теперь\s+)?я\b', re.I)
_EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')

_PHONE = re.compile(r'(?<![\d.,])(?:\+?[78][\s\-()]*)?\(?9\d{2}\)?(?:[\s\-]*\d){7}(?![\d.,])')

_CARD = re.compile(r'(?<![\d.,])\d{4}(?:[\s\-]?\d{4}){2}[\s\-]?\d{1,7}(?![\d.,])')
_DOCUMENT = re.compile(r'\b(?:паспорт\w*|снилс\w*|инн|полис\w*)\b\D{0,12}\d(?:[\s\-]?\d){5,}', re.I)




_NO_DIGIT_BEFORE = r'(?<![\d.,])'
_NO_DIGIT_AFTER = r'(?![\d]|[.,]\d)'
_PHONE_SHAPES = re.compile(
    _NO_DIGIT_BEFORE + r'(?:\+\d[\d\s\-()]{8,16}\d'
    r'|(?:[78][\s\-]*)?\(?\d{3,5}\)?[\s\-]\d{2,3}[\s\-]\d{2}[\s\-]\d{2}'
    r'|\(?\d{3}\)?[\s\-.]\d{3}[\s\-.]\d{4}'
    r'|\d{3}-\d{2}-\d{2})' + _NO_DIGIT_AFTER)
_LONG_NUMBER = re.compile(_NO_DIGIT_BEFORE + r'\d{10,}' + _NO_DIGIT_AFTER)
_ACCOUNT_GROUPS = re.compile(_NO_DIGIT_BEFORE + r'\d{5}[\s\-]\d{3}[\s\-]\d[\s\-]\d{4}[\s\-]\d{7}' + _NO_DIGIT_AFTER)
_IBAN = re.compile(r'\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b')

_PATRONYMIC = r'[А-ЯЁ][а-яё]+(?:ович|евич|ьич|ична|овна|евна)'
_FULL_NAME = re.compile(r'(?<![А-Яа-яЁё])[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+' + _PATRONYMIC + r'(?![А-Яа-яЁё])|(?<![А-Яа-яЁё])[А-ЯЁ][а-яё]+\s+' + _PATRONYMIC + r'\s+[А-ЯЁ][а-яё]+(?![А-Яа-яЁё])', re.I)


_NOT_PERSONAL_AFTER = re.compile(r'\s*(?:рубл|руб\b|р\.|₽|%|процент|долл|евро|\$|€|тыс|млн|млрд|копе)', re.I)
_NOT_PERSONAL_BEFORE = re.compile(r'(?:тн\s*вэд|тнвэд|оквэд\d*|окпо|окпд\d*|октмо|окато|кбк|код\w*)\W{0,6}$', re.I)
_THOUSANDS = re.compile(r'^\+?\d{1,3}(?:[\s ]\d{3})+$')
_STREET = r'(?:ул\.|улиц\w*|пр-т|проспект\w*|пер\.|переул\w*|бульвар\w*|шоссе|наб\.|набережн\w*|микрорайон\w*|мкр\.)'
_ADDRESS = re.compile(r'\b' + _STREET + r'\s+[^\d?!;]{1,40}?[\s,]+(?:д\.|дом\w*)\s*\d+|\bд(?:ом)?\.?\s*\d+\s*[,\s]\s*кв(?:артира)?\.\s*\d+|\b(?:street|st\.|avenue|ave\.|road|rd\.)\s*,?\s*\d+\b|\b\d+\s+[A-Z][a-z]+\s+(?:street|avenue|road|lane)\b')
_SECRET = re.compile(
    r'\b(?:парол[ьяеюи]\w{0,3}|логин\w*|пин(?:[\s\-]*код\w*)?|pin|password|passcode|login|'
    r'(?:одноразов\w+|смс|sms)[\s\-]*(?:код\w*|code)|код\s+(?:из\s+смс|подтверждения|доступа|безопасности))\b'
    r'[^\w]{1,6}(?:\d{4,}\b(?!\s*(?:символ|цифр|знак|бук))|(?=\w*\d)(?=\w*[^\W\d_])\w{4,}|[A-Za-z][\w.@!#$%^&*\-]{3,})', re.I)
_CVV = re.compile(r'\b(?:cvv2?|cvc2?)\b[^\w]{1,6}\d{3,4}\b', re.I)


def personal_data_reason(text):
    
    for rule, kind in ((_PHONE_SHAPES, 'phone'), (_LONG_NUMBER, 'account')):
        for match in rule.finditer(text):
            if len(re.sub(r'\D', '', match.group())) < 7 or _NOT_PERSONAL_AFTER.match(text, match.end()) or _THOUSANDS.match(match.group()) \
                    or _NOT_PERSONAL_BEFORE.search(text[max(0, match.start() - 30):match.start()]):
                continue
            return kind
    if _ACCOUNT_GROUPS.search(text) or _IBAN.search(text):
        return 'account'
    if _FULL_NAME.search(text):
        return 'name'
    if _ADDRESS.search(text):
        return 'address'
    if _SECRET.search(text) or _CVV.search(text):
        return 'secret'
    return None



_FRAME_SAY_KNOW = frozenset(
    'сказать говорить объяснить объяснять рассказать рассказывать спросить спрашивать ответить пояснить пояснять уточнить уточнять попросить просить '
    'знать узнать узнавать понять понимать думать считать полагать предполагать помнить интересоваться любопытствовать искать выяснить выяснять разобраться'.split())

_FRAME_INTENT = frozenset('хотеть мочь пытаться попытаться начать начинать стараться пробовать собираться решить'.split())
_FRAME_CLASSES = _FRAME_SAY_KNOW | _FRAME_INTENT

_OWN_MARKERS = frozenset('себе себя свой своя свое свои своего своей мне меня мой моя мое мои ооо'.split())


_FRAME_WINDOW = 4
_OPENERS = frozenset('что как почему сколько зачем где когда чем кто куда откуда какой какая какое какие каков ли почем'.split())

_I_STATUS = re.compile(r'\bя[\s—–-]+(?:(?:вот|уже|теперь|сейчас|ещ[её]|тоже|просто)\s+)*(?:(?:на\s+пенсии|в\s+декрете|ип|студент(?:ка)?|школьни(?:к|ца)|пенсионер(?:ка)?|самозанят(?:ый|ая)|предприниматель|безработн(?:ый|ая)|директор|бухгалтер|сотрудник|работник|владелец|собственник|женат|замужем|учитель(?:ница)?|врач)\b)', re.I)
_I_BORN = re.compile(r'\bя\s+(?:\w+\s+){0,2}?родил(?:ся|ась)\b', re.I)
_INTRO = re.compile(r'\b(?:меня|мне|нас|нам)\s+зовут\s+\S+', re.I)

_ENGLISH_I = re.compile(r"\bI(?:'m\s+(?:a|an|the|at|in|from|on|working|living)|'ve\s+(?:got|been|worked|lived|paid)|'ll\s+pay)\b|\bI\s+(?:work|live|earn|own|run|pay|study|manage|owe)\b")
_ENGLISH_MY = re.compile(r"\b(?:my|mine|myself|me)\b", re.I)
_ENGLISH_ASK = re.compile(r"\b(?:tell|show|give|explain|help|remind|let|teach)\s+(?:to\s+)?me\b", re.I)


def _lemma_of(ru, word):
    with ru._LOCK:
        return ru._MORPH.parse(word)[0].normal_form


def speaks_as_i(text):
    
    try:
        from . import ru_alignment as ru
        from .textutil import WORDS, normalize
        ru._lemma('да')
        words = [normalize(match.group()) for match in WORDS.finditer(str(text))]
        for index, word in enumerate(words):
            with ru._LOCK:
                top = ru._MORPH.parse(word)[0]
            if top.tag.POS == 'VERB' and top.tag.person == '1per' and top.tag.number == 'sing':
                after = words[index + 1:index + 1 + _FRAME_WINDOW]
                if top.normal_form in _FRAME_CLASSES and any(other in _OPENERS for other in after) and not any(other in _OWN_MARKERS for other in after):
                    if top.normal_form in _FRAME_SAY_KNOW or (after and _lemma_of(ru, after[0]) in _FRAME_SAY_KNOW) or after[0] in _OPENERS:
                        continue
                return True
    except Exception:
        return True
    return False


def personal_reason(question):
    
    text = str(question)
    english = _ENGLISH_ASK.sub(' ', text)
    if PERSONAL_QUERY.search(text) or FIRST_PERSON_WORDS.search(text) or _I_AFTER_QUESTION.search(text) or _I_STATUS.search(text) or _ENGLISH_I.search(english) or _ENGLISH_MY.search(english) or _I_BORN.search(text) or speaks_as_i(text):
        return 'first_person'
    for name, rule in (('email', _EMAIL), ('document', _DOCUMENT), ('card', _CARD), ('phone', _PHONE)):
        if rule.search(text):
            return name
    return personal_data_reason(text)


def allowed(question, search=False):
    
    text = str(question)
    if PERSONAL_QUERY.search(text):
        return False
    if not search:
        return True
    general = GENERAL_FIRST_PERSON.sub(' ', text)
    return not SEARCH_PERSONAL.search(general) and personal_reason(general) is None


def impersonal(question, content_words):
    
    text = FIRST_PERSON_CLAUSE.sub(' ', _INTRO.sub(' ', str(question)))
    text = FIRST_PERSON_WORDS.sub(' ', text)
    text = re.sub(r'\s*,\s*([?!.])', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip(' ,;:')
    if len(content_words(text)) < 2 or not allowed(text, True) or STILL_PERSONAL.search(text) or speaks_as_i(text):
        return ''
    return text
