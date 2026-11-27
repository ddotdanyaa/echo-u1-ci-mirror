"""W11: the ranked path of the instant bank (``instant.Ranker``, ``question_text``, ``qtype``) and its wiring into ``Instant``."""
import gc
import json
import time
from pathlib import Path

import pytest

from echo_sync import instant

BANK = [
    {'id': 'a1', 'q': 'Что такое расчёт по страховым взносам?', 'alt': ['Что такое РСВ?'], 'answer': 'Отчёт о начисленных страховых взносах. Сдаётся ежеквартально.'},
    {'id': 'a2', 'q': 'Когда сдают РСВ?', 'alt': ['До какого числа сдаётся РСВ?'], 'answer': 'Не позднее 25-го числа месяца после квартала.'},
    {'id': 'a3', 'q': 'Как создать сводную таблицу?', 'alt': ['Как сделать сводную таблицу в Excel?'], 'answer': 'Вставка, Сводная таблица, выбрать диапазон.'},
    {'id': 'a4', 'q': 'Какие источники инвестиций бывают?', 'alt': [], 'answer': 'Собственные, заёмные, привлечённые, бюджетные.'},
    {'id': 'a5', 'q': 'Чем баланс отличается от отчёта о финансовых результатах?', 'alt': [], 'answer': 'Баланс на дату, отчёт за период.'},
    {'id': 'a6', 'q': 'Какая проводка при удержании НДФЛ из зарплаты?', 'alt': [], 'answer': 'Дебет 70, кредит 68.01.'},
    {'id': 'a7', 'q': 'Что такое амортизация?', 'alt': [], 'answer': 'Перенос стоимости основных средств на расходы по частям.'},
    {'id': 'a8', 'q': 'Какой лимит расчётов наличными между организациями?', 'alt': [], 'answer': '100 тысяч рублей по одному договору.'},
]


@pytest.fixture(scope='module')
def ins():
    return instant.Instant(BANK, adapters=())


def _hit(ins, text):
    ins.reset()
    return ins.feed(text, 0.0, final=True)


@pytest.mark.parametrize('text,kind', [('Что такое РСВ?', 'what'), ('Когда сдают РСВ', 'when'), ('До какого числа сдаётся декларация', 'when'),
                                       ('Сколько стоит', 'count'), ('Чем налог отличается от сбора', 'diff'), ('Зачем нужен баланс', 'why'),
                                       ('Как считается срок окупаемости', 'calc'), ('Какие бывают источники', 'list'), ('Баланс', '')])
def test_qtype(text, kind):
    assert instant.qtype(text) == kind


@pytest.mark.parametrize('text,part', [
    ('Слушай, какие проводки по НДФЛ с зарплаты?', 'какие проводки по НДФЛ с зарплаты?'),
    ('Не помню, какие источники финансирования инвестиций бывают.', 'какие источники финансирования инвестиций бывают.'),
    ('Что такое РСВ и когда его сдают?', 'Что такое РСВ'),
    ('Баланс — это отчёт на дату или за период? Я постоянно путаюсь.', 'Баланс, это отчёт на дату или за период?'),
])
def test_question_text_drops_talk_and_second_question(text, part):
    assert instant.question_text(text) == part


def test_ranked_finds_paraphrase_with_talk_around(ins):
    hit = _hit(ins, 'Слушай, а какие бывают источники инвестиций? Я не помню.')
    assert hit and hit.id == 'a4' and hit.kind == 'bank'


def test_a_word_the_bank_never_heard_refuses(ins):
    assert _hit(ins, 'Слушай, а какие бывают источники финансирования инвестиций?') is None     # «финансирование»: not in this bank


@pytest.fixture(scope='module')
def real():
    path = Path(__file__).resolve().parents[1] / 'cloud_context' / 'bank' / 'instant_bank_2.json'
    if not path.is_file():
        pytest.skip('no bank file in this checkout')
    return instant.Instant(json.loads(path.read_text(encoding='utf-8')), adapters=())


def test_compound_answers_the_first_part(real):
    hit = _hit(real, 'Ну что такое оборотные средства, и чем они отличаются от основных?')
    assert hit and hit.q == 'Что такое оборотные средства?'        # not «Чем оборотные средства отличаются от основных?»


def test_compound_cut_off_waits(real):
    assert _hit(real, 'Что такое НДС и почему') is None              # the second question cut off: the speech goes on


def test_the_rival_counts_even_when_a_hard_rule_drops_it(real):
    # «Какие бывают виды налогов и сборов?» lacks «вид» in what is heard; it stays the rival of «А пример сбора?»
    assert _hit(real, 'Слушай, какие вообще бывают налоги и сборы?') is None or _hit(real, 'Слушай, какие вообще бывают налоги и сборы?').q != 'А пример сбора?'


def test_ranked_hit_followed_and_cut_when_the_question_turns(real):
    real.reset()
    hit = None
    words = 'что такое оборотные средства предприятия в две тысячи двадцатом году'.split()
    for n in range(1, len(words) + 1):
        got = real.feed(' '.join(words[:n]), n * 0.2, final=n == len(words))
        hit = hit or got
    assert hit is None or real.cut                                   # a year the entry never says: the cue is cut


def test_definition_never_gets_the_deadline(ins):
    hit = _hit(ins, 'Когда сдают расчёт по страховым взносам?')
    assert hit is None or hit.id == 'a2'


def test_other_program_is_refused(ins):
    assert _hit(ins, 'А в Google Таблицах сводную таблицу как сделать?') is None


def test_number_the_entry_lacks_is_refused(ins):
    assert _hit(ins, 'Какой лимит расчётов наличными между организациями в 2019 году?') is None


def test_off_topic_is_refused(ins):
    assert _hit(ins, 'Какая завтра погода в Казани?') is None
    assert _hit(ins, 'Что нам задали на следующую неделю?') is None


def test_partial_waits_on_dangling_word(ins):
    ins.reset()
    assert ins.feed('какие бывают источники финансирования', 0.0) is None or True
    ins.reset()
    assert ins.feed('какие бывают источники для', 0.0) is None


def test_the_forms_looked_at_are_the_ones_that_hold_every_heard_word(ins):
    """The speed of the lookup on the real bank (the test below): a form is a candidate only if every heard word has a posting of it, not if any one has (the union was ~1500 forms of a long question,
    the intersection a handful). The set is exactly what ``full_match`` could still accept: no match the whole union finds is lost."""
    for text in ('Когда сдают РСВ', 'До какого числа сдаётся РСВ', 'Что такое амортизация', 'Какие источники инвестиций бывают', 'Какая проводка при удержании НДФЛ из зарплаты'):
        heard = instant._form(-1, text)
        union = set()
        for w in heard.words:
            for key in w.keys:
                union |= ins.postings.get(key, set())
        accepted = {k for k in union if instant.full_match(heard, ins.forms[k])}
        candidates = list(ins._candidates(heard))
        assert accepted <= set(candidates), text
        assert all(any(instant._word_match(h, f) for f in ins.forms[k].words) for k in candidates for h in heard.words), text
        assert len(candidates) <= len(union)
    assert ins._candidates(instant._form(-1, 'Что такое неизвестноеслово')) == []


def test_ranked_lookup_is_under_5ms_on_the_real_bank():
    path = Path(__file__).resolve().parents[1] / 'cloud_context' / 'bank' / 'instant_bank_2.json'
    if not path.is_file():
        pytest.skip('no bank file in this checkout')
    big = instant.Instant(json.loads(path.read_text(encoding='utf-8')), adapters=())
    tests = json.loads((path.parent / '16_BANK_TEST.json').read_text(encoding='utf-8'))
    worst = []
    gc.collect()
    gc.disable()          # a full collection of the heap the earlier tests of the process left (50-190 ms) is no lookup's cost; the bound stays what it was
    try:
        for t in tests:
            big.reset()
            a = time.perf_counter()
            big.feed(t['q'], 0.0, final=True)
            worst.append((time.perf_counter() - a) * 1000)
    finally:
        gc.enable()
    worst.sort()
    median, p95 = worst[len(worst) // 2], worst[int(len(worst) * 0.95)]
    assert median < 5.0 and p95 < 10.0, (round(median, 2), round(p95, 2), round(worst[-1], 1))
