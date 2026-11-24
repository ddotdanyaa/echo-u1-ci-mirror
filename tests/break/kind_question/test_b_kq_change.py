"""BREAK kind_question 2: the question changes on the fly. The listener turns to another question while the first job still talks; he corrects a number; two forms that differ by the order of the numbers.
Class of problem: К8 (the answer replaced under the speaker), A2 of the stand (the older answer said for a newer question). Real ControlledMedia, not run on the laptop."""
from break_kit import AMORT, LIVE_RULES, LONG_ANSWER, LONG_ASKED, answered, asked, call, heard, job_input, late, user_turn    # noqa: F401 - call is the fixture

MONEY = 'Если у меня было 80 рублей и я потратил 20 рублей, сколько денег осталось'
SWAPPED = 'Если у меня было 20 рублей и я потратил 80 рублей, сколько денег осталось'


def test_b03_the_old_job_that_talks_on_after_the_question_changed_says_nothing(call):
    rig = call(**LIVE_RULES)
    asked(rig, AMORT, uid='u1')
    rig.job_says(0, 'Амортизация — это перенос стоимости')
    old = rig.fake.run(0)
    rig.pump(0.3)
    asked(rig, LONG_ASKED, uid='u2')
    rig.pump(0.3)
    answered(rig, 1, LONG_ANSWER)
    late(old, ' на расходы за срок службы.')
    rig.pump(3.0)
    assert not heard(rig, 'срок службы'), f'the dropped job spoke after the question changed: {rig.said()}'
    assert heard(rig, 'Срок уплаты налога')


def test_b04_a_correction_of_a_number_reaches_the_job_with_the_question_it_corrects(call):
    rig = call(**LIVE_RULES)
    asked(rig, MONEY, uid='u1')
    answered(rig, 0, 'Осталось 60 рублей.')
    rig.pump(1.0)
    user_turn(rig, 'u2', 'Нет, не восемьдесят, а девяносто')
    assert rig.fake.runs[1:], 'the correction never reached a job'
    text = job_input(rig, 1)
    assert 'потратил' in text and 'девяносто' in text, text
    answered(rig, 1, 'Осталось 70 рублей.')
    rig.pump(1.0)
    assert heard(rig, 'Осталось 70')


def test_b05_the_same_form_with_the_numbers_turned_gets_its_own_job_and_the_old_answer_is_not_said_again(call):
    rig = call(**LIVE_RULES)
    asked(rig, MONEY, uid='u1')
    answered(rig, 0, 'Осталось 60 рублей.')
    rig.pump(0.5)
    asked(rig, SWAPPED, uid='u2')
    rig.pump(0.5)
    assert rig.fake.runs[1:], 'the turned question was taken for the first one'
    before = rig.said().count('Осталось 60 рублей.')
    answered(rig, 1, 'Не хватает 60 рублей.')
    rig.pump(8.0)
    assert heard(rig, 'Не хватает')
    assert rig.said().count('Осталось 60 рублей.') == before, 'the answer of the other numbers was said again'
