"""V2 E18: a clarification, an objection, an example, a context («почему?», «пример», «да/нет» without «?», a mistaken objection) beside an answer in play. Contract of the backlog: such a remark reaches the job with what was REALLY said
(why / example / objection), the partial progress of the plan is not lost, and the plan can be returned to.

Real ControlledMedia (rig ``call``). The forms are a table of utterances, the result is judged by the call's own state: the job was asked, the cursor stood, the old plan is still in the history, not revised away.
Not run on the laptop.
"""
import pytest

from echo_sync.engine import UNASKED
from question_kit import ACCOUNT, LIVE_RULES, MATERIALS, answered, call, entry_of, heard, job_input, job_text, plan, user_turn      # noqa: F401 - call is the fixture

SIDE_ANSWER = 'Потому что так учитывается стоимость материалов.'
FORMS = [
    ('why', 'А почему именно так'),
    ('example', 'Приведите пример'),
    ('objection', 'Нет, я не согласен, это неправильно'),
    ('yesno_no_question_mark', 'А это обязательно делать в этом месяце'),
    ('context', 'Поясните, как это связано с покупкой материалов'),
]


@pytest.mark.parametrize('name, said', FORMS, ids=[row[0] for row in FORMS])
def test_a_remark_beside_the_answer_reaches_the_job_with_its_own_words_and_the_cursor_stands(call, name, said):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    cursor = rig.c.state().get('chunk_index')
    rig.pump(1.0)
    user_turn(rig, 'u1', said)
    assert rig.fake.runs[1:], f'{name}: the job never heard it'
    assert job_text(rig, 1) == said, 'the job gets what was said, not a part of it'
    assert rig.c.state().get('chunk_index') == cursor or rig.c.state().get('question') != ACCOUNT, 'the cursor of the old plan stands'
    answered(rig, 1, SIDE_ANSWER)
    rig.pump(2.0)
    assert heard(rig, 'учитывается стоимость')


@pytest.mark.parametrize('name, said', FORMS[:3], ids=[row[0] for row in FORMS[:3]])
def test_the_old_plan_is_still_in_the_history_after_the_remark_was_answered(call, name, said):
    """Partial progress is not lost: the plan is neither 'revised' nor 'unasked' away by an answer to a clarification."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    user_turn(rig, 'u1', said)
    answered(rig, 1, SIDE_ANSWER)
    rig.pump(2.0)
    entry = entry_of(rig, 'материалов')
    assert entry is not None and entry.get('status') not in ('revised', UNASKED), entry


def test_the_job_of_a_clarification_sees_the_exchange_it_clarifies(call):
    """«Почему?» alone means nothing: the job's input holds the question and the answer in play."""
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    user_turn(rig, 'u1', 'А почему так')
    whole = job_input(rig, 1)
    assert 'покупк' in whole.lower() and 'дебет' in whole.lower(), whole
