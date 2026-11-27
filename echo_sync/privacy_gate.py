"""w9-safe (N174): what may leave the laptop for the PUBLIC lookup (the keyless search behind ``echo_quick_lookup``, a third party).

This module holds the words of the gate: ``personal_reason`` names why a question must not go to the public search. The ONE gate is
``ControlledMedia.public_lookup_allowed(question, search)``: with ``search`` it adds this reason to ``PERSONAL_QUERY`` («мой», «у меня», «что я», «обо мне»).
Every case of «я»/«мой» ``FIRST_PERSON_WORDS`` lists (so a refused question takes the designed way: ``impersonal`` cuts the frame and looks up what is public),
«я» after a question word, and contact or document data (an e-mail, a phone number, a card number, digits after паспорт/СНИЛС/ИНН/полис).
Plural «мы/нас/наш» is NOT added here: «какая у нас в стране ставка НДС» is public; the owner decides (report w9-safe, D-safe-1).
Pure, no I/O, a few µs.
"""
import re

# The words of the listener's own affairs: the ONE list of the route (``PERSONAL_QUERY``, what keeps a question from a lookup of its own affairs), of the search (``SEARCH_PERSONAL``, E88: the wider words only
# the PUBLIC search may not see; ``GENERAL_FIRST_PERSON``: a request to tell, a wish to know, «наша эра» are none), of the frame ``impersonal`` cuts (``FIRST_PERSON_CLAUSE``, ``FIRST_PERSON_WORDS``) and of what stays personal after it (``STILL_PERSONAL``).
PERSONAL_QUERY=re.compile(r'\b(?:мой|моя|мо[её]|моего|моей|моих|моему|мо[её]м|мои)\b|\bу\s+меня\b|\b(?:что|где|когда|как|кому|зачем)\s+я\b|\bобо?\s+мне\b',re.I)
SEARCH_PERSONAL=re.compile(r'\b(?:моим|моими|мою|мне|меня|мной|нам|нас|нами|наш\w*)\b',re.I)
GENERAL_FIRST_PERSON=re.compile(r'\b(?:скажи|скажите|объясни|объясните|расскажи|расскажите|подскажи|подскажите|поясни|поясните|покажи|покажите|напомни|напомните|назови|назовите)\s+мне\b|\bмне\s+(?:интересно|любопытно)\b|\bменя\s+интересу\w+|\bнаш\w*\s+эр\w*|\bдо\s+н\.?\s*э\b',re.I)
FIRST_PERSON_CLAUSE=re.compile(r'\b(?:что|где|когда|как|кому|зачем|если|чтобы)\s+я\b[^,;:?!.]*',re.I)
FIRST_PERSON_WORDS=re.compile(r'\bу\s+меня\b|\bобо?\s+мне\b|\b(?:мне|меня|мной|мой|моя|мо[её]|моего|моей|моих|моему|мо[её]м|мои|моим|моими|мою|мною|моею)\b',re.I)
STILL_PERSONAL=re.compile(r'\b(?:я|мы|нам|нас|нами|наш\w*|сво[йеяёию]\w*|себе|себя)\b',re.I)
# «я» after any question word. A bare «я» is NOT a first-person word: «нет, я хотел спросить про насекомое», «вот я сегодня не выспался» are the speaker's frame (16 tests of the suite pin it: report, D-safe-2).
_I_AFTER_QUESTION = re.compile(r'\b(?:кто|что|где|когда|как|кому|кого|чем|чего|зачем|почему|сколько|куда|откуда|какой|какая|какое|какие|ли)\s+(?:же\s+|вообще\s+|теперь\s+)?я\b', re.I)
_EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
# A phone: +7 / 8 / 7 and ten digits, any spaces, dashes, brackets between them; or ten-eleven digits in a row starting with 9 (a mobile said without its 8).
_PHONE = re.compile(r'(?<![\d.,])(?:\+?[78][\s\-()]*)?\(?9\d{2}\)?(?:[\s\-]*\d){7}(?![\d.,])')
# A card: 16 digits (13-19), in groups of four or in one run.
_CARD = re.compile(r'(?<![\d.,])\d{4}(?:[\s\-]?\d{4}){2}[\s\-]?\d{1,7}(?![\d.,])')
_DOCUMENT = re.compile(r'\b(?:паспорт\w*|снилс\w*|инн|полис\w*)\b\D{0,12}\d(?:[\s\-]?\d){5,}', re.I)

# S5: personal DATA by its class (a shape, not a list of words): a phone of any country or a city one, a long number (an account, a card, a passport, a SNILS, a number run together), an IBAN,
# a name of three words (surname, name, patronymic) or «зовут Имя», an address (a street word + a house), a secret word + its value (пароль 1234, PIN, CVV, a code from an SMS). The rule of doubt: a shape that is
# personal in most mouths is refused; a short number («статья 422», «ставка 20 %», «счёт 62», «ОКВЭД 62.01») has none of these shapes and stays public.
_NO_DIGIT_BEFORE = r'(?<![\d.,])'
_NO_DIGIT_AFTER = r'(?![\d]|[.,]\d)'
_PHONE_SHAPES = re.compile(
    _NO_DIGIT_BEFORE + r'(?:\+\d[\d\s\-()]{8,16}\d'                                                       # +49 30 123456, +1 (555) 123-4567: international
    r'|(?:[78][\s\-]*)?\(?\d{3,5}\)?[\s\-]\d{2,3}[\s\-]\d{2}[\s\-]\d{2}'                                    # 495 123-45-67, 8 (4012) 12-34-56: a city phone
    r'|\(?\d{3}\)?[\s\-.]\d{3}[\s\-.]\d{4}'                                                                # 555 123 4567, (555) 123-4567
    r'|\d{3}-\d{2}-\d{2})' + _NO_DIGIT_AFTER)
_LONG_NUMBER = re.compile(_NO_DIGIT_BEFORE + r'\d{10,}' + _NO_DIGIT_AFTER)                                 # 10+ digits in a row: an account (20), a card, a passport/SNILS/INN, a phone said without gaps
_ACCOUNT_GROUPS = re.compile(_NO_DIGIT_BEFORE + r'\d{5}[\s\-]\d{3}[\s\-]\d[\s\-]\d{4}[\s\-]\d{7}' + _NO_DIGIT_AFTER)   # 40817 810 3 3800 0000123
_IBAN = re.compile(r'\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b')
# A birth date is no shape of its own: «родился Пушкин 06.06.1799» is public; «я родился 12.03.1990» is the first person (refused above).
_PATRONYMIC = r'[А-ЯЁ][а-яё]+(?:ович|евич|ьич|ична|овна|евна)'
_FULL_NAME = re.compile(r'(?<![А-Яа-яЁё])[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+' + _PATRONYMIC + r'(?![А-Яа-яЁё])|(?<![А-Яа-яЁё])[А-ЯЁ][а-яё]+\s+' + _PATRONYMIC + r'\s+[А-ЯЁ][а-яё]+(?![А-Яа-яЁё])', re.I)   # the case of the letters does not save a name (a recognizer writes «иванов иван иванович»)
# «зовут Имя»: no rule of its own: «меня зовут» is the first person (SEARCH_PERSONAL), «как зовут Путина» is public.
# Not a phone/account: a sum («+12 000 000 рублей», «12000000000 руб»), a code of a classifier (ТН ВЭД, ОКВЭД, ОКПО, КБК, «код 8471 30 00 00»).
_NOT_PERSONAL_AFTER = re.compile(r'\s*(?:рубл|руб\b|р\.|₽|%|процент|долл|евро|\$|€|тыс|млн|млрд|копе)', re.I)
_NOT_PERSONAL_BEFORE = re.compile(r'(?:тн\s*вэд|тнвэд|оквэд\d*|окпо|окпд\d*|октмо|окато|кбк|код\w*)\W{0,6}$', re.I)
_THOUSANDS = re.compile(r'^\+?\d{1,3}(?:[\s ]\d{3})+$')
_STREET = r'(?:ул\.|улиц\w*|пр-т|проспект\w*|пер\.|переул\w*|бульвар\w*|шоссе|наб\.|набережн\w*|микрорайон\w*|мкр\.)'
_ADDRESS = re.compile(r'\b' + _STREET + r'\s+[^\d?!;]{1,40}?[\s,]+(?:д\.|дом\w*)\s*\d+|\bд(?:ом)?\.?\s*\d+\s*[,\s]\s*кв(?:артира)?\.\s*\d+|\b(?:street|st\.|avenue|ave\.|road|rd\.)\s*,?\s*\d+\b|\b\d+\s+[A-Z][a-z]+\s+(?:street|avenue|road|lane)\b')
_SECRET = re.compile(
    r'\b(?:парол[ьяеюи]\w{0,3}|логин\w*|пин(?:[\s\-]*код\w*)?|pin|password|passcode|login|'
    r'(?:одноразов\w+|смс|sms)[\s\-]*(?:код\w*|code)|код\s+(?:из\s+смс|подтверждения|доступа|безопасности))\b'
    r'[^\w]{1,6}(?:\d{4,}\b(?!\s*(?:символ|цифр|знак|бук))|(?=\w*\d)(?=\w*[^\W\d_])\w{4,}|[A-Za-z][\w.@!#$%^&*\-]{3,})', re.I)   # a VALUE: 4+ digits, letters with digits, a latin token; «12 символов», «6 цифр» are a length
_CVV = re.compile(r'\b(?:cvv2?|cvc2?)\b[^\w]{1,6}\d{3,4}\b', re.I)


def personal_data_reason(text):
    """The kind of personal data in ``text`` by shape, or ``None``: 'phone', 'account', 'name', 'address', 'secret'."""
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


# E88 rest. The words a speaker uses to FRAME a question («я хочу узнать, что такое …», «я думаю», «не понимаю»): a verb of the 1st person by lemma, not a affair of the listener. Everything else in the 1st person singular is («работаю», «живу», «посмотрю»).
_FRAME_SAY_KNOW = frozenset(
    'сказать говорить объяснить объяснять рассказать рассказывать спросить спрашивать ответить пояснить пояснять уточнить уточнять попросить просить '      # speech
    'знать узнать узнавать понять понимать думать считать полагать предполагать помнить интересоваться любопытствовать искать выяснить выяснять разобраться'.split())  # cognition
# Intention verbs are a frame only when what they intend is itself speech or cognition («я могу узнать, что такое ИП»): «я могу позволить себе, как ...», «я хочу квартиру» intend an affair of the listener.
_FRAME_INTENT = frozenset('хотеть мочь пытаться попытаться начать начинать стараться пробовать собираться решить'.split())
_FRAME_CLASSES = _FRAME_SAY_KNOW | _FRAME_INTENT
# A personal marker inside the window never leaves a frame: «я скажу себе, что такое ...».
_OWN_MARKERS = frozenset('себе себя свой своя свое свои своего своей мне меня мой моя мое мои ооо'.split())
# A verb of these classes is the speaker's FRAME only when it leads a question: an interrogative opener follows within ``_FRAME_WINDOW`` words («я скажу кратко, что такое ИП», «я спрошу, как ...», «я хочу узнать, почему ...»).
# «я хочу квартиру» or «я работаю в ООО, какая ставка» are no frame: the class alone is not enough, nor an opener after a verb of another class.
_FRAME_WINDOW = 4
_OPENERS = frozenset('что как почему сколько зачем где когда чем кто куда откуда какой какая какое какие каков ли почем'.split())
# Personal with no verb: «я студент», «я — ИП», «я директор ООО», «я на пенсии», «я в декрете»: «я» and, within three words, a status or a trade of the speaker.
_I_STATUS = re.compile(r'\bя[\s—–-]+(?:(?:вот|уже|теперь|сейчас|ещ[её]|тоже|просто)\s+)*(?:(?:на\s+пенсии|в\s+декрете|ип|студент(?:ка)?|школьни(?:к|ца)|пенсионер(?:ка)?|самозанят(?:ый|ая)|предприниматель|безработн(?:ый|ая)|директор|бухгалтер|сотрудник|работник|владелец|собственник|женат|замужем|учитель(?:ница)?|врач)\b)', re.I)
_I_BORN = re.compile(r'\bя\s+(?:\w+\s+){0,2}?родил(?:ся|ась)\b', re.I)      # S5: «я родился 12.03.1990» is the speaker's own date (the past has no person for ``speaks_as_i``); «родился Пушкин» without «я» stays public
_INTRO = re.compile(r'\b(?:меня|мне|нас|нам)\s+зовут\s+\S+', re.I)      # S5: «меня зовут Данил»: ``impersonal`` cuts the name with the frame, else «зовут Данил, ...» would reach the public search
# English («I work at Romashka», «my salary», «I'm», «me»): the Russian words are not read, the English ones are listed (the pronoun «I» is read as written, capital).
_ENGLISH_I = re.compile(r"\bI(?:'m\s+(?:a|an|the|at|in|from|on|working|living)|'ve\s+(?:got|been|worked|lived|paid)|'ll\s+pay)\b|\bI\s+(?:work|live|earn|own|run|pay|study|manage|owe)\b")
_ENGLISH_MY = re.compile(r"\b(?:my|mine|myself|me)\b", re.I)
_ENGLISH_ASK = re.compile(r"\b(?:tell|show|give|explain|help|remind|let|teach)\s+(?:to\s+)?me\b", re.I)    # «Can you tell me ...», «explain to me»: the request to say, no affair (as GENERAL_FIRST_PERSON for «скажи мне»)


def _lemma_of(ru, word):
    with ru._LOCK:
        return ru._MORPH.parse(word)[0].normal_form


def speaks_as_i(text):
    """The ONE reading of «a verb in the 1st person singular» (present or future; the past has no person in the analyzer: «я хотел спросить» is the speaker's frame), with or without «я»:
    «я вот работаю», «работаю в ООО Ромашка», «посмотрю». A frame verb (``_FRAME_CLASSES`` + an opener of a question within the window: «хочу узнать, что такое», «скажу кратко, что такое», «не понимаю, как») is no affair. The analyzer is not there or fails:
    ``True`` - the ONE policy of a failure is to keep the question from the public search, never to let it through (the analyzer is a required dependency: plugin.yaml, test_env_deps)."""
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
                    if top.normal_form in _FRAME_SAY_KNOW or (after and _lemma_of(ru, after[0]) in _FRAME_SAY_KNOW) or after[0] in _OPENERS or (top.normal_form in _FRAME_INTENT and any(w in ('с', 'со', 'о', 'об', 'про') or _lemma_of(ru, w) in ('с', 'о', 'про') for w in after)):
                        continue
                return True
    except Exception:
        return True
    return False


def personal_reason(question):
    """Why ``question`` must not go to the public lookup: 'first_person', 'email', 'phone', 'card', 'document', or (S5, by the shape of the data: ``personal_data_reason``) 'account', 'name', 'address', 'secret', or ``None``."""
    text = str(question)
    english = _ENGLISH_ASK.sub(' ', text)
    if PERSONAL_QUERY.search(text) or FIRST_PERSON_WORDS.search(text) or _I_AFTER_QUESTION.search(text) or _I_STATUS.search(text) or _ENGLISH_I.search(english) or _ENGLISH_MY.search(english) or _I_BORN.search(text) or speaks_as_i(text):
        return 'first_person'
    for name, rule in (('email', _EMAIL), ('document', _DOCUMENT), ('card', _CARD), ('phone', _PHONE)):
        if rule.search(text):
            return name
    return personal_data_reason(text)


def allowed(question, search=False):
    """The ONE privacy gate of the road (cm-route). ``search=False``: may the question go on the route and to the job (``PERSONAL_QUERY`` keeps it from a lookup of its own affairs).
    ``search=True`` (E88): may it reach the PUBLIC search: past the route's gate, no word of the listener's own affairs (``SEARCH_PERSONAL``), nor a reason of ``personal_reason`` (w10 item 1, W9S-F1)."""
    text = str(question)
    if PERSONAL_QUERY.search(text):
        return False
    if not search:
        return True
    general = GENERAL_FIRST_PERSON.sub(' ', text)
    return not SEARCH_PERSONAL.search(general) and personal_reason(general) is None


def impersonal(question, content_words):
    """The question without its first-person frame, when what remains is a public question: ``''`` otherwise. «Какая сейчас ставка НДС, когда я продаю товар?» -> «Какая сейчас ставка НДС?».
    What remains must pass the gate (``allowed(.., True)``), hold no other personal marker (я, мы, наш, свой, a verb in the 1st person singular) and still be a question (two content words: ``content_words(text)``)."""
    text = FIRST_PERSON_CLAUSE.sub(' ', _INTRO.sub(' ', str(question)))
    text = FIRST_PERSON_WORDS.sub(' ', text)
    text = re.sub(r'\s*,\s*([?!.])', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip(' ,;:')
    if len(content_words(text)) < 2 or not allowed(text, True) or STILL_PERSONAL.search(text) or speaks_as_i(text):
        return ''
    return text
