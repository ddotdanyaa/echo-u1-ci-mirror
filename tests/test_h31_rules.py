"""h31: the critics' scenes of the h29-h30 rules, through the real chain. Seconds are the rig's clock, not a phone's."""
import pytest

from echo_sync import instant
from tools.replay import quantity as Q, repeat_scenes as R

ROWS = Q.BANK + [
    ('Что такое приказ 79 Министерства финансов?', 'Приказ 79 Министерства финансов — про возврат денег из бюджета.', ['приказ 79 министерства финансов']),
    ('Что такое приказ 422 Министерства финансов?', 'Приказ 422 Министерства финансов — про страховые взносы организаций.', ['приказ 422 министерства финансов']),
]
OLD = 'Инфляция — это устойчивый рост общего уровня цен, деньги при этом обесцениваются.'


@pytest.fixture
def rig():
    rig = Q.rig_of()
    rows = [instant.clean_entry({'q': q, 'alt': alt, 'answer': a, 'source': 'scene', 'subject': 'scene'}) for q, a, alt in ROWS]
    rig.c.instant = instant.Instant(rows, adapters=(), rank=True, rank2=True).for_call()
    yield rig
    rig.close()
    rig._mp.undo()


def model_says(rig, text):
    if rig.fake.runs:
        last = len(rig.fake.runs) - 1
        rig.job_says(last, text)
        rig.job_ends(last)


def asked(rig, text='Что такое инфляция?'):
    Q.ear_only(rig, text)
    rig.pump(1.0)
    assert rig.cues()


def new(rig, mark, word):
    return [c.text for c in rig.cues()[mark:] if word in c.text]


@pytest.mark.parametrize('said,reply,word', [
    ('Кто написал Войну и мир, Толстой или Достоевский?', 'Войну и мир написал Толстой.', 'Толстой'),
    ('Налог на прибыль платят организации или физические лица?', 'Налог на прибыль платят организации.', 'организации'),
])
@pytest.mark.parametrize('first', [True, False])
def test_an_answer_of_the_questions_own_words_is_an_answer(rig, said, reply, word, first):
    if first:
        asked(rig)
    mark = len(rig.cues())
    R.utter(rig, said)
    rig.pump(0.5)
    model_says(rig, reply)
    rig.pump(4.0)
    assert new(rig, mark, word)


TASK = ('В первом квартале выручка компании составила сто тысяч рублей, во втором квартале двести тысяч рублей, а расходы за полугодие '
        'составили сто пятьдесят тысяч рублей без учёта налогов и прочих выплат. Найдите прибыль за полугодие.')


@pytest.mark.parametrize('first', [True, False])
def test_a_sheet_task_answered_with_a_figure_of_its_own(rig, first):
    if first:
        asked(rig)
    mark = len(rig.cues())
    R.utter(rig, TASK)
    rig.pump(0.5)
    model_says(rig, 'Прибыль за полугодие сто пятьдесят тысяч рублей.')
    rig.pump(4.0)
    assert new(rig, mark, 'Прибыль')


def test_the_second_task_of_a_sheet_is_answered(rig):
    R.utter(rig, TASK)
    rig.pump(0.5)
    model_says(rig, 'Прибыль за полугодие составила сто пятьдесят тысяч рублей.')
    rig.pump(6.0)
    mark = len(rig.cues())
    R.utter(rig, TASK.replace('сто тысяч', 'триста тысяч').replace('двести тысяч', 'шестьсот тысяч').replace('сто пятьдесят', 'двести пятьдесят'))
    rig.pump(0.5)
    model_says(rig, 'Прибыль за полугодие составила шестьсот пятьдесят тысяч рублей.')
    rig.pump(4.0)
    assert new(rig, mark, 'шестьсот пятьдесят')


@pytest.mark.parametrize('said', [
    ('Предприятие за квартал получило выручку в размере трёх миллионов рублей, себестоимость составила два миллиона рублей, прочие расходы равны двумстам тысячам рублей, '
     'налог уплачен в полном объёме. Вычислите рентабельность продаж.'),
    ('Если выручка компании за год выросла на десять процентов, а расходы при этом остались на прежнем уровне и никаких других изменений в работе компании за этот год не было, '
     'то какая прибыль получится в итоге.'),
    ('Скажи, какой налог платит организация при продаже имущества? Слушай, вот это тоже важно, потому что об этом вчера говорили, и я это записал себе в тетрадь, надо будет потом посмотреть.'),
])
def test_a_long_question_goes_to_the_model(rig, said):
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, said)
    rig.pump(0.5)
    runs = len(rig.fake.runs)
    model_says(rig, 'Новый ответ по сути заданного вопроса получен.')
    rig.pump(1.0)
    if len(rig.fake.runs) > runs:      # the job of the final, when the first was on the ear's text
        model_says(rig, 'Новый ответ по сути заданного вопроса получен.')
    rig.pump(4.0)
    assert new(rig, mark, 'Новый ответ')


def test_a_form_inside_a_clause_near_the_end_opens_nothing(rig):
    asked(rig)
    state = rig.c.state()
    said = ('Вот мы сегодня с другом проверяли это всё целый вечер и снова вернулись, а потом опять всё то же самое, причём уже поздно, '
            'мы поговорили сколько, четырнадцать минут, и опять вернулись к этому')
    assert rig.c._long_talk(said, state)


@pytest.mark.parametrize('remark', ['Почему он опять молчит сегодня', 'Зачем ты это опять повторяешь', 'Ты вообще меня слышишь?'])
def test_a_short_remark_in_question_form_does_not_restart_the_answer(rig, remark):
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, remark)
    rig.pump(0.5)
    model_says(rig, OLD)
    rig.pump(4.0)
    assert not new(rig, mark, 'Инфляция — это')


def test_a_question_whose_answer_resembles_an_old_one_is_answered(rig):
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, 'А почему рост цен всегда обесценивает деньги?')
    rig.pump(0.5)
    model_says(rig, 'Устойчивый рост уровня цен всегда обесценивает деньги, да.')
    rig.pump(4.0)
    assert new(rig, mark, 'всегда')


@pytest.mark.parametrize('said', ['Точно, устойчивый рост', 'да, точно, рост цен'])
def test_an_agreeing_word_is_no_doubt(rig, said):
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, said)
    rig.pump(0.5)
    model_says(rig, OLD)
    rig.pump(4.0)
    assert not new(rig, mark, 'Инфляция — это')


def test_a_doubt_at_the_end_is_a_doubt_and_no_loop(rig):
    asked(rig)
    assert not rig.c._reads_answer('устойчивый рост цен, ты уверена')


@pytest.mark.parametrize('said,word', [
    ('Какая она была в прошлом году, денежная масса?', 'Ответ модели'),
    ('Да я тебе про это и говорю, денежная масса', 'Ответ модели'),
])
def test_the_last_clause_does_not_stand_for_a_head_of_its_own(rig, said, word):
    assert rig.c._reference_tail(said) is None


def test_the_last_clause_still_answers_a_head_the_cloud_cut(rig):
    assert rig.c._reference_tail(', предприятия, понятия, денежная масса')


@pytest.mark.parametrize('said', ['Сколько будет 1,5 плюс 2,5 плюс 3?', 'пять, пять плюс шесть'])
def test_a_decimal_comma_is_not_a_clause(rig, said):
    assert rig.c._reference_tail(said) is None


def test_no_to_the_cue_keeps_the_answer_when_the_model_has_none(rig):
    asked(rig)
    state = rig.c.state()
    before = rig.c.ear_asked_on if hasattr(rig.c, 'ear_asked_on') else None
    rig.c._no_taken(state)
    assert rig.c.repeat_at is not None and getattr(rig.c, 'ear_asked_on', None) == before


def test_no_it_is_so_is_no_rejection(rig):
    asked(rig)
    state = rig.c.state()
    rig.c.cue_window = (rig.c.clock() - 1.0, rig.c.clock())
    if waiting := state:
        assert not rig.c._no_to_the_cue('нет, это так', rig.c.clock(), waiting)


def test_one_word_in_common_is_no_try_at_the_answer(rig):
    asked(rig)
    assert not rig.c._at_the_answer('рост цен это вообще про другое было вчера у них в городе', rig.c.state())


def test_the_final_corrects_the_base_answer_said_on_the_ear_alone(rig):
    rig.c.ear_stood_open = {'tid': 'u9', 'text': 'что такое приказ семьдесят девять министерства финансов', 'at': rig.c.clock(), 'hit': 'Приказ 79'}
    assert rig.c._ear_stood_short({'id': 'u9', 'text': 'что такое приказ 422 министерства финансов'})
    rig.c.ear_stood_open = {'tid': 'u9', 'text': 'что такое приказ семьдесят девять министерства финансов', 'at': rig.c.clock(), 'hit': 'Приказ 79'}
    assert not rig.c._ear_stood_short({'id': 'u9', 'text': 'что такое приказ семьдесят девять министерства финансов'})


def test_a_negation_past_the_ears_words_is_another_question(rig):
    first = {'hit': 'Устойчивый рост цен.', 'text': 'что такое инфляция'}
    assert not rig.c._ear_goes_past(first, 'Что такое инфляция не в экономике, а в космологии?')
    assert rig.c._ear_goes_past(first, 'Что такое инфляция и как её измеряют')


def test_a_figure_of_the_last_clause_reads_the_whole_number(rig):
    assert rig.c._reference_tail('Цена 12,5 рубля, сколько будет 12,5 умножить на 3?') != 'Пятнадцать.'
