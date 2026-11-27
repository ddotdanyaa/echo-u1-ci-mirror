"""Semantic punctuation checks for ACKs after ordinary word normalization."""
from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right


_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_WORD_BEFORE = re.compile(r"([^\W_]+)\s*$", re.UNICODE)
_WORD_AFTER = re.compile(r"^\s*([^\W_]+)", re.UNICODE)
_DATE = re.compile(
    r"(?<!\d)(?:\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-](?:\d{2}|\d{4}))(?!\d)"
)


def _norm_word(word: str) -> str:
    return unicodedata.normalize('NFKC', word).casefold().replace('ё', 'е')


def _dash_is_semantic(text: str, index: int) -> bool:
    left, right = text[:index], text[index + 1:]
    # A streamed definition may issue its subject with the copula dash.
    # That punctuation is inaudible, unlike an explicit minus, numeric range,
    # or single-letter algebraic operand. Keep those protected below.
    if text[index] in '—–' and not right.strip():
        word = _WORD_BEFORE.search(left)
        if word and word.group(1).isalpha() and len(word.group(1)) > 1:
            return False
    prev = left[-1] if left else ""
    nxt = right[0] if right else ""
    if prev.isalpha() and nxt.isalpha():
        left_word = _WORD_BEFORE.search(left)
        right_word = _WORD.match(right)
        return bool(left_word and right_word and len(left_word.group(1)) == len(right_word.group()) == 1)
    if prev.isspace() and nxt.isspace():
        left_word = _WORD_BEFORE.search(left)
        right_word = _WORD_AFTER.match(right)
        if not left_word or not right_word:
            return False
        a, b = left_word.group(1), right_word.group(1)
        return (a.isdigit() and b.isdigit()) or (len(a) == len(b) == 1)
    if prev.isdigit() or nxt.isdigit() or not prev or not nxt:
        return True
    if not prev.isalpha() or not nxt.isalpha():
        return True
    return False


def _leading_fillers(text: str, spans, fillers) -> int:
    allowed = {_norm_word(str(word)) for word in (fillers or ())}
    count = 0
    for start, end in spans:
        if _norm_word(text[start:end]) not in allowed:
            break
        count += 1
    return count


def _signature(text: str, fillers=()) -> tuple[tuple[int, str], ...]:
    text = unicodedata.normalize('NFKC', str(text or ''))
    spans = [(m.start(), m.end()) for m in _WORD.finditer(text)]
    starts = [start for start, _ in spans]
    filler_count = _leading_fillers(text, spans, fillers)
    date_separators = {
        i for match in _DATE.finditer(text)
        for i in range(match.start(), match.end()) if text[i] in '.-/'
    }

    def anchor(index):
        return max(0, bisect_right(starts, index) - filler_count)

    marks = []
    for i, char in enumerate(text):
        if char in ('-', '−', '–', '—') and i not in date_separators \
                and (char == '−' or _dash_is_semantic(text, i)):
            marks.append((anchor(i), 'minus'))
        elif char in ('%', '‰'):
            marks.append((anchor(i), 'percent' if char == '%' else 'permille'))
        elif char in (',', '.') and i > 0 and i + 1 < len(text) \
                and i not in date_separators and text[i - 1].isdigit() and text[i + 1].isdigit():
            marks.append((anchor(i), 'numeric_separator'))
        elif char in '*/×÷=<>≤≥^':
            mark = {'×': 'multiply', '*': 'multiply', '÷': 'divide', '/': 'divide',
                    '≤': 'less_equal', '<': 'less', '≥': 'greater_equal', '>': 'greater',
                    '^': 'power'}.get(char, char)
            marks.append((anchor(i), mark))
        elif char == '+':
            marks.append((anchor(i), 'plus'))
    return tuple(marks)


def ack_symbols_compatible(heard: str, portion: str, fillers=()) -> bool:
    """Check semantic marks, with optional leading filler words ignored in offsets."""
    heard_text = unicodedata.normalize('NFKC', str(heard or ''))
    portion_text = unicodedata.normalize('NFKC', str(portion or ''))
    heard_signature = _signature(heard_text, fillers)
    portion_signature = _signature(portion_text, fillers)
    if heard_signature == portion_signature:
        return True
    portion_words = len(_WORD.findall(portion_text))
    if portion_words and len(_WORD.findall(heard_text)) == 2 * portion_words:
        repeated = portion_signature + tuple((index + portion_words, mark)
                                               for index, mark in portion_signature)
        return heard_signature == repeated
    return False
