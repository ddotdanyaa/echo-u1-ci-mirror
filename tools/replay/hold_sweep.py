"""w9-hold-sweep (E06, E06.1): the window D of the ear's silence before an utterance counts as over, against what it costs: questions missed, false starts, added delay. On the real ``ControlledMedia`` of ``stand``.

    python -m tools.replay.hold_sweep --seeds 0:2000 --jobs 4 [--length 40] [--json out.json] [--md out.md]

D is ``controlled_media.EAR_RELEASE_SILENCE_SECONDS`` (the quiet that ends an utterance; ``EAR_TAIL_SILENCE_SECONDS`` is its bound when the text stops on an open tail). A fixed D sets both to D; ``adaptive`` keeps a short window
and the long tail one (now: 0.9 / 2.5, and 0.5 / 2.5). The stand's listener says each question in one breath, so here every question with 5 words or more is split, with the chance ``SPLIT``, into two pieces with a pause between (the ear's
two utterances, the cloud's two turns): the pause is drawn 0.3-1.8 s, half of them at a word the sentence goes on from (a function word) and half at any word. That pause law is an ASSUMPTION of this stand, not a measurement of a speaker:
the real one comes from the laptop's journal. The profile is the stand's with ``ear_release`` forced on: D governs only that path (the other half of the stand's profiles answer on the cloud's final and D changes nothing there). Everything else is the stand's (``tools/replay/stand.py``); no number here is a latency of a laptop or a phone.

Per split question: FALSE START = an audible cue between the end of the first piece and the end of the second (the answer begun over a question not finished); PREPARED = a job (a preparation, nothing heard) before the second piece began. Per question: MISS = no job within ``WAIT`` s of its last word. DELAY = the last word to the first cue (non-diagnostic).
"""
import argparse
import copy
import json
import random
import statistics
import sys
import time
from multiprocessing import Pool

SPLIT = 0.5
WAIT = 20.0
PAUSE = (0.3, 1.8)
CONFIGS = [('D=0', 0.0, 0.0), ('D=0.3', 0.3, 0.3), ('D=0.5', 0.5, 0.5), ('D=0.7', 0.7, 0.7), ('D=0.9', 0.9, 0.9), ('D=1.2', 1.2, 1.2), ('D=1.5', 1.5, 1.5),
           ('adaptive 0.5/2.5', 0.5, 2.5), ('adaptive 0.9/2.5 (now)', 0.9, 2.5)]
SOURCES = [c for c in CONFIGS]


def _splitter(stand_module):
    """``Stand`` with the pauses inside a question; ``cuts`` keeps (first piece, second piece) of each split."""
    from echo_sync.textutil import FUNCTION_WORDS

    class Hold(stand_module.Stand):
        def __init__(self, seed, **keywords):
            self.cuts, self.pauses = [], random.Random(f'hold-{seed}')
            super().__init__(seed, **keywords)

        def _utter(self, u):
            words, p = u.text.split(), self.pauses
            if u.kind not in ('question',) or len(words) < 5 or p.random() >= SPLIT:
                return super()._utter(u)
            at = [i for i in range(2, len(words) - 1) if words[i - 1].lower().strip('.,?') in FUNCTION_WORDS] if p.random() < 0.5 else []
            k = p.choice(at) if at else p.randrange(2, len(words) - 1)
            first = copy.copy(u)
            first.text, first.meaning = ' '.join(words[:k]), u.meaning
            first.ear = self.heard_by_ear(first.text, 'question')
            u.text, u.n = ' '.join(words[k:]), u.n + 1
            u.ear = self.heard_by_ear(u.text, 'question')
            first.offset = round(u.onset + max(0.35, k * p.uniform(0.25, 0.42)), 2)
            u.onset = round(first.offset + p.uniform(*PAUSE), 2)
            u.offset = round(u.onset + max(0.35, len(words[k:]) * p.uniform(0.25, 0.42)), 2)
            self.said.insert(len(self.said) - 1, first)
            self.free = u.offset + 0.15
            for piece in (first, u):
                for said in (piece.text, piece.ear):
                    self.mind.learn(said, u.meaning)
            self.cuts.append((first, u))
            super()._utter(first)
            super()._utter(u)

    return Hold


def _window(release, tail):
    """P01: the window is read by the methods of the family modules (``cm_kind``, ``cm_portion``) from their own globals: it is set where each of them binds it."""
    import importlib
    import pkgutil
    import echo_sync
    for info in [None, *pkgutil.iter_modules(echo_sync.__path__)]:
        if info is not None and not info.name.startswith('cm_'):
            continue
        module = importlib.import_module('echo_sync.controlled_media' if info is None else 'echo_sync.' + info.name)
        for name, value in (('EAR_RELEASE_SILENCE_SECONDS', release), ('EAR_TAIL_SILENCE_SECONDS', tail)):
            if name in vars(module):
                setattr(module, name, value)


def one(args):
    """One seed under one config: the counts and the delays."""
    seed, name, release, tail, length = args
    import logging
    from echo_sync import controlled_media as cm
    from tools.replay import stand
    # W14 item 3: the window and the log are put back: in a test process they outlived ``one`` (the four ``test_q1_*`` after it on a worker)
    saved = (cm.EAR_RELEASE_SILENCE_SECONDS, cm.EAR_TAIL_SILENCE_SECONDS, logging.root.manager.disable)
    logging.disable(logging.WARNING)
    _window(release, tail)
    try:
        hold = _splitter(stand)(seed, length=length, profile={**stand.profile_of(seed), 'ear_release': 'on'})
        try:
            hold.play()
        except Exception as error:                                   # noqa: BLE001 - a crash of the chain is counted, not hidden
            hold.out.crash = repr(error)
        finally:
            hold.close()
    finally:
        _window(*saved[:2])
        logging.disable(saved[2])
    return measure(hold.out, hold.cuts, length) | {'seed': seed, 'config': name}


def measure(out, cuts, length):
    """The counts of an Outcome: ``cuts`` are the (first, second) pieces of the questions the stand split."""
    jobs = [j['at'] for j in out.jobs]
    cues = sorted(c[0] for c in out.cues if not c[6])
    second = {id(b) for _, b in cuts}
    false = sum(1 for a, b in cuts if any(a.offset < t <= b.offset for t in cues))
    prepared = sum(1 for a, b in cuts if any(a.offset < t <= b.onset for t in jobs))
    asked = [u for u in out.said if u.kind in ('question', 'fix') and u.offset + WAIT < length and (id(u) in second or not any(u is a for a, _ in cuts))]
    missed = sum(1 for u in asked if not any(u.onset < t <= u.offset + WAIT for t in jobs))
    delays = [min((t for t in cues if t > u.offset), default=None) for u in asked]
    delays = [round(t - u.offset, 2) for t, u in zip(delays, asked) if t is not None and t - u.offset < WAIT]
    return {'splits': len(cuts), 'false': false, 'prepared': prepared, 'asked': len(asked), 'missed': missed, 'delays': delays, 'crash': bool(out.crash)}


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else float('nan')


def table(rows):
    by = {}
    for r in rows:
        a = by.setdefault(r['config'], {'splits': 0, 'false': 0, 'prepared': 0, 'asked': 0, 'missed': 0, 'delays': [], 'crash': 0})
        for k in ('splits', 'false', 'prepared', 'asked', 'missed', 'crash'):
            a[k] += r[k]
        a['delays'] += r['delays']
    out = []
    for name, *_ in CONFIGS:
        a = by.get(name)
        if a:
            out.append({'config': name, 'splits': a['splits'], 'false_rate': a['false'] / max(1, a['splits']), 'prepared_rate': a['prepared'] / max(1, a['splits']), 'asked': a['asked'], 'miss_rate': a['missed'] / max(1, a['asked']),
                        'delay_p50': pct(a['delays'], .5), 'delay_p90': pct(a['delays'], .9), 'crashes': a['crash']})
    return out


def markdown(rows, seeds, length):
    lines = [f'{seeds} seeds x {len(CONFIGS)} configs, {length:.0f} s of conversation each (stand a1-fuzz, real ControlledMedia).', '',
             '| окно | разрезанных вопросов | ложный старт (звук до конца вопроса) | подготовка до второй части | вопросов | пропуск | задержка p50, с | p90, с | падений |', '|---|---|---|---|---|---|---|---|---|']
    lines += [f"| {r['config']} | {r['splits']} | {r['false_rate']:.1%} | {r['prepared_rate']:.1%} | {r['asked']} | {r['miss_rate']:.1%} | {r['delay_p50']:.2f} | {r['delay_p90']:.2f} | {r['crashes']} |" for r in rows]
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--seeds', default='0:200')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--length', type=float, default=40.0)
    p.add_argument('--json')
    p.add_argument('--md')
    a = p.parse_args(argv)
    lo, hi = (int(x) for x in a.seeds.split(':'))
    tasks = [(s, n, r, t, a.length) for s in range(lo, hi) for n, r, t in CONFIGS]
    began = time.time()
    with Pool(a.jobs) as pool:
        rows = pool.map(one, tasks, chunksize=8)
    summary = table(rows)
    text = markdown(summary, hi - lo, a.length)
    print(text, f'\n({time.time() - began:.0f} s)')
    if a.json:
        json.dump({'summary': summary, 'rows': rows}, open(a.json, 'w'), ensure_ascii=False)
    if a.md:
        open(a.md, 'w', encoding='utf-8').write(text + '\n')


if __name__ == '__main__':
    sys.exit(main())
