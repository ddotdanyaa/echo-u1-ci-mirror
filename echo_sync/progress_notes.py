"""CL2, ruling 5: the spoken progress, told to the cloud model as quiet service notes.

The cloud session only hears the call: it does not know that the listener stopped an answer half-way, that a new question cut one off, or
(after a reconnect) what the conversation was. These notes tell it, in Russian, as data: what was said of an answer and what was not. They
travel as ``session.context.append`` frames on the quiet ``commentary`` channel (native_media_socket.note_frames): never ``speakable``, no
answer is asked for. Every text is cleaned and fenced (the «» quotes around each piece cannot be closed from inside it), and sized here:

* a progress note (ruling 5a) is ONE frame: at most NOTE_BYTES UTF-8 bytes; the pieces start at 80 / 150 / 150 characters (question / said /
  not said) and shrink until it fits, the last resort being a cut with «…»;
* a reconnect note (ruling 5b) is at most RECONNECT_FRAMES frames of NOTE_BYTES each, for the newest MAP_ROWS fresh entries of the map.

Nothing here logs: the caller logs sizes and counts only, never the text.
"""
import unicodedata

NOTE_BYTES = 500                 # one commentary frame (Conduit GPTLiveProtocol's context chunk size)
RECONNECT_FRAMES = 2
MAP_ROWS = 3
QUESTION_CHARS, SAID_CHARS, UNSAID_CHARS = 80, 150, 150
_MIN_CHARS = 20
# A frame is cut at the last space among its last _WORD_SLACK_CHARS characters, so the text of a multi-frame note keeps that much room.
_WORD_SLACK_CHARS = 30
_WORD_SLACK_BYTES = 4 * _WORD_SLACK_CHARS
_FENCE = str.maketrans({'«': '‹', '»': '›', '⟦': '[', '⟧': ']', '〚': '[', '〛': ']', '⟬': '[', '⟭': ']'})
HEAD = 'Служебная заметка суфлёра, не вопрос: '


def clean(text):
    """One line of plain text safe inside the note's «» quotes: no control or invisible format characters, no quote or fence brackets."""
    kept = ''.join(' ' if ch in '\n\r\t' else ch for ch in str(text or '') if ch in '\n\r\t' or unicodedata.category(ch) not in ('Cc', 'Cf'))
    return ' '.join(kept.translate(_FENCE).split())


def _head(text, limit):
    return text if len(text) <= limit else text[:max(1, limit - 1)].rstrip() + '…'


def _tail(text, limit):
    return text if len(text) <= limit else '…' + text[len(text) - max(1, limit - 1):].lstrip()


def _size(text):
    return len(text.encode('utf-8'))


def _cut(text, budget):
    """``text`` cut to at most ``budget`` UTF-8 bytes, ending in «…» when it was cut."""
    if _size(text) <= budget:
        return text
    while text and _size(text) + _size('…') > budget:
        text = text[:-1]
    return text.rstrip() + '…'


def _shrink(caps):
    """The next, smaller caps: the largest piece gives up a tenth (never below _MIN_CHARS); ``None`` when none can shrink."""
    largest = max(range(len(caps)), key=lambda i: caps[i])
    if caps[largest] <= _MIN_CHARS:
        return None
    smaller = list(caps)
    smaller[largest] = max(_MIN_CHARS, caps[largest] - max(5, caps[largest] // 10))
    return tuple(smaller)


def _progress_text(question, said, unsaid):
    body = f'из ответа на «{question}» '
    body += f'человек успел сказать «{said}»' if said else 'человек ещё ничего не успел сказать'
    return f'{HEAD}{body}; не сказано: «{unsaid}».'


def progress_note(item):
    """Ruling 5a: the note for one answer left with something unsaid; ``item`` is ``{question, spoken_text, unspoken_text}``
    (engine.unfinished). ``None`` when nothing is left unsaid. Of what was said the END is kept (where the listener stopped), of the
    question and of the rest the beginning. One frame: at most NOTE_BYTES bytes."""
    if not isinstance(item, dict):
        return None
    question, said, unsaid = (clean(item.get(key)) for key in ('question', 'spoken_text', 'unspoken_text'))
    if not unsaid:
        return None
    caps = (QUESTION_CHARS, SAID_CHARS, UNSAID_CHARS)
    while True:
        text = _progress_text(_head(question, caps[0]), _tail(said, caps[1]), _head(unsaid, caps[2]))
        if _size(text) <= NOTE_BYTES:
            return text
        smaller = _shrink(caps)
        if smaller is None:
            return _cut(text, NOTE_BYTES)
        caps = smaller


def _row_text(number, row, caps):
    question = _head(clean(row.get('question')), caps[0])
    said, unsaid = clean(row.get('spoken_text')), clean(row.get('unspoken_text'))
    text = f'{number}) вопрос «{question}» — '
    text += f'сказано «{_tail(said, caps[1])}»' if said else 'ничего не сказано'
    if unsaid:
        text += f', не сказано «{_head(unsaid, caps[2])}»'
    return text


def reconnect_note(rows):
    """Ruling 5b: the note of a call that opens while the conversation map holds fresh entries (``rows`` = engine.conversation_map,
    oldest first, stale entries already left out). ``None`` with no rows. At most RECONNECT_FRAMES frames of NOTE_BYTES bytes."""
    rows = [row for row in (rows or ()) if isinstance(row, dict)][-MAP_ROWS:]
    if not rows:
        return None
    budget = (NOTE_BYTES - _WORD_SLACK_BYTES) * RECONNECT_FRAMES      # room for cutting the text into frames between words
    caps = (QUESTION_CHARS, SAID_CHARS, UNSAID_CHARS)
    while True:
        text = HEAD + 'связь восстановлена; разговор до этого: ' + '; '.join(
            _row_text(number, row, caps) for number, row in enumerate(rows, 1)) + '.'
        if _size(text) <= budget:
            return text
        smaller = _shrink(caps)
        if smaller is None:
            return _cut(text, budget)
        caps = smaller


def split_frames(text, budget=NOTE_BYTES, limit=RECONNECT_FRAMES):
    """``text`` as at most ``limit`` pieces of at most ``budget`` UTF-8 bytes, cut between words when a space is near the end of a piece
    (within _WORD_SLACK_CHARS characters), else between characters (never inside one). What does not fit into ``limit`` pieces is dropped:
    the builders above size the text so that nothing is."""
    pieces = []
    rest = str(text or '')
    while rest and len(pieces) < limit:
        if _size(rest) <= budget:
            pieces.append(rest)
            break
        cut, size = 0, 0
        for index, char in enumerate(rest):
            size += _size(char)
            if size > budget:
                break
            cut = index + 1
        space = rest.rfind(' ', max(0, cut - _WORD_SLACK_CHARS), cut)
        if space > 0:
            cut = space + 1
        pieces.append(rest[:cut])
        rest = rest[cut:]
    return [piece for piece in pieces if piece]
