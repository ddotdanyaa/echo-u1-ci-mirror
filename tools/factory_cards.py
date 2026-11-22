"""Shared contract source resolution and verbatim regions for task cards."""
import ast
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
