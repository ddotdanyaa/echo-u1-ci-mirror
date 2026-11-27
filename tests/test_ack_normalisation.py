"""What counts as the same words (WAVE 2 / Task A; DEF-ACK-01..11, 13, 14, 22): normalisation for the ACK matcher.

Through the real ``analyze`` with the production profile (ack_match=ru_aligned, on_mismatch=silent). These tests add what
the S6 property suite (test_s6_ack_properties.py) does not spell out: scale words, decimals, centuries, protected
neighbours of every new tolerance, hesitations in the middle, a unit that looks like a hesitation, and the old
``_canonical`` contract the other modules rely on.
"""
import pytest

import helpers_s6_ack as H
from echo_sync import ru_alignment as ru
from echo_sync.classifier import ACK


def kind(heard, portion):
    return H.verdict(heard, portion).kind


def both_ways(a, b):
    return kind(a, b) == ACK and kind(b, a) == ACK


# -- written and spoken numbers ----------------------------------------------------------------------------------------

SAME_NUMBER = [
    ('в 1945 году', 'в тысяча девятьсот сорок пятом году'),
    ('с 1991 года', 'с тысяча девятьсот девяносто первого года'),
    ('2026 год', 'две тысячи двадцать шестой год'),
    ('в 2001 году', 'в две тысячи первом году'),
    ('в 2010 году', 'в две тысячи десятом году'),
    ('в 2000 году', 'в двухтысячном году'),
    ('в 988 году', 'в девятьсот восемьдесят восьмом году'),
    ('высота 2500 метров', 'высота две тысячи пятьсот метров'),
    ('около 300 000 километров', 'около трёхсот тысяч километров'),
    ('около 1 500 000 человек', 'около одного миллиона пятисот тысяч человек'),
    ('более 17 миллионов человек', 'более семнадцати миллионов человек'),
    ('13 миллионов', 'тринадцать миллионов'),
    ('1,5 миллиона рублей', 'полтора миллиона рублей'),
    ('5 тысяч рублей', 'пять тысяч рублей'),
    ('1000 человек', 'тысяча человек'),
    ('3,14', 'три целых четырнадцать сотых'),
    ('36,6 градуса', 'тридцать шесть целых шесть десятых градуса'),
    ('3,5 процента', 'три с половиной процента'),
    ('3,5 процента', 'три целых пять десятых процента'),
    ('0,5 литра', 'ноль целых пять десятых литра'),
    ('в 21 веке', 'в двадцать первом веке'),
    ('в XXI веке', 'в двадцать первом веке'),
    ('22 июня 1941 года', 'двадцать второго июня тысяча девятьсот сорок первого года'),
    ('1 сентября', 'первого сентября'),
    ('в 10 классе', 'в десятом классе'),
]


@pytest.mark.parametrize('written,spoken', SAME_NUMBER, ids=[f'{i:02d}' for i in range(len(SAME_NUMBER))])
def test_a_number_written_with_digits_and_spoken_in_words_is_the_same_repeat(written, spoken):
    assert both_ways(written, spoken), (written, spoken, kind(written, spoken), kind(spoken, written))


DIFFERENT_NUMBER = [
    ('в 1945 году', 'в тысяча девятьсот сорок шестом году'),
    ('в 1945 году', 'в тысяча девятьсот пятьдесят пятом году'),
    ('высота 2500 метров', 'высота две тысячи шестьсот метров'),
    ('высота 2500 метров', 'высота пять тысяч метров'),
    ('высота 2500 метров', 'высота двадцать пять метров'),
    ('около 300 000 километров', 'около трёхсот миллионов километров'),
    ('около 300 000 километров', 'около тридцати тысяч километров'),
    ('13 миллионов', 'тринадцать тысяч'),
    ('3,14', 'три целых пятнадцать сотых'),
    ('3,14', 'три целых четырнадцать тысячных'),
    ('3,5 процента', 'три целых шесть десятых процента'),
    ('3,5 процента', 'пять с половиной процента'),
    ('в 21 веке', 'в двадцатом веке'),
    ('22 июня', 'двадцать третьего июня'),
    ('22 июня', 'двадцать второго июля'),
    ('пять шесть', 'одиннадцать'),
    ('в 1945 году', 'в 1954 году'),
    ('2 500', '25 00'),
]


@pytest.mark.parametrize('heard,portion', DIFFERENT_NUMBER, ids=[f'{i:02d}' for i in range(len(DIFFERENT_NUMBER))])
def test_a_different_number_is_not_the_same_repeat_in_any_notation(heard, portion):
    assert kind(heard, portion) != ACK and kind(portion, heard) != ACK, (heard, portion)


def test_a_cardinal_and_an_ordinal_of_the_same_value_stay_apart_outside_a_date():
    assert kind('один ответ', 'первый ответ') != ACK
    assert kind('два раза', 'второй раз') != ACK
    # C7-B2 (live run 20261103-164741, w3_03 step 6): the cloud ASR writes a year it heard as a cardinal before «году», so a cardinal of
    # 1000 or more right before «году»/«годом»/«годе» IS that year; a count stays a count («лет», «год», «года», anything below 1000)
    assert kind('в тысяча девятьсот сорок пять году', 'в 1945 году') == ACK
    assert kind('тысяча девятьсот сорок пять лет', 'в 1945 году') != ACK
    assert kind('двадцать один год', '21-й год') != ACK


def test_a_bare_plural_scale_word_is_not_a_number():
    """«тысячи людей» is not «1000 людей»; only a singular form on its own («тысяча человек») is the number."""
    assert kind('тысячи людей', '1000 людей') != ACK
    assert kind('миллионы людей', '1000000 людей') != ACK


def test_scale_abbreviations_follow_their_numbers():
    assert both_ways('5 тыс. рублей', 'пять тысяч рублей')
    assert both_ways('5 млн человек', 'пять миллионов человек')
    assert both_ways('2 млрд', 'два миллиарда')
    assert kind('5 тыс. рублей', 'пять миллионов рублей') != ACK


# -- thousands grouping ------------------------------------------------------------------------------------------------

def test_grouped_and_ungrouped_digits_are_one_number_but_a_comma_is_not_a_group():
    assert both_ways('около 1 500 человек', 'около 1500 человек')
    assert both_ways('около 1 500 человек', 'около 1500 человек')
    assert both_ways('около 12 345 человек', 'около 12345 человек')
    assert kind('около 1 500 человек', 'около 1 600 человек') != ACK
    assert kind('около 1 5 человек', 'около 15 человек') != ACK


# -- punctuation runs the ASR emits ---------------------------------------------------------------------------------------

@pytest.mark.parametrize('heard', ['Наклон земной оси...', 'Наклон земной оси?!', '“Наклон земной оси”', 'Наклон, земной… оси!!',
                                   '«Наклон земной оси»?', "‘Наклон земной оси’", 'Наклон земной оси ?!?', '…Наклон земной оси'])
def test_punctuation_runs_and_typographic_quotes_are_not_words(heard):
    assert kind(heard, 'Наклон земной оси') == ACK


@pytest.mark.parametrize('heard,portion', [('1+2*3', '(1+2)*3'), ('Наклон (земной) оси', 'Наклон земной оси'),
                                           ('Наклон [земной] оси', 'Наклон земной оси'), ('2 / 3', '2 3'), ('a * b', 'a b')])
def test_brackets_and_operators_are_still_part_of_the_meaning(heard, portion):
    assert kind(heard, portion) != ACK


# -- fillers and hesitations ---------------------------------------------------------------------------------------------

def test_hesitations_are_ignored_at_both_ends_and_in_the_middle():
    portion = 'Наклон земной оси'
    for heard in ('э-э Наклон земной оси', 'Наклон э земной оси', 'Наклон земной эээ оси', 'ммм, Наклон земной оси, эм',
                  'м-м Наклон земной оси э-э', 'Наклон земной оси хм'):
        assert kind(heard, portion) == ACK, heard


def test_a_unit_that_looks_like_a_hesitation_is_still_a_unit():
    assert kind('толщина 5 мм', 'толщина 5 мм') == ACK
    assert kind('толщина пять мм', 'толщина 5 мм') == ACK
    assert kind('толщина 5', 'толщина 5 мм') != ACK
    assert kind('толщина 5 мм', 'толщина 5') != ACK
    assert kind('толщина 5 мм', 'толщина 5 мг') != ACK


def test_fillers_are_ignored_in_the_heard_text_never_in_the_portion():
    assert kind('хорошо проводит тепло', 'Хорошо проводит тепло') == ACK
    assert kind('ну хорошо проводит тепло', 'Хорошо проводит тепло') == ACK
    assert kind('проводит тепло', 'Хорошо проводит тепло') != ACK
    assert kind('ну проводит тепло', 'Хорошо проводит тепло') != ACK
    assert kind('это не так', 'это не так') == ACK
    assert kind('это не', 'это не так') != ACK
    assert kind('и это не так', 'это не так') == ACK
    assert kind('это не так и', 'это не так') == ACK


def test_a_portion_made_only_of_fillers_can_be_confirmed():
    assert kind('Хорошо.', 'Хорошо.') == ACK
    assert kind('ну хорошо', 'Хорошо.') == ACK
    assert kind('хорошо хорошо', 'Хорошо.') == ACK
    assert kind('Ну и так', 'Ну и так.') == ACK
    assert kind('ну', 'Хорошо.') != ACK


def test_saying_a_filler_led_portion_twice_confirms_it():
    assert kind('а млекопитающее, а млекопитающее,', 'а млекопитающее,') == ACK
    assert kind('Вот почему зимой Вот почему зимой', 'Вот почему зимой') == ACK
    assert kind('а млекопитающее, а', 'а млекопитающее,') == ACK       # a trailing filler is dropped, not a second copy
    assert kind('а млекопитающее, а рыба', 'а млекопитающее,') != ACK


# -- word boundaries -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('heard,portion', [
    ('Что то вроде электронной', 'Что-то вроде электронной'), ('что-то вроде электронной', 'Что то вроде электронной'),
    ('это по русски важно', 'это по-русски важно'), ('это чтобы важно', 'это что бы важно'),
    ('поэтому важно', 'по этому важно'), ('зато важно', 'за то важно'), ('Wi Fi работает', 'Wi-Fi работает'),
    ('интернет магазин принимает заказы', 'Интернет-магазин принимает заказы'),
    ('электро энцефалограмма регистрирует активность', 'Электроэнцефалограмма регистрирует активность'),
    ('кое что известно', 'кое-что известно'), ('чтото известно', 'что-то известно'),
])
def test_a_hyphen_a_space_or_a_merge_between_the_same_letters_is_the_same_word(heard, portion):
    assert kind(heard, portion) == ACK, (heard, portion)


@pytest.mark.parametrize('heard,portion', [
    ('не равно', 'равно'), ('равно', 'не равно'), ('нет налога', 'есть налог'), ('налог уплачен', 'залог уплачен'),
    ('это что бы важно', 'это чтобы важно сегодня'),
    ('x y', 'x-y'), ('x-y', 'x y'), ('a-b', 'a b'), ('2 5', '25'), ('в 19 45 году', 'в 1945 году'),
    ('вода кипит', 'вода кипит при ста'), ('гипогликемия', 'гипергликемия'), ('кот', 'собака'),
])
def test_a_boundary_tolerance_never_joins_what_differs_in_letters_signs_or_numbers(heard, portion):
    assert kind(heard, portion) != ACK, (heard, portion)


# -- the contract of the shared canonical form ----------------------------------------------------------------------------

def test_canonical_keeps_returning_plain_atoms_for_the_modules_that_import_it():
    assert ru._canonical('Ставка 15% применяется', ()) == ('ставка', '#15', '%', 'применяться')
    assert ru._canonical('статья восемнадцатая', ()) == ('статья', '#18')
    assert ru._canonical('в 1945 году', ()) == ('в', '#ord:1945', 'год')
    assert ru._canonical('две тысячи пятьсот', ()) == ('#2500',)
    assert ru._canonical('2 500', ()) == ('#2500',)
    assert ru._canonical('пять шесть', ()) == ('!spoken:number:5', '!spoken:number:6')
    assert ru._canonical('ну так называемый', ('ну', 'так')) == ('называть',)      # the legacy leading-filler strip
    assert ru._canonical('Наклон...', ()) == ('наклон',)


def test_the_donor_tables_other_modules_import_still_exist():
    for name in ('_lemma', '_NUMBERS', '_ORDINALS', '_UNITS', '_LOCK', '_canonical', 'match_current'):
        assert hasattr(ru, name), name
    assert ru._NUMBERS['пять'] == 5 and ru._ORDINALS['второй'] == 2 and ru._UNITS['процент'] == '%'


def test_a_rare_script_or_a_broken_lemma_cannot_raise():
    assert H.analyze('\U00017000', H.waiting('Наклон земной оси'), [], H.PROD_SETTINGS).kind
    assert ru._lemma('\U00017000')


# -- fillers: the start of a portion, runs of fillers, and what stays a word (found by the differential fuzz of the old matcher) ----

def test_a_portion_may_start_with_a_connector_that_the_listener_or_the_asr_drops():
    """«и», «а», «ну», «вот», «э»: dropped from the START of the portion they change nothing (the old matcher took it, ASR often drops them)."""
    assert kind('движется', 'и движется') == ACK
    assert kind('млекопитающее', 'а млекопитающее,') == ACK
    assert kind('почему зимой', 'Вот почему зимой') == ACK
    assert kind('смотрите', 'Ну, смотрите') == ACK
    # …but a word with a meaning of its own («хорошо», «так», «ладно») has to be said, and so does the rest of the portion
    assert kind('проводит тепло', 'Хорошо проводит тепло') != ACK
    assert kind('называемый эффект', 'Так называемый эффект') != ACK
    assert kind('почему', 'Вот почему зимой') != ACK


def test_fillers_around_a_portion_that_starts_with_a_filler_do_not_hide_the_portion():
    assert kind('Хорошо ну проводит', 'Хорошо проводит') == ACK
    assert kind('а хорошо млекопитающее', 'а млекопитающее,') == ACK
    assert kind('а так млекопитающее', 'а млекопитающее,') == ACK
    assert kind('и пожалуйста движется', 'и движется') == ACK
    assert kind('ну так называемый эффект', 'Так называемый эффект') == ACK


def test_only_hesitation_sounds_are_ignored_inside_a_portion_not_words_like_nu_or_tak():
    assert kind('Наклон э земной оси', 'Наклон земной оси') == ACK
    assert kind('Наклон ну земной оси', 'Наклон земной оси') != ACK
    assert kind('Наклон так земной оси', 'Наклон земной оси') != ACK
    assert kind('Наклон земной оси', 'Наклон ну земной оси') != ACK


def test_a_wrong_number_with_a_question_mark_is_an_attempt_never_a_new_question():
    """The numbers are merged («13 миллионов» is one atom), so the word-level overlap has to protect the repeat."""
    for heard, portion in (('23 миллионов человек?', '13 миллионов человек.'), ('около 300 покрыт километров?', 'около 300 000 километров'),
                           ('в 1799 учёный году?', 'в 1799 году'), ('17 миллионов человек?', '17 миллионов')):
        d = H.verdict(heard, portion)
        assert d.kind in ('replay', 'silent'), (heard, portion, d)


def test_a_verb_in_another_tense_is_not_the_same_repeat_but_the_other_inflections_are():
    assert kind('Закон будет принят', 'Закон был принят') != ACK
    assert kind('вода кипела', 'вода кипит') != ACK
    assert kind('люди платят налоги', 'человек платит налог') == ACK
    assert kind('были приняты законы', 'был принят закон') == ACK
    assert kind('будут приняты законы', 'будет принят закон') == ACK
    assert kind('он пришёл домой', 'он пришел домой') == ACK


# -- robustness of the number and filler grammar against nonsense built from its own vocabulary -----------------------------------

_KINDS = frozenset({'ack', 'repeat', 'stop', 'question', 'replay', 'silent', 'greeting', 'correction', 'clarify_repair'})
_POOL = ('ноль один одна два две три пять десять двадцать сто двести тысяча тысячи тысяч миллион миллиона миллионов полтора полторы '
         'первый первого второй двадцатый сотый двухтысячный целых целая десятых сотых тысячных с половиной запятая '
         'год году года века веке классе июня мая декабрь 0 00 007 5 15 1945 2026 3,5 1.5 1,000 1 500 300 000 12:30 5–10 №5 15-я '
         'xxi XXI iv mix э-э мм ммм эм хм и а ну вот так хорошо не ни что-то по-русски x-y a-b 5% 5‰ -5 +5 ... ?! “ ” ( ) 1/2 °C '
         'мин л тыс. млн кг мг м Wi-Fi \u00a0 \u17000').split(' ')


def test_the_matcher_and_the_classifier_never_raise_on_nonsense_made_of_their_own_vocabulary():
    import random
    rng = random.Random(20261102)
    states = (None, H.waiting('Наклон земной оси'), dict(H.waiting('Наклон земной оси'), completed=True),
              dict(H.waiting('Наклон земной оси'), pending_turn='t'))
    for _ in range(600):
        heard = ' '.join(rng.choice(_POOL) for _ in range(rng.randint(1, 9)))
        portion = ' '.join(rng.choice(_POOL) for _ in range(rng.randint(1, 9)))
        assert ru.match_current(heard, portion, H.FILLERS) in (None, 'ack', 'attempt'), (heard, portion)
        state = states[rng.randrange(len(states))] if rng.random() < .5 else H.waiting(portion)
        for settings in (H.PROD_SETTINGS, {'ack_match': 'stem'}, {'ack_match': 'exact', 'on_mismatch': 'silent'}):
            assert H.analyze(heard, state, [], settings).kind in _KINDS, (heard, portion, settings)
