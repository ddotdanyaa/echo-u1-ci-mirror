"""Bounded UTF-8 context. Bytes are a conservative estimate, not provider usage."""
import ast
import os
import re
from pathlib import Path

from .agent_factory import InvalidPlan, redact


def _lines(source: str) -> list:
    """Lines the way ast counts them: \n, \r\n and \r only (str.splitlines also cuts at \x0c, U+2028...)."""
    return re.split(r'\r\n|\r|\n', source)


def slice_source(name: str, source: str, target: str) -> str:
    lines = _lines(source)
    if name.endswith('.py'):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Broken source is still useful repair input; never parse other formats.
            tree = None
        if tree is not None:
            definitions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            selected = next((n for n in definitions if n.name == target), None)
            if selected is not None:
                imports = [ast.get_source_segment(source, n) for n in tree.body
                           if isinstance(n, (ast.Import, ast.ImportFrom))]
                calls = {n.func.id for n in ast.walk(selected)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                signatures = []
                for node in definitions:
                    if node.name in calls and node is not selected:
                        if isinstance(node, ast.ClassDef):
                            signatures.append(f'class {node.name}: ...')
                        else:
                            prefix = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
                            signatures.append(f'{prefix} {node.name}({ast.unparse(node.args)}): ...')
                start = min([selected.lineno] + [d.lineno for d in selected.decorator_list])
                return '\n'.join(imports + signatures + lines[start - 1:selected.end_lineno])
    if re.fullmatch(r'\d+:\d+', target):
        start, end = map(int, target.split(':'))
        if start < 1 or end < start:
            raise InvalidPlan('invalid context line range')
        return '\n'.join(lines[max(0, start - 4):end + 3])
    # An unknown selector must not silently discard required source.
    return source


def packet(files: dict[str, bytes], targets: dict[str, str], *, max_tokens: int) -> str:
    sections = []
    for name, data in sorted(files.items()):
        text = data.decode('utf-8')
        if name in targets:
            text = slice_source(name, text, targets[name])
        sections.append(f'FILE {name}\n{text}')
    result = '\n\n'.join(sections)
    if len(result.encode('utf-8')) > max_tokens:
        raise InvalidPlan('context exceeds conservative token budget; narrow task scope')
    return result


# ---- big files: outline + selected fragments instead of the whole text -------------------------------
LARGE_FILE_CHARS = 12000     # a touch/read file above this is shown as outline + fragments, never whole
OUTLINE_MAX_CHARS = 7000
FRAGMENT_MAX_CHARS = 6000
WINDOW_MAX_LINES = 40        # one window of a large definition (merged hits); more hits make more windows
GAP_FILL_LINES = 8           # unseen lines between two shown parts up to this many are shown too (room permitting)
MIN_VIEW_CHARS = 1500
READ_HINT = ("The file is large: read the places you need with the read tool by line numbers (offset/limit) "
             "from the outline; edit only the files listed in touch_files.")


STOP_WORDS = frozenset(("self", "cls", "test", "tests", "assert", "return", "none", "true", "false"))


def keywords_from(*texts, strict: bool = True) -> set:
    """Identifiers (unicode letters allowed). ``strict`` drops service words: use it for the text of tests
    and diffs; names the task title, goal or feedback gives are never filtered (strict=False)."""
    words: set = set()
    for text in texts:
        for word in re.findall(r'[^\W\d]\w*', text or '', re.UNICODE):
            if len(word) >= 3 and not (strict and word.lower() in STOP_WORDS):
                words.add(word)
    return words


def _sig(node) -> str:
    if isinstance(node, ast.ClassDef):
        return 'class ' + node.name
    prefix = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
    try:
        return '%s %s(%s)' % (prefix, node.name, ast.unparse(node.args))
    except Exception:  # noqa: BLE001
        return '%s %s(...)' % (prefix, node.name)


def _definitions(tree):
    """(depth, node) for top-level defs/classes and the methods of top-level classes."""
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in tree.body:
        if isinstance(node, kinds):
            yield 0, node
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield 1, sub


def outline(source: str, max_chars: int = OUTLINE_MAX_CHARS, tools: bool = True) -> str:
    """Table of contents of a python module: top-level defs/classes and methods with line ranges.
    ``tools=False``: the reader has no read tool (the light engine), so no "read it" instructions."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return '(the file does not parse; read it by line numbers)' if tools else '(the file does not parse)'
    rows = ['%sL%d-%d %s' % ('  ' * depth, node.lineno, node.end_lineno, _sig(node))
            for depth, node in _definitions(tree)]
    text, used = [], 0
    for i, row in enumerate(rows):
        if used + len(row) + 1 > max_chars:
            text.append(('... %d more definitions (read the file by line numbers)' if tools else
                         '... %d more definitions are not shown') % (len(rows) - i))
            break
        text.append(row)
        used += len(row) + 1
    return '\n'.join(text)


FILE_EXTENSIONS = frozenset(("py", "md", "json", "yaml", "yml", "txt", "toml", "cfg", "ini", "csv", "log",
                             "html", "xml", "js", "ts"))


def identifier_tokens(text: str) -> set:
    """Identifier-like tokens of a free text: with an underscore, CamelCase or dotted (a.b gives a and b);
    plain prose words are not identifiers and never select a fragment."""
    found: set = set()
    text = text or ''
    for m in re.finditer(r'[^\W\d]\w*(?:\.[^\W\d]\w*)+', text):
        parts = m.group(0).split('.')
        called = text[m.end():m.end() + 1] == '('          # obj.log(...) is a call, never a file name
        if parts[-1].lower() in FILE_EXTENSIONS and not called:
            # only "log" is also an attribute name: Task.log, self.logger.log are code; Notes.md, app.config.json are not
            if parts[-1].lower() == 'log' and (len(parts) >= 3 or (parts[0][:1].isupper() and not parts[0].isupper())):
                parts = parts[:-1]
            else:
                continue
        found |= {p for p in parts if len(p) >= 3}
    for m in re.finditer(r'[^\W\d]\w*', text):
        word = m.group(0)
        if re.match(r'\.(?:' + '|'.join(sorted(FILE_EXTENSIONS)) + r')\b', text[m.end():], re.I):
            continue                    # agent_factory_runner.py: a file name, not an identifier
        if len(word) >= 3 and ('_' in word or re.search(r'[a-z][A-Z]', word)
                               or re.match(r'[A-Z][a-z]+[A-Z]', word)):
            found.add(word)
    return found


class _Assigned:
    """A module-level assignment shown like a definition (it has no decorators)."""
    def __init__(self, name, node):
        self.name, self.decorator_list = name, []
        self.lineno, self.end_lineno = node.lineno, node.end_lineno


def _imports(source: str) -> str:
    """The module's top-level import statements as written (a guessed import is a SEARCH not found)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ''
    lines = _lines(source)
    return '\n'.join('\n'.join(lines[n.lineno - 1:n.end_lineno]) for n in tree.body
                     if isinstance(n, (ast.Import, ast.ImportFrom)))[:1500]


def _fragments(source: str, keywords: set, room: int, priority: frozenset = frozenset(),
               tools: bool = True) -> str:
    """Selected definitions as they are. Python fragments are deliberately NOT redacted: redaction could
    corrupt code, and secrets never enter the work copy (forbidden paths, .env). Non-.py heads are redacted."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ''
    lines = _lines(source)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    named = {p for p in priority if p in defined or identifier_tokens(p)}
    candidates = [node for depth, node in _definitions(tree) if node.name in keywords]
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in keywords:
                candidates.append(_Assigned(name, node))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name in keywords:
                candidates.append(_Assigned(name, node))
    # names from the task title / goal / feedback first, names only the test mentions after them;
    # a method the title names is taken BEFORE the class the test names (no nesting loss)
    spans = [(n.lineno, n.end_lineno) for n in candidates if n.name in priority]
    candidates.sort(key=lambda n: (0 if n.name in priority or any(a <= n.lineno and n.end_lineno <= b for a, b in spans) else 1, n.end_lineno - n.lineno, n.lineno))
    picked, taken, used = [], set(), 0
    spans = []        # (start, end, name, part): what is shown; _joined() closes the small gaps between them
    for node in candidates:
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        node_lines = list(range(start, node.end_lineno + 1))
        if any(ln in taken for ln in node_lines):   # a container of a shown part is not pulled in on top of it
            continue
        full_body = '\n'.join(lines[start - 1:node.end_lineno])
        piece = '# %s, lines %d-%d\n%s' % (node.name, start, node.end_lineno, full_body)
        if len(full_body) <= FRAGMENT_MAX_CHARS and used + len(piece) + 2 <= room:
            picked.append((start, piece))
            spans.append((start, node.end_lineno, node.name, False))
            used += len(piece) + 2
            taken.update(node_lines)
        else:
            nested = {n.name for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))} if isinstance(node, ast.AST) else {node.name}
            active_keywords = (identifier_tokens(' '.join(sorted(keywords))) | (keywords & nested)) or keywords
            def_lines_sub = lines[start - 1:node.end_lineno]
            targets = []
            for i, l in enumerate(def_lines_sub, start):
                if i in taken:
                    continue
                if any(re.search(r'\b' + re.escape(k) + r'\b', l) for k in active_keywords):
                    targets.append(i)
            if not targets:
                continue
            raw_windows = []
            for t in targets:
                w_start, w_end = max(start, t - 12), min(node.end_lineno, t + 12)
                if raw_windows and w_start <= raw_windows[-1][1] + 1:
                    if w_end - raw_windows[-1][0] < WINDOW_MAX_LINES:     # dense hits: several windows, not one giant
                        raw_windows[-1] = (raw_windows[-1][0], max(raw_windows[-1][1], w_end))
                        continue
                    w_start = raw_windows[-1][1] + 1                       # the next window starts where it ends
                    if w_start > w_end:
                        continue
                raw_windows.append((w_start, w_end))
            scored_windows = []
            for w_s, w_e in raw_windows:
                w_lines = range(w_s, w_e + 1)
                p_count = sum(1 for p_name in named if any(re.search(r'\b' + re.escape(p_name) + r'\b', lines[ln - 1]) for ln in w_lines))
                t_count = sum(1 for ln in w_lines if ln in targets)
                score = (p_count, t_count)   # a named part first, however many plain hits a big block has
                scored_windows.append((score, w_s, w_e))
            scored_windows.sort(key=lambda item: item[0], reverse=True)   # stable: ties keep the earlier window
            chosen, piece_len = [], 0
            for _, w_start, w_end in scored_windows:            # chosen by score, shown in line order
                w_piece = '# %s, lines %d-%d (part)\n%s' % (node.name, w_start, w_end,
                                                           '\n'.join(lines[w_start - 1:w_end]))
                extra = len(w_piece) + (2 if chosen else 0)
                if used + piece_len + extra > room or piece_len + extra > FRAGMENT_MAX_CHARS:
                    continue                                    # one big definition never eats the room
                chosen.append((w_start, w_piece))
                spans.append((w_start, w_end, node.name, True))
                piece_len += extra
                taken.update(range(w_start, w_end + 1))
            piece = '\n\n'.join(p for _, p in sorted(chosen))
            if piece:
                picked.append((start, piece))
                used += piece_len
    return _joined(spans, lines, max(0, room - used))


def _joined(spans, lines, spare: int) -> str:
    """The shown parts in line order. Parts whose unseen gap is at most GAP_FILL_LINES lines become ONE contiguous
    part, gap included, while ``spare`` characters allow it; overlapping parts are shown once. 19.11 23:59: a SEARCH
    copied across two parts with a try/except unseen between them matched nothing, 4 passes in a row, twice."""
    merged = []
    for start, end, name, part in sorted(spans):
        if merged:
            m_start, m_end, m_name, m_part = merged[-1]
            cost = sum(len(lines[i - 1]) + 1 for i in range(m_end + 1, start))
            if start <= m_end + 1 + GAP_FILL_LINES and cost <= spare:
                spare -= cost
                merged[-1] = (m_start, max(m_end, end), m_name, m_part or part)
                continue
        merged.append((start, end, name, part))
    return '\n\n'.join('# %s, lines %d-%d%s\n%s' % (name, start, end, ' (part)' if part else '',
                                                  '\n'.join(lines[start - 1:end]))
                       for start, end, name, part in merged)


def large_view(name: str, source: str, keywords: set, room: int, priority: frozenset = frozenset(),
               hint: str = READ_HINT, tools: bool = True) -> str:
    """Outline + the definitions whose names are mentioned, within ``room`` characters."""
    lines = len(_lines(source))
    head = 'FILE %s (LARGE: %d lines, %d chars; outline and selected parts only)\n%s' % (
        name, lines, len(source), hint)
    if name.endswith('.py'):
        imports = _imports(source)
        toc = outline(source, min(OUTLINE_MAX_CHARS, max(300, room // 2)), tools)
        body = head + ('\nIMPORTS\n' + imports if imports else '') + '\nOUTLINE\n' + toc
        frag = _fragments(source, keywords, max(0, room - len(body) - 40), priority, tools)
        return body + ('\nSELECTED PARTS\n' + frag if frag else '')
    return head + '\nHEAD OF THE FILE\n' + redact(source)[:max(300, min(3000, room - len(head) - 40))]


def render(files: dict, targets: dict, *, large: set, keywords: set, budget_chars: int,
           small_tokens: int, priority: frozenset = frozenset(), hint: str = READ_HINT, tools: bool = True) -> str:
    """Prompt body: small files whole (as ``packet`` does), large ones as outline + fragments. ``tools=False``
    for a reader without a read tool (the light engine): no "read it" instructions anywhere in the body."""
    small = {n: v for n, v in files.items() if n not in large}
    sections = [packet(small, targets, max_tokens=small_tokens)] if small else []
    used = sum(len(s) for s in sections)
    big = sorted(n for n in files if n in large)
    if big:
        room = (budget_chars - used - 2 * len(big)) // len(big)
        if room < MIN_VIEW_CHARS:
            raise InvalidPlan('context exceeds the prompt budget even with outlines; split the task')
        for n in big:
            text = files[n].decode('utf-8', 'replace')
            if n in targets:   # an explicit selector: show that slice when it fits, not the outline
                try:
                    cut = slice_source(n, text, targets[n])
                except InvalidPlan:
                    cut = None
                if cut is not None and len(cut) <= room:
                    sections.append('FILE %s (slice %s of a large file)\n%s' % (n, targets[n], cut))
                    continue
            sections.append(large_view(n, text, keywords, room, priority, hint, tools))
    elif used > budget_chars:
        raise InvalidPlan('context exceeds the prompt budget; split the task')
    return '\n\n'.join(sections)


# ---- local paths must not leave the machine inside a prompt ------------------------------------------
_PATH_TAIL = r"""([^\s'"():,;<>|*?]*)"""
_BS = chr(92)


def _forms(path) -> list:
    text = str(path).rstrip('/' + _BS)
    return sorted({text, text.replace(_BS, '/'), text.replace('/', _BS)}, key=len, reverse=True)


def _replace_root(text: str, root, mark: str) -> str:
    for form in _forms(root):
        if len(form) < 4:       # never turn "/" or "C:" into a marker
            continue
        text = re.sub(re.escape(form) + r"""(?=[\\/]|$|[\s'"():,;<>|*?]|[.!?,](?:\s|$))""" + '[' + _BS + _BS + '/]*' + _PATH_TAIL,
                      lambda m: mark + m.group(1).replace(_BS, '/'), text, flags=re.I)
    return text


def scrub_paths(text, repo_roots=()) -> str:
    """Local paths of the machine out of a text bound for an external model: copies of the repository
    (``repo_roots``, factory-base-*/factory-gate-tree-*) become ``<repo>/...``; the home directory,
    %TEMP%/%LOCALAPPDATA% and any ``C:\\Users\\<name>`` / ``/home/<name>`` become ``~``."""
    text = str(text)
    for root in sorted((str(r) for r in repo_roots if r), key=len, reverse=True):
        text = _replace_root(text, root, '<repo>/')
    text = re.sub(r"""[^\s'"]*factory-(?:base|gate-tree|junit|review|kilo-home)[-\w]*[\\/]+(?:tree[\\/]+)?""" + _PATH_TAIL,
                  lambda m: '<repo>/' + m.group(1).replace(_BS, '/'), text, flags=re.I)
    homes = {str(Path.home())}
    homes |= {os.environ[k] for k in ('USERPROFILE', 'HOME', 'TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA') if os.environ.get(k)}
    for home in sorted(homes, key=len, reverse=True):
        text = _replace_root(text, home, '~/')
    # the profile name: one word, or up to three when a path separator follows ("John van Smith\AppData");
    # prose after a bare name is never swallowed. Windows forms ignore case, POSIX forms do not (/users/42 is a route)
    seg = r"""(?:[^\\/\s'":]+(?: [^\\/\s'":]+){0,2}(?=[\\/])|[^\\/\s'":]+)"""
    text = re.sub(r"""[A-Za-z]:[\\/]+Users[\\/]+""" + seg, '~', text, flags=re.I)
    text = re.sub(r"""(?<![\w.])(?:/mnt)?/[A-Za-z]/Users/""" + seg, '~', text, flags=re.I)   # /c/Users/x, /mnt/c/Users/x
    return re.sub(r"""(?<![\w.])/(?:home|Users)/""" + seg, '~', text)
