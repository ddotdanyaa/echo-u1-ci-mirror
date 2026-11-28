"""U15-S3: ``meaning_guard`` tri-state over pairs; a pure function, nothing is wired to it."""
import pytest
from echo_sync.fast_text import meaning_guard
from echo_sync.utterance_judge import DIFFERS, SAME, UNKNOWN, UNKNOWN_POLICY, VERDICTS

PAIRS = [
    # numbers
    ('статья 17 кодекса', 'статья 18 кодекса', DIFFERS),
    ('срок сорок восемь часов', 'срок 24 часа', DIFFERS),
    ('налог 20 процентов', 'налог 10 процентов', DIFFERS),
    ('штраф 5000 рублей', 'штраф 50000 рублей', DIFFERS),
    # negation
    ('не нагревать а охлаждать', 'нагревать а не охлаждать', DIFFERS),
    ('можно не платить налог', 'можно платить налог', UNKNOWN),
    ('налог не облагается', 'налог облагается', UNKNOWN),
    # unit
    ('штраф 80 рублей', 'штраф 80 долларов', DIFFERS),
    ('нагрев до 100 градусов', 'нагрев до 100 процентов', DIFFERS),
    # roles
    ('было 80 потратил 20', 'было 20 потратил 80', DIFFERS),
    ('от Москвы до Питера', 'от Питера до Москвы', DIFFERS),
    ('кто убил Каина', 'кого убил Каин', DIFFERS),
    # kind of question
    ('сколько стоит билет', 'когда стоит билет', DIFFERS),
    ('где находится банк', 'почему находится банк', DIFFERS),
    ('кто подписывает договор', 'что подписывает договор', DIFFERS),
    # object
    ('как открыть расчетный счет', 'как закрыть расчетный счет', DIFFERS),
    ('сколько стоит патент', 'сколько стоит лицензия', DIFFERS),
    # a dropped atom
    ('статья 17 кодекса', 'статья кодекса', UNKNOWN),
    ('срок подачи 30 апреля', 'срок подачи апреля', UNKNOWN),
    ('сколько стоит патент на работу', 'сколько стоит патент', UNKNOWN),
    ('сколько стоит билет', 'стоит билет', UNKNOWN),
    ('', 'сколько стоит билет', UNKNOWN),
    # fillers
    ('ну сколько стоит билет', 'сколько стоит билет', SAME),
    ('э-э сколько стоит билет', 'сколько стоит билет', SAME),
    ('вот как открыть счет', 'как открыть счет', SAME),
    ('статья 17 кодекса', 'статья семнадцать кодекса', SAME),
    ('сколько стоит билет', 'Сколько стоит билет?', SAME),
    ('штраф 80 рублей', 'штраф 80 ₽', SAME),
    ('какой срок подачи декларации', 'какой срок подачи декларации', SAME),
    ('не позднее 25 марта', 'не позднее 25 марта', SAME),
    ('нужно ли платить налог', 'нужно платить налог ли', SAME),
]


@pytest.mark.parametrize('left,right,verdict', PAIRS)
def test_pairs(left, right, verdict):
    assert meaning_guard(left, right) == verdict
    if verdict != UNKNOWN or not left:
        assert meaning_guard(right, left) == verdict


def test_vocabulary():
    assert set(VERDICTS) == {SAME, DIFFERS, UNKNOWN}
    assert UNKNOWN_POLICY == 'keep_and_log'


def test_garbage_is_unknown():
    assert meaning_guard(None, None) == UNKNOWN
    assert meaning_guard(object(), 'x') == UNKNOWN
