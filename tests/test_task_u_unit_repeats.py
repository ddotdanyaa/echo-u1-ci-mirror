"""WAVE 2 / Task U: the spoken repeat of a number with its unit or symbol is acknowledged.

Since Task C a portion keeps a number with its unit or symbol whole («при 100 °C», «500 ₽», «20 %», «$30»), but the ACK matcher
only knew «%» ↔ «процентов» (task-c-seg-report.md §8.1): the natural repeat «при сто градусов Цельсия» left the call waiting
for ever. These tests pin that the units of the brief are the same repeat as their words, in every grammatical case that can
follow the number, in both directions (the portion may be written with symbols while the ASR says words, and the other way
round), and that nothing else becomes the same repeat: a different number, a different unit, a missing unit or a missing number.

Everything goes through the production ``analyze`` with the production profile (``helpers_s6_ack.verdict``); the §8.1 repro and
a price run through the real ``EchoEngine`` with the profile of the iPhone call. The declensions below are written by hand: an
oracle that does not lean on the morphology of the code under test.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_ack as H                                                    # noqa: E402
import helpers_s6_seg as S                                                    # noqa: E402
from echo_sync import ru_alignment as ru                                       # noqa: E402
from echo_sync.classifier import ACK                                           # noqa: E402
from echo_sync.engine import EchoEngine                                        # noqa: E402
from engine_say import engine_reply


def acks(heard, portion):
    return H.verdict(heard, portion).kind == ACK


def both_ways(written, spoken):
    """The portion may be written and heard spoken, or the other way round (an ASR that prints «500 ₽»)."""
    return acks(spoken, written) and acks(written, spoken)


# -- the repro of task-c-seg-report.md §8.1, through the whole engine -----------------------------------------------------------

def _drive(tmp_path, answer, unit_text, spoken_unit, question='Сколько?'):
    """Say every portion in front of the one that holds ``unit_text`` exactly, then say ``spoken_unit`` for it.

    Returns ``(plan, index of the unit portion, chunk_index afterwards)``.
    """
    engine = EchoEngine(tmp_path / 'unit.sqlite3', lambda *args: answer, settings=S.CONTROLLED_SETTINGS)
    engine_reply(engine, session_id='s', turn_id='q', text=question, request={}, model='m')
    plan = engine.state('s')['chunks']
    where = next(i for i, portion in enumerate(plan) if unit_text in portion)
    for i in range(where):
        engine_reply(engine, session_id='s', turn_id=f'say{i}', text=plan[i], request={}, model='m')
    assert engine.state('s')['chunk_index'] == where, plan
    engine_reply(engine, session_id='s', turn_id='unit', text=plan[where].replace(unit_text, spoken_unit), request={}, model='m')
    return plan, where, engine.state('s')['chunk_index']


def test_the_repro_of_the_task_c_report_is_acknowledged(tmp_path):
    """EchoEngine + the call's profile, answer «Вода кипит при 100 °C на уровне моря.», «Вода кипит», then the words."""
    plan, where, after = _drive(tmp_path, 'Вода кипит при 100 °C на уровне моря.', '100 °C', 'сто градусов Цельсия',
                                question='При какой температуре кипит вода?')
    assert plan[:2] == ['Вода кипит', 'при 100 °C'], plan
    assert after == where + 1, ('the spoken repeat did not move the cursor', plan, after)


IN_A_CALL = [
    ('Билет стоит 500 ₽ в одну сторону.', '500 ₽', 'пятьсот рублей'),
    ('Подписка стоит 30 $ в месяц для одного человека.', '30 $', 'тридцать долларов'),
    ('Подписка стоит $30 в месяц для одного человека.', '$30', 'тридцать долларов'),
    ('Билет стоит 20 € в одну сторону без багажа.', '20 €', 'двадцать евро'),
    ('Скорость поезда составляет около 100 км/ч на этом участке.', '100 км/ч', 'сто километров в час'),
    ('Скорость ветра достигала 20 м/с во время шторма.', '20 м/с', 'двадцать метров в секунду'),
    ('Длина стола равна 120 см по замеру мастера.', '120 см', 'сто двадцать сантиметров'),
    ('Опыт длился ровно 5 с при комнатной температуре.', '5 с', 'пять секунд'),
    ('Ночью было минус 20 °C и дул сильный ветер.', '20 °C', 'двадцать градусов Цельсия'),
    ('Вода кипит при 212 °F по шкале Фаренгейта.', '212 °F', 'двести двенадцать градусов Фаренгейта'),
]


@pytest.mark.parametrize('answer,unit_text,spoken', IN_A_CALL, ids=[f'{i:02d}' for i in range(len(IN_A_CALL))])
def test_a_price_a_speed_and_a_temperature_are_acknowledged_in_a_call(tmp_path, answer, unit_text, spoken):
    plan, where, after = _drive(tmp_path, answer, unit_text, spoken)
    assert after == where + 1, ('the spoken repeat did not move the cursor', plan, where, after)


# F1 (wave F): a call cuts by meaning, so the portion that holds the unit is a clause or a sentence (it was «при 100 °C», «500 ₽»,
# «20 м/с во время»): it is found in the live plan, and the listener says THAT portion with the unit in words. Each answer has a
# sentence after it, so that there is a next portion to speak.
LIVE_UNITS = [
    ('Вода кипит при 100 °C на уровне моря. В горах она кипит раньше.', '100 °C', 'сто градусов Цельсия'),
    ('Билет стоит 500 ₽ в одну сторону. Обратный билет стоит дешевле.', '500 ₽', 'пятьсот рублей'),
    ('Скорость ветра достигала 20 м/с во время шторма. Потом ветер стих.', '20 м/с', 'двадцать метров в секунду'),
]


def _unit_portion(live, unit):
    portion = next((chunk for chunk in live.chunks if unit in chunk), None)
    assert portion is not None, live.chunks
    return portion


@pytest.mark.parametrize('answer,unit,spoken_unit', LIVE_UNITS, ids=['celsius', 'rubles', 'speed'])
def test_a_live_dictation_moves_on_when_the_listener_says_the_unit_in_words(tmp_path, answer, unit, spoken_unit):
    """ControlledMedia as the host builds it: the controller, not just the engine, takes the spoken unit for the repeat."""
    live = H.Dictation(tmp_path, answer)
    portion = _unit_portion(live, unit)
    while live.current != portion:
        assert live.say(live.current).after == live.index           # the portions before it, said exactly
    here = live.index
    out = live.say(portion.replace(unit, spoken_unit).rstrip('.'))
    assert (out.before, out.after) == (here, here + 1), (live.chunks, out.types)
    assert not live.completed, live.chunks
    assert out.speaks == [live.chunks[live.index]], out.speaks            # …and the next portion is what it speaks


def test_a_live_dictation_does_not_move_on_a_wrong_spoken_unit(tmp_path):
    live = H.Dictation(tmp_path, LIVE_UNITS[0][0])
    portion = _unit_portion(live, '100 °C')
    while live.current != portion:
        live.say(live.current)
    here = live.index
    for wrong in ('сто градусов Фаренгейта', 'двести градусов Цельсия', 'сто рублей'):
        assert live.say(portion.replace('100 °C', wrong).rstrip('.')).after == here, wrong
    assert live.say(portion.replace('100 °C', 'сто градусов Цельсия').rstrip('.')).after == here + 1


WRONG_IN_A_CALL = ['при сто двадцать градусов Цельсия', 'при сто градусов Фаренгейта', 'при сто градусов', 'при сто процентов']


@pytest.mark.parametrize('wrong', WRONG_IN_A_CALL, ids=[f'{i:02d}' for i in range(len(WRONG_IN_A_CALL))])
def test_a_wrong_number_or_unit_does_not_move_the_cursor_in_a_call(tmp_path, wrong):
    engine = EchoEngine(tmp_path / 'wrong.sqlite3', lambda *args: 'Вода кипит при 100 °C на уровне моря.',
                        settings=S.CONTROLLED_SETTINGS)
    engine_reply(engine, session_id='s', turn_id='q', text='При какой температуре кипит вода?', request={}, model='m')
    engine_reply(engine, session_id='s', turn_id='a', text='Вода кипит', request={}, model='m')
    assert engine.state('s')['chunk_index'] == 1
    engine_reply(engine, session_id='s', turn_id='b', text=wrong, request={}, model='m')
    assert engine.state('s')['chunk_index'] == 1


# -- written and spoken: the same repeat --------------------------------------------------------------------------------------

SAME = [
    # a temperature: the degree sign alone, on a scale, every way the sign is typed
    ('при 100 °C', 'при сто градусов Цельсия'),                      # the §8.1 repro
    ('при 100°C', 'при ста градусах Цельсия'),
    ('при 100 °С', 'при ста градусах Цельсия'),                      # a Cyrillic «С»
    ('при 100 ℃', 'при сто градусов Цельсия'),                       # the one-character sign
    ('при 100 ° C', 'при сто градусов Цельсия'),                     # a space after the degree sign
    ('при 100 °C', 'при сто градусов по Цельсию'),
    ('0 °C', 'ноль градусов Цельсия'),
    ('1 °C', 'один градус Цельсия'),
    ('2 °C', 'два градуса Цельсия'),
    ('36,6 °C', 'тридцать шесть целых шесть десятых градуса Цельсия'),
    ('−5 °C', 'минус пять градусов Цельсия'),
    ('-5 °C', 'минус пять градусов Цельсия'),
    ('212 °F', 'двести двенадцать градусов Фаренгейта'),
    ('212 ℉', 'двести двенадцать градусов по Фаренгейту'),
    ('212 ° F', 'двести двенадцать градусов Фаренгейта'),
    ('90°', 'девяносто градусов'),
    ('угол 90 °', 'угол девяносто градусов'),
    ('1 °', 'один градус'),
    ('2 °', 'два градуса'),
    ('Вода кипит при 100 °C на уровне моря.', 'Вода кипит при ста градусах Цельсия на уровне моря'),
    # money: the sign after the number, before it, and the abbreviation
    ('500 ₽', 'пятьсот рублей'),
    ('500₽', 'пятьсот рублей'),
    ('1 ₽', 'один рубль'),
    ('2 ₽', 'два рубля'),
    ('500 руб.', 'пятьсот рублей'),
    ('500 руб', 'пятьсот рублей'),
    ('1 500 ₽', 'тысяча пятьсот рублей'),
    ('5 тыс. руб.', 'пять тысяч рублей'),
    ('5 тыс. ₽', 'пять тысяч рублей'),
    ('2,5 млн ₽', 'два с половиной миллиона рублей'),
    ('$30', 'тридцать долларов'),
    ('30 $', 'тридцать долларов'),
    ('$ 30', 'тридцать долларов'),
    ('$1', 'один доллар'),
    ('$1,5 млн', 'полтора миллиона долларов'),
    ('€50', 'пятьдесят евро'),
    ('50 €', 'пятьдесят евро'),
    ('₽500', 'пятьсот рублей'),
    ('цена $30 за штуку', 'цена тридцать долларов за штуку'),
    # a speed
    ('100 км/ч', 'сто километров в час'),
    ('20 м/с', 'двадцать метров в секунду'),
    ('1 км/ч', 'один километр в час'),
    ('2 км/ч', 'два километра в час'),
    ('2 м/с', 'два метра в секунду'),
    ('100 км/час', 'сто километров в час'),
    ('20 м/сек', 'двадцать метров в секунду'),
    ('100 км / ч', 'сто километров в час'),
    ('Скорость ветра 20 м/с, а не 2.', 'Скорость ветра двадцать метров в секунду, а не 2'),
    # the abbreviations of the brief, one by one
    ('5 кг', 'пять килограммов'),
    ('5 г', 'пять граммов'),
    ('5 км', 'пять километров'),
    ('5 м', 'пять метров'),
    ('5 см', 'пять сантиметров'),
    ('5 мм', 'пять миллиметров'),
    ('5 ч', 'пять часов'),
    ('5 мин', 'пять минут'),
    ('5 с', 'пять секунд'),
    ('5 сек', 'пять секунд'),
    ('20 %', 'двадцать процентов'),
    ('20%', 'двадцать процентов'),
    ('5 с.', 'пять секунд'),
    ('5 с половиной с', 'пять с половиной секунд'),
    ('в 5 ч', 'в пяти часах'),
    # …also after a scale word, where the abbreviation is not read as a unit by the word-level table
    ('5 тыс. ч', 'пять тысяч часов'),
    ('5 тыс. мин', 'пять тысяч минут'),
    ('5 тыс. с', 'пять тысяч секунд'),
    ('5 тыс. сек', 'пять тысяч секунд'),
    ('2,5 млн кг', 'два с половиной миллиона килограммов'),
    ('20 м/мин', 'двадцать метров в минуту'),
    ('3 км/с', 'три километра в секунду'),
    ('30 см/с', 'тридцать сантиметров в секунду'),
]


@pytest.mark.parametrize('written,spoken', SAME, ids=[f'{i:02d}' for i in range(len(SAME))])
def test_a_unit_written_with_its_symbol_is_the_same_repeat_as_its_words(written, spoken):
    assert both_ways(written, spoken), (written, spoken, H.verdict(spoken, written), H.verdict(written, spoken))


# -- every grammatical case that can follow a number -------------------------------------------------------------------------

# For each noun the forms after «один», «два» and «пять», per case. After «два» the nominative and the accusative want the genitive
# singular («два градуса»), after «пять» the genitive plural; in every other case the numeral and the noun stand in that case.
DECLENSIONS = {
    'градус': {'nom': 'градус градуса градусов', 'gen': 'градуса градусов градусов', 'dat': 'градусу градусам градусам',
               'ins': 'градусом градусами градусами', 'prep': 'градусе градусах градусах'},
    'рубль': {'nom': 'рубль рубля рублей', 'gen': 'рубля рублей рублей', 'dat': 'рублю рублям рублям',
              'ins': 'рублем рублями рублями', 'prep': 'рубле рублях рублях'},
    'доллар': {'nom': 'доллар доллара долларов', 'gen': 'доллара долларов долларов', 'dat': 'доллару долларам долларам',
               'ins': 'долларом долларами долларами', 'prep': 'долларе долларах долларах'},
    'евро': {case: 'евро евро евро' for case in ('nom', 'gen', 'dat', 'ins', 'prep')},
    'секунда': {'nom': 'секунда секунды секунд', 'gen': 'секунды секунд секунд', 'dat': 'секунде секундам секундам',
                'ins': 'секундой секундами секундами', 'prep': 'секунде секундах секундах'},
    'минута': {'nom': 'минута минуты минут', 'gen': 'минуты минут минут', 'dat': 'минуте минутам минутам',
               'ins': 'минутой минутами минутами', 'prep': 'минуте минутах минутах'},
    'час': {'nom': 'час часа часов', 'gen': 'часа часов часов', 'dat': 'часу часам часам',
            'ins': 'часом часами часами', 'prep': 'часе часах часах'},
    'метр': {'nom': 'метр метра метров', 'gen': 'метра метров метров', 'dat': 'метру метрам метрам',
             'ins': 'метром метрами метрами', 'prep': 'метре метрах метрах'},
    'километр': {'nom': 'километр километра километров', 'gen': 'километра километров километров',
                 'dat': 'километру километрам километрам', 'ins': 'километром километрами километрами',
                 'prep': 'километре километрах километрах'},
    'сантиметр': {'nom': 'сантиметр сантиметра сантиметров', 'gen': 'сантиметра сантиметров сантиметров',
                  'dat': 'сантиметру сантиметрам сантиметрам', 'ins': 'сантиметром сантиметрами сантиметрами',
                  'prep': 'сантиметре сантиметрах сантиметрах'},
    'миллиметр': {'nom': 'миллиметр миллиметра миллиметров', 'gen': 'миллиметра миллиметров миллиметров',
                  'dat': 'миллиметру миллиметрам миллиметрам', 'ins': 'миллиметром миллиметрами миллиметрами',
                  'prep': 'миллиметре миллиметрах миллиметрах'},
    'килограмм': {'nom': 'килограмм килограмма килограммов', 'gen': 'килограмма килограммов килограммов',
                  'dat': 'килограмму килограммам килограммам', 'ins': 'килограммом килограммами килограммами',
                  'prep': 'килограмме килограммах килограммах'},
    'грамм': {'nom': 'грамм грамма граммов', 'gen': 'грамма граммов граммов', 'dat': 'грамму граммам граммам',
              'ins': 'граммом граммами граммами', 'prep': 'грамме граммах граммах'},
    'процент': {'nom': 'процент процента процентов', 'gen': 'процента процентов процентов', 'dat': 'проценту процентам процентам',
                'ins': 'процентом процентами процентами', 'prep': 'проценте процентах процентах'},
}
FEMININE = frozenset({'секунда', 'минута'})
# The numerals 1, 2, 5 per case (masculine/neuter, feminine).
NUMERALS = {'nom': ('один два пять', 'одна две пять'), 'gen': ('одного двух пяти', 'одной двух пяти'),
            'dat': ('одному двум пяти', 'одной двум пяти'), 'ins': ('одним двумя пятью', 'одной двумя пятью'),
            'prep': ('одном двух пяти', 'одной двух пяти')}
# How each noun is written next to a digit (the symbols and abbreviations of the brief).
WRITTEN = {'градус': ['°'], 'рубль': ['₽', 'руб.'], 'доллар': ['$'], 'евро': ['€'], 'секунда': ['с'], 'минута': ['мин'],
           'час': ['ч'], 'метр': ['м'], 'километр': ['км'], 'сантиметр': ['см'], 'миллиметр': ['мм'],
           'килограмм': ['кг'], 'грамм': ['г'], 'процент': ['%']}
# A scale after «градус» (Celsius, Fahrenheit) is said in the genitive and written as one sign.
SCALES = {'Цельсия': ['°C', '°С', '℃'], 'Фаренгейта': ['°F', '℉']}


def _grid():
    cases = []
    for noun, by_case in DECLENSIONS.items():
        for case, forms in by_case.items():
            numerals = NUMERALS[case][1 if noun in FEMININE else 0].split()
            for digit, numeral, form in zip((1, 2, 5), numerals, forms.split()):
                lead = 'в ' if case == 'prep' else ''
                for written in WRITTEN[noun]:
                    cases.append((f'{lead}{digit} {written}', f'{lead}{numeral} {form}', f'{noun}-{case}-{digit}'))
                if noun == 'градус':
                    for scale, signs in SCALES.items():
                        for sign in signs:
                            cases.append((f'{lead}{digit} {sign}', f'{lead}{numeral} {form} {scale}', f'{noun}-{case}-{digit}'))
    return cases


GRID = _grid()


def test_the_grid_covers_every_case_of_every_unit():
    assert len(GRID) >= 300
    assert {ident.split('-')[0] for _, _, ident in GRID} == set(DECLENSIONS)
    assert {ident.split('-')[1] for _, _, ident in GRID} == {'nom', 'gen', 'dat', 'ins', 'prep'}


@pytest.mark.parametrize('written,spoken', [(w, s) for w, s, _ in GRID], ids=[f'{i:03d}' for i in range(len(GRID))])
def test_every_grammatical_case_after_the_number_is_the_same_repeat(written, spoken):
    assert both_ways(written, spoken), (written, spoken, H.verdict(spoken, written), H.verdict(written, spoken))


NUMBERS = (0, 1, 2, 3, 4, 5, 11, 12, 14, 15, 19, 20, 21, 22, 25, 40, 99, 100, 101, 111, 112, 121, 200, 365, 999, 1000, 1001,
           1002, 1500, 2000, 2002, 2500, 11000, 21000, 22000, 100000, 300000, 999999)
FEMININE_FORM = {'один': 'одна', 'два': 'две'}


def spoken_number(n, noun):
    """The numeral as ``helpers_s6_ack`` speaks it (an oracle of its own), «одна»/«две» in front of a feminine noun."""
    words = H.cardinal(n) if n < 1000 else H.cardinal_big(n)
    if noun in FEMININE:
        head, _, last = words.rpartition(' ')
        words = f'{head} {FEMININE_FORM.get(last, last)}'.strip()
    return words


def spoken_quantity(n, noun):
    """«двадцать один рубль», «две тысячи два рубля», «пять рублей», «одиннадцать рублей»."""
    index = 0 if n % 10 == 1 and n % 100 != 11 else 1 if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else 2
    return f'{spoken_number(n, noun)} {DECLENSIONS[noun]["nom"].split()[index]}'


def test_any_number_with_any_unit_is_the_same_repeat_in_digits_and_in_words():
    rng = random.Random(20261103)
    nouns = sorted(DECLENSIONS)
    checked = 0
    for n in NUMBERS:
        for noun in nouns:
            sign = rng.choice(WRITTEN[noun])
            spoken = spoken_quantity(n, noun)
            assert both_ways(f'{n} {sign}', spoken), (n, sign, spoken)
            # …and not the same: the number next to it, another unit of the same size
            step = rng.choice((1, 10, 100))
            other_number = n + step if n + step < 10 ** 6 else n - step
            other_noun = rng.choice([k for k in nouns if k != noun])
            assert not acks(spoken_quantity(other_number, noun), f'{n} {sign}'), (n, other_number, sign)
            assert not acks(spoken_quantity(n, other_noun), f'{n} {sign}'), (n, noun, other_noun)
            assert not acks(spoken, f'{n} {rng.choice(WRITTEN[other_noun])}'), (n, noun, other_noun)
            checked += 1
    assert checked == len(NUMBERS) * len(nouns)


def test_any_number_with_a_speed_a_scale_or_a_currency_sign_in_front():
    rng = random.Random(20261104)
    for n in NUMBERS:
        for sign, unit, tail in (('км/ч', 'километр', ' в час'), ('м/с', 'метр', ' в секунду')):
            spoken = spoken_quantity(n, unit) + tail
            assert both_ways(f'{n} {sign}', spoken), (n, sign, spoken)
            assert not acks(spoken, f'{n - 1 if n == 999999 else n + 1} {sign}'), (n, sign)
        for scale, signs in SCALES.items():
            spoken = spoken_quantity(n, 'градус') + f' {scale}'
            assert both_ways(f'{n} {rng.choice(signs)}', spoken), (n, scale, spoken)
            assert not acks(spoken, f'{n} °'), (n, scale)
        for sign, noun in (('$', 'доллар'), ('€', 'евро'), ('₽', 'рубль')):
            assert both_ways(f'{sign}{n}', spoken_quantity(n, noun)), (n, sign)


@pytest.mark.parametrize('case,forms', [('nom', 'километр километра километров'), ('gen', 'километра километров километров'),
                                        ('dat', 'километру километрам километрам'), ('ins', 'километром километрами километрами'),
                                        ('prep', 'километре километрах километрах')], ids=['nom', 'gen', 'dat', 'ins', 'prep'])
def test_a_speed_is_the_same_repeat_in_every_case(case, forms):
    for digit, numeral, form in zip((1, 2, 5), NUMERALS[case][0].split(), forms.split()):
        assert both_ways(f'{digit} км/ч', f'{numeral} {form} в час'), (case, digit)


# -- not the same repeat ----------------------------------------------------------------------------------------------------

DIFFERENT = [
    # a different number
    ('200 °C', 'сто градусов Цельсия'),                              # the brief's example
    ('100 °C', 'сто один градус Цельсия'),
    ('100 °C', 'двести градусов Цельсия'),
    ('36,6 °C', 'тридцать шесть целых семь десятых градуса Цельсия'),
    ('500 ₽', 'пятьдесят рублей'),
    ('500 ₽', 'пять тысяч рублей'),
    ('500 ₽', 'пятьсот один рубль'),
    ('$30', 'тридцать один доллар'),
    ('$30', 'тринадцать долларов'),
    ('20 м/с', 'двенадцать метров в секунду'),
    ('100 км/ч', 'сто двадцать километров в час'),
    ('5 с', 'пятнадцать секунд'),
    ('5 см', 'пятьдесят сантиметров'),
    ('1 500 ₽', 'тысяча шестьсот рублей'),
    ('−5 °C', 'пять градусов Цельсия'),
    ('5 °C', 'минус пять градусов Цельсия'),
    ('+5 °C', 'минус пять градусов Цельсия'),
    # a different unit (the brief: «рублей» for «$»)
    ('$30', 'тридцать рублей'),
    ('$', 'рублей'),
    ('$5', 'пять рублей'),
    ('5 ₽', 'пять долларов'),
    ('5 €', 'пять долларов'),
    ('5 $', 'пять евро'),
    ('5 ₽', 'пять евро'),
    ('100 °C', 'сто градусов Фаренгейта'),
    ('100 °F', 'сто градусов Цельсия'),
    ('100 °', 'сто градусов Цельсия'),
    ('100 °C', 'сто процентов'),
    ('100 °', 'сто процентов'),
    ('100 км/ч', 'сто метров в секунду'),
    ('20 м/с', 'двадцать километров в час'),
    ('20 м/с', 'двадцать метров в минуту'),
    ('20 м', 'двадцать метров в секунду'),
    ('100 км', 'сто километров в час'),
    ('5 кг', 'пять граммов'),
    ('5 г', 'пять миллиграммов'),
    ('5 мм', 'пять сантиметров'),
    ('5 см', 'пять миллиметров'),
    ('5 см', 'пять метров'),
    ('5 мин', 'пять секунд'),
    ('5 с', 'пять минут'),
    ('5 ч', 'пять минут'),
    ('5 с', 'пять часов'),
    ('5 ч', 'пять секунд'),
    ('5 ₽', 'пять процентов'),
    # a unit is not a number and a number is not a unit
    ('500 ₽', 'пятьсот'),
    ('500 ₽', 'рублей'),
    ('градусов', '°'),
    ('сто градусов', '100'),
    ('100 °C', 'сто'),
    ('100 °C', 'градусов Цельсия'),
    # an added or dropped word is still another repeat
    ('100 °C', 'сто градусов Цельсия по шкале'),
    ('при 100 °C', 'до сто градусов Цельсия'),
    ('500 ₽', 'пятьсот рублей и пятьсот рублей ещё'),
    ('100 км/ч', 'сто километров час'),
]


@pytest.mark.parametrize('heard,portion', DIFFERENT, ids=[f'{i:02d}' for i in range(len(DIFFERENT))])
def test_a_different_number_or_unit_is_not_the_same_repeat(heard, portion):
    assert not acks(heard, portion), (heard, portion, H.verdict(heard, portion))
    assert not acks(portion, heard), (portion, heard, H.verdict(portion, heard))


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason='found by Task U, not a unit matter: ru_numbers reads «два целых три десятых» as 2.3 and «миллиона» as a '
                          'second number, so it is not 2 300 000 (= «2,3 млн»); «два с половиной миллиона» works. Open for the '
                          'number grammar (Task A).')
def test_a_decimal_in_words_followed_by_a_scale_word_is_the_number_it_says():
    assert both_ways('2,3 млн рублей', 'два целых три десятых миллиона рублей')


def test_a_unit_is_matched_only_right_after_its_number():
    """Without a number a degree sign, a ruble sign or a dollar word is not a unit to be merged: no new equivalences."""
    assert not acks('температура в градусах Цельсия', 'температура в °C')
    assert not acks('курс доллара', 'курс $')
    assert not acks('цена в рублях', 'цена в ₽')
    assert not acks('пять шесть рублей', '5 6 ₽')


@pytest.mark.parametrize('text', ['второй градус', 'пятая секунда', 'двадцать второй рубль', 'сотый доллар', 'тысячный евро'])
def test_a_unit_word_after_an_ordinal_stays_a_word(text):
    """«второй градус» is not two degrees: after a spoken ordinal the pass leaves the words as they are.

    Both texts go through the same pass, so only the atoms can show it (a cross-form pair is rejected either way)."""
    assert all(atom.kind != 'u' for atom in ru._units(ru._canonical(text, (), True))), text


# -- the tolerances of the matcher still hold around a unit ---------------------------------------------------------------------

AROUND_A_UNIT = [
    'при сто э градусов Цельсия',                  # a hesitation between the number and the unit
    'при сто градусов эм Цельсия',                 # … and inside the unit
    'при сто градусов Цельсия э',
    'э при сто градусов Цельсия',
    'ну при сто градусов Цельсия',                 # a listed filler in front
    'при сто градусов Цельсия ну',
    'При СТО Градусов Цельсия!',
    'при сто градусов Цельсия при сто градусов Цельсия',     # said twice
    'при сто, градусов, Цельсия.',
]


@pytest.mark.parametrize('heard', AROUND_A_UNIT, ids=[f'{i:02d}' for i in range(len(AROUND_A_UNIT))])
def test_hesitations_fillers_case_and_a_double_say_around_a_spoken_unit(heard):
    assert acks(heard, 'при 100 °C'), heard


IN_WORDS = [
    ('при сто э градусах Цельсия', 'при 100 градусах Цельсия'),     # a portion written in words (the usual ones)
    ('при сто градусах э Цельсия', 'при 100 градусах Цельсия'),
    ('пятьсот э рублей', '500 ₽'),
    ('двадцать э метров в секунду', '20 м/с'),
    ('при сто градусов Цельсия', 'при 100 градусах Цельсия'),
]


@pytest.mark.parametrize('heard,portion', IN_WORDS, ids=[f'{i:02d}' for i in range(len(IN_WORDS))])
def test_a_portion_written_in_words_keeps_its_tolerances(heard, portion):
    assert acks(heard, portion), (heard, portion)


CHANGED_AROUND_A_UNIT = [
    'при сто ну градусов Цельсия',                 # a filler IN the middle is another word
    'при сто градусов вот Цельсия',
    'при сто градусов Цельсия вчера',
    'при сто градусов',                            # the scale is dropped
    'при градусов Цельсия',                        # the number is dropped
    'при сто градусов Цельсия Фаренгейта',
]


@pytest.mark.parametrize('heard,portion', [
    ('при сто градусов Цельсия', 'при э 100 °C'),          # only the listener's hesitations are left out, never the portion's own
    ('пятьсот рублей', '500 э ₽'),
    ('двадцать метров в секунду', '20 эм м/с'),
], ids=['celsius', 'rubles', 'speed'])
def test_a_hesitation_inside_the_portion_is_part_of_the_portion(heard, portion):
    assert not acks(heard, portion), (heard, portion)


@pytest.mark.parametrize('heard', CHANGED_AROUND_A_UNIT, ids=[f'{i:02d}' for i in range(len(CHANGED_AROUND_A_UNIT))])
def test_what_is_added_or_dropped_around_a_unit_is_not_the_portion(heard):
    assert not acks(heard, 'при 100 °C'), heard


# -- a minus glued to its number inside a sentence ---------------------------------------------------------------------------
# razdel keeps «-5» / «−5» as ONE token after a word («Ночью было −5 °C», «до −140 °C») and splits the sign from the digits only at
# the start of a text or after punctuation. The one-token form was a protected literal that no «минус пять» could equal, with a unit
# or without one: a negative temperature in the middle of an answer hung on its natural repeat.

MINUS = [
    ('Ночью было −5 °C', 'Ночью было минус пять градусов Цельсия'),
    ('Ночью было -5 °C', 'Ночью было минус пять градусов Цельсия'),
    ('Температура упала до −140 °C', 'Температура упала до минус сто сорок градусов Цельсия'),
    ('Было −5,5 °C', 'Было минус пять целых пять десятых градуса Цельсия'),
    ('Было −5 °C', 'Было минус 5 градусов Цельсия'),
    ('Было −5 °F', 'Было минус пять градусов Фаренгейта'),
    ('Было −5 градусов', 'Было минус пять градусов'),
    ('Курс упал на −5 %', 'Курс упал на минус пять процентов'),
    ('Курс упал на −5%', 'Курс упал на минус пять процентов'),
    ('Долг составил −500 ₽', 'Долг составил минус пятьсот рублей'),
    ('Это −5', 'Это минус пять'),
    ('x -5', 'x минус пять'),
    ('10 -5', 'десять минус пять'),
    ('Было +5 °C', 'Было плюс пять градусов Цельсия'),                    # a plus was never glued: it stays so
    ('«−5 °C»', 'минус пять градусов Цельсия'),                           # after punctuation it was split already
]
NOT_THE_SAME_SIGN = [
    ('Было −5 °C', 'Было пять градусов Цельсия'),
    ('Было −5 °C', 'Было плюс пять градусов Цельсия'),
    ('Было −5 °C', 'Было минус шесть градусов Цельсия'),
    ('Было −5 °C', 'Было минус пять градусов Фаренгейта'),
    ('Было +5 °C', 'Было минус пять градусов Цельсия'),
    ('Было −5 градусов', 'Было пять градусов'),
    ('Было −5', 'Было 5'),
    ('Было -5', 'Было +5'),
    ('x -5', 'x пять'),
]


@pytest.mark.parametrize('written,spoken', MINUS, ids=[f'{i:02d}' for i in range(len(MINUS))])
def test_a_minus_glued_to_its_number_inside_a_sentence_is_a_minus_and_a_number(written, spoken):
    assert both_ways(written, spoken), (written, spoken, H.verdict(spoken, written), H.verdict(written, spoken))


@pytest.mark.parametrize('heard,portion', NOT_THE_SAME_SIGN, ids=[f'{i:02d}' for i in range(len(NOT_THE_SAME_SIGN))])
def test_another_sign_is_not_the_same_repeat(heard, portion):
    assert not acks(heard, portion) and not acks(portion, heard), (heard, portion)


def test_a_glued_minus_gives_the_same_atoms_as_a_minus_at_the_start_of_a_text():
    assert ru._canonical('x -5', ()) == ru._canonical('x − 5', ()) == ('x', '−', '#5')
    assert ru._canonical('10 -5', ()) == ru._canonical('10 − 5', ()) == ('#10', '−', '#5')
    assert ru._canonical('-5', ()) == ru._canonical('−5', ()) == ('−', '#5')
    assert ru._canonical('x −0,5', ()) == ('x', '−', '#0.5')


@pytest.mark.parametrize('text,atoms', [
    ('x -5-3', ('x', '#-5-3')), ('x −5/3', ('x', '#−5/3')), ('x -1.2.3', ('x', '#-1.2.3')), ('x -y', ('x', '-y')),
    ('x --5', ('x', '!symbol:--', '#5')),
], ids=['range', 'fraction', 'version', 'word', 'two-hyphens'])
def test_a_sign_in_front_of_anything_but_a_plain_number_stays_as_it_was(text, atoms):
    assert ru._canonical(text, ()) == atoms


# -- the pass itself --------------------------------------------------------------------------------------------------------

def test_the_unit_pass_keeps_what_it_is_given_and_what_it_does_not_know():
    assert ru._units(()) == ()
    atoms = ru._canonical('в 1945 году вода при 100 °C стоит $30 за 5 кг', (), True)
    before = tuple(atoms)
    merged = ru._units(atoms)
    assert atoms == before                                                  # a cached tuple is never changed
    assert [a.atom for a in merged] == ['в', '#ord:1945', 'год', 'вода', 'при', '#100', '°c', 'стоить', '#30', '$', 'за', '#5', 'kg']
    assert [a.kind for a in merged if a.atom in ('°c', '$', 'kg')] == ['u', 'u', 'u']
    assert ru._canonical('при 100 °C', ()) == ('при', '#100', '°c')         # the shared canonical form is not touched


# -- it never raises ----------------------------------------------------------------------------------------------------------

POOL = ('5 12 100 1,5 36,6 1945 пять сто двадцать тысяча полтора ноль минус плюс с половиной первый целых десятых сотых и 6 '
        '° °C °С ℃ ℉ °F ₽ $ € % км/ч м/с км м см мм кг г ч мин с сек руб руб. градус градуса градусов градусах Цельсия Фаренгейта '
        'по в час секунду секунд рубль рублей доллар долларов евро процентов килограммов э эм мм ну вот / - — . , ! ? ( ) '
        'c f C F K к Ф ₽500 $30 €5 5₽ 5$   ᜀ0').split(' ')


def test_the_matcher_never_raises_on_nonsense_made_of_units_and_numbers():
    rng = random.Random(20261103)
    for _ in range(1500):
        heard = ' '.join(rng.choice(POOL) for _ in range(rng.randint(1, 9)))
        portion = ' '.join(rng.choice(POOL) for _ in range(rng.randint(1, 9)))
        assert ru.match_current(heard, portion, H.FILLERS) in (None, 'ack', 'attempt'), (heard, portion)
        assert H.verdict(heard, portion).kind


SOLID = tuple(word for word in POOL if word not in {'э', 'эм', 'мм', 'ну', 'вот'})      # a portion keeps its own hesitations


def test_a_portion_is_its_own_repeat_whatever_numbers_and_units_it_holds():
    rng = random.Random(7)
    checked = 0
    for _ in range(800):
        portion = ' '.join(rng.choice(SOLID) for _ in range(rng.randint(2, 8)))
        if ru.match_current(portion, portion, H.FILLERS) is None:
            continue                       # (nothing but marks: no word to compare)
        checked += 1
        assert ru.match_current(portion, portion, H.FILLERS) == 'ack', portion
    assert checked > 400


# -- WAVE 2 / Task E2, ruling 5 (scoped re-review P3): a decimal said «N и M десятых», and the colloquial «N и M» ----------------------------------

# Only «…целых шесть десятых…» and digits were read as 36,6; the way a person says it («тридцать шесть и шесть десятых градуса Цельсия», or just
# «тридцать шесть и шесть») left the call waiting for ever when the portion was written «36,6 °C» (rr2_decimal.py).
# «N и M десятых / сотых / тысячных» is N.M, like «N целых M десятых». The colloquial «N и M» (no fraction word at all) is a decimal ONLY where the
# portion holds that very decimal: «тридцать шесть и шесть» is not 36,6 anywhere else («5 и 6» are two numbers).

AND_FRACTIONS = [
    ('36,6 °C', 'тридцать шесть и шесть десятых градуса Цельсия'),
    ('36,6 °C', 'тридцати шести и шести десятых градуса Цельсия'),
    ('около 36,6 °C', 'около тридцать шесть и шесть десятых градуса Цельсия'),
    ('около 36,6 °C', 'около тридцати шести и шести десятых градуса Цельсия'),
    ('около 36,6', 'около тридцать шесть и шесть десятых'),
    ('3,5', 'три и пять десятых'),
    ('0,5', 'ноль и пять десятых'),
    ('3,05', 'три и пять сотых'),
    ('3,14', 'три и четырнадцать сотых'),
    ('2,125', 'два и сто двадцать пять тысячных'),
    ('1,5 кг', 'один и пять десятых килограмма'),
    ('7,9 км/с', 'семь и девять десятых километра в секунду'),
    ('Температура тела 36,6 °C.', 'Температура тела тридцать шесть и шесть десятых градуса Цельсия'),
]


@pytest.mark.parametrize('written,spoken', AND_FRACTIONS, ids=[f'{i:02d}' for i in range(len(AND_FRACTIONS))])
def test_a_decimal_said_n_and_m_tenths_is_the_same_repeat_as_its_digits(written, spoken):
    assert both_ways(written, spoken), (written, spoken, H.verdict(spoken, written), H.verdict(written, spoken))


COLLOQUIAL = [
    ('около 36,6 °C', 'около тридцать шесть и шесть градусов Цельсия'),
    ('около 36,6 °C', 'около тридцати шести и шести градусов Цельсия'),
    ('36,6 °C', 'тридцать шесть и шесть градусов Цельсия'),
    ('около 36,6', 'около тридцать шесть и шесть'),
    ('3,5 кг', 'три и пять килограммов'),
    ('2,5 км', 'два и пять километров'),
    ('0,5', 'ноль и пять'),
    ('Температура тела 36,6 °C.', 'Температура тела тридцать шесть и шесть градусов Цельсия'),
    ('36,6 °C', 'э тридцать шесть и э шесть градусов Цельсия'),       # a hesitation inside is left out, as everywhere
    ('36,6 °C, а ещё 5 и 7 минут', 'тридцать шесть и шесть градусов Цельсия, а ещё пять и семь минут'),     # a plain «5 и 7» stays two numbers
]


@pytest.mark.parametrize('written,spoken', COLLOQUIAL, ids=[f'{i:02d}' for i in range(len(COLLOQUIAL))])
def test_the_colloquial_n_and_m_is_a_decimal_for_a_portion_that_holds_that_decimal(written, spoken):
    assert acks(spoken, written), (written, spoken, H.verdict(spoken, written))
    assert not acks(written, spoken), 'the portion in words holds no decimal: the digits are another number'


NOT_COLLOQUIAL = [
    # the portion does not hold that decimal
    ('около 36 °C', 'около тридцать шесть и шесть градусов Цельсия'),
    ('около 37,6 °C', 'около тридцать шесть и шесть градусов Цельсия'),
    ('около 36,7 °C', 'около тридцать шесть и шесть градусов Цельсия'),
    ('около 36,06 °C', 'около тридцать шесть и шесть градусов Цельсия'),
    ('около 36,6 °C', 'около тридцать шесть и семь градусов Цельсия'),
    ('около 36,6 °C', 'около тридцать шесть и шестьдесят градусов Цельсия'),     # numbers are compared as written: 36,60 is not 36,6
    ('около 36,6 °C', 'около шесть и тридцать шесть градусов Цельсия'),
    # no «и»: two numbers, never summed or joined
    ('около 36,6 °C', 'около тридцать шесть шесть градусов Цельсия'),
    ('около 36,6 °C', 'около тридцать шесть и шесть и градусов Цельсия'),
    # another unit, a dropped unit, an extra word
    ('около 36,6 °C', 'около тридцать шесть и шесть градусов Фаренгейта'),
    ('около 36,6 °C', 'около тридцать шесть и шесть'),
    ('около 36,6 °C', 'около тридцать шесть и шесть градусов Цельсия по шкале'),
    ('5 °C', 'пять и шесть градусов Цельсия'),
    ('5 и 6 °C', 'пять и шесть десятых градусов Цельсия'),
    # only «и» joins the numbers
    ('около 36,6 °C', 'около тридцать шесть или шесть градусов Цельсия'),
    ('около 36,6 °C', 'около тридцать шесть а шесть градусов Цельсия'),
    ('около 36,6 °C', 'около тридцать шесть с шестью градусов Цельсия'),
]


@pytest.mark.parametrize('written,spoken', NOT_COLLOQUIAL, ids=[f'{i:02d}' for i in range(len(NOT_COLLOQUIAL))])
def test_n_and_m_is_not_a_decimal_anywhere_else(written, spoken):
    assert not acks(spoken, written), (written, spoken, H.verdict(spoken, written))


DIFFERENT_AND_FRACTIONS = [
    ('36,6 °C', 'тридцать шесть и семь десятых градуса Цельсия'),
    ('36,6 °C', 'тридцать шесть и шесть сотых градуса Цельсия'),
    ('36,06 °C', 'тридцать шесть и шесть десятых градуса Цельсия'),
    ('36,6 °C', 'тридцать семь и шесть десятых градуса Цельсия'),
    ('36,6 °C', 'тридцать шесть и шесть десятых градуса Фаренгейта'),
    ('36,6 °C', 'тридцать шесть и шесть десятых'),
    ('3,5', 'три и пять сотых'),
]


@pytest.mark.parametrize('heard,portion', DIFFERENT_AND_FRACTIONS, ids=[f'{i:02d}' for i in range(len(DIFFERENT_AND_FRACTIONS))])
def test_another_decimal_said_n_and_m_tenths_is_not_the_same_repeat(heard, portion):
    assert not acks(heard, portion), (heard, portion, H.verdict(heard, portion))
    assert not acks(portion, heard), (portion, heard, H.verdict(portion, heard))


def test_a_colloquial_decimal_with_the_unit_dropped_is_an_attempt_at_the_portion():
    """The reading that joins «тридцать шесть и шесть» can make the difference between an attempt (the portion is replayed) and noise."""
    assert ru.match_current('около тридцать шесть и шесть', 'около 36,6 °C', H.FILLERS) == 'attempt'
    assert ru.match_current('около тридцать шесть и шесть градусов', 'около 36,6 °C', H.FILLERS) == 'attempt'


def test_a_portion_that_holds_both_n_and_m_and_the_decimal_is_still_its_own_repeat():
    """The colloquial reading is one more way to read what was heard, never the only one: a portion repeated word for word is its own repeat."""
    for portion in ('36 и 6 и 36,6', 'около 36,6 °C и 36 и 6 градусов', '5 и 6 и 5,6 кг', '36,6 и 36 и 6'):
        assert acks(portion, portion), portion
        assert ru.match_current(portion, portion, H.FILLERS) == 'ack', portion


def test_the_colloquial_decimal_follows_the_portion_in_a_live_dictation(tmp_path):
    """ControlledMedia as the host builds it: the listener says «тридцать шесть и шесть градусов Цельсия» for «36,6 °C» and the dictation moves on."""
    live = H.Dictation(tmp_path, 'Температура тела составляет 36,6 °C в норме.')
    assert any('36,6' in portion for portion in live.chunks), live.chunks
    while '36,6' not in live.current:
        before = live.index
        assert live.say(live.current).after == before + 1
    here = live.index
    out = live.say(live.current.replace('36,6 °C', 'тридцать шесть и шесть градусов Цельсия'))
    assert (out.before, out.after) == (here, here + 1), (live.chunks, out.types)
