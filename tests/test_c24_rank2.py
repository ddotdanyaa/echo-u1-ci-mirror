"""C24-d: the ranked path read kindly (``Instant(rank2=True)``): chatter and frame words around a question are no part of it, the why-words are one kind;
the guards stay: numbers, «не», roles, the kind of the question, the word the bank never heard. A false answer is worse than a refusal."""
import json
from pathlib import Path

import pytest

from echo_sync import instant

BANK7 = Path(__file__).resolve().parents[1] / 'cloud_context' / 'bank' / 'instant_bank_7.json'

TWINS = [
    {'id': 't1', 'q': 'Когда можно менять учётную политику?', 'alt': [], 'answer': 'С начала следующего года.'},
    {'id': 't2', 'q': 'Когда нельзя менять учётную политику?', 'alt': [], 'answer': 'В течение года без причин.'},
    {'id': 't3', 'q': 'Было 80 рублей, потратил 20, сколько осталось?', 'alt': [], 'answer': 'Шестьдесят рублей.'},
    {'id': 't4', 'q': 'Было 20 рублей, потратил 80, сколько осталось?', 'alt': [], 'answer': 'Долг шестьдесят рублей.'},
    {'id': 't5', 'q': 'Что такое инфляция?', 'alt': [], 'answer': 'Устойчивое повышение уровня цен.'},
    {'id': 't6', 'q': 'Почему растёт инфляция?', 'alt': [], 'answer': 'Из-за избытка денег в обороте.'},
    {'id': 't7', 'q': 'Кто платит налог с аренды?', 'alt': [], 'answer': 'Арендодатель.'},
    {'id': 't8', 'q': 'Кому платят налог с аренды?', 'alt': [], 'answer': 'В бюджет.'},
    {'id': 't9', 'q': 'Почему бухгалтер обязан хранить документы?', 'alt': [], 'answer': 'Так требует закон о бухучёте.'},
    {'id': 't10', 'q': 'Что такое бухгалтерский учёт?', 'alt': [], 'answer': 'Система сбора информации об имуществе.'},
]


def _hit(ins, text):
    ins.reset()
    return ins.lookup(text, final=True, bank_only=True)


def _ear(ins, text):
    """The ear's way: the partials word by word, then the cut-off (tools.bank_eval.feed)."""
    from tools.bank_eval import feed
    return feed(ins, text)[0]


@pytest.fixture(scope='module')
def real():
    rows = json.load(open(BANK7, encoding='utf-8'))
    return instant.Instant(rows, adapters=(), rank=True, rank2=True)


@pytest.fixture(scope='module')
def twins():
    return instant.Instant(TWINS, adapters=(), rank=True, rank2=True)


@pytest.mark.parametrize('text,want', [
    ('Ливонская война чем закончилась-то, мы выиграли хоть', 'b01496'),
    ('почему произошёл церковный раскол, неужели из-за двух пальцев', 'b01524'),
    ('зачем Иван Грозный ввёл опричнину, он что, с ума сошёл', 'b01490'),
    ('что такое стагфляция, объясни как другу', 'b01389'),
    ('Соляной бунт из-за чего был, неужели из-за соли', 'b01516'),
])
def test_chatter_around_a_known_question_is_not_a_reason_to_refuse(real, text, want):
    hit = _hit(real, text)
    assert hit and hit.id == want


@pytest.mark.parametrize('text', [
    'Лжедмитрий этот откуда взялся и почему ему поверили',      # the bank has who he was, not where from
    'Почему после Фёдора Ивановича началась Смута?',             # the date of the end of the dynasty is no «why»
    'Годунов правда царевича убил или это наговор',              # a verb the bank never heard is not chatter
    'Какая сейчас ключевая ставка?',                              # live
])
def test_what_the_bank_does_not_say_stays_a_refusal(real, text):
    assert _hit(real, text) is None
    assert _ear(real, text) is None


def test_the_definition_is_not_given_for_a_why(twins):
    assert _hit(twins, 'Что такое инфляция?').id == 't5'
    assert _hit(twins, 'Почему растёт инфляция?').id == 't6'
    assert _hit(twins, 'Ну а почему вообще растёт инфляция, неужели из-за денег?').id == 't6'
    assert _hit(twins, 'Ну так что такое инфляция, объясни на пальцах').id == 't5'
    assert _hit(twins, 'Почему растёт инфляция, скажи в двух словах').id == 't6'
    got = _hit(twins, 'Отчего инфляция ползёт вверх')           # a why asked with another word: never the definition
    assert got is None or got.id == 't6'


def test_can_and_cannot_stay_apart(twins):
    assert _hit(twins, 'Ну когда можно менять учётную политику, в двух словах').id == 't1'
    assert _hit(twins, 'А когда нельзя менять учётную политику, на пальцах?').id == 't2'


def test_eighty_of_twenty_is_not_twenty_of_eighty(twins):
    got = _hit(twins, 'Было восемьдесят рублей потратил двадцать сколько осталось')
    assert got is None or got.id == 't3'                         # words for digits: a refusal or the right twin, never the other
    assert _hit(twins, 'Было 80 рублей, потратил 20, сколько осталось, ну?').id == 't3'
    assert _hit(twins, 'Было 20 рублей, потратил 80, сколько осталось, ну?').id == 't4'


def test_roles_stay_apart(twins):
    assert _hit(twins, 'Слушай, кто платит налог с аренды, на пальцах?').id == 't7'
    assert _hit(twins, 'Слушай, кому платят налог с аренды, на пальцах?').id == 't8'


def test_what_is_alike_is_not_what_differs(real):
    assert _hit(real, 'Чем срок окупаемости отличается от чистой приведённой стоимости?').id == 'b00912'
    assert _hit(real, 'Чем срок окупаемости похож на чистую приведённую стоимость') is None
    assert _ear(real, 'Чем срок окупаемости похож на чистую приведённую стоимость') is None


def test_a_not_is_never_chatter(twins):
    assert _hit(twins, 'Когда не нужно менять учётную политику') is None


def test_a_why_alt_of_a_date_entry_is_not_the_index_of_rank2():
    bank = [{'id': 'd1', 'q': 'Когда оборвалась династия?', 'alt': ['Почему началась Смута?'], 'answer': 'В 1598 году.'}]
    assert _hit(instant.Instant(bank, adapters=(), rank=True), 'Почему началась Смута?') is not None       # as it was
    assert _hit(instant.Instant(bank, adapters=(), rank=True, rank2=True), 'Почему началась Смута?') is None


def test_rank2_off_keeps_the_old_path():
    rows = json.load(open(BANK7, encoding='utf-8'))
    old = instant.Instant(rows, adapters=(), rank=True)
    assert _hit(old, 'почему произошёл церковный раскол, неужели из-за двух пальцев') is None


def test_the_kind_reading_is_the_rule_of_every_call():
    base = {'instant': 'on'}
    got = instant.from_settings(base)
    assert got.ranker is not None and got.rank2 is True                                     # the owner's profile had it on: no switch, no W11/F5 path "as it was"
    assert instant.from_settings(base).rank2 is True                                         # the cache holds the same index


def test_chatter_off_never_takes_a_number_or_a_not_or_a_role_out():
    import random
    rows = json.load(open(BANK7, encoding='utf-8'))
    rnd = random.Random(24)
    tails = ['', ', в двух словах', ' на пальцах', ', неужели так', ', объясни как другу', ' что ли', ', правда', ', ну', ' простыми словами']
    qs = [t for r in rnd.sample(rows, 300) for t in [r['q']] + r['alt'][:2]]
    qs += ['Не могу, что не так 80 из 20', 'Кто платит налог, а кому не платят', 'Было 20, потратил 80, сколько осталось', 'не плати 3 штуки']
    for q in qs:
        for tail in tails:
            before, after = instant._terms(q), instant._terms(instant.chatter_off(q + tail))      # «в двух словах» has a number word of its own: it goes with the chatter
            assert set(before[1]) == set(after[1]), (q, tail)                                       # numbers of the question stay
            assert before[2] == after[2], (q, tail)                                                 # «не» + the next word stay
            assert instant.qtype2(q) == instant.qtype2(instant.chatter_off(q + tail)), (q, tail)    # the kind of the question (who/whom, why, when…) stays
