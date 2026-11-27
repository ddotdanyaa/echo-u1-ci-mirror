"""W2 / С10, С11: готовые ответы без модели. Лист вопрос-ответ из материала и долгий кэш устойчивых ответов, поиск через ``same_question``; форма результата как у ``quick_math.answer``: строка или ``None``."""
import json
import time

import pytest

from echo_sync import prepared_answers as pa
from echo_sync import settings

PAIRS = [('Что такое амортизация основных средств', 'Амортизация — это перенос стоимости основного средства на расходы по частям.'),
         ('Сколько дней в отпуске по трудовому кодексу', 'Двадцать восемь календарных дней.'),
         ('Не более пятнадцати процентов выручки', 'Проверка условия не нужна.'),
         ('Что такое дебет счёта', 'Дебет — левая сторона счёта.')]


def book(**kw):
    return pa.PreparedAnswers(PAIRS, **kw)


@pytest.mark.parametrize('heard,expected', [
    ('Что такое амортизация основных средств?', 0), ('ну скажи, что такое амортизация основных средств', 0), ('что такое дебет счёта', 3)])
def test_hits(heard, expected):
    assert book().lookup(heard) == PAIRS[expected][1]


@pytest.mark.parametrize('heard', [
    'Что такое амортизация', 'Что такое амортизация нематериальных активов', 'Сколько дней в отпуске по трудовому кодексу в 2026 году', 'Сколько дней в отпуске',
    'Не более пятидесяти процентов выручки', 'Более пятнадцати процентов выручки', 'расскажи про погоду', '', None, 'а почему?'])
def test_misses(heard):
    assert book().lookup(heard) is None


def test_numbers_are_protected():
    b = pa.PreparedAnswers([('Сколько стоит сорок восемь штук товара', 'Много.')])
    assert b.lookup('сколько стоит 48 штук товара') == 'Много.'
    assert b.lookup('сколько стоит 49 штук товара') is None and b.lookup('сколько стоит сорок штук товара') is None
    assert b.lookup('сколько стоит 2025 штук товара') is None   # an ordinal year spoken in words is a miss, never a wrong hit


def test_two_answers_for_one_question_is_no_answer():
    b = pa.PreparedAnswers([('Что такое дебет счёта', 'Один.'), ('что такое дебет счёта?', 'Два.')])
    assert b.lookup('что такое дебет счёта') is None
    assert pa.PreparedAnswers([('Что такое дебет счёта', 'Один.'), ('что такое дебет счёта?', 'Один.')]).lookup('что такое дебет счёта') == 'Один.'


def test_current_data_is_not_kept():
    b = pa.PreparedAnswers([('Какая сейчас ставка НДС', 'Двадцать.'), ('Какая ставка рефинансирования', 'Шестнадцать.'), ('Что такое НДС', 'Налог.')])
    assert b.skipped == 2 and len(b) == 1
    assert b.lookup('какая сейчас ставка НДС') is None
    assert b.remember('Какой действующий размер МРОТ', 'Много.') is False


def test_short_or_empty_pairs_dropped():
    b = pa.PreparedAnswers([('Да', 'Нет.'), ('Что такое НДС', ''), ('', 'x'), ('Что такое налог на прибыль', '  Налог.  ')])
    assert len(b) == 1 and b.lookup('что такое налог на прибыль') == 'Налог.'


def test_speed():
    big = pa.PreparedAnswers([('Что такое понятие номер %d в учёте' % i, 'Ответ %d.' % i) for i in range(1000)])
    big.lookup('что такое понятие номер 5 в учёте')
    start = time.perf_counter()
    for _ in range(20):
        assert big.lookup('что такое понятие номер 777 в учёте') == 'Ответ 777.'
    assert (time.perf_counter() - start) / 20 < 0.02


def test_parse_formats(tmp_path):
    text = 'В: Что такое НДС?\nО: Налог на добавленную стоимость.\n\nВ: Что такое НДФЛ\nО: Налог\nна доходы.\n'
    assert pa.parse_pairs(text) == [('Что такое НДС?', 'Налог на добавленную стоимость.'), ('Что такое НДФЛ', 'Налог на доходы.')]
    data = json.dumps([{'q': 'Что такое НДС', 'a': 'Налог.'}, ['Что такое НДФЛ', 'Другой.'], {'bad': 1}, 5], ensure_ascii=False)
    assert pa.parse_pairs(data) == [('Что такое НДС', 'Налог.'), ('Что такое НДФЛ', 'Другой.')]
    path = tmp_path / 'p.txt'
    path.write_text(text, encoding='utf-8')
    assert len(pa.load(str(path))) == 2 and len(pa.load(str(tmp_path / 'none'))) == 0


def test_cache_survives_restart_and_expires(tmp_path):
    now = [1000.0]
    path = tmp_path / 'cache.json'
    a = pa.PreparedAnswers(cache_path=path, clock=lambda: now[0], ttl=100)
    assert a.remember('Что такое амортизация основных средств', 'Перенос стоимости.') is True
    assert pa.PreparedAnswers(cache_path=path, clock=lambda: now[0] + 50, ttl=100).lookup('что такое амортизация основных средств') == 'Перенос стоимости.'
    assert pa.PreparedAnswers(cache_path=path, clock=lambda: now[0] + 101, ttl=100).lookup('что такое амортизация основных средств') is None


def test_cache_refuses_unstable_and_bad(tmp_path):
    a = pa.PreparedAnswers(cache_path=tmp_path / 'c.json')
    for q, ans in (('Какая сегодня ставка НДС', 'Двадцать.'), ('а почему', 'Потому.'), ('Что это такое', 'Вот.'), ('Что такое НДС', ''), ('Что такое НДС', 'x' * 5000)):
        assert a.remember(q, ans) is False
    assert not (tmp_path / 'c.json').exists()


def test_cache_damaged_file_is_empty(tmp_path):
    path = tmp_path / 'c.json'
    a = pa.PreparedAnswers(cache_path=path)
    a.remember('Что такое налог на прибыль', 'Налог.')
    row = json.loads(path.read_text('utf-8'))
    row['entries'][0]['a'] = 'Подмена.'
    path.write_text(json.dumps(row, ensure_ascii=False), 'utf-8')
    assert pa.PreparedAnswers(cache_path=path).lookup('что такое налог на прибыль') is None
    path.write_text('{not json', 'utf-8')
    assert len(pa.PreparedAnswers(cache_path=path)) == 0


def test_cache_bounded(tmp_path):
    a = pa.PreparedAnswers(cache_path=tmp_path / 'c.json', max_entries=3)
    for i in range(6):
        a.remember('Что такое понятие номер %d в учёте' % i, 'Ответ %d.' % i)
    assert len(a) == 3 and a.lookup('что такое понятие номер 5 в учёте') == 'Ответ 5.' and a.lookup('что такое понятие номер 0 в учёте') is None


def test_prepared_beats_cache(tmp_path):
    a = pa.PreparedAnswers(PAIRS, cache_path=tmp_path / 'c.json')
    a.remember('Что такое дебет счёта', 'Из кэша.')
    assert a.lookup('что такое дебет счёта') == PAIRS[3][1]


def test_never_raises():
    b = book()
    for bad in (5, b'x', object(), ['что такое дебет счёта']):
        assert b.lookup(bad) is None
    assert pa.PreparedAnswers(5).lookup('что такое дебет счёта') is None


def test_the_file_setting_is_empty_by_default_and_there_is_no_switch():
    s = settings.resolve({})
    assert s['prepared_answers_file'] == '' and 'prepared_answers' not in s


# -- the builder script (tools/build_prepared_answers.py): the model is a fake here ----------------------------------

def _builder():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'tools' / 'build_prepared_answers.py'
    spec = importlib.util.spec_from_file_location('build_prepared_answers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_builder_filters_the_model(tmp_path):
    b = _builder()
    material = 'Амортизация переносит стоимость на расходы по частям.\n\nОтпуск длится 28 дней.'
    reply = json.dumps([{'q': 'Что такое амортизация', 'a': 'Перенос стоимости по частям.'},
                        {'q': 'Сколько длится отпуск', 'a': 'Двадцать восемь дней, то есть 28.'},
                        {'q': 'Сколько длится отпуск у нас', 'a': 'Тридцать пять дней, то есть 35.'},
                        {'q': 'Какая сейчас ставка НДС', 'a': 'Двадцать.'},
                        {'q': 'А почему так', 'a': 'Потому.'},
                        {'q': 'что такое амортизация?', 'a': 'Дубль.'}], ensure_ascii=False)
    pairs, stats = b.build(material, lambda prompt: '```json\n' + reply + '\n```', chunk_chars=5000)
    assert [q for q, _ in pairs] == ['Что такое амортизация', 'Сколько длится отпуск']
    assert (stats['dropped_foreign_number'], stats['dropped_unstable'], stats['dropped_duplicate']) == (1, 2, 1)
    out = tmp_path / 'pairs.json'
    out.write_text(json.dumps([{'q': q, 'a': a} for q, a in pairs], ensure_ascii=False), 'utf-8')
    assert pa.load(str(out)).lookup('что такое амортизация') == 'Перенос стоимости по частям.'


def test_builder_survives_model_failure():
    b = _builder()

    def broken(prompt):
        raise RuntimeError('нет сети')
    assert b.build('Один абзац.\n\nДругой абзац.', broken, chunk_chars=5)[0] == []
    assert b.build('текст', lambda p: 'не json')[1]['bad_reply'] == 1


# -- the controller: the patch in cloud_context/reports/w2-prepared.md (controlled_media.py is not ours to edit) --------------------

from test_h3_tempo import call  # noqa: E402,F401 - the fixture of the controller rig


def test_controller_takes_a_prepared_answer_like_a_hit_of_the_base(call):
    rig = call(fast_text='on')
    rig.c.prepared = book()
    assert rig.c._reference('что такое амортизация основных средств') == PAIRS[0][1]
    assert rig.c._reference('что такое амортизация') is None
    assert rig.c._reference('семнадцатая статья налогового кодекса').startswith('Статья 17'), 'the base stays first'


def test_a_prepared_answer_the_ear_opens_needs_the_cloud_as_second_witness(call):
    """w3-integ item 10 (risk 1 of w2-prepared.md): a prepared hit on the ear's words is held like a figure of quick_math (``_ear_sum``) until the cloud's words give the same hit."""
    rig = call(fast_text='on')
    rig.c.prepared = book()
    first = {'hit': PAIRS[0][1], 'text': 'что такое амортизация основных средств'}
    assert rig.c._ear_sum(first), 'the ear alone opens no prepared answer'
    assert rig.c._witness('Что такое амортизация основных средств?') == PAIRS[0][1]
    assert rig.c._witness('Что такое аренда основных средств?') != PAIRS[0][1], 'another word of the cloud: no second witness'
    rig.c.prepared = None
    assert not rig.c._ear_sum(first), 'off: as before'


def test_the_reference_and_the_prepared_read_the_one_selector_of_the_calls_questions(call):
    """memory: the questions a follow-up takes its code from are the call's (the floor ``call_began``), no exchange the ear opened by mistake, and the last ``CALL_QUESTIONS``: one window, not 8 and 3."""
    rig = call(fast_text='on')
    rows = [{'question': q, 'answer': 'ответ', 'at': at} for q, at in
            (('старый звонок', 1.0), ('что такое 18 статья налогового кодекса', 50.0), ('а', 60.0), ('б', 70.0), ('в', 80.0))]
    rows[-1]['status'] = 'unasked'      # the engine's history says the ear opened it by mistake
    rig.c.state = lambda: {'history': rows}
    rig.c.call_began = 10.0
    assert rig.c.call_questions() == ['что такое 18 статья налогового кодекса', 'а', 'б']
    assert rig.c._reference('а 27-я?') is not None, 'the code is taken from the 3 last questions of the call'
    rows[-1]['status'] = 'complete'
    assert rig.c.call_questions() == ['а', 'б', 'в']
    assert rig.c._reference('а 27-я?') is None, 'the code is 4 questions back: out of the window'
