"""The ear's errors, learned from ``cloud_context/analysis/14_EAR_N2_raw.jsonl`` (sherpa on the laptop, N2 set, 536 runs, clean only).

The file has the reference text and the ear's pieces of every run. ``learn`` aligns them word by word (difflib) and keeps: the rates of a substituted, a lost and an
added word per reference word, the substitutions seen (``ну``→``но``, ``последнее``→``последние``) and the pauses between the ear's pieces. ``Ear.hear`` applies them.
Noise: the file has no ``snr10``/``snr5`` rows (the meta line names them, the runs are all ``clean``), so the noisy ear is the clean one with the rates multiplied
(``NOISE``): an assumption of this stand, not a measurement.
"""
import difflib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'cloud_context' / 'analysis' / '14_EAR_N2_raw.jsonl'
LEARNED = Path(__file__).with_name('ear_n2.json')
NOISE = {'clean': 1.0, 'snr10': 2.0, 'snr5': 3.5}        # times the clean rates (assumed, see above)
VOWELS = 'аеиоуыэюя'


def words(text):
    return re.findall(r'[\w-]+', text.lower().replace('ё', 'е'))


def learn(source=SOURCE):
    rows = [json.loads(line) for line in Path(source).read_text(encoding='utf-8').splitlines() if line.strip()]
    runs = [r for r in rows if r.get('type') == 'run']
    n = s = d = i = 0
    subs, gaps, conds = defaultdict(Counter), Counter(), Counter(r['cond'] for r in runs)
    for r in runs:
        ref, hyp = words(r['ref']), words(' '.join(u['text'] for u in r['utts']))
        n += len(ref)
        for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_opcodes():
            if op == 'replace':
                k = min(a2 - a1, b2 - b1)
                s, d, i = s + k, d + max(0, a2 - a1 - k), i + max(0, b2 - b1 - k)
                for x, y in zip(ref[a1:a2], hyp[b1:b2]):
                    subs[x][y] += 1
            elif op == 'delete':
                d += a2 - a1
            elif op == 'insert':
                i += b2 - b1
        for a, b in zip(r['utts'], r['utts'][1:]):
            gaps[round(b['on_s'] - a['off_s'], 1)] += 1
    return {'source': str(Path(source).relative_to(ROOT)) if Path(source).is_relative_to(ROOT) else str(source), 'runs': len(runs), 'conds': dict(conds), 'words': n,
            'sub': round(s / n, 5), 'del': round(d / n, 5), 'ins': round(i / n, 5), 'subs': {x: dict(c) for x, c in sorted(subs.items())},
            'gaps': {str(k): v for k, v in sorted(gaps.items())}}


def load():
    if not LEARNED.exists():
        LEARNED.write_text(json.dumps(learn(), ensure_ascii=False, indent=0, sort_keys=True), encoding='utf-8')
    return json.loads(LEARNED.read_text(encoding='utf-8'))


class Ear:
    """``hear(rng, text, noise)``: the ear's words of ``text`` (lower case, no punctuation), with the N2 errors at the noise level's rate. Numbers and «не» keep
    their place but may be misheard like any word (a number's error is the one that costs most: it is kept, not shielded)."""

    def __init__(self, model=None):
        self.m = model or load()

    def rates(self, noise):
        k = NOISE.get(noise, 1.0)
        return self.m['sub'] * k, self.m['del'] * k, self.m['ins'] * k

    def wrong(self, rng, word):
        seen = self.m['subs'].get(word)
        if seen and rng.random() < 0.8:
            return rng.choices(list(seen), list(seen.values()))[0]
        if word.isdigit():
            return str(int(word) + rng.choice((-10, -1, 1, 10))) if int(word) > 10 else word
        if len(word) > 3 and word[-1] in VOWELS:                                        # the ending: «последнее» → «последние», the most common kind in N2
            return word[:-1] + rng.choice([v for v in 'аеиыя' if v != word[-1]])
        if len(word) > 4:
            return word[1:]                                                             # the head lost: «подождите» → «дождите»
        return rng.choice(('а', 'и', 'но', 'то', 'как'))

    def hear(self, rng, text, noise='clean'):
        sub, lost, added = self.rates(noise)
        out = []
        for word in words(text):
            roll = rng.random()
            if roll < lost:
                continue
            out.append(self.wrong(rng, word) if roll < lost + sub else word)
            if rng.random() < added:
                out.append(rng.choice(('э', 'а', 'ну', 'и')))
        return ' '.join(out)
