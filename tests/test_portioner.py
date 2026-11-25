"""Answer -> spoken portions: legacy 3-word mode and the syllable mode."""
import itertools
import unittest

try:
    from echo_sync.portioner import portions, syllables
    from echo_sync.engine import normalize
except ImportError:
    portions = syllables = normalize = None

SYL = {'portion_mode': 'syllables'}

SAMPLES = [
    'Финансовая система Российской Федерации представляет собой совокупность взаимосвязанных сфер финансовых '
    'отношений, в которых образуются, распределяются и используются денежные фонды государства, предприятий и населения.',
    'Фотосинтез — это процесс, в котором растения, водоросли и некоторые бактерии превращают световую энергию '
    'в химическую энергию органических веществ. Он протекает в хлоропластах при участии хлорофилла.',
    'Статья 228 УК РФ предусматривает ответственность за незаконные приобретение, хранение, перевозку, изготовление '
    'и переработку наркотических средств без цели сбыта в значительном размере.',
    'В 2026 году доходы компании выросли на 15 %, а расходы сократились на 6,5 %. Чистая прибыль составила '
    '2,3 млн рублей, и это на 15 % больше, чем годом ранее.',
    'Электроэнцефалография — метод регистрации электрической активности головного мозга с помощью электродов, '
    'которые закрепляют на поверхности головы. Метод применяют при диагностике эпилепсии и нарушений сна.',
    'Это зависит от того, что в системе работает не так, как задумано, и поэтому нужно по возможности проверить '
    'все данные, а также убедиться, что на входе нет ошибок.',
]

# Independent of the implementation's own list on purpose.
DANGLING = {'в', 'на', 'и', 'а', 'но', 'с', 'со', 'по', 'к', 'о', 'от', 'из', 'за', 'для', 'не', 'ни', 'что', 'как',
            'бы', 'ли', 'же', 'при', 'до', 'у', 'или', 'чтобы', 'если'}


def words(text):
    return normalize(text).split()


def ends_dangling(portion):
    last = words(portion)[-1]
    return last in DANGLING and not portion.rstrip().endswith(('.', '!', '?', '…'))


class PortionerCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(portions, 'Portioner has not been implemented')


class WordsModeTests(PortionerCase):
    def test_default_is_the_legacy_three_word_portions(self):
        answer = 'Первый второй третий, четвёртый пятый шестой. Седьмой восьмой.'
        expected = ['Первый второй третий,', 'четвёртый пятый шестой.', 'Седьмой восьмой.']
        self.assertEqual(portions(answer), expected)
        self.assertEqual(portions(answer, {'portion_mode': 'words'}), expected)
        self.assertEqual(portions(answer, {'portion_mode': 'words', 'words_per_portion': 3}), expected)

    def test_word_count_is_configurable(self):
        answer = 'Один два три четыре пять шесть семь'
        self.assertEqual(portions(answer, {'words_per_portion': 2}), ['Один два', 'три четыре', 'пять шесть', 'семь'])
        self.assertEqual(portions(answer, {'words_per_portion': 4}), ['Один два три четыре', 'пять шесть семь'])
        self.assertEqual(portions(answer, {'words_per_portion': 1}), answer.split())

    def test_standalone_dash_does_not_consume_a_word_slot(self):
        self.assertEqual(portions('Доходы — это деньги, полученные нашей компанией.'),
                         ['Доходы — это деньги,', 'полученные нашей компанией.'])

    def test_a_portion_never_ends_on_a_preposition_conjunction_or_particle(self):
        self.assertEqual(portions('Это зависит от того, что в системе'), ['Это зависит', 'от того,', 'что в системе'])
        for answer, size in itertools.product(SAMPLES, (1, 2, 3, 4, 5, 6)):
            for portion in portions(answer, {'words_per_portion': size}):
                self.assertFalse(ends_dangling(portion), (size, portion))

    def test_function_words_chain_extends_instead_of_leaving_a_dangling_tail(self):
        result = portions('Он молчал и в то же время думал', {'words_per_portion': 3})
        self.assertEqual(result, ['Он молчал', 'и в то же время', 'думал'])

    def test_a_function_word_before_a_sentence_end_is_left_alone(self):
        self.assertEqual(portions('Мы пошли домой и. Потом сели', {'words_per_portion': 4}), ['Мы пошли домой и.', 'Потом сели'])

    def test_decimal_numbers_are_not_split(self):
        for size in (1, 2, 3):
            result = portions('Доля составила 6,5 процента от всех расходов', {'words_per_portion': size})
            self.assertTrue(any('6,5' in p for p in result), (size, result))

    def test_no_word_is_lost_or_reordered(self):
        for answer, size in itertools.product(SAMPLES, (1, 2, 3, 4, 6)):
            joined = ' '.join(normalize(p) for p in portions(answer, {'words_per_portion': size}))
            self.assertEqual(joined, normalize(answer))


class SyllableCountTests(PortionerCase):
    def test_russian_syllables_are_vowels(self):
        self.assertEqual(syllables('Первый'), 2)
        self.assertEqual(syllables('Он'), 1)
        self.assertEqual(syllables('электроэнцефалография'), 10)
        self.assertEqual(syllables('Фотосинтез позволяет'), 4 + 4)
        self.assertEqual(syllables('ёжик'), 2)
        self.assertEqual(syllables(''), 0)
        self.assertEqual(syllables('— , .'), 0)

    def test_all_caps_abbreviations_are_spelled_out(self):
        self.assertEqual(syllables('ВВП'), 3)
        self.assertEqual(syllables('УК РФ'), 4)
        self.assertEqual(syllables('НАТО'), 2)

    def test_digits_are_a_rough_but_stable_estimate(self):
        self.assertEqual(syllables('15'), syllables('99'))
        self.assertGreater(syllables('2026'), syllables('228'))
        self.assertGreater(syllables('228'), syllables('15'))
        self.assertGreaterEqual(syllables('5'), 1)

    def test_percent_sign_is_spoken(self):
        self.assertGreater(syllables('15 %'), syllables('15'))


class SyllableModeTests(PortionerCase):
    def test_limits_hold_for_ordinary_text(self):
        for answer in SAMPLES:
            result = portions(answer, SYL)
            for portion in result:
                self.assertLessEqual(syllables(portion), 12, portion)
                self.assertLessEqual(len(words(portion)), 5, portion)
            self.assertGreater(len(result), 1)

    def test_limits_follow_the_settings(self):
        plain = 'Красивый старый деревянный дом давно стоит тихо зимой весной летом осенью'
        for max_words in (1, 2, 3, 4):
            for portion in portions(plain, {**SYL, 'target_syllables': 6, 'max_syllables': 8, 'max_words': max_words}):
                self.assertLessEqual(len(words(portion)), max_words, portion)
                self.assertLessEqual(syllables(portion), 8, portion)
        wide = portions(plain, {**SYL, 'target_syllables': 12, 'max_syllables': 16, 'max_words': 6})
        self.assertTrue(any(len(words(p)) >= 4 for p in wide), wide)

    def test_portions_vary_in_length_and_follow_the_target(self):
        result = portions(SAMPLES[0], SYL)
        counts = [syllables(p) for p in result]
        self.assertGreater(len(set(counts)), 1)
        average = sum(counts[:-1]) / (len(counts) - 1)
        self.assertTrue(6 <= average <= 10, counts)

    def test_never_ends_on_a_function_word(self):
        for answer in SAMPLES:
            for target in (3, 4, 6, 8, 10, 12):
                settings = {**SYL, 'target_syllables': target, 'max_syllables': max(target, 12)}
                for portion in portions(answer, settings):
                    self.assertFalse(ends_dangling(portion), (target, portion))

    def test_acknowledgement_text_is_the_answer_text(self):
        for answer in SAMPLES:
            for settings in (SYL, {**SYL, 'target_syllables': 4}, {**SYL, 'target_syllables': 11, 'max_syllables': 14, 'max_words': 6}):
                self.assertEqual(' '.join(normalize(p) for p in portions(answer, settings)), normalize(answer))

    def test_one_long_word_may_stand_alone_even_when_two_words_are_the_minimum(self):
        result = portions('Электроэнцефалография регистрирует активность', {**SYL, 'min_words': 2})
        self.assertEqual(result, ['Электроэнцефалография', 'регистрирует активность'])
        # A short word is not allowed to stand alone when min_words=2.
        for portion in portions('Да, конечно, так и есть, это важно знать.', {**SYL, 'min_words': 2}):
            self.assertGreaterEqual(len(words(portion)), 2, portion)

    def test_long_word_threshold_is_configurable(self):
        text = 'Взаимосвязанных сфер'
        self.assertEqual(portions(text, {**SYL, 'min_words': 2, 'long_word_syllables': 6, 'target_syllables': 4, 'max_syllables': 6}),
                         ['Взаимосвязанных', 'сфер'])
        self.assertEqual(portions(text, {**SYL, 'min_words': 2, 'long_word_syllables': 7, 'target_syllables': 4, 'max_syllables': 12}),
                         ['Взаимосвязанных сфер'])

    def test_a_word_longer_than_the_maximum_is_still_one_portion(self):
        word = 'сверхъестественноэлектромагнитнокосмический'
        result = portions(f'Это {word} явление', {**SYL, 'max_syllables': 8, 'target_syllables': 6})
        self.assertIn(word, [p.strip(' ,.') for p in result])

    def test_min_words_one_allows_single_word_sentences(self):
        self.assertEqual(portions('Да.', SYL), ['Да.'])
        self.assertEqual(portions('Нет. Нет. Нет.', {**SYL, 'target_syllables': 1, 'max_syllables': 2}), ['Нет.', 'Нет.', 'Нет.'])

    def test_cuts_prefer_punctuation(self):
        # Every word has two syllables, so only the comma decides where the cut falls.
        self.assertEqual(portions('Мама мыла раму, папа пилил дрова дети', SYL), ['Мама мыла раму,', 'папа пилил дрова дети'])
        self.assertEqual(portions('Мама мыла раму папа, пилил дрова дети', SYL), ['Мама мыла раму папа,', 'пилил дрова дети'])
        self.assertEqual(portions('Мама мыла раму, папа пилил дрова, дети ели кашу.', SYL),
                         ['Мама мыла раму,', 'папа пилил дрова,', 'дети ели кашу.'])

    def test_sentence_ends_make_cuts(self):
        self.assertEqual(portions('Мама мыла раму. Папа пилил дрова. Дети ели кашу.', SYL),
                         ['Мама мыла раму.', 'Папа пилил дрова.', 'Дети ели кашу.'])

    def test_tiny_sentences_are_merged_instead_of_spoken_one_by_one(self):
        self.assertEqual(portions('Да. Нет. Возможно.', SYL), ['Да. Нет. Возможно.'])


class UnitTests(PortionerCase):
    PRESSURE = {**SYL, 'target_syllables': 3, 'max_syllables': 4, 'max_words': 2}

    def portion_with(self, text, needle, settings=None):
        result = portions(text, settings or self.PRESSURE)
        found = [p for p in result if needle in p]
        self.assertEqual(len(found), 1, (needle, result))
        return found[0]

    def test_number_and_unit_stay_together(self):
        self.assertIn('2026 году', self.portion_with('Это случилось в 2026 году после долгих споров', '2026'))
        self.assertIn('5 лет', self.portion_with('Срок составляет 5 лет и более для всех', '5 лет'))
        self.assertIn('15 %', self.portion_with('Выручка выросла на 15 % по сравнению с прошлым', '15 %'))
        self.assertIn('3 кг', self.portion_with('Вес груза равен 3 кг при перевозке', '3 кг'))

    def test_scale_words_stay_with_their_number(self):
        text = 'Прибыль составила 2,3 млн рублей за этот период'
        self.assertIn('2,3 млн рублей', self.portion_with(text, '2,3'))

    def test_label_and_number_stay_together(self):
        self.assertIn('Статья 228', self.portion_with('Статья 228 предусматривает ответственность', 'Статья'))
        self.assertIn('пункт 3', self.portion_with('Смотрите пункт 3 настоящего договора', 'пункт'))

    def test_adjacent_abbreviations_stay_together(self):
        self.assertIn('УК РФ', self.portion_with('Статья 228 УК РФ предусматривает ответственность', 'УК'))

    def test_initials_stay_with_the_surname(self):
        self.assertIn('А. С. Пушкин', self.portion_with('Это стихотворение написал А. С. Пушкин в юности', 'Пушкин'))
        self.assertIn('Иванов И. И.', self.portion_with('Подписал приказ Иванов И. И. в понедельник', 'Иванов'))

    def test_abbreviation_with_a_period_is_one_unit(self):
        self.assertIn('и т. д.', self.portion_with('Берут яблоки, груши и т. д. в большом количестве', 'т.'))

    def test_decimal_and_grouped_numbers_are_not_split(self):
        self.assertIn('6,5', self.portion_with('Доля составила 6,5 процента от всех расходов', '6,5'))
        self.assertIn('1 500', self.portion_with('Цена равна 1 500 рублей без скидки', '1 500'))

    def test_prepositional_phrases_do_not_leave_a_half_phrase(self):
        for text in ('Это длилось в течение года без перерыва', 'Он сделал это в связи с болезнью матери', 'Мы поступили так в целях безопасности всех'):
            for portion in portions(text, {**SYL, 'target_syllables': 4, 'max_syllables': 6}):
                self.assertFalse(portion.split()[-1].strip(',.') in {'течение', 'связи', 'целях', 'с', 'в'}, (text, portion))

    def test_opening_quote_travels_with_the_next_word(self):
        self.assertEqual(portions('Он сказал «привет» всем', {'words_per_portion': 2}), ['Он сказал', '«привет» всем'])


class AbbreviationTests(PortionerCase):
    def test_default_dictionary_is_empty(self):
        self.assertEqual(portions('ВВП растёт. Рост ВВП важен.', {'words_per_portion': 10}), ['ВВП растёт. Рост ВВП важен.'])

    def test_only_the_first_occurrence_is_expanded(self):
        settings = {'words_per_portion': 30, 'abbreviations': {'ВВП': 'валовой внутренний продукт'}}
        self.assertEqual(portions('ВВП растёт. Рост ВВП важен.', settings),
                         ['валовой внутренний продукт растёт. Рост ВВП важен.'])

    def test_expansion_changes_the_spoken_text_for_acknowledgement(self):
        settings = {**SYL, 'abbreviations': {'ВВП': 'валовой внутренний продукт'}}
        spoken = ' '.join(normalize(p) for p in portions('ВВП растёт быстро. Рост ВВП важен.', settings))
        self.assertEqual(spoken, 'валовой внутренний продукт растет быстро рост ввп важен')

    def test_several_and_multiword_abbreviations(self):
        settings = {'words_per_portion': 30, 'abbreviations': {'УК РФ': 'Уголовный кодекс Российской Федерации', 'ЦБ': 'Центральный банк'}}
        self.assertEqual(portions('Статья 228 УК РФ. ЦБ следит. Ещё раз УК РФ и ЦБ.', settings),
                         ['Статья 228 Уголовный кодекс Российской Федерации. Центральный банк следит. Ещё раз УК РФ и ЦБ.'])

    def test_an_expanded_term_is_never_cut_in_half(self):
        table = {'ЦБ': 'Центральный банк', 'ВВП': 'валовой внутренний продукт', 'УК РФ': 'Уголовный кодекс Российской Федерации'}
        text = 'Рост ВВП говорит о расширении экономики, а ЦБ следит за ценами. Статья 228 УК РФ предусматривает ответственность.'
        for size in (1, 2, 3, 4):
            result = portions(text, {'words_per_portion': size, 'abbreviations': table})
            for term in table.values():
                self.assertEqual(sum(term in p for p in result), 1, (size, term, result))
        for target in (3, 4, 6, 8, 12):
            result = portions(text, {**SYL, 'target_syllables': target, 'max_syllables': max(12, target), 'abbreviations': table})
            for term in table.values():
                self.assertEqual(sum(term in p for p in result), 1, (target, term, result))

    def test_term_already_spelled_out_is_not_repeated(self):
        settings = {'words_per_portion': 30, 'abbreviations': {'ВВП': 'валовой внутренний продукт'}}
        text = 'Валовой внутренний продукт (ВВП) растёт, а ВВП важен.'
        self.assertEqual(portions(text, settings), [text])

    def test_abbreviation_inside_a_longer_word_is_not_touched(self):
        settings = {'words_per_portion': 30, 'abbreviations': {'ВВП': 'валовой внутренний продукт'}}
        self.assertEqual(portions('ВВП-дефлятор и НЕВВП', settings), ['ВВП-дефлятор и НЕВВП'])


PHONE_COMMANDS = ['стоп', 'хватит', 'замолчи', 'тише', 'пока', 'до свидания', 'закончить разговор', 'это всё']


class PhoneCommandTests(PortionerCase):
    """Conduit handles these WHOLE utterances locally (End closes the voice session) and never sends them."""

    def assert_clean(self, text, settings):
        result = portions(text, settings)
        for portion in result:
            self.assertNotIn(normalize(portion), {normalize(p) for p in PHONE_COMMANDS}, (settings, portion))
        return result

    def test_a_portion_equal_to_stop_or_end_is_merged_with_its_neighbour(self):
        two = {'words_per_portion': 2}
        self.assertEqual(portions('Закончить разговор. Спасибо вам.', two), ['Закончить разговор. Спасибо вам.'])
        self.assertEqual(portions('Спасибо вам. Это всё.', two), ['Спасибо вам. Это всё.'])
        self.assertEqual(portions('Спасибо вам. До свидания.', two), ['Спасибо вам. До свидания.'])
        self.assertEqual(portions('Хватит. Достаточно, спасибо.', {'words_per_portion': 1}), ['Хватит. Достаточно,', 'спасибо.'])

    def test_the_neighbour_across_the_weaker_punctuation_is_chosen(self):
        one = {'words_per_portion': 1}
        self.assertEqual(portions('Один два. Стоп. Три четыре.', one), ['Один', 'два.', 'Стоп. Три', 'четыре.'])
        self.assertEqual(portions('Мы идём домой. Тише, а потом спим.', one), ['Мы', 'идём', 'домой.', 'Тише, а потом', 'спим.'])
        self.assertEqual(portions('Мы идём домой, тише. А потом спим.', one), ['Мы', 'идём', 'домой, тише.', 'А потом', 'спим.'])

    def test_every_phrase_in_every_position_and_mode(self):
        modes = [{'words_per_portion': n} for n in (1, 2, 3)] + [SYL, {**SYL, 'target_syllables': 2, 'max_syllables': 4, 'max_words': 2}]
        for phrase in PHONE_COMMANDS:
            spoken = phrase[:1].upper() + phrase[1:]
            for template in ('{p}. Мы продолжаем работу над задачей.', 'Мы начинаем работу над задачей. {p}. Потом продолжаем.',
                             'Мы закончили работу над задачей. {p}.', 'Мы закончили, {p}, и разошлись по домам.'):
                text = template.format(p=spoken)
                for settings in modes:
                    result = self.assert_clean(text, settings)
                    self.assertEqual(' '.join(normalize(p) for p in result), normalize(text), (text, settings))

    def test_ordinary_answers_never_contain_such_a_portion(self):
        for answer in SAMPLES:
            for settings in ({}, SYL, {'words_per_portion': 1}, {**SYL, 'target_syllables': 2, 'max_syllables': 3, 'max_words': 1}):
                self.assertTrue(self.assert_clean(answer, settings))

    def test_an_answer_that_is_only_such_a_phrase_is_not_spoken_at_all(self):
        for phrase in PHONE_COMMANDS:
            for settings in ({}, SYL, {'words_per_portion': 5}):
                self.assertEqual(portions(phrase.capitalize() + '!', settings), [], (phrase, settings))
        # One word per portion: a one-word command is the whole portion, a two-word one is two separate portions.
        self.assertEqual(portions('Стоп!', {'words_per_portion': 1}), [])
        self.assertEqual(portions('Закончить разговор!', {'words_per_portion': 1}), ['Закончить', 'разговор!'])

    def test_the_phrases_are_only_forbidden_as_a_whole_portion(self):
        self.assertEqual(portions('Пока не поздно', {'words_per_portion': 5}), ['Пока не поздно'])
        self.assertEqual(portions('Хватит ли денег?', {'words_per_portion': 3}), ['Хватит ли денег?'])


class EdgeCaseTests(PortionerCase):
    def test_empty_and_wordless_answers_have_no_portions(self):
        for answer in ('', None, '   ', '...', '— , .', '\n'):
            self.assertEqual(portions(answer), [])
            self.assertEqual(portions(answer, SYL), [])

    def test_single_word_and_missing_final_punctuation(self):
        self.assertEqual(portions('Бюджет'), ['Бюджет'])
        self.assertEqual(portions('Бюджет', SYL), ['Бюджет'])

    def test_whitespace_is_collapsed_inside_a_portion(self):
        self.assertEqual(portions('Первый\n\nвторой   третий\tчетвёртый'), ['Первый второй третий', 'четвёртый'])

    def test_unknown_mode_falls_back_to_words(self):
        self.assertEqual(portions('Один два три четыре', {'portion_mode': 'nonsense'}), ['Один два три', 'четыре'])

    def test_result_is_deterministic(self):
        for answer in SAMPLES:
            self.assertEqual(portions(answer, SYL), portions(answer, SYL))

    def test_long_answers_are_handled_quickly(self):
        import time
        started = time.time()
        result = portions(' '.join(SAMPLES * 60), SYL)
        self.assertGreater(len(result), 300)
        self.assertLess(time.time() - started, 5)


if __name__ == '__main__':
    unittest.main()
