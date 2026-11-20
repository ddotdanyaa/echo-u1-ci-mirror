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


# A dotted name starts where no letter precedes it: inside a long word every start failed only after re-scanning the
# rest of the word (quadratic; live 20.11: one 29 000-character comment word cost 20 s per prompt). Linear now.
_DOTTED = re.compile(r'(?<![^\W\d])[^\W\d]\w*(?:\.[^\W\d]\w*)+')
_FILE_SUFFIX = re.compile(r'\.(?:' + '|'.join(sorted(FILE_EXTENSIONS)) + r')\b', re.I)


def identifier_tokens(text: str) -> set:
    """Identifier-like tokens of a free text: with an underscore, CamelCase or dotted (a.b gives a and b);
    plain prose words are not identifiers and never select a fragment."""
    found: set = set()
    text = text or ''
    for m in _DOTTED.finditer(text):
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
        if _FILE_SUFFIX.match(text, m.end()):
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
        self.node = node


def _uses(node) -> list:
    """The names a shown definition uses, in source order: the names it calls or reads and the attributes it reaches
    (self._step() gives '_step'). <id> fills the room left with the definitions these name."""
    node = getattr(node, 'node', node)
    found = sorted((sub.lineno, sub.col_offset, sub.id if isinstance(sub, ast.Name) else sub.attr)
                   for sub in ast.walk(node) if isinstance(sub, (ast.Name, ast.Attribute)))
    seen, names = set(), []
    for _, _, name in found:
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _imports(source: str) -> str:
    """The module's top-level import statements as written (a guessed import is a SEARCH not found)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ''
    lines = _lines(source)
    return '\n'.join('\n'.join(lines[n.lineno - 1:n.end_lineno]) for n in tree.body
                     if isinstance(n, (ast.Import, ast.ImportFrom)))[:1500]


# The code a model asked for: 'CANNOT: name' (the light rules ask for exactly that) and the runner's own refusal
# "function 'name' was not shown whole". Live 20.11 03:18, one task: three candidates answered CANNOT:
# _last_clause_question (28 lines of a 145 KB file) while smaller functions the task text names filled the room.
_ASKED = re.compile(r"CANNOT:\s*([A-Za-z_][\w.]*)|function '([A-Za-z_][\w.]*)' was not shown whole")


def asked_names(text: str) -> frozenset:
    """Names of the definitions a model asked to see in ``text`` (Class.method gives the method)."""
    return frozenset((a or b).split('.')[-1] for a, b in _ASKED.findall(text or ''))


# a failing test id of the gate (factory_gate: 'classname::name'; the name may carry a [parameter])
_FAILED_ID = re.compile(r'::([^\W\d]\w*)(?:\[[^\]\n]*\])?')


def failing_names(failing: str, sources: dict) -> frozenset:
    """The test functions the failing ids in ``failing`` name, with what each uses from its own file: the functions
    it calls, the fixtures it takes, the module names it reads. A big test file is shown as outline + parts and these
    parts first. ``sources``: name -> bytes of the task's test files."""
    names = set(_FAILED_ID.findall(failing or ''))
    if not names:
        return frozenset()
    used: set = set()
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for data in sources.values():
        try:
            tree = ast.parse(data.decode('utf-8', 'replace'))
        except SyntaxError:
            continue
        defined = {n.name for n in ast.walk(tree) if isinstance(n, kinds)}
        defined |= {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
                refs = {a.arg for a in node.args.args + node.args.kwonlyargs}
                refs |= {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}
                refs |= {sub.attr for sub in ast.walk(node) if isinstance(sub, ast.Attribute)}
                used |= (refs & defined) - {node.name}
    return frozenset(names | used)


def _fragments(source: str, keywords: set, room: int, priority: frozenset = frozenset(),
               tools: bool = True, asked: frozenset = frozenset()) -> str:
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
    # what the model asked for (nested ones too) before anything else, whole when the room allows
    listed = {id(n) for n in candidates}
    candidates += [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                   and n.name in asked and id(n) not in listed]
    # names from the task title / goal / feedback first, names only the test mentions after them;
    # a method the title names is taken BEFORE the class the test names (no nesting loss)
    spans = [(n.lineno, n.end_lineno) for n in candidates if n.name in priority]
    candidates.sort(key=lambda n: (0 if n.name in asked else 1 if n.name in priority or any(
        a <= n.lineno and n.end_lineno <= b for a, b in spans) else 2, n.end_lineno - n.lineno, n.lineno))
    picked, taken, used, shown = [], set(), 0, []
    spans = []        # (start, end, name, part): what is shown; _joined() closes the small gaps between them
    budgets = {}      # a windowed definition: what is left of its FRAGMENT_MAX_CHARS for the gaps
    # the words of each line once: '\bname\b' of a word name is "name is one of the line's words". Live 20.11: a test
    # file of 560 functions took over 30 s, one regex per (line, name) recompiled 224 665 times past re's cache
    words_of = [set(re.findall(r'\w+', line)) for line in lines]
    plain = identifier_tokens(' '.join(sorted(keywords)))
    odd = {k: re.compile(r'\b' + re.escape(k) + r'\b') for k in set(keywords) | plain | named
           if not re.fullmatch(r'\w+', k)}       # a name with other characters keeps its regex

    def hits(line_no, names) -> set:
        """The names of ``names`` that stand in line ``line_no`` as whole words."""
        found = names & words_of[line_no - 1]
        if odd:
            found = found | {k for k, p in odd.items() if k in names and p.search(lines[line_no - 1])}
        return found
    for node in candidates:
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        node_lines = list(range(start, node.end_lineno + 1))
        if any(ln in taken for ln in node_lines):   # a container of a shown part is not pulled in on top of it
            continue
        full_body = '\n'.join(lines[start - 1:node.end_lineno])
        piece = '# %s, lines %d-%d\n%s' % (node.name, start, node.end_lineno, full_body)
        if (len(full_body) <= FRAGMENT_MAX_CHARS or node.name in asked) and used + len(piece) + 2 <= room:
            picked.append((start, piece))
            spans.append((start, node.end_lineno, node.name, False))
            used += len(piece) + 2
            taken.update(node_lines)
            shown.append(node)
        else:
            nested = {n.name for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))} if isinstance(node, ast.AST) else {node.name}
            active_keywords = (plain | (keywords & nested)) or set(keywords)
            targets = [i for i in range(start, node.end_lineno + 1) if i not in taken and hits(i, active_keywords)]
            target_set = set(targets)
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
                p_count = len(set().union(*(hits(ln, named) for ln in w_lines)))
                t_count = sum(1 for ln in w_lines if ln in target_set)
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
                budgets[node.name] = FRAGMENT_MAX_CHARS - piece_len
                shown.append(node)
    used = _fill_by_uses(tree, lines, shown, taken, spans, used, room)
    return _joined(spans, lines, max(0, room - used), budgets)


def _fill_by_uses(tree, lines, shown, taken, spans, used: int, room: int) -> int:
    """<id> step 1 (verdict light-view-bound 20.11: 60% of the no-change answers needed code that was not shown while a
    third of the prompt stayed empty): the room left goes to WHOLE definitions and module constants the shown code
    uses, the nearer relation first (what a shown part uses, then what those use), each at most FRAGMENT_MAX_CHARS,
    none already visible or holding a shown part. Returns the room used."""
    named = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            named.setdefault(node.name, []).append(node)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            named.setdefault(node.targets[0].id, []).append(_Assigned(node.targets[0].id, node))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            named.setdefault(node.target.id, []).append(_Assigned(node.target.id, node))
    queue, queued = [], set()
    for node in shown:
        for name in _uses(node):
            if name not in queued:
                queued.add(name)
                queue.append(name)
    while queue and used < room:
        name = queue.pop(0)
        for node in named.get(name, ()):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            node_lines = range(start, node.end_lineno + 1)
            if any(ln in taken for ln in node_lines):
                continue
            body = '\n'.join(lines[start - 1:node.end_lineno])
            piece = '# %s, lines %d-%d\n%s' % (node.name, start, node.end_lineno, body)
            if len(body) > FRAGMENT_MAX_CHARS or used + len(piece) + 2 > room:
                continue
            spans.append((start, node.end_lineno, node.name, False))
            used += len(piece) + 2
            taken.update(node_lines)
            for sub in _uses(node):
                if sub not in queued:
                    queued.add(sub)
                    queue.append(sub)
    return used


def _joined(spans, lines, spare: int, budgets=None) -> str:
    """The shown parts in line order. Parts whose unseen gap is at most GAP_FILL_LINES lines become ONE contiguous
    part, gap included, while ``spare`` characters allow it; overlapping parts are shown once. 19.11 23:59: a SEARCH
    copied across two parts with a try/except unseen between them matched nothing, 4 passes in a row, twice.
    The gap between two windows of ONE large definition is also paid from that definition's own budget
    (``budgets``: FRAGMENT_MAX_CHARS minus its windows), so one big definition never outgrows a fragment (cloud matrix
    20.11 01:38: 6 423 characters for a bound of 6 000 + 200 after the gap fill)."""
    budgets = dict(budgets or {})
    merged = []
    for start, end, name, part in sorted(spans):
        if merged:
            m_start, m_end, m_name, m_part = merged[-1]
            cost = sum(len(lines[i - 1]) + 1 for i in range(m_end + 1, start))
            own = m_part and part and m_name == name and name in budgets
            if start <= m_end + 1 + GAP_FILL_LINES and cost <= spare and (not own or cost <= budgets[name]):
                spare -= cost
                if own:
                    budgets[name] -= cost
                merged[-1] = (m_start, max(m_end, end), m_name, m_part or part)
                continue
        merged.append((start, end, name, part))
    return '\n\n'.join('# %s, lines %d-%d%s\n%s' % (name, start, end, ' (part)' if part else '',
                                                  '\n'.join(lines[start - 1:end]))
                       for start, end, name, part in merged)


def large_view(name: str, source: str, keywords: set, room: int, priority: frozenset = frozenset(),
               hint: str = READ_HINT, tools: bool = True, asked: frozenset = frozenset()) -> str:
    """Outline + the definitions whose names are mentioned, within ``room`` characters; a definition of this file
    the model ``asked`` for first, with the outline cut to a quarter of the room to make room for it."""
    lines = len(_lines(source))
    head = 'FILE %s (LARGE: %d lines, %d chars; outline and selected parts only)\n%s' % (
        name, lines, len(source), hint)
    if name.endswith('.py'):
        imports = _imports(source)
        here = any(re.search(r'\b(?:def|class)\s+%s\b' % re.escape(a), source) for a in asked)
        toc = outline(source, min(OUTLINE_MAX_CHARS, max(300, room // (4 if here else 2))), tools)
        body = head + ('\nIMPORTS\n' + imports if imports else '') + '\nOUTLINE\n' + toc
        frag = _fragments(source, keywords, max(0, room - len(body) - 40), priority, tools, asked)
        return body + ('\nSELECTED PARTS\n' + frag if frag else '')
    return head + '\nHEAD OF THE FILE\n' + redact(source)[:max(300, min(3000, room - len(head) - 40))]


def render(files: dict, targets: dict, *, large: set, keywords: set, budget_chars: int,
           small_tokens: int, priority: frozenset = frozenset(), hint: str = READ_HINT, tools: bool = True,
           asked: frozenset = frozenset()) -> str:
    """Prompt body: small files whole (as ``packet`` does), large ones as outline + fragments. ``tools=False``
    for a reader without a read tool (the light engine): no "read it" instructions anywhere in the body.
    ``asked``: definitions the model asked to see (asked_names), shown first."""
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
            sections.append(large_view(n, text, keywords, room, priority, hint, tools, asked))
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
