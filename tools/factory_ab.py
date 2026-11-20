"""<id>, A/B experiments built into the conveyor: a task gets an arm by a stable hash, outcomes are counted per arm from the telemetry, the better arm is decided only with enough cases and a clear margin, the decision goes to the growth journal."""
import hashlib
import json
from pathlib import Path


def assign(task_id: str, experiment: str, arms) -> str:
    digest = hashlib.sha256((experiment + ':' + task_id).encode('utf-8')).hexdigest()
    return arms[int(digest, 16) % len(arms)]


def outcomes(rows, experiment: str) -> dict:
    result = {}
    for row in rows:
        if row.get('action') != 'RUN':
            continue
        exps = row.get('experiments') or {}
        arm = exps.get(experiment)
        if arm is None:
            continue
        if arm not in result:
            result[arm] = {'n': 0, 'ok': 0, 's': 0.0}
        result[arm]['n'] += 1
        dur = row.get('dur_s')
        if isinstance(dur, (int, float)) and not isinstance(dur, bool) and dur > 0:
            result[arm]['s'] = round(result[arm]['s'] + dur, 3)      # the arm's own run time
        if row.get('status') in ('REVIEW', 'PROMOTED', 'DONE'):
            result[arm]['ok'] += 1
    return result


CHEAPER_FACTOR = 1.5     # one arm's runs take this many times as long as the other's


def cheaper(per_arm: dict):
    """The arm that wins when neither arm has passes enough to be compared by passes per hour: the other one takes at
    least CHEAPER_FACTOR times as long per run and won no more passes than it. None otherwise (more or fewer than two
    timed arms, a small difference in time, the slow arm has more passes). Live 20.11: a small model as a later
    tournament candidate took 182 s per run against 64 s (74 and 96 runs, 1.35 h of the loop's time) and won none, but
    the per-hour rule wanted three passes of the winner, so the experiment never ended."""
    timed = {arm: v['s'] / v['n'] for arm, v in per_arm.items() if v.get('s') and v.get('n')}
    if len(timed) != 2:
        return None
    fast, slow = sorted(timed, key=timed.get)
    if timed[slow] >= timed[fast] * CHEAPER_FACTOR and per_arm[slow]['ok'] <= per_arm[fast]['ok']:
        return fast
    return None


def decide(per_arm: dict, min_n: int = 10, margin: float = 0.15, per_hour: bool = False, min_ok: int = 3):
    """The better arm, or None without enough cases or a clear margin. Per run: the pass rates differ by ``margin``.
    ``per_hour``: the rate is passes per hour of the arm's own run time, the best has at least ``min_ok`` passes and
    beats the next by the factor 1 + ``margin`` (an arm that only costs time is the slower one); when the best has
    fewer passes, the arm that only costs time and wins no more passes still loses (``cheaper``)."""
    if len(per_arm) < 2 or any(v['n'] < min_n for v in per_arm.values()):
        return None
    if per_hour:
        rates = {arm: round(v['ok'] * 3600.0 / v['s'], 4) if v.get('s') else 0.0 for arm, v in per_arm.items()}
    else:
        rates = {arm: round(v['ok'] / v['n'], 4) for arm, v in per_arm.items()}
    sorted_arms = sorted(rates.keys(), key=lambda a: rates[a], reverse=True)
    best = sorted_arms[0]
    other = rates[sorted_arms[1]]
    counts = {arm: v['n'] for arm, v in per_arm.items()}
    if per_hour:
        if per_arm[best]['ok'] < min_ok:
            winner = cheaper(per_arm)
            return None if winner is None else {'winner': winner, 'rates': rates, 'n': counts, 'why': 'cheaper'}
        if rates[best] <= other * (1 + margin):
            return None
    elif rates[best] - other < margin:
        return None
    return {
        'winner': best,
        'rates': rates,
        'n': counts
    }


def record(path, experiment: str, decision, when: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {'when': when, 'experiment': experiment}
    if decision is not None:
        row.update(decision)
    else:
        row['winner'] = None
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
