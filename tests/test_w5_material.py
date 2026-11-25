"""w5-material (E15, E40): the model sees the parts of the material that fit the question and the talk, in the same character cap."""
import csv
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import helpers_w5_material as fx
from echo_sync import content_policy
from echo_sync.content_policy import MATERIAL_EXCERPT_CHARS, CallContext
from echo_sync.material_pick import MaterialPicker, split_parts

MATERIAL, FACTS = fx.build_material()
TABLE = Path(__file__).resolve().parent.parent / 'cloud_context' / 'reports' / 'w5-material.table.csv'


def test_the_cut_is_where_the_report_says():
    shown, truncated = content_policy.excerpt_of(MATERIAL)
    assert truncated and len(shown) <= MATERIAL_EXCERPT_CHARS < len(MATERIAL)
    assert 'Курс: электротехника' not in shown            # three of four subjects are silently out


def test_parts_follow_headings_and_paragraphs_and_lose_nothing():
    parts = split_parts(MATERIAL)
    assert len(parts) >= 40 and all(len(p) <= 1500 for p in parts)
    assert all(marker in ''.join(parts) for *_, marker in FACTS)
    long = '## Длинный\n\n' + '\n\n'.join(f'Абзац {i}. ' + 'слово ' * 90 for i in range(12))
    assert all(len(p) <= 1500 for p in split_parts(long)) and sum(p.count('Абзац') for p in split_parts(long)) == 12


def test_table_200_questions():
    picker, rows, base_hits, ms = MaterialPicker(MATERIAL), [], 0, []
    head, _ = content_policy.excerpt_of(MATERIAL)
    for question, history, marker in fx.questions():
        t0 = time.perf_counter()
        pick = picker.pick(question, history)
        ms.append((time.perf_counter() - t0) * 1000)
        hit, base = marker in pick.text, marker in head
        base_hits += base
        assert len(pick.text) <= MATERIAL_EXCERPT_CHARS
        rows.append((question, bool(history), marker, int(hit), int(base), pick.parts, len(pick.text), pick.fallback))
    TABLE.parent.mkdir(exist_ok=True)
    with TABLE.open('w', newline='', encoding='utf-8') as out:
        w = csv.writer(out)
        w.writerow(['question', 'followup', 'marker', 'picked_hit', 'first_chars_hit', 'parts', 'chars', 'fallback'])
        w.writerows(rows)
    hits = sum(r[3] for r in rows)
    print(f'picked {hits}/200, first chars {base_hits}/200, median {statistics.median(ms):.2f} ms, max {max(ms):.2f} ms')
    assert hits >= 196 and hits > base_hits + 100
    assert statistics.median(ms) < 5 and max(ms) < 50


def test_numbers_and_terms_weigh_more():
    body = '## А\n\nКоэффициент равен 183 для расчёта срока.\n\n## Б\n\n' + 'Коэффициент расчёта срока описан в общем виде и часто упоминается. ' * 3
    picker = MaterialPicker(body, cap=len(body) - 20)
    assert '183' in picker.pick('Какой коэффициент 183 в расчёте срока?', []).text


def test_nothing_fits_means_the_first_characters_as_now():
    pick = MaterialPicker(MATERIAL).pick('Привет, как дела?', [])
    expected, _ = content_policy.excerpt_of(MATERIAL)
    assert pick.fallback and pick.text == expected


def test_short_material_is_shown_whole():
    pick = MaterialPicker('Одна короткая справка о гусях.').pick('Что нового?', [])
    assert pick.text == 'Одна короткая справка о гусях.' and not pick.truncated


def test_summary_has_no_text():
    pick = MaterialPicker(MATERIAL).pick('Что такое резонансный контур?', [])
    line = pick.summary()
    assert 'parts=' in line and 'chars=' in line and 'truncated=' in line and 'контур' not in line and 'Кальвина' not in line


def test_instructions_carry_the_picked_text_inside_the_data_block():
    picker = MaterialPicker(MATERIAL)
    text = picker.instructions('Что такое мейоз?', [], CallContext(subject='Биология'), content_policy.ANSWER_POLICY)
    assert 'кроссинговером в профазе' in text and 'Предмет занятия: Биология' in text
    assert text.index('⟦МАТЕРИАЛЫ') < text.index('кроссинговером') < text.index('⟦КОНЕЦ МАТЕРИАЛОВ') < text.index(content_policy.CLOSING)
    assert 'показано начало' not in text and 'подобраны' in text


def test_a_broken_picker_never_fails_the_call():
    assert MaterialPicker('').pick('Что такое мейоз?', []).text == ''
    assert MaterialPicker(MATERIAL).pick(None, None).fallback
