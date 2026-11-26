"""I12 (W09, R31-2, U155, U84): the morning report from git, one sheet. python -m tools.morning_report [--since "18 hours ago"] [--rev HEAD] [--md PATH] [--json PATH].
Three sections (U155): DONE_IN_CODE (the commit changes a non-test file of the engine `echo_sync/`), ONLY_RESEARCHED (the commit changes only docs, reports, research, classes, evidence: nothing that runs),
OFF (the commit touches the engine but its subject says it is behind a switch that is off / a shadow / a stub / disabled: it is in the code and does NOT work yet).
Two more lines that are not «done»: TESTS_TOOLS (tests and tools only: they prove or measure, they do not change the call) and OTHER.
The number the owner asked for: the engine commits in the window and `echo_sync/` lines added/removed (numstat, tests excluded).
Everything is read from `git log`: nothing is measured on a call and nothing here is a latency number. A commit is classified by its files and its subject, not by what it claims."""
import argparse, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = 'echo_sync/'
TEST_PARTS = ('tests/',)
TOOL_PARTS = ('tools/', 'scripts/')
DOC_PARTS = ('docs_wave/', 'lane_reports/', 'research/', 'classes/', 'evidence/', 'registry_proof/', 'cloud_context/')
DOC_EXT = ('.md', '.txt', '.log', '.json', '.tsv', '.csv')
OFF_RE = re.compile(r'behind (a|the) (flag|switch)|\b(off by default|disabled|shadow|stub|dormant|not wired|unwired)\b|выключен|за флагом|тень|не подключ', re.I)
SEP = '\x1e'


def _git(args, root):
    r = subprocess.run(['git', '-C', str(root)] + args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError('git ' + ' '.join(args) + ': ' + r.stderr.strip()[:300])
    return r.stdout


def _is_engine(path):
    return path.startswith(ENGINE) and not path.startswith(ENGINE + 'tests/')


def _is_doc(path):
    return path.startswith(DOC_PARTS) or (('/' not in path) and path.endswith(DOC_EXT))


def classify(subject, files):
    """-> one of DONE_IN_CODE, OFF, ONLY_RESEARCHED, TESTS_TOOLS, OTHER. `files` = list of paths of the commit."""
    if any(_is_engine(f) for f in files):
        return 'OFF' if OFF_RE.search(subject) else 'DONE_IN_CODE'
    if files and all(f.startswith(TEST_PARTS + TOOL_PARTS) for f in files):
        return 'TESTS_TOOLS'
    if files and all(_is_doc(f) for f in files):
        return 'ONLY_RESEARCHED'
    return 'OTHER'


def commit_id(subject):
    m = re.match(r'^([A-Za-zА-Яа-я]{1,3}\d+(?:[.\-]\d+)*)\s*:', subject)
    return m.group(1) if m else ''


def collect(root=ROOT, since='18 hours ago', rev='HEAD'):
    out = _git(['log', rev, '--since=' + since, '--numstat', '--format=' + SEP + '%h%x09%ad%x09%s', '--date=format:%d.%m %H:%M'], root)
    commits = []
    for block in out.split(SEP)[1:]:
        lines = block.strip('\n').split('\n')
        sha, when, subject = (lines[0].split('\t', 2) + ['', ''])[:3]
        files, add, dele = [], 0, 0
        for ln in lines[1:]:
            p = ln.split('\t')
            if len(p) != 3:
                continue
            files.append(p[2])
            if _is_engine(p[2]) and p[0].isdigit() and p[1].isdigit():
                add += int(p[0]); dele += int(p[1])
        commits.append({'sha': sha, 'when': when, 'subject': subject, 'id': commit_id(subject), 'class': classify(subject, files), 'files': len(files), 'engine_add': add, 'engine_del': dele})
    return commits


def summarize(commits):
    s = {k: [] for k in ('DONE_IN_CODE', 'ONLY_RESEARCHED', 'OFF', 'TESTS_TOOLS', 'OTHER')}
    for c in commits:
        s[c['class']].append(c)
    eng = [c for c in commits if c['class'] in ('DONE_IN_CODE', 'OFF')]
    return {'sections': s, 'engine_commits': len(eng), 'engine_added': sum(c['engine_add'] for c in eng), 'engine_removed': sum(c['engine_del'] for c in eng), 'total': len(commits),
            'ids_in_code': sorted({c['id'] for c in s['DONE_IN_CODE'] if c['id']})}


TITLES = (('DONE_IN_CODE', 'Сделано в коде (движок изменён)'), ('OFF', 'В коде, но выключено или тень (не работает на звонке)'),
          ('ONLY_RESEARCHED', 'Только исследовано (документы, ничего не запускается)'), ('TESTS_TOOLS', 'Тесты и инструменты (проверяют, не меняют звонок)'), ('OTHER', 'Прочее'))


def render(summary, since, rev, limit=40):
    s = summary['sections']
    L = ['# Утренний отчёт из git', '', 'Окно: %s, ветка/ревизия: %s. Классы по файлам и заголовку коммита, не по заявлениям; замеров звонка здесь нет.' % (since, rev), '',
         'Коммитов за окно: %d. Изменений движка: %d коммитов, строк +%d / -%d (`echo_sync/`, без тестов).' % (summary['total'], summary['engine_commits'], summary['engine_added'], summary['engine_removed']), '']
    for key, title in TITLES:
        rows = s[key]
        L.append('## %s: %d' % (title, len(rows)))
        for c in rows[:limit]:
            L.append('- %s %s %s%s' % (c['sha'], c['when'], (c['id'] + ' ') if c['id'] and not c['subject'].startswith(c['id']) else '', c['subject'][:110]))
        if len(rows) > limit:
            L.append('- ... ещё %d' % (len(rows) - limit))
        L.append('')
    L.append('ID, закрытые в коде в окне (по заголовку `<ID>: ...`): ' + (', '.join(summary['ids_in_code']) or 'нет'))
    L.append('Если «Сделано в коде» пусто, а тестов много, это не успех: движок не менялся.')
    return '\n'.join(L) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=str(ROOT)); ap.add_argument('--since', default='18 hours ago'); ap.add_argument('--rev', default='HEAD')
    ap.add_argument('--md'); ap.add_argument('--json'); ap.add_argument('--limit', type=int, default=40)
    a = ap.parse_args(argv)
    summary = summarize(collect(Path(a.root), a.since, a.rev))
    text = render(summary, a.since, a.rev, a.limit)
    if a.md:
        Path(a.md).write_bytes(text.encode('utf-8'))
    if a.json:
        Path(a.json).write_bytes(json.dumps(summary, ensure_ascii=False, indent=1).encode('utf-8'))
    sys.stdout.buffer.write(text.encode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
