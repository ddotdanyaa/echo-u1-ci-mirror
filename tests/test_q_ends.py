"""E87.1 (family question, package Q): ``search_identity.same_meaning`` took «из Москвы в Питер» and «из Питера в Москву» for one question (the same words, one transposition: the last word of the check was «at most one word out of place»),
so a search prepared on one reading could serve the other. The two ends of a road are now compared by the preposition each word stands after. The order of the call on the real ControlledMedia + NativeMediaSocket:
``tests/verify/question/test_v_E87_1.py::test_a_prefetch_prepared_for_one_reading_is_not_taken_by_the_final_of_another[another_road]``. Needs the lemmatizer (the cloud). Not run on the laptop."""
import pytest

from echo_sync.search_identity import same_meaning

ROADS = [
    ('Сколько стоит билет из Москвы в Питер', 'Сколько стоит билет из Питера в Москву'),
    ('Как доехать от вокзала до аэропорта', 'Как доехать от аэропорта до вокзала'),
    ('Сколько ехать с Арбата на Таганку', 'Сколько ехать с Таганки на Арбат'),
]


@pytest.mark.parametrize('a, b', ROADS)
def test_two_roads_over_the_same_places_are_not_one_question(a, b):
    assert not same_meaning(a, b) and not same_meaning(b, a)


@pytest.mark.parametrize('a, _b', ROADS)
def test_the_same_road_said_twice_is_one_question(a, _b):
    assert same_meaning(a, a) and same_meaning(a, a + '?')
