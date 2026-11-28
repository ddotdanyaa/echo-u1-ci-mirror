"""h29: the owner's call of 07.11 20:29, its scenes through the real chain. Words are his, seconds the rig's clock, not a phone's."""
import pytest

from echo_sync import instant
from tools.replay import quantity as Q, repeat_scenes as R

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

ROWS = Q.BANK + [
    ('Что такое приказ 79 Министерства финансов?', 'Приказ 79 Министерства финансов — про возврат денег из бюджета.', ['приказ 79 министерства финансов']),
    ('Что такое приказ 422 Министерства финансов?', 'Приказ 422 Министерства финансов — про страховые взносы организаций.', ['приказ 422 министерства финансов']),
    ('Рассчитайте долю каждого вида ценных бумаг', 'Сумма вида делить на итог и умножить на 100.', ['рассчитать долю каждого вида ценных бумаг']),
]
MONOLOGUE = ('Опа, смотри, прошло шестнадцать секунд, и он начал повторять предыдущий ответ. И вот мы снова пришли к этой проблеме, вот, мы поговорили сколько, четырнадцать минут, '
             'и мы снова вернулись к этой проблеме, она никуда не исчезла, и вот это нужно, избавляться от этого нужно, вот так')
OLD = 'Инфляция — это устойчивый рост общего уровня цен, деньги при этом обесцениваются.'


@pytest.fixture
def rig():
    rig = Q.rig_of()
    rows = [instant.clean_entry({'q': q, 'alt': alt, 'answer': a, 'source': 'scene', 'subject': 'scene'}) for q, a, alt in ROWS]
    rig.c.instant = instant.Instant(rows, adapters=()).for_call()
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


def test_a_stretched_word_and_a_word_of_the_answer_is_no_question(rig):
    """131 s: «Та-ак Веках», the model said «Термин возник…», and the answer began from the start."""
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, 'Та-ак цен')
    rig.pump(0.5)
    model_says(rig, OLD)
    rig.pump(4.0)
    assert not [c.text for c in rig.cues()[mark:] if 'Инфляция — это' in c.text]


@pytest.mark.parametrize('said', ['Обозначал обесцениваются', 'деньги при этом', 'Так, рост уровня цен'])
def test_the_model_answering_the_owners_reading_opens_nothing(rig, said):
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, said)
    rig.pump(0.5)
    model_says(rig, 'Да, сначала именно рост цен, а позже смысл расширился до другого.')
    rig.pump(4.0)
    assert not [c.text for c in rig.cues()[mark:] if 'смысл' in c.text or c.text.startswith('Да,')]


def test_a_question_word_inside_a_long_remark_is_no_question(rig):
    """872 s: «мы поговорили сколько, четырнадцать минут»: the remark opened a question and the old answer came again."""
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, MONOLOGUE)
    rig.pump(0.5)
    model_says(rig, OLD)
    rig.pump(4.0)
    assert not [c.text for c in rig.cues()[mark:] if 'Инфляция — это' in c.text]


@pytest.mark.parametrize('k', [1, 5, 20])
def test_a_question_at_the_end_of_a_long_remark_is_answered(rig, k):
    """806 s: «…сразу быстро ответы не приходят. Что такое бухгалтерский учет», however long the remark."""
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, ' '.join(['вот это конечно очень плохо работает у нас сегодня'] * k) + '. Что такое денежная масса?')
    rig.pump(2.0)
    assert [c.text for c in rig.cues()[mark:] if c.text.startswith('Все наличные')]


def test_the_model_saying_an_answer_again_is_not_said(rig):
    """842 s: the old question inside a remark: its answer again, 16 s later."""
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, 'Вот, видишь, а причём вроде, что такое инфляция вообще была за вопрос, это же тоже, наверное, надо понять, почему он так делает и зачем, это же странно?')
    rig.pump(0.5)
    model_says(rig, OLD)
    rig.pump(4.0)
    assert not [c.text for c in rig.cues()[mark:] if 'Инфляция — это' in c.text]


def test_the_same_question_again_is_answered(rig):
    asked(rig)
    rig.pump(20.0)
    mark = len(rig.cues())
    R.utter(rig, 'Что такое инфляция?')
    rig.pump(2.0)
    assert [c.text for c in rig.cues()[mark:] if c.text.startswith('Устойчивый')]


def test_a_number_of_its_own_is_a_new_question(rig):
    """925 s: «статья 422» while «Статья 79…» was on: taken for a wrong try, the old cue said again."""
    asked(rig, 'Что такое приказ 79 Министерства финансов?')
    said = 'приказ четыреста двадцать два Министерства финансов'
    state = rig.c.state()
    assert rig.c._own_number(said, state) and rig.c._bank_asks(said, state)
    assert not rig.c._own_number('приказ семьдесят девять Министерства финансов', state)


def test_a_bank_question_with_a_number_needs_no_cloud(rig):
    """910 s: the article of the base came on the seventh second."""
    ended = Q.ear_only(rig, 'что такое приказ семьдесят девять министерства финансов')
    text, at = Q.after(rig, 0)
    assert text and text.startswith('Приказ 79') and at - ended < 2.0


def test_the_final_that_only_goes_on_keeps_the_answer_of_the_base(rig):
    """1074 s: the ear's head opened the base's formula, the final of the whole task 22 s later took it away."""
    asked(rig, 'рассчитать долю каждого вида ценных бумаг')
    mark = len(rig.cues())
    rig.pump(15.0)
    R.utter(rig, 'рассчитать долю каждого вида ценных бумаг в общем объеме внутреннего долга на ноль первое ноль первое две тысячи семнадцатое')
    rig.pump(0.5)
    model_says(rig, 'Рассчитайте долю каждого вида ценных бумаг в общем объёме внутреннего долга.')
    rig.pump(4.0)
    assert not [c.text for c in rig.cues()[mark:] if c.text.startswith('Рассчитайте')]


def test_silence_repeats_after_about_a_second():
    got = Q.silence_repeats(30.0)
    cue = got['gaps'][0]
    assert cue < 2.5 and got['repeats'] >= 8, got


@pytest.mark.parametrize('text,word', [('Из торговых городов Италии, в XIII-XV веках.', 'тринадцат'), ('В XIX веке', 'девятнадцат')])
def test_a_century_is_said_in_words(text, word):
    from echo_sync.speech_text import speak
    said = speak(text)
    assert word in said and 'XI' not in said and 'XV' not in said


def test_a_correction_is_answered_though_it_has_no_question_form(rig):
    """half_hour seed 24, question 9: «не X, а Y» over an answer on: h29 took it for talk and the model's answer was dropped."""
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, 'Нужно не снижать цены, а повышать их при таком росте')
    rig.pump(0.5)
    model_says(rig, 'Повышение цен при таком спросе ведёт к падению продаж.')
    rig.pump(4.0)
    assert [c.text for c in rig.cues()[mark:] if 'Повышение' in c.text]
