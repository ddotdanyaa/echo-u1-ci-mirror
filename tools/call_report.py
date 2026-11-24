"""After-call report (w9-game, N126/N192): where the latency of every answer went, as a file next to the journal.

Built on ``cloud_context/scripts/latency_chain.py`` (read-only, loaded from the repo; it is owned by A4): the same parse of the call journal
and the same chain of steps. The report holds NUMBERS AND LABELS ONLY - step names are decision kinds/reasons, never the text of a reply.
``<journal>.jsonl`` -> ``<journal>.report.json``. Local; nothing is sent.

Run: python tools/call_report.py --table [folder] [--json out.json]     (I2: the table of stages over an archive of calls, with / without a search, with the passport; no latency_chain needed)
     python tools/call_report.py [journal.jsonl | folder]     (a folder: its newest journal; no argument: the default echo_calls folder)
"""
import importlib.util
import json
import sys
from pathlib import Path

_CHAIN = Path(__file__).resolve().parents[1] / 'cloud_context' / 'scripts' / 'latency_chain.py'


def _chain():
    spec = importlib.util.spec_from_file_location('latency_chain', _CHAIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault('latency_chain', module)
    spec.loader.exec_module(module)
    return module


def _default_calls():
    import os
    return Path(os.environ.get('LOCALAPPDATA', '')) / 'hermes-echo' / 'home' / 'profiles' / 'echo-sync' / 'logs' / 'echo_calls'


def latest(folder):
    """The newest call journal of a folder (report files are skipped); None when there is none."""
    folder = Path(folder)
    files = sorted(folder.glob('*.jsonl')) if folder.is_dir() else []
    return files[-1] if files else None


def _label(key):
    return key if isinstance(key, str) else '/'.join(str(part) for part in key if part)      # (kind, reason, evidence) of a decision


def build(rows, name, chain=None):
    chain = chain or _chain()
    call = chain.parse_call(rows, name)
    episodes = []
    for ep in chain.phone_episodes(call):
        if ep.get('segments') is None:
            continue
        pcm_ms = round(ep['pcm_ms'])
        episodes.append({'class': ep['class'], 'path': ep.get('path'), 'pcm_ms': pcm_ms, 'pcm_s': round(pcm_ms / 1000, 2), 'cue_status': ep.get('cue_status'),
                         'steps': [[_label(key), round(ms)] for key, ms in ep['segments']],
                         'marks': {k: round(v) for k, v in (ep.get('marks') or {}).items()}})
    totals = [e['pcm_ms'] for e in episodes]
    sums = {}
    for e in episodes:
        for key, ms in e['steps']:
            sums[key] = sums.get(key, 0) + ms
    biggest = max(sums.items(), key=lambda kv: kv[1]) if sums else None
    med_ms = chain.med(totals)
    p90_ms = chain.pct(totals, 0.9) if len(totals) >= 5 else None
    max_ms = max(totals) if totals else None
    return {'call': name, 'elapsed_ms': call['elapsed'], 'episodes': episodes,
            'summary': {'episodes': len(episodes), 'median_ms': med_ms, 'median_s': round(med_ms / 1000, 2) if med_ms is not None else None,
                        'p90_ms': p90_ms, 'p90_s': round(p90_ms / 1000, 2) if p90_ms is not None else None,
                        'max_ms': max_ms, 'max_s': round(max_ms / 1000, 2) if max_ms is not None else None,
                        'biggest_step': list(biggest) if biggest else None,
                        'step_totals_ms': dict(sorted(sums.items(), key=lambda kv: -kv[1]))}}


def write_report(journal):
    journal = Path(journal)
    try:
        chain = _chain()
        chain_rows = chain.read_rows(journal)
        report = build(chain_rows, journal.stem, chain)
    except Exception as exc:             # the report must never matter more than the call: a broken journal gives an empty one
        report = {'call': journal.stem, 'elapsed_ms': None, 'episodes': [], 'error': type(exc).__name__,
                  'summary': {'episodes': 0, 'median_ms': None, 'p90_ms': None, 'max_ms': None, 'biggest_step': None, 'step_totals_ms': {}}}
    out = journal.with_name(journal.stem + '.report.json')
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


# ---------------------------------------------------------------- the table of stages over an archive of calls (E05, E05.1, U132, U133, W11, E52, U28)
# Self-contained (stdlib): the journal is read here, ``latency_chain`` lives on the owner's laptop and is not in a checkout or the cloud.
# Every number is of the SERVER LAYER (the clock of the call journal: from the ear's cut to the first audible PCM the server wrote); the phone's speaker is another column and is NOT measured (E52).
# Reply texts are never copied: only event names, numbers and counts.
import hashlib
import math
import statistics

EAR_OFFSET_MS = 300                      # local_ear.OFFSET_MS: the quiet the ear needs to call the speech over; the cut is this long after the last voiced sample (a constant of the code, not a measurement)
LINK_MAX_MS = 20000                      # an ear cut older than this before the first PCM is not tied to the sound
FINAL_MAX_MS = 15000
TAIL_MS = 50                             # tolerance for the order of rows of one tick
STAGES = [('ear', 'ухо: отсечка → текст'), ('phrase_end', 'конец фразы: ожидание последнего куска или финала облака'),
          ('job_wait', 'ожидание старта задания модели'), ('model', 'модель: старт задания → первый текст'), ('search', 'поиск: источники вернулись'),
          ('admit', 'допуск и решение контроллера'), ('gate', 'ворота до начала синтеза'), ('synthesis', 'синтез'), ('delivery', 'очередь и кадр до первого PCM')]
TARGETS = {'no_search': (300, 600), 'search': (None, 1000)}     # U132: from the end of the owner's phrase; a target, not a result
USAGE_KEYS = ('input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens', 'reasoning_tokens')
REPORT = 'server layer (journal clock, ear cut to first PCM); the phone speaker is NOT measured (E52)'


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _read(path):
    rows = []
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and _num(row.get('t')) is not None and isinstance(row.get('ev'), str):
                rows.append(row)
    return rows


def _call(rows, name):
    call = {'name': name, 'open': {}, 'ears': [], 'finals': [], 'decisions': [], 'cues': [], 'stages': [], 'jobs': [], 'adopted': [], 'refused': [], 'counts': {}}
    for row in rows:
        ev, t = row['ev'], row['t']
        if ev == 'call_open':
            call['open'] = {k: row.get(k) for k in ('wall', 'source', 'build', 'code', 'flags', 'policy')}
        elif ev == 'ear_final':
            lag = _num(row.get('lag_ms'))
            call['ears'].append({'cut': None if lag is None else t - lag, 'txt': t, 'text': bool(str(row.get('text') or '').strip()), 'kind': row.get('kind')})
        elif ev == 'user_final':
            call['finals'].append(t)
        elif ev == 'decision':
            call['decisions'].append({'t': t, 'kind': row.get('kind'), 'reason': str(row.get('reason'))})
            if row.get('kind') in ('replay', 'retire'):
                call['counts'][row['kind']] = call['counts'].get(row['kind'], 0) + 1
        elif ev in ('cue_end', 'cue_cut'):
            if ev == 'cue_cut':
                call['counts']['cue_cut'] = call['counts'].get('cue_cut', 0) + 1
            if _num(row.get('first_ms')) is not None:
                call['cues'].append({'first': row['first_ms'], 'last': _num(row.get('last_ms')), 'status': row.get('status') or ('cut' if ev == 'cue_cut' else None)})
        elif ev == 'stage' and row.get('name') in ('synthesis_start', 'synthesis_end'):
            call['stages'].append((t, row['name']))
        elif ev == 'fast_job':
            call['jobs'].append({'t': t, 'job': row.get('job'), 'after': _num(row.get('after_ear_ms')), 'ttft': _num(row.get('ttft_ms')),
                                 'used': bool(row.get('released') or row.get('adopted')), 'outcome': str(row.get('outcome')), 'reason': str(row.get('reason')),
                                 'usage': {k: row[k] for k in USAGE_KEYS if _num(row.get(k)) is not None}})
        elif ev == 'fast_refused':
            rule = str(row.get('rule'))
            call['refused'].append(rule)
            call.setdefault('refused_at', []).append((t, rule))
        elif ev == 'fast_refused_sum':
            for rule, count in (row.get('rules') or {}).items():
                rule = str(rule)
                for _ in range(int(count)):
                    call['refused'].append(rule)
                call.setdefault('refused_at', []).append((t, rule))
        elif ev == 'fast_adopted':
            call['adopted'].append({'t': t, 'job': row.get('job'), 'ms': _num(row.get('ms')), 'ready': _num(row.get('ready_ms'))})
    call['cues'].sort(key=lambda c: c['first'])
    return call


def _job_times(call):
    """{job: (start, first_text)} on the call's clock (ms), the way ``latency_chain`` takes them: ``fast_adopted`` is exact, ``fast_job`` through the ear's cut (only when one cut fits)."""
    jobs = {}
    for a in call['adopted']:
        start = a['t'] - a['ms'] if a['ms'] is not None else None
        text = a['t'] - a['ready'] if a['ready'] is not None else None
        jobs[a['job']] = [start, text]
    cuts = sorted(e['cut'] for e in call['ears'] if e['cut'] is not None)
    for j in call['jobs']:
        got = jobs.setdefault(j['job'], [None, None])
        if got[0] is None and j['after'] is not None:
            end = j['t'] - (j['ttft'] or 0)
            fits = [c + j['after'] for i, c in enumerate(cuts) if c + j['after'] <= end + TAIL_MS and c + j['after'] < (cuts[i + 1] if i + 1 < len(cuts) else float('inf'))]
            if len(fits) == 1:
                got[0] = fits[0]
        if got[1] is None and got[0] is not None and j['ttft'] is not None:
            got[1] = got[0] + j['ttft']
    return jobs


def episodes_of(call):
    """One episode per audible cue: the stages from the ear's cut (T0) to the first PCM, adding up to the interval exactly; ``search`` tells the path with a search from the one without."""
    out, prev_first = [], -10 ** 9
    ears = [e for e in call['ears'] if e['cut'] is not None and e['text']]
    jobs = _job_times(call)
    for cue in call['cues']:
        first = cue['first']
        cand = [e for e in ears if e['cut'] <= first + TAIL_MS and first - e['cut'] <= LINK_MAX_MS and e['cut'] > prev_first - 1]
        ear = max(cand, key=lambda e: e['cut']) if cand else None
        prev, prev_first = prev_first, first
        if ear is None:
            continue
        t0 = ear['cut']
        finals = [f for f in call['finals'] if t0 - TAIL_MS <= f <= min(first + 30000, t0 + FINAL_MAX_MS)]
        final = min(finals) if finals else None
        decisions = [d for d in call['decisions'] if max(t0 - 600, prev) <= d['t'] <= first + TAIL_MS and d['kind'] in ('question', 'lookup', 'answer', 'ack', 'resume', 'replay', 'cached')]
        reasons = {d['reason'] for d in decisions}
        searched = any(d['kind'] == 'lookup' and d['reason'].startswith('sources_') for d in decisions)
        if 'ear_first' in reasons or 'local_ear' in reasons or final is None or final > first + TAIL_MS:
            src, src_t = 'ear', ear['txt']
        else:
            src, src_t = 'phrase_end', final
        if src_t > first + TAIL_MS:
            continue
        nodes = [(src_t, src)]
        for d in decisions:
            if d['t'] >= src_t:
                nodes.append((d['t'], 'search' if d['kind'] == 'lookup' and d['reason'].startswith('sources_') else 'admit'))
        pick = None
        for number, (start, text) in jobs.items():
            if text is not None and t0 - 3000 <= text <= first + TAIL_MS and (pick is None or text > jobs[pick][1]):
                pick = number
        if pick is not None:
            start, text = jobs[pick]
            if start is not None and start >= src_t:
                nodes.append((start, 'job_wait'))
            if text >= src_t:
                nodes.append((text, 'model'))
        synth = [(t, n) for t, n in call['stages'] if src_t <= t <= first + TAIL_MS]
        starts = [t for t, n in synth if n == 'synthesis_start']
        ends = [t for t, n in synth if n == 'synthesis_end']
        if starts and ends and max(ends) >= max(starts):
            nodes += [(max(starts), 'gate'), (max(ends), 'synthesis')]
        stages, at = {}, t0
        for t, name in sorted(nodes, key=lambda n: n[0]):
            t = min(max(t, at), first)
            stages[name] = stages.get(name, 0) + (t - at)
            at = t
        stages['delivery'] = stages.get('delivery', 0) + (first - at)
        total = first - t0
        out.append({'call': call['name'], 't0': t0, 'first': first, 'search': searched, 'total_ms': total, 'stages': stages, 'sum_ok': total > 0 and abs(sum(stages.values()) - total) <= 0.1 * total,
                    'path': src, 'status': cue['status'], 'cue_before_final': final is not None and first < final})
    return out


def _follow(call):
    """U28, what the journal holds: counts of replays, retirements, cut cues and the longest quiet between two cues of one stretch (< 15 s). The lag in words and the jumps of the cursor are NOT in the journal (``input_state`` holds them)."""
    gaps = [b['first'] - a['last'] for a, b in zip(call['cues'], call['cues'][1:]) if a['last'] is not None and 0 <= b['first'] - a['last'] < 15000]
    return {'call': call['name'], 'replays': call['counts'].get('replay', 0), 'retired': call['counts'].get('retire', 0), 'cue_cut': call['counts'].get('cue_cut', 0),
            'cues': len(call['cues']), 'longest_quiet_ms': max(gaps) if gaps else None, 'gaps': len(gaps)}


def _stats(values):
    values = sorted(values)
    if not values:
        return None
    return {'n': len(values), 'min': values[0], 'median': statistics.median(values), 'p90': values[max(0, math.ceil(0.9 * len(values)) - 1)] if len(values) >= 5 else None,
            'p95': values[max(0, math.ceil(0.95 * len(values)) - 1)] if len(values) >= 20 else None, 'max': values[-1]}


def jobs_summary(calls):
    """E05.1: what the journal says of the model's jobs: outcomes, why a job was refused (the ``rule``), the first-token time and the tokens spent. Queue depth of the helper is NOT in the journal (named, not guessed)."""
    jobs = [j for c in calls for j in c['jobs']]
    outcomes, refused = {}, {}
    for j in jobs:
        key = f"{j['outcome']}/{j['reason']}"
        outcomes[key] = outcomes.get(key, 0) + 1
    for c in calls:
        for rule in c['refused']:
            refused[rule] = refused.get(rule, 0) + 1
    tokens = {k: sum(j['usage'].get(k, 0) for j in jobs) for k in USAGE_KEYS}
    answered = sum(1 for j in jobs if j['used'])
    return {'jobs': len(jobs), 'used_for_a_cue': answered, 'outcomes': dict(sorted(outcomes.items(), key=lambda kv: -kv[1])), 'refused_by_rule': dict(sorted(refused.items(), key=lambda kv: -kv[1])),
            'ttft_ms': _stats([j['ttft'] for j in jobs if j['ttft'] is not None]), 'tokens': tokens, 'tokens_per_useful_job': round(tokens['total_tokens'] / answered) if answered and tokens['total_tokens'] else None,
            'queue_depth': 'not in the journal'}


def _hash(*parts):
    return hashlib.sha256('\n'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:12]


def stage_table(folder, limit=None):
    """The table of stages over the journals of a folder (phone calls only; probes and synthetic runs are never mixed in, §6). Returns a dict: ``passport``, ``paths`` (stats of every stage with / without a search), ``follow``, ``checks``."""
    folder = Path(folder)
    files = sorted(p for p in folder.glob('*.jsonl') if '.v5tap' not in p.name and '.report' not in p.name)
    if limit:
        files = files[-limit:]
    calls, skipped, other = [], 0, 0
    for path in files:
        rows = _read(path)
        if not rows:
            skipped += 1                                  # an empty file or another schema (the v2 rows have no ``ev``)
            continue
        call = _call(rows, path.stem)
        if call['open'].get('source') not in (None, 'phone'):
            other += 1
            continue
        calls.append(call)
    eps = [e for c in calls for e in episodes_of(c)]
    tables = {}
    for label, group in (('search', [e for e in eps if e['search']]), ('no_search', [e for e in eps if not e['search']])):
        stage_stats = {name: _stats([e['stages'][name] for e in group if name in e['stages']]) for name, _ in STAGES}
        total = _stats([e['total_ms'] for e in group])
        low, high = TARGETS[label]
        tables[label] = {'episodes': len(group), 'total_ms': total, 'stages': {k: v for k, v in stage_stats.items() if v}, 'target_ms': [low, high],
                         'target_met': None if not total else total['median'] <= high, 'cue_before_final': sum(1 for e in group if e['cue_before_final'])}
    walls = sorted(str(c['open'].get('wall')) for c in calls if c['open'].get('wall'))
    me = Path(__file__).read_bytes()
    passport = {'set': 'echo_calls/*.jsonl (phone) @' + _hash(*[c['name'] for c in calls]), 'checker': 'tools/call_report.py @' + hashlib.sha256(me).hexdigest()[:12],
                'profile': '@' + _hash(*sorted({str(c['open'].get('flags')) for c in calls})), 'builds': sorted({str(c['open'].get('build')) for c in calls}),
                'policies': sorted({str(c['open'].get('policy')) for c in calls}), 'load': 'not recorded by the journal (the contract asks quiet / loaded; none is claimed)',
                'n_of_N': f'{len(eps)} answers with a measurable chain of {sum(len(c["cues"]) for c in calls)} audible cues in {len(calls)} phone calls '
                          f'({len(files)} files: {skipped} empty or of another schema, {other} not phone)',
                'span': [walls[0], walls[-1]] if walls else None, 'layer': REPORT, 'zero': f'ear cut; the real end of speech is ~{EAR_OFFSET_MS} ms earlier (OFFSET_MS), the phone to server path is not measured'}
    checks = {'sum_within_10pct': sum(1 for e in eps if e['sum_ok']), 'episodes': len(eps), 'enough_for_u133': len(eps) >= 20}
    return {'passport': passport, 'paths': tables, 'follow': [_follow(c) for c in calls if c['cues']], 'jobs': jobs_summary(calls), 'checks': checks}


def stage_markdown(result):
    p, lines = result['passport'], []
    lines += ['**Паспорт (контракт §6, `07_METRICS_PROVENANCE.md`):** набор ' + p['set'], f"проверяющий {p['checker']}; профиль {p['profile']}; сборки {', '.join(p['builds'])}; нагрузка: {p['load']}",
              f"n из N: {p['n_of_N']}; период {p['span']}", f"**Слой: серверный** ({p['layer']}). Ноль: {p['zero']}.", '']
    for label, title in (('no_search', 'Без поиска (цель U132: 0,3-0,6 с от конца фразы)'), ('search', 'С поиском (цель U132: до 1 с от конца фразы)')):
        t = result['paths'][label]
        lines += [f"### {title}: ответов {t['episodes']}", '']
        if not t['episodes']:
            lines += ['нет данных', '']
            continue
        lines += ['| этап | n | мин, с | медиана, с | p90, с | макс, с |', '|---|---|---|---|---|---|']
        sec = lambda v: '—' if v is None else f'{v / 1000:.2f}'
        names = dict(STAGES)
        for key, s in t['stages'].items():
            lines.append(f"| {names[key]} | {s['n']} | {sec(s['min'])} | {sec(s['median'])} | {sec(s['p90'])} | {sec(s['max'])} |")
        s = t['total_ms']
        lines += [f"| **всего (ухо → первый звук)** | {s['n']} | {sec(s['min'])} | {sec(s['median'])} | {sec(s['p90'])} | {sec(s['max'])} |", '']
    j = result['jobs']
    lines += [f"Задания модели (E05.1): {j['jobs']}, из них дали звук {j['used_for_a_cue']}; исходы {j['outcomes']}; отказы по правилам {j['refused_by_rule']}; первый токен {j['ttft_ms']}; токены {j['tokens']}; глубина очереди: {j['queue_depth']}.", '']
    c = result['checks']
    lines.append(f"Сверка: сумма этапов равна полному времени (±10 %) в {c['sum_within_10pct']} из {c['episodes']} ответов; для U133 нужно не меньше 20 ответов: {'есть' if c['enough_for_u133'] else 'НЕТ, таблица пока не принимается'}.")
    return '\n'.join(lines)



# ---------------------------------------------------------------- I2b: every journal, one row per QUESTION (the denominator is every question the ear heard, §6), phone / probe, build, with / without a search
# A question = an ``ear_final`` of kind ``question``. T0 = the ear's cut (as above). The first cue = the first audible PCM (``cue_end.first_ms``) at or after T0 and before the cut of the next question.
# Outcomes: ``answered`` (a cue after T0), ``covered`` (a cue already sounding at T0 carries on: no new first sound, latency not defined), ``none`` (no cue before the next question: the reason is the last decision of the window).
# NOT measured here: the phone speaker, the real end of speech (~300 ms before T0), the usefulness and the truth of the cue (§6 asks for both), the load of the laptop.
ON_TIME_MS = 3000
BUCKETS = (1000, 3000, 5000, 8000, 15000)
SEARCH_REASON = 'sources_'


def collect(roots, synthetic=()):
    """Call journals of the folders (the live folder and its archive hold one call at most once: the first of equal name and size wins). Probes of the VOICE runs lie deeper: folders are walked one level of ``echo_calls*`` only."""
    seen, files = set(), []
    for root in [(r, 'journal') for r in roots] + [(r, 'synthetic') for r in synthetic]:
        root, label = Path(root[0]), root[1]
        for path in sorted(root.glob('*.jsonl')) if root.is_dir() else []:
            if '.v5tap' in path.name or '.report' in path.name:
                continue
            key = (path.name, path.stat().st_size)
            if key in seen:
                continue
            seen.add(key)
            files.append((path, label))
    return files


def questions_of(call):
    """One row per question of the call: outcome, ms from T0 to the first audible PCM, whether a search stood in the window, the stages when the chain is known."""
    ears = [e for e in call['ears'] if e['cut'] is not None and e['kind'] == 'question']
    ears.sort(key=lambda e: e['cut'])
    episodes = {round(e['first']): e for e in episodes_of(call)}
    out = []
    for i, ear in enumerate(ears):
        t0 = ear['cut']
        end = ears[i + 1]['cut'] if i + 1 < len(ears) else float('inf')
        after = [c for c in call['cues'] if t0 - TAIL_MS <= c['first'] < end]
        late = bool(after) and after[0]['first'] - t0 > FINAL_MAX_MS          # §6: an answer later than 15 s is a miss and stays in the denominator
        cue = after[0] if after and not late else None
        covering = any(c['first'] < t0 - TAIL_MS and (c['last'] or 0) > t0 for c in call['cues'])
        hi = cue['first'] if cue else end
        window = [d for d in call['decisions'] if t0 - 600 <= d['t'] <= (hi if hi != float('inf') else t0 + 30000)]
        searched = any(d['kind'] == 'lookup' and d['reason'].startswith(SEARCH_REASON) for d in window)
        row = {'call': call['name'], 'source': str(call['open'].get('source')), 'build': str(call['open'].get('build') or 'не записана')[:12], 'search': searched, 'cut': t0}
        if cue:
            row.update(outcome='answered', total_ms=cue['first'] - t0)
            ep = episodes.get(round(cue['first']))
            if ep:
                row['stages'] = ep['stages']
        elif late:
            row.update(outcome='late', total_ms=None, late_ms=after[0]['first'] - t0)
        elif covering:
            row.update(outcome='covered', total_ms=None)
        else:
            last = window[-1] if window else None
            refused = [r for tt, r in call.get('refused_at', []) if t0 - 600 <= tt <= min(end, t0 + 30000)]
            row.update(outcome='none', total_ms=None, why=_label((last['kind'], last['reason'])) if last else ('refused/' + refused[-1] if refused else 'no_decision'))
        out.append(row)
    return out


def _share(rows, limit):
    return sum(1 for r in rows if r['total_ms'] is not None and r['total_ms'] <= limit)


def _group(rows):
    """The cell of the table: N = every question, the shares are of N (a miss stays in the denominator), the median/p90/p95 only of the measured ones with n beside them."""
    n = len(rows)
    ans = [r['total_ms'] for r in rows if r['outcome'] == 'answered']
    cell = {'N': n, 'answered': len(ans), 'covered': sum(1 for r in rows if r['outcome'] == 'covered'), 'none': sum(1 for r in rows if r['outcome'] == 'none'), 'late': sum(1 for r in rows if r['outcome'] == 'late'),
            'within': {str(b): _share(rows, b) for b in BUCKETS}, 'stats': _stats(ans)}
    stage_rows = [r['stages'] for r in rows if r.get('stages')]
    cell['stages'] = {name: _stats([s[name] for s in stage_rows if name in s]) for name, _ in STAGES if any(name in s for s in stage_rows)}
    cell['stage_n'] = len(stage_rows)
    whole = sum(sum(s.values()) for s in stage_rows)
    cell['stage_share'] = {name: round(sum(s.get(name, 0) for s in stage_rows) / whole, 3) for name, _ in STAGES} if whole else {}
    return cell


def all_table(roots, synthetic=()):
    files = collect(roots, synthetic)
    calls, rows, empty = [], [], 0
    for path, label in files:
        data = _read(path)
        if not data:
            empty += 1
            continue
        call = _call(data, path.stem)
        if label == 'synthetic':
            call['open']['source'] = 'synthetic'                  # a stand run with a synthetic voice (VOICE/runs): never mixed with a phone or a probe
        calls.append(call)
        rows += questions_of(call)
    groups = {}
    for name, test in (('all', lambda r: True), ('phone', lambda r: r['source'] == 'phone'), ('probe', lambda r: r['source'] not in ('phone', 'synthetic')),
                       ('synthetic', lambda r: r['source'] == 'synthetic')):
        part = [r for r in rows if test(r)]
        groups[name] = {'any': _group(part), 'search': _group([r for r in part if r['search']]), 'no_search': _group([r for r in part if not r['search']])}
    builds = {}
    for b in sorted({r['build'] for r in rows}):
        part = [r for r in rows if r['build'] == b and r['source'] == 'phone']
        if part:
            builds[b] = _group(part)
    why = {}
    for r in rows:
        if r['outcome'] == 'none':
            key = f"{r['source']}: {r['why']}"
            why[key] = why.get(key, 0) + 1
    walls = sorted(str(c['open'].get('wall')) for c in calls if c['open'].get('wall'))
    me = Path(__file__).read_bytes()
    passport = {'set': 'echo_calls* journals of the roots @' + _hash(*[c['name'] for c in calls]), 'roots': [str(r) for r in roots], 'checker': 'tools/call_report.py --all @' + hashlib.sha256(me).hexdigest()[:12],
                'profile': '@' + _hash(*sorted({str(c['open'].get('flags')) for c in calls})), 'builds': sorted({str(c['open'].get('build')) for c in calls}),
                'policies': sorted({str(c['open'].get('policy')) for c in calls}), 'sources': {s: sum(1 for c in calls if str(c['open'].get('source')) == s) for s in sorted({str(c['open'].get('source')) for c in calls})},
                'load': 'not recorded by the journal; none claimed', 'n_of_N': f'{len(rows)} questions of the ear in {len(calls)} journals ({len(files)} files, {empty} empty or of another schema)',
                'span': [walls[0], walls[-1]] if walls else None, 'layer': REPORT, 'zero': f'ear cut; the real end of speech is ~{EAR_OFFSET_MS} ms earlier, the phone path is not measured'}
    return {'passport': passport, 'groups': groups, 'builds_phone': builds, 'none_why': dict(sorted(why.items(), key=lambda kv: -kv[1])), 'jobs': jobs_summary(calls),
            'ear_ms': _stats([e['txt'] - e['cut'] for c in calls for e in c['ears'] if e['cut'] is not None and e['kind'] == 'question'])}


def _sec(v):
    return '—' if v is None else f'{v / 1000:.2f}'


def all_markdown(result):
    p, out = result['passport'], []
    out += ['**Паспорт (§6):** набор ' + p['set'], f"проверяющий {p['checker']}; профиль {p['profile']}; сборки {', '.join(p['builds'])}; политики {', '.join(p['policies'])}; источники {p['sources']}",
            f"нагрузка: {p['load']}; n из N: {p['n_of_N']}; период {p['span']}", f"Слой: серверный ({p['layer']}). Ноль: {p['zero']}. Знаменатель — ВСЕ вопросы уха; промах не уходит из знаменателя.", '']

    def line(name, c):
        s = c['stats'] or {}
        w = c['within']
        pct = lambda b: f"{w[b]} ({100 * w[b] / c['N']:.0f} %)" if c['N'] else '—'
        return f"| {name} | {c['N']} | {c['answered']} | {c['covered']} | {c['late']} | {c['none']} | {pct('1000')} | {pct('3000')} | {pct('5000')} | {pct('8000')} | {_sec(s.get('median'))} | {_sec(s.get('p90'))} | {_sec(s.get('p95'))} | {_sec(s.get('max'))} |"
    head = ['| группа | N вопросов | ответ ≤15 с | уже звучал | позже 15 с | без реплики | ≤1 с | ≤3 с | ≤5 с | ≤8 с | медиана, с | p90 | p95 | макс |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    out += ['### Доля вовремя (от отсечки уха до первого слышимого PCM), доли от N', ''] + head
    for src, title in (('phone', 'телефон'), ('probe', 'проба'), ('synthetic', 'синтетический голос (стенд)'), ('all', 'все')):
        for k, t in (('any', 'всего'), ('no_search', 'без поиска'), ('search', 'с поиском')):
            out.append(line(f'{title}, {t}', result['groups'][src][k]))
    out += ['', '### По сборкам (только телефон)', ''] + head
    for b, c in result['builds_phone'].items():
        out.append(line(b, c))
    out += ['', '### По этапам (ответы с известной цепочкой; сумма этапов равна полному времени; доля = сумма этапа / сумма всех времён)', '', '| группа | этап | n | медиана, с | p90 | макс | доля времени |', '|---|---|---|---|---|---|---|']
    names = dict(STAGES)
    for src in ('phone', 'probe'):
        for k, t in (('no_search', 'без поиска'), ('search', 'с поиском')):
            c = result['groups'][src][k]
            for key, s in c['stages'].items():
                out.append(f"| {src}, {t} (цепочка у {c['stage_n']}) | {names[key]} | {s['n']} | {_sec(s['median'])} | {_sec(s['p90'])} | {_sec(s['max'])} | {100 * c['stage_share'].get(key, 0):.0f} % |")
    e = result['ear_ms']
    out += ['', f"Ухо: текст готов через (медиана) {_sec(e['median']) if e else '—'} с после отсечки, n={e['n'] if e else 0}.", '', '### Почему нет реплики (последнее решение окна)', '']
    out += [f'- {n} × {k}' for k, n in list(result['none_why'].items())[:15]]
    j = result['jobs']
    out += ['', f"Задания модели: {j['jobs']}, дали звук {j['used_for_a_cue']}; первый токен {j['ttft_ms']}; токены {j['tokens']['total_tokens']}; глубина очереди: {j['queue_depth']}."]
    return '\n'.join(out)


def all_main(rest):
    roots = []
    opts = {'--json': None, '--md': None}
    synthetic = []
    i = 0
    while i < len(rest):
        if rest[i] == '--root':
            roots.append(rest[i + 1])
            i += 2
        elif rest[i] == '--synthetic':
            synthetic.append(rest[i + 1])
            i += 2
        elif rest[i] in opts:
            opts[rest[i]] = rest[i + 1]
            i += 2
        else:
            i += 1
    if not roots:
        base = _default_calls()
        roots = [base, base.with_name('echo_calls_archive')]
    result = all_table(roots, synthetic)
    text = all_markdown(result)
    sys.stdout.buffer.write((text + '\n').encode('utf-8'))
    for key, writer in (('--json', lambda f: json.dump(result, f, ensure_ascii=False, indent=1)), ('--md', lambda f: f.write(text + '\n'))):
        if opts[key]:
            with open(opts[key], 'w', encoding='utf-8', newline=chr(10)) as handle:
                writer(handle)
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '--all':                         # python tools/call_report.py --all [--root DIR]... [--synthetic DIR]... [--json out.json] [--md out.md]: every journal, per QUESTION (I2b)
        return all_main(args[1:])
    if args and args[0] == '--table':                       # python tools/call_report.py --table [folder] [--json out.json]: the table of stages over the archive (U133)
        rest = args[1:]
        out_json = rest[rest.index('--json') + 1] if '--json' in rest else None
        folder = next((a for a in rest if not a.startswith('--') and a != out_json), None)
        result = stage_table(folder or _default_calls())
        print(stage_markdown(result))
        if out_json:
            with open(out_json, 'w', encoding='utf-8', newline=chr(10)) as handle:
                json.dump(result, handle, ensure_ascii=False, indent=1)
        return 0
    target = Path(args[0]) if args else _chain().CALLS_DEFAULT
    journal = latest(target) if target.is_dir() else target
    if journal is None or not journal.exists():
        print('no call journal found', file=sys.stderr)
        return 1
    out = write_report(journal)
    rep = json.loads(out.read_text(encoding='utf-8'))
    s = rep['summary']
    print(f"{out}: {s['episodes']} answers, median {s['median_ms']} ms, p90 {s['p90_ms']} ms, biggest step {s['biggest_step']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
