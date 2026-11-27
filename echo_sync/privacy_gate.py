"""w9-safe (N174): what may leave the laptop for the PUBLIC lookup (the keyless search behind ``echo_quick_lookup``, a third party).

This module holds the words of the gate: ``personal_reason`` names why a question must not go to the public search. The ONE gate is
``ControlledMedia.public_lookup_allowed(question, search)``: with ``search`` it adds this reason to the route's own words («мой», «у меня», «что я», «обо мне»).
Every case of «я»/«мой» the controller's ``_FIRST_PERSON_WORDS`` lists (so a refused question takes the designed way: ``impersonal`` cuts the frame and looks up what is public),
«я» after a question word, and contact or document data (an e-mail, a phone number, a card number, digits after паспорт/СНИЛС/ИНН/полис).
Plural «мы/нас/наш» is NOT added here: «какая у нас в стране ставка НДС» is public; the owner decides (report w9-safe, D-safe-1).
Pure, no I/O, a few µs.
"""
import re

# The route's words (controlled_media's _PERSONAL_QUERY + «обо мне»), the first of the reasons.
_BASE = re.compile(r'\b(?:мой|моя|мо[её]|моего|моей|моих|моему|мо[её]м|мои)\b|\bу\s+меня\b|\b(?:что|где|когда|как|кому|зачем)\s+я\b|\bобо?\s+мне\b', re.I)
# Every oblique form of the first person singular (the controller's _FIRST_PERSON_WORDS + «мною/моею»), and «я» after any question word. A bare «я» is
# NOT one: «нет, я хотел спросить про насекомое», «вот я сегодня не выспался» are the speaker's frame (16 tests of the suite pin it: report, D-safe-2).
_FIRST_PERSON = re.compile(r'\b(?:мне|меня|мной|мною|мой|моя|мо[её]|моего|моей|моею|моих|моему|мо[её]м|мои|моим|моими|мою)\b'
                           r'|\b(?:кто|что|где|когда|как|кому|кого|чем|чего|зачем|почему|сколько|куда|откуда|какой|какая|какое|какие|ли)\s+(?:же\s+|вообще\s+|теперь\s+)?я\b', re.I)
_EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
# A phone: +7 / 8 / 7 and ten digits, any spaces, dashes, brackets between them; or ten-eleven digits in a row starting with 9 (a mobile said without its 8).
_PHONE = re.compile(r'(?<![\d.,])(?:\+?[78][\s\-()]*)?\(?9\d{2}\)?(?:[\s\-]*\d){7}(?![\d.,])')
# A card: 16 digits (13-19), in groups of four or in one run.
_CARD = re.compile(r'(?<![\d.,])\d{4}(?:[\s\-]?\d{4}){2}[\s\-]?\d{1,7}(?![\d.,])')
_DOCUMENT = re.compile(r'\b(?:паспорт\w*|снилс\w*|инн|полис\w*)\b\D{0,12}\d(?:[\s\-]?\d){5,}', re.I)


def personal_reason(question):
    """Why ``question`` must not go to the public lookup: 'first_person', 'email', 'phone', 'card', 'document', or ``None``."""
    text = str(question)
    if _BASE.search(text) or _FIRST_PERSON.search(text):
        return 'first_person'
    for name, rule in (('email', _EMAIL), ('document', _DOCUMENT), ('card', _CARD), ('phone', _PHONE)):
        if rule.search(text):
            return name
    return None
