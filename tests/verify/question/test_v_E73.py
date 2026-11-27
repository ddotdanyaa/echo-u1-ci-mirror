"""V2 E73: the judgments «by words» read the whole utterance, not the question: «сейчас» in the preface gave ``no_source_current_data`` and a false «Не нашёл» after 0.2 s (call 10:27, 194.3). Fixed on H7 item 0b (1214bbb).

Real ControlledMedia (rig ``call``, the profile of the call of 10:27). The control keeps the other side: data that really changes is still «not found» without a source. Not run on the laptop.
"""
import logging

import pytest

from question_kit import CALL_1027, SAID_15, TICK, asked, call, decisions, job_answers, job_text, said_with_a_delegation, spoken_failures      # noqa: F401 - call is the fixture

PREFACES = [
    ('s15_of_the_call', SAID_15, 'пятнадцатый счёт', 'Счёт 15 — заготовление и приобретение материалов.'),
    ('now_in_the_preface', 'Вот сейчас идёт вторая минута, так, значит, что такое амортизация основных средств ? 20 секунд', 'амортизац', 'Амортизация — перенос стоимости основных средств на расходы.'),
    ('today_in_the_preface', 'Сегодня мы повторяем тему, ну вот, давайте так, что такое дебет и кредит ? 15 секунд', 'дебет', 'Дебет — левая сторона счёта, кредит — правая.'),
]


@pytest.mark.parametrize('name, said, key, answer', PREFACES, ids=[row[0] for row in PREFACES])
def test_a_word_of_the_present_in_the_preface_gets_the_question_an_answer_not_a_false_refusal(call, caplog, name, said, key, answer):
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    said_with_a_delegation(rig, 'u1', said)
    rig.pump(TICK * 4)
    if name == 's15_of_the_call':      # the reference base answers «счёт 15» from the ear (local_reference): no job, and the answer is spoken
        assert 'заготовление' in ' '.join(rig.said()), rig.said()
        assert not decisions(caplog, 'no_source_current_data') and not decisions(caplog, 'personal_unanswerable')
        return
    assert rig.fast.count >= 1, f'{name}: no job was asked'
    job_answers(rig, 0, answer)
    rig.pump(1.0)
    assert not decisions(caplog, 'no_source_current_data') and not decisions(caplog, 'personal_unanswerable'), 'the preface made the question «current» or «personal»'
    assert answer in rig.said() and not spoken_failures(rig), rig.said()
    assert key in job_text(rig, 0).lower() or key in str(rig.fake.run(0).request).lower(), 'the job got the words of the question'


@pytest.mark.parametrize('question', ['Какой курс доллара сейчас', 'Какая сегодня погода в Москве', 'Сколько сейчас стоит нефть'])
def test_data_that_really_changes_is_still_not_found_without_a_source(call, monkeypatch, question):
    rig = call(**CALL_1027)
    monkeypatch.setattr(rig.w, '_lookup', None, raising=False)
    asked(rig, question)
    rig.pump(0.5)
    assert rig.c.direct_content is False, 'not answered from memory'
