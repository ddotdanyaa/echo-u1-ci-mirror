"""g27-portions (wave 20): a meaning portion is a finished piece of sense.

The owner's call of 6 Nov: the first portion broke on a dash, «Статья 59 Налогового кодекса —», «Активный счёт учитывает имущество, пассивный —».
A portion that is not the last of its text never ends on a dash, a preposition, conjunction or particle, a word that needs its head, a comma
with no thought before it; «X — это Y» stays whole when it fits; a list goes item by item; a number keeps its unit; a portion holds 4-9 words;
a streamed tail is held to the end of its sense, at most TAIL_HOLD_SECONDS. The corpus checks run over every bank answer and 200 model-style
texts built from the bank (tools/portion_audit.py).
"""
from __future__ import annotations

import re

import pytest

from echo_sync import portioner as P
from echo_sync.portioner import portions, stable_prefix
from echo_sync.settings import CALL_SETTINGS, resolve
from tools import portion_audit as A

SENSE = {**CALL_SETTINGS, 'portion_sense': 'on'}      # c22-speed: g27 is behind the flag
CFG = resolve(SENSE)


def cut(text):
    return portions(text, CFG)


def _no_dash_end(parts):
    return not any(re.search(r'(?:[—–]|\s-)\W*$', p) for p in parts)


# --- the owner's call of 6 Nov -------------------------------------------------------------------------------------------------------

def test_article_does_not_end_on_dash():
    parts = cut('Статья 59 Налогового кодекса — безнадёжные долги признаются по основаниям этой статьи.')
    assert _no_dash_end(parts), parts
    assert parts[0].startswith('Статья 59 Налогового кодекса — безнадёжные'), parts


def test_active_passive_cut_at_the_comma():
    assert cut('Активный счёт учитывает имущество, пассивный — источники его образования.') == [
        'Активный счёт учитывает имущество,', 'пассивный — источники его образования.']


def test_dash_never_ends_a_portion_in_the_corpus():
    for text in [a for a, _ in A.bank_answers()] + A.model_texts():
        assert _no_dash_end(cut(text)[:-1]), (text, cut(text))


# --- «X — это Y» whole; a bound with its number; a correlative with its clause; 4-9 words ---------------------------------------------

def test_definition_that_fits_nine_words_is_one_portion_even_over_the_syllables():
    assert cut('Налоговая декларация — это письменное заявление налогоплательщика. Или заявление в электронной форме.') == [
        'Налоговая декларация — это письменное заявление налогоплательщика.', 'Или заявление в электронной форме.']


def test_definition_is_not_split_at_its_colon_into_a_three_word_tail():
    assert cut('Пассивный счёт — это счёт источников: остаток по кредиту.') == ['Пассивный счёт — это счёт источников: остаток по кредиту.']


def test_long_definition_never_ends_on_eto_or_on_a_bound():
    parts = cut('Налоговый резидент по НДФЛ — это не менее 183 дней в России.')
    assert not any(re.search(r'\b(?:это|менее|не)\W*$', p) for p in parts[:-1]), parts
    assert any('не менее 183 дней' in p for p in parts), parts


def test_correlative_keeps_its_clause():
    for text in ('Взаимозависимы и те, кто связан подчинением по должности или семейными отношениями.',
                 'Также госпошлину, кроме той, по которой арбитражный суд выдал исполнительный документ, возвращают.',
                 'Различие в том, где они обязательны к уплате и кто их устанавливает.'):
        parts = cut(text)
        assert not any(re.search(r'\b(?:те|той|том),$', p) for p in parts), parts


def test_a_three_word_tail_with_a_preposition_beats_tearing_an_adverb_from_its_adjective():
    assert cut('Налог — обязательный, индивидуально безвозмездный платёж для финансирования государства.') == [
        'Налог — обязательный, индивидуально безвозмездный платёж', 'для финансирования государства.']


@pytest.fixture(scope='module')
def corpus():
    return [a for a, _ in A.bank_answers()] + A.model_texts()


def test_corpus_has_the_bank_and_200_model_texts(corpus):
    assert len(A.model_texts()) == 200 and len(corpus) >= 1300


def test_corpus_no_dash_function_word_copula_unit_or_correlative_end(corpus):
    bad = [(k, p, t) for t in corpus for k, _, p in A.problems(t, CFG) if k != 'short']
    assert bad == [], bad[:5]


def test_corpus_portions_hold_four_to_nine_words(corpus):
    total = short = 0
    for t in corpus:
        total += len(cut(t))
        short += sum(k == 'short' for k, _, _ in A.problems(t, CFG))
        assert all(len(P.WORDS.findall(p)) <= CFG['max_words'] for p in cut(t)), cut(t)
    assert short <= 0.025 * total, (short, total)


# --- a list goes item by item ---------------------------------------------------------------------------------------------------

def test_numbered_items_keep_their_marks():
    assert cut('Основные моменты: 1) микропредприятиям и некоммерческим организациям; 2) такие организации; 3) если вправе применять '
               'упрощённые способы учёта.') == ['Основные моменты: 1) микропредприятиям и некоммерческим организациям;', '2) такие организации;',
                                                '3) если вправе применять упрощённые способы учёта.']


def test_word_items_keep_their_marks():
    assert cut('Во-первых, налог на доходы физических лиц; во-вторых, это федеральный налог главы 23 Налогового кодекса; '
               'в-третьих, его объект — доход.') == ['Во-первых, налог на доходы физических лиц;',
                                                     'во-вторых, это федеральный налог главы 23 Налогового кодекса;', 'в-третьих, его объект — доход.']


def test_items_are_cut_between_items():
    parts = cut('Есть три пункта. Во-первых, налог обязателен; во-вторых, он индивидуально безвозмездный; в-третьих, его платят деньгами.')
    assert parts == ['Есть три пункта.', 'Во-первых, налог обязателен;', 'во-вторых, он индивидуально безвозмездный;', 'в-третьих, его платят деньгами.']


def test_line_items_with_a_full_stop():
    parts = cut('Виды документов:\n1. Первичные учётные документы.\n2. Сводные учётные документы.\n3. Регистры бухгалтерского учёта.')
    assert all(not re.search(r'(?:^|\s)\d\.$', p) for p in parts), parts
    assert sum(bool(re.match(r'\d\. ', p)) for p in parts) == 3, parts


# --- a number with its unit, its bound, its smaller unit ----------------------------------------------------------------------------

@pytest.mark.parametrize('text, whole', [
    ('Взносы платят ежемесячно не позднее 28-го числа следующего месяца, по единому тарифу 30 процентов в пределах базы.', 'не позднее 28-го числа'),
    ('Сумма НДС к уплате составила 1 250 000 рублей 50 копеек за третий квартал 2026 года по данным налоговой декларации.', '1 250 000 рублей 50 копеек'),
    ('Уставный капитал общества с ограниченной ответственностью должен быть не менее 10 000 рублей на дату регистрации общества.', 'не менее 10 000 рублей'),
    ('Скорость звука в воздухе при температуре 20 °C составляет примерно 343 метра в секунду, а в воде около 1500 м/с.', 'примерно 343 метра в секунду'),
    ('Срок камеральной проверки составляет 3 месяца со дня представления декларации, а выездной — 2 месяца с возможностью продления до 6 месяцев.', 'до 6 месяцев'),
    ('Курс доллара вырос на 2,5 % за неделю, а цена нефти марки Brent поднялась до 85 долларов за баррель.', '2,5 %'),
    ('Пенсионный фонд получает 22 процента до предельной базы и 10 процентов сверх неё, а ФСС получает 2,9 процента.', '2,9 процента'),
])
def test_number_stays_with_its_unit_and_bound(text, whole):
    parts = cut(text)
    assert any(whole in p for p in parts), parts
    assert not any(k == 'unit' for k, _, _ in A.problems(text, CFG)), parts


# --- the stream: the first cue and stable_prefix never let go a piece that hangs -------------------------------------------------

def _streamed_cue(text, question=''):
    from echo_sync.first_useful import first_cue
    for k in range(1, len(text) + 1):
        cue = first_cue(text[:k], question, SENSE, final=k == len(text), last=k == len(text))
        if cue:
            return cue


@pytest.mark.parametrize('text', [
    'Статья 59 Налогового кодекса — безнадёжные долги признаются по основаниям этой статьи.',
    'Единый тариф регулирует Кодекс, травматизм — отдельный федеральный закон о страховании.',
    'Активный счёт учитывает имущество, пассивный — источники его образования.',
])
def test_streamed_first_cue_never_ends_on_a_dash(text):
    cue = _streamed_cue(text, 'расскажи')
    assert cue and not re.search(r'[—–]\W*$', cue), cue


@pytest.mark.parametrize('arrived, never', [
    ('Налог на прибыль организаций — ', '—'), ('Ставки указаны в статьях 13– ', '13'), ('Прочие доходы это, ', 'это'),
    ('Права у налогового агента те же, ', 'же'), ('Счёт 91 в рабочем плане счетов — «', '«'), ('Основные моменты: 1) ', '1)'),
])
def test_stable_prefix_holds_a_hanging_end(arrived, never):
    for eager in (False, True):
        for starving in (False, True):
            got = stable_prefix(arrived, CFG, eager=eager, starving=starving)
            assert not got.rstrip().endswith(never), (arrived, eager, starving, got)


def test_starving_lets_go_up_to_the_last_word_that_does_not_hang():
    assert stable_prefix('Налоговая база по налогу на прибыль определяется как — ', CFG, starving=True) == \
        'Налоговая база по налогу на прибыль определяется'


def test_corpus_stream_never_lets_go_a_hanging_piece(corpus):
    rows = A.bank_answers() + [(t, '') for t in A.model_texts()]
    counts, examples = A.stream_audit(rows, seeds=1, cfg=CFG)
    assert not counts, dict(examples)


# --- more hanging ends: «т. е.», «X, а не Y», «НДС, — это» -------------------------------------------------------------------------

def test_abbreviated_conjunction_is_never_the_end():
    parts = cut('Хозяйственные операции отражаются методом двойной записи, т. е. одновременно по дебету одного и кредиту другого счёта.')
    assert not any(re.search(r'\bт\. ?[ек]\.$', p) for p in parts), parts
    assert cut('Это касса, банк, расчёты и т. д. Дальше идут счета капитала.') == ['Это касса, банк, расчёты и т. д.', 'Дальше идут счета капитала.']


def test_elliptic_contrast_stays_with_what_it_contrasts():
    parts = cut('Пассивный счёт отражает источники, а не имущество, поэтому сальдо у него всегда кредитовое и никогда не дебетовое.')
    assert parts[0] == 'Пассивный счёт отражает источники, а не имущество,', parts
    # a contrast with a predicate of its own is a clause of its own (F1 frontier test)
    assert stable_prefix('Короткое плечо даёт выигрыш в пути, но не даёт выигрыша в работе и', CFG, eager=True) == 'Короткое плечо даёт выигрыш в пути,'


def test_a_comma_and_a_dash_before_eto_still_hold_the_definition():
    parts = cut('Налог на добавленную стоимость, или НДС, — это косвенный налог, который включается в цену товаров, работ и услуг.')
    assert not any(re.match(r'(?:— )?это\b', p) for p in parts), parts


def test_a_dash_is_a_cheaper_cut_than_an_adjective_torn_from_its_noun():
    # the reference answer of article 17 (reference_kb): 10 words, one cut; «— общие | условия» tore the adjective from its noun
    assert cut('Статья 17 Налогового кодекса — общие условия установления налогов и сборов.') == [
        'Статья 17 Налогового кодекса', '— общие условия установления налогов и сборов.']
