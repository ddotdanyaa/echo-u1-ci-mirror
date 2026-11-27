"""Build the law base.

From the downloaded pages (the way it is rebuilt; repeat it any time, new pages are picked up):
    python -I tools/build_law_base.py --raw-full "C:/УСТРОЙСТВО 1/U1/03_TESTS/reference_kb/raw_full" --out law.sqlite

``--raw-full DIR``: DIR holds ``manifest.jsonl`` (code, law, title, url, sha256, bytes, at) and ``<code>/<hash of the url>.html``. A page is taken only when its
file exists, its size and sha256 are the manifest's (a page that is being written is skipped, the next run takes it), it is parsed with ``law_base.parse_page``.
The pages are untrusted text: they are only parsed (html.parser and regular expressions), nothing in them is run or fetched.

From single files (the first version): ``--doc CODE=FILE[::SOURCE_URL]`` (repeat per document; FILE is a consultant page saved as HTML or the plain text of
the law; CODE one of konst gk nk tk uk koap gpk apk sk zhk). ``--edition YYYY-MM-DD`` overrides the edition taken from the title.

``--low-priority`` puts the process to BelowNormal. Prints one JSON line (documents, rows, articles, bytes, pages, what was skipped, seconds)."""
import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from echo_sync import law_base as lb  # noqa: E402


def below_normal():
    """BelowNormal priority of this process (Windows; a no-op elsewhere). True only when Windows accepted it."""
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p                  # the pseudo handle is -1: without the types ctypes cuts it to 32 bits and the call fails quietly
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        return bool(kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000))
    except Exception:  # noqa: BLE001
        return False


def read_manifest(raw_dir):
    """Entries of ``manifest.jsonl`` (a half-written last line is dropped; a url met twice counts once, the last wins)."""
    entries, bad = {}, 0
    with open(os.path.join(raw_dir, 'manifest.jsonl'), encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line)
                entries[entry['url']] = entry
            except (ValueError, KeyError, TypeError):
                bad += 1
    return list(entries.values()), bad


def page_path(raw_dir, entry):
    return os.path.join(raw_dir, entry['code'], entry['url'].rstrip('/').rsplit('/', 1)[-1] + '.html')


def article_key(entry):
    """Natural order of the article of a manifest entry («Статья 346.43. ...» -> (346, 43)); entries without a number go last."""
    m = re.match(r'Статья\s+(\d+(?:\.\d+)*(?:-\d+)?)', entry.get('title', ''))
    return tuple(int(x) for x in re.findall(r'\d+', m.group(1))) if m else (10 ** 9,)


def load_pages(raw_dir, codes=None, skipped=None):
    """``[(entry, markup)]`` of the pages that are whole, in a fixed order (code, article number, url). ``skipped`` counts the rest by reason."""
    skipped = skipped if skipped is not None else {}
    entries, bad = read_manifest(raw_dir)
    skipped['manifest_bad_lines'] = bad
    out = []
    for entry in sorted(entries, key=lambda e: (e['code'], article_key(e), e['url'])):
        if codes and entry['code'] not in codes:
            continue
        path = page_path(raw_dir, entry)
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            skipped['missing_file'] = skipped.get('missing_file', 0) + 1
            continue
        if len(data) != entry.get('bytes') or hashlib.sha256(data).hexdigest() != entry.get('sha256'):
            skipped['size_or_hash_differs'] = skipped.get('size_or_hash_differs', 0) + 1
            continue
        try:
            out.append((entry, data.decode('utf-8')))
        except UnicodeDecodeError:
            skipped['not_utf8'] = skipped.get('not_utf8', 0) + 1
    return out


def parse_all(raw_dir, codes=None, skipped=None):
    """``[(Doc, [Row])]`` for every whole page of the manifest; a page that does not parse or has no article is counted in ``skipped`` and left out."""
    skipped = skipped if skipped is not None else {}
    parsed = []
    for entry, markup in load_pages(raw_dir, codes, skipped):
        try:
            doc, rows = lb.parse_page(markup, entry['code'], entry['url'])
        except Exception:  # noqa: BLE001
            skipped['parse_error'] = skipped.get('parse_error', 0) + 1
            continue
        if not rows:
            skipped['no_article'] = skipped.get('no_article', 0) + 1
            continue
        parsed.append((doc, rows))
    return parsed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True)
    ap.add_argument('--raw-full', metavar='DIR')
    ap.add_argument('--codes', help='only these codes, comma separated (with --raw-full)')
    ap.add_argument('--doc', action='append', metavar='CODE=FILE[::URL]')
    ap.add_argument('--edition')
    ap.add_argument('--low-priority', action='store_true')
    args = ap.parse_args(argv)
    if bool(args.raw_full) == bool(args.doc):
        ap.error('give --raw-full DIR or --doc CODE=FILE')
    if args.low_priority:
        below_normal()
    started, skipped = time.perf_counter(), {}
    parsed = []
    if args.raw_full:
        parsed = parse_all(args.raw_full, set(args.codes.split(',')) if args.codes else None, skipped)
    for spec in args.doc or ():
        code, _, rest = spec.partition('=')
        path, _, url = rest.partition('::')
        if code not in lb.SPOKEN or not path:
            ap.error('bad --doc %r' % spec)
        with open(path, encoding='utf-8') as f:
            parsed.append(lb.parse_page(f.read(), code, url, args.edition))
    parsed_at = time.perf_counter()
    tmp = args.out + '.new'
    lb.build(tmp, parsed)
    os.replace(tmp, args.out)
    done = time.perf_counter()
    print(json.dumps({'documents': len({d.code for d, _ in parsed}), **lb.stats(args.out), 'pages': len(parsed), 'skipped': skipped,
                      'seconds': {'read_and_parse': round(parsed_at - started, 1), 'write': round(done - parsed_at, 1), 'total': round(done - started, 1)}},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
