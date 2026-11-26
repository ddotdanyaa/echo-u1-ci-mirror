"""c24-b (rehearsals, «missed» and «old answer» with the speed set and without): «Нет, не 9, а 19.» said as a reply of its own after the answer to
«Сколько будет 9 умножить на 5?» was «not a question»: the corrected question was never asked (Р099/1, Р065, Р034, Р040, Р104 ...). A correction of a number
the question has is that question corrected: CORRECTION, the question with the correction after it (the job reads it as the stand's ideal model and the real one do)."""
import pytest

from echo_sync.classifier import CORRECTION, analyze

Q = 'Сколько будет 9 умножить на 5?'
DONE = {'question': Q, 'answer': '45. Это 9 раз по 5.', 'chunks': ['45. Это 9 раз по 5.'], 'chunk_index': 1, 'completed': True, 'revision': 3,
        'history': [{'question': Q, 'answer': '45. Это 9 раз по 5.'}]}
WAITS = {**DONE, 'chunk_index': 0, 'completed': False}


@pytest.mark.parametrize('state', [DONE, WAITS], ids=['answer over', 'portion waits'])
@pytest.mark.parametrize('said', ['Нет, не 9, а 19.', 'не 9, а 19'])
def test_a_correction_of_a_number_of_the_question_asks_it_corrected(state, said):
    d = analyze(said, state, [])
    assert d.kind == CORRECTION and Q.rstrip('?') in d.question and said.strip(' .') in d.question, d


@pytest.mark.parametrize('said', ['Нет, не 7, а 8.', 'Нет, не так.', 'Нет.'])
def test_what_corrects_nothing_the_question_says_is_not_taken_for_it(said):
    d = analyze(said, DONE, [])
    assert not (d.kind == CORRECTION and d.question and Q.rstrip('?') in d.question), d
