"""Q1: what needs no model answers at once. No network, no sleep.

Item 1 (idea B8): a plain sum, difference, product, quotient or percent is answered by code (``echo_sync/quick_math.py``), exactly, in the shape of a reference hit (one spoken sentence,
``ControlledMedia._reference``), so H4's ear path takes it with no route of its own. The test of the grammar is a whitelist, as the reference base's: after the expression itself only filler and
question words may be left; one word that is not on the list, one number more than two, and it is not arithmetic and the model answers. The tables below are CLASSES of wordings, both
directions: what is answered, and the neighbours that look like it and are not (a score, a date, a size with a unit, a phone number, a year, a percent of nothing, a correction).

The case is the owner's call of 4 Nov 20:34: «Пять умножить на пять» waited for the model (and for the cloud's final, 2.1-2.8 s) though nothing in it needs one.
"""
import pytest

from echo_sync import quick_math

# =====================================================================================================================================
# the grammar: what is arithmetic, and the spoken answer
# =====================================================================================================================================

HITS = [
    # the owner's list: a product by «на», by a verb, a percent in digits, a quotient, a sum
    ('пять на пять', 'Двадцать пять.'),
    ('Пять на пять?', 'Двадцать пять.'),
    ('сколько будет семь умножить на восемь', 'Пятьдесят шесть.'),
    ('Сколько будет семь умножить на восемь?', 'Пятьдесят шесть.'),
    ('10% от 200 000', 'Двадцать тысяч.'),
    ('10 % от 200 000', 'Двадцать тысяч.'),
    ('двести разделить на четыре', 'Пятьдесят.'),
    ('двадцать плюс двадцать два', 'Сорок два.'),
    # digits and words alike, the operator as a sign
    ('5 на 5', 'Двадцать пять.'),
    ('20 + 22', 'Сорок два.'),
    ('сколько будет 7 × 8', 'Пятьдесят шесть.'),
    ('сколько будет 7 * 8', 'Пятьдесят шесть.'),
    ('сколько будет 12 плюс 30', 'Сорок два.'),
    # the verb in front of the first number
    ('разделить двести на четыре', 'Пятьдесят.'),
    ('умножить пять на семь', 'Тридцать пять.'),
    ('помножить пять на семь', 'Тридцать пять.'),
    # percents: digits, words, the case of the number after «от»
    ('десять процентов от двухсот тысяч', 'Двадцать тысяч.'),
    ('сколько будет пятнадцать процентов от двухсот', 'Тридцать.'),
    ('20 процентов от 100', 'Двадцать.'),
    ('сколько будет 5 процентов от тысячи', 'Пятьдесят.'),
    ('1 процент от 5000', 'Пятьдесят.'),
    ('13% от 250', 'Тридцать две целых пять десятых.'),
    # the words around it
    ('ну а сколько будет сто плюс двести', 'Триста.'),
    ('так, посчитай пять на шесть', 'Тридцать.'),
    ('пять на шесть это сколько', 'Тридцать.'),
    ('а пять на шесть?', 'Тридцать.'),
    # signs of the result
    ('пять минус десять', 'Минус пять.'),
    ('пять минус пять', 'Ноль.'),
    ('семь разделить на два', 'Три целых пять десятых.'),
    ('2,5 умножить на 4', 'Десять.'),
    ('две целых пять десятых умножить на четыре', 'Десять.'),
    # the scales, the endings of the answer
    ('сто пятьдесят тысяч разделить на три', 'Пятьдесят тысяч.'),
    ('тысяча плюс тысяча', 'Две тысячи.'),
    ('сорок две тысячи умножить на двенадцать', 'Пятьсот четыре тысячи.'),
    ('двадцать одна тысяча плюс десять', 'Двадцать одна тысяча десять.'),
    ('миллион разделить на четыре', 'Двести пятьдесят тысяч.'),
    ('сорок восемь умножить на десять', 'Четыреста восемьдесят.'),
    ('сколько будет 300 000 плюс 50 000', 'Триста пятьдесят тысяч.'),
    ('сколько будет сто на сто', 'Десять тысяч.'),           # said alone it is «certainly» (the skeptic, test_q1_skeptic.py)
    ('девятьсот девяносто девять миллиардов плюс один', 'Девятьсот девяносто девять миллиардов один.'),
    ('999 тысяч плюс 1', 'Девятьсот девяносто девять тысяч один.'),
]


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


@pytest.mark.parametrize('text,spoken', HITS)
def test_a_plain_expression_is_answered_exactly(text, spoken):
    assert quick_math.answer(text) == spoken


NOT_ARITHMETIC = [
    # a plain expression plus a unit, a thing, or a question about it: more than a sum is asked, the model answers
    'пять на пять метров это сколько квадратных',
    'пять на пять метров',
    'сколько будет пять метров на пять метров',
    'комната пять на шесть',
    'сколько будет пять умножить на пять в квадрате',
    'сколько будет пять умножить на пять и почему',
    'почему пять на пять двадцать пять',
    'пять плюс пять метров',
    'сколько будет пять плюс пять рублей',
    # a score, a date, a size, an address: «на» between two numbers, and something else said
    'счёт 60 на 90',
    'счёт шестьдесят на девяносто',
    'с 5 на 6 ноября',
    'с пятого на шестое ноября',
    'в ночь с 5 на 6',
    'размер 20 на 30',
    'матрица 5 на 6',
    'дом 5 на улице 6',
    # a percent that is a rate, a percent of nothing, a percent of a thing
    'налог на прибыль 20 процентов',
    'ставка налога на прибыль двадцать процентов от выручки',
    '20 процентов',
    'сколько процентов',
    '20% от суммы',
    '10% от',
    'процент от 100',
    'сколько будет двадцать процентов от налога',
    # a phone number, a year, a century, a number alone, a time
    '+7 900 123 45 67',
    '8 900 123 45 67',
    'восемь девятьсот пять сто двадцать три сорок пять шестьдесят семь',
    'в 2026 году',
    'две тысячи двадцать шестой год',
    '1945',
    'двадцать пять',
    '5 на',
    'на пять',
    'умножить на пять',
    'пять плюс',
    '12:30',
    '2:1',
    '5/6',
    # more than two numbers, an order that is not said, a chain
    'два плюс два умножить на два',
    'пять на пять двадцать пять',
    'сколько будет пять плюс пять плюс пять',
    'пять плюс пять равно десять',
    # a correction of the listener's: the words that take back are not on the list
    'не пять на пять, а пять на шесть',
    'нет, пять на шесть',
    'пять на пять, ой, нет, на шесть',
    'я имею в виду пять на шесть',
    'то есть пять на шесть',
    'точнее шесть на пять',
    # exactness and the bounds: not a whole sum, a division by nothing, a number too big to say
    'сто разделить на три',
    'десять разделить на ноль',
    'сколько будет ноль разделить на ноль',
    'миллиард умножить на миллиард',
    'триллион умножить на тысячу',
    'триллион плюс один',
    '1,2345 плюс один',
    'один разделить на шестнадцать',
    # the bare «на» is for small whole numbers only
    'две тысячи двадцать пять на двадцать шесть',
    '2025 на 26',
    'пять целых пять десятых на четыре',
    # not a question about a sum at all
    'я заплатил пять на пять',
    'это пять умножить на пять',
    'он сказал пять на пять',
    '',
    '   ',
    'пять',
]


@pytest.mark.parametrize('text', NOT_ARITHMETIC)
def test_what_is_more_than_a_plain_expression_is_not_arithmetic(text):
    assert quick_math.answer(text) is None


@pytest.mark.parametrize('value', [None, 5, 5.5, b'5 na 5', ['5 на 5'], {'a': 1}])
def test_a_text_that_is_not_one_is_not_arithmetic_and_never_raises(value):
    assert quick_math.answer(value) is None


def test_a_very_long_utterance_is_not_arithmetic():
    assert quick_math.answer('пять на пять ' + 'ну ' * 200) is None
    assert quick_math.answer('ну ' * 200 + 'пять на пять') is None
    assert quick_math.answer('ну ' * 14 + 'пять на пять') is None, 'seventeen words: a sum is said shorter'
    assert quick_math.answer('ну ' * 13 + 'пять на пять') == 'Двадцать пять.'
    assert quick_math.answer('пять' + ' ' * 200 + 'на пять') is None, 'a text this long is not what a person says'


def test_the_bounds_of_the_result_are_the_modules_own():
    assert quick_math._result('*', 10 ** 9, 10 ** 9) is None and quick_math._result('*', 10 ** 9, 10 ** 5) == 10 ** 14
    assert quick_math._result('/', 5, 0) is None and quick_math._result('/', 1, 16) is None and quick_math._result('/', 1, 8) == quick_math.Decimal('0.125')
    assert quick_math._result('-', 5, 10) == -5 and quick_math._result('%', 13, 250) == quick_math.Decimal('32.5')


# =====================================================================================================================================
# the spoken number
# =====================================================================================================================================

SPOKEN = [
    (0, 'ноль'), (1, 'один'), (2, 'два'), (11, 'одиннадцать'), (19, 'девятнадцать'), (20, 'двадцать'), (21, 'двадцать один'), (40, 'сорок'),
    (99, 'девяносто девять'), (100, 'сто'), (101, 'сто один'), (200, 'двести'), (999, 'девятьсот девяносто девять'),
    (1000, 'одна тысяча'), (1001, 'одна тысяча один'), (2000, 'две тысячи'), (5000, 'пять тысяч'), (11000, 'одиннадцать тысяч'),
    (21000, 'двадцать одна тысяча'), (22000, 'двадцать две тысячи'), (101000, 'сто одна тысяча'), (111000, 'сто одиннадцать тысяч'),
    (1000000, 'один миллион'), (2000000, 'два миллиона'), (5000000, 'пять миллионов'), (21000000, 'двадцать один миллион'),
    (1000000000, 'один миллиард'), (3000000000, 'три миллиарда'), (1000000000000, 'один триллион'),
    (1234567, 'один миллион двести тридцать четыре тысячи пятьсот шестьдесят семь'),
    (-3, 'минус три'),
]


@pytest.mark.parametrize('value,words', SPOKEN)
def test_whole_numbers_are_spoken_in_words(value, words):
    assert quick_math.spell(value) == words


SPOKEN_FRACTIONS = [
    ('3.5', 'три целых пять десятых'), ('1.5', 'одна целая пять десятых'), ('2.5', 'две целых пять десятых'),
    ('0.5', 'ноль целых пять десятых'), ('0.25', 'ноль целых двадцать пять сотых'), ('0.05', 'ноль целых пять сотых'),
    ('22.1', 'двадцать две целых одна десятая'), ('21.01', 'двадцать одна целая одна сотая'), ('5.002', 'пять целых две тысячных'),
    ('0.001', 'ноль целых одна тысячная'), ('-1.5', 'минус одна целая пять десятых'), ('11.5', 'одиннадцать целых пять десятых'),
]


@pytest.mark.parametrize('value,words', SPOKEN_FRACTIONS)
def test_a_decimal_is_spoken_as_whole_and_fraction(value, words):
    from decimal import Decimal
    assert quick_math.spell(Decimal(value)) == words


def test_the_answer_is_one_sentence_with_a_capital_and_a_full_stop():
    for text, spoken in HITS:
        assert spoken[0].isupper() and spoken.endswith('.') and spoken.count('.') == 1


# =====================================================================================================================================
# the controller: a hit of the base like any other
# =====================================================================================================================================
# The real NativeMediaSocket, ShadowEar and controller on the injected clock (the rig of H3/H4); only the speech detector, the recognizer's worker, the cloud's events and the job's stream
# are scripted. Arithmetic is on in every call.

import helpers_s6_state as S
from echo_sync.settings import resolve
from test_h3_tempo import TICK, WAIT_OF_H3, call             # noqa: F401 - call is the fixture
from test_h4_ear_first import final, speaks

FIVE = 'Двадцать пять.'
THIRTY = 'Тридцать.'
EAR_FIVE = 'пять на пять'


@pytest.fixture
def maths(call):
    def make(**profile):
        rig = call(fast_text='on', **profile)
        return rig
    return make


def named(rig, ear, cloud=None, turn='u1', announced=1.0, speech=1.5):
    """The ear's text of a sum, the cloud's open turn that names the same sum, the ear's silence: the skeptic's rule (``ControlledMedia._ear_sum``): the ear alone cues no figure. Returns the end of the speech."""
    ended = speaks(rig, ear, turn=turn, announced=announced, speech=speech, partial=cloud or ear)
    rig.pump(0.9)
    return ended


def cut_since(rig, sent):
    """Did the wire tell the phone to drop what it holds of the voice (a cue may have been said to its end by then: the cut is still the order given)?"""
    return any(frame.get('type') == 'output_audio_buffer.clear' for _, _, frame in rig.w.frames[sent:])


def test_there_is_no_switch_for_arithmetic():
    from echo_sync.settings import DEFAULTS
    assert 'quick' + '_math' not in DEFAULTS and 'quick' + '_math' not in resolve({})


def test_the_controller_does_arithmetic_on_every_call(call):
    rig = call(fast_text='on')
    assert rig.c._reference('пять на пять') is not None


def test_a_bare_controller_does_arithmetic_too(tmp_path):
    from echo_sync.controlled_media import ControlledMedia
    bare = ControlledMedia(tmp_path / 't.sqlite3', session_id='t', settings={})
    assert bare._reference('пять на пять') is not None


def test_a_hit_of_the_base_is_the_same_hit(maths):
    rig = maths()
    assert rig.c._reference('пять на пять') == FIVE and rig.c._reference('Сколько будет пять умножить на пять?') == FIVE
    assert rig.c._reference('счёт 60 на 90') is None and rig.c._reference('налог на прибыль 20 процентов') is None
    assert rig.c._reference('семнадцатая статья налогового кодекса').startswith('Статья 17'), 'the base is the base'


# -- at the cloud's final: no job is needed ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('said,spoken', [('Сколько будет пять умножить на пять?', FIVE), ('Пять на пять.', FIVE), ('Ну давай, сколько будет семь умножить на восемь', 'Пятьдесят шесть.'),
                                         ('10% от 200 000', 'Двадцать тысяч.'), ('Двести разделить на четыре?', 'Пятьдесят.')])
def test_a_final_with_a_sum_is_answered_by_the_base_not_the_job(maths, said, spoken):
    rig = maths()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', said)
    assert rig.said() == [spoken] and rig.c.local_answer and not rig.fake.runs, 'the job was not asked'


@pytest.mark.parametrize('said', ['Счёт 60 на 90.', 'Пять на пять метров, это сколько квадратных?', 'С 5 на 6 ноября.', 'Налог на прибыль 20 процентов.'])
def test_a_final_that_is_no_sum_is_not_answered_by_the_base(maths, said):
    rig = maths()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', said)
    assert not rig.c.local_answer and rig.said() != [FIVE]


# -- from the ear, before the final ---------------------------------------------------------------------------------------------------------

def test_a_sum_is_cued_from_the_ears_text_before_the_final(maths):
    rig = maths(**WAIT_OF_H3)
    ended = named(rig, EAR_FIVE)
    assert rig.said() == [FIVE], 'not at the final: it has not come'
    assert rig.cues()[0].t - ended <= 0.9 + 2 * TICK + 0.01, 'the end of the utterance by the ear: its silence'
    assert rig.c.question_id == 'u1' and rig.c.user_boundaries['u1'] == 'ear_first' and not rig.fake.runs
    revision, epoch = rig.c.state()['revision'], rig.c.epoch
    rig.pump(2.0)
    final(rig, 'u1', 'Пять на пять?')
    assert rig.said() == [FIVE] and not rig.cues()[0].cleared
    assert (rig.c.state()['revision'], rig.c.epoch) == (revision, epoch), 'the answer is the one that was opened'


@pytest.mark.parametrize('ear,spoken', [
    ('пять на пять', FIVE), ('сколько будет семь умножить на восемь', 'Пятьдесят шесть.'), ('десять процентов от двухсот тысяч', 'Двадцать тысяч.'),
    ('двести разделить на четыре', 'Пятьдесят.'), ('двадцать плюс двадцать два', 'Сорок два.'), ('а пять на шесть', THIRTY), ('ну сколько будет шесть на пять', THIRTY),
    ('разделить двести на четыре', 'Пятьдесят.'), ('сколько будет сто пятьдесят тысяч разделить на три', 'Пятьдесят тысяч.')], ids=lambda value: value.replace(' ', '_'))
def test_the_wordings_of_a_sum_are_all_cued(maths, ear, spoken):
    rig = maths()
    named(rig, ear)
    assert rig.said() == [spoken], rig.said()


@pytest.mark.parametrize('heard', ['пять на пять метров это сколько квадратных', 'счёт шестьдесят на девяносто', 'с пятого на шестое ноября', 'налог на прибыль двадцать процентов',
                                   'не пять на пять а пять на шесть', 'нет пять на шесть', 'двадцать процентов от суммы', 'в две тысячи двадцать шестом году', 'сто разделить на три',
                                   'восемь девятьсот пять сто двадцать три сорок пять шестьдесят семь', 'два плюс два умножить на два', 'пять на пять двадцать пять'], ids=lambda value: value.replace(' ', '_'))
def test_what_is_no_sum_is_not_the_ears(maths, heard):
    rig = maths()
    speaks(rig, heard, turn='u1', announced=1.0, speech=1.5)
    assert rig.said() == [] and rig.c.question_id is None


def test_the_sum_the_ear_hears_after_a_remark_is_read_alone_only_when_a_silence_keeps_them_apart(maths):
    """Read past the remark an article of a code stays that article; a figure does not (the skeptic: «раздели» | «сто на пять»)."""
    rig = maths()
    speaks(rig, 'ну давай быстрее уже', speech=1.0)
    rig.pump(1.1)
    named(rig, EAR_FIVE, speech=1.0, announced=0.5)
    assert rig.said() == [FIVE]
    joined = maths()
    speaks(joined, 'ну давай быстрее уже', speech=1.0)
    joined.pump(0.1)
    named(joined, EAR_FIVE, speech=1.0, announced=0.5)
    assert joined.said() == []


# -- the ear heard a number wrong ----------------------------------------------------------------------------------------------------------------

def test_a_final_with_another_number_cuts_the_cue_and_answers_again(maths):
    """The live order: the ear heard «пять на пять», the cue is out; the cloud's final is «пять на шесть». The cue is cut, the answer to what the cloud heard follows."""
    rig = maths()
    named(rig, EAR_FIVE)
    assert rig.said() == [FIVE]
    sent = len(rig.w.frames)
    rig.w.feed(S.turn_done('u1', 'user', 'Пять на шесть?'))
    rig.pump(0.5)
    assert rig.said() == [FIVE, THIRTY] and not rig.cues()[1].cleared
    assert cut_since(rig, sent), 'what is in the earpiece is cut'
    assert [entry['status'] for entry in rig.c.state()['history']] == ['revised', 'active'], 'the first answer is no answer in play'
    assert rig.c.question_id == 'u1' and rig.c.user_boundaries['u1'] == 'provider_turn_done' and rig.c.local_answer


def test_the_other_number_of_a_final_in_words_and_signs_is_the_same_cut(maths):
    rig = maths()
    named(rig, 'сорок восемь умножить на десять', speech=1.8)
    assert rig.said() == ['Четыреста восемьдесят.']
    sent = len(rig.w.frames)
    rig.w.feed(S.turn_done('u1', 'user', 'Сколько будет 48 × 11?'))
    rig.pump(0.5)
    assert rig.said() == ['Четыреста восемьдесят.', 'Пятьсот двадцать восемь.'] and cut_since(rig, sent)


@pytest.mark.parametrize('said', ['Пять на пять?', 'Сколько будет 5 на 5?', 'Сколько будет пять умножить на пять', '5 × 5', 'Ну, пять умножить на пять, пожалуйста.'])
def test_any_final_of_the_same_sum_changes_nothing(maths, said):
    rig = maths()
    named(rig, EAR_FIVE)
    final(rig, 'u1', said)
    assert rig.said() == [FIVE] and not rig.cues()[0].cleared


def test_a_final_that_goes_on_past_the_sum_is_a_final_of_its_own(maths):
    rig = maths()
    named(rig, EAR_FIVE)
    sent = len(rig.w.frames)
    rig.w.feed(S.turn_done('u1', 'user', 'Пять на пять метров, это сколько квадратных?'))
    rig.pump(0.5)
    assert cut_since(rig, sent) and rig.said() == [FIVE], 'the cue is cut and nothing else is cued'
    assert rig.c.question_text.endswith('квадратных?') and rig.c.user_boundaries['u1'] == 'provider_turn_done' and not rig.c.local_answer


def test_a_number_the_cloud_already_shows_other_keeps_the_ear_from_cueing(maths):
    """The guard before the cue: the cloud's open turn must give the same figure."""
    rig = maths()
    speaks(rig, EAR_FIVE, turn='u1', announced=0.5, speech=1.5, partial='6 на 5')
    assert rig.said() == [] and rig.c.question_id is None, 'the cloud shows another number: the final decides'
    final(rig, 'u1', 'Шесть на пять?')
    assert rig.said() == [THIRTY]


def test_a_last_number_the_cloud_names_other_keeps_the_ear_from_cueing_too(maths):
    """As delivered H4's rule left the last word of a partial open and the wrong figure was said to its end before the final (the skeptic, test_q1_skeptic.py): a sum is the one thing that rule cannot do for."""
    rig = maths()
    speaks(rig, EAR_FIVE, turn='u1', announced=0.5, speech=1.5, partial='5 на 6')
    rig.pump(1.0)
    assert rig.said() == []
    rig.w.feed(S.turn_done('u1', 'user', 'Пять на шесть?'))
    rig.pump(0.5)
    assert rig.said() == [THIRTY]


def test_the_portion_that_waits_with_a_sum_in_it_misheard_opens_nothing(maths):
    """The neighbour of the c9 veto: «Итого двадцать плюс двадцать два.» waits, the listener repeats it, the ear hears 23, and the base has that sum too (43): a wrong number in the earpiece. The classifier
    reads the repeat as a try at the portion; where it would not (a bare sum with words of the portion in it), H4's own guard ``_ear_misheard`` does: the words of the portion, another number."""
    rig = maths()
    rig.asks('u1', 'Чему равна сумма двух чисел?', 0, 'Итого двадцать плюс двадцать два.')
    said, state = rig.said(), rig.c.state()
    rig.pump(1.0)
    speaks(rig, 'двадцать плюс двадцать три', turn='u2', announced=1.0, speech=1.5)
    assert rig.said() == said and rig.c.question_id == 'u1', rig.said()
    assert rig.c._ear_misheard('двадцать плюс двадцать три', state) and rig.c._ear_misheard('итого двадцать плюс двадцать пять', state)
    assert not rig.c._ear_misheard('двадцать плюс двадцать два', state), 'the same sum is the portion repeated, not misheard'
    assert not rig.c._ear_misheard('а сколько будет шесть умножить на семь', state), 'a question of its own says more than the portion has words for'


def test_a_new_sum_while_a_portion_waits_is_asked_at_once(maths):
    rig = maths()
    rig.asks('u1', 'Чему равна сумма двух чисел?', 0, 'Двадцать плюс двадцать два будет сорок два.')
    rig.pump(1.0)
    named(rig, 'а сколько будет пять умножить на шесть', turn='u2')
    assert rig.said()[-1] == THIRTY and rig.c.question_id == 'u2'


def test_the_answer_in_play_is_not_opened_again(maths):
    rig = maths()
    named(rig, EAR_FIVE)
    final(rig, 'u1', 'Пять на пять?')
    rig.pump(1.0)
    speaks(rig, EAR_FIVE, turn='u2', announced=1.0, speech=1.5)
    assert rig.said() == [FIVE] and rig.c.question_id == 'u1'


def test_the_repeat_of_the_answer_is_a_repeat_not_a_sum(maths):
    rig = maths()
    named(rig, EAR_FIVE)
    final(rig, 'u1', 'Пять на пять?')
    rig.pump(1.0)
    speaks(rig, 'двадцать пять', turn='u2', announced=0.5, speech=0.8)
    final(rig, 'u2', 'Двадцать пять.')
    assert rig.said() == [FIVE] and rig.c.question_id == 'u1'


# =====================================================================================================================================
# item 2 (idea B9): the early lookup is fed from the ear's text as well as the cloud's partial
# =====================================================================================================================================
# ``EarlyLookup`` (native_prefetch.py) prepares the existing public lookup for a question while it is still being said; the call's ``ear_lookup`` is off by default and stays so (the
# coordinator's switch: the tests below turn it on for themselves). It prepares and nothing else: no cue, no state of the call, no new check of privacy - ``prefetch_candidate`` asks the same of the ear's
# text as of the cloud's.
# Why it is off (see the report): the experiment of 29 Oct - 12 probes, none of the preparations adopted by the exact question of the final, usually two searches instead of one, no A/B that proved a gain;
# "the next step: the contract of the segments, the criterion of a useful first portion, only then repeat the early lookup". It was never switched on again. The cloud's partial lags the ear by about
# a second on the phone (1.06 s after the end of speech against 0.14 s) and shows a form only late, so the search used to start when the final was near.

import asyncio

from echo_sync.native_prefetch import EarlyLookup, question_key

KEY_RATE = 'Какая сейчас ключевая ставка Банка России'
EAR_RATE = 'какая сейчас ключевая ставка банка россии'
FINAL_RATE = 'Какая сейчас ключевая ставка Банка России?'
OTHER_RATE = 'Какая сейчас ставка налога на добавленную стоимость?'


def lookup_of(calls):
    async def fetch(question):
        calls.append(question)
        return [{'text': question}]
    return fetch


async def silent(*args, **kwargs):
    pass


class StubController:
    """What the feed asks of the controller: the cloud's open turn (``ledger.latest_user``) and the candidate of a text (``prefetch_candidate``)."""

    def __init__(self, text='', tid='u'):
        self.user = {'id': tid, 'text': text, 'final': False, 'valid': True}
        self.settings = None
        self.ledger = self
        self.asked = []

    def latest_user(self):
        return self.user

    @staticmethod
    def public_lookup_allowed(question, search=False):
        return True

    def prefetch_candidate(self, text=None):
        self.asked.append(text)
        return (self.user['id'], text) if text and self.user else None


def test_the_ears_text_starts_the_search_at_once_where_a_partial_waits_to_settle():
    async def go():
        calls = []
        early = EarlyLookup(lookup_of(calls), silent, enabled=True)
        early.observe('u', KEY_RATE, now=10)
        await early.tick(now=10.1)
        await asyncio.sleep(0)
        assert calls == [], "the cloud's partial must be stable for the wait"
        early.observe_ear('v', KEY_RATE, now=10.2)
        await early.tick(now=10.2)
        await asyncio.sleep(0)
        assert calls == [KEY_RATE], "the ear's text is a whole utterance: no wait"
        await early.close()
    asyncio.run(go())


def test_what_the_ear_prepared_is_adopted_by_the_same_question_of_the_final_and_by_no_other():
    async def go():
        calls, events = [], []

        async def trace(stage, **values):
            events.append((stage, values))
        early = EarlyLookup(lookup_of(calls), trace, enabled=True)
        early.observe_ear('u', EAR_RATE, now=0)
        await early.tick(now=0)
        await asyncio.sleep(0)
        started = [values for stage, values in events if stage == 'speculation_started']
        assert len(started) == 1 and started[0]['source'] == 'ear' and started[0]['stable_ms'] == 0
        assert await early.resolve('u', FINAL_RATE) == [{'text': EAR_RATE}] and calls == [EAR_RATE], 'one request for the question and its final'
        assert any(stage == 'prefetch_adopted' for stage, _ in events)
        events.clear()
        other = EarlyLookup(lookup_of(calls), trace, enabled=True)
        other.observe_ear('w', EAR_RATE, now=0)
        await other.tick(now=0)
        await asyncio.sleep(0)
        assert await other.resolve('w', OTHER_RATE) == [{'text': OTHER_RATE}] and len(calls) == 3
        assert not any(stage == 'prefetch_adopted' for stage, _ in events), 'what was prepared for another question is no source of this one'
        await early.close()
        await other.close()
    asyncio.run(go())


def test_the_ear_prepares_nothing_with_the_switch_off_or_for_a_turn_the_final_has_confirmed():
    async def go():
        calls = []
        off = EarlyLookup(lookup_of(calls), silent, enabled=False)
        off.observe_ear('u', KEY_RATE, now=0)
        await off.tick(now=1)
        await asyncio.sleep(0)
        assert calls == []
        assert await off.resolve('u', KEY_RATE) and len(calls) == 1
        on = EarlyLookup(lookup_of(calls), silent, enabled=True)
        await on.resolve('v', KEY_RATE)
        on.observe_ear('v', KEY_RATE, now=0)
        await on.tick(now=1)
        await asyncio.sleep(0)
        assert len(calls) == 2, 'one request for the final, none for a speculation after it'
        await off.close()
        await on.close()
    asyncio.run(go())


def test_a_turn_the_ear_prepared_for_keeps_the_two_requests_of_the_real_question():
    """The hard budget of a turn is two requests (test_native_prefetch, for a partial). A turn the ear prepared for has one more, for the preparation: the final and one restart of it are served even if
    the preparation was for other words. And it is one preparation a turn, as for a partial."""
    async def go():
        calls = []
        early = EarlyLookup(lookup_of(calls), silent, enabled=True)
        early.observe_ear('u', EAR_RATE, now=0)
        await early.tick(now=0)
        await asyncio.sleep(0)
        early.observe_ear('u', 'какая ставка налога на прибыль', now=1)
        await early.tick(now=2)
        await asyncio.sleep(0)
        assert len(calls) == 1, 'one preparation a turn'
        await early.resolve('u', OTHER_RATE)
        await early.resolve('u', 'А какой курс доллара сейчас?')
        assert len(calls) == 3
        with pytest.raises(RuntimeError):
            await early.resolve('u', 'А какой курс евро сейчас?')
        assert len(calls) == 3
        await early.close()
    asyncio.run(go())


def test_the_feed_binds_the_ears_text_to_the_open_turn_when_there_is_one_and_gives_it_up_in_time():
    from echo_sync.ear_prefetch import EAR_FEED_WAIT_SECONDS, EarFeed

    async def go():
        calls, clock = [], [0.0]
        early = EarlyLookup(lookup_of(calls), silent, enabled=True)
        controller = StubController()
        controller.user = None                         # the cloud has not announced the turn yet
        feed = EarFeed(controller, early, clock=lambda: clock[0], settle=0)
        feed.heard({'uid': 1, 'text': EAR_RATE})
        feed.step()
        await early.tick(now=0)
        await asyncio.sleep(0)
        assert calls == []
        clock[0] = EAR_FEED_WAIT_SECONDS - 0.5
        controller.user = {'id': 'u', 'text': '', 'final': False, 'valid': True}
        feed.step()
        await early.tick(now=clock[0])
        await asyncio.sleep(0)
        assert calls == [EAR_RATE], 'bound when the turn came'
        late = EarlyLookup(lookup_of(calls), silent, enabled=True)
        slow = EarFeed(StubController(), late, clock=lambda: clock[0], settle=0)
        slow.controller.user = None
        slow.heard({'uid': 2, 'text': EAR_RATE})
        clock[0] += EAR_FEED_WAIT_SECONDS + 0.1
        slow.controller.user = {'id': 'x', 'text': '', 'final': False, 'valid': True}
        slow.step()
        await late.tick(now=clock[0])
        await asyncio.sleep(0)
        assert len(calls) == 1, 'a turn that comes too late is another utterance'
        await early.close()
        await late.close()
    asyncio.run(go())


def test_the_feed_does_not_bind_the_ears_text_to_a_turn_that_says_something_else():
    from echo_sync.ear_prefetch import EarFeed

    async def go():
        calls = []
        early = EarlyLookup(lookup_of(calls), silent, enabled=True)
        feed = EarFeed(StubController('Какой сейчас курс доллара'), early, clock=lambda: 0.0, settle=0)
        feed.heard({'uid': 1, 'text': EAR_RATE})
        feed.step()
        await early.tick(now=0)
        await asyncio.sleep(0)
        assert calls == [] and early.signature is None and feed.held is None
        feed.controller.user['text'] = 'Какая сейчас ключевая'              # a head of what the ear heard: the same utterance
        feed.step()
        await early.tick(now=0)
        await asyncio.sleep(0)
        assert calls == [EAR_RATE]
        await early.close()
    asyncio.run(go())


def test_the_feed_never_offers_the_controller_a_text_that_stops_in_the_middle_or_that_says_nothing():
    from echo_sync.ear_prefetch import EarFeed

    async def go():
        early = EarlyLookup(lookup_of([]), silent, enabled=True)
        controller = StubController()
        feed = EarFeed(controller, early, clock=lambda: 0.0, settle=0)
        for text in ('какая сейчас ключевая ставка банка россии и', 'какая сейчас ставка налога на', 'если ставка', '', '   ', None, 5):
            feed.heard({'uid': 1, 'text': text})
            feed.step()
        feed.heard({'uid': 2})
        feed.step()
        assert controller.asked == [], controller.asked
        await early.close()
    asyncio.run(go())


def test_a_text_is_judged_once_for_an_open_turn_not_on_every_tick():
    """The judgement is the classifier's (a few ms): a text that is no candidate is not asked again for 4 s of ticks, and nothing is asked while the cloud has no open turn."""
    from echo_sync.ear_prefetch import EarFeed

    async def go():
        early = EarlyLookup(lookup_of([]), silent, enabled=True)
        controller = StubController()
        controller.prefetch_candidate = lambda text=None: controller.asked.append(text)       # no candidate
        feed = EarFeed(controller, early, clock=lambda: 0.0, settle=0)
        controller.user = None
        feed.heard({'uid': 1, 'text': EAR_RATE})
        for _ in range(5):
            feed.step()
        assert controller.asked == [], 'no open turn: nothing is judged'
        controller.user = {'id': 'u', 'text': '', 'final': False, 'valid': True}
        for _ in range(10):
            feed.step()
        assert controller.asked == [EAR_RATE]
        controller.user = {'id': 'v', 'text': '', 'final': False, 'valid': True}
        feed.step()
        assert controller.asked == [EAR_RATE, EAR_RATE], 'another open turn is another judgement'
        await early.close()
    asyncio.run(go())


def test_a_question_cut_by_a_breath_is_prepared_joined_and_not_in_its_first_half():
    from echo_sync.ear_prefetch import EarFeed

    async def go():
        clock, calls = [0.0], []
        early = EarlyLookup(lookup_of(calls), silent, enabled=True)
        controller = StubController()
        feed = EarFeed(controller, early, clock=lambda: clock[0], settle=0)
        feed.heard({'uid': 1, 'text': 'какая сейчас ключевая'})
        clock[0] = 0.8
        feed.heard({'uid': 2, 'text': 'ставка банка россии'})
        feed.step()
        assert controller.asked[0] == 'какая сейчас ключевая ставка банка россии', controller.asked
        await early.tick(now=1)
        await asyncio.sleep(0)
        assert calls == ['какая сейчас ключевая ставка банка россии']
        await early.close()
    asyncio.run(go())


def test_a_cloud_partial_that_is_nothing_or_a_head_of_what_the_ear_prepared_leaves_it_alone():
    from echo_sync.ear_prefetch import EarFeed

    async def go():
        calls = []
        early = EarlyLookup(lookup_of(calls), silent, enabled=True)
        controller = StubController()
        feed = EarFeed(controller, early, clock=lambda: 0.0, settle=0)
        feed.heard({'uid': 1, 'text': EAR_RATE})
        feed.step()
        await early.tick(now=0)
        await asyncio.sleep(0)
        task, signature = early.task, early.signature
        assert calls == [EAR_RATE] and signature == ('u', question_key(EAR_RATE))
        for partial in (None, ('u', 'Какая сейчас'), ('u', 'Какая сейчас ключевая ставка'), ('u', EAR_RATE.capitalize()), None):
            feed.partial(partial)
            await early.tick(now=1)
            assert early.signature == signature and early.task is task and len(calls) == 1, partial
        await early.close()
    asyncio.run(go())


def test_a_cloud_partial_that_heard_other_words_replaces_it_and_another_turn_does_too():
    from echo_sync.ear_prefetch import EarFeed

    async def go():
        calls = []
        early = EarlyLookup(lookup_of(calls), silent, enabled=True)
        controller = StubController()
        feed = EarFeed(controller, early, clock=lambda: 0.0, settle=0)
        feed.heard({'uid': 1, 'text': EAR_RATE})
        feed.step()
        await early.tick(now=0)
        await asyncio.sleep(0)
        assert feed.held is not None
        feed.partial(('u', 'Какой сейчас курс доллара'))
        assert early.signature == ('u', question_key('Какой сейчас курс доллара')) and feed.held is None
        feed.heard({'uid': 2, 'text': EAR_RATE})
        feed.step()
        assert feed.held is not None
        feed.partial(('w', 'Какой сейчас курс доллара'))
        assert early.signature == ('w', question_key('Какой сейчас курс доллара')) and feed.held is None
        await early.close()
    asyncio.run(go())


def test_with_the_switch_off_the_feed_does_nothing_and_the_partial_goes_the_old_way():
    from echo_sync.ear_prefetch import EarFeed

    async def go():
        early = EarlyLookup(lookup_of([]), silent, enabled=False)
        controller = StubController()
        feed = EarFeed(controller, early, clock=lambda: 0.0, settle=0)
        feed.heard({'uid': 1, 'text': EAR_RATE})
        feed.step()
        assert controller.asked == [] and feed.held is None
        feed.partial(('u', KEY_RATE))
        assert early.signature == ('u', question_key(KEY_RATE))
        await early.close()
    asyncio.run(go())


# -- the real wire: ear, controller, transport ---------------------------------------------------------------------------------------------

QUIET = 0.45         # the ear's text has stood for EAR_FEED_SETTLE_SECONDS (the skeptic: a question is often cut by a breath)


@pytest.fixture
def lookups(call):
    def make(**profile):
        rig = call(**{'fast_text': 'on', **profile})
        rig.w.wire.early.enabled = True        # the wire reads ``ear_lookup`` of the modes for it: on for these tests only
        return rig
    return make


def test_the_search_of_a_lookup_question_starts_at_the_end_of_speech_and_says_nothing(lookups):
    rig = lookups()
    speaks(rig, EAR_RATE, turn='u1', announced=1.0, speech=1.5, partial='Какая сейчас')
    rig.pump(QUIET)
    assert len(rig.w.lookup_calls) == 1 and question_key(rig.w.lookup_calls[0]) == question_key(FINAL_RATE), rig.w.lookup_calls
    assert rig.said() == [] and rig.c.question_id is None and not rig.c.grounded, 'preparing only'
    assert not any(frame.get('type') == 'response.audio.delta' for _, _, frame in rig.w.frames)


def test_the_final_with_the_same_question_adopts_it_and_asks_nothing_again(lookups):
    rig = lookups()
    speaks(rig, EAR_RATE, turn='u1', announced=1.0, speech=1.5, partial='Какая сейчас')
    rig.pump(QUIET)
    final(rig, 'u1', FINAL_RATE)
    assert len(rig.w.lookup_calls) == 1 and rig.c.question_id == 'u1'
    assert rig.c.grounded, 'the final has authorized the source, as it always does'


def test_the_final_with_other_words_asks_its_own_question_and_uses_nothing_of_the_ears(lookups):
    rig = lookups()
    speaks(rig, EAR_RATE, turn='u1', announced=1.0, speech=1.5, partial='Какая сейчас')
    rig.pump(QUIET)
    final(rig, 'u1', 'Какая сейчас ключевая ставка по вкладам?')
    assert len(rig.w.lookup_calls) == 2 and question_key(rig.w.lookup_calls[1]) == question_key('Какая сейчас ключевая ставка по вкладам?')


def test_a_shadow_ear_prepares_too(lookups):
    rig = lookups(ear='shadow')
    speaks(rig, EAR_RATE, turn='u1', announced=1.0, speech=1.5, partial='Какая сейчас')
    rig.pump(QUIET)
    assert len(rig.w.lookup_calls) == 1 and rig.said() == []


def test_with_the_switch_off_nothing_is_searched_before_the_final(call):
    rig = call(fast_text='on')
    assert rig.w.wire.early.enabled is False
    speaks(rig, EAR_RATE, turn='u1', announced=1.0, speech=1.5, partial='Какая сейчас')
    rig.pump(QUIET)
    assert rig.w.lookup_calls == []
    final(rig, 'u1', FINAL_RATE)
    assert len(rig.w.lookup_calls) == 1, 'the final asks, as it always did'


def test_the_turn_not_announced_yet_the_search_waits_for_it(lookups):
    from echo_sync.ear_prefetch import EAR_FEED_WAIT_SECONDS
    rig = lookups()
    speaks(rig, EAR_RATE, speech=1.5)
    assert rig.w.lookup_calls == []
    rig.pump(EAR_FEED_WAIT_SECONDS - 1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(TICK * 2)
    assert len(rig.w.lookup_calls) == 1


def test_a_turn_that_comes_too_late_is_not_the_ears(lookups):
    from echo_sync.ear_prefetch import EAR_FEED_WAIT_SECONDS
    rig = lookups()
    speaks(rig, EAR_RATE, speech=1.5)
    rig.pump(EAR_FEED_WAIT_SECONDS + 0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(TICK * 2)
    assert rig.w.lookup_calls == []


@pytest.mark.parametrize('heard', ['какая у меня сейчас ставка по кредиту', 'какая сейчас ставка по моему кредиту', 'какая моя ставка налога сейчас', 'расскажи обо мне какая ставка сейчас',
                                   'что такое инерция', 'какая сейчас ключевая ставка банка россии и', 'какая сейчас ставка налога на'], ids=lambda value: value.replace(' ', '_'))
def test_what_the_cloud_would_not_prepare_the_ear_does_not_either(lookups, heard):
    """The privacy gate and the rest of ``prefetch_candidate``: a personal question never reaches the public lookup, a question that needs none is not searched, a text cut in the middle waits."""
    rig = lookups()
    speaks(rig, heard, turn='u1', announced=1.0, speech=1.5, partial='Какая')
    rig.pump(QUIET)
    assert rig.w.lookup_calls == [] and rig.said() == []


def test_a_turn_that_says_something_else_gets_the_search_of_what_it_says(lookups):
    rig = lookups()
    speaks(rig, EAR_RATE, turn='u1', announced=1.0, speech=1.5, partial='Какой сейчас курс доллара')
    rig.pump(1.0)
    assert [question_key(question) for question in rig.w.lookup_calls] == [question_key('Какой сейчас курс доллара')], "the ear's text is not for this turn: only what it says is searched"


def test_the_clouds_own_partial_still_prepares_a_question_the_ear_did_not_hear(lookups):
    rig = lookups()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_delta('u1', KEY_RATE, 1))
    rig.pump(1.0)
    assert len(rig.w.lookup_calls) == 1
    final(rig, 'u1', FINAL_RATE)
    assert len(rig.w.lookup_calls) == 1


def test_the_question_the_ear_prepared_survives_the_clouds_shorter_partials(lookups):
    """The search is still running when the cloud's partials come (they lag): none of them takes it back, and the final adopts it."""
    rig = lookups()
    gate = rig.w.run(_event())
    early = rig.w.wire.early

    async def slow(question):
        rig.w.lookup_calls.append(question)
        await gate.wait()
        return list(S.SOURCE_ROWS)
    early.fetch = slow
    speaks(rig, EAR_RATE, turn='u1', announced=1.0, speech=1.5, partial='Какая')
    rig.pump(QUIET)
    assert len(rig.w.lookup_calls) == 1 and not early.task.done()
    task = early.task
    for n, text in enumerate(('Какая сейчас', 'Какая сейчас ключевая ставка'), 1):
        rig.w.feed(S.turn_delta('u1', text, n))
        rig.pump(0.2)
    assert early.task is task and not task.cancelled() and not task.done()
    gate.set()
    final(rig, 'u1', FINAL_RATE)
    assert len(rig.w.lookup_calls) == 1 and rig.c.grounded, 'adopted: one search for the question and its final'


async def _event():
    return asyncio.Event()
