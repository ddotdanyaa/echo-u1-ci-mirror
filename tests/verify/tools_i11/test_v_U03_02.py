"""V U03-02: the per-call report shows latency in SECONDS, the same scale the owner sees (the all-calls table has ``_sec``;
the report of one call has only ``*_ms``).
Acceptance: the summary of one call report carries the median in seconds and every episode its pcm in seconds, equal to
the ms values / 1000.  The test drives the real ``call_report.build``; the latency chain (``latency_chain.py``, which
lives on the owner's laptop and is in neither a checkout nor the cloud) is a minimal stand-in that hands build() two
episodes, so the test checks only what build() itself writes."""
from statistics import median

from tools import call_report


class _Chain:
    """The three answers build() asks the latency chain for, nothing else."""

    @staticmethod
    def parse_call(rows, name):
        return {'elapsed': 20000}

    @staticmethod
    def phone_episodes(call):
        return [{'class': 'модель', 'path': None, 'pcm_ms': 2020.4, 'cue_status': 'completed',
                 'segments': [(('question', 'ear_first'), 400), (('question', 'admitted_answer'), 1620)], 'marks': {}},
                {'class': 'модель', 'path': None, 'pcm_ms': 3500, 'cue_status': 'completed',
                 'segments': [(('question', 'ear_first'), 1500), (('question', 'admitted_answer'), 2000)], 'marks': {}}]

    @staticmethod
    def med(values):
        return median(values) if values else None

    @staticmethod
    def pct(values, q):
        return sorted(values)[int(q * (len(values) - 1))] if values else None


def test_call_report_summary_has_latency_in_seconds():
    rep = call_report.build([], 'call', _Chain())
    summary = rep['summary']
    assert summary['median_ms'] == 2760, summary                      # the base: the ms number is there
    assert 'median_s' in summary, 'the report of one call has no latency in seconds: %s' % sorted(summary)
    assert abs(summary['median_s'] - summary['median_ms'] / 1000) < 0.01
    assert all('pcm_s' in ep and abs(ep['pcm_s'] - ep['pcm_ms'] / 1000) < 0.01 for ep in rep['episodes']), rep['episodes']
