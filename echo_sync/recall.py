"""U14 recall: «повтори мои последние 20 слов». Pure parser and resolver, wired by U14-S6 as the first rule of the judge.
Grammar of five slots on stems inside a window of at most ``WINDOW`` words that starts at the verb: VERB, RECENCY (required: «последн» / «last», so «первые 10 слов» or «скажи пять слов о себе» are not recalls), UNIT (required), QUANTITY (read by ``ru_numbers``), OWNER.
Only caveat words («слушай», «ну», «пожалуйста», «could you») may stand before the verb. A miss is extended structurally (a numeral right before the unit noun), never by a phrase list.
No owner word means the cue's own words that the listener heard (decision D2); «мои» / «my» means the listener's words."""
from collections import namedtuple

WINDOW = 9
MAX_WORDS = 200

Recall = namedtuple('Recall', 'owner n')
USER, ASSISTANT = 'user', 'assistant'

VERB_STEMS = ('повтор', 'скаж', 'прочита', 'перескаж', 'напомн', 'зачита', 'произнес', 'repeat', 'say', 'read', 'tell')
UNITS = frozenset({'слово', 'слова', 'слов', 'словам', 'словами', 'word', 'words'})
CAVEATS = frozenset({
    'слушай', 'слушайте', 'ну', 'так', 'вот', 'там', 'пожалуйста', 'пожалуста', 'будь', 'добр', 'добра', 'извини', 'извините', 'можешь', 'можете',
    'давай', 'давайте', 'короче', 'тогда', 'просто', 'ты', 'вы', 'а', 'и', 'hey', 'ok', 'okay', 'please', 'could', 'can', 'would', 'you', 'just',
    'now', 'so', 'well', 'uh', 'um', 'listen', 'sorry'})
MY = frozenset({'мои', 'моих', 'мой', 'мое', 'мою', 'моим', 'моими', 'my'})
YOUR = frozenset({'твои', 'твоих', 'твой', 'твое', 'твою', 'ваши', 'ваших', 'ваш', 'ваше', 'your'})
MAX_PREFIX = 5
RECENCY_STEMS = ('последн', 'last')


def _norm(surface):
    return str(surface).lower().replace('ё', 'е')


def parse(text):
    """``Recall(owner, n)`` for a recall command, else ``None``."""
    from .ru_alignment import _items
    from .ru_numbers import read_number
    items = _items(str(text or ''))
    words = [_norm(it.surface) if it.kind == 'word' else None for it in items]
    verb = next((i for i, w in enumerate(words) if w and w.startswith(VERB_STEMS)), None)
    if verb is None or verb > MAX_PREFIX or any(w not in CAVEATS for w in words[:verb]):
        return None
    end = min(len(items), verb + WINDOW)
    unit = next((i for i in range(verb + 1, end) if words[i] in UNITS), None)
    if unit is None:
        return None
    if not any(w and w.startswith(RECENCY_STEMS) for w in words[verb + 1:unit]):
        return None
    n = owner = None
    for i in range(verb + 1, unit):
        if words[i] in MY:
            owner = USER
        elif words[i] in YOUR:
            owner = ASSISTANT
        read = read_number(items, i) if items[i].kind != 'word' else None
        if read is None or not hasattr(read, 'atom'):
            continue
        if unit - read.end > 1 or not read.atom[1:].isdigit():
            continue
        n = int(read.atom[1:])
        break
    if not n or n < 1:
        return None
    return Recall(owner or ASSISTANT, min(n, MAX_WORDS))


def resolve(ledger, recall, skip=None):
    """The verbatim words to repeat: the listener's last ``n`` words or the last ``n`` words of the cues that were heard."""
    if recall is None:
        return []
    return ledger.user_words(recall.n, skip=skip) if recall.owner == USER else ledger.played_words(recall.n)
