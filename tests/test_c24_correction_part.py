"""c24-b: a correction said after the question («…, сколько денег осталось? Нет, не 90, а 80.») is a condition of it, not a remark around it: ``question_part``
keeps it. Before, the part was the question without it (or the correction without the question), the plan recorded that as its question, and a doubt («Разве?»)
asked the job again on the old numbers: «Осталось 40 рублей.» after «Осталось 30 рублей.» (rehearsal Р103 seed 0 with the speed set, an old answer)."""
import pytest

from echo_sync.classifier import question_part


@pytest.mark.parametrize('text, numbers', [
    ('Если у меня было 90 рублей и я потратил 50 рублей, сколько денег осталось? Нет, не 90, а 80.', ('80', '50')),
    ('Сколько будет 9 умножить на 5? Нет, не 9, а 19.', ('19', '5')),
    ('Если у меня было 40 рублей и я потратил 80 рублей, сколько денег осталось? Нет, не 40, а 50.', ('50', '80')),
    ('Сколько будет 14 умножить на 5? Нет, не 14, а 24.', ('24', '5')),
])
def test_a_correction_after_the_question_stays_with_it(text, numbers):
    part = question_part(text)
    assert all(n in part for n in numbers) and 'не' in part.split() and 'сколько' in part.lower(), part
