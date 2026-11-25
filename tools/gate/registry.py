"""N184 (W09): link and integrity check of a markdown registry (BACKLOG_ECHO.md style). Finds: duplicate row IDs, references to IDs with no row,
markdown links and `backticked/paths.ext` that do not exist, and snapshot dates (dd.mm hh:mm) older than the newest date in the file.
Only table-row IDs (| E50 | ...) are definitions. A reference is a bare ID token or a range in the text."""
import argparse
import json
import re
import sys
from pathlib import Path

ID = r'(?:[EWDTRNНС]\d{1,3}(?:\.\d+)?)'
ROW = re.compile(r'^\|\s*(' + ID + r')\s*\|')
TOKEN = re.compile(r'(?<![\w.`/-])(' + ID + r')(?![\w])')
LINK = re.compile(r'\]\(([^)#\s]+)(?:#[^)]*)?\)')
PATH = re.compile(r'`((?:[\w.-]+/)+[\w.-]+\.(?:py|md|json|jsonl|csv|ps1|txt|sh|diff|patch))`')
DATE = re.compile(r'(?<!\d)(\d{2})\.(\d{2})(?:\.\d{2,4})?\s+(\d{2}):(\d{2})')
ANY_PREFIX = re.compile(r'^[EW]')


def check_registry(path, root=None, strict_refs=('E', 'W')):
    path = Path(path)
    root = Path(root) if root else path.parent
    lines = path.read_text(encoding='utf-8').splitlines()
    defined, problems = {}, []
    for n, line in enumerate(lines, 1):
        m = ROW.match(line)
        if m:
            if m.group(1) in defined:
                problems.append({'kind': 'duplicate_id', 'what': m.group(1), 'line': n, 'first': defined[m.group(1)]})
            else:
                defined[m.group(1)] = n
    seen = set()
    for n, line in enumerate(lines, 1):
        row = ROW.match(line)
        body = line[row.end():] if row else line
        for tok in TOKEN.findall(body):
            if tok[0] in strict_refs and tok not in defined and ('unknown_id', tok) not in seen:
                seen.add(('unknown_id', tok))
                problems.append({'kind': 'unknown_id', 'what': tok, 'line': n})
        for target in LINK.findall(line):
            if not re.match(r'[a-z]+:', target) and not (root / target).exists() and not (path.parent / target).exists():
                problems.append({'kind': 'broken_link', 'what': target, 'line': n})
        for target in PATH.findall(line):
            if not (root / target).exists() and not (path.parent / target).exists():
                problems.append({'kind': 'missing_path', 'what': target, 'line': n})
    stamps = [(int(mo), int(d), int(h), int(mi), n) for n, line in enumerate(lines, 1) for d, mo, h, mi in DATE.findall(line)]
    if stamps:
        newest = max(s[:4] for s in stamps)
        for s in stamps:
            if s[:2] < newest[:2]:                        # a whole day behind the newest date in the registry
                problems.append({'kind': 'stale_date', 'what': f'{s[1]:02d}.{s[0]:02d} {s[2]:02d}:{s[3]:02d}', 'line': s[4], 'newest': f'{newest[1]:02d}.{newest[0]:02d} {newest[2]:02d}:{newest[3]:02d}'})
    return problems


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('registry', nargs='?', default=str(Path(__file__).resolve().parents[2] / 'cloud_context/BACKLOG_ECHO.md'))
    p.add_argument('--root', default=str(Path(__file__).resolve().parents[2]))
    a = p.parse_args(argv)
    probs = check_registry(a.registry, a.root)
    kinds = {}
    for q in probs:
        kinds[q['kind']] = kinds.get(q['kind'], 0) + 1
    print(json.dumps({'registry': a.registry, 'problems': len(probs), 'by_kind': kinds}, ensure_ascii=False))
    for q in probs:
        print(json.dumps(q, ensure_ascii=False))
    return 1 if probs else 0


if __name__ == '__main__':
    sys.exit(main())
