"""ERROR_PATTERNS (owner: «сам защищался от целых классов ошибок»): classes of a weak model's edit mistakes, each
with what the factory does about it. A 'repair' applies only when exactly ONE place of the file matches; a 'note'
tells the next attempt what to do instead. Written by gemini-3.5-flash-lite from the coordinator's tests; collapsed_match,
repair and hints corrected by the coordinator after 4 passes (blank lines around a place counted as other places, a
substring inside a longer line counted as a match, the hint text)."""
import re

VIEW_LINE = re.compile(r'^\s*(?:# [\w.]+, lines \d+-\d+(?: \(part\))?|FILE \S+.*|OUTLINE|SELECTED PARTS|IMPORTS|HEAD OF THE FILE)\s*$')

PATTERNS = (
    ('view-line', 'repair', 'a line of the prompt view, not of the file, copied into SEARCH: dropped'),
    ('reflow', 'repair', 'lines joined or wrapped differently than the file: matched with whitespace collapsed'),
    ('indent-shift', 'repair', 'one uniform indent added or removed: agent_factory_runner._replace_shifted'),
    ('elided', 'note', "SEARCH shortened with '...': the next attempt is told to copy whole lines"),
    ('guessed-line', 'note', 'a SEARCH line that is nowhere in the file: the note names it'),
)


def strip_view_lines(search: str, replace: str) -> tuple:
    """Both texts without the lines of the prompt view; the number of lines dropped from the search."""
    search_lines = search.split('\n')
    replace_lines = replace.split('\n')
    kept_search = [line for line in search_lines if not VIEW_LINE.fullmatch(line)]
    kept_replace = [line for line in replace_lines if not VIEW_LINE.fullmatch(line)]
    return '\n'.join(kept_search), '\n'.join(kept_replace), len(search_lines) - len(kept_search)


def _collapse(text: str) -> str:
    return ' '.join(text.split())


def _line_starts(lines) -> dict:
    """The index of the first word of every non-blank line, counted over the words of all the lines -> that line's
    leading whitespace."""
    starts, words = {}, 0
    for line in lines:
        count = len(line.split())
        if count:
            starts[words] = line[:len(line) - len(line.lstrip())]
            words += count
    return starts


def collapsed_match(text: str, search: str):
    """0-based (first, last) lines of the ONE place of ``text`` (whole lines, starting on a non-blank line, ending as
    soon as it is complete) whose whitespace-collapsed text equals the collapsed ``search``, and where every line that
    starts on the same word in both keeps its indent: a reflow moves line breaks, it never re-indents a statement
    ('x = 1' for '    x = 1' is an uneven shift, test_an_uneven_shift_is_no_match). None when there is no such
    place, more than one, or the search is blank."""
    want = _collapse(search)
    if not want:
        return None
    ours = _line_starts(search.split('\n'))
    lines = text.split('\n')
    found = []
    for i, first in enumerate(lines):
        if not first.strip():
            continue
        got = ''
        for j in range(i, len(lines)):
            got = _collapse(got + ' ' + lines[j])
            if got == want:
                theirs = _line_starts(lines[i:j + 1])
                if all(theirs[k] == lead for k, lead in ours.items() if k in theirs):
                    found.append((i, j))
                break
            if not want.startswith(got):
                break
    return found[0] if len(found) == 1 else None


def repair(text: str, search: str, replace: str):
    """The view lines dropped, then the search matched as whole lines (trailing spaces aside) at exactly one place,
    else as one reflowed place; None when neither is unique. A substring inside a longer line is never a match."""
    search, replace, _ = strip_view_lines(search, replace)
    if not search.strip():
        return None
    lines = text.split('\n')
    want = [line.rstrip() for line in search.split('\n')]
    while want and not want[-1]:
        want.pop()
    while want and not want[0]:
        want.pop(0)
    n = len(want)
    hits = [i for i in range(len(lines) - n + 1) if [line.rstrip() for line in lines[i:i + n]] == want]
    if len(hits) == 1:
        return '\n'.join(lines[:hits[0]] + replace.split('\n') + lines[hits[0] + n:])
    if hits:
        return None
    span = collapsed_match(text, search)
    if span is None:
        return None
    i, j = span
    return '\n'.join(lines[:i] + replace.split('\n') + lines[j + 1:])


def hints(blocks) -> list:
    """One instruction per block whose SEARCH was shortened with an ellipsis: there is no safe repair for it."""
    return ["block %d (%s): SEARCH must not shorten code with '...': copy whole lines exactly" % (n, name)
            for n, (name, search, _) in enumerate(blocks, 1) if '...' in search or '…' in search]
