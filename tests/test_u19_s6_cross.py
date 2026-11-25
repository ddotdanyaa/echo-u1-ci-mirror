"""U19-S6: cross-script equality in repeat_rule.verdict (always on: no switch)."""
import unittest
from echo_sync import repeat_rule as rr

FIN = 'Что наводит financia'
XL = 'Ссылка в Excel'


class Cross(unittest.TestCase):
    def test_next(self):
        self.assertEqual(rr.verdict('финансия', 'financia'), 'next')
        self.assertEqual(rr.verdict('ссылка в эксель', XL), 'next')
        self.assertEqual(rr.verdict('эксель', XL), 'next')

    def test_unlike_word_is_none(self):
        self.assertIsNone(rr.verdict('прапедлей', 'rapidly'))

    def test_numbers_and_ne_not_folded(self):
        self.assertIsNone(rr.verdict('в пятнадцатом веке', 'Это было в 16 веке'))
        self.assertIsNone(rr.verdict('это было не в веке', 'Это было в веке'))


if __name__ == '__main__':
    unittest.main()
