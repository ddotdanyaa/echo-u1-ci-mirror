"""Build the bank of the instant path (W5): ``python tools/build_instant_bank.py --out D:/echo/bank.json --bank mine.json --pairs pairs.txt --material context.md``.

``--bank`` a JSON list of rows ``{q, alt, core, answer, source, subject, trust}`` (repeat); ``--pairs`` a pairs file of ``prepared_answers`` (JSON ``{q,a}`` or
``В:``/``О:`` blocks, trust «Д»); ``--material`` the material with ``В:``/``О:`` pairs in it (trust «М»). Rows are checked (``instant.clean_entry``), a question that
two rows answer differently is dropped with both, and the result is written for ``instant_bank_file``. ``--pcm-dir DIR --home HOME`` (on the laptop: SAPI is there)
speaks the first portion of every answer into the PCM cache (``pcm_cache.prerender``). Prints one JSON line: counts and the ear's terms (``ear_vocab``). The bank
lives outside the repository; nothing of it is printed but counts.

E96 (1), the holdout: ``--holdout FILE`` (repeat; a JSON list of questions or of rows ``{q, alt}``, or one question per line) names the questions of the measurement. A bank row
whose question or alternative is one of them is DROPPED (a bank made of the measurement's questions is «наизусть», the measurement would be circular) and counted as
``dropped_holdout``; ``holdout_sha256`` is the hash of the list and ``bank_sha256`` the hash of the finished bank's questions and answers, so that both can be frozen before the run
and compared after it. Only counts and hashes are printed."""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from echo_sync import instant, pcm_cache  # noqa: E402
from echo_sync.prepared_answers import parse_pairs  # noqa: E402


def _norm(text):
    return ' '.join(re.findall(r'\w+', str(text or '').casefold().replace('ё', 'е')))


def load_holdout(paths):
    """The measurement's questions of the holdout files, normalized (``_norm``). A file that does not read is an error, never an empty holdout."""
    found = set()
    for path in paths:
        text = Path(path).read_text(encoding='utf-8')
        try:
            data = json.loads(text)
        except ValueError:
            data = [line for line in text.splitlines() if line.strip()]
        for item in data if isinstance(data, list) else ():
            for q in ([item] if isinstance(item, str) else [item.get('q', ''), *(item.get('alt') or ())] if isinstance(item, dict) else ()):
                if _norm(q):
                    found.add(_norm(q))
    return found


def _sha(parts):
    digest = hashlib.sha256()
    for part in sorted(parts):
        digest.update(part.encode('utf-8') + b'\n')
    return digest.hexdigest()


def build(banks=(), pairs=(), materials=(), holdout=()):
    rows, dropped = [], 0
    for path in banks:
        got = instant.load_bank(path)
        rows += got
    for path in pairs:
        for q, a in parse_pairs(Path(path).read_text(encoding='utf-8')):
            row = instant.clean_entry({'q': q, 'answer': a, 'source': Path(path).name}, 'Д')
            rows.append(row) if row else None
    for path in materials:
        rows += instant.material_entries(Path(path).read_text(encoding='utf-8'))
    barred = load_holdout(holdout) if holdout else set()
    held = [row for row in rows if barred.intersection(_norm(q) for q in (row['q'], *(row.get('alt') or ())))]
    gone = {id(row) for row in held}
    rows = [row for row in rows if id(row) not in gone]
    seen = {}
    for row in rows:
        seen.setdefault(' '.join(row['q'].casefold().split()), set()).add(row['answer'])
    out, kept = [], set()
    for row in rows:
        key = ' '.join(row['q'].casefold().split())
        if len(seen[key]) > 1:
            dropped += 1
            continue
        if key in kept:
            continue
        kept.add(key)
        out.append(row)
    for n, row in enumerate(out):
        row['id'] = row['id'] or 'b%05d' % n
    probe = instant.Instant(out, adapters=())
    clashes = sum(1 for row in out if probe.lookup(row['q'], bank_only=True) is None)
    return out, {'rows': len(out), 'dropped_conflicts': dropped, 'dropped_holdout': len(held), 'not_self_found': clashes,
                 'bank_sha256': _sha(_norm(row['q']) + '	' + row['answer'] for row in out), 'holdout_sha256': _sha(barred) if barred else ''}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True)
    ap.add_argument('--bank', action='append', default=[])
    ap.add_argument('--pairs', action='append', default=[])
    ap.add_argument('--material', action='append', default=[])
    ap.add_argument('--holdout', action='append', default=[])
    ap.add_argument('--pcm-dir')
    ap.add_argument('--home')
    ap.add_argument('--pcm-mb', type=int, default=200)
    args = ap.parse_args(argv)
    rows, counts = build(args.bank, args.pairs, args.material, args.holdout)
    tmp = Path(args.out + '.tmp')
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, args.out)
    from echo_sync.ear_sherpa import material_terms      # noqa: PLC0415 - the ear's bias words of the bank's questions (one rule: ear_sherpa.material_terms)
    counts['vocab_terms'] = len(material_terms([t for row in rows if isinstance(row, dict) for t in (str(row.get('q', '')), *map(str, row.get('alt') or ()))], limit=60))
    if args.pcm_dir:
        if not args.home:
            ap.error('--pcm-dir needs --home (the profile whose SAPI voice speaks)')
        from echo_sync.controlled_host import profile_sapi_worker, render_cue_pcm, voice_key      # noqa: PLC0415 - the laptop only
        worker = profile_sapi_worker(Path(args.home))
        cache = pcm_cache.PcmCache(args.pcm_dir, max_bytes=args.pcm_mb * 2 ** 20)
        counts['pcm'] = pcm_cache.prerender(cache, lambda text: render_cue_pcm(worker, text, Path(args.home) / 'echo-sync'), rows,
                                            voice_key(getattr(worker, 'voice', None), None, False), 24000)
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
