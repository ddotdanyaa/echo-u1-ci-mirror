"""Seeded random checks of the portioner: old 3-word chunks for plain text, and invariants for everything else."""
import random
import unittest

try:
    from echo_sync.portioner import expand_abbreviations, portions, syllables
    from echo_sync.settings import resolve
    from echo_sync.textutil import CONDUIT_LOCAL_PHRASES, FUNCTION_WORDS, WORDS, normalize
except ImportError:
    portions = None


def legacy_chunks(answer):
    """The engine's chunking before the portioner existed (3 Unicode words, punctuation preserved)."""
    answer = str(answer)
    words = list(WORDS.finditer(answer))
    return [answer[0 if i == 0 else words[i].start():words[i + 3].start() if i + 3 < len(words) else len(answer)].strip()
            for i in range(0, len(words), 3)]


CONTENT = ('дом лес река город машина человек компания система деньги работа вода воздух книга учитель ученик красивый '
           'большой новый старый быстрый важный простой сложный основной главный создаёт показывает находится работает '
           'использует проверяет объясняет получается образуются электроэнцефалография взаимосвязанных распределяются '
           'предприятий организаций государства Москва Россия Иванов Пушкин Конституция').split()
FUNCTION = sorted(FUNCTION_WORDS)
EXTRA = ['2026', '15', '228', '6,5', '1 500', '2,3 млн', '15 %', 'А. С. Пушкин', 'Иванов И. И.', 'УК РФ', 'ВВП', 'ЦБ',
         'и т. д.', 'в течение года', 'в 2026 году', 'статья 228', 'пункт 3', 'кто-то', 'по-русски', 'Стоп', 'Тише', 'Пока',
         'До свидания', 'Это всё', 'Хватит', 'Замолчи', 'Закончить разговор', '№ 5', '$100', '«кавычки»']
SEPARATORS = [' ', ' ', ' ', ', ', ', ', '. ', '; ', ': ', ' — ', '! ', '? ', '… ', ' (', ') ', '\n', '  ', ' «', '» ']


def random_text(rng, count, plain=False):
    parts = []
    for _ in range(count):
        roll = rng.random()
        if plain or roll < 0.55:
            word = rng.choice(CONTENT)
        elif roll < 0.85:
            word = rng.choice(FUNCTION)
        else:
            word = rng.choice(EXTRA)
        if word in CONTENT or word in FUNCTION:
            word = word.capitalize() if rng.random() < 0.1 else word
        parts += [word, rng.choice(SEPARATORS[:8] if plain else SEPARATORS)]
    return ''.join(parts).strip()


class PropertyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(portions, 'Portioner has not been implemented')

    def test_words_mode_equals_the_legacy_chunks_for_plain_text(self):
        rng = random.Random(20261021)
        for _ in range(400):
            text = random_text(rng, rng.randint(1, 40), plain=True).replace('\n', ' ').replace('  ', ' ')
            self.assertEqual(portions(text, {'portion_mode': 'words'}), [' '.join(p.split()) for p in legacy_chunks(text)], text)

    def test_invariants_hold_for_any_text_and_settings(self):
        rng = random.Random(1021)
        table = {'ВВП': 'валовой внутренний продукт', 'УК РФ': 'Уголовный кодекс Российской Федерации', 'ЦБ': 'Центральный банк'}
        for _ in range(500):
            text = random_text(rng, rng.randint(1, 50))
            settings = {'portion_mode': rng.choice(['words', 'syllables']), 'words_per_portion': rng.randint(1, 6),
                        'target_syllables': rng.randint(2, 14), 'max_syllables': rng.randint(3, 20),
                        'max_words': rng.randint(1, 7), 'min_words': rng.randint(1, 3), 'long_word_syllables': rng.randint(2, 8)}
            if rng.random() < 0.3:
                settings['abbreviations'] = table
            result = portions(text, settings)
            self.assertEqual(result, portions(text, settings), 'portions must be deterministic')
            expanded = expand_abbreviations(text, resolve(settings)['abbreviations'])
            if not result:
                # Only an answer that is nothing but a phone command (or has no words) may be dropped.
                self.assertIn(normalize(expanded), CONDUIT_LOCAL_PHRASES | {''}, (text, settings))
                continue
            self.assertEqual(' '.join(normalize(p) for p in result), normalize(expanded), (text, settings))
            for portion in result:
                self.assertTrue(normalize(portion), (text, settings, portion))
                self.assertNotIn(normalize(portion), CONDUIT_LOCAL_PHRASES, (text, settings, portion))
                self.assertEqual(portion, ' '.join(portion.split()), 'whitespace must be collapsed')
            for portion in result[:-1]:
                last = normalize(portion).split()[-1]
                # «Иванов И. И.,»: an initial («И.») is a letter of a name, not the conjunction «и»
                self.assertFalse(last in FUNCTION_WORDS and not portion.rstrip(',;:)»”').endswith(('.', '!', '?', '…'))
                                 and not last.isdigit(), (text, settings, portion))

    def test_syllable_limits_hold_unless_a_single_indivisible_block_is_longer(self):
        rng = random.Random(77)
        for _ in range(300):
            text = random_text(rng, rng.randint(1, 50), plain=True)
            settings = {'portion_mode': 'syllables', 'target_syllables': rng.randint(2, 12), 'max_syllables': rng.randint(8, 20),
                        'max_words': rng.randint(1, 6)}
            for portion in portions(text, settings):
                words = len(normalize(portion).split())
                # Plain words only: every word is its own block, so the limits are strict unless one word alone is longer.
                self.assertTrue(words <= settings['max_words'] and syllables(portion) <= settings['max_syllables'] or words == 1,
                                (text, settings, portion))


if __name__ == '__main__':
    unittest.main()
