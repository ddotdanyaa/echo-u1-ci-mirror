"""U16-S5: repeat verdict and dictation written_to read a range said as its two ends"""
import unittest
from echo_sync import repeat_rule as rr

CUE = 'Это было в XIII–XV веках'
LONG = 'Это было в XIII–XV веках, когда город рос'


class RangesOn(unittest.TestCase):
    def test_range_said_as_ends_is_next(self):
        self.assertEqual(rr.verdict('в тринадцатом по пятнадцатом веках', CUE), 'next')

    def test_range_end_ordinal_form_is_next(self):
        self.assertEqual(rr.verdict('по пятнадцатый век', CUE), 'next')

    def test_other_century_is_none(self):
        self.assertIsNone(rr.verdict('в тринадцатом по шестнадцатый век', CUE))
        self.assertIsNone(rr.verdict('шестнадцатый век', CUE))

    def test_plain_veka_still_next(self):
        self.assertEqual(rr.verdict('в тринадцатом по пятнадцатом века', CUE), 'next')

    def test_written_to_reads_range(self):
        got = rr.written_to('это было в тринадцатом по пятнадцатом веках', LONG)
        self.assertIsNotNone(got)
        self.assertTrue(got.startswith('когда'), got)


if __name__ == '__main__':
    unittest.main()
