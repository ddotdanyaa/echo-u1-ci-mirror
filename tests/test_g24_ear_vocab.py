"""g24 / N198: the ear's word list is built from the material by itself, per subject, and never holds a number word, a digit or «не»."""
import json
from pathlib import Path

from tools import ear_vocab

MATERIAL = Path(__file__).resolve().parent.parent / 'cloud_context' / 'material' / 'ВСЕ_ПРЕДМЕТЫ.md'
TEXT = '# ОП.09 БУХГАЛТЕРСКИЙ УЧЁТ (Иванова)\n## ОП.09. Касса\nКассовая книга ведётся кассиром. Кассовая книга, кассовая дисциплина, 50 счёт.\n# ОП.05 ИТ\n## ОП.05. Excel\nТаблица Excel, формулы таблицы, сводная таблица.\n'


def test_subjects_are_split_by_top_headings():
    assert list(ear_vocab.split_subjects(TEXT)) == ['ОП.09', 'ОП.05']


def test_each_subject_gets_its_own_terms():
    vocab = ear_vocab.build(TEXT)
    assert 'кассовая' in vocab['ОП.09'] and 'кассовая' not in vocab['ОП.05']
    assert 'таблица' in vocab['ОП.05'] or 'таблицы' in vocab['ОП.05']


def test_no_digit_or_not_in_terms():
    for terms in ear_vocab.build(TEXT + 'не нужно, пятьдесят два, ни разу, двадцать копеек').values():
        assert all(not any(c.isdigit() for c in t) and t not in ('не', 'ни', 'пятьдесят', 'двадцать') for t in terms)


def test_real_material_gives_four_subjects_and_a_stable_file(tmp_path):
    out = tmp_path / 'ear_vocab.json'
    a = ear_vocab.write(MATERIAL, out)
    first = out.read_bytes()
    assert len(a) == 4 and all(len(v) >= 20 for v in a.values())
    ear_vocab.write(MATERIAL, out)
    assert out.read_bytes() == first and json.loads(first) == a


def test_a_broken_material_file_keeps_the_old_vocab(tmp_path):
    out = tmp_path / 'ear_vocab.json'
    out.write_text('{"x": ["слово"]}', encoding='utf-8')
    try:
        ear_vocab.write(tmp_path / 'missing.md', out)
    except ValueError:
        pass
    assert json.loads(out.read_text(encoding='utf-8')) == {'x': ['слово']}
