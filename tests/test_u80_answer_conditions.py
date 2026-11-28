"""U80 (audit points 52, 56, 60): the answer is held against the conditions of its question before it is released. The probe only REPORTS (answer_conditions.broken); the owner of the answer
(``ControlledMedia._bind_answer``) writes the feature to the log and the call trace and the answer is still released: a rule with no model cannot know the right one, it can tell the broken condition.
Words are invented. REAL: ControlledMedia, EchoEngine, the classifier. EMULATED: the cloud (the wire events)."""
import logging

import pytest

from helpers_w1f import Wire


@pytest.fixture(autouse=True)
def info_log(caplog):
    caplog.set_level(logging.INFO)


def noted(caplog):
    return [r.getMessage() for r in caplog.records if 'answer_condition' in r.getMessage()]


def ask(tmp_path, question, answer):
    w = Wire(tmp_path)
    w.user('u1', question, 0.0, 2.0)
    w.assistant('a1', answer, 2.05, 2.8)
    w.until(3.5)
    return w


def test_a_bare_number_to_a_question_in_percent_is_reported_and_still_said(tmp_path, caplog):
    w = ask(tmp_path, 'Какую долю составляет четверть от целого, в процентах?', ' Двадцать пять.')
    assert w.played_after(0) and 'Двадцать пять' in w.played_after(0)[0]      # released as before
    rows = noted(caplog)
    assert len(rows) == 1 and 'unit' in rows[0], rows


def test_the_unit_given_is_no_report(tmp_path, caplog):
    ask(tmp_path, 'Какую долю составляет четверть от целого, в процентах?', ' Двадцать пять процентов.')
    assert noted(caplog) == []


@pytest.mark.parametrize('question, answer, names', [
    ('Какую долю составляет четверть, в процентах?', 'Двадцать пять.', ['unit']),
    ('Какую долю составляет четверть, в процентах?', 'Двадцать пять процентов.', []),
    ('Какую долю составляет четверть, в процентах?', '25%', []),
    ('Сколько это в рублях?', '25 руб.', []),
    ('Сколько это в рублях?', 'Двести рублей.', []),
    ('Сколько это в рублях?', 'Двести.', ['unit']),
    ('Сколько это в рублях?', 'Точно не знаю.', []),                 # no number: no unit is missing
    ('В каких единицах измеряют давление?', 'Паскаль.', []),
    ('В каких единицах измеряют длину?', 'Сто.', ['unit']),
    ('Назови планеты кроме Земли', 'Марс и Венера.', []),
    ('Назови планеты кроме Земли', 'Марс, Венера и Земля.', ['except']),
    ('Назови планеты кроме Земли', 'Марс, Земля не входит.', []),
    ('Сколько жителей было в 2019 году?', 'В 2021 году сто сорок миллионов, 2021.', ['period']),
    ('Сколько жителей было в 2019 году?', 'В 2019 году 140 миллионов.', []),
    ('Когда в 2019 году прошёл матч?', 'В 2021 году.', []),         # «когда»: another year is the answer
    ('', 'Двадцать.', []),
])
def test_the_probe_names_only_a_plainly_broken_condition(question, answer, names):
    from echo_sync.answer_conditions import broken
    assert broken(question, answer) == names


def test_the_report_goes_to_the_trace_and_never_raises():
    from echo_sync.answer_conditions import report
    seen = []
    assert report('Сколько это в рублях?', 'Двести.', lambda line, **kw: seen.append((line, kw))) == ['unit']
    assert seen == [('answer_condition', {'broken': 'unit'})]
    assert report('Сколько это в рублях?', 'Двести.', lambda *a, **kw: 1 / 0) == ['unit']      # a failing trace is no failure of the call
