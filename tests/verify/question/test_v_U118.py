"""V2 U118: tell an OBJECTION from a CLARIFICATION and from a REPEAT; after a reconnect recover correctly and keep what the long talk knew (goals 4 and 13 of the master prompt). Check of the backlog: a replay with a dropped line, the details of the
talk in place, the objection and the clarification told apart on a set of 20 utterances.

The set: 7 objections, 7 clarifications, 6 repeats (of the waiting portion, written in six ways). Decided by the call itself (real ControlledMedia, rig ``call``): an objection or a clarification is asked to the job and the cursor stands;
a repeat is no question at all (no job, the cursor goes on by one). The distinction between an objection and a clarification is not visible in a text stand beyond «both go to the job with their own words»: it is asserted here as the words the job
received, and the label of the kind is left to the cloud's reading of the journal. Not run on the laptop.
"""
import pytest

from question_kit import ACCOUNT, LIVE_RULES, MATERIALS, TICK, answered, call, entry_of, heard, job_input, job_text, plan, rebuilt, user_turn      # noqa: F401 - call is the fixture

OBJECTIONS = ['Нет, это неправильно', 'Я не согласен, так нельзя', 'Это неверно, вы ошиблись', 'Нет, не так, кредит и дебет наоборот', 'Подождите, но ведь материалы приходуют иначе',
              'Мне кажется, вы неправы', 'Не может быть, проверьте ещё раз']
CLARIFICATIONS = ['А что значит кредит', 'Поясните, почему дебет счёта материалов', 'А можно подробнее про десять тысяч', 'Что вы имеете в виду под счётом денег',
                  'А как это записать в журнале', 'Уточните, это за один месяц или за год', 'Расскажите чуть подробнее']
REPEATS = ['{p}', '{p_low}', 'ну {p_low}', '{p_low} вот', 'так {p_low}', '{p_low}, да']


@pytest.mark.parametrize('said', OBJECTIONS + CLARIFICATIONS, ids=range(len(OBJECTIONS + CLARIFICATIONS)))
def test_an_objection_or_a_clarification_goes_to_the_job_with_its_words_and_the_cursor_stands(call, said):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    cursor = rig.c.state().get('chunk_index')
    rig.pump(1.0)
    user_turn(rig, 'u1', said)
    assert rig.fake.runs[1:], 'the job never heard it'
    assert said.rstrip('?') in job_text(rig, 1) or job_text(rig, 1) in said, job_text(rig, 1)
    assert rig.c.state().get('chunk_index') == cursor


@pytest.mark.parametrize('form', REPEATS, ids=range(len(REPEATS)))
def test_a_repeat_of_the_waiting_portion_is_no_question_and_moves_the_cursor_by_one(call, form):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    index, portion = rig.c.state()['chunk_index'], rig.said()[0]
    plain = portion.rstrip('.:,')
    rig.pump(0.5)
    user_turn(rig, 'u1', form.format(p=plain, p_low=plain.lower()))
    rig.pump(1.0)
    assert not rig.fake.runs[1:], f'a repeat was taken for a question: {[r.question for r in rig.fake.runs[1:]]}'
    assert rig.c.state()['chunk_index'] == index + 1


def test_after_the_line_drops_the_details_of_the_talk_are_in_place_and_an_objection_is_still_heard_with_them(call):
    rig = call(**LIVE_RULES)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    before = rig.c.state()
    rebuilt(rig)
    after = rig.c.state()
    assert after['chunks'] == before['chunks'] and after['chunk_index'] == before['chunk_index'], 'the position is the file\'s'
    assert entry_of(rig, 'материалов') is not None, 'the talk\'s history survived the drop'
    rig.pump(3.0)
    said = len(rig.said())
    user_turn(rig, 'u1', 'Нет, это неправильно, вы ошиблись со счётом')
    assert rig.fake.runs, 'the objection reached the new call\'s job'
    assert 'покупк' in job_input(rig, 0).lower() or 'материал' in job_input(rig, 0).lower(), 'the job knows what the objection is about'
    answered(rig, 0, 'Проверим: материалы приходуют по дебету счёта материалов.')
    rig.pump(2.0)
    assert heard(rig, 'приходуют')
