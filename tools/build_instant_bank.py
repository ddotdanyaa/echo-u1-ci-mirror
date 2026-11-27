"""Build the bank of the instant path (W5): ``python tools/build_instant_bank.py --out D:/echo/bank.json --bank mine.json --pairs pairs.txt --material context.md``.

``--bank`` a JSON list of rows ``{q, alt, core, answer, source, subject, trust}`` (repeat); ``--pairs`` a pairs file of ``prepared_answers`` (JSON ``{q,a}`` or
``В:``/``О:`` blocks, trust «Д»); ``--material`` the material with ``В:``/``О:`` pairs in it (trust «М»). Rows are checked (``instant.clean_entry``), a question that
two rows answer differently is dropped with both, and the result is written for ``instant_bank_file``. ``--pcm-dir DIR --home HOME`` (on the laptop: SAPI is there)
speaks the first portion of every answer into the PCM cache (``pcm_cache.prerender``). Prints one JSON line: counts and the ear's terms (``ear_vocab``). The bank
lives outside the repository; nothing of it is printed but counts."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from echo_sync import instant, pcm_cache  # noqa: E402
from echo_sync.prepared_answers import parse_pairs  # noqa: E402


def build(banks=(), pairs=(), materials=()):
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
    return out, {'rows': len(out), 'dropped_conflicts': dropped, 'not_self_found': clashes}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True)
    ap.add_argument('--bank', action='append', default=[])
    ap.add_argument('--pairs', action='append', default=[])
    ap.add_argument('--material', action='append', default=[])
    ap.add_argument('--pcm-dir')
    ap.add_argument('--home')
    ap.add_argument('--pcm-mb', type=int, default=200)
    ap.add_argument('--number-ranges', action='store_true', help="read a plural century as the profile's number_ranges=on does; its sound is cached under its own key")
    args = ap.parse_args(argv)
    rows, counts = build(args.bank, args.pairs, args.material)
    tmp = Path(args.out + '.tmp')
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, args.out)
    counts['vocab_terms'] = len(instant.vocab_terms(rows))
    if args.pcm_dir:
        if not args.home:
            ap.error('--pcm-dir needs --home (the profile whose SAPI voice speaks)')
        from echo_sync.controlled_host import profile_sapi_worker, render_cue_pcm, voice_key      # noqa: PLC0415 - the laptop only
        worker = profile_sapi_worker(Path(args.home))
        if args.number_ranges:
            from echo_sync import speech_text      # noqa: PLC0415
            speech_text.set_ranges(True)
        cache = pcm_cache.PcmCache(args.pcm_dir, max_bytes=args.pcm_mb * 2 ** 20)
        counts['pcm'] = pcm_cache.prerender(cache, lambda text: render_cue_pcm(worker, text, Path(args.home) / 'echo-sync'), rows,
                                            voice_key(getattr(worker, 'voice', None), None, False, args.number_ranges), 24000)
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
