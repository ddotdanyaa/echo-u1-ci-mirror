"""Shared contract source resolution and verbatim regions for task cards."""
import ast
import json
import os
import re
from pathlib import Path, PurePosixPath

PART_REGION_CHARS = 24000


def _symbols(tree):
    found = {}

    def walk(body, prefix="", in_function=False, nested=False):
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                if nested:                  # defined under if/try/with: a plain definition of the same name keeps its place
                    found.setdefault(name, node)
                else:
                    found[name] = node
                walk(node.body, name + ".", in_function or not isinstance(node, ast.ClassDef))
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)) and not in_function:
                # a definition under `if TYPE_CHECKING:` / `try: import ... except` / a platform branch is a name too (W-pay 4)
                for block in ("body", "orelse", "finalbody"):
                    walk(getattr(node, block, []) or [], prefix, in_function, True)
                for handler in getattr(node, "handlers", []) or []:
                    walk(handler.body, prefix, in_function, True)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and not in_function:
                # a module (or class) constant is a named target too; a def of the same name keeps its place
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        found.setdefault(prefix + target.id, node)

    walk(tree.body)
    return found


def _is_function(node) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _node_start(node) -> int:
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])


PART_CODE_MAX = 8000        # parts[].code of one part (W-hard 3)


def split_part_code(code, symbols) -> list:
    """[(symbol, text)] of parts[].code of a .py part: ``code`` holds the whole new text of every named function (one
    top-level ``def`` each, a method may stand indented), matched to ``symbols`` by the function name. ValueError with
    the exact reason when it does not parse, holds anything but whole functions, or does not cover every symbol once."""
    import textwrap
    if not isinstance(code, str) or not code.strip():
        raise ValueError("empty code")
    if not symbols:
        raise ValueError("code needs named symbols")
    text = textwrap.dedent(code.strip("\n"))
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        raise ValueError("code does not parse: " + str(exc)[:100])
    lines, pending, out = text.split("\n"), list(symbols), []
    for node in tree.body:
        if not _is_function(node):
            raise ValueError("code must hold only whole function definitions")
        hit = [s for s in pending if s.rpartition(".")[2] == node.name]
        if not hit:
            raise ValueError("code defines %s, which is not a named symbol" % node.name)
        pending.remove(hit[0])
        out.append((hit[0], "\n".join(lines[_node_start(node) - 1:node.end_lineno])))
    if pending:
        raise ValueError("no code for: " + ", ".join(pending))
    return out


def region_sha(text, symbols) -> str:
    """sha1 of the source of the named functions (LF), what parts[].code was written against; '' when they cannot be read."""
    import hashlib
    try:
        return hashlib.sha1(part_region(text.replace("\r\n", "\n"), symbols)[1].encode("utf-8")).hexdigest()
    except (ValueError, SyntaxError, TypeError):
        return ""


def known_names(text: str, limit: int = 60) -> list[str]:
    """Real names of a Python source (functions, classes, methods, constants), up to ``limit``."""
    try:
        return list(_symbols(ast.parse(text)))[:limit]
    except (SyntaxError, ValueError):
        return []


def similar_paths(root, file: str, limit: int = 10) -> list[str]:
    """Paths of the tree that look like ``file`` (same file name, or the closest names), up to ``limit``."""
    import difflib
    root = Path(root)
    rel = PurePosixPath(str(file).replace("\\", "/"))
    base = rel.name.lower()
    skip = {".git", "__pycache__", "node_modules", ".pytest_cache", "SECRETS_LOCAL"}
    found = []
    try:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip]
            for name in files:
                found.append((Path(dirpath) / name).relative_to(root).as_posix())
            if len(found) > 20000:
                break
    except OSError:
        pass
    same = sorted(p for p in found if PurePosixPath(p).name.lower() == base)
    close = difflib.get_close_matches(str(rel), found, n=limit, cutoff=0.5)
    out = []
    for p in same + close:
        if p not in out:
            out.append(p)
    return out[:limit]


def hint_for(root, file: str, defect: str) -> str:
    """For a 'missing symbol' / 'missing file' defect: the real names of that file or the similar paths."""
    try:
        if defect.startswith("missing symbol"):
            path = Path(root) / file
            names = known_names(path.read_text(encoding="utf-8-sig")) if path.is_file() else []
            return ("names in " + file + ": " + ", ".join(names)) if names else ""
        if defect.startswith("missing file"):
            paths = similar_paths(root, file)
            return ("similar paths: " + ", ".join(paths)) if paths else ""
    except (OSError, UnicodeError):
        pass
    return ""


def resolve(root: Path, file: str, symbols: list[str], anchor: str = "") -> list[str]:
    """Validate containment, exact path case and the contract's source targets."""
    root = Path(root).resolve()
    rel = PurePosixPath(file.replace("\\", "/"))
    if rel.is_absolute() or not rel.parts or any(p in ("..", ".") or ":" in p for p in rel.parts):
        return ["file must be under root: " + file]
    path = root
    try:
        for component in rel.parts:
            if component not in {p.name for p in path.iterdir()}:
                return ["missing file or wrong case: " + file]
            path = path / component
            if not path.resolve().is_relative_to(root):
                return ["file escapes root: " + file]
        if not path.is_file():
            return ["not a file: " + file]
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return ["cannot read file: " + file + " (" + type(exc).__name__ + ")"]
    if path.suffix == ".py":
        try:
            found = _symbols(ast.parse(text))
        except SyntaxError:
            return ["invalid Python: " + file]
        return ["missing symbol: " + name for name in symbols if name not in found]
    defects = ["symbols require a Python file"] if symbols else []
    if not anchor or anchor not in text.splitlines():
        defects.append("missing anchor: " + anchor)
    return defects


def part_region(text, symbols, anchor="", cap=PART_REGION_CHARS) -> tuple[str, str]:
    """Return a line-range header and exact source, keeping distant targets adjacent.

    Named definitions are never cut in half. Oversized definitions are refused
    so a caller can split its request instead of showing an unusable edit target.
    """
    if cap <= 0:
        raise ValueError("region cap must be positive")
    lines = text.splitlines(keepends=True)
    if symbols:
        found = _symbols(ast.parse(text))
        spans = []
        for name in symbols:
            if name not in found:
                raise ValueError("missing symbol: " + name)
            node = found[name]
            spans.append((_node_start(node), node.end_lineno))
        merged = []
        for start, end in sorted(set(spans)):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        region = "\n".join("".join(lines[start - 1:end]) for start, end in merged)
        if len(region) > cap:
            raise ValueError("named definitions exceed region cap")
        return "lines " + ", ".join(f"{a}-{b}" for a, b in merged), region
    if not anchor:
        return "lines 1-" + str(len(lines)), text[:cap]
    matches = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == anchor]
    if not matches:
        raise ValueError("missing anchor: " + anchor)
    index = matches[0]
    region = lines[index]
    if len(region) > cap:
        raise ValueError("anchor exceeds region cap")
    start, end = index, index + 1
    while start > 0 or end < len(lines):
        added = False
        if start > 0 and len(lines[start - 1]) + len(region) <= cap:
            start -= 1
            region = lines[start] + region
            added = True
        if end < len(lines) and len(region) + len(lines[end]) <= cap:
            region += lines[end]
            end += 1
            added = True
        if not added:
            break
    return f"lines {start + 1}-{end}", region


OUTLINE_CHARS = 12000


def _outline_sig(node) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return "class " + node.name + ("(" + bases + ")" if bases else "")
    if _is_function(node):
        returns = " -> " + ast.unparse(node.returns) if node.returns else ""
        return ("async def " if isinstance(node, ast.AsyncFunctionDef) else "def ") + node.name + \
            "(" + ast.unparse(node.args) + ")" + returns
    return ""


def outline(text: str, cap: int = OUTLINE_CHARS) -> str:
    """The table of contents of a Python source too big to show: classes, functions with signatures and line
    numbers, module and class constants, at most ``cap`` characters (a reading aid, never an edit target)."""
    rows = []
    for name, node in _symbols(ast.parse(text)).items():
        sig = _outline_sig(node)
        if sig:
            rows.append(f"{_node_start(node)}-{node.end_lineno}: {sig}" if name.count(".") == 0 else
                        f"{_node_start(node)}-{node.end_lineno}:   {name}: {sig}")
        else:
            rows.append(f"{node.lineno}: {name} = ...")
    out, size = [], 0
    for row in rows:
        if size + len(row) + 1 > cap:
            out.append("... (the outline is cut at %d characters)" % cap)
            break
        out.append(row)
        size += len(row) + 1
    return "\n".join(out)


def symbol_excerpt(text: str, symbols, cap: int = PART_REGION_CHARS) -> tuple[str, str]:
    """Named definitions for READING when together they exceed ``cap``: each shown whole while it fits, a bigger one as
    its signature, docstring and beginning up to what is left, with a note of the cut. Not an edit target."""
    lines = text.splitlines(keepends=True)
    found = _symbols(ast.parse(text))
    parts, left, spans = [], cap, []
    for name in symbols:
        if name not in found:
            raise ValueError("missing symbol: " + name)
        node = found[name]
        start, end = _node_start(node), node.end_lineno
        body = "".join(lines[start - 1:end])
        if len(body) <= left:
            parts.append(body)
            spans.append(f"{start}-{end}")
        else:
            shown = body[:max(left, 0)]
            parts.append(shown + f"\n# [cut: {name} is {len(body)} characters, the first {len(shown)} are shown; "
                                 f"this is reading, not an edit target]\n")
            spans.append(f"{start}-{start + shown.count(chr(10))} of {start}-{end}")
        left -= len(parts[-1])
    return "lines " + ", ".join(spans), "\n".join(parts)


class StaleContract(Exception):
    """A part of the contract no longer matches the code: the row goes back to the slicer without a strike."""


# The editor's rules: Aider's editor_editblock prompt (SEARCH/REPLACE blocks, exact copies of the shown lines),
# plus the two formats the executor already reads: a whole function and the honest refusal.
EDITOR_RULES = (
    "Act as an expert software developer who edits the source file named in the first line. Describe each change "
    "with a SEARCH/REPLACE block: the file path on its own line, a line <<<<<<< SEARCH, lines copied EXACTLY from "
    "the shown code (every character, comment and blank line; enough lines to be unique; never line numbers or "
    "omission markers), a line =======, the new lines, a line >>>>>>> REPLACE. An empty SEARCH part creates a new "
    "file. Edit only this file and only what the instruction asks; keep the rest as it is. Answer with the blocks "
    "only, no explanation. To add a new function, write an ordinary SEARCH/REPLACE block that repeats the last "
    "lines of the function named in 'add after' and appends the new function after them. To replace a whole "
    "function shown whole, write the line REPLACE FUNCTION <path> <name> (name: func or Class.method), then a "
    "```python fence with the complete new definition, then a closing ``` line. If the code you must change is "
    "not shown, or the instruction cannot be carried out, answer one line: CANNOT: and the reason.")


MAX_STAGE_PARTS = 10   # parts edited at once in one stage; the same number as the runner's LIGHT_MAX_FILES


def stages(parts) -> list[list[dict]]:
    """The parts grouped by their ``stage`` (no field: stage 1), the stages in ascending order."""
    grouped: dict[int, list[dict]] = {}
    for part in parts:
        grouped.setdefault(int(part.get("stage", 1) or 1), []).append(part)
    return [grouped[n] for n in sorted(grouped)]


def contract_of(task) -> dict:
    """The task's contract as a dict ({} when it has none or it does not read)."""
    raw = getattr(task, "contract", "") or ""
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def test_spec(task) -> str:
    """The contract of a test card as text for a critic (given / when / then / red now because); '' for any other
    task or a contract with no new test."""
    if getattr(task, "kind", "") != "unit_test":
        return ""
    new = (contract_of(task).get("test") or {}).get("new") or {}
    lines = [f"{label}: {str(new.get(key, '')).strip()}" for label, key in
             (("Given", "given"), ("When", "when"), ("Then", "then"), ("Red now because", "red_now_because"))
             if str(new.get(key, "")).strip()]
    return "\n".join(lines)


def contract_parts(task, root: Path) -> list[dict]:
    """The parts of the task's contract, each checked by ``resolve`` against the fresh snapshot ``root``.
    A defect of any part: StaleContract (the executor then returns the row to the slicer and calls no model)."""
    parts = contract_of(task).get("parts")
    if not isinstance(parts, list) or not parts:
        return []
    found, defects = [], []
    for raw in parts:
        if not isinstance(raw, dict) or not isinstance(raw.get("file"), str):
            defects.append("a part without a file")
            continue
        symbols = [s for s in (raw.get("symbols") or []) if isinstance(s, str)]
        part = dict(raw, symbols=symbols, anchor=str(raw.get("anchor") or ""))
        defects.extend(resolve(root, part["file"], symbols, part["anchor"]))
        found.append(part)
    for number, stage in enumerate(stages(found), 1):
        if len(stage) > MAX_STAGE_PARTS:
            defects.append("stage %d has %d parts, at most %d" % (number, len(stage), MAX_STAGE_PARTS))
    if defects:
        raise StaleContract("; ".join(defects))
    return found


def signatures(texts: dict, names) -> str:
    """``def`` lines of the functions of ``texts`` ({file: source}) that ``names`` mention: what a part may call."""
    lines = []
    for file, text in sorted(texts.items()):
        if not file.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        for name, node in _symbols(tree).items():
            if not _is_function(node) or name.rpartition(".")[2] not in names:
                continue
            head = ast.get_source_segment(text, node) or ""
            first = head.split("\n", 1)[0].rstrip()
            lines.append(f"{file}: {first}")
    return "\n".join(lines)


class CardTooLarge(Exception):
    """The fixed part of a card (the code to edit, the test fields, the answer format) alone is over the prompt limit:
    the row goes back to the slicer (reslice), it is not blocked."""


CUT_NOTE = "\n# [cut: the rest of this code is not shown (the prompt limit); it is reading, not an edit target]\n"


def _def_lines(region: str) -> str:
    """The ``def`` / ``class`` lines of a region of code (a signature table of what it defines)."""
    rows = [ln.rstrip() for ln in region.splitlines() if ln.lstrip().startswith(("def ", "async def ", "class "))]
    return "\n".join(rows)


def part_prompt(file, part, header, region, failing="", signatures="", limit=None) -> str:
    """The card of one part: its own file only. The first line is ``FILE <path>``. With ``limit`` (characters) a
    card over it gives up, in this order: the signatures of other files, the head of the failing line, and (only for a
    part with no named symbols, a window of the file) the end of the window. The code of the named symbols, the
    instruction and the answer format stay whole; when they alone are over the limit: CardTooLarge."""
    def build(sigs, fail, shown):
        out = [f"FILE {file}", "Instruction: " + str(part.get("instruction", "")).strip()]
        if part.get("keep"):
            out.append("Keep: " + str(part["keep"]).strip())
        if part.get("add_after"):
            out.append("Add after: " + str(part["add_after"]).strip())
        out.append(f"Code of {file} ({header}), shown exactly:\n{shown}")
        if sigs:
            out.append("Signatures of functions in other files that the instruction names (read only):\n" + sigs)
        if fail:
            out.append("The check fails with this exact line:\n" + fail.strip())
        out.append(EDITOR_RULES)
        return "\n\n".join(out) + "\n"

    card = build(signatures, failing, region)
    if limit is None or len(card) <= limit:
        return card
    sigs = signatures
    while sigs and len(build(sigs, failing, region)) > limit:       # other files' signatures: line by line from the end
        sigs = sigs.rpartition("\n")[0]
    card = build(sigs, failing, region)
    if len(card) > limit and failing:
        room = limit - len(build(sigs, "x", region)) + 1
        card = build(sigs, failing.strip()[-room:] if room > 40 else "", region)
    if len(card) > limit and not part.get("symbols"):
        over = len(card) - limit
        keep = len(region) - over - len(CUT_NOTE)
        if keep > 0:
            card = build(sigs, "", region[:keep] + CUT_NOTE)
    if len(card) > limit:
        raise CardTooLarge("the card of %s is %d characters, the limit is %d" % (file, len(card), limit))
    return card


SIGNATURE_CHARS = 3000
EXAMPLE_CHARS = 2500
EXAMPLE_FILE_LIMIT = 300


def _signature(node) -> str:
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return prefix + node.name + "(" + ast.unparse(node.args) + ")"


def signature_lines(source: str, symbols, file: str = "") -> list[str]:
    """Signatures of the named functions of ``source`` and of the ``__init__`` of every class they belong to
    (what a test must know to build the object and call it)."""
    try:
        found = _symbols(ast.parse(source))
    except (SyntaxError, ValueError):
        return []
    out: list[str] = []

    def add(name):
        node = found.get(name)
        if node is not None and _is_function(node):
            line = (file + ": " if file else "") + (name.rpartition(".")[0] + "." if "." in name else "") + _signature(node)
            if line not in out:
                out.append(line)

    for name in symbols or []:
        node = found.get(name)
        if isinstance(node, ast.ClassDef):
            add(name + ".__init__")
        elif node is not None:
            owner = name.rpartition(".")[0]
            if owner and isinstance(found.get(owner), ast.ClassDef):
                add(owner + ".__init__")
            add(name)
    return out


def example_test(root: Path, symbols, limit: int = EXAMPLE_CHARS) -> str:
    """One neighbouring test of the product that calls one of ``symbols`` (a test function and the fixtures it
    names, at most ``limit`` chars): how the code is built and called; '' when none is found."""
    names = {s.split(".")[0] for s in symbols or []} | {s.rpartition(".")[2] for s in symbols or []}
    names = {n for n in names if n and not n.startswith("__")}
    tests = Path(root) / "tests"
    if not names or not tests.is_dir():
        return ""
    candidates = []
    try:
        for path in sorted(tests.rglob("test_*.py"))[:EXAMPLE_FILE_LIMIT]:
            try:
                if path.stat().st_size > 80000:
                    continue
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            if any(n in text for n in names):
                candidates.append((len(text), str(path), text))
    except OSError:
        return ""
    for _, path, text in sorted(candidates):
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in tree.body:
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test")):
                continue
            body = ast.get_source_segment(text, node) or ""
            if not any(n in body for n in names):
                continue
            pieces = [ast.get_source_segment(text, defs[a.arg]) or "" for a in node.args.args
                      if a.arg in defs and a.arg not in ("self",)]
            shown = "\n\n".join([p for p in pieces if p] + [body])
            return f"{PurePosixPath(Path(path).relative_to(root).as_posix())}:\n" + shown[:limit]
    return ""


def test_prompt(task, contract, regions, signatures: str = "", example: str = "", problems=(), limit=None,
                reserve: int = 0) -> str:
    """The card of a test task written from the contract: the test file, given/when/then, why it is red now, and
    the code of the functions it checks (read only), their signatures, one neighbouring test as a pattern, and the
    parts whose code could not be shown.

    ``limit`` (characters; ``reserve`` of them stay free for what the caller appends): a card over it shrinks the
    READ-ONLY blocks in this order: the example, the code of the functions (the biggest first) down to its ``def`` /
    ``class`` lines, then the end of what is left of the code. The test fields (given / when / then / red now), the
    signatures and the answer format stay whole; when they alone do not fit: CardTooLarge."""
    new = (contract.get("test") or {}).get("new") or {}
    head = [f"FILE {new.get('path', '')}", "Task: " + str(getattr(task, "title", "")).strip(),
            "The test file does not exist yet: create it with an EMPTY SEARCH part and the whole file in REPLACE.",
            "Given: " + str(new.get("given", "")), "When: " + str(new.get("when", "")),
            "Then: " + str(new.get("then", "")), "Red now because: " + str(new.get("red_now_because", ""))]
    shown = {file: (header, region) for file, (header, region) in dict(regions).items()}
    tail = ("Write ONE test that fails now for the reason named above. No skip, no sleep, no stub in place of the "
            "code under test. Import the real code and call it.\n" + EDITOR_RULES)

    def build(code, ex):
        out = list(head)
        for file, (header, region) in sorted(code.items()):
            out.append(f"Code of {file} ({header}), read only:\n{region}")
        if problems:
            out.append("The code of these parts of the contract could not be shown:\n" + "\n".join(map(str, problems)))
        if signatures:
            out.append("Signatures (call the code exactly this way):\n" + signatures[:SIGNATURE_CHARS])
        if ex:
            out.append("Example of an existing test of this code (read only; copy the way objects are built and called, "
                       "not the asserts):\n" + ex)
        out.append(tail)
        return "\n\n".join(out) + "\n"

    card = build(shown, example)
    if limit is None:
        return card
    room = limit - reserve
    if len(card) <= room:
        return card
    for ex in (example[:EXAMPLE_CHARS // 3], ""):               # 1. the example
        if len(build(shown, ex)) > room:
            continue
        return build(shown, ex)
    example = ""
    for file in sorted(shown, key=lambda f: -len(shown[f][1])):  # 2. foreign code down to its signatures
        header, region = shown[file]
        shown[file] = (header + ", cut to its signatures", _def_lines(region) or region[:200])
        if len(build(shown, "")) <= room:
            return build(shown, "")
    over = len(build(shown, "")) - room                          # 3. the end of what is left
    for file in sorted(shown, key=lambda f: -len(shown[f][1])):
        header, region = shown[file]
        keep = max(0, len(region) - over - len(CUT_NOTE))
        if keep and keep < len(region):
            shown[file] = (header, region[:keep] + CUT_NOTE)
        elif not keep:
            shown.pop(file)
        card = build(shown, "")
        over = len(card) - room
        if over <= 0:
            return card
    raise CardTooLarge("the test card is %d characters, %d allowed" % (len(build(shown, "")), room))


_QUOTED = re.compile(r"'([A-Za-z_][\w.]*)'")
_CALLED = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\(\) (?:missing|takes|got|argument)")
_FROM_MODULE = re.compile(r"(?:from|module named|import) '?([A-Za-z_][\w.]*)'?")


def error_names(diag: str) -> list[str]:
    """The names a test error line talks about: quoted names (KeyError, AttributeError, ImportError) and the callables of
    ``f() missing 1 required positional argument`` / ``Cls.__init__() takes ...``; leaf names, in order, no repeats."""
    found: list[str] = []
    for match in _CALLED.finditer(diag or ""):
        found.extend(part for part in match.group(1).split(".") if part != "__init__")
    for match in _QUOTED.finditer(diag or ""):
        found.append(match.group(1).rpartition(".")[2])
    return list(dict.fromkeys(n for n in found if n and not n.startswith("__")))


def error_modules(root, diag: str) -> list[str]:
    """Files of the tree (posix paths) of the modules an import error of ``diag`` names ('from pkg.mod import X',
    'No module named pkg.mod'): the nearest existing file or package for each dotted name."""
    root = Path(root)
    out: list[str] = []
    for match in _FROM_MODULE.finditer(diag or ""):
        dotted = match.group(1).split(".")
        while dotted:
            base = "/".join(dotted)
            hit = next((c for c in (base + ".py", base + "/__init__.py") if (root / c).is_file()), "")
            if hit:
                if hit not in out:
                    out.append(hit)
                break
            dotted = dotted[:-1]
    return out


def object_facts(source: str, names, file: str = "") -> list[str]:
    """What the code really has under ``names`` (read from the AST, never guessed): a class with its bases,
    ``__init__``, instance fields and methods; a function with its signature; and the names the module exports."""
    try:
        tree = ast.parse(source)
        found = _symbols(tree)
    except (SyntaxError, ValueError):
        return []
    where = file + ": " if file else ""
    rows: list[str] = []
    for name in names:
        for key, node in found.items():
            if key.rpartition(".")[2] != name or "." in key and not isinstance(found.get(key.rpartition(".")[0]), ast.ClassDef):
                continue
            if isinstance(node, ast.ClassDef):
                init = found.get(key + ".__init__")
                fields = sorted({t.attr for n in ast.walk(init) if isinstance(n, ast.Assign) for t in n.targets
                                 if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self"}) \
                    if init is not None else []
                methods = [k.rpartition(".")[2] + "(" + ast.unparse(v.args) + ")" for k, v in found.items()
                           if k.startswith(key + ".") and k.count(".") == key.count(".") + 1 and _is_function(v)
                           and not k.endswith("__init__")]
                rows.append(f"{where}{_outline_sig(node)}: __init__({ast.unparse(init.args) if init is not None else '...'})"
                            + ("; fields: " + ", ".join(fields) if fields else "")
                            + ("; methods: " + ", ".join(methods[:12]) if methods else ""))
            elif _is_function(node):
                rows.append(where + key + "(" + ast.unparse(node.args) + ")")
            else:
                rows.append(f"{where}{key} is a constant, not a callable" if key.isupper() else f"{where}{key} (a name of the module)")
    exported = [k for k in found if "." not in k and not k.startswith("__")][:40]
    if exported:
        rows.append(f"{where}the module's names: " + ", ".join(exported))
    return rows


def signature_hint(root, diag: str, files=(), symbols=(), limit: int = 1800) -> str:
    """For a test that does not collect or crashes before its assertion: the exact error line and the REAL shape of the
    object it fell on, read from the AST of the snapshot ``root`` (class, ``__init__``, fields, exported names). The
    modules are those the error names plus ``files`` (the contract's files); ``symbols`` are shown when the error names
    nothing. '' when nothing is known."""
    names = error_names(diag) or [s.rpartition(".")[2] for s in symbols or []]
    modules = error_modules(root, diag) + [f for f in files if f not in error_modules(root, diag)]
    rows: list[str] = []
    for file in modules:
        try:
            source = (Path(root) / file).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        rows.extend(object_facts(source, names, file))
    text = "\n".join(dict.fromkeys(rows))
    if not text:
        return ""
    return "\nThe code as it really is (from its source; call it exactly this way and use only these names):\n" + text[:limit] + "\n"


def _def_texts(text: str) -> dict[str, str]:
    lines = text.splitlines()
    found = {}
    for name, node in _symbols(ast.parse(text)).items():
        found[name] = "\n".join(lines[_node_start(node) - 1:node.end_lineno])
    return found


def defined(text: str) -> set[str]:
    """Names of all definitions of a Python source (empty when it does not parse)."""
    try:
        return set(_def_texts(text))
    except (SyntaxError, ValueError):
        return set()


def changed_symbols(old: str, new: str) -> set[str]:
    """Names of the definitions that differ between two sources (added, removed or changed); a class whose only
    change is inside a method is not named, the method is."""
    try:
        before, after = _def_texts(old), _def_texts(new)
    except (SyntaxError, ValueError):
        return set()
    names = {n for n in set(before) | set(after) if before.get(n) != after.get(n)}
    return {n for n in names if not any(m.startswith(n + ".") for m in names)}


def contract_conformance(changed: dict, contract: dict) -> list[str]:
    """Files and functions of an edit outside the contract (``"calc.py: mul"``, ``"other.py"``); [] = in contract."""
    allowed: dict[str, list] = {}
    for part in (contract.get("parts") or []):
        entry = allowed.setdefault(part["file"], [set(), False])
        entry[0].update(part.get("symbols") or [])
        if part.get("anchor") or not part.get("symbols"):
            entry[1] = True                      # a whole-file part: any function of the file
    out = []
    for file in sorted(changed):
        if file not in allowed:
            out.append(file)
            continue
        symbols, whole = allowed[file]
        if whole:
            continue
        out.extend(f"{file}: {name}" for name in sorted(changed[file])
                   if name not in symbols and not any(name.startswith(s + ".") for s in symbols))
    return out
