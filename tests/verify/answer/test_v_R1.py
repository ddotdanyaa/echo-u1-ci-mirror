"""V3 R1: a ready text of the ear's job is not thrown away by the check against the second witness (the rules ``words``, ``played``) because the breath had chatter before the question: K words of chatter + the question,
K = 0, 5, 30. The final of the cloud is the question alone (the cloud cut the breath: its last sentence), the job on the ear's text has the chatter + the question. The measure of the backlog: the share thrown away
with the same question -> 0, one job answers, no second one.

Real ControlledMedia and wire (rig ``call`` with ``prepare_wide`` on). Red = a card for P/A (``fast_text._why_not``, ``wide_refusal``, ``keep_chatter``); the phone's 4.6-5.3 s is not here. Not run on the laptop."""
import pytest

import helpers_s6_state as S
from answer_kit import TICK, WIDE, call, job_answers, journal, lines, texts      # noqa: F401

CHATTER = ['ну', 'вот', 'значит', 'так', 'слушай', 'короче']
QUESTION = 'как отразить покупку материалов на складе'
ANSWER = 'Купили материалы: дебет счёта материалов, кредит счёта расчётов.'


@pytest.mark.parametrize('k', [0, 5, 30])
def test_the_job_of_a_breath_with_chatter_is_not_thrown_away_when_the_final_is_the_question(call, k):
    rig = call(**WIDE)
    notes = journal(rig)
    chatter = ' '.join(CHATTER[n % len(CHATTER)] for n in range(k))
    rig.says((chatter + ' ' + QUESTION).strip(), speech=2.0 + 0.2 * k)
    assert rig.fast.count == 1, 'precondition: a job on the ear\'s text'
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', QUESTION.capitalize() + '?'))
    rig.pump(TICK)
    job_answers(rig, 0, ANSWER)
    rig.pump(TICK * 3)
    assert rig.fast.count == 1, f'K={k}: the ready job was refused ({[line["rule"] for line in lines(notes, "fast_refused")]}) and a new one begun'
    assert texts(rig) == [ANSWER]
