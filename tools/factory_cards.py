"""Shared contract source resolution and verbatim regions for task cards."""
import ast
import json
from pathlib import Path, PurePosixPath

PART_REGION_CHARS = 24000


def _symbols(tree):
    found = {}

    def walk(body, prefix=""):
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                found[name] = node
                walk(node.body, name + ".")

    walk(tree.body)
    return found


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
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            spans.append((start, node.end_lineno))
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
            if isinstance(node, ast.ClassDef) or name.rpartition(".")[2] not in names:
                continue
            head = ast.get_source_segment(text, node) or ""
            first = head.split("\n", 1)[0].rstrip()
            lines.append(f"{file}: {first}")
    return "\n".join(lines)


def part_prompt(file, part, header, region, failing="", signatures="") -> str:
    """The card of one part: its own file only. The first line is ``FILE <path>``."""
    out = [f"FILE {file}", "Instruction: " + str(part.get("instruction", "")).strip()]
    if part.get("keep"):
        out.append("Keep: " + str(part["keep"]).strip())
    if part.get("add_after"):
        out.append("Add after: " + str(part["add_after"]).strip())
    out.append(f"Code of {file} ({header}), shown exactly:\n{region}")
    if signatures:
        out.append("Signatures of functions in other files that the instruction names (read only):\n" + signatures)
    if failing:
        out.append("The check fails with this exact line:\n" + failing.strip())
    out.append(EDITOR_RULES)
    return "\n\n".join(out) + "\n"


def test_prompt(task, contract, regions) -> str:
    """The card of a test task written from the contract: the test file, given/when/then, why it is red now, and
    the code of the functions it checks (read only)."""
    new = (contract.get("test") or {}).get("new") or {}
    out = [f"FILE {new.get('path', '')}", "Task: " + str(getattr(task, "title", "")).strip(),
           "Given: " + str(new.get("given", "")), "When: " + str(new.get("when", "")),
           "Then: " + str(new.get("then", "")), "Red now because: " + str(new.get("red_now_because", ""))]
    for file, (header, region) in sorted(dict(regions).items()):
        out.append(f"Code of {file} ({header}), read only:\n{region}")
    out.append("Write ONE test that fails now for the reason named above. No skip, no sleep, no stub in place of the "
               "code under test. Import the real code and call it.\n" + EDITOR_RULES)
    return "\n\n".join(out) + "\n"


def _def_texts(text: str) -> dict[str, str]:
    lines = text.splitlines()
    found = {}
    for name, node in _symbols(ast.parse(text)).items():
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        found[name] = "\n".join(lines[start - 1:node.end_lineno])
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
