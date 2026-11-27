"""After-call report (w9-game, N126/N192): where the latency of every answer went, as a file next to the journal.

Built on ``cloud_context/scripts/latency_chain.py`` (read-only, loaded from the repo; it is owned by A4): the same parse of the call journal
and the same chain of steps. The report holds NUMBERS AND LABELS ONLY - step names are decision kinds/reasons, never the text of a reply.
``<journal>.jsonl`` -> ``<journal>.report.json``. Local; nothing is sent.

Run: python tools/call_report.py [journal.jsonl | folder]     (a folder: its newest journal; no argument: the default echo_calls folder)
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
        episodes.append({'class': ep['class'], 'path': ep.get('path'), 'pcm_ms': round(ep['pcm_ms']), 'cue_status': ep.get('cue_status'),
                         'steps': [[_label(key), round(ms)] for key, ms in ep['segments']],
                         'marks': {k: round(v) for k, v in (ep.get('marks') or {}).items()}})
    totals = [e['pcm_ms'] for e in episodes]
    sums = {}
    for e in episodes:
        for key, ms in e['steps']:
            sums[key] = sums.get(key, 0) + ms
    biggest = max(sums.items(), key=lambda kv: kv[1]) if sums else None
    return {'call': name, 'elapsed_ms': call['elapsed'], 'episodes': episodes,
            'summary': {'episodes': len(episodes), 'median_ms': chain.med(totals), 'p90_ms': chain.pct(totals, 0.9) if len(totals) >= 5 else None,
                        'max_ms': max(totals) if totals else None, 'biggest_step': list(biggest) if biggest else None,
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


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
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
