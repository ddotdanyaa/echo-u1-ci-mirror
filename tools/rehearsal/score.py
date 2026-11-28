"""The board of one run and of a rehearsal: what the owner asked for, counted over the record of ``sim.play``.

  to_cue        seconds from the end of a question to the first cue that answers it (p50, p90 over the questions answered)
  silence       per answer: the seconds the user waited in silence, from the question's end to the first cue plus from each repeat's end to the next cue
  false_cue     cues nobody asked for: a plan that answers no question the friend asked (cloud chatter, a passer-by's question, a question after its «неважно»), or sound after «стоп»
  model_down    a question whose model the stand killed (or hung past the wait) and the controller said so with its error frame: counted apart, never as missed
  missed        a friend's question never answered before the next one, when the next one came later than the wait the controller allows (or never)
  false_step    the cursor moved on with no repeat, «дальше» or partial repeat of the user since the portion was said (a stranger's words, nothing, a doubt)
  lost_place    the cursor went back or jumped, or a plan came back by itself (a1's A3 back/jump and A4)
  old_answer    an answer of an older question began after the system had a newer one (a1's A2, not the stop)
Red: ``RED`` (per rehearsal, over all its seeds). An episode: a seed, a moment, the kind, the first cause (the invariant's text and the controller's log before it).
"""
from tools.replay.stand import ANSWER_WAIT_SECONDS, CHATTER_OF_THE_CLOUD, normalize

RED = {'to_cue_p90': 6.0, 'false_cue': 0.05, 'missed': 0.05, 'false_step': 0.02, 'lost_place': 0.01, 'old_answer': 0.02}
WEIGHT = {'old_answer': 6, 'missed': 5, 'lost_place': 5, 'false_step': 4, 'false_cue': 3, 'slow': 1, 'crash': 9, 'error_frame': 2}
ADVANCING = ('repeat', 'partial', 'wrong', 'stutter', 'resume', 'self')


def plan_of(c):
    return ' '.join(c[4])


def quantile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo = int(k)
    return round(xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (k - lo), 2)


def cause(out, t, span=4.0):
    """The controller's own lines just before ``t``: the first cause is read there."""
    lines = [m for at, m in getattr(out, 'ctl', []) if t - span <= at <= t + 0.05]
    keep = [m for m in lines if any(w in m for w in ('act=', 'reason=', 'admit', 'question', 'cue', 'stop', 'drop', 'held', 'release'))] or lines
    return ' | '.join(keep[-3:])[:400]


def model_was_down(out, onset, end, nxt):
    """Every job the stand started between this question and the next one failed or would have given its first text 8 s or more after the question's end (the controller's wait)."""
    jobs = [j for j in out.jobs if onset <= j['at'] < nxt]
    return bool(jobs) and all(j['fail'] or j['at'] + j['first'] - end >= 8.0 for j in jobs)


def board(out):
    """The counts of one run and its episodes."""
    said, cues = out.said, [c for c in out.cues if not c[6]]
    friend = [u for u in said if u.kind in ('question', 'fix') and getattr(u, 'who', 'friend') == 'friend']
    cancelled = getattr(out, 'cancelled', {})                     # question number -> when it was cancelled
    eps, to_cue, silence = [], [], []
    spoken_failures = sum(1 for f in out.errors if str(f.get('error', {}).get('code', '')).startswith('controlled_'))      # the error frames the client says aloud
    m = {'questions': len(friend), 'cues': len(cues), 'answered': 0, 'missed': 0, 'missed_silent': 0, 'model_down': 0, 'false_cue': 0, 'false_step': 0, 'lost_place': 0, 'old_answer': 0, 'crash': int(bool(out.crash))}

    def episode(kind, t, text, after=0.0):
        eps.append({'kind': kind, 'seed': out.seed, 'rehearsal': out.profile.get('rehearsal'), 't': t, 'what': text[:300],
                    'cause': cause(out, t + after, span=max(4.0, after))})

    # to_cue, silence, missed
    for k, u in enumerate(friend):
        nxt = friend[k + 1].onset if k + 1 < len(friend) else float('inf')
        q = u.meaning[1]
        mine = [c for c in cues if u.onset < c[0] < nxt + 0.5 and q.fits(plan_of(c))]
        if u.n in cancelled or any(x.kind == 'stop' and getattr(x, 'who', 'user') != 'other' and u.onset < x.onset < nxt for x in said):
            continue                                       # cancelled («неважно») or stopped by the user: nothing was owed
        if not mine and model_was_down(out, u.onset, u.offset, nxt) and spoken_failures > m['model_down']:
            m['model_down'] += 1       # the stand killed the model for this question (a failure, or a hang past the controller's wait) and the controller sent its error frame, which the client says aloud: an honest answer, not a miss
            continue
        if not mine:
            end = min(nxt, max([c[0] for c in out.cues] + [s.offset for s in said] + [0.0]))
            if nxt - u.offset > ANSWER_WAIT_SECONDS + 3.5 and (nxt != float('inf') or end - u.offset > ANSWER_WAIT_SECONDS + 3.5):
                if not any(u.offset < t < u.offset + ANSWER_WAIT_SECONDS + 3.5 for t in out.reconnects):
                    m['missed'] += 1
                    told = any(c[6] and u.offset < c[0] < min(nxt, u.offset + ANSWER_WAIT_SECONDS + 3.5) for c in out.cues)
                    m['missed_silent'] += not told
                    episode('missed', round(u.offset, 2), f'question {u.n} {u.text!r} never answered{" (a timeout was said)" if told else " and nothing said"} (next at {nxt if nxt != float("inf") else "end"})',
                            after=ANSWER_WAIT_SECONDS + 3.5)                  # the controller's lines after the question: what it did with it
            continue
        m['answered'] += 1
        wait = max(0.0, mine[0][0] - u.offset)
        to_cue.append(wait)
        if wait > 6.0:
            episode('slow', round(mine[0][0], 2), f'{wait:.1f} s to the first cue of question {u.n} {u.text!r}')
        total = wait
        for r in [x for x in said if x.kind in ADVANCING and mine[0][0] < x.onset < nxt and getattr(x, 'who', 'user') != 'other']:
            after = [c for c in cues if c[0] > r.offset and c[0] < nxt]
            if after:
                total += max(0.0, after[0][0] - r.offset)
        silence.append(total)

    # false cues: a plan that answers nothing the friend asked (or a cancelled question), the cloud's chatter, sound after a stop
    asked = [(u, u.meaning[1]) for u in friend]
    flagged = set()
    for c in cues:
        text = plan_of(c)
        before = [(u, q) for u, q in asked if u.onset < c[0]]
        good = [u for u, q in before if q.fits(text) and c[0] < cancelled.get(u.n, float('inf'))]       # a cancelled question's answer: only before «неважно»
        chatter = any(normalize(x) and normalize(x) in normalize(text) for x in CHATTER_OF_THE_CLOUD)
        if chatter or not good:
            m['false_cue'] += 1
            flagged.add(c[0])
            episode('false_cue', c[0], f'cue {c[1]!r} of plan {text[:120]!r} answers no question asked' + (' (cloud chatter)' if chatter else ''))
    for inv, t, msg in out.violations:
        if inv == 'A2' and 'стоп' in msg and t not in flagged:
            m['false_cue'] += 1
            episode('false_cue', t, msg)
        elif inv == 'A2':
            m['old_answer'] += 1
            episode('old_answer', t, msg)
        elif inv in ('A3', 'A4') and ('back' in msg or 'jumped' in msg or 'came back' in msg):
            m['lost_place'] += 1
            episode('lost_place', t, msg)
        elif inv == 'A0':
            episode('error_frame' if msg.startswith('error frame') else 'crash', t, msg)

    # false steps: every advance needs a repeat-like utterance of the user since the portion was said
    last, used = {}, set()
    for t, rev, index, completed, waiting, hearing, call in out.states:
        if rev is None or index is None:
            continue
        before = last.get(rev)
        if before is not None and index == before[1] + 1:
            spoken = [c for c in cues if c[2] == rev and c[3] == before[1] and c[0] <= t]
            since = spoken[0][0] if spoken else before[0]
            own = [u for u in said if since - 0.5 < u.onset <= t and u.n not in used and u.kind in ADVANCING and getattr(u, 'who', 'user') != 'other']
            chunks = next((c[4] for c in cues if c[2] == rev and len(c) > 4 and isinstance(c[4], (tuple, list)) and len(c[4]) > before[1]), None)
            ahead = chunks and normalize(chunks[before[1]]) and [u for u in said if u.onset <= t and u.offset is not None and u.offset >= before[0] - 15
                                                                and u.kind in ADVANCING + ('more',) and normalize(chunks[before[1]]) in normalize(u.text)]
            if own:
                used.add(own[0].n)               # the EARLIEST unused utterance of the window pays for this advance (the last one left the earlier advance with none)
            elif ahead:
                pass                     # g7: the user said this portion ahead of its cue, in the utterance that took the one before it
            else:
                m['false_step'] += 1
                others = [u for u in said if since - 0.5 < u.onset <= t]
                episode('false_step', t, f'revision {rev}: {before[1]} -> {index} with no repeat of the user since {since}; said: '
                                         + '; '.join(f'{u.kind}/{getattr(u, "who", "")} {u.text[:40]!r}' for u in others[-3:]))
        last[rev] = (t, index)
    m['to_cue'], m['silence'] = [round(x, 2) for x in to_cue], [round(x, 2) for x in silence]
    m['invariants'] = sorted({inv for inv, *_ in out.violations})
    return m, eps


def total(rows):
    """The board of a rehearsal: the runs' counts summed, the rates per question (per cue for false cues, per advance-able cue for steps), red or not."""
    agg = {k: sum(r.get(k, 0) for r in rows) for k in ('questions', 'cues', 'answered', 'missed', 'missed_silent', 'model_down', 'false_cue', 'false_step', 'lost_place', 'old_answer', 'crash')}
    to_cue = [x for r in rows for x in r['to_cue']]
    silence = [x for r in rows for x in r['silence']]
    q, c = max(1, agg['questions']), max(1, agg['cues'])
    b = {'seeds': len(rows), **agg, 'to_cue_p50': quantile(to_cue, 0.5), 'to_cue_p90': quantile(to_cue, 0.9), 'silence_p50': quantile(silence, 0.5),
         'silence_mean': round(sum(silence) / len(silence), 2) if silence else None,
         'rate': {'false_cue': round(agg['false_cue'] / c, 4), 'missed': round(agg['missed'] / q, 4), 'false_step': round(agg['false_step'] / c, 4),
                  'lost_place': round(agg['lost_place'] / c, 4), 'old_answer': round(agg['old_answer'] / q, 4)}}
    red = [k for k in ('false_cue', 'missed', 'false_step', 'lost_place', 'old_answer') if b['rate'][k] > RED[k]]
    if b['to_cue_p90'] is not None and b['to_cue_p90'] > RED['to_cue_p90']:
        red.insert(0, 'to_cue_p90')
    if agg['crash']:
        red.insert(0, 'crash')
    if agg['questions'] and not agg['answered']:
        red.insert(0, 'nothing_answered')
    b['red'] = red
    return b


def worst(episodes, n=20, boards=None):
    """The worst ``n``: the kinds in turn, heaviest first (so the list shows every kind there is); within a kind the rehearsals with the most of it first
    (``boards``), one per rehearsal before a second one, seeds small first."""
    by = {}
    for e in sorted(episodes, key=lambda e: (e['seed'], e['t'])):
        by.setdefault(e['kind'], []).append(e)
    queues = {}
    for kind, rows in by.items():
        seen, first, rest = set(), [], []
        for e in rows:
            (rest if e['rehearsal'] in seen else first).append(e)
            seen.add(e['rehearsal'])
        many = lambda e: -((boards or {}).get(e['rehearsal'], {}).get('rate', {}).get(kind, 0) or len([x for x in rows if x['rehearsal'] == e['rehearsal']]))
        queues[kind] = sorted(first, key=lambda e: (many(e), e['rehearsal'] or '')) + rest
    out, kinds = [], sorted(queues, key=lambda k: -WEIGHT.get(k, 1))
    while len(out) < n and any(queues.values()):
        for kind in kinds:
            if queues[kind] and len(out) < n:
                out.append(queues[kind].pop(0))
    return sorted(out, key=lambda e: (-WEIGHT.get(e['kind'], 1), e['rehearsal'] or '', e['seed']))


def kept(episodes, per=3):
    """A few episodes of each (rehearsal, kind), smallest seeds first: enough to rebuild the worst list from the JSON."""
    out, count = [], {}
    for e in sorted(episodes, key=lambda e: (e['rehearsal'] or '', e['kind'], e['seed'], e['t'])):
        key = (e['rehearsal'], e['kind'])
        if count.get(key, 0) < per:
            count[key] = count.get(key, 0) + 1
            out.append(e)
    return out
