"""ERROR_PATTERNS (owner: «сам защищался от целых классов ошибок»): classes of a weak model's edit mistakes, each
with what the factory does about it. A 'repair' applies only when exactly ONE place of the file matches; a 'note'
tells the next attempt what to do instead. Written by gemini-3.5-flash-lite from the coordinator's tests; collapsed_match,
repair and hints corrected by the coordinator after 4 passes (blank lines around a place counted as other places, a
substring inside a longer line counted as a match, the hint text)."""
import ast
import io
import re
import tokenize

VIEW_LINE = re.compile(r'^\s*(?:# [\w.]+, lines \d+-\d+(?: \(part\))?|FILE \S+.*|OUTLINE|SELECTED PARTS|IMPORTS|HEAD OF THE FILE)\s*$')
# a row of the view's OUTLINE (factory_context.outline: a line range label, then 'def name(args)'), label or not
OUTLINE_ROW = re.compile(r'\s*(?:L(\d+)-(\d+) )?((?:async def|def|class) \w+.*?)\s*')
LABELED_ROW = re.compile(r'^\s*L\d+-\d+ (?:async def|def|class) (\w+)', re.M)
# a header with no colon (a def line closed by ')' or a bare 'class X') is never python: a row, labeled or not
ROW_LIKE = re.compile(r'^\s*(?:L\d+-\d+ )?(?:async def|def|class) (\w+)(?:\(.*\))?[ \t]*$', re.M)

PATTERNS = (
    ('view-line', 'repair', 'a line of the prompt view, not of the file, copied into SEARCH: dropped'),
    ('outline-row', 'repair', "a row of the view's OUTLINE (a line range label, then 'def f(a, b)': no colon, no "
                              'annotation) in SEARCH and REPLACE: the real header lines of that one definition'),
    ('reflow', 'repair', 'lines joined or wrapped differently than the file: matched with whitespace collapsed'),
    ('indent-shift', 'repair', 'one uniform indent added or removed: agent_factory_runner._replace_shifted'),
    ('elided', 'note', "SEARCH shortened with '...': the next attempt is told to copy whole lines"),
    ('guessed-line', 'note', 'a SEARCH line that is nowhere in the file: the note names it'),
    ('inline-thought', 'repair', 'reasoning written into the answer (<thought>, Gemma 4): every light call asks for '
                                 'none (agent_factory_runner.NO_THOUGHT), a leading block is stripped'),
)


def strip_view_lines(search: str, replace: str) -> tuple:
    """Both texts without the lines of the prompt view; the number of lines dropped from the search."""
    search_lines = search.split('\n')
    replace_lines = replace.split('\n')
    kept_search = [line for line in search_lines if not VIEW_LINE.fullmatch(line)]
    kept_replace = [line for line in replace_lines if not VIEW_LINE.fullmatch(line)]
    return '\n'.join(kept_search), '\n'.join(kept_replace), len(search_lines) - len(kept_search)


def _header_ends(text: str) -> dict:
    """1-based line of every 'def'/'class' keyword -> 1-based line of the ':' that closes its header (tokens, so a
    bracket or a colon inside a string, a default lambda or an annotation never ends it)."""
    ends, start, depth = {}, None, 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.NAME and tok.string in ('def', 'class') and start is None:
                start, depth = tok.start[0], 0
            elif start is not None and tok.type == tokenize.OP:
                if tok.string in ('(', '[', '{'):
                    depth += 1
                elif tok.string in (')', ']', '}'):
                    depth -= 1
                elif tok.string == ':' and depth == 0:
                    ends[start] = tok.start[0]
                    start = None
    except (tokenize.TokenError, SyntaxError):
        pass
    return ends


def _outline_rows(text: str) -> list:
    """(row, lineno, end_lineno, first, last) of every definition the view's OUTLINE shows: ``row`` its text there
    after the label (factory_context._sig, the one renderer), first..last the 0-based lines of the real header."""
    from .factory_context import _definitions, _sig
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    ends = _header_ends(text)
    return [(_sig(node), node.lineno, node.end_lineno, node.lineno - 1, ends[node.lineno] - 1)
            for _, node in _definitions(tree) if node.lineno in ends]


def expand_outline_rows(text: str, search: str, replace: str):
    """A SEARCH line that is a row of the view's OUTLINE (label or not) becomes the real header lines of the ONE
    definition it names (the label decides between equal rows), the same row in REPLACE the same lines: an edit inside
    a function that keeps its header. (search, replace), unchanged when SEARCH has no row; None when a row names no
    single definition, REPLACE lacks a row of SEARCH (the model rewrote the function or its signature: replacing only
    the header would leave the old body, live 20.11 probe: 2 of 11 such blocks did not compile) or REPLACE carries a
    row SEARCH has not (no python, never put into the file)."""
    if not any(OUTLINE_ROW.fullmatch(x) for x in search.split('\n')):
        return search, replace
    rows = _outline_rows(text)
    if not rows:
        return search, replace
    lines = text.split('\n')
    seen = {}

    def header(line):
        m = OUTLINE_ROW.fullmatch(line)
        if not m:
            return None
        same = [r for r in rows if r[0] == m.group(3)]
        if m.group(1):
            labeled = [r for r in same if (r[1], r[2]) == (int(m.group(1)), int(m.group(2)))]
            same = labeled or same
        if not same:
            return None
        if len(same) > 1:
            raise LookupError(line)
        return '\n'.join(lines[same[0][3]:same[0][4] + 1])

    try:
        out = []
        for line in search.split('\n'):
            real = header(line)
            if real is not None:
                seen[OUTLINE_ROW.fullmatch(line).group(3)] = real
            out.append(line if real is None else real)
        new_replace, kept = [], set()
        for line in replace.split('\n'):
            m = OUTLINE_ROW.fullmatch(line)
            if m and m.group(3) in seen:
                new_replace.append(seen[m.group(3)])
                kept.add(m.group(3))
            elif LABELED_ROW.match(line) or (m and header(line) is not None):
                return None
            else:
                new_replace.append(line)
    except LookupError:
        return None
    if set(seen) - kept:
        return None
    return '\n'.join(out), '\n'.join(new_replace)


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
    expanded = expand_outline_rows(text, search, replace)
    if expanded is None:
        return None
    search, replace = expanded
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
    """One instruction per block with no safe repair: a SEARCH shortened with an ellipsis, a row of the OUTLINE that
    could not stand for its definition's header (a changed signature written as a row)."""
    found = []
    for n, (name, search, replace) in enumerate(blocks, 1):
        if '...' in search or '…' in search:
            found.append("block %d (%s): SEARCH must not shorten code with '...': copy whole lines exactly" % (n, name))
        row = ROW_LIKE.search(search) or ROW_LIKE.search(str(replace or ''))
        if row:
            found.append("block %d (%s): '%s' is a row of the OUTLINE, not a line of the file: keep it in REPLACE to "
                         "edit inside the function, else rewrite the whole function with REPLACE FUNCTION %s"
                         % (n, name, row.group(0).strip()[:60], row.group(1)))
    return found
