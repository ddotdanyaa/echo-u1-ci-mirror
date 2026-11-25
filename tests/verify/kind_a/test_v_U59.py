"""V1a U59: the dispatcher's «doubt does not break» - one judge, one verdict per utterance; a thing that merely looks like a question (a «что» that joins a clause, a discourse, a fragment) neither resets the waiting portion
nor drops the plan; a command (a slide, a stop) is read by its rule before the word «что». The row's evidence: 21 of 54 resets «new question» came straight from the ear with no check, 30 of 54 through a candidate judged by
the model that writes the answer.

Fixed by the judge of M1 (``utterance_judge``, ``ControlledMedia._judge``; commits 7237293b -> e629e91d, U47/U59/U15). The guards drive the REAL ControlledMedia over a waiting portion (``helpers_s6_ack.Dictation`` + the provider's
events as ``test_stable_partial_ack.Speaker``). Not run on the laptop; a red row reproduces the class: a defect card for the family K.
"""
import re

import pytest

from test_one_m1_kind import held, said_over_the_portion

NOT_A_QUESTION = [
    'смотри что получается', 'так вот что я хотел сказать', 'как говорится, что посеешь то и пожнёшь', 'ну вот что важно',      # the conjunction «что»
    'а вот', 'ну и', 'и это',                                                                                          # fragments: the plan stays
    'слайд семь', 'перейди на слайд три',                                                                              # slide commands
]
QUESTIONS = ['что такое масса', 'скажи что такое масса', 'а что мы делаем дальше', 'объясни что происходит при кипении']


@pytest.mark.parametrize('text', NOT_A_QUESTION)
def test_a_remark_that_only_looks_like_a_question_keeps_the_portion_and_the_plan(tmp_path, caplog, text):
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    assert all('kind=question' not in line for line in lines), lines
    assert held(d, s, caplog)


@pytest.mark.parametrize('text', QUESTIONS)
def test_a_real_question_is_judged_once_and_the_judge_says_question(tmp_path, caplog, text):
    """One judge, one verdict: the lines of the judge on the final of one utterance do not disagree with each other (the old paths gave the ear's and the candidate's different verdicts on one phrase)."""
    lines, d, s = said_over_the_portion(tmp_path, caplog, text)
    kinds = {m.group(1) for m in (re.search(r'kind=(\w+)', line) for line in lines) if m}
    assert lines and kinds == {'question'}, lines
