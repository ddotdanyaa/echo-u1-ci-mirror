"""Wave G / G2: the local reference base answers «статья N НК» and «N счёт» exactly and at once - and nothing else.

The data are the public official tables of contents (consultant.ru, captured 04.11.2026); the questions are
CLASSES of wordings (keyword before/after the number, digits/ordinal digits/number words, lead words, trailing «это»,
codes by name or by letters, follow-ups from the history), never the phrases of one call.
"""
import importlib
import os
import subprocess
import sys
import unittest

from echo_sync import reference_kb
from echo_sync.reference_kb import lookup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NK19 = 'Статья 19 Налогового кодекса — налогоплательщики, плательщики сборов, плательщики страховых взносов.'
NK18 = 'Статья 18 Налогового кодекса — специальные налоговые режимы.'
NK15 = 'Статья 15 Налогового кодекса — местные налоги и сборы.'
NK21 = 'Статья 21 Налогового кодекса — права налогоплательщиков, плательщиков сборов, плательщиков страховых взносов.'
NK27 = 'Статья 27 Налогового кодекса — законный представитель налогоплательщика.'
A71 = 'Счёт 71 — расчёты с подотчётными лицами.'
A62 = 'Счёт 62 — расчёты с покупателями и заказчиками.'
A01 = 'Счёт 01 — основные средства.'
A99 = 'Счёт 99 — прибыли и убытки.'


class DataTests(unittest.TestCase):
    """The tables: counted against the pages they were built from, spot checks of the owner's list."""

    @classmethod
    def setUpClass(cls):
        load = lambda name: importlib.import_module('echo_sync.' + name)
        cls.nk, cls.gk, cls.tk, cls.acc = load('kb_nk'), load('kb_gk'), load('kb_tk'), load('kb_accounts')

    def test_counts_match_the_captured_pages(self):
        # 812 + 2 group lines of the NK pages (45.1-45.2, 86.1-86.3 are one line each) = 815 articles; ГК 1733 + 3; ТК 540; 62 + 11 accounts.
        self.assertEqual((len(self.nk.TITLES), self.nk.COUNT), (815, 815))
        self.assertEqual(sum(1 for key in self.nk.TITLES if int(key.split('.')[0].split('-')[0]) <= 142), 275)    # part 1
        self.assertEqual((len(self.gk.TITLES), self.gk.COUNT), (1736, 1736))
        self.assertEqual((len(self.tk.TITLES), self.tk.COUNT), (540, 540))
        self.assertEqual((len(self.acc.ACCOUNTS), self.acc.COUNT), (73, 73))
        self.assertEqual(sum(1 for key in self.acc.ACCOUNTS if len(key) == 2), 62)
        self.assertEqual(sum(1 for key in self.acc.ACCOUNTS if len(key) == 3), 11)

    def test_every_whole_number_of_the_codes_is_there_except_repealed_chapters(self):
        nk_ints = {int(key.split('.')[0].split('-')[0]) for key in self.nk.TITLES}
        self.assertEqual(sorted(set(range(1, 433)) - nk_ints),
                         list(range(234, 246)) + list(range(347, 356)) + list(range(364, 372)))   # chapters 24, 26.2.., 28.. repealed as a whole
        tk_ints = {int(key.split('.')[0].split('-')[0]) for key in self.tk.TITLES}
        self.assertEqual(sorted(set(range(1, 425)) - tk_ints), [])
        gk_ints = {int(key.split('.')[0].split('-')[0]) for key in self.gk.TITLES}
        self.assertEqual(sorted(set(range(1, 1542)) - gk_ints),
                         [95, 105] + list(range(107, 113)) + list(range(116, 123)))

    def test_spot_checks(self):
        titles = self.nk.TITLES
        self.assertEqual(titles['15'], 'Местные налоги и сборы')
        self.assertEqual(titles['18'], 'Специальные налоговые режимы')
        self.assertTrue(titles['19'].startswith('Налогоплательщики, плательщики сборов'))
        self.assertTrue(titles['21'].startswith('Права налогоплательщиков'))
        self.assertTrue(titles['27'].startswith('Законный представитель налогоплательщика'))
        self.assertEqual(titles['105.1'], 'Взаимозависимые лица')
        self.assertIn('105.16-1', titles)
        self.assertEqual(self.acc.ACCOUNTS['71'], 'Расчеты с подотчетными лицами')
        self.assertEqual(self.acc.ACCOUNTS['62'], 'Расчеты с покупателями и заказчиками')
        self.assertEqual(self.acc.ACCOUNTS['01'], 'Основные средства')
        self.assertEqual(self.acc.ACCOUNTS['99'], 'Прибыли и убытки')
        self.assertEqual(self.acc.ACCOUNTS['001'], 'Арендованные основные средства')
        self.assertEqual(self.acc.ACCOUNTS['011'], 'Основные средства, сданные в аренду')

    def test_the_capture_date_is_in_every_module(self):
        for module in (self.nk, self.gk, self.tk, self.acc):
            self.assertEqual(module.CAPTURED, '2026-11-04')
        self.assertEqual(reference_kb.CAPTURED, '2026-11-04')

    def test_the_plan_leaves_the_known_numbers_unused(self):
        for number in ('06', '12', '13', '17', '18', '22', '24', '27', '30', '39', '47', '49', '53', '54', '56', '61', '64',
                       '65', '72', '74', '78', '85', '87', '89', '92', '93', '95'):
            self.assertNotIn(number, self.acc.ACCOUNTS)

    def test_all_tables_load_ahead_of_time(self):
        self.assertTrue(reference_kb.preload())


class PositiveTests(unittest.TestCase):
    """Wordings of one question in many shapes: each has to give the title, spoken as one sentence."""

    ARTICLE_19 = [
        'статья 19 налогового кодекса', 'Статья 19 НК.', 'статья 19 НК РФ', 'ст. 19 НК', 'ст.19 НК РФ', 'ст 19 нк',
        '19-я статья НК', '19-я статья налогового кодекса', '19 статья налогового кодекса', 'девятнадцатая статья НК',
        'девятнадцатая статья налогового кодекса', 'девятнадцатая статья налогового кодекса Российской Федерации',
        'статьи девятнадцать НК', 'статья девятнадцать налогового кодекса', 'статья девятнадцатая налогового кодекса',
        'в девятнадцатой статье налогового кодекса', 'налоговый кодекс статья 19', 'Налоговый кодекс, статья 19', 'НК РФ статья 19',
        'НК, 19 статья', 'статья номер 19 налогового кодекса', 'статья № 19 НК', 'в налоговом кодексе статья 19',
        'по налоговому кодексу 19 статья', 'эн ка статья 19',
        # lead words, question words, trailing «это» - the way it is said in a call
        'Что такое статья 19 налогового кодекса?', 'Что такое 19 статья НК', 'что за статья 19 налогового кодекса',
        'про что статья 19 НК', 'о чем статья 19 налогового кодекса', 'какая это статья 19 НК', 'как называется статья 19 НК',
        'Так, девятнадцатая статья налогового кодекса это', 'ну 19-я статья НК это что', 'Подскажите, статья 19 НК РФ',
        'Скажите пожалуйста, 19 статья налогового кодекса, это про что', 'а что такое статья 19 НК', 'и статья 19 налогового кодекса',
        'чему посвящена статья 19 НК', 'что означает статья 19 налогового кодекса', 'Так, статья девятнадцать, налоговый кодекс, это',
    ]

    def test_article_19_in_every_wording(self):
        self.assertGreaterEqual(len(self.ARTICLE_19), 40)
        for text in self.ARTICLE_19:
            with self.subTest(text=text):
                self.assertEqual(lookup(text), NK19)

    def test_the_owner_s_spot_checks(self):
        cases = {
            'статья 15 НК': NK15, 'пятнадцатая статья налогового кодекса': NK15, 'ст. 18 НК РФ': NK18, 'восемнадцатая статья НК': NK18,
            'Так, восемнадцатая статья налогового кодекса это': NK18, 'статья 21 НК': NK21, 'двадцать первая статья налогового кодекса': NK21,
            'статья 27 НК': NK27, 'двадцать седьмая статья налогового кодекса': NK27, 'в двадцать седьмой статье НК': NK27,
            '71 счёт': A71, 'семьдесят первый счёт': A71, 'счёт 71': A71, 'что за 71 счёт': A71, '62 счёт': A62, 'что за 62 счёт': A62,
            'шестьдесят второй счёт': A62, 'первый счёт': A01, 'счёт 01': A01, '01 счёт': A01, '99 счёт': A99, 'девяносто девятый счёт': A99,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(lookup(text), expected)

    def test_asr_variants_heard_in_real_calls(self):
        """A cloud ASR writes «21-ая», «пятнадцатое статья», «план счетов» before the number: the class is tolerated, not the phrase."""
        cases = {
            '21-ая статья налогового кодекса. Что такое': NK21, 'хорошо пятнадцатое статья налогового кодекса что такое': NK15,
            'пятнадцатая статья налогового кодекса': NK15, 'так что такое двадцать седьмая статья налогового кодекса': NK27,
            'так план счетов семьдесят первый счёт это что': A71, 'семьдесят первый план счетов про что': A71,
            'Ну, что такое двадцать первая статья Налогового кодекса?': NK21, 'Так, что такое пятнадцатая статья Налогового кодекса': NK15,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(lookup(text), expected)

    def test_accounts_in_every_wording(self):
        for text in ('71 счёт', 'семьдесят первый счёт', 'счёт 71', 'счёт семьдесят один', 'Счет 71.', '71-й счёт', '71 план счетов',
                     'в плане счетов 71', 'счёт 71 в плане счетов', 'что за 71 счёт', 'Что такое 71 счёт?', 'как называется 71 счёт',
                     'семьдесят первый счёт это что', 'на счёте 71', 'про 71 счёт', 'Так, 71 счёт это', 'счёт 71 бухгалтерского учета', 'а что за счёт 71'):
            with self.subTest(text=text):
                self.assertEqual(lookup(text), A71)

    def test_off_balance_accounts(self):
        for text in ('забалансовый счёт 001', 'счёт 001', '001 счёт', 'забалансовый счёт 1', 'что за забалансовый счёт один'):
            with self.subTest(text=text):
                self.assertEqual(lookup(text), 'Забалансовый счёт 001 — арендованные основные средства.')
        self.assertEqual(lookup('счёт 011'), 'Забалансовый счёт 011 — основные средства, сданные в аренду.')
        self.assertEqual(lookup('счёт 10'), 'Счёт 10 — материалы.')

    def test_other_codes_and_decimal_numbers(self):
        cases = {
            'статья 10 гражданского кодекса': 'Статья 10 Гражданского кодекса — пределы осуществления гражданских прав.',
            'десятая статья ГК РФ': 'Статья 10 Гражданского кодекса — пределы осуществления гражданских прав.',
            'статья тысяча сто пятьдесят один ГК': 'Статья 1151 Гражданского кодекса — наследование выморочного имущества.',
            'ст. 81 ТК РФ': 'Статья 81 Трудового кодекса — расторжение трудового договора по инициативе работодателя.',
            'восемьдесят первая статья трудового кодекса': 'Статья 81 Трудового кодекса — расторжение трудового договора по инициативе работодателя.',
            'статья 105.1 налогового кодекса': 'Статья 105.1 Налогового кодекса — взаимозависимые лица.',
            'статья сто пять точка один НК': 'Статья 105.1 Налогового кодекса — взаимозависимые лица.',
            'статья 105 НК': 'Статья 105 Налогового кодекса — рассмотрение дел и иных материалов о правонарушениях в сфере налогов и сборов и о налоговых правонарушениях.',
            'сто пятая статья налогового кодекса': 'Статья 105 Налогового кодекса — рассмотрение дел и иных материалов о правонарушениях в сфере налогов и сборов и о налоговых правонарушениях.',
            'статья 346.11 НК': 'Статья 346.11 Налогового кодекса — общие положения.',
            'статья 144 НК': 'Статья 144 Налогового кодекса утратила силу.',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                got = lookup(text)
                if expected.endswith('Налогового кодекса — рассмотрение дел и иных материалов о правонарушениях в сфере налогов и сборов и о налоговых правонарушениях.'):
                    self.assertTrue(got and got.startswith('Статья 105 Налогового кодекса — '), got)
                else:
                    self.assertEqual(got, expected)

    def test_the_answer_is_one_spoken_sentence(self):
        for text in ('статья 19 НК', 'статья 21 НК', '71 счёт', 'статья 1 НК', 'статья 56.1 НК', 'статья 25.12-1 НК', 'статья 10 ГК'):
            with self.subTest(text=text):
                answer = lookup(text)
                self.assertTrue(answer, text)
                self.assertTrue(answer.endswith('.') and not answer.endswith('..'), answer)
                self.assertNotIn('\n', answer)
                self.assertNotIn('"', answer)
                self.assertNotIn('(', answer)
                self.assertEqual(answer.count('. '), 0, answer)
                self.assertIn('ё' if 'счёт' in answer.lower() else '', answer)

    def test_yo_and_quotes_are_spoken(self):
        self.assertIn('расчёты', lookup('счёт 71') + lookup('счёт 62'))
        self.assertIn('Сириус', lookup('статья 1 налогового кодекса'))
        self.assertIn('«Сириус»', lookup('статья 1 налогового кодекса'))

    def test_a_repealed_article_says_so(self):
        self.assertEqual(lookup('статья 144 НК'), 'Статья 144 Налогового кодекса утратила силу.')
        self.assertEqual(lookup('статья 45.2 НК'), 'Статья 45.2 Налогового кодекса утратила силу.')


class FollowUpTests(unittest.TestCase):
    """«а 27-я?» takes the code (or the plan of accounts) from the last lines of the conversation."""

    NK_HISTORY = ['Что такое 18 статья налогового кодекса?']
    NK_ANSWER = [NK18]
    ACCOUNT_HISTORY = ['что за 71 счёт', A71]

    def test_follow_ups_after_a_code(self):
        for text in ('а 27-я?', 'а двадцать седьмая?', 'А 27-я', 'и 27-я?', 'а 27?', 'а двадцать семь?', 'а статья 27?', 'а в 27-й статье?',
                     'а что насчёт 27-й статьи?', 'а про 27 статью?', 'ну а двадцать седьмая статья?', 'Так, а 27-я?', 'Ну, а двадцать седьмая?', 'хорошо, и 27-я?','а 27 статья это что', 'статья 27', 'двадцать седьмая статья?'):
            for history in (self.NK_HISTORY, self.NK_ANSWER, [NK18, 'ага', 'спасибо']):
                with self.subTest(text=text, history=history):
                    self.assertEqual(lookup(text, history), NK27)

    def test_follow_up_after_an_account(self):
        for text in ('а 62-й?', 'а шестьдесят второй?', 'а 62?', 'а 62 счёт?', 'а счёт 62?', 'и шестьдесят второй?'):
            with self.subTest(text=text):
                self.assertEqual(lookup(text, self.ACCOUNT_HISTORY), A62)

    def test_follow_up_chain_uses_its_own_answers(self):
        history = list(self.NK_HISTORY)
        history.append(lookup('а 27-я?', history))
        self.assertEqual(lookup('а 21-я?', history), NK21)
        history.append(lookup('а 21-я?', history))
        self.assertEqual(lookup('а девятнадцатая?', history), NK19)

    def test_follow_up_in_another_code(self):
        history = ['статья 10 гражданского кодекса']
        self.assertTrue(lookup('а 11-я?', history).startswith('Статья 11 Гражданского кодекса — '))
        history = ['Статья 81 Трудового кодекса — расторжение трудового договора по инициативе работодателя.']
        self.assertTrue(lookup('а 77-я?', history).startswith('Статья 77 Трудового кодекса — '))

    def test_no_code_in_the_history_no_answer(self):
        for text in ('а 27-я?', 'а двадцать седьмая?', 'а 27?', 'а статья 27?', 'статья 27'):
            for history in ((), [], [''], ['привет, как дела'], ['статья 19 Конституции'], [None, 5, b'x'], 'нет', None):
                with self.subTest(text=text, history=history):
                    self.assertIsNone(lookup(text, history))

    def test_the_history_given_is_read_as_it_is(self):
        # the window of the call's questions is the controller's one selector (``call_questions``, tests/test_w2_prepared.py), not a number of this module
        self.assertEqual(lookup('а 27-я?', ['что такое 18 статья налогового кодекса', 'а', 'б', 'в']), NK27)

    def test_the_gender_must_fit_the_kind(self):
        self.assertIsNone(lookup('а 62-й?', self.NK_HISTORY))                # «62-й» is a masculine ordinal: a code has articles
        self.assertIsNone(lookup('а двадцать седьмая?', self.ACCOUNT_HISTORY))   # accounts are masculine
        self.assertIsNone(lookup('а 27-я?', self.ACCOUNT_HISTORY))

    def test_the_explicit_code_beats_the_history(self):
        self.assertEqual(lookup('а статья 27 налогового кодекса?', ['статья 10 гражданского кодекса']), NK27)
        self.assertEqual(lookup('статья 19 НК', ['счёт 71']), NK19)

    def test_a_follow_up_that_asks_more_is_not_answered(self):
        for text in ('а 27-я какая ставка?', 'а 27-я, расскажи подробнее', 'а сколько в 27-й?', 'а 27-я почему?'):
            with self.subTest(text=text):
                self.assertIsNone(lookup(text, self.NK_HISTORY))


class NegativeTests(unittest.TestCase):
    """Everything that is not a plain question about a name goes on to the normal path."""

    NEGATIVE = [
        # another document, or a number that is not in the base
        'статья 19 Конституции', 'статья 19 Конституции Российской Федерации', 'статья 19 закона о бухгалтерском учёте',
        'статья 19 закона об ООО', 'статья 19 уголовного кодекса', 'девятнадцатая статья', 'статья 19', '19-я статья',
        'статья 999 налогового кодекса', 'статья 2000 гражданского кодекса', 'статья 500 трудового кодекса', 'статья 234 налогового кодекса',
        'статья 0 налогового кодекса', 'статья 019 налогового кодекса', 'статья -19 НК', 'статья 19.99 НК', 'статья 19,5 НК',
        'счёт 12', 'счёт 06', 'счёт 100', 'счёт 90.1', 'счёт 000', 'счёт 012', 'счёт 99.5',
        # not the Plan of accounts at all
        'счёт в банке', 'выставили счёт', 'счёт 2:1', 'счёт 12:30', 'ничья, счёт 2 1', 'счёт 71 000 рублей', 'счёт на 71 тысяча',
        'счёт-фактура 71', 'оплатите счёт 62 до пятницы', 'счёт 62 на оплату', 'счёт 71 в банке', 'на счёте 71 лежит миллион', 'счёт 62 и 71',
        'счёт', 'статья', 'план счетов', 'налоговый кодекс', 'нк', 'какой кодекс',
        # asks more than the title can say
        'какая ставка по статье 19 налогового кодекса', 'сколько штраф по статье 19 НК', 'почему статья 19 НК так устроена',
        'пример по статье 19 НК', 'в какой срок по статье 19 НК', 'расскажи про статью 19 налогового кодекса', 'объясни статью 19 НК',
        'статья 19 НК, какие сроки', 'сумма по статье 19 НК', 'по статье 19 НК как это применять', 'что говорится в статье 19 НК',
        'можно ли по статье 19 НК', 'статья 19 налогового кодекса обязывает платить налоги', 'какая ставка по 71 счёту', 'проводка по счёту 71',
        'сколько проводок по 62 счёту', 'почему 62 счёт дебетуется', 'для чего нужен 62 счёт', 'расскажи про 71 счёт', 'пример проводки по счёту 71',
        'в 2018 году статья 19 НК изменилась', 'статья 19 НК в редакции 2020 года', 'ст. 19 НК РФ и ст. 20', 'статья 18 и статья 19 НК',
        'статьи 18 и 19 НК', 'статья 19 налогового кодекса и гражданского кодекса', 'статья 19 НК и 71 счёт',
        # arithmetic, small talk, the calls of 04.11
        'сорок восемь умножить на десять', 'Так, двадцать три, хорошо. Значит, сорок восемь умножить на десять', 'сколько будет десять плюс тринадцать',
        'привет', 'спасибо большое', 'угу', 'а 27-я?', 'и вот статья', 'ну да статья статья', '', '   ', '?', '...',
    ]

    def test_negatives(self):
        self.assertGreaterEqual(len(self.NEGATIVE), 20)
        for text in self.NEGATIVE:
            with self.subTest(text=text):
                self.assertIsNone(lookup(text))

    def test_negatives_with_a_code_in_the_history(self):
        history = ['Что такое 18 статья налогового кодекса?', NK18]
        for text in ('статья 19 Конституции', 'счёт в банке', 'какая ставка по статье 19', 'расскажи про 27-ю', 'сколько будет 27 умножить на 3',
                     'а 27 умножить на 3', 'а сколько?', 'а почему?', 'а 999-я?', 'а 234-я?'):
            with self.subTest(text=text):
                self.assertIsNone(lookup(text, history))

    def test_a_long_speech_is_not_a_question_about_a_name(self):
        text = 'Значит, смотрите, у нас в договоре сказано, что по статье 19 налогового кодекса мы обязаны это сделать до пятницы, ' \
               'и тогда по статье 21 налогового кодекса вы вправе потребовать разъяснений, и ещё статья 27 налогового кодекса, и счёт 71.'
        self.assertIsNone(lookup(text))
        self.assertIsNone(lookup('статья 19 НК ' + 'это ' * 40))


class RobustnessTests(unittest.TestCase):
    def test_lookup_never_raises(self):
        garbage = [None, 0, 1.5, b'statya 19', object(), [], ['статья 19 НК'], {'a': 1}, True, '\x00', '\ud800', 'ё' * 10000, '9' * 5000,
                   'статья ' + '9' * 300 + ' НК', '19' * 200, '‮19 статья НК', 'статья ٣ НК', 'статья １９ НК', '⁹⁹ статья НК', '٧١ счёт',
                   'ст.' * 300, '(' * 500, 'á' * 200, '😀 статья 19 НК', 'статья 19 НК 😀', '\n\n\t']
        for text in garbage:
            with self.subTest(text=repr(text)[:40]):
                result = lookup(text)
                self.assertTrue(result is None or isinstance(result, str))
        for history in (None, 5, 5.5, object(), [None], [[]], [b'x'], ['x' * 100000], iter(['a']), {1: 2}, (1, 2, 3), 'статья 19 НК'):
            with self.subTest(history=repr(history)[:40]):
                result = lookup('а 27-я?', history)
                self.assertTrue(result is None or isinstance(result, str))

    def test_the_history_may_be_a_tuple_or_a_list(self):
        self.assertEqual(lookup('а 27-я?', ('статья 18 НК',)), NK27)
        self.assertEqual(lookup('а 27-я?', ['статья 18 НК']), NK27)

    def test_a_missing_table_is_a_none_not_an_error(self):
        saved = dict(reference_kb._DATA)
        try:
            reference_kb._DATA[('kb_nk', 'TITLES')] = None
            self.assertIsNone(lookup('статья 19 НК'))
            reference_kb._DATA[('kb_accounts', 'ACCOUNTS')] = None
            self.assertIsNone(lookup('71 счёт'))
        finally:
            reference_kb._DATA.clear()
            reference_kb._DATA.update(saved)
        self.assertEqual(lookup('статья 19 НК'), NK19)

    def test_the_lookup_is_fast(self):
        import time
        lookup('статья 19 НК')
        started = time.perf_counter()
        for _ in range(200):
            lookup('Так, восемнадцатая статья налогового кодекса это')
            lookup('Сколько будет десять плюс тринадцать')
        self.assertLess((time.perf_counter() - started) / 400, 0.002)       # a warm lookup is well under 2 ms


class ImportTests(unittest.TestCase):
    def test_import_is_cheap_and_loads_no_table(self):
        code = ('import sys, time\n'
                'import echo_sync, echo_sync.ru_numbers\n'
                'LIBS = ("pymorphy3", "razdel", "rapidfuzz", "requests", "urllib3", "numpy")\n'
                'before = [m for m in LIBS if m in sys.modules]\n'          # the package itself (the plugin, the classifier) has its own libraries: only what the KB adds counts
                't = time.perf_counter()\n'
                'import echo_sync.reference_kb as kb\n'
                'ms = (time.perf_counter() - t) * 1000\n'
                'tables = [m for m in sys.modules if m.startswith("echo_sync.kb_")]\n'
                'heavy = [m for m in LIBS if m in sys.modules and m not in before]\n'
                'print(ms, tables, heavy)\n')
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join([ROOT] + [p for p in env.get('PYTHONPATH', '').split(os.pathsep) if p])
        done = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        ms, rest = done.stdout.strip().split(' ', 1)
        self.assertLess(float(ms), 100.0, done.stdout)
        self.assertTrue(rest.startswith('[] []'), done.stdout)          # no table, no morphology library, no network client was imported

    def test_the_modules_have_no_network_or_morphology_imports(self):
        for name in ('reference_kb', 'kb_nk', 'kb_gk', 'kb_tk', 'kb_accounts', 'kb_yo'):
            with open(os.path.join(ROOT, 'echo_sync', name + '.py'), encoding='utf-8') as handle:
                source = handle.read()
            for forbidden in ('import requests', 'import urllib', 'import socket', 'import http', 'pymorphy3', 'razdel', 'subprocess', 'open('):
                self.assertNotIn(forbidden, source, (name, forbidden))


class PrefaceTests(unittest.TestCase):
    """Candidate 12, the owner's real wordings: a reference that ends an utterance is read past the preface; anything that wants more is not."""

    def test_the_reference_after_a_preface(self):
        for text in ('Ну и короче я готов. А какой вопрос? Вопрос получается двадцать первая статья налогового кодекса.',
                     'Ну и, короче, я готов. А какой вопрос? Вопрос получается двадцать первая статья Налогового кодекса',
                     'Вопрос получается 21 статья налогового кодекса.',
                     'Блин, ты еще и не отвечаешь, когда я тебе говорю, что это тебе нужно обязательно сказать, что такое двадцать первая статья Налогового кодекса'):
            self.assertEqual(lookup(text), NK21, text)

    def test_the_account_after_a_preface(self):
        self.assertEqual(lookup('Так, я готов. Следующий вопрос семьдесят первый счёт.'), A71)

    def test_more_than_a_title_is_not_a_reference(self):
        for text in ('Как применяется вычет, статья 218 НК',
                     'Статья 21 НК. А что там с вычетами?',
                     'Я про статью 19, а статья 21 НК?',
                     'Сколько платить по пени статья 75 НК',
                     'Тебе нужно обязательно сказать что такое статья 21 НК',
                     'Ну и короче я готов. Двадцать первая статья',
                     'Мы готовы. Двадцать один.'):
            self.assertIsNone(lookup(text), text)



if __name__ == '__main__':
    unittest.main()
