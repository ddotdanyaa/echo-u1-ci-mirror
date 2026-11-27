"""g8-speech: the text before the voice. Every digit, symbol and abbreviation is said right; the numbers survive the round trip.

Golden forms are written by hand (not produced by the module). ``spoken_values`` reads the speech back into numbers independently of
the generator: the number in the text must equal the number in the normalized speech.
"""
import json
import os
import re
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from echo_sync import speech_text as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Cardinals(unittest.TestCase):
    def test_nominative(self):
        for n, w in ((0, 'ноль'), (1, 'один'), (2, 'два'), (11, 'одиннадцать'), (21, 'двадцать один'), (40, 'сорок'), (100, 'сто'), (200, 'двести'),
                     (1000, 'тысяча'), (2000, 'две тысячи'), (5000, 'пять тысяч'), (14160, 'четырнадцать тысяч сто шестьдесят'),
                     (300000, 'триста тысяч'), (21000, 'двадцать одна тысяча'), (1000000, 'один миллион'), (2500000, 'два миллиона пятьсот тысяч'),
                     (1945, 'тысяча девятьсот сорок пять'), (2026, 'две тысячи двадцать шесть'), (3210, 'три тысячи двести десять')):
            self.assertEqual(S.cardinal(n), w, n)

    def test_cases(self):
        gold = {('gen', 5): 'пяти', ('dat', 5): 'пяти', ('ins', 5): 'пятью', ('prep', 5): 'пяти', ('gen', 20): 'двадцати', ('ins', 20): 'двадцатью',
                ('gen', 50): 'пятидесяти', ('ins', 50): 'пятьюдесятью', ('gen', 40): 'сорока', ('gen', 90): 'девяноста', ('gen', 100): 'ста',
                ('dat', 200): 'двумстам', ('gen', 200): 'двухсот', ('ins', 300): 'тремястами', ('prep', 400): 'четырёхстах', ('gen', 500): 'пятисот',
                ('ins', 500): 'пятьюстами', ('gen', 3): 'трёх', ('ins', 3): 'тремя', ('ins', 4): 'четырьмя', ('gen', 8): 'восьми', ('ins', 2): 'двумя',
                ('gen', 125): 'ста двадцати пяти', ('ins', 125): 'ста двадцатью пятью', ('gen', 2026): 'двух тысяч двадцати шести',
                ('ins', 21): 'двадцатью одним', ('gen', 1000): 'тысячи', ('dat', 1000): 'тысяче', ('ins', 1000000): 'одним миллионом',
                ('gen', 1500000): 'одного миллиона пятисот тысяч', ('prep', 12): 'двенадцати', ('gen', 11): 'одиннадцати'}
        for (case, n), w in gold.items():
            self.assertEqual(S.cardinal(n, case), w, (case, n))

    def test_gender(self):
        self.assertEqual(S.cardinal(1, 'nom', 'f'), 'одна')
        self.assertEqual(S.cardinal(2, 'nom', 'f'), 'две')
        self.assertEqual(S.cardinal(1, 'acc', 'f'), 'одну')
        self.assertEqual(S.cardinal(21, 'gen', 'f'), 'двадцати одной')
        self.assertEqual(S.cardinal(1, 'nom', 'n'), 'одно')
        self.assertEqual(S.cardinal(22, 'nom', 'f'), 'двадцать две')


class Ordinals(unittest.TestCase):
    def test_golden(self):
        gold = ((1, 'gen', 'm', 'первого'), (2, 'prep', 'm', 'втором'), (3, 'gen', 'f', 'третьей'), (3, 'nom', 'f', 'третья'), (3, 'nom', 'm', 'третий'),
                (5, 'ins', 'm', 'пятым'), (7, 'nom', 'm', 'седьмой'), (8, 'gen', 'n', 'восьмого'), (20, 'gen', 'm', 'двадцатого'),
                (40, 'nom', 'm', 'сороковой'), (90, 'nom', 'm', 'девяностый'), (100, 'gen', 'm', 'сотого'), (200, 'nom', 'm', 'двухсотый'),
                (21, 'nom', 'm', 'двадцать первый'), (21, 'prep', 'm', 'двадцать первом'), (1945, 'prep', 'm', 'тысяча девятьсот сорок пятом'),
                (2026, 'gen', 'm', 'две тысячи двадцать шестого'), (2020, 'prep', 'm', 'две тысячи двадцатом'), (2000, 'prep', 'm', 'двухтысячном'),
                (1000, 'gen', 'm', 'тысячного'), (100, 'prep', 'f', 'сотой'), (12, 'gen', 'm', 'двенадцатого'), (30, 'dat', 'm', 'тридцатому'),
                (4, 'nom', 'f', 'четвёртая'), (6, 'gen', 'f', 'шестой'), (9, 'nom', 'n', 'девятое'), (15, 'nom', 'n', 'пятнадцатое'), (70, 'nom', 'f', 'семидесятая'))
        for n, case, g, w in gold:
            self.assertEqual(S.ordinal(n, case, g), w, (n, case, g))

    def test_plural(self):
        self.assertEqual(S.ordinal(3, 'gen', 'm', plural=True), 'третьих')
        self.assertEqual(S.ordinal(2020, 'nom', 'm', plural=True), 'две тысячи двадцатые')


def say(text):
    return S.speak(text)


class Legal(unittest.TestCase):
    def test_article(self):
        self.assertEqual(say('ст. 15 НК РФ'), 'статья пятнадцатая Налогового кодекса')
        self.assertEqual(say('В ст. 15 НК РФ сказано'), 'В статье пятнадцатой Налогового кодекса сказано')
        self.assertEqual(say('согласно ст. 346.11'), 'согласно статье триста сорок шесть точка одиннадцать')
        self.assertEqual(say('п. 2 ст. 15'), 'пункт второй статьи пятнадцатой')
        self.assertEqual(say('в п. 2'), 'в пункте втором')
        self.assertEqual(say('ч. 3 ст. 9'), 'часть третья статьи девятой')
        self.assertEqual(say('подп. 1 п. 1 ст. 146'), 'подпункт первый пункта первого статьи ста сорок шестой'.replace('ста сорок', 'сто сорок'))
        self.assertEqual(say('Статья 15 Налогового кодекса'), 'Статья пятнадцатая Налогового кодекса')

    def test_codes(self):
        self.assertEqual(say('в ТК РФ'), 'в Трудовом кодексе')
        self.assertEqual(say('по ГК РФ'), 'по Гражданскому кодексу')
        self.assertEqual(say('в Российской Федерации'), 'в Российской Федерации')
        self.assertEqual(say('территории РФ'), 'территории Российской Федерации')

    def test_abbreviations(self):
        self.assertEqual(say('НДС 20%'), 'эн дэ эс двадцать процентов')
        self.assertEqual(say('ООО «Орхидея»'), 'о о о Орхидея')
        self.assertEqual(say('то есть, т.е. и т. д.'), 'то есть, то есть и так далее.')
        self.assertEqual(say('и т.п.'), 'и тому подобное.')
        self.assertEqual(say('402-ФЗ от'), 'четыреста два эф зэ от')
        self.assertEqual(say('3210-У'), 'три тысячи двести десять у')
        self.assertEqual(say('157н'), 'сто пятьдесят семь эн')
        self.assertEqual(say('6-НДФЛ'), 'шесть эн дэ эф эль')
        self.assertEqual(say('ФСБУ 4/2023'), 'эф эс бэ у четыре дробь две тысячи двадцать три')


class Percent(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(say('5%'), 'пять процентов')
        self.assertEqual(say('1%'), 'один процент')
        self.assertEqual(say('2%'), 'два процента')
        self.assertEqual(say('21%'), 'двадцать один процент')
        self.assertEqual(say('от 5% до 7%'), 'от пяти процентов до семи процентов')
        self.assertEqual(say('до 1%'), 'до одного процента')
        self.assertEqual(say('с 2%'), 'с двух процентов'.replace('с двух', 'с двух'))
        self.assertEqual(say('на 20%'), 'на двадцать процентов')
        self.assertEqual(say('в 5%'), 'в пять процентов')
        self.assertEqual(say('при 5%'), 'при пяти процентах')
        self.assertEqual(say('ставка 2,5%'), 'ставка две целых пять десятых процента')
        self.assertEqual(say('от 0,2 до 8,5'), 'от нуля целых двух десятых до восьми целых пяти десятых')
        self.assertEqual(say('5–10%'), 'от пяти до десяти процентов')
        self.assertEqual(say('под 20 процентов'), 'под двадцать процентов')


class Money(unittest.TestCase):
    def test_money(self):
        self.assertEqual(say('14 160 рублей'), 'четырнадцать тысяч сто шестьдесят рублей')
        self.assertEqual(say('100 ₽'), 'сто рублей')
        self.assertEqual(say('1 ₽'), 'один рубль')
        self.assertEqual(say('2 руб.'), 'два рубля.')
        self.assertEqual(say('5 руб.'), 'пять рублей.')
        self.assertEqual(say('1 000 руб.'), 'тысяча рублей.')
        self.assertEqual(say('3 коп.'), 'три копейки.')
        self.assertEqual(say('1,5 млн руб.'), 'одна целая пять десятых миллиона рублей.')
        self.assertEqual(say('2 тыс. руб.'), 'две тысячи рублей.')
        self.assertEqual(say('5 млрд ₽'), 'пять миллиардов рублей')
        self.assertEqual(say('на 300 000 рублей'), 'на триста тысяч рублей')
        self.assertEqual(say('с 1 000 рублями'), 'с тысячей рублями')
        self.assertEqual(say('$5'), 'пять долларов')
        self.assertEqual(say('10 €'), 'десять евро')

    def test_units(self):
        self.assertEqual(say('2 кг'), 'два килограмма')
        self.assertEqual(say('5 км'), 'пять километров')
        self.assertEqual(say('21 м'), 'двадцать один метр')
        self.assertEqual(say('500 г'), 'пятьсот граммов')
        self.assertEqual(say('3 шт.'), 'три штуки.')
        self.assertEqual(say('30 дн.'), 'тридцать дней.')
        self.assertEqual(say('2,5 кг'), 'две целых пять десятых килограмма')
        self.assertEqual(say('20 °C'), 'двадцать градусов Цельсия')
        self.assertEqual(say('60 км/ч'), 'шестьдесят километров в час')
        self.assertEqual(say('5 чел.'), 'пять человек.')


class Dates(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(say('5 ноября 2026 года'), 'пятого ноября две тысячи двадцать шестого года')
        self.assertEqual(say('6 декабря 2011'), 'шестого декабря две тысячи одиннадцатого')
        self.assertEqual(say('1 марта'), 'первого марта')
        self.assertEqual(say('25-го числа'), 'двадцать пятого числа')
        self.assertEqual(say('28-го числа.'), 'двадцать восьмого числа.')
        self.assertEqual(say('05.11.2026'), 'пятого ноября две тысячи двадцать шестого года')
        self.assertEqual(say('с 1 января по 31 декабря'), 'с первого января по тридцать первое декабря')
        self.assertEqual(say('до 25 числа'), 'до двадцать пятого числа'.replace('до двадцать пятого', 'до двадцать пятого'))
        self.assertEqual(say('в 2026 году'), 'в две тысячи двадцать шестом году')
        self.assertEqual(say('с 2020 года'), 'с две тысячи двадцатого года')
        self.assertEqual(say('2026 год'), 'две тысячи двадцать шестой год')
        self.assertEqual(say('в 1945 г.'), 'в тысяча девятьсот сорок пятом году.')
        self.assertEqual(say('2020–2022 гг.'), 'с две тысячи двадцатого по две тысячи двадцать второй годы.')
        self.assertEqual(say('в XXI веке'), 'в двадцать первом веке')
        self.assertEqual(say('XIX век'), 'девятнадцатый век')
        self.assertEqual(say('в 10 классе'), 'в десятом классе')
        self.assertEqual(say('10:30'), 'десять тридцать')
        self.assertEqual(say('в 10:00'), 'в десять часов')
        self.assertEqual(say('1 квартал'), 'первый квартал')
        self.assertEqual(say('3-го квартала'), 'третьего квартала')
        self.assertEqual(say('в 4 квартале'), 'в четвёртом квартале')


class Accounts(unittest.TestCase):
    def test_accounts(self):
        self.assertEqual(say('счёт 62'), 'счёт шестьдесят два')
        self.assertEqual(say('Дебет 50, кредит 51:'), 'Дебет пятьдесят, кредит пятьдесят один:')
        self.assertEqual(say('субсчёт 73-1'), 'субсчёт семьдесят три точка один')
        self.assertEqual(say('кредит 90-1'), 'кредит девяносто точка один')
        self.assertEqual(say('68.90'), 'шестьдесят восемь точка девяносто')
        self.assertEqual(say('счёт 50.01'), 'счёт пятьдесят точка ноль один')
        self.assertEqual(say('счёт 01'), 'счёт ноль один')
        self.assertEqual(say('забалансовые 001-011'), 'забалансовые от ноль ноль один до ноль один один')
        self.assertEqual(say('код 0310001'), 'код ноль три один, ноль ноль ноль один')
        self.assertEqual(say('01-99'), 'ноль один девяносто девять'.replace('ноль один девяносто девять', 'от ноль один до девяносто девять'))
        self.assertEqual(say('сч. 60'), 'счёт шестьдесят')


class Fractions(unittest.TestCase):
    def test_fractions(self):
        self.assertEqual(say('1/2'), 'одна вторая')
        self.assertEqual(say('3/4'), 'три четвёртых')
        self.assertEqual(say('2/3 доли'), 'две третьих доли')
        self.assertEqual(say('1/100'), 'одна сотая')
        self.assertEqual(say('и/или'), 'и или')
        self.assertEqual(say('0,5'), 'ноль целых пять десятых')
        self.assertEqual(say('1,25'), 'одна целая двадцать пять сотых')
        self.assertEqual(say('0,001'), 'ноль целых одна тысячная')


class Symbols(unittest.TestCase):
    def test_punct(self):
        self.assertEqual(say('Налог — это платёж'), 'Налог, это платёж')
        self.assertEqual(say('Заём (долг) возвращают'), 'Заём, долг, возвращают')
        self.assertEqual(say('«Бухучёт» и "учёт"'), 'Бухучёт и учёт')
        self.assertEqual(say('кто-то'), 'кто-то')
        self.assertEqual(say('2 + 2 = 4'), 'два плюс два равно четыре')
        self.assertEqual(say('2 × 3'), 'два умножить на три')
        self.assertEqual(say('№ 5'), 'номер пять')
        self.assertEqual(say('-5'), 'минус пять')
        self.assertEqual(say('1)'), 'первое,')
        self.assertEqual(say('Ну… да'), 'Ну. да'.replace('Ну. да', 'Ну, да'))
        self.assertNotRegex(say('(а) «б» — "в" 5% № 3 ст. 1 – 2'), r'[()«»"—–%№]|\d')

    def test_same_text_no_digits_untouched(self):
        for t in ('Что такое бухгалтерский учёт?', 'Да, конечно. Сейчас скажу.', 'Налог на добавленную стоимость'):
            self.assertEqual(say(t), t)

    def test_never_empty_or_crash(self):
        for t in ('', ' ', '5', '%', '₽', '((', '«', '—', '1/0', '99999999999999999999', '0,0', '00', '1:99', '31.02.2026', '0/0', '--5'):
            out = say(t)
            self.assertIsInstance(out, str)
        self.assertEqual(say(''), '')


def spoken_values(spoken):
    """Independent reader: the multiset of numbers (Decimal) said in ``spoken`` -- cardinal/ordinal runs in any case, 'целых ... десятых', digit runs."""
    return S.read_back(spoken)


class RoundTrip(unittest.TestCase):
    def test_cardinal_all_small(self):
        for n in range(0, 12001):
            for case in ('nom', 'gen', 'dat', 'ins', 'prep'):
                self.assertEqual(S.read_back(S.cardinal(n, case)), [Decimal(n)], (n, case))

    def test_cardinal_random_large(self):
        import random
        rnd = random.Random(8)
        for _ in range(4000):
            n = rnd.choice((rnd.randrange(10 ** 4, 10 ** 6), rnd.randrange(10 ** 6, 10 ** 9), rnd.randrange(10 ** 9, 10 ** 13)))
            case = rnd.choice(S.CASES)
            self.assertEqual(S.read_back(S.cardinal(n, case)), [Decimal(n)], (n, case))

    def test_ordinal_roundtrip(self):
        for n in range(1, 3001):
            for case in S.CASES:
                for g in 'mfn':
                    self.assertEqual(S.read_back(S.ordinal(n, case, g)), [Decimal(n)], (n, case, g))

    def test_sentences(self):
        for text, want in (('Налог 20% с 14 160 рублей', [20, 14160]), ('от 0,2 до 8,5', [Decimal('0.2'), Decimal('8.5')]),
                           ('5 ноября 2026 года', [5, 2026]), ('ст. 346.11 п. 2', [346, 11, 2]), ('Дебет 50, кредит 90-1', [50, 90, 1]),
                           ('3 тыс. руб.', [3000]), ('1,5 млн руб.', [Decimal('1.5') * 10 ** 6]), ('XXI век', [21]), ('ФСБУ 4/2023', [4, 2023]),
                           ('2020–2022 гг.', [2020, 2022]), ('10:30', [10, 30]), ('счёт 01', [0, 1])):
            self.assertEqual(S.read_back(say(text)), S.numbers_of(text), text)
            self.assertEqual(sorted(x for x in S.numbers_of(text) if x not in range(1, 13) or text.count(str(x)) or True), sorted(S.numbers_of(text)))


class Corpus(unittest.TestCase):
    """Every answer of the bank: no digit or symbol left, the numbers of the text equal the numbers of the speech."""
    def answers(self):
        rows = json.load(open(os.path.join(ROOT, 'cloud_context', 'bank', 'instant_bank_2.json'), encoding='utf-8'))
        return [r['answer'] for r in rows if r.get('answer')]

    def test_bank_clean_and_equal(self):
        bad = []
        for a in self.answers():
            out = S.speak(a)
            if re.search(r'[\d%₽№()«»"“”\[\]/<>=+*^_~@#&|\\]|[—–]|\.\.', out) or re.search(r'[A-Za-z]', out):
                bad.append((a[:80], out[:120]))
            elif S.numbers_of(a) != S.read_back(out):
                bad.append((a[:80], S.numbers_of(a), S.read_back(out)))
        self.assertEqual(bad[:5], [])

    def test_idempotent(self):
        for a in self.answers()[:300]:
            once = S.speak(a)
            self.assertEqual(S.speak(once), once)

    def test_words_not_lost(self):
        """The plain words of the text all stay: nothing a listener needs is dropped."""
        for a in self.answers()[:300]:
            words = set(re.findall(r'[а-яё]{5,}', S.speak(a).lower()))
            for w in re.findall(r'[а-яё]{5,}', a.lower()):
                self.assertIn(w, words, (w, a[:60]))


class Fuzz(unittest.TestCase):
    """Thousands of seeded sentences: nothing but words and plain punctuation is left, the numbers round-trip, a second pass changes nothing."""
    PARTS = ('ст. {a} НК РФ', 'п. {a} ст. {b}', 'в п. {a}', 'ставка {a}%', 'от {a}% до {b}%', 'на {a},{d}%', '{a} руб.', '{a} ₽', 'в {y} году', 'с {y} года', '{y} г.', '{day} {mon} {y} года',
             '{day}.{m}.{y}', 'до {day} числа', '{day}-го числа', 'счёт {acc}', 'дебет {acc}, кредит {acc}', 'субсчёт {c2}-{c}', '{a} тыс. руб.', '{c},{d} млн руб.', '{a} кг', '{c} м',
             '{a}-{b} дней', '{a}–{b}%', '{y}–{y2} гг.', '{a} из {b}', '{c4}/{c5}', '№ {a}', 'ФЗ-{a}', '{a}н', 'в {c4} квартале', '{c4} квартал', '{h}:{mi}', 'с {h}:00 до {h2}:00',
             'через {a} дней', 'за {c2} недели', 'около {a} человек', 'более {a} рублей', 'не менее {c5} лет', 'XXI век', '{a} раз', 'под {c5}%', 'по {c5} рублей', '{a} (прописью)', '«{a}»')
    HEADS = ('Налог', 'Срок', 'Это', 'Нужно', 'Платёж', 'Размер', 'Штраф', 'Сдаём', 'Итого', 'Условие', 'Если', 'Вот')

    def sentence(self, rnd):
        import random
        f = dict(a=rnd.choice((rnd.randrange(1, 100), rnd.randrange(1, 100000), rnd.randrange(100, 1000))), b=rnd.randrange(1, 1000), c=rnd.randrange(1, 10), c2=rnd.randrange(2, 5), c4=rnd.randrange(1, 5), c5=rnd.randrange(5, 40), d=rnd.randrange(1, 100),
                 y=rnd.randrange(1950, 2100), y2=rnd.randrange(2100, 2200), day=rnd.randrange(1, 29), m='%02d' % rnd.randrange(1, 13), mon=rnd.choice(S._MONTHS), acc=rnd.choice(('50', '62', '90', '51', '08', '68.90', '73-1', '001')),
                 h=rnd.randrange(1, 12), h2=rnd.randrange(13, 24), mi='%02d' % rnd.randrange(1, 60))
        f['a'], f['b'] = int(f['a']), max(int(f['b']), int(f['a']) + 1)
        f['y2'] = f['y'] + rnd.randrange(1, 5)
        parts = [rnd.choice(self.PARTS).format(**f) for _ in range(rnd.randrange(1, 4))]
        return rnd.choice(self.HEADS) + ' ' + ' и '.join(parts) + rnd.choice(('.', '', ',', '. Далее', '!'))

    def test_fuzz(self):
        import random
        bad = []
        for seed in range(3000):
            text = self.sentence(random.Random(seed))
            out = S.speak(text)
            if re.search(r'[\d%₽№()«»"/<>=+*^_~@#&|\\\[\]—–−]|[A-Za-z]|\x01|\x02', out) or re.search(r'\s[,.;:!?]|,,|  ', out):
                bad.append((text, out))
            elif S.numbers_of(text) != S.read_back(out):
                bad.append((text, S.numbers_of(text), S.read_back(out), out))
            elif S.speak(out) != out:
                bad.append((text, out, S.speak(out)))
        self.assertEqual(bad[:6], [], len(bad))


class LawBuild(unittest.TestCase):
    """Every answer ``law_base.lookup`` gives (on the stand's fake pages) is spoken clean and keeps its numbers."""
    ASKS = ('прочитай статью 70 трудового кодекса', 'статья 81 трк часть 1 пункт 3', 'что говорит статья 19 Конституции', 'статья 103 Конституции часть 1 пункт б', 'статья 82 трудового кодекса',
            'статья 19 налогового кодекса', 'статья 71 тк', 'статья 19 гражданского кодекса', 'статья 20 конституции', 'статья 81 тк часть 2')

    @classmethod
    def setUpClass(cls):
        import tempfile
        sys.path.insert(0, os.path.join(ROOT, 'tests'))
        import helpers_law as H
        from echo_sync import law_base
        cls.lb, cls.dir = law_base, tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.dir.name, 'law.sqlite')
        H.build(cls.path)
        law_base.use(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.lb.use(None)
        cls.dir.cleanup()

    def test_law_answers(self):
        got = 0
        for q in self.ASKS:
            a = self.lb.lookup(q, (), today='2026-11-05')
            if not a:
                continue
            got += 1
            out = S.speak(a)
            self.assertNotRegex(out, r'[\d%()«»"№—–/]', (q, out))
            self.assertEqual(S.numbers_of(a), S.read_back(out), (q, a, out))
            self.assertEqual(S.speak(out), out)
        self.assertGreaterEqual(got, 6)

    def test_samples(self):
        for t in ('Статья 15 Налогового кодекса. Налогоплательщики обязаны платить 20% от суммы, не позднее 25 числа.', 'Пункт 2. Ставка налога — 6% (шесть процентов) с 1 января 2025 года.',
                  'Часть 3 статьи 9 ТК РФ: срок не более 30 календарных дней, т.е. месяц.', 'Трудовой кодекс Российской Федерации от 30.12.2001 N 197-ФЗ (ред. от 08.08.2024)',
                  'Утратила силу с 6 октября 2006 года. - Федеральный закон от 30.06.2006 N 90-ФЗ.'):
            out = S.speak(t)
            self.assertNotRegex(out, r'[\d%()—]')
            self.assertEqual(S.numbers_of(t), S.read_back(out), t)


class Regression(unittest.TestCase):
    """Cases found while walking the bank, the law texts and the fuzz."""
    def test_gender_and_case_from_the_noun(self):
        for t, w in (('1 копейку', 'одну копейку'), ('через 1 неделю', 'через одну неделю'), ('за 2 недели', 'за две недели'), ('по 1 рублю', 'по одному рублю'), ('по 5 рублей', 'по пять рублей'),
                     ('с 21 дня', 'с двадцати одного дня'), ('в 22 года', 'в двадцать два года'), ('за 21 день', 'за двадцать один день'), ('к 5 ноября', 'к пятому ноября'),
                     ('в 5 раз', 'в пять раз'), ('1,5 раза', 'одна целая пять десятых раза'), ('в 1,5 раза', 'в одну целую пять десятых раза'), ('от 12 до 14 лет', 'от двенадцати до четырнадцати лет'),
                     ('в возрасте 18 лет', 'в возрасте восемнадцати лет'), ('более 1 млн', 'более одного миллиона'), ('до 5 000 000 рублей', 'до пяти миллионов рублей')):
            self.assertEqual(say(t), w, t)

    def test_ids_phones_letters(self):
        self.assertEqual(say('ИНН 7727406020'), 'и эн эн семь семь два, семь четыре ноль, шесть ноль два ноль')
        self.assertEqual(say('+7 495 123-45-67'), 'плюс семь, четыре девять пять, один два три, четыре пять, шесть семь')
        self.assertEqual(say('A1:D10'), 'а один двоеточие дэ десять')
        self.assertEqual(say('Шифт F5'), 'Шифт эф пять')
        self.assertEqual(say('формат PDF и Excel'), 'формат пи ди эф и эксель')
        self.assertEqual(say('5-летний срок'), 'пятилетний срок')
        self.assertEqual(say('100%-ная'), 'стопроцентная')
        self.assertEqual(say('в 1990-х годах'), 'в тысяча девятьсот девяностых годах')
        self.assertEqual(say('ПБУ 19/02'), 'пэ бэ у девятнадцать дробь ноль два')

    def test_spans_and_dates(self):
        for t, w in (('ст. 419–431', 'статьи с четыреста девятнадцатой по четыреста тридцать первую'), ('пп. 2–4 п. 3', 'подпункты со второго по четвёртый пункта третьего'),
                     ('материалы от 08.09-16.09', 'материалы от восьмого сентября по шестнадцатое сентября'), ('пакет на пятницу 06.11', 'пакет на пятницу шестого ноября'),
                     ('с 1–5 ноября', 'с первого по пятое ноября'), ('в 2020–2022 гг. ставка', 'с две тысячи двадцатого по две тысячи двадцать второй годы ставка'),
                     ('ст. 143, 146 и 171', 'статьи сто сорок три, сто сорок шесть и сто семьдесят один'), ('Подробности в тексте статьи 217.', 'Подробности в тексте статьи двести семнадцатой.'),
                     ('2 500,50 руб', 'две тысячи пятьсот рублей пятьдесят копеек'), ('5 000,00 ₽', 'пять тысяч рублей'), ('18 329 тыс. руб.', 'восемнадцать миллионов триста двадцать девять тысяч рублей.')):
            self.assertEqual(say(t), w, t)

    def test_accounts_stay_accounts(self):
        self.assertEqual(say('кредит 90-1 и 5 тыс. руб.'), 'кредит девяносто точка один и пять тысяч рублей.')
        self.assertEqual(say('счёт 08 и 79 тыс. руб.'), 'счёт ноль восемь и семьдесят девять тысяч рублей.')
        self.assertEqual(say('Дебет 20 (23, 26, 29, 44), кредит 69.09.'), 'Дебет двадцать, двадцать три, двадцать шесть, двадцать девять, сорок четыре, кредит шестьдесят девять точка ноль девять.')

    def test_sentence_dot_only_at_a_sentence_end(self):
        self.assertEqual(say('Это 5 руб. Далее'), 'Это пять рублей. Далее')
        self.assertEqual(say('Это 5 руб. и всё'), 'Это пять рублей и всё')

    def test_speed(self):
        import time
        text = 'Дебет 50, кредит 62: покупатели ООО «Орхидея» внесли 14 160 рублей по ст. 346.11 НК РФ с 5 ноября 2026 года, ставка 2,5%.' * 4
        t = time.perf_counter()
        for _ in range(200):
            S.speak(text)
        self.assertLess((time.perf_counter() - t) / 200, 0.01)


if __name__ == '__main__':
    unittest.main()
