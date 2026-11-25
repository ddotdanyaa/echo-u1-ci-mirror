"""W2 / С10: заранее строит файл пар «вопрос — ответ» из материала текстовой моделью. Запуск на ноутбуке; здесь модели нет, в тестах подделка.

    python -m tools.build_prepared_answers материал.txt пары.json --complete пакет.модуль:функция [--per-chunk 6] [--chunk-chars 2500]

``--complete``: функция ``complete(prompt: str) -> str`` (ответ модели одной строкой), её даёт ноутбук (тот же вход Codex, что у ``fast_text``); ключей и токенов скрипт не читает и не пишет.
Модель просят вернуть JSON-список ``{"q","a"}``; всё, что не прошло ``prepared_answers`` (изменчивые данные, отсылочные и короткие вопросы), отбрасывается, ответ с числом, которого нет в куске материала,
тоже: число в готовом ответе должно быть из источника. Повторы по ``same_question`` сливаются. Итог — JSON, который читает ``prepared_answers.load``; в stderr только счётчики."""
import argparse
import importlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echo_sync import prepared_answers as pa  # noqa: E402
from echo_sync.fast_text import same_question  # noqa: E402

PROMPT = ('Ты готовишь шпаргалку для устного ответа. По тексту ниже придумай до {n} вопросов, которые могут задать вслух, и короткий ответ на каждый: две-три фразы до 12 слов, обычными словами, '
          'только из текста, без новых чисел. Вопрос должен быть понятен без текста: без «это», «он», «выше». Не включай ставки, лимиты и всё, что меняется со временем. '
          'Верни только JSON-список вида [{{"q": "...", "a": "..."}}].\n\nТекст:\n{chunk}')


def chunks(material, size):
    """The material cut at paragraph ends into pieces of about ``size`` characters."""
    out, cur = [], ''
    for para in re.split(r'\n\s*\n', material):
        if cur and len(cur) + len(para) > size:
            out.append(cur.strip())
            cur = ''
        cur += para + '\n\n'
    if cur.strip():
        out.append(cur.strip())
    return out


def _numbers(text):
    return set(re.findall(r'\d+(?:[.,]\d+)?', text))


def build(material, complete, *, per_chunk=6, chunk_chars=2500):
    """-> (pairs, stats). ``complete(prompt) -> str`` may raise: that chunk gives nothing."""
    pairs, stats = [], {'chunks': 0, 'asked': 0, 'kept': 0, 'bad_reply': 0, 'dropped_unstable': 0, 'dropped_foreign_number': 0, 'dropped_duplicate': 0}
    for chunk in chunks(str(material or ''), chunk_chars):
        stats['chunks'] += 1
        try:
            reply = complete(PROMPT.format(n=per_chunk, chunk=chunk))
            raw = pa.parse_pairs(re.sub(r'^```\w*\s*|\s*```$', '', str(reply).strip()))
        except Exception:                # noqa: BLE001
            raw = []
        if not raw:
            stats['bad_reply'] += 1
        known = _numbers(chunk)
        for q, a in raw[:per_chunk * 2]:
            stats['asked'] += 1
            kept = pa._stable(q, a)
            if not kept:
                stats['dropped_unstable'] += 1
            elif not _numbers(kept[1]) <= known:
                stats['dropped_foreign_number'] += 1
            elif any(same_question(kept[0], old) and same_question(old, kept[0]) for old, _ in pairs):
                stats['dropped_duplicate'] += 1
            else:
                pairs.append(kept)
                stats['kept'] += 1
    return pairs, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('material')
    ap.add_argument('out')
    ap.add_argument('--complete', required=True, help='пакет.модуль:функция')
    ap.add_argument('--per-chunk', type=int, default=6)
    ap.add_argument('--chunk-chars', type=int, default=2500)
    args = ap.parse_args(argv)
    module, _, name = args.complete.partition(':')
    complete = getattr(importlib.import_module(module), name)
    pairs, stats = build(Path(args.material).read_text(encoding='utf-8'), complete, per_chunk=args.per_chunk, chunk_chars=args.chunk_chars)
    Path(args.out).write_text(json.dumps([{'q': q, 'a': a} for q, a in pairs], ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(stats, ensure_ascii=False), file=sys.stderr)
    return 0 if pairs else 1


if __name__ == '__main__':
    sys.exit(main())
