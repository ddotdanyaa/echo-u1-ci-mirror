"""U113: the number the owner's «expand the functions 2-4 times» is measured by: the functions of РЕЕСТР_ФУНКЦИЙ.md counted by one stated rule. python -m tools.function_count PATH [--date 2026-11-14] prints ONE json line.
Rule (no judgement, no model): a function is a row of a section table «## N. ...» whose first cell is a number like 3.04 / 4.03c and whose column «Состояние» is read from the table's own header; the cross-tables («Выключено...», «Сломано...») and the appendices are not counted again. The status is the words before « — » of that cell:
РАБОТАЕТ... = works (the old function stands, on the server); В ТЕНИ / ВЫКЛЮЧЕНО / СЛОМАНО / НЕ СДЕЛАНО = tried (it was tried or was asked for, and on the server it does not act); ТОЛЬКО В ВЕТКЕ = in_branch (done in the new version, not on the server). A row of another status is `unmarked` (must be 0).
`confirmed` = works rows that say «подтверждено на сервере» (a live call or the deploy, not only a test). Targets: total x2 and x4 (the base is the list of the registry, U113). Not a measurement of a call."""
import argparse, json, re, sys
from pathlib import Path

ID = re.compile(r'\d\.\d\d[a-z]?')
SECTION = re.compile(r'##\s+\d\.')
STATUS = {'РАБОТАЕТ': 'works', 'В ТЕНИ': 'tried', 'ВЫКЛЮЧЕНО': 'tried', 'СЛОМАНО': 'tried', 'НЕ СДЕЛАНО': 'tried', 'ТОЛЬКО В ВЕТКЕ': 'in_branch'}
HEADER_TOTAL = re.compile(r'Всего функций:\s*\**(\d+)')


def status_of(cell):
    """(the status word of a «Состояние» cell, its group or None)."""
    head = cell.split(' — ')[0].strip()
    for word, group in STATUS.items():
        if head.startswith(word):
            return word, group
    return head[:40], None


def count(text):
    """The numbers of one registry text: counted rows, groups, per status, and what the registry's own summary says."""
    rows, section, column = [], False, None
    for line in text.splitlines():
        if line.startswith('#'):
            section, column = bool(SECTION.match(line)), None
            continue
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if cells[0] == '№':
            column = cells.index('Состояние') if 'Состояние' in cells else None
            continue
        if section and column is not None and column < len(cells) and ID.fullmatch(cells[0]):
            rows.append((cells[0], cells[column]))
    ids = [r[0] for r in rows]
    by_status, groups = {}, {'works': 0, 'tried': 0, 'in_branch': 0}
    unmarked, confirmed = [], 0
    for ident, cell in rows:
        word, group = status_of(cell)
        if group is None:
            unmarked.append(ident)
            continue
        by_status[word] = by_status.get(word, 0) + 1
        groups[group] += 1
        confirmed += group == 'works' and 'подтверждено на сервере' in cell
    claimed = HEADER_TOTAL.search(text)
    total = len(rows)
    return {'total': total, **groups, 'confirmed': confirmed, 'by_status': dict(sorted(by_status.items())), 'unmarked': len(unmarked), 'duplicate_ids': len(ids) - len(set(ids)),
            'summary_total': int(claimed.group(1)) if claimed else None, 'summary_agrees': bool(claimed) and int(claimed.group(1)) == total, 'target_x2': total * 2, 'target_x4': total * 4}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('path')
    ap.add_argument('--date', default='')
    a = ap.parse_args(argv)
    result = {'source': Path(a.path).name, 'counted_on': a.date or None, **count(Path(a.path).read_text(encoding='utf-8'))}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
