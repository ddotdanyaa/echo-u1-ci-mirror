"""U16-S2: range atoms in ru_alignment, (always on: no switch)."""
import unittest
from echo_sync import ru_alignment as ra


def atoms(text):
    return [a.atom for a in ra._atoms(text)]


class RangesOn(unittest.TestCase):
    def test_canonical_table(self):
        table = [
            ('в XIII–XV веках', ['в', '#ord:13', '~', '#ord:15', 'век']),
            ('в XIII-XV веках', ['в', '#ord:13', '~', '#ord:15', 'век']),
            ('в 13–15 веках', ['в', '#ord:13', '~', '#ord:15', 'век']),
            ('в 1941–1945 годах', ['в', '#ord:1941', '~', '#ord:1945', 'год']),
            ('в 1941-1945 годах', ['в', '#ord:1941', '~', '#ord:1945', 'год']),
            ('3-4 дня', ['#3', '~', '#4', 'день']),
            ('5–7', ['#5', '~', '#7']),
            ('в XIII веке', ['в', '#ord:13', 'век']),            # single numbers are untouched
            ('36,6', ['#36.6']),
        ]
        for text, want in table:
            with self.subTest(text=text):
                self.assertEqual(atoms(text), want)

    def test_not_a_range(self):
        self.assertEqual(atoms('x-y'), atoms('x-y'))
        self.assertNotIn('~', atoms('XIII–7 веках'))        # mixed kinds
        self.assertNotIn('~', atoms('Иван-Петр'))
        self.assertNotIn('~', atoms('сорок-пятьдесят'))
        self.assertNotIn('#ord:50', atoms('в 10–50 веках'))  # 50 is not a century: stays a plain count

    def test_range_atom_is_protected(self):
        self.assertEqual([a.kind for a in ra._atoms('13–15 веках')][:3], ['n', 'p', 'n'])

    def test_adjacent_romans(self):
        from echo_sync.ru_numbers import Item
        items = [Item('roman', (13, 'xiii'), 'xiii'), Item('lit', '~', '–'), Item('roman', (15, 'xv'), 'xv')]
        self.assertTrue(ra._adjacent_romans(items, 0))
        self.assertFalse(ra._adjacent_romans(items, 2))


class SpokenRanges(unittest.TestCase):
    """U16-S3: a range said as its two ends is the range written; hook in match_current."""
    def test_full_readings_ack(self):
        for heard in ['в тринадцатом по пятнадцатом веках', 'в тринадцатом по пятнадцатый века',
                      'в XIII–XV веках']:
            with self.subTest(heard=heard):
                self.assertEqual(ra.match_current(heard, 'в XIII–XV веках'), 'ack')
        self.assertEqual(ra.match_current('с тринадцатого по пятнадцатый века', 'с XIII–XV веках'), 'ack')
        self.assertEqual(ra.match_current('с тринадцатого по пятнадцатый века', 'в XIII–XV веках'), 'attempt')  # «с» is not «в»: not a hit

    def test_one_end_or_wrong_value_is_not_ack(self):
        self.assertIsNone(ra.match_current('шестнадцатом', 'в XIII–XV веках'))
        self.assertNotEqual(ra.match_current('в тринадцатом по шестнадцатом веках', 'в XIII–XV веках'), 'ack')

    def test_years_ack(self):
        self.assertEqual(ra.match_current('1941–1945', '1941–1945'), 'ack')
        self.assertEqual(ra.match_current('в тысяча девятьсот сорок первом по тысяча девятьсот сорок пятом годах', 'в 1941–1945 годах'), 'ack')
        self.assertNotEqual(ra.match_current('с тысяча девятьсот сорок первого по тысяча девятьсот сорок шестой годы', 'в 1941–1945 годах'), 'ack')

    def test_counts(self):
        self.assertEqual(ra.match_current('с пяти до семи', '5–7'), 'ack')

    def test_spoken_as_written_text(self):
        self.assertEqual(ra.spoken_as_written('в тринадцатом по пятнадцатом веках', 'в XIII–XV веках'), 'в xiii–xv веках')
        self.assertEqual(ra.spoken_as_written('в тринадцатом веке', 'в XIII–XV веках'), 'в тринадцатом веке')

    def test_unit_start(self):
        t = 'в XIII–XV веках'
        self.assertEqual(ra.unit_start(t, 7), 2)
        self.assertEqual(ra.unit_start(t, 2), 2)
        self.assertEqual(ra.unit_start(t, 10), 10)
        self.assertEqual(ra.unit_start('в 1941–1945 годах', 6), 2)


if __name__ == '__main__':
    unittest.main()
