"""I12 (W09, R31-2, R31-4, W06): local check of links and of the backlog copies, no model. python -m tools.link_check [--root DIR] [--work PATH] [--json PATH] [--max-age-days 3].
1. COPY: every file named BACKLOG_ECHO.md under root (not the working one) must say in its first 15 lines it is a snapshot (`СНИМОК`); otherwise it looks like a queue (R31-2). Reported with the IDs the working backlog has and the copy has not (W09: lost IDs).
2. LINK: relative markdown links `[t](path)` in the checked files that point nowhere (anchors and urls are skipped).
3. STALE: the newest date `dd.mm` in each state file (WAVES_STATE, BACKLOG_ECHO, STATE, 00_НАЧНИ_ЗДЕСЬ, heartbeat) against the working backlog; older than --max-age-days is marked (MECH-N020: «Next:» / «Дальше» lines are counted).
4. GRAPH (R31-4): if graphify-out/graph.json exists: share of nodes from the deployed copy hermes-echo and how many backlog IDs are nodes.
Exit code 0 always: this is a report; the marks are the output. Nothing here proves a call works."""
import argparse, json, os, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path('C:/УСТРОЙСТВО 1/U1/05_WORK')
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'hermes-echo', 'SECRETS_LOCAL'}
ID_RE = re.compile(r'(?m)^\|\s*([A-Za-zА-Яа-я]{1,3}\d+(?:[.\-]\d+)*)\s*\|')
LINK_RE = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)')
DATE_RE = re.compile(r'\b(\d{1,2})\.(\d{2})(?:\.(20\d\d))?\b')
STATE_NAMES = ('WAVES_STATE.md', 'BACKLOG_ECHO.md', 'STATE.md', '00_НАЧНИ_ЗДЕСЬ.md', 'MAIN_HEARTBEAT.txt')


def _walk(root, name_test, max_depth=7):
    """os.walk with pruning: the tree has deployed copies and worktrees, a plain rglob takes minutes."""
    out = []
    base = len(root.parts)
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith('.')]
        if len(Path(dp).parts) - base >= max_depth:
            dns[:] = []
        for f in fns:
            if name_test(f):
                out.append(Path(dp) / f)
    return out


def _read(p):
    try:
        return p.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def ids_of(text):
    return set(ID_RE.findall(text))


def check_copies(root, work):
    wtxt = _read(work); wids = ids_of(wtxt); res = []
    for p in _walk(root, lambda n: n == 'BACKLOG_ECHO.md'):
        if p.resolve() == work.resolve():
            continue
        t = _read(p); head = '\n'.join(t.split('\n')[:15])
        missing = sorted(wids - ids_of(t))
        res.append({'path': str(p), 'bytes': len(t.encode('utf-8')), 'banner': 'СНИМОК' in head, 'ids': len(ids_of(t)), 'ids_missing_vs_work': len(missing), 'sample_missing': missing[:8], 'looks_like_queue': 'СНИМОК' not in head})
    return {'work_ids': len(wids), 'copies': res, 'without_banner': sum(1 for r in res if r['looks_like_queue'])}


def check_links(files):
    bad = []
    for p in files:
        for m in LINK_RE.finditer(_read(p)):
            t = m.group(1).split('#')[0]
            if not t or re.match(r'^[a-z]+:', t) or t.startswith('mailto'):
                continue
            try:
                if not (p.parent / t).exists():
                    bad.append({'file': str(p), 'target': t})
            except OSError:
                bad.append({'file': str(p), 'target': t})
    return bad


def newest_date(text, today):
    best = None
    for d, mo, y in DATE_RE.findall(text):
        try:
            dt = date(int(y) if y else today.year, int(mo), int(d))
        except ValueError:
            continue
        if dt > today:
            continue
        if best is None or dt > best:
            best = dt
    return best


def check_stale(root, work, max_age, today):
    ref = newest_date(_read(work), today); res = []
    cand = [q for q in _walk(root, lambda n: n in STATE_NAMES) if q.name != 'BACKLOG_ECHO.md' or q.resolve() == work.resolve()]
    cand += [q for q in (root.parent / n for n in STATE_NAMES) if q.is_file()]
    for p in cand:
        t = _read(p); nd = newest_date(t, today)
        nxt = len(re.findall(r'(?im)^\W*(next|дальше)\b', t))
        lag = (ref - nd).days if (ref and nd) else None
        res.append({'path': str(p), 'newest': nd.isoformat() if nd else None, 'lag_days_vs_work': lag, 'next_lines': nxt, 'stale': (nd is None) or (lag is not None and lag > max_age)})
    return {'work_newest': ref.isoformat() if ref else None, 'files': res, 'stale': sum(1 for r in res if r['stale'])}


def check_graph(root, wids):
    g = root / 'graphify-out' / 'graph.json'
    if not g.exists():
        return {'present': False}
    try:
        data = json.loads(g.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'present': True, 'readable': False}
    nodes = data.get('nodes', []); n = len(nodes) or 1
    blob = [json.dumps(x, ensure_ascii=False) for x in nodes]
    twins = sum(1 for b in blob if 'hermes-echo' in b)
    labels = {str(x.get('label') or x.get('id') or '') for x in nodes}
    hit = sum(1 for i in wids if i in labels)
    return {'present': True, 'readable': True, 'nodes': len(nodes), 'hermes_echo_share': round(twins / n, 3), 'backlog_ids_as_nodes': hit, 'backlog_ids': len(wids)}


def run(root, work, max_age=3, today=None):
    today = today or date.today(); wids = ids_of(_read(work))
    states = [p for p in _walk(root, lambda n: n in STATE_NAMES) if p.stat().st_size < 3_000_000]
    return {'root': str(root), 'work': str(work), 'copies': check_copies(root, work), 'dead_links': check_links(states), 'stale': check_stale(root, work, max_age, today), 'graph': check_graph(root, wids)}


def render(r):
    c, s, g = r['copies'], r['stale'], r['graph']
    L = ['# Проверка ссылок и копий бэклога', '', 'Рабочий: %s (ID: %d). Только чтение файлов, ничего не изменено.' % (r['work'], c['work_ids']), '',
         '## Копии бэклога: %d, без пометки «СНИМОК»: %d' % (len(c['copies']), c['without_banner'])]
    for x in c['copies']:
        L.append('- %s %s: ID %d, нет против рабочего %d' % ('[выглядит как очередь]' if x['looks_like_queue'] else '[снимок]', x['path'], x['ids'], x['ids_missing_vs_work']))
    L += ['', '## Битые ссылки в файлах состояния: %d' % len(r['dead_links'])]
    L += ['- %s -> %s' % (b['file'], b['target']) for b in r['dead_links'][:30]]
    L += ['', '## Отстающие файлы состояния: %d (самая свежая дата рабочего: %s)' % (s['stale'], s['work_newest'])]
    L += ['- %s %s: дата %s, отставание %s дн., строк «Next/Дальше» %d' % ('[отстаёт]' if x['stale'] else '[ок]', x['path'], x['newest'], x['lag_days_vs_work'], x['next_lines']) for x in s['files']]
    L += ['', '## Граф']
    if not g.get('present'):
        L.append('- graphify-out/graph.json не найден: нет данных (не «хорошо»)')
    elif not g.get('readable'):
        L.append('- graph.json не читается')
    else:
        L.append('- узлов %d, доля двойников hermes-echo %s, ID бэклога как узлы %d из %d' % (g['nodes'], g['hermes_echo_share'], g['backlog_ids_as_nodes'], g['backlog_ids']))
    return '\n'.join(L) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=str(DEFAULT_ROOT if DEFAULT_ROOT.exists() else ROOT)); ap.add_argument('--work')
    ap.add_argument('--json'); ap.add_argument('--max-age-days', type=int, default=3)
    a = ap.parse_args(argv)
    root = Path(a.root); work = Path(a.work) if a.work else root / 'BACKLOG_ECHO.md'
    r = run(root, work, a.max_age_days)
    if a.json:
        Path(a.json).write_bytes(json.dumps(r, ensure_ascii=False, indent=1).encode('utf-8'))
    sys.stdout.buffer.write(render(r).encode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
