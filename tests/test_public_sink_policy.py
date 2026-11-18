"""Synthetic-only tests for the actual production public network authorization."""
from types import SimpleNamespace as NS

import pytest

from public_sink_policy_slice import ControllerPolicy, lookup_publicly_permitted


def controller(raw="Что такое инерция?", question="", *, question_id=None, origin=None, valid=True):
    latest = None if raw is None else {"text": raw, "valid": valid}
    originals = {} if question_id is None else {
        question_id: {"text": origin if origin is not None else raw, "valid": valid}
    }
    c = ControllerPolicy()
    c.ledger = NS(latest_user=lambda: latest, snapshot=originals.get)
    c.question_id = question_id
    c.question_text = question
    return c


@pytest.mark.parametrize("query", [
    "Что такое инерция?",
    "Сколько будет два плюс два?",
    "Когда произошла битва?",
])
def test_public_question_with_live_origin_is_allowed(query):
    assert lookup_publicly_permitted(controller(raw=query), query)


@pytest.mark.parametrize("original", [
    "Лена, что такое инерция?",
    "Лена объясни что такое инерция",
    "Миша, проверь запись. Что такое инерция?",
])
def test_named_person_source_not_published_as_safe_extracted_question(original):
    c = controller(raw=original)
    assert not lookup_publicly_permitted(c, "Что такое инерция?")


def test_public_lookup_does_not_publish_own_personal_question():
    c = controller(raw="Какой мой пароль от аккаунта?")
    assert not lookup_publicly_permitted(c, "Какой мой пароль от аккаунта?")


@pytest.mark.parametrize("question", [
    "Лена, что такое инерция?",
    "Лена, проверь запись. Что такое инерция?",
])
def test_original_question_field_remains_authoritative(question):
    c = controller(raw="Что такое инерция?", question=question)
    assert not lookup_publicly_permitted(c, "Что такое инерция?")


def test_unattached_query_with_no_user_or_question_is_rejected():
    c = controller(raw=None, question="")
    assert not lookup_publicly_permitted(c, "Что такое инерция?")


def test_empty_open_transcript_with_no_question_is_rejected():
    c = controller(raw="", question="")
    assert not lookup_publicly_permitted(c, "Что такое инерция?")


def test_invalid_user_transcript_is_rejected():
    c = controller(raw="Что такое инерция?", valid=False)
    assert not lookup_publicly_permitted(c, "Что такое инерция?")


def test_open_question_origin_is_checked_not_only_the_latest_speaker():
    c = controller(raw="Что такое инерция?", question="Что такое инерция?", question_id="u1",
                   origin="Лена, что такое инерция?")
    assert not lookup_publicly_permitted(c, "Что такое инерция?")


def test_confirmed_good_origin_still_allows_lookup():
    c = controller(raw="Что такое инерция?", question="Что такое инерция?", question_id="u1",
                   origin="Что такое инерция?")
    assert lookup_publicly_permitted(c, "Что такое инерция?")
