"""U21-S9: does a semantic leg (rubert-tiny2 ONNX, CLS pooling, L2) add right bank hits the lexical ranked path misses, without one false accept? OFFLINE probe, no engine change.
Run in a SEPARATE venv (onnxruntime, tokenizers, numpy); the model is a local folder (model.onnx + tokenizer.json), nothing is downloaded here:
  python -m tools.bank_semantic_probe --model-dir <dir> --bank-dir <dir> [--lexical lex.json]   (without --lexical the engine is imported for the baseline)
  python -m tools.bank_semantic_probe --dump-lexical lex.json --bank-dir <dir>                  (in the ENGINE venv: ``Ranker.best`` outcome per question)
Thresholds (cosine T, margin M to the best rival with another answer) are tuned on the dev half only (no wrong first, then most rescued) and scored on the test half.
Prints a passport and ``verdict PASS|FAIL|NOT_MEASURED``. Unmeasured is not passed: no model or runtime -> NOT_MEASURED."""
import argparse, hashlib, json, platform, re, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GATE_MIN_RESCUE = 2          # right hits on test questions where the lexical path gave none
GATE_P95_MS = 30.0           # one question, batch 1, threads=1; the N95 is unmeasured, so a PASS here is a laptop PASS only
GRID_T = (0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)
GRID_M = (0.0, 0.02, 0.05, 0.08, 0.1, 0.15)
BANK_DEFAULT = ROOT / 'cloud_context' / 'bank'


def _atoms(text):
    """What two texts of one question must agree on, by count: the digit groups and the «не»/«ни» words."""
    words = re.sub(r'[^\w\s-]', ' ', str(text).lower().replace('ё', 'е')).split()
    return sorted(re.findall(r'\d+', ' '.join(words))), sum(w in ('не', 'ни') for w in words)


def veto_ok(question, form):
    return _atoms(question) == _atoms(form)


def forms_of(rows):
    """-> (texts, owner): every question form of the bank (q and alt) and the index of its entry."""
    texts, owner = [], []
    for k, r in enumerate(rows):
        for f in [r['q'], *(r.get('alt') or ())]:
            texts.append(f)
            owner.append(k)
    return texts, owner


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _rank_one(qv, fvecs, owner, rows, texts):
    """-> (entry, score, margin, form text) of the best entry; the margin is to the best entry with ANOTHER answer; None without forms."""
    best = {}
    for fv, k, tx in zip(fvecs, owner, texts):
        s = _dot(qv, fv)
        if k not in best or s > best[k][0]:
            best[k] = (s, tx)
    if not best:
        return None
    e = max(best, key=lambda k: best[k][0])
    rival = max((s for k, (s, _) in best.items() if rows[k]['answer'] != rows[e]['answer']), default=0.0)
    return e, best[e][0], best[e][0] - rival, best[e][1]


def _in_half(i, half):
    return not (half == 'dev' and i % 2 or half == 'test' and not i % 2)


def evaluate(encode, rows, tests, gold, forms, owner, *, half, lexical, t, m, _cache=None):
    """Score the semantic leg on one half. ``lexical``: question index -> entry index or None (the ranked path alone). rescued = right here, none there."""
    from tools import bank_eval
    fvecs = _cache['forms'] if _cache else encode(forms)
    out = {'right': 0, 'wrong': 0, 'none': 0, 'neg_hit': 0, 'n_gold': 0, 'n_neg': 0, 'rescued': 0, 'lost': 0, 'wrongs': []}
    for i, tq in enumerate(tests):
        if not _in_half(i, half):
            continue
        g = gold[i]
        qv = _cache['q'][i] if _cache else encode([tq['q']])[0]
        got = _rank_one(qv, fvecs, owner, rows, forms)
        e = got[0] if got and got[1] >= t and got[2] >= m and veto_ok(tq['q'], got[3]) else None
        v = bank_eval.judge(rows, g, e)
        lex = lexical.get(i)
        if g.get('gold'):
            out['n_gold'] += 1
            out[v] += 1
            out['rescued'] += v == 'right' and lex is None
            out['lost'] += v != 'right' and lex is not None and bank_eval.judge(rows, g, lex) == 'right'
        else:
            out['n_neg'] += 1
            out['neg_hit'] += v != 'none'
            out['wrong'] += v != 'none'
        if v == 'wrong':
            out['wrongs'].append((i, tq['q'], rows[e]['q'], round(got[1], 3)))
    return out


def tune(encode, rows, tests, gold, forms, owner, *, lexical):
    """The grid on dev only: no wrong (nor on no-answer questions) first, then the most rescued, then right, then the higher T and M. -> (t, m, dev result)"""
    cache = {'forms': encode(forms), 'q': {i: encode([tq['q']])[0] for i, tq in enumerate(tests) if _in_half(i, 'dev')}}
    best = None
    for t in GRID_T:
        for m in GRID_M:
            r = evaluate(encode, rows, tests, gold, forms, owner, half='dev', lexical=lexical, t=t, m=m, _cache=cache)
            key = (-r['wrong'], r['rescued'], r['right'], t, m)
            if best is None or key > best[0]:
                best = (key, t, m, r)
    return best[1], best[2], best[3]


def verdict(test_result, *, p95_ms):
    """-> (PASS | FAIL | NOT_MEASURED, reasons). The gate is quantities: 0 wrong (0 on no-answer), rescued >= GATE_MIN_RESCUE, p95 <= GATE_P95_MS."""
    if test_result is None or p95_ms is None:
        return 'NOT_MEASURED', ['model_missing']
    why = []
    if test_result['wrong'] or test_result['neg_hit']:
        why.append(f"wrong {test_result['wrong']} (no-answer {test_result['neg_hit']}) > 0")
    if test_result['rescued'] < GATE_MIN_RESCUE:
        why.append(f"rescued {test_result['rescued']} < {GATE_MIN_RESCUE}")
    if p95_ms > GATE_P95_MS:
        why.append(f'p95 {p95_ms:.1f} ms > {GATE_P95_MS} ms')
    return ('FAIL', why) if why else ('PASS', [])


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OnnxEncoder:
    """rubert-tiny2 as exported to ONNX: tokenizers + onnxruntime, CLS pooling, L2. ``__call__(texts)`` -> list of vectors."""

    def __init__(self, model_dir, threads=1):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np, self.dir = np, Path(model_dir)
        self.model_path = self.dir / 'model.onnx'
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = opts.inter_op_num_threads = threads
        self.sess = ort.InferenceSession(str(self.model_path), opts, providers=['CPUExecutionProvider'])
        self.tok = Tokenizer.from_file(str(self.dir / 'tokenizer.json'))
        self.tok.enable_truncation(max_length=64)
        self.tok.enable_padding()
        self.names = {i.name for i in self.sess.get_inputs()}
        self.ort_version = ort.__version__

    def __call__(self, texts):
        np, out = self.np, []
        for lo in range(0, len(texts), 32):
            enc = self.tok.encode_batch(list(texts[lo:lo + 32]))
            feed = {'input_ids': np.array([e.ids for e in enc], dtype=np.int64), 'attention_mask': np.array([e.attention_mask for e in enc], dtype=np.int64)}
            if 'token_type_ids' in self.names:
                feed['token_type_ids'] = np.zeros_like(feed['input_ids'])
            cls = self.sess.run(None, feed)[0][:, 0, :]
            out.extend((cls / np.maximum(np.linalg.norm(cls, axis=1, keepdims=True), 1e-12)).tolist())
        return out


def lexical_outcomes(rows, tests):
    """In the engine venv: the entry index of ``Ranker.best`` per question (None = no hit)."""
    from echo_sync import instant
    ranker = instant.Ranker(rows)
    return {i: (lambda g: g[0] if g else None)(ranker.best(t['q'])) for i, t in enumerate(tests)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bank-dir', default=str(BANK_DEFAULT))
    ap.add_argument('--bank', default='instant_bank_2.json')
    ap.add_argument('--model-dir', default='', help='a folder with model.onnx and tokenizer.json (rubert-tiny2, exported once, offline)')
    ap.add_argument('--lexical', default='', help='JSON {question index: entry index | null} from --dump-lexical; else the engine is imported')
    ap.add_argument('--dump-lexical', default='', help='write the lexical baseline to this file and stop (engine venv)')
    ap.add_argument('--threads', type=int, default=1)
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()
    from tools import bank_eval
    rows, tests, gold = bank_eval.load(a.bank_dir, a.bank)
    if a.dump_lexical:
        Path(a.dump_lexical).write_text(json.dumps(lexical_outcomes(rows, tests)), encoding='utf-8')
        return
    lexical = {int(k): v for k, v in json.load(open(a.lexical, encoding='utf-8')).items()} if a.lexical else lexical_outcomes(rows, tests)
    passport = {'probe_sha256': _sha(__file__), 'bank': a.bank, 'bank_sha256': _sha(bank_eval.find(a.bank_dir, a.bank)),
                'tests_sha256': _sha(bank_eval.find(a.bank_dir, '16_BANK_TEST.json')), 'gold_sha256': _sha(bank_eval.find(a.bank_dir, 'gold.json')),
                'lexical_sha256': _sha(a.lexical) if a.lexical else 'engine', 'cpu': platform.processor() or platform.machine(), 'threads': a.threads,
                'n_test': sum(_in_half(i, 'test') for i in range(len(tests))), 'of': len(tests), 'n95': 'unmeasured', 'engine_change': False}
    enc, why = None, ''
    try:
        if not (Path(a.model_dir) / 'model.onnx').is_file() or not (Path(a.model_dir) / 'tokenizer.json').is_file():
            why = 'model_missing'
        else:
            enc = OnnxEncoder(a.model_dir, a.threads)
            passport.update(model_sha256=_sha(enc.model_path), onnxruntime=enc.ort_version)
    except ImportError as exc:
        why = f'runtime_missing:{exc.name}'
    if enc is None:
        print('passport', json.dumps(passport, ensure_ascii=False))
        print(f'verdict NOT_MEASURED | {why}')
        return
    forms, owner = forms_of(rows)
    t, m, dev = tune(enc, rows, tests, gold, forms, owner, lexical=lexical)
    ms = []
    for tq in tests[:60]:
        a0 = time.perf_counter()
        enc([tq['q']])
        ms.append((time.perf_counter() - a0) * 1000)
    ms.sort()
    p95 = ms[min(len(ms) - 1, int(len(ms) * 0.95))]
    res = evaluate(enc, rows, tests, gold, forms, owner, half='test', lexical=lexical, t=t, m=m)
    v, reasons = verdict(res, p95_ms=p95)
    passport.update(forms=len(forms), encode_ms_median=round(statistics.median(ms), 2), encode_ms_p95=round(p95, 2), t=t, m=m)
    print('passport', json.dumps(passport, ensure_ascii=False))
    print(f"dev  (tuned): right {dev['right']}/{dev['n_gold']} wrong {dev['wrong']} rescued {dev['rescued']} | T {t} M {m}")
    print(f"test (scored): right {res['right']}/{res['n_gold']} wrong {res['wrong']} (no-answer {res['neg_hit']} of {res['n_neg']}) rescued {res['rescued']} lost {res['lost']}")
    if a.show:
        for w in res['wrongs']:
            print('   WRONG', w)
    print('verdict ' + v + (' | ' + '; '.join(reasons) if reasons else ''))


if __name__ == '__main__':
    main()
