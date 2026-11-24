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


# E88 rest. The words a speaker uses to FRAME a question («я хочу узнать, что такое …», «я думаю», «не понимаю»): a verb of the 1st person by lemma, not a affair of the listener. Everything else in the 1st person singular is («работаю», «живу», «посмотрю»).
_FRAME_LEMMAS = frozenset('хотеть думать понимать знать считать интересоваться спрашивать полагать предполагать любопытствовать уточнять уточнить просить мочь пытаться попытаться искать помнить понять пробовать стараться'.split())
# Personal with no verb: «я студент», «я — ИП», «я директор ООО», «я на пенсии», «я в декрете»: «я» and, within three words, a status or a trade of the speaker.
_I_STATUS = re.compile(r'\bя[\s—–-]+(?:(?:вот|уже|теперь|сейчас|ещ[её]|тоже|просто)\s+)*(?:(?:на\s+пенсии|в\s+декрете|ип|студент(?:ка)?|школьни(?:к|ца)|пенсионер(?:ка)?|самозанят(?:ый|ая)|предприниматель|безработн(?:ый|ая)|директор|бухгалтер|сотрудник|работник|владелец|собственник|женат|замужем|учитель(?:ница)?|врач)\b)', re.I)
# English («I work at Romashka», «my salary», «I'm», «me»): the Russian words are not read, the English ones are listed (the pronoun «I» is read as written, capital).
_ENGLISH_I = re.compile(r"\bI(?:'m\s+(?:a|an|the|at|in|from|on|working|living)|'ve\s+(?:got|been|worked|lived|paid)|'ll\s+pay)\b|\bI\s+(?:work|live|earn|own|run|pay|study|manage|owe)\b")
_ENGLISH_MY = re.compile(r"\b(?:my|mine|myself|me)\b", re.I)
_ENGLISH_ASK = re.compile(r"\b(?:tell|show|give|explain|help|remind|let|teach|can\s+you\s+tell)\s+me\b", re.I)    # «Can you tell me ...», «explain to me»: the request to say, no affair (as GENERAL_FIRST_PERSON for «скажи мне»)


def speaks_as_i(text):
    """The ONE reading of «a verb in the 1st person singular» (present or future; the past has no person in the analyzer: «я хотел спросить» is the speaker's frame), with or without «я»:
    «я вот работаю», «работаю в ООО Ромашка», «посмотрю». A frame verb by lemma (``_FRAME_LEMMAS``: «хочу узнать», «думаю», «не понимаю») is no affair. The analyzer is not there or fails:
    ``True`` - the ONE policy of a failure is to keep the question from the public search, never to let it through (the analyzer is a required dependency: plugin.yaml, test_env_deps)."""
    try:
        from . import ru_alignment as ru
        from .textutil import WORDS, normalize
        ru._lemma('да')
        for match in WORDS.finditer(str(text)):
            with ru._LOCK:
                top = ru._MORPH.parse(normalize(match.group()))[0]
            if top.tag.POS == 'VERB' and top.tag.person == '1per' and top.tag.number == 'sing' and top.normal_form not in _FRAME_LEMMAS:
                return True
    except Exception:
        return True
    return False


def personal_reason(question):
    """Why ``question`` must not go to the public lookup: 'first_person', 'email', 'phone', 'card', 'document', or ``None``."""
    text = str(question)
    english = _ENGLISH_ASK.sub(' ', text)
    if PERSONAL_QUERY.search(text) or FIRST_PERSON_WORDS.search(text) or _I_AFTER_QUESTION.search(text) or _I_STATUS.search(text) or _ENGLISH_I.search(english) or _ENGLISH_MY.search(english) or speaks_as_i(text):
        return 'first_person'
    for name, rule in (('email', _EMAIL), ('document', _DOCUMENT), ('card', _CARD), ('phone', _PHONE)):
        if rule.search(text):
            return name
    return None


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
    text = FIRST_PERSON_CLAUSE.sub(' ', str(question))
    text = FIRST_PERSON_WORDS.sub(' ', text)
    text = re.sub(r'\s*,\s*([?!.])', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip(' ,;:')
    if len(content_words(text)) < 2 or not allowed(text, True) or STILL_PERSONAL.search(text) or speaks_as_i(text):
        return ''
    return text
