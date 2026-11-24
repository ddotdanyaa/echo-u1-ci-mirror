"""G32: the time to the first cue of the model, step by step, on the stand (``stand.Stand``: the real chain, the boundaries scripted).

One clean question in silence, no faults. The cloud's final comes ``cloud`` s after the end of speech, the model's first text ``job`` s after its job began: both fixed, so what
is left is what the code waits by itself. The steps, from the end of the speech (the stand's clock, not a laptop's nor a phone's):
  ear     the ear's text of the utterance            final   the cloud's final
  job     the job whose text became the first cue    text    its first text (job + the model's latency)
  cue     the first cue on the wire
The waits: ``job_wait`` the job began this long after the system had the words (the ear's text or the final, the earlier); ``after_text`` the cue came this long after the model's
text. ``python -m tools.replay.first_clock [N]`` prints the table for N seeds on the candidate's profile.
"""
import json
import random
import statistics
import sys
from pathlib import Path

from tools.replay import stand as A

ROOT = Path(__file__).resolve().parents[2]
# The profile of the stand when ``cloud_context/reports/candidate_flags.json`` is not there (it is a file of the owner's laptop, not of the repository: a checkout and the cloud suite have none, and the stand's
# tests then ran on four keys and measured another way to the first cue). The keys of that file (wave 13) that the way to the first cue depends on: the ear's text and the two witnesses open the answer before the
# cloud's final (ear_release, two_witnesses), the model's job starts on the ear's text with the material of the question (prepare_wide).
STAND_PROFILE = {'fast_text': 'on', 'local_ear': 'act', 'ear_release': 'on', 'prepare_wide': 'on'}
SKIP = ('instant_bank_file', 'pcm_cache_dir', 'pcm_cache_mb', 'call_trace')


PASSPORT = ('PASSPORT (07_METRICS_PROVENANCE section 6): set = stand seeds (synthetic questions, not recorded calls); checker = this file; profile = candidate() above; load = not recorded; '
            'layer = the stand clock, from the end of the scripted speech (not a server of a call, not a phone: E52). The table of REAL calls: python tools/call_report.py --table')


def candidate():
    """The candidate's profile for the laptop (``cloud_context/reports/candidate_flags.json``) without its files."""
    path = ROOT / 'cloud_context' / 'reports' / 'candidate_flags.json'
    profile = json.loads(path.read_text(encoding='utf-8'))['profile'] if path.exists() else {}
    return {k: v for k, v in profile.items() if k not in SKIP} or dict(STAND_PROFILE)


class One(A.Stand):
    """The stand with one listener's question and nothing after it."""

    def __init__(self, seed, question, **keywords):
        self.question = question
        super().__init__(seed, faults=False, **keywords)

    def decide(self):
        if not self.said:
            self.later(self.now() + 0.3, lambda: self.speak('question', None))

    def speak(self, kind, cue, barge=False):
        original = A.ask
        A.ask = lambda rng, last=None: self.question
        try:
            super().speak(kind, cue, barge)
        finally:
            A.ask = original


def scene(seed, *, profile=None, cloud=1.5, job=0.6, question=None, length=20.0):
    """The steps of one question (seconds from the end of its speech) and the waits; ``cue`` None: no cue."""
    q = question or A.ask(random.Random(seed))
    stand = One(seed, q, length=length, cloud=(cloud, cloud), job=(job, job), profile=dict(profile or candidate()))
    try:
        out = stand.play()
    finally:
        stand.close()
    u = out.said[0]
    cues = [c for c in out.cues if not c[6]]
    rel = lambda t: None if t is None else round(t - u.offset, 2)
    row = {'seed': seed, 'question': q.text, 'ear': rel(u.ear_at), 'final': rel(u.final_at), 'cue': rel(cues[0][0]) if cues else None, 'said': cues[0][1] if cues else None,
           'jobs': [rel(j['at']) for j in out.jobs], 'right': bool(cues) and q.fits(cues[0][1]), 'violations': A.check(out)}
    before = [j for j in out.jobs if cues and j['at'] <= cues[0][0]]
    used = before[-1] if before else None
    row['job'] = rel(used['at']) if used else None
    row['text'] = rel(used['at'] + used['first']) if used else None
    had = min(t for t in (row['ear'], row['final']) if t is not None) if (row['ear'] is not None or row['final'] is not None) else None
    row['job_wait'] = round(row['job'] - had, 2) if used and had is not None else None
    row['after_text'] = round(row['cue'] - row['text'], 2) if used and row['cue'] is not None else None
    return row


def table(seeds, **keywords):
    rows = [scene(seed, **keywords) for seed in seeds]
    median = lambda key: statistics.median([r[key] for r in rows if r[key] is not None] or [float('nan')])
    return rows, {key: round(median(key), 2) for key in ('ear', 'final', 'job', 'text', 'cue', 'job_wait', 'after_text')}


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    rows, med = table(range(n))
    for r in rows:
        print(f"{r['seed']:3d} ear {r['ear']} final {r['final']} job {r['job']} text {r['text']} cue {r['cue']} wait {r['job_wait']} after {r['after_text']} "
              f"{'ok' if r['right'] else 'WRONG'} {r['question'][:48]!r}")
    print('median', med)
    print(PASSPORT)
