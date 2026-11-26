"""C24-d: candidate retrievers over the bank, compared on the same questions (python -m tools.c24_retrievers): the ranker's soft score as it is (baseline), BM25 on
lemmas, BM25 on character n-grams, their fusion. Retrieval only (recall@k), the verdict (threshold, gap, hard rules) is a separate step."""
import math, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echo_sync import instant  # noqa: E402
from tools import c24_lab as L  # noqa: E402


def norm(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', text.lower().replace('ё', 'е'))).strip()


def lemmas(text):
    """content lemmas (ranker's own normalizer: pymorphy3 lemma, stop words and talk dropped) + numbers"""
    w, n, _ = instant._terms(text)
    return w + n


def grams(text, lo=3, hi=5):
    out = []
    for w in norm(text).split():
        if len(w) < 3:
            continue
        s = f' {w} '
        for k in range(lo, hi + 1):
            out += [s[i:i + k] for i in range(max(len(s) - k + 1, 1))]
    return out


class Bm25:
    def __init__(self, docs, k1=1.2, b=0.75):
        self.k1, self.b = k1, b
        self.tf = [{} for _ in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(docs), 1)
        df, self.post = {}, {}
        for n, d in enumerate(docs):
            for t in d:
                self.tf[n][t] = self.tf[n].get(t, 0) + 1
            for t in self.tf[n]:
                df[t] = df.get(t, 0) + 1
                self.post.setdefault(t, []).append(n)
        N = len(docs)
        self.idf = {t: math.log(1 + (N - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, query):
        s = {}
        for t in set(query):
            for n in self.post.get(t, ()):
                f = self.tf[n][t]
                s[n] = s.get(n, 0.0) + self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[n] / self.avg))
        return s


def build(rows, answer_w=1):
    qdoc = [[t for x in [r['q']] + list(r['alt']) for t in lemmas(x)] for r in rows]
    adoc = [lemmas(r['answer']) for r in rows]
    gdoc = [grams(' '.join([r['q']] + list(r['alt']))) for r in rows]
    return {'lem': Bm25([q + a * answer_w for q, a in zip(qdoc, adoc)]), 'lem_q': Bm25(qdoc), 'gram': Bm25(gdoc)}


def topk(scores, k):
    return sorted(scores, key=scores.get, reverse=True)[:k]


def fuse(*lists, k=60):
    f = {}
    for l in lists:
        for r, n in enumerate(l):
            f[n] = f.get(n, 0.0) + 1 / (k + r)
    return f


def gated(rows, idx, kind):
    """BM25 alone as the verdict: top-1 normalised by the query's own weight, and the margin to the best entry with another answer. -> system(text)."""
    bm = idx[kind]

    def top(text):
        part = instant.question_parts(text)[0]
        q = lemmas(part) if kind != 'gram' else grams(part)
        sc = bm.score(q)
        if not sc:
            return None, 0.0, 0.0
        ranked = sorted(sc, key=sc.get, reverse=True)
        full = sum(bm.idf[t] for t in set(q) if t in bm.idf) or 1.0
        t1 = sc[ranked[0]]
        other = next((sc[k] for k in ranked[1:] if rows[k]['answer'] != rows[ranked[0]]['answer']), 0.0)
        return ranked[0], t1 / (full * (bm.k1 + 1) / (1 + bm.k1)) , (t1 - other) / t1
    return top


def gate_study(rows, idx, out):
    """The best threshold pair of BM25-only gating on dev with the least false answers, then the same pair on the held-out sets (history round 3, W11 odd i)."""
    import itertools
    dev = [(L.load(gold=g)[1], sp) for g, sp in (('holdout/gold_c24.json', 'dev'), ('holdout/gold_c24_w11.json', 'dev'))]
    tst = [(L.load(gold=g)[1], sp) for g, sp in (('holdout/gold_c24.json', 'holdout'), ('holdout/gold_c24_w11.json', 'test'))]
    ix = {r['id']: r for r in rows}
    for kind in ('lem', 'gram'):
        top = gated(rows, idx, kind)
        cache = {}

        def evaluate(sets, t, m):
            right = false = 0
            for gold, sp in sets:
                for g in gold:
                    if g['split'] != sp:
                        continue
                    if g['q'] not in cache:
                        cache[g['q']] = top(g['q'])
                    k, sc, mg = cache[g['q']]
                    if k is None or sc < t or mg < m:
                        continue
                    ok = {ix[i]['answer'] for i in g['gold']}
                    if g['gold'] and rows[k]['answer'] in ok:
                        right += 1
                    else:
                        false += 1
            return right, false
        grid = [(t, m) for t, m in itertools.product((0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9), (0.0, 0.1, 0.2, 0.3, 0.5))]
        best = min(grid, key=lambda tm: (evaluate(dev, *tm)[1], -evaluate(dev, *tm)[0]))
        out.append(f'BM25 {kind} alone as the verdict: best on dev (least false answers, then most right) t={best[0]} m={best[1]}: dev right/false {evaluate(dev, *best)}, held-out right/false {evaluate(tst, *best)}')


def main():
    rows, gold = L.load()
    idx = build(rows)
    out = []
    R = instant.Ranker(rows)
    ix = {r['id']: k for k, r in enumerate(rows)}
    ans = {}
    for k, r in enumerate(rows):
        ans.setdefault(r['answer'], set()).add(k)
    gate_study(rows, idx, out)
    res = {n: [0, 0, 0, 0] for n in ('ranker_soft', 'bm25_lemma+answer', 'bm25_lemma_q', 'bm25_ngram', 'fuse(lem,ngram)')}
    import json
    pos = [g for g in gold if g['gold']] + [g for g in json.load(open(L.BANK / 'holdout/gold_c24_w11.json', encoding='utf-8')) if g['gold']]
    for g in pos:
        q = g['q']
        want = set().union(*(ans[rows[ix[i]]['answer']] for i in g['gold']))
        part = instant.question_parts(q)[0]
        ranked, _ = R.rank(q)
        lists = {'ranker_soft': [e for _, e, s in sorted(ranked, key=lambda x: -x[2])],
                 'bm25_lemma+answer': topk(idx['lem'].score(lemmas(part)), 20), 'bm25_lemma_q': topk(idx['lem_q'].score(lemmas(part)), 20),
                 'bm25_ngram': topk(idx['gram'].score(grams(part)), 20)}
        lists['fuse(lem,ngram)'] = topk(fuse(lists['bm25_lemma+answer'], lists['bm25_ngram']), 20)
        for n, l in lists.items():
            for j, k in enumerate((1, 3, 5, 10)):
                res[n][j] += any(e in want for e in l[:k])
    print(f'recall@k over {len(pos)} questions with a gold entry')
    print('retriever | @1 @3 @5 @10')
    for n, v in res.items():
        print(f'{n:20s} |', *(f'{x:3d}' for x in v))
    print(*out, sep='\n')


if __name__ == '__main__':
    main()
