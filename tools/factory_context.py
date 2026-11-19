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


def outline(source: str, max_chars: int = OUTLINE_MAX_CHARS) -> str:
    """Table of contents of a python module: top-level defs/classes and methods with line ranges."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return '(the file does not parse; read it by line numbers)'
    rows = ['%sL%d-%d %s' % ('  ' * depth, node.lineno, node.end_lineno, _sig(node))
            for depth, node in _definitions(tree)]
    text, used = [], 0
    for i, row in enumerate(rows):
        if used + len(row) + 1 > max_chars:
            text.append('... %d more definitions (read the file by line numbers)' % (len(rows) - i))
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


def _fragments(source: str, keywords: set, room: int, priority: frozenset = frozenset()) -> str:
    """Selected definitions as they are. Python fragments are deliberately NOT redacted: redaction could
    corrupt code, and secrets never enter the work copy (forbidden paths, .env). Non-.py heads are redacted."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ''
    lines = _lines(source)
    candidates = [node for depth, node in _definitions(tree) if node.name in keywords]
    # names from the task title / goal / feedback first, names only the test mentions after them;
    # a method the title names is taken BEFORE the class the test names (no nesting loss)
    candidates.sort(key=lambda n: (0 if n.name in priority else 1, n.lineno))
    picked, taken, used = [], [], 0
    for node in candidates:
        span = (node.lineno, node.end_lineno)
        if any(span[0] <= b and a <= span[1] for a, b in taken):
            continue
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        body = '\n'.join(lines[start - 1:node.end_lineno])
        cut = ''
        if len(body) > FRAGMENT_MAX_CHARS:
            body = body[:FRAGMENT_MAX_CHARS]
            cut = '\n# ... cut: read lines %d-%d with the read tool' % (start, node.end_lineno)
        piece = '# %s, lines %d-%d\n%s%s' % (node.name, start, node.end_lineno, body, cut)
        if used + len(piece) + 2 > room:
            continue          # does not fit: NOT marked as taken, so a smaller overlapping one may still be shown
        taken.append(span)
        picked.append((start, piece))
        used += len(piece) + 2
    return '\n\n'.join(p for _, p in sorted(picked))


def large_view(name: str, source: str, keywords: set, room: int, priority: frozenset = frozenset(),
               hint: str = READ_HINT) -> str:
    """Outline + the definitions whose names are mentioned, within ``room`` characters."""
    lines = len(_lines(source))
    head = 'FILE %s (LARGE: %d lines, %d chars; outline and selected parts only)\n%s' % (
        name, lines, len(source), hint)
    if name.endswith('.py'):
        toc = outline(source, min(OUTLINE_MAX_CHARS, max(300, room // 2)))
        body = head + '\nOUTLINE\n' + toc
        frag = _fragments(source, keywords, max(0, room - len(body) - 40), priority)
        return body + ('\nSELECTED PARTS\n' + frag if frag else '')
    return head + '\nHEAD OF THE FILE\n' + redact(source)[:max(300, min(3000, room - len(head) - 40))]


def render(files: dict, targets: dict, *, large: set, keywords: set, budget_chars: int,
           small_tokens: int, priority: frozenset = frozenset(), hint: str = READ_HINT) -> str:
    """Prompt body: small files whole (as ``packet`` does), large ones as outline + fragments."""
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
            sections.append(large_view(n, text, keywords, room, priority, hint))
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
