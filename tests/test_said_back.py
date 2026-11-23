"""The owner's call of 06.11 (65f46fe91e81, on the phone): the owner said a cue back, the cloud glued it to the question or to the cue before it, the job answered that as a question and the same cue went round."""
import pytest

from echo_sync.classifier import strip_fillers
from echo_sync.fast_text import adds_nothing, ends_like, most_said
from echo_sync.settings import CALL_SETTINGS


def strip(text):
    return strip_fillers(text, CALL_SETTINGS)


@pytest.mark.parametrize('heard,said', [
    ('Так, 51 счёт в плане счетов Счет 51, расчетные счета', ['так пятьдесят первый счёт в плане счетов', 'Счёт 51 — расчётные счета.']),
    ('Счёт 51 - расчетные счета', ['Счёт 51 — расчётные счета.']),
    ('Приходный кассовый ордер Документ, по которому принимают наличные деньги в кассу', ['ПКО КО-1 — приходный кассовый ордер,', 'Документ, по которому принимают наличные деньги в кассу.']),
    ('Значит КО-1 это приходный ордер, в который деньги принимают, для себя берет', ['КО-1 — приходный ордер, принимает деньги;', 'Разница между КО-1 и КО-2']),
    ('Ну, простыми словами, КО-1 принимает деньги в кассу. КО-1 принимает деньги в кассу', ['КО-1 принимает деньги в кассу,']),
])
def test_said_back(heard, said):
    assert adds_nothing(heard, said, strip=strip)


@pytest.mark.parametrize('heard,said', [
    ('Счет 51 — расчетные счета, а счет 58', ['Счёт 51 — расчётные счета.']),
    ('А РКО. Документ, по которому принимают наличные деньги в кассу', ['Документ, по которому принимают наличные деньги в кассу.']),
    ('Испытательный срок для главного бухгалтера', ['Счёт 51 — расчётные счета.']),
    ('Налог на прибыль двадцать пять процентов', ['Налог на прибыль двадцать процентов']),
    ('Не принимает деньги в кассу', ['Принимает деньги в кассу']),
    ('Срок камеральной проверки', ['Срок выездной проверки два месяца']),
])
def test_something_new(heard, said):
    assert not adds_nothing(heard, said, strip=strip)


@pytest.mark.parametrize('heard,portion', [
    ('шестьдесят девять расчёты', 'Счёт 69 — расчёты'),
    ('указание банка тридцать два десять', 'Указание Банка России 3210-У'),
    ('счёт пятьдесят два валютные', 'Счёт 52 — «Валютные счета», активный.'),
])
def test_most_said(heard, portion):
    assert most_said(heard, portion)


@pytest.mark.parametrize('heard,portion', [
    ('налог двадцать пять процентов', 'Налог двадцать процентов'),
    ('счёт', 'Счёт 69 — расчёты с бюджетом по налогам'),
    ('совсем другое слово', 'Счёт 69 — расчёты'),
    ('общие условия установления взносов и сборов', 'общие условия установления налогов и сборов.'),
])
def test_not_most_said(heard, portion):
    assert not most_said(heard, portion)


@pytest.mark.parametrize('text', ['а подробней пятьдесят первый счёт', 'подробнее про пятьдесят первый счёт', 'а подробнее'])
def test_more_detail_is_a_question(text):
    from echo_sync.classifier import analyze, QUESTION
    assert analyze(text, None, [], CALL_SETTINGS).kind == QUESTION


def test_more_detail_is_no_line_of_the_reference():
    from echo_sync.controlled_media import MORE_DETAIL
    assert MORE_DETAIL.search('что значит подробнее про пятьдесят первый счёт') and MORE_DETAIL.search('Расскажи поподробнее') and not MORE_DETAIL.search('счёт пятьдесят один')


@pytest.mark.parametrize('heard,portion', [
    ('своими словами это вложения финансовые активный счёт', 'Счёт 58 «Финансовые вложения» — активный счёт.'),
    ('ну значит деньги на счетах приобретение активов', 'Дебет показывает приобретение активов,'),
    ('операции записывают на двух счетах', 'Запись операции на двух счетах:'),
])
def test_the_end_of_the_portion_closes_it(heard, portion):
    assert ends_like(heard, portion)


@pytest.mark.parametrize('heard,portion', [
    ('налог двадцать пять процентов на прибыль', 'Налог двадцать процентов на прибыль'),
    ('не облагается налогом на прибыль', 'Облагается налогом на прибыль'),
    ('общие условия установления взносов и сборов', 'общие условия установления налогов'),
])
def test_a_change_is_no_end(heard, portion):
    assert not ends_like(heard, portion)


@pytest.mark.parametrize('heard,portion', [
    ('приходный кассовый ордер то есть наоборот', 'Приходный кассовый ордер, документ кассы,'),
    ('ой расходный кассовый ордер форма ко два', 'Расходный кассовый ордер, форма КО-2,'),
])
def test_own_words_around_the_portion(heard, portion):
    assert most_said(heard, portion)


@pytest.mark.parametrize('heard,said', [
    ('ответственностью', ['Организация со своим имуществом и ответственностью']),
    ('расчётные счета', ['Счёт 51 — расчётные счета.']),
])
def test_a_piece_of_the_cue_says_nothing_new(heard, said):
    assert adds_nothing(heard, said, strip=strip)


def test_a_new_word_alone_is_new():
    assert not adds_nothing('амортизация', ['Организация со своим имуществом'], strip=strip)


def test_no_method_of_the_controller_is_written_twice():
    """The merge of 06.11: a second ``_candidate_asks(candidate)`` shadowed the first, ``first_cue_hold`` raised and the ear's tempo went off for the call."""
    import ast
    import pathlib
    import collections
    from cm_patch import controller_modules
    for module in controller_modules():
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                names = collections.Counter(item.name for item in node.body if isinstance(item, ast.FunctionDef) and not item.decorator_list)
                assert [name for name, count in names.items() if count > 1] == []


def test_a_number_said_in_two_breaths_reads_out_the_portion():
    from echo_sync.fast_text import reads_out
    assert reads_out('двадцать два процента основная ставка', '22 процента — основная ставка НДС')
    assert not reads_out('двадцать пять процентов', '22 процента — основная ставка НДС')
