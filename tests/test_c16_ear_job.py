"""c16 ``ear_job``: the job of the ear's whole breath opens the question before the cloud's final.

The night's stand (c15-cand-f, c15-cand-g, 4 scenes): 14 of 20 first answers had no ``ear first`` at all (no strong form, a portion waiting, or a preface); 34 of 80 that had one ended on ``cloud_disagrees`` because the cloud's
open turn began with the preface; with ``prepare_wide`` the two jobs of a breath went on the preface. The job waited for the final and then took its own 1-2 s. Numbers, «не», roles are not loosened: those cases are here too.
The logic only: nothing here is a measurement of a call.
"""
import pytest

import helpers_s6_state as S
from echo_sync import fast_text as FT
from echo_sync.classifier import strip_fillers
from echo_sync.settings import CALL_SETTINGS, resolve
from test_h1_fast_text import settled       # noqa: F401
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture

FLAGS = {'fast_text': 'on', 'ear_release': 'on', 'prepare_wide': 'on', 'two_witnesses': 'on', 'ear_job': 'on'}
SILENCE = 0.9
PREFACE = 'добрый день садитесь резюме ваше я видела опыт хороший'
ASKS = 'давайте сразу по делу испытательный срок для главного бухгалтера какой максимальный'
ANSWER = 'Шесть месяцев для главного бухгалтера.'


def strip(text):
    return strip_fillers(text, CALL_SETTINGS)


def breath(rig, pieces, *, turn='u1', gap=0.35, speech=1.0, lag=0.15):
    """The pieces of one breath of the ear, the cloud's turn open since its start and silent so far."""
    rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created(turn, 'user', ''))
    rig.pump(speech - 0.3)
    for at, text in enumerate(pieces):
        if at:
            rig.onset()
            rig.pump(speech)
        uid = rig.ear.current
        rig.offset()
        rig.pump(lag)
        rig.worker.heard(uid, text)
        rig.pump(TICK)
        if at < len(pieces) - 1:
            rig.pump(max(0.0, gap - lag - TICK))


def cloud(rig, words, turn='u1', every=TICK, start=0):
    for n, word in enumerate(words, start):
        rig.w.feed(S.turn_delta(turn, word, n))
        rig.pump(every)


def jobs(rig):
    return [str(run.request['input'][-1]) for run in rig.fake.runs]


def test_the_flag_is_off_by_default_and_needs_its_four():
    assert resolve({})['ear_job'] == 'off'
    assert resolve({'local_ear': 'act', **FLAGS})['ear_job'] == 'on'
    for flag in ('prepare_wide', 'ear_release', 'two_witnesses', 'fast_text'):
        assert resolve({'local_ear': 'act', **{**FLAGS, flag: 'off'}})['ear_job'] == 'off', flag


# ---- the rule of an adoption is the witness ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('heard,said,same', [
    ('испытательный срок для главного бухгалтера какой максимальный', 'Добрый день, садитесь. Резюме ваше я видела. Давайте сразу по делу, испытательный срок для главного бухгалтера какой максимальный', True),   # a preface is no conflict
    ('за сколько ему нужно предупредить работодателя', 'А вот если работник, ну, сам решит уволиться, за сколько ему нужно предупредить работодателя', True),
    ('сколько штук нужно продать при цене 500', 'Сколько штук нужно продать при цене 600', False),               # another number
    ('можно ли платить налог', 'Можно ли не платить налог', False),                                               # the ear lost «не»
    ('было 80 рублей потратил 20 сколько осталось', 'Было 20 рублей, потратил 80. Сколько осталось', False),       # the roles
    ('сколько штук нужно продать', 'Постоянные расходы 120 тысяч, цена 500. Сколько штук нужно продать', False),  # a condition is the question's
    ('что такое инерция', 'Что такое индукция', False),                                                           # another word
    ('резюме ваше я видела опыт хороший давайте сразу по делу испытательный срок для главного бухгалтера какой максимальный', 'Резюме ваше я видела, опыт хороший. Давайте сразу по делу, испытательный срок для главного бухгалтера какой максимальный', True),   # no marks in the ear
    ('постоянные расходы сто тысяч цена пятьсот сколько штук нужно продать', 'Постоянные расходы 120 тысяч, цена 500. Сколько штук нужно продать', False),   # a preface with another number
    ('сколько штук нужно продать', 'Вот смотрите, постоянные расходы 120 тысяч, цена 500, сколько штук нужно продать', False),   # the job has not heard the conditions
])
def test_the_witness_reads_as_an_adoption(heard, said, same):
    assert (FT.wide_refusal(heard, said, strip=strip, whole=True) is None) is same


# ---- the job goes on the breath ---------------------------------------------------------------------------------------------------------------

def test_a_preface_of_pieces_leaves_the_question_its_job(call):
    rig = call(**FLAGS)
    breath(rig, ['ну здравствуйте садитесь пожалуйста', 'резюме ваше я видела опыт хороший', 'кофе у нас тут хороший', ASKS])
    assert any('максимальный' in text for text in jobs(rig)), jobs(rig)


def test_the_stable_piece_starts_no_job(call):
    rig = call(**FLAGS)
    rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    cloud(rig, ['Объясни, ', 'пожалуйста, ', 'что такое ', 'инерция ', 'в физике ', 'простыми словами'], every=0.2)
    assert rig.ear.current is not None and not rig.fake.runs, 'the ear is ahead of it'


# ---- it opens without the final ---------------------------------------------------------------------------------------------------------------

def test_after_a_preface_the_answer_sounds_before_the_final(call):
    rig = call(**FLAGS)
    breath(rig, [PREFACE, ASKS])
    cloud(rig, ['Добрый день, садитесь. ', 'Резюме ваше я видела, ', 'опыт хороший. ', 'Давайте сразу по делу, ', 'испытательный срок ', 'для главного ', 'бухгалтера ', 'какой ', 'максимальный'])
    rig.pump(SILENCE)
    rig.job_says(len(rig.fake.runs) - 1, ANSWER)
    rig.pump(TICK * 4)
    assert any('Шесть месяцев' in text for text in rig.said()), rig.said()
    assert rig.c.user_boundaries.get('u1') == 'ear_first'
    rig.w.feed(S.turn_done('u1', 'user', 'Добрый день, садитесь. Резюме ваше я видела, опыт хороший. Давайте сразу по делу, испытательный срок для главного бухгалтера какой максимальный'))
    rig.pump(TICK * 4)
    assert not [cue for cue in rig.w.frames if cue[2].get('type') == 'response.cancelled'], 'the final confirms what was opened'
    assert rig.c.question_id == 'u1'


def test_a_question_with_no_form_while_a_portion_waits_opens_on_the_job(call):
    rig = call(**FLAGS)
    rig.first_portion()
    rig.pump(3.0)
    count = len(rig.said())
    breath(rig, ['выручка и прибыль это одно и то же'], turn='u2')
    cloud(rig, ['Выручка ', 'и прибыль, ', 'это одно ', 'и то же'], turn='u2')
    rig.pump(SILENCE)
    rig.job_says(len(rig.fake.runs) - 1, 'Нет, выручка больше прибыли.')
    rig.pump(TICK * 4)
    assert any('выручка больше' in text for text in rig.said()[count:]), rig.said()


def test_a_remark_the_job_declines_opens_nothing(call):
    rig = call(**FLAGS)
    rig.first_portion()
    rig.pump(3.0)
    count = len(rig.said())
    breath(rig, ['мне кажется кофе у вас давно остыл'], turn='u2')
    cloud(rig, ['Мне ', 'кажется, ', 'кофе у вас ', 'давно ', 'остыл'], turn='u2')
    rig.pump(SILENCE)
    rig.job_says(len(rig.fake.runs) - 1, '—')
    rig.job_ends(len(rig.fake.runs) - 1)
    rig.pump(TICK * 4)
    assert rig.said()[count:] == [] and rig.c.question_id != 'u2'


# ---- what is never loosened ---------------------------------------------------------------------------------------------------------------------

def opened_with(rig, ear, words, answer='Двести штук.'):
    breath(rig, [ear])
    cloud(rig, words)
    rig.pump(SILENCE)
    rig.job_says(len(rig.fake.runs) - 1, answer)
    rig.pump(TICK * 4)
    return rig.said()


def test_another_number_of_the_cloud_opens_nothing(call):
    rig = call(**FLAGS)
    assert opened_with(rig, 'если потратить пятьсот рублей сколько денег останется', ['Если ', 'потратить ', '600 ', 'рублей, ', 'сколько денег ', 'останется']) == []


def test_a_number_at_the_end_of_the_turn_may_still_grow(call):
    rig = call(**FLAGS)
    assert opened_with(rig, 'что говорится в статье девятнадцать', ['Что ', 'говорится ', 'в статье ', 'девятнадцать']) == []


def test_a_lost_not_of_the_ear_opens_nothing(call):
    rig = call(**FLAGS)
    assert opened_with(rig, 'можно ли платить налог с дохода', ['Можно ', 'ли ', 'не платить ', 'налог ', 'с дохода']) == []


def test_a_final_with_another_number_cuts_what_was_opened(call):
    rig = call(**FLAGS)
    said = opened_with(rig, 'если потратить пятьсот рублей сколько денег останется', ['Если ', 'потратить ', '500 ', 'рублей, ', 'сколько денег ', 'останется'])
    assert said, 'precondition: opened on the ear and the cloud'
    rig.w.feed(S.turn_done('u1', 'user', 'Если потратить 500 рублей и ещё 300, сколько денег останется'))
    rig.pump(TICK * 4)
    assert rig.c.user_boundaries.get('u1') != 'ear_first' or rig.c.question_text != strip('если потратить пятьсот рублей сколько денег останется')


def test_with_the_flag_off_nothing_opens_on_a_form_it_did_not_open_on(call):
    rig = call(**{**FLAGS, 'ear_job': 'off'})
    rig.first_portion()
    rig.pump(3.0)
    count = len(rig.said())
    breath(rig, ['выручка и прибыль это одно и то же'], turn='u2')
    cloud(rig, ['Выручка ', 'и прибыль, ', 'это одно ', 'и то же'], turn='u2')
    rig.pump(SILENCE)
    assert rig.said()[count:] == []


# ---- a try at the portion ---------------------------------------------------------------------------------------------------------------------

def tried(call, *flags):
    rig = call(**dict(FLAGS, **dict(flags)))
    rig.first_portion()
    rig.pump(1.5)
    ended = rig.says('статья восемнадцать налогового кодекса', speech=1.2)
    rig.w.feed(S.turn_created('u2', 'user', 'Статья'))
    rig.pump(1.9)
    rig.w.feed(S.turn_done('u2', 'user', 'Статья 18 Налогового кодекса'))
    cue = rig.next_cue(1.5)
    return cue, cue.t - ended if cue else None


def test_a_wrong_repeat_is_said_again_as_soon_as_its_final_came(call):
    cue, after = tried(call)
    assert cue is not None and cue.text == 'Статья 17 Налогового кодекса —' and after < 2.4, after


def test_the_second_of_a_wrong_repeat_counts_from_the_final_with_the_flag_off(call):
    cue, after = tried(call, ('ear_job', 'off'))
    assert cue is not None and after > 2.8, after


# ---- the answer in play is no answer to what does not ask for it (n1_02 step 15 of c15-cand-g and c16-a) --------------------------------------------

OLD = 'Инерция — это свойство тела сохранять скорость. Масса есть мера инерции тела.'


def said_again(call, heard, answer=OLD, **flags):
    rig = call(fast_text='on', **flags)
    rig.asks('u1', 'Что такое инерция?', 0, OLD)
    rig.pump(1.5)
    count = len(rig.said())
    rig.w.feed(S.turn_created('u2', 'user', heard.split()[0]))
    rig.w.feed(S.turn_done('u2', 'user', heard))
    rig.pump(TICK * 2)
    rig.job_says(1, answer)
    rig.job_ends(1)
    rig.pump(1.0)
    return rig, rig.said()[count:]


def test_a_stop_the_job_answers_with_the_old_answer_stops(call):
    rig, said = said_again(call, 'Стоп, подождите секунду, у меня телефон, ну, звонит')
    assert not [text for text in said if 'свойство' in text or 'Инерция' in text], said
    assert rig.c.state()['paused'] and rig.c.question_id == 'u1'


def test_a_remark_the_job_answers_with_the_old_answer_opens_nothing(call):
    rig, said = said_again(call, 'Мне кажется, кофе у вас давно остыл')
    assert rig.c.question_id == 'u1' and rig.c.candidate is None


def test_the_same_question_again_may_have_the_same_answer(call):
    rig, said = said_again(call, 'Так что такое инерция')
    assert rig.c.question_id == 'u2' and said, said


def test_a_doubt_may_have_the_same_answer(call):
    rig, said = said_again(call, 'Вы уверены, вот точно')
    assert rig.c.question_id == 'u2' and said, said


def test_another_answer_to_a_remark_is_as_it_was(call):
    rig, said = said_again(call, 'Мне кажется, кофе у вас давно остыл', answer='Кофе остывает за двадцать минут.')
    assert rig.c.question_id == 'u2' and said, said


# ---- the cloud cuts the end of what the job heard (n1_02 step 14 of c16-a) ------------------------------------------------------------------------

HEAD_TURN = 'А вот если работник сам решит уйти, за сколько ему нужно предупредить'
BREATH = 'а вот если работник сам решит уйти за сколько ему нужно предупредить работодателя'


def cut_by_the_cloud(call, tail=' работодателя', **flags):
    rig = call(**{**FLAGS, **flags})
    rig.first_portion()
    rig.pump(3.0)
    count = len(rig.said())
    breath(rig, [BREATH], turn='u2')
    rig.w.feed(S.turn_done('u2', 'user', HEAD_TURN))
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.pump(SILENCE)
    rig.job_says(len(rig.fake.runs) - 1, 'За две недели письменно.')
    rig.pump(TICK * 4)
    before = rig.said()[count:]
    jobs_then = len(rig.fake.runs)
    rig.w.feed(S.turn_done('u3', 'user', tail))
    rig.pump(TICK * 4)
    return rig, before, jobs_then


def test_the_answer_does_not_wait_for_a_turn_that_says_what_the_job_heard(call):
    rig, before, jobs_then = cut_by_the_cloud(call)
    assert any('две недели' in text for text in before), before
    assert len(rig.fake.runs) == jobs_then and rig.c.question_id == 'u2', 'nothing is joined, nothing starts again'


def test_a_rest_the_job_has_not_heard_is_joined_as_ever(call):
    rig, before, jobs_then = cut_by_the_cloud(call, tail=' и что будет с отпуском')
    assert rig.c.question_id == 'u3' and len(rig.fake.runs) == jobs_then + 1


def test_a_rest_with_a_number_the_job_has_not_heard_is_joined_as_ever(call):
    rig, before, jobs_then = cut_by_the_cloud(call, tail=' работодателя за 30 дней')
    assert rig.c.question_id == 'u3' and len(rig.fake.runs) == jobs_then + 1


def test_the_old_answer_opens_nothing_on_the_ear(call):
    rig = call(**FLAGS)
    rig.asks('u1', 'Что такое инерция?', 0, OLD)
    rig.pump(3.0)
    count = len(rig.said())
    breath(rig, ['мне кажется кофе у вас давно остыл'], turn='u2')
    cloud(rig, ['Мне ', 'кажется, ', 'кофе у вас ', 'давно ', 'остыл'], turn='u2')
    rig.pump(SILENCE)
    rig.job_says(len(rig.fake.runs) - 1, OLD)
    rig.job_ends(len(rig.fake.runs) - 1)
    rig.pump(TICK * 4)
    assert rig.c.question_id == 'u1' and not [text for text in rig.said()[count:] if 'свойство' in text], rig.said()[count:]
