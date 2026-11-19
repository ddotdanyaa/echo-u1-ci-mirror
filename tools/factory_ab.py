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


def decide(per_arm: dict, min_n: int = 10, margin: float = 0.15, per_hour: bool = False, min_ok: int = 3):
    """The better arm, or None without enough cases or a clear margin. Per run: the pass rates differ by ``margin``.
    ``per_hour``: the rate is passes per hour of the arm's own run time, the best has at least ``min_ok`` passes and
    beats the next by the factor 1 + ``margin`` (an arm that only costs time is the slower one)."""
    if len(per_arm) < 2 or any(v['n'] < min_n for v in per_arm.values()):
        return None
    if per_hour:
        rates = {arm: round(v['ok'] * 3600.0 / v['s'], 4) if v.get('s') else 0.0 for arm, v in per_arm.items()}
    else:
        rates = {arm: round(v['ok'] / v['n'], 4) for arm, v in per_arm.items()}
    sorted_arms = sorted(rates.keys(), key=lambda a: rates[a], reverse=True)
    best = sorted_arms[0]
    other = rates[sorted_arms[1]]
    if per_hour:
        if per_arm[best]['ok'] < min_ok or rates[best] <= other * (1 + margin):
            return None
    elif rates[best] - other < margin:
        return None
    return {
        'winner': best,
        'rates': rates,
        'n': {arm: v['n'] for arm, v in per_arm.items()}
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
