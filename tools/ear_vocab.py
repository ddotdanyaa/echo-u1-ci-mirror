"""N198 (g24): the ear's word list from the material, by itself, one list per subject.

    python -m tools.ear_vocab [material.md] [out.json]

Subjects are the top «# » headings of the material file (the first token is the subject: «ОП.09»). Each list is ``ear_sherpa.material_terms`` of that
subject's text, so a digit, a number word and «не»/«ни» never get in. The output is deterministic; a material file that cannot be read raises
ValueError and the old output file is not touched."""
import json
import re
import sys
from pathlib import Path

from echo_sync.ear_sherpa import material_terms

_TOP = re.compile(r'^# ([А-ЯA-Z]+\.\d\d(?:\.\d\d)?)\b', re.M)


def split_subjects(text):
    marks = list(_TOP.finditer(text))
    return {m.group(1): text[m.start():(marks[i + 1].start() if i + 1 < len(marks) else len(text))] for i, m in enumerate(marks)}


def build(text, limit=200):
    return {name: material_terms(body, limit) for name, body in split_subjects(text).items()}


def write(material, out, limit=200):
    try:
        text = Path(material).read_text(encoding='utf-8-sig')
    except OSError as exc:
        raise ValueError(f'material cannot be read: {type(exc).__name__}') from exc
    vocab = build(text, limit)
    if not vocab:
        raise ValueError('material has no «# » subject headings')
    Path(out).write_text(json.dumps(vocab, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
    return vocab


if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else 'cloud_context/material/ВСЕ_ПРЕДМЕТЫ.md'
    dst = sys.argv[2] if len(sys.argv) > 2 else 'ear_vocab.json'
    print({k: len(v) for k, v in write(src, dst).items()})
