"""ERROR_PATTERNS (owner: «сам защищался от целых классов ошибок»): classes of a weak model's edit mistakes, each
with what the factory does about it. A 'repair' applies only when exactly ONE place of the file matches; a 'note'
tells the next attempt what to do instead. Written by gemini-3.5-flash-lite from the coordinator's tests; collapsed_match,
repair and hints corrected by the coordinator after 4 passes (blank lines around a place counted as other places, a
substring inside a longer line counted as a match, the hint text)."""
import ast
import difflib
import io
import math
import re
import tokenize
from collections import Counter

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
    ('guessed-line', 'note', 'a SEARCH line that is nowhere in the file: the note names it and the closest real line'),
    ('unseen-target', 'note', "a SEARCH aimed at a definition the prompt did not show whole (63 of 96 failed blocks, "
                              "replay 20.11 07:10): the note asks for it (\"function 'name' was not shown whole\") and "
                              'the next candidate is shown it first and whole'),
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


def near_merge(text: str, search: str, replace: str):
    """The last repair of a SEARCH block that matched nowhere: it drifted from the file (a line misremembered or
    retyped), but one region of the file still holds at least half of its non-blank lines (and 2). Each SEARCH line
    equal to a file line votes for the shift between them; the 12 most voted shifts are tried with a margin of a
    quarter of the block, and no region apart from the chosen one may match as many lines. The edit is then merged
    like diff3 (base = SEARCH, ours = the file region, theirs = REPLACE): between two lines stable on both sides,
    ours == base takes theirs, theirs == base or ours == theirs takes ours, anything else is a conflict (None); stable
    lines are written from ours. Written by a free model in the self-build queue (20.11, its tests passed); the
    coordinator's review added one rule: the same region found from two shifts is one region (two equal SEARCH lines
    in a row voted two shifts and the region read as two, test_two_equal_lines_in_a_row_are_one_place)."""

    def clean_lines(s: str) -> list:
        lines = [line.rstrip() for line in s.split('\n')]
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        return lines

    search_lines = clean_lines(search)
    replace_lines = clean_lines(replace)
    if not search_lines:
        return None

    file_lines = text.split('\n')
    n = len(search_lines)
    s = max(1, n // 4)

    # Vote for offsets
    votes = []
    for k, s_line in enumerate(search_lines):
        if not s_line:
            continue
        for q, f_line in enumerate(file_lines):
            if f_line.rstrip() == s_line:
                votes.append(q - k)

    if not votes:
        return None

    counts = Counter(votes)
    top_offsets = [off for off, _ in counts.most_common(12)]

    places = []
    for p in top_offsets:
        win_start = max(0, p - s)
        win_end = min(len(file_lines), p + n + s)
        window = file_lines[win_start:win_end]

        matcher = difflib.SequenceMatcher(None, search_lines, window, autojunk=False)
        matching_blocks = matcher.get_matching_blocks()

        matched_non_blank = 0
        first_match_info = None
        last_match_info = None

        for si, wi, blen in matching_blocks:
            for b_idx in range(blen):
                s_idx = si + b_idx
                w_idx = wi + b_idx
                if s_idx < n and search_lines[s_idx]:
                    matched_non_blank += 1
                    if first_match_info is None:
                        first_match_info = (s_idx, w_idx)
                    last_match_info = (s_idx, w_idx)

        min_matched = max(2, math.ceil(0.5 * sum(1 for l in search_lines if l)))
        if matched_non_blank < min_matched or first_match_info is None:
            continue

        fs_idx, fw_idx = first_match_info
        ls_idx, lw_idx = last_match_info

        a = win_start + fw_idx - fs_idx
        b = win_start + lw_idx + (n - 1 - ls_idx) + 1

        a = max(0, min(a, len(file_lines)))
        b = max(a, min(b, len(file_lines)))

        places.append((a, b, matched_non_blank))

    places = sorted(set(places))   # one region found from two shifts is one region
    if not places:
        return None

    # a region no other region apart from it (not overlapping it) matches as well as; of those, the best matched
    valid_places = []
    for i, (a1, b1, m1) in enumerate(places):
        is_best = True
        for j, (a2, b2, m2) in enumerate(places):
            if i == j:
                continue
            overlapping = max(a1, a2) < min(b1, b2)
            if not overlapping and m2 >= m1:
                is_best = False
                break
        if is_best:
            valid_places.append((a1, b1, m1))
    top = max((m for _, _, m in valid_places), default=0)
    valid_places = [p for p in valid_places if p[2] == top]
    if len(valid_places) != 1:
        return None

    a, b, _ = valid_places[0]
    ours = file_lines[a:b]
    base = search_lines
    theirs = replace_lines

    def get_diff3_merged(base, ours, theirs):
        # Find matching blocks between base and ours, and base and theirs
        m_ours = dict() # base_idx -> ours_idx if equal/matched
        m_theirs = dict()

        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, ours, autojunk=False).get_opcodes():
            if tag == 'equal':
                for bi, oi in zip(range(i1, i2), range(j1, j2)):
                    m_ours[bi] = oi

        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, theirs, autojunk=False).get_opcodes():
            if tag == 'equal':
                for bi, ti in zip(range(i1, i2), range(j1, j2)):
                    m_theirs[bi] = ti

        # a base line matched both to ours and to theirs is stable
        stable_base = []
        for bi in range(len(base)):
            if bi in m_ours and bi in m_theirs:
                if ours[m_ours[bi]] == base[bi] and theirs[m_theirs[bi]] == base[bi]:
                    stable_base.append(bi)

        stable_base = [-1] + sorted(stable_base) + [len(base)]   # virtual stable points at both ends

        merged = []
        for idx in range(len(stable_base) - 1):
            b_start = stable_base[idx]
            b_end = stable_base[idx + 1]
            if b_start != -1:
                merged.append(ours[m_ours[b_start]])   # a stable line is written from ours
            chunk_base = base[b_start + 1 : b_end]
            o_start = m_ours[b_start] + 1 if b_start != -1 else 0
            o_end = m_ours[b_end] if b_end != len(base) else len(ours)
            chunk_ours = ours[o_start:o_end]

            t_start = m_theirs[b_start] + 1 if b_start != -1 else 0
            t_end = m_theirs[b_end] if b_end != len(base) else len(theirs)
            chunk_theirs = theirs[t_start:t_end]

            if chunk_ours == chunk_base:
                merged.extend(chunk_theirs)
            elif chunk_theirs == chunk_base or chunk_ours == chunk_theirs:
                merged.extend(chunk_ours)
            else:
                return None

        return merged

    merged_lines = get_diff3_merged(base, ours, theirs)
    if merged_lines is None:
        return None

    return '\n'.join(file_lines[:a] + merged_lines + file_lines[b:])


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
    if span is not None:
        i, j = span
        return '\n'.join(lines[:i] + replace.split('\n') + lines[j + 1:])
    return near_merge(text, search, replace)


HEADER = re.compile(r'^\s*(?:L\d+-\d+ )?(?:async def|def|class)\s+(\w+)')
AIM_LINES = 2     # without a header line, a definition holding this many of the SEARCH lines is the one aimed at


def aimed_definition(text: str, search: str):
    """(name, lines of its text) of the ONE definition of ``text`` a SEARCH aims at: the one a header line (or an
    OUTLINE row) of the SEARCH names, else the smallest holding AIM_LINES or more of its lines; None when the SEARCH
    names a definition the file does not have (invented code) or holds too few of its lines."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    lines = text.split('\n')
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]

    def body(node):
        first = min([node.lineno] + [d.lineno for d in node.decorator_list])
        return lines[first - 1:node.end_lineno]
    for line in search.split('\n'):
        m = HEADER.match(line)
        if m:
            same = [n for n in nodes if n.name == m.group(1)]
            return (same[0].name, body(same[0])) if same else None
    wanted = {x.strip() for x in search.split('\n') if x.strip()}
    holding = [n for n in nodes if len(wanted & {x.strip() for x in body(n)}) >= AIM_LINES]
    if not holding:
        return None
    best = min(holding, key=lambda n: n.end_lineno - n.lineno)
    return best.name, body(best)


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
