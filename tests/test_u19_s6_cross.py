"""U19-S6: cross-script equality in repeat_rule.verdict (flag CROSS_SCRIPT, default off)."""
import unittest
from echo_sync import repeat_rule as rr
from echo_sync import ru_alignment as ra

FIN = 'Что наводит financia'
XL = 'Ссылка в Excel'
CENT = 'Это было в XV веке'


class Cross(unittest.TestCase):
    def tearDown(self):
        rr.set_cross_script(False)
        ra.set_ranges(False)

    def test_off_by_default(self):
        self.assertFalse(rr.CROSS_SCRIPT)
        self.assertIsNone(rr.verdict('финансия', 'financia'))

    def test_next_when_on(self):
        rr.set_cross_script(True)
        self.assertEqual(rr.verdict('финансия', 'financia'), 'next')
        self.assertEqual(rr.verdict('ссылка в эксель', XL), 'next')
        self.assertEqual(rr.verdict('эксель', XL), 'next')

    def test_unlike_word_is_none(self):
        rr.set_cross_script(True)
        self.assertIsNone(rr.verdict('прапедлей', 'rapidly'))

    def test_numbers_and_ne_not_folded(self):
        rr.set_cross_script(True)
        self.assertIsNone(rr.verdict('в пятнадцатом веке', 'Это было в 16 веке'))
        self.assertIsNone(rr.verdict('это было не в веке', 'Это было в веке'))

    def test_century_unchanged(self):
        before = rr.verdict('пятнадцатый век', CENT)
        rr.set_cross_script(True)
        self.assertEqual(rr.verdict('пятнадцатый век', CENT), before)
        ra.set_ranges(True)
        a = rr.verdict('пятнадцатый век', CENT)
        rr.set_cross_script(False)
        self.assertEqual(rr.verdict('пятнадцатый век', CENT), a)


if __name__ == '__main__':
    unittest.main()
