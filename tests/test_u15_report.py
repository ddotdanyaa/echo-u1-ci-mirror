"""U15-S2: ``tools.replay.u15_report`` counts what the judge did in one journal (or fixture). Synthetic rows; the real call 120135 is read only where its fixture is."""
from pathlib import Path

import pytest

from tools import harvest as H
from tools.replay import u15_report as R

FIXTURE = Path(H.OUT_DEFAULT) / '20261108-120135-6dc9eed08e9b.json'


def rows(*items):
    return H.read_rows([{'t': 0, 'ev': 'call_open'}] + [{'t': t, 'ev': ev, **fields} for t, ev, fields in items])


def test_counts_resolutions_analyses_keeps_and_false_keeps():
    got = R.report(rows(
        (1000, 'judge', {'tid': 'u1', 'rule': 'question', 'chain': 'question', 'analyses': 2}),
        (2000, 'judge', {'tid': 'u2', 'rule': 'recall', 'chain': 'recall', 'analyses': 0}),
        (2500, 'fast_keep', {'job': 1, 'heard': 'сколько будет сорок два', 'asked': 'сколько будет сорок два'}),
        (2600, 'fast_keep', {'job': 2, 'heard': 'статья семнадцать', 'asked': 'статья восемнадцать'}),
    ))
    assert got['resolutions'] == 2 and got['analyses'] == 2 and got['fast_keep'] == 2 and got['false_keeps'] == 1
    assert got['by_rule'] == {'question': 1, 'recall': 1} and got['wrong_refusals'] == 0


def test_a_tid_judged_twice_is_one_resolution_and_the_last_rule_stands():
    got = R.report(rows(
        (1000, 'judge', {'tid': 'u1', 'rule': 'question', 'chain': 'question', 'analyses': 1}),
        (1100, 'judge', {'tid': 'u1', 'rule': 'recall', 'chain': 'recall', 'analyses': 1}),
        (2000, 'judge', {'tid': 'u2', 'rule': 'question', 'chain': 'question', 'analyses': 1}),
    ))
    assert got['resolutions'] == 2 and got['analyses'] == 3 and got['by_rule'] == {'recall': 1, 'question': 1}


def test_u06_wrong_refusals_are_counted_from_the_events():
    ask = 'объясни что такое счёт пятьдесят один подробнее'
    got = R.report(rows((1000, 'ear_final', {'text': ask, 'kind': 'question', 'speech_ms': 900, 'lag_ms': 100}),
                        (1100, 'fast_job', {'job': 1, 'outcome': 'ok'}),
                        (1200, 'fast_refused', {'job': 1, 'rule': 'words', 'on': 'ear', 'heard': ask, 'asked': ask, 'ms': 10}),
                        (3000, 'decision', {'kind': 'question', 'reason': 'x', 'revision': 1})))
    assert got['wrong_refusals'] == 1 and got['resolutions'] == 0


def test_a_fixture_is_read_too():
    got = R.report_fixture({'events': [{'t': 1.0, 'label': 'refusal', 'verdict': 'wrong'}, {'t': 2.0, 'label': 'refusal', 'verdict': 'unanswered'}]})
    assert got['wrong_refusals'] == 1 and got['resolutions'] == 0


@pytest.mark.skipif(not FIXTURE.exists(), reason='the fixture of 120135 is not on this laptop')
def test_the_report_runs_on_120135(capsys):
    assert R.main([str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    for word in ('resolutions', 'analyses', 'fast_keep', 'false_keeps', 'wrong_refusals'):
        assert word in out
