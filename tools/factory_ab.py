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
            result[arm] = {'n': 0, 'ok': 0}
        result[arm]['n'] += 1
        if row.get('status') in ('REVIEW', 'PROMOTED', 'DONE'):
            result[arm]['ok'] += 1
    return result


def decide(per_arm: dict, min_n: int = 10, margin: float = 0.15):
    if len(per_arm) < 2 or any(v['n'] < min_n for v in per_arm.values()):
        return None
    rates = {arm: round(v['ok'] / v['n'], 4) for arm, v in per_arm.items()}
    sorted_arms = sorted(rates.keys(), key=lambda a: rates[a], reverse=True)
    best = sorted_arms[0]
    other = rates[sorted_arms[1]]
    if rates[best] - other < margin:
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
