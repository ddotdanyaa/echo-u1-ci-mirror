"""The rehearsals: one command on any head and any set of flags; the comparison of two heads.

    python -m tools.rehearsal.run [--rehearsals Р001-Р100] [--seeds 100] [--seed0 0] [--jobs 4] [--flags fast_text:off,instant:on] [--head REF]
                                  [--mutant mute|stale] [--minutes-cap M] [--json board.json] [--md board.md]
    python -m tools.rehearsal.run compare old.json new.json [--md diff.md]

``--head REF``: the engine (``echo_sync/``, ``tests/`` helpers) of commit REF in a git worktree, the stand (``tools/replay``, ``tools/rehearsal``) of this tree copied
over it, the same command run there. ``--minutes-cap``: no run longer than M simulated minutes (the board says so). Seconds are the stand's, not a laptop's.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from tools.rehearsal import plan as P
from tools.rehearsal import score

ROOT = Path(__file__).resolve().parents[2]
LIMIT_S = 1800                    # one run's wall time; past it the run is a crash of the board (a hang of the stand or of the chain)


def _one(task):
    name, seed, flags, mutant, cap = task
    import logging
    logging.disable(logging.NOTSET)
    from tools.rehearsal import sim
    spec = sim.Spec(name)
    if cap and spec.minutes > cap:
        spec.minutes = cap
    began = time.time()
    import signal

    def late(*_):
        raise TimeoutError(f'{name} seed {seed}: more than {LIMIT_S} s of wall time')
    signal.signal(signal.SIGALRM, late)
    signal.alarm(LIMIT_S)
    try:
        out = sim.play(spec, seed, flags=flags, mutant=mutant)
    finally:
        signal.alarm(0)
    metrics, eps = score.board(out)
    return name, seed, metrics, eps, round(time.time() - began, 2)


NOISE_SEEDS = 20           # U136: a board before/after on fewer seeds than this is noise; the proof of a lock is a shrunk scene red before, green after


def rehearse(names, seeds, *, seed0=0, jobs=4, flags=None, mutant=None, cap=None, long_seeds=None, progress=True):
    """Every (rehearsal, seed): the board of each rehearsal, all episodes, the wall seconds."""
    def count(n):
        return long_seeds if long_seeds and float(P.parse(P.PLAN[n])[1].get('min', 2)) > 10 and not (cap and cap <= 10) else seeds
    tasks = [(n, s, flags, mutant, cap) for n in names for s in range(seed0, seed0 + count(n))]
    tasks.sort(key=lambda t: -min(float(P.parse(P.PLAN[t[0]])[1].get('min', 2)), cap or 1e9))     # the long ones first
    rows, eps, began, done = {n: [] for n in names}, [], time.time(), 0
    with Pool(jobs) as pool:
        for name, seed, metrics, episodes, wall in pool.imap_unordered(_one, tasks, chunksize=1):
            rows[name].append(metrics)
            eps += episodes
            done += 1
            if progress and done % 100 == 0:
                print(f'.. {done}/{len(tasks)} runs, {time.time() - began:.0f} s', file=sys.stderr, flush=True)
    boards = {n: score.total(rows[n]) for n in names}
    return boards, eps, round(time.time() - began)


def markdown(result):
    lines = [f"Голова `{result['head']}`, флаги `{result['flags'] or '-'}`, сидов на репетицию {result['seeds']} (с {result['seed0']}; длиннее 10 минут: {result.get('long_seeds') or result['seeds']}), "
             f"предел минут {result['cap'] or 'нет'}, {result['wall']} с на {result['jobs']} процессах" + (f", сломанный контроллер `{result['mutant']}`" if result['mutant'] else ''),
             '', '| Р | название | вопр | подсказок | до подсказки p50/p90, с | тишина на ответ p50, с | ложн. подск. | пропущ. (из них молча) | ложн. переход | потеря позиции | старый ответ | красное |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, b in result['boards'].items():
        title = P.parse(P.PLAN[name])[0]
        approx = P.parse(P.PLAN[name])[1].get('approx')
        lines.append(f"| {name} | {title}{' (≈' + approx + ')' if approx else ''} | {b['questions']} | {b['cues']} | {b['to_cue_p50']}/{b['to_cue_p90']} | {b['silence_p50']} | "
                     f"{b['false_cue']} | {b['missed']} ({b.get('missed_silent', '?')}) | {b['false_step']} | {b['lost_place']} | {b['old_answer']} | {', '.join(b['red']) or '—'} |")
    reds = [n for n, b in result['boards'].items() if b['red']]
    lines += ['', f"Красных репетиций: {len(reds)} из {len(result['boards'])}" + (f": {', '.join(reds)}" if reds else ''), '',
              f'Пороги красного (доля): {score.RED}', '', '## Худшие 20 эпизодов', '', '| # | вид | Р | сид | с | что | первая причина (журнал контроллера до момента) |', '|---|---|---|---|---|---|---|']
    for k, e in enumerate(result['worst'], 1):
        lines.append(f"| {k} | {e['kind']} | {e['rehearsal']} | {e['seed']} | {e['t']} | {e['what'][:200].replace('|', '/')} | {e['cause'][:260].replace('|', '/')} |")
    return '\n'.join(lines) + '\n'


def at_head(ref, argv):
    """Run the same command with the engine of ``ref``: a worktree, this stand copied in, the board read back."""
    sha = subprocess.run(['git', 'rev-parse', ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    where = Path(os.environ.get('REHEARSAL_HEADS', '/tmp/rehearsal-heads')) / sha[:12]
    if not where.exists():
        where.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'worktree', 'add', '--detach', str(where), sha], cwd=ROOT, check=True, capture_output=True)
    for part in ('tools/replay', 'tools/rehearsal'):
        shutil.rmtree(where / part, ignore_errors=True)
        shutil.copytree(ROOT / part, where / part, ignore=shutil.ignore_patterns('__pycache__'))
    for helper in ('helpers_s6_state.py', 'test_ear_shadow.py'):
        if not (where / 'tests' / helper).exists():
            shutil.copy(ROOT / 'tests' / helper, where / 'tests' / helper)
    out = where / 'board.json'
    rest, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in ('--head', '--json', '--md'):
            skip = True
            continue
        rest.append(a)
    out.unlink(missing_ok=True)
    done = subprocess.run([sys.executable, '-m', 'tools.rehearsal.run', *rest, '--json', str(out), '--label', sha[:12]], cwd=where)
    if done.returncode not in (0, 1) or not out.exists():                      # 1: the board has red, which is an answer, not a failure
        raise RuntimeError(f'the rehearsal at {sha[:12]} failed: exit {done.returncode}')
    return json.loads(out.read_text(encoding='utf-8'))


def compare(a, b):
    lines = [f"Сравнение: A `{a['head']}` флаги `{a['flags'] or '-'}` против B `{b['head']}` флаги `{b['flags'] or '-'}`; сидов {a['seeds']} / {b['seeds']}", '',
             '| Р | до подсказки p50 A→B | p90 A→B | ложн. подск. | пропущ. | ложн. переход | потеря позиции | старый ответ | красное A → B |', '|---|---|---|---|---|---|---|---|---|']
    for name in a['boards']:
        if name not in b['boards']:
            continue
        x, y = a['boards'][name], b['boards'][name]
        cell = lambda k: f"{x[k]}→{y[k]}" + (' ▲' if y[k] > x[k] else ' ▼' if y[k] < x[k] else '')
        lines.append(f"| {name} | {x['to_cue_p50']}→{y['to_cue_p50']} | {x['to_cue_p90']}→{y['to_cue_p90']} | {cell('false_cue')} | {cell('missed')} | {cell('false_step')} | "
                     f"{cell('lost_place')} | {cell('old_answer')} | {','.join(x['red']) or '—'} → {','.join(y['red']) or '—'} |")
    few = min(a['seeds'], b['seeds'])
    lines.append('')
    if few < NOISE_SEEDS:
        lines.append(f'ШУМ: сидов {few} < {NOISE_SEEDS}: разница досок на таком числе сидов шум (одна правка сдвигает все линии).')
    lines.append('Разница досок не доказательство замка: доказательство это сцена `python -m tools.rehearsal.shrink`, красная до правки и зелёная после (U136).')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['compare']:
        p = argparse.ArgumentParser()
        p.add_argument('a')
        p.add_argument('b')
        p.add_argument('--md')
        a = p.parse_args(argv[1:])
        text = compare(*(json.loads(Path(x).read_text(encoding='utf-8')) for x in (a.a, a.b)))
        print(text)
        if a.md:
            Path(a.md).write_text(text, encoding='utf-8')
        return 0
    p = argparse.ArgumentParser()
    p.add_argument('--rehearsals', default='all')
    p.add_argument('--seeds', type=int, default=100)
    p.add_argument('--seed0', type=int, default=0)
    p.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    p.add_argument('--flags', default='')
    p.add_argument('--head')
    p.add_argument('--mutant', choices=('mute', 'stale'))
    p.add_argument('--minutes-cap', type=float)
    p.add_argument('--long-seeds', type=int, help='seeds of a rehearsal longer than 10 minutes (default: --seeds)')
    p.add_argument('--json')
    p.add_argument('--md')
    p.add_argument('--label')
    a = p.parse_args(argv)
    if a.head:
        result = at_head(a.head, argv)
    else:
        flags = dict(kv.split(':', 1) for kv in a.flags.split(',')) if a.flags else {}
        names = P.names(a.rehearsals)
        boards, eps, wall = rehearse(names, a.seeds, seed0=a.seed0, jobs=a.jobs, flags=flags, mutant=a.mutant, cap=a.minutes_cap, long_seeds=a.long_seeds)
        head = a.label or subprocess.run(['git', 'rev-parse', '--short=12', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(['git', 'status', '--porcelain', 'echo_sync'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        result = {'head': head + ('+dirty' if dirty else ''), 'flags': a.flags, 'seeds': a.seeds, 'long_seeds': a.long_seeds, 'seed0': a.seed0, 'cap': a.minutes_cap, 'jobs': a.jobs, 'mutant': a.mutant,
                  'wall': wall, 'boards': boards, 'worst': score.worst(eps, boards=boards), 'episodes': score.kept(eps), 'red': [n for n, b in boards.items() if b['red']]}
    text = markdown(result)
    print(text)
    if a.json:
        Path(a.json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    if a.md:
        Path(a.md).write_text(text, encoding='utf-8')
    return 1 if result['red'] else 0


if __name__ == '__main__':
    sys.exit(main())
