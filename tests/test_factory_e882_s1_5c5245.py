# factory-backlog-id: E882.s1
from echo_sync.user_intents import disagreement


def test_synonym_of_wrong_is_dissent_with_impersonal_subject():
    assert disagreement('это некорректно') == (True, None)
    assert disagreement('это ложно') == (True, None)


def test_synonym_after_opener_is_dissent():
    assert disagreement('нет некорректно') == (True, None)


def test_synonym_with_what_is_wrong_after_it():
    assert disagreement('это некорректно там 360') == (False, 'там 360')
