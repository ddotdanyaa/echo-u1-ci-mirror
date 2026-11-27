"""w9-map (N136, E17.1): abbreviations as state of the call, always on. The stock expander (``portioner.expand_abbreviations``) spells a term out at its FIRST
occurrence IN EACH ANSWER, so a call that talks about «НДС» for ten minutes hears «налог на добавленную стоимость» in every answer. The controller
(``ControlledMedia._abbreviations``) spells the term out once per call; afterwards the short form is kept, until the listener asks what it means (``asks_expansion``).
This module holds only the two pure tests the controller asks: is the term in the text, does the question ask for it."""
import re

_ASKS = re.compile(r'расшифр|что\s+так(?:ое|ой|ая|ие)|что\s+знач|что\s+означ|что\s+эт[оа]\b|что\s+за\b', re.I)


def _found(key, text):
    return re.search(r'(?<![\w-])' + r'\s+'.join(re.escape(p) for p in key.split()) + r'(?![\w-])', text) is not None


def asks_expansion(question, key):
    """Does the listener ask what ``key`` means («расшифруй НДС», «что такое НДС»)? «Какая ставка НДС» does not."""
    return isinstance(question, str) and _found(key, question) and _ASKS.search(question) is not None
