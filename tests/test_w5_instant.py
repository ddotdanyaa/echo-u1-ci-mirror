"""w5-instant (С10, С11, С12, Ст7, Б5): a ready answer on the ear's partial text, from one index of the bank, the laws, the chart of accounts and the material."""
import csv
import json
import statistics
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_w5_instant as fx
from echo_sync import instant, pcm_cache
from echo_sync.instant import Instant, load_bank, phonetic
from echo_sync.settings import resolve

TABLE = Path(__file__).resolve().parent.parent / 'cloud_context' / 'reports' / 'w5-instant.table.csv'


@pytest.fixture(scope='module')
def ix():
    return Instant(fx.bank())


def run(ix, row):
    """The row as the ear gives it: every partial word by word (``t`` = word index * 0.3 s), then the final. -> (hit, at, cut)"""
    ix.reset()
    hit, at, cut = None, None, False
    for k, text in enumerate(row['partials']):
        final = k == len(row['partials']) - 1
        got = ix.feed(text, 0.3 * k, final=final)
        if got and hit is None:
            hit, at = got, k
        if hit and ix.cut:
            cut = True
            break
    return hit, at, cut


def test_off_by_default_and_paths():
    s = resolve(None)
    assert s['instant'] == 'off' and s['instant_bank_file'] == '' and s['pcm_cache_dir'] == ''
    assert resolve({'instant': 'on', 'instant_bank_file': ' C:/bank.json '})['instant_bank_file'] == 'C:/bank.json'
    assert resolve({'instant_bank_file': 'a\nb'})['instant_bank_file'] == ''
    assert resolve({'instant': 'on'})['instant'] == 'off', 'no acting ear, no text to open on'
    assert resolve({'instant': 'on', 'fast_text': 'on', 'local_ear': 'act'})['instant'] == 'on'


def test_plain_question_hits_on_the_partial_before_the_final(ix):
    ix.reset()
    assert ix.feed('что такое', 0.0) is None
    assert ix.feed('что такое амортизация', 0.3) is None          # «Какие способы амортизации бывают» holds every word heard: wait on a partial
    ix.reset()
    hit = ix.feed('когда пал константинополь', 0.6)
    assert hit and hit.id == 'h01' and hit.early and hit.core and len(hit.core.split()) <= 6 and hit.answer.startswith('Двадцать девятого')
    assert hit.trust == 'Д' and hit.source == 'фейк'


def test_numbers_and_not_are_exact(ix):
    ix.reset()
    assert ix.feed('что говорится в статье 16 налогового кодекса', 0, final=True) is None
    ix.reset()
    assert ix.feed('что говорится в статье 17 налогового кодекса', 0, final=True).id == 'n01'
    ix.reset()
    assert ix.feed('кто не платит налог на имущество организаций', 0, final=True) is None
    ix.reset()
    assert ix.feed('кто платит налог на имущество организаций', 0, final=True).id == 't04'


def test_ear_error_in_an_ordinary_word_but_never_in_a_number(ix):
    ix.reset()
    assert ix.feed('что такое амартизация основных средств', 0, final=True).id == 'a01'
    assert phonetic('амартизация') == phonetic('амортизация') and phonetic('семнадцать') != phonetic('шестнадцать')
    ix.reset()
    assert ix.feed('какие налоги платит ип на усн 16 процентов', 0, final=True) is None


def test_two_candidates_and_a_question_that_goes_on(ix):
    ix.reset()
    assert ix.feed('когда началась мировая война', 0, final=True) is None       # first or second?
    ix.reset()
    assert ix.feed('что такое ндс', 0) is None                                   # «… при импорте» is a bank question too: wait on a partial
    ix.reset()
    assert ix.feed('что такое ндс', 0, final=True).id == 't16'                   # the ear's cut-off: the speech stopped
    ix.reset()
    hit = ix.feed('что такое митохондрия', 0.6)
    assert hit and hit.id == 'b01' and not ix.cut
    assert ix.feed('что такое митохондрия и почему', 0.9) is None and ix.cut     # new significant words: the cue is cut, the question goes on as usual
    ix.reset()
    hit = ix.feed('что такое митохондрия', 0.6)
    assert ix.feed('что такое митохондрия вот', 0.9) is None and not ix.cut      # a filler is no new question


def test_dangling_preposition_waits(ix):
    ix.reset()
    assert ix.feed('что такое пеня по налогам и', 0) is None


def test_adapters_reference_and_math_on_the_final():
    ix = Instant([])
    assert ix.feed('сколько будет семь умножить на восемь', 0) is None
    ix.reset()
    hit = ix.feed('сколько будет семь умножить на восемь', 0, final=True)
    assert hit and hit.source == 'quick_math' and hit.answer == 'Пятьдесят шесть.'
    ix.reset()
    hit = ix.feed('что такое 71 счёт', 0, final=True)
    assert hit and hit.source == 'reference_kb' and '71' in hit.answer


def test_bank_and_adapter_that_disagree_give_nothing():
    bank = [{'q': 'Что такое 71 счет', 'answer': 'Совсем другое.', 'source': 'x'}]
    ix = Instant(bank)
    assert ix.feed('что такое 71 счет', 0, final=True) is None


def test_bank_file_validation(tmp_path):
    path = tmp_path / 'bank.json'
    path.write_text(json.dumps([{'q': 'Что такое осмос', 'answer': 'Переход воды через мембрану.'}, {'q': '', 'answer': 'x'}, 5,
                                {'q': 'Что такое сегодня курс доллара', 'answer': 'Девяносто.'}], ensure_ascii=False), encoding='utf-8')
    rows = load_bank(path)
    assert [r['q'] for r in rows] == ['Что такое осмос'] and rows[0]['trust'] == 'Д' and rows[0]['core']
    assert load_bank(tmp_path / 'missing.json') == [] and load_bank(path, trust='М')[0]['trust'] == 'М'


def test_material_pairs_are_trust_m():
    ix = Instant([], material='## Тема\n\nВ: Что такое осмос\nО: Переход воды через мембрану.\n\nТекст без вопроса.')
    hit = ix.feed('что такое осмос', 0, final=True)
    assert hit and hit.trust == 'М'


def test_core_is_six_words_at_most():
    assert instant.core_of('Крещение Руси традиционно относят к девятьсот восемьдесят восьмому году, при князе Владимире.') == 'Крещение Руси традиционно относят'
    core = instant.core_of('Основная ставка НДС двадцать процентов, льготные десять и ноль.')
    assert core == 'Основная ставка НДС двадцать процентов,'
    assert len(instant.core_of('Один два три четыре пять шесть семь восемь девять.').split()) <= 6


def test_vocab_has_no_numbers_and_no_not():
    terms = instant.vocab_terms(fx.bank())
    assert 'амортизация' in ' '.join(terms) and not any(t.isdigit() or t in ('не', 'ни', 'семнадцать') for t in terms)


def test_lookup_is_milliseconds_on_5000_questions():
    rows = fx.bank()
    words = sorted({w for r in rows for w in r['q'].lower().split() if len(w) > 4})
    big = rows + [{'q': f'Что такое {words[i % len(words)]} {words[(i * 7) % len(words)]} номер {i}', 'answer': f'Ответ {i}.'} for i in range(5000 - len(rows))]
    t0 = time.perf_counter()
    ix = Instant(big)
    build = time.perf_counter() - t0
    texts = [r['heard'] for r in fx.table()[:200]]
    times = []
    for text in texts:
        ix.reset()
        t = time.perf_counter()
        ix.feed(text, 0, final=True)
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    print(f'build {build:.2f} s, feed median {statistics.median(times):.2f} ms, p95 {times[int(0.95 * len(times))]:.2f} ms')
    assert statistics.median(times) < 5 and times[int(0.95 * len(times))] < 15


def test_table_of_500_no_false_accept(ix):
    rows = fx.table()
    assert len(rows) == 500
    false, early_cut, lost, got, stats = [], 0, 0, 0, {}
    out = []
    for row in rows:
        hit, at, cut = run(ix, row)
        hid = hit.id if hit else ''
        wrong = bool(hit) and not cut and hid not in row['ok']
        if wrong:
            false.append((row['kind'], row['heard'], hid))
        early_cut += bool(hit and cut)
        if row['want']:
            got += hid == row['want'] and not cut
            lost += hid != row['want'] or cut
        k = stats.setdefault(row['kind'], [0, 0, 0, 0])
        k[0] += 1
        k[1] += bool(hit and not cut)
        k[2] += bool(hit and cut)
        k[3] += wrong
        words_left = len(row['partials']) - 1 - at if hit else ''
        out.append([row['kind'], row['heard'], row['want'] or '', '|'.join(sorted(row['ok'])), row['forbid'] or '', hid, words_left, int(cut), int(wrong)])
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    with TABLE.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['kind', 'heard', 'want', 'ok', 'forbid', 'hit', 'words_before_end', 'cut', 'false_accept'])
        w.writerows(out)
    print('kind: rows, hits kept, hits cut, false accepts', stats, 'want got', got, 'lost', lost, 'early cut', early_cut)
    assert false == []
    wanted = sum(1 for r in rows if r['want'])
    assert got >= 0.85 * wanted


def test_pcm_cache_roundtrip_and_limit(tmp_path):
    cache = pcm_cache.PcmCache(tmp_path / 'pcm', max_bytes=3000)
    assert cache.get('Привет', 'irina', 24000) is None
    cache.put('Привет', 'irina', 24000, b'\x01\x00' * 500)
    assert cache.get('Привет', 'irina', 24000) == b'\x01\x00' * 500
    assert cache.get('Привет', 'pavel', 24000) is None and cache.get('Привет', 'irina', 16000) is None
    for i in range(5):
        cache.put(f'Текст {i}', 'irina', 24000, b'\x00\x00' * 500)
    assert cache.size() <= 3000 and cache.get('Текст 4', 'irina', 24000) is not None


def test_pcm_cache_render_looks_first(tmp_path):
    calls = []

    def render(text):
        calls.append(text)
        return b'\x02\x00' * 10
    cache = pcm_cache.PcmCache(tmp_path, max_bytes=10 ** 6)
    assert pcm_cache.cached(cache, render, 'Один', 'v', 24000) == b'\x02\x00' * 10
    assert pcm_cache.cached(cache, render, 'Один', 'v', 24000) == b'\x02\x00' * 10 and calls == ['Один']
    assert pcm_cache.cached(None, render, 'Один', 'v', 24000) and calls == ['Один', 'Один']
    rows = fx.bank()[:5]
    texts = {t for r in rows for t in (pcm_cache.first_portion(r['answer']), instant.core_of(r['answer']))}
    done = pcm_cache.prerender(cache, render, rows, 'v', 24000)
    assert done == {'rendered': len(texts), 'cached': 0, 'failed': 0}
    assert pcm_cache.prerender(cache, render, rows, 'v', 24000)['cached'] == len(texts)
    assert pcm_cache.first_portion('Основная ставка НДС двадцать процентов, льготные десять и ноль.') == 'Основная ставка НДС двадцать процентов,'


def test_pcm_cache_damaged_file_is_a_miss(tmp_path):
    cache = pcm_cache.PcmCache(tmp_path, max_bytes=10 ** 6)
    cache.put('Два', 'v', 24000, b'\x00\x01' * 8)
    path = cache.path('Два', 'v', 24000)
    path.write_bytes(b'\x00')
    assert cache.get('Два', 'v', 24000) is None


def test_the_build_tool_merges_checks_and_drops_conflicts(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
    import build_instant_bank as tool
    bank = tmp_path / 'bank.json'
    bank.write_text(json.dumps(fx.bank(), ensure_ascii=False), encoding='utf-8')
    pairs = tmp_path / 'pairs.txt'
    pairs.write_text('В: Что такое осмос\nО: Совсем другой ответ.\n\nВ: Что такое тургор\nО: Давление содержимого клетки на стенку.\n', encoding='utf-8')
    material = tmp_path / 'context.md'
    material.write_text('## Клетка\n\nВ: Что такое вакуоль\nО: Полость клетки с клеточным соком.\n', encoding='utf-8')
    out = tmp_path / 'out.json'
    assert tool.main(['--out', str(out), '--bank', str(bank), '--pairs', str(pairs), '--material', str(material)]) == 0
    rows = json.loads(out.read_text(encoding='utf-8'))
    qs = {r['q']: r for r in rows}
    assert 'Что такое осмос' not in qs and qs['Что такое тургор']['trust'] == 'Д' and qs['Что такое вакуоль']['trust'] == 'М'
    assert len(rows) == len(fx.BANK) - 1 + 2 and all(r['id'] for r in rows)


# A rate changes with the day and is never answered from the bank; «курсовая работа» is a paper whose title and chapters do not change,
# and the owner's answer about it must be allowed to stand in the bank (it was dropped while the pattern was «курс\w*»).
@pytest.mark.parametrize('question', [
    'Какой курс доллара?', 'Какой курс рубля к евро?', 'Какие курсы валют в банке?',
    'Что с курсом доллара?', 'Что известно о курсе евро?', 'Какой разброс курсов в обменниках?',
])
def test_a_question_about_a_rate_is_never_in_the_bank(question):
    assert instant._changes(question)
    assert instant.clean_entry({'q': question, 'answer': 'Девяносто рублей.'}) is None


@pytest.mark.parametrize('question', [
    'Какая у тебя тема курсовой?', 'Что за курсовая, которую нужно принести?',
    'Сколько глав в курсовой работе?', 'Когда сдавать курсовую?',
    'Что писать во введении курсовой?', 'Какие курсовые работы у вас были?',
])
def test_a_question_about_the_coursework_paper_stays_in_the_bank(question):
    assert not instant._changes(question)
    row = instant.clean_entry({'q': question, 'answer': 'Содержание, введение и первая глава.'}, 'М')
    assert row is not None and row['q'] == question
    assert Instant([row], adapters=()).lookup(question, bank_only=True) is not None


def test_u30_a_lost_or_wrong_question_word_enters_the_bank_only_when_every_other_word_is_the_rows(ix):
    """U30: the ear heard «кто такое транспортный налог» / «то платит налог …» for «что такое …» / «Кто платит …»: the other words are the row's, so its answer is the ear's;
    a different question (other content words, a number, «не», a question of another kind of cause) never takes it."""
    for heard, want in (('кто такое транспортный налог', 't12'), ('то такое транспортный налог', 't12'), ('кто такое земельный налог', 't15'),
                        ('то платит налог на имущество организаций', 't04'), ('что платит налог на имущество организаций', 't04')):
        ix.reset()
        got = ix.feed(heard, 0, final=True)
        assert got and got.id == want, heard
    for heard in ('когда платит налог на имущество организаций', 'где платит налог на имущество организаций', 'почему платит налог на имущество организаций', 'кто такое водный налог', 'что такое транспортный сбор', 'кто не платит налог на имущество организаций', 'что такое транспортный налог 5',
                  'кто такое налог', 'кто такое транспортный налог на землю'):
        ix.reset()
        assert ix.feed(heard, 0, final=True) is None, heard
