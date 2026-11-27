# factory-backlog-id: U21
from tools.bank_states import completeness, right


def test_near_numbers_are_not_the_right_fact():
    assert completeness('Ставка 15 процентов', '5') == ([], ['5'])
    assert completeness('Ставка 12,5 процента', '5') == ([], ['5'])
    assert completeness('Срок 120 дней', '20 дней') == ([], ['20 дней'])
    assert right('Ставка 15 процентов', '5') is False
    assert completeness('Срок 5 дней', '5') == (['5'], [])
    assert right('Срок 5 дней', '5') is True
    assert right('Срок 20 дней', '20 дней') is True
