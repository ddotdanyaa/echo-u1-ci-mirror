"""U15-S2: what the utterance judge did in one call - ``echo-sync judge`` records (one per utterance), the analyze calls they count, the jobs kept (``fast_keep``) and
the keeps that were a different question (``false_keeps``: ``meaning_guard`` of what the job heard against what was asked says DIFFERS), and the U06 wrong refusals
(``tools.harvest.events``). Numbers only. A journal that predates the judge line has resolutions 0.

Run: python -m tools.replay.u15_report <journal.jsonl | fixture.json> ...
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from echo_sync.fast_text import meaning_guard      # noqa: E402
from echo_sync.utterance_judge import DIFFERS      # noqa: E402
from tools import harvest                          # noqa: E402


def _once(judged):
    """One judge row per utterance (tid): ``_abandons`` re-enters the judge for the same tid, and a final can be judged twice. The LAST row is the verdict that stood; a row with no tid stands alone."""
    last = {}
    for n, row in enumerate(judged):
        last[row.get('tid') if row.get('tid') is not None else ('row', n)] = row
    return list(last.values())


def _count(judged, kept, events):
    # Counting rule: ``resolutions`` = utterances (distinct tid) that have a judge line; a final that returns before the judge (_try_final, _take_back, a seen tid)
    # has none, and the c9-numveto analyze is made outside ``_judge`` and is NOT in ``analyses``. ``analyses`` sums every judge row (a re-entered tid counts its analyzes both times).
    by_rule = {}
    analyses_rows = judged
    judged = _once(judged)
    for row in judged:
        by_rule[row.get('rule')] = by_rule.get(row.get('rule'), 0) + 1
    analyses = sum(int(row['analyses']) for row in analyses_rows if isinstance(row.get('analyses'), (int, float)) and not isinstance(row.get('analyses'), bool))
    false = sum(1 for row in kept if meaning_guard(str(row.get('heard') or ''), str(row.get('asked') or '')) == DIFFERS)
    wrong = sum(1 for event in events if event.get('label') == 'refusal' and event.get('verdict') == 'wrong')
    return {'resolutions': len(judged), 'analyses': analyses, 'fast_keep': len(kept), 'false_keeps': false, 'wrong_refusals': wrong, 'by_rule': by_rule}


def report(rows):
    """The counts of a journal's rows (``harvest.read``)."""
    return _count([r for r in rows if r['ev'] == 'judge'], [r for r in rows if r['ev'] == 'fast_keep'], harvest.events(rows))


def report_fixture(fixture):
    """The counts of a harvested fixture; it holds the U06 events, and the judge and keep records when it was harvested with them (``judge``, ``keeps``)."""
    return _count(list(fixture.get('judge') or []), list(fixture.get('keeps') or []), fixture.get('events') or [])


def main(argv=None):
    for target in (argv if argv is not None else sys.argv[1:]):
        path = Path(target)
        got = report_fixture(json.loads(path.read_text(encoding='utf-8'))) if path.suffix == '.json' else report(harvest.read(path))
        print(f"{path.name}: resolutions={got['resolutions']} analyses={got['analyses']} fast_keep={got['fast_keep']} false_keeps={got['false_keeps']} "
              f"wrong_refusals={got['wrong_refusals']} by_rule={got['by_rule']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
